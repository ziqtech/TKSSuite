# -*- coding: utf-8 -*-
"""tkitem_expand 战斗图标取帧修正 (tkitem_expand.battle_icon) 的构建与执行级验证。

覆盖:
  1. icon_cave.py 生成的机器码与 icon.json 的 cave_code 字节级一致 (含 hook 字段)。
  2. 机器码结构: 载入 Mu.JVG -> 全量加载 -> 帧表 -130 -> 状态次序还原 -> 状态基准 112
     -> 重放被替换指令。
  3. unicorn 执行级: 用桩函数替换 sub_453BD0 / sub_45410C, 验证三条路径
     (载入成功 / 载入失败 / 对象未载入) 的字段、表项、全局字、寄存器与栈平衡;
     载入成功路径只交换帧表下标 252/253 两条, 其余表项保持不变。
  4. 计划门控: 只有物品表实际使用 >75 图标值且 Mu.JVG 存在时才注入图标操作。
  5. 真实 exe: hook pattern 全 .text 唯一, 且 hook_size 恰好覆盖一条可重放指令;
     validate_runtime_plan 通过。
  6. 真实 JVG 数据: Mu2 帧 0..75 == Mu 帧 130..205 (物品图标); 状态图标 Mu2 76..106
     与 Mu 242..272 仅 11/12 次序相反; MOD 追加帧的扩展图标值在重定位后可解析。
"""
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tks_launcher_gui"
PATCH_DIR = LAUNCHER / "patches" / "tkitem_expand"
GAME_DIR = Path(os.environ.get("TKS_GAME_DIR", r"游戏目录（原版）"))
for _p in (str(ROOT), str(LAUNCHER), str(PATCH_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import icon_cave  # noqa: E402   (patches/tkitem_expand/icon_cave.py)
from core.patch_plan import build_patch_plan, validate_runtime_plan  # noqa: E402
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from editor_utils.lzss import lzss_compress_dat  # noqa: E402

TEXT_BASE = 0x401000
DATA_BASE = 0x00500000          # 桩函数/字符串/伪造对象所在页
MUDATA_BASE = 0x00A00000        # 0x9D6F76 等战斗全局所在页
CAVE_BASE = 0x70000000
STACK_BASE = 0x7FF00000
RETURN_ADDR = 0x00430000        # 模拟 E8 返回地址 (hook 点之后)
HOOK_REPLAY_ADDR = 0x00755AF8
OBJ_ADDR = 0x00501000
STUB_LOAD_JVG = 0x00453BD0
STUB_LOAD_ALL = 0x0045410C
FRAME_TOTAL = 764               # 模拟 MOD Mu.JVG 的总帧数
TABLE_BLOCK = 0x00600000        # 帧→块表 (帧→子帧表 = +0x10000)
TABLE_SF = 0x00610000
MU2_FRAME_TOTAL = 107           # 原版 Mu2.JVG 总帧数 (物品 0..75 + 状态 76..106)


def _load_icon_op():
    with open(PATCH_DIR / "icon.json", encoding="utf-8") as stream:
        return json.load(stream)


class IconCaveBuildTests(unittest.TestCase):
    """机器码与 icon.json 的一致性和结构断言。"""

    def test_cave_matches_operation(self):
        op = _load_icon_op()
        self.assertEqual(op["cave_code"], icon_cave.cave_code_hex())
        self.assertEqual(op["type"], "cave_hook")
        self.assertEqual(op["id"], "tkitem_expand.battle_icon")
        self.assertEqual(op["hook_pattern"], icon_cave.HOOK_PATTERN)
        self.assertEqual(op["hook_offset"], icon_cave.HOOK_OFFSET)
        self.assertEqual(op["hook_size"], icon_cave.HOOK_SIZE)
        self.assertEqual(op["hook_expect_count"], 1)

    def test_cave_structure(self):
        code = icon_cave.build_cave()
        self.assertEqual(code[0], 0x60)                  # pushad
        self.assertEqual(code[1], 0xFC)                  # cld
        self.assertEqual(code[-8:],
                         bytes.fromhex("61 8B 15 F8 5A 75 00 C3".replace(" ", "")),
                         "结尾必须是 popad + 重放 + ret")
        # 载入器: mov eax, imm32; call eax (间接调用, 不依赖 cave 自身地址)
        for target in (icon_cave.LOAD_JVG, icon_cave.LOAD_ALL_BLOCKS):
            self.assertIn(b"\xB8" + struct.pack("<I", target) + b"\xFF\xD0", code)
        # 帧表 +130 项 (2 字节/项 = 260) 出现两次; 总帧数 -130 (必须 imm32:
        # 83 /5 的 imm8 0x82 会按有符号扩展成 -126); 状态基准 = 112
        self.assertEqual(code.count(b"\x81\xC1" + struct.pack("<I", 260)), 2)
        self.assertIn(b"\x81\x68\x18" + struct.pack("<I", 130), code)
        self.assertEqual(icon_cave.STATUS_BASE_SHIFTED, 112)
        self.assertIn(b"\x66\xC7\x05"
                      + struct.pack("<I", icon_cave.STATUS_BASE)
                      + struct.pack("<H", icon_cave.STATUS_BASE_SHIFTED), code)
        # 状态次序还原: 帧→块表与帧→子帧表各一次 32 位读改写 (rol 16 交换两条
        # 相邻表项), 偏移 = (Mu 帧 252 - 130) * 2 = 244
        self.assertEqual(icon_cave.STATUS_ORDER_SWAP_FRAME, 252)
        self.assertEqual(icon_cave.SWAP_ENTRY_OFFSET, 244)
        swap = (b"\x81\xC1" + struct.pack("<I", icon_cave.SWAP_ENTRY_OFFSET)
                + b"\x8B\x11" + b"\xC1\xC2\x10" + b"\x89\x11")
        self.assertEqual(code.count(swap), 2, "两张帧表都必须交换")
        self.assertEqual(code.count(b"\x8B\x48\x08"), 2, "帧→块表被两次寻址")
        self.assertEqual(code.count(b"\x8B\x48\x0C"), 2, "帧→子帧表被两次寻址")

    @unittest.skipUnless((GAME_DIR / "TKS.exe").is_file(),
                         "需要原版 TKS.exe 才能校验 hook pattern")
    def test_hook_pattern_unique_and_replayable(self):
        import pefile
        pe = pefile.PE(str(GAME_DIR / "TKS.exe"), fast_load=True)
        text = next(s for s in pe.sections
                    if s.Name.rstrip(b"\0") == b".text").get_data()
        pattern = bytes.fromhex(icon_cave.HOOK_PATTERN.replace(" ", ""))
        hits = []
        pos = text.find(pattern)
        while pos >= 0:
            hits.append(pos)
            pos = text.find(pattern, pos + 1)
        self.assertEqual(len(hits), 1, "hook pattern 必须全 .text 唯一")
        site = TEXT_BASE + hits[0] + icon_cave.HOOK_OFFSET
        self.assertEqual(site, 0x430218, "hook 必须落在 42FEE0 的 0x430218")
        # hook_size 必须恰好覆盖一条可重放的指令 (cave 结尾就是它)
        replaced = pattern[icon_cave.HOOK_OFFSET:icon_cave.HOOK_OFFSET
                           + icon_cave.HOOK_SIZE]
        self.assertEqual(replaced,
                         b"\x8B\x15" + struct.pack("<I", HOOK_REPLAY_ADDR),
                         "被替换的 6 字节必须正好是 mov edx,[0x755AF8]")
        self.assertTrue(icon_cave.build_cave().endswith(
            b"\x8B\x15" + struct.pack("<I", HOOK_REPLAY_ADDR) + b"\xC3"))

    @unittest.skipUnless((GAME_DIR / "TKS.exe").is_file(),
                         "需要原版 TKS.exe 才能做计划预检")
    def test_plan_precheck_passes_on_original_exe(self):
        import pefile
        pe = pefile.PE(str(GAME_DIR / "TKS.exe"), fast_load=True)
        text = next(s for s in pe.sections
                    if s.Name.rstrip(b"\0") == b".text").get_data()
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            _write_tkitem(game / "TKItem.dat", icons=[0, 200])
            (game / "Mu.JVG").write_bytes(b"@JVG" + b"\0" * 64)
            plan = _build_plan(game)
            validate_runtime_plan(plan, text)   # 预检失败会抛 PatchPlanError


class IconCavePlanTests(unittest.TestCase):
    """prepare.py 的数据门控。"""

    def _plan_ids(self, game, selected=("tkitem_expand",), disabled=()):
        plan = _build_plan(game, selected, disabled)
        return {op.id for op in plan.patches
                if op.id.startswith("tkitem_expand.")}

    def test_vanish_when_icons_fit_mu2(self):
        """图标值在原版 Mu2 帧数 (107) 内 → 战斗取值合法, 不注入。"""
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            _write_tkitem(game / "TKItem.dat",
                          icons=[0, 75, MU2_FRAME_TOTAL - 1])
            (game / "Mu.JVG").write_bytes(b"@JVG" + b"\0" * 64)
            self.assertEqual(self._plan_ids(game), {"tkitem_expand.table"})

    def test_injected_when_extended_icon_used(self):
        """图标值 ≥ Mu2 帧数 → 战斗取帧越界 (原版必然空白) → 注入图标操作。"""
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            _write_tkitem(game / "TKItem.dat",
                          icons=[0, MU2_FRAME_TOTAL, 300])
            (game / "Mu.JVG").write_bytes(b"@JVG" + b"\0" * 64)
            self.assertEqual(self._plan_ids(game),
                             {"tkitem_expand.table",
                              "tkitem_expand.battle_icon"})

    def test_vanilla_mu2_treated_as_107_when_absent(self):
        """Mu2.JVG 不在游戏目录时按原版 107 帧判定 (106 不注入 / 107 注入)。"""
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            _write_tkitem(game / "TKItem.dat", icons=[106])
            (game / "Mu.JVG").write_bytes(b"@JVG" + b"\0" * 64)
            self.assertEqual(self._plan_ids(game), {"tkitem_expand.table"})
            _write_tkitem(game / "TKItem.dat", icons=[107])
            self.assertEqual(self._plan_ids(game),
                             {"tkitem_expand.table",
                              "tkitem_expand.battle_icon"})

    def test_skipped_when_mu2_already_covers_icons(self):
        """Mu2.JVG 已补全 (帧号 = 图标值) 时无需 cave: 纯数据方案不被补丁干扰。"""
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            _write_mu2(game / "Mu2.JVG", frames=400)
            _write_tkitem(game / "TKItem.dat", icons=[0, 300, 399])
            (game / "Mu.JVG").write_bytes(b"@JVG" + b"\0" * 64)
            self.assertEqual(self._plan_ids(game), {"tkitem_expand.table"})
            # 超出补全范围的值仍需 cave
            _write_tkitem(game / "TKItem.dat", icons=[400])
            self.assertEqual(self._plan_ids(game),
                             {"tkitem_expand.table",
                              "tkitem_expand.battle_icon"})

    def test_skipped_without_mu_jvg(self):
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            _write_tkitem(game / "TKItem.dat", icons=[200])
            self.assertEqual(self._plan_ids(game), {"tkitem_expand.table"})

    def test_disabled_bundle_expands_to_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            _write_tkitem(game / "TKItem.dat", icons=[200])
            (game / "Mu.JVG").write_bytes(b"@JVG" + b"\0" * 64)
            # tkitem_expand 为非可选补丁, 只能通过 disabled 关闭
            self.assertEqual(self._plan_ids(game, disabled=("tkitem_expand",)),
                             set())

    def test_corrupt_data_does_not_block_plan(self):
        """TKItem.dat 无法解压时保守跳过图标操作, 不让计划准备失败。"""
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            (game / "TKItem.dat").write_bytes(bytes(32))
            (game / "Mu.JVG").write_bytes(b"@JVG" + bytes(64))
            self.assertEqual(self._plan_ids(game), {"tkitem_expand.table"})

    def test_tkspatch_zip_carries_bundle_resources(self):
        """打包成 .tkspatch 后 prepare/JSON 资源仍随包分发并正常展开。"""
        from patcher.build_patches import build_single_patch
        from core.tkspatch_loader import load_tkspatch_file
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "tkitem_expand.tkspatch"
            self.assertTrue(build_single_patch(PATCH_DIR, package))
            defn = load_tkspatch_file(str(package))
            self.assertEqual(defn.type, "bundle")
            self.assertEqual(sorted(defn.package_files),
                             ["data_expand.json", "icon.json", "icon_cave.py",
                              "patch.json", "prepare.py"])
            game = Path(td) / "game"
            game.mkdir()
            _write_tkitem(game / "TKItem.dat", icons=[200])
            (game / "Mu.JVG").write_bytes(b"@JVG" + b"\0" * 64)
            plan = build_patch_plan(
                [defn], selected={"tkitem_expand"},
                resolve_file=lambda name: str(game / name))
            self.assertEqual({op.id for op in plan.patches},
                             {"tkitem_expand.table",
                              "tkitem_expand.battle_icon"})


def _write_tkitem(path, icons):
    """写出 n 条记录的 TKItem.dat (图标值取自 icons, 其余补零)。"""
    import editor_utils.lzss as lzss
    records = len(icons)
    data = bytearray(records * 64)
    for index, icon in enumerate(icons):
        struct.pack_into("<h", data, index * 64 + 8, icon)
    path.write_bytes(lzss.lzss_compress_dat(bytes(data)))


def _write_mu2(path, frames):
    """写出只保留 JVG 头的假 Mu2.JVG (门控只读头 +0x10 的总帧数)。"""
    head = bytearray(b"@JVG" + b"\0" * 0x40)
    struct.pack_into("<I", head, 0x10, frames)
    path.write_bytes(bytes(head))


def _build_plan(game, selected=("tkitem_expand",), disabled=()):
    patches = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None).patches
    return build_patch_plan(
        patches, selected=set(selected), disabled=set(disabled),
        resolve_file=lambda name: str(Path(game) / name))


class IconCaveApplyTests(unittest.TestCase):
    """两个消费端都走通: 离线烧录 (.test 节 + E8 hook) 与运行时注入。"""

    def _cave_item(self):
        from core.exe_builder import CavePatchItem
        op = _load_icon_op()
        return CavePatchItem(
            patch_id=op["id"], name=op["name"],
            hook_pattern=op["hook_pattern"], hook_size=op["hook_size"],
            cave_code=bytes.fromhex(op["cave_code"].replace(" ", "")),
            fallback_rva=None, expect_count=op["hook_expect_count"],
            hook_offset=op["hook_offset"])

    def test_runtime_apply_writes_cave_and_hook(self):
        from core import patch_engine as pe
        from core.tkspatch_loader import load_patch_directory as _load
        cfg = _load(str(LAUNCHER / "patches"), log_func=lambda *_a: None)
        icon_defn = None
        with tempfile.TemporaryDirectory() as td:
            game = Path(td)
            _write_tkitem(game / "TKItem.dat", icons=[200])
            (game / "Mu.JVG").write_bytes(b"@JVG" + b"\0" * 64)
            plan = _build_plan(game)
            icon_defn = next(op for op in plan.patches
                             if op.id == "tkitem_expand.battle_icon")
        pattern = bytes.fromhex(icon_defn.hook_pattern.replace(" ", ""))
        code = bytearray(b"\x90" * 0x1000)
        code[0x400:0x400 + len(pattern)] = pattern
        before = bytes(code)
        written = {}

        def fake_write(_proc, addr, payload):
            written[addr] = bytes(payload)
            return len(payload)

        from core.config_loader import PatchSettings, PatchRuntimeState
        with patch.object(pe, "write_pm", side_effect=fake_write), \
                patch.object(pe, "vp_ex", return_value=0x40):
            ok = pe.apply_cave_hook(
                icon_defn, [0x400], code, 0x401000,
                0x1234, 0x70000000, 0, PatchSettings(), PatchRuntimeState())
        self.assertTrue(ok)
        self.assertEqual(written[0x70000000], icon_cave.build_cave())
        # hook: RVA 0x400 + hook_offset -> E8 rel32 指向 cave
        site = 0x400 + icon_defn.hook_offset
        self.assertEqual(code[site], 0xE8)
        rel = struct.unpack_from("<i", code, site + 1)[0]
        self.assertEqual(0x401000 + site + 5 + rel, 0x70000000)
        # hook_size 之外的原始字节保持不动 (NOP 填充不越界)
        size = icon_defn.hook_size
        self.assertEqual(bytes(code[:site]), before[:site])
        self.assertEqual(bytes(code[site + size:]), before[site + size:])

    @unittest.skipUnless((GAME_DIR / "TKS.exe").is_file(),
                         "需要原版 TKS.exe 才能做离线烧录验证")
    def test_offline_build_injects_test_section(self):
        import pefile
        from core.exe_builder import ExeBuilder
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "TKS_icon.exe"
            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [self._cave_item()], str(out))
            self.assertTrue(result.success, "\n".join(result.log))
            pe = pefile.PE(str(out), fast_load=True)
            ib = pe.OPTIONAL_HEADER.ImageBase
            test = next(s for s in pe.sections
                        if s.Name.rstrip(b"\0") == b".test")
            blob = test.get_data()
            self.assertIn(icon_cave.build_cave(), blob)
            # hook 点写入 E8 rel32 -> .test 内 cave 入口
            raw = out.read_bytes()
            hook_off = 0x430218 - ib - 0x1000 + 0x400  # code_buf 起点 0x401000
            text = next(s for s in pe.sections
                        if s.Name.rstrip(b"\0") == b".text")
            at = text.PointerToRawData + (0x430218 - ib - text.VirtualAddress)
            self.assertEqual(raw[at], 0xE8)
            rel = struct.unpack_from("<i", raw, at + 1)[0]
            self.assertEqual(0x430218 + 5 + rel, ib + test.VirtualAddress,
                             "hook 必须 E8 跳到 .test 内的 cave 入口")
            pe.close()   # 释放文件句柄, 否则临时目录无法删除


@unittest.skipUnless(__import__("importlib").util.find_spec("unicorn"),
                     "需要 unicorn 才能做执行级验证")
class IconCaveEmulationTests(unittest.TestCase):
    """unicorn 执行 cave 字节码: 两条路径的字段/全局/寄存器/栈平衡。"""

    def _run(self, *, obj_addr=OBJ_ADDR, load_ok=True):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX,
                                       UC_X86_REG_EDX, UC_X86_REG_ESP,
                                       UC_X86_REG_EIP)

        code = icon_cave.build_cave()
        mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in ((0x00450000, 0x10000),   # 桩加载器 (0x453BD0/0x45410C)
                           (0x004E0000, 0x10000),   # exe 内 "Mu.jvg" 字面量
                           (0x00500000, 0x10000),   # 伪造 JVG 对象
                           (0x00600000, 0x20000),   # 帧→块表 / 帧→子帧表
                           (0x00750000, 0x10000),   # 0x755AF4 / 0x755AF8
                           (0x009D0000, 0x10000),   # word_9D6F76
                           (CAVE_BASE, 0x1000),
                           (STACK_BASE, 0x10000)):
            mu.mem_map(base, size)
        mu.mem_write(OBJ_ADDR + 8, struct.pack("<II", TABLE_BLOCK, TABLE_SF))
        mu.mem_write(OBJ_ADDR + 0x18, struct.pack("<I", FRAME_TOTAL))
        # 表项内容唯一: 帧→块表第 i 项 = 0x100+i, 帧→子帧表第 i 项 = 0x200+i
        mu.mem_write(TABLE_BLOCK, struct.pack("<%dH" % FRAME_TOTAL,
                                              *[(0x100 + i) & 0xFFFF
                                                for i in range(FRAME_TOTAL)]))
        mu.mem_write(TABLE_SF, struct.pack("<%dH" % FRAME_TOTAL,
                                           *[(0x200 + i) & 0xFFFF
                                             for i in range(FRAME_TOTAL)]))
        mu.mem_write(icon_cave.MU2_OBJ, struct.pack("<I", obj_addr))
        mu.mem_write(HOOK_REPLAY_ADDR, struct.pack("<I", 0xDEADBEEF))
        mu.mem_write(icon_cave.STATUS_BASE, struct.pack("<H", 76))
        mu.mem_write(icon_cave.MU_FILENAME, b"Mu.jvg\x00")
        mu.mem_write(STUB_LOAD_JVG, b"\xC3")
        mu.mem_write(STUB_LOAD_ALL, b"\xC3")

        calls = []

        def handler(uc, address, size, user):
            esp = uc.reg_read(UC_X86_REG_ESP)
            ret_addr = struct.unpack("<I", uc.mem_read(esp, 4))[0]
            if address == STUB_LOAD_JVG:
                # cdecl: [esp+4] = 第一参 = obj, [esp+8] = 第二参 = 文件名指针
                obj, name = struct.unpack("<II", uc.mem_read(esp + 4, 8))
                calls.append(("load_jvg", obj, name))
                uc.reg_write(UC_X86_REG_EAX, 1 if load_ok else 0xFFFFFF00)
            elif address == STUB_LOAD_ALL:
                # cdecl: [esp+4..0xC] = obj, -1, 0
                obj, a2, a3 = struct.unpack("<III", uc.mem_read(esp + 4, 12))
                calls.append(("load_all", obj, a2, a3))
            else:
                return
            uc.reg_write(UC_X86_REG_ESP, esp + 4)   # 模拟桩函数 ret 弹栈
            uc.reg_write(UC_X86_REG_EIP, ret_addr)

        mu.hook_add(UC_HOOK_CODE, handler, begin=0x00450000, end=0x00460000)

        mu.mem_write(CAVE_BASE, code)
        esp = STACK_BASE + 0x8000
        mu.mem_write(esp, struct.pack("<I", RETURN_ADDR))
        for reg, value in ((UC_X86_REG_EAX, 0x11111111),
                           (UC_X86_REG_ECX, 0x22222222),
                           (UC_X86_REG_EDX, 0x33333333)):
            mu.reg_write(reg, value)
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(CAVE_BASE, RETURN_ADDR, count=4096)

        def words(addr):
            return list(struct.unpack("<%dH" % FRAME_TOTAL,
                                      mu.mem_read(addr, 2 * FRAME_TOTAL)))

        block_ptr, sf_ptr = struct.unpack("<II", mu.mem_read(OBJ_ADDR + 8, 8))

        def resolve(frame):
            """对象内帧号 frame 实际落到的原表下标 (含状态 11/12 次序还原)。"""
            index = (block_ptr - TABLE_BLOCK) // 2 + frame
            if icon_cave.STATUS_ORDER_SWAP_FRAME <= index \
                    < icon_cave.STATUS_ORDER_SWAP_FRAME + 2:
                index = 2 * icon_cave.STATUS_ORDER_SWAP_FRAME + 1 - index
            return index

        return {
            "calls": calls,
            "esp": mu.reg_read(UC_X86_REG_ESP),
            "eax": mu.reg_read(UC_X86_REG_EAX),
            "ecx": mu.reg_read(UC_X86_REG_ECX),
            "edx": mu.reg_read(UC_X86_REG_EDX),
            "table_block": block_ptr,
            "table_sf": sf_ptr,
            "block_words": words(TABLE_BLOCK),
            "sf_words": words(TABLE_SF),
            "frames": struct.unpack("<I", mu.mem_read(OBJ_ADDR + 0x18, 4))[0],
            "status": struct.unpack("<H", mu.mem_read(icon_cave.STATUS_BASE, 2))[0],
            "mu2": struct.unpack("<I", mu.mem_read(icon_cave.MU2_OBJ, 4))[0],
            "resolve": resolve,
        }

    def test_load_success_shifts_tables(self):
        result = self._run(load_ok=True)
        self.assertEqual([c[0] for c in result["calls"]],
                         ["load_jvg", "load_all"])
        self.assertEqual(result["calls"][0][1], OBJ_ADDR)
        self.assertEqual(result["calls"][0][2], icon_cave.MU_FILENAME)
        self.assertEqual(result["calls"][1][1:], (OBJ_ADDR, 0xFFFFFFFF, 0))
        self.assertEqual(result["table_block"], TABLE_BLOCK + 260)
        self.assertEqual(result["table_sf"], TABLE_SF + 260)
        self.assertEqual(result["frames"], FRAME_TOTAL - 130)
        self.assertEqual(result["status"], 112, "状态图标基准 = Mu 帧 242 - 130")
        self.assertEqual(result["mu2"], OBJ_ADDR, "对象引用不变 (仅重载内容)")
        self.assertEqual(result["esp"], STACK_BASE + 0x8000 + 4, "栈平衡 (cave ret 消耗返回地址)")
        self.assertEqual(result["eax"], 0x11111111, "pushad/popad 恢复寄存器")
        self.assertEqual(result["ecx"], 0x22222222)
        self.assertEqual(result["edx"], 0xDEADBEEF,
                         "edx 为被替换指令的重放结果")

    def test_load_success_swaps_only_status_pair(self):
        """两张帧表都只交换下标 252/253 两条 (状态 11/12 次序还原)。"""
        result = self._run(load_ok=True)
        for key, base in (("block_words", 0x100), ("sf_words", 0x200)):
            expected = [(base + i) & 0xFFFF for i in range(FRAME_TOTAL)]
            expected[252], expected[253] = expected[253], expected[252]
            self.assertEqual(result[key], expected, key)

    def test_shifted_view_resolves_like_menu(self):
        """对象内帧 v: 物品/扩展 = 原表 v+130 (菜单同一张图); 状态 = Mu2 原版次序。"""
        result = self._run(load_ok=True)
        for frame in (0, 28, 75, 106, 130, 143):
            self.assertEqual(result["resolve"](frame), frame + 130)
        # 状态帧: 基准 112 -> Mu 帧 242, 帧 122/123 交换 -> 253/252 (= Mu2 帧 86/87)
        self.assertEqual(result["resolve"](112), 242)
        self.assertEqual(result["resolve"](122), 253)
        self.assertEqual(result["resolve"](123), 252)
        self.assertEqual(result["resolve"](142), 272)

    def test_load_failure_keeps_mu2(self):
        result = self._run(load_ok=False)
        self.assertEqual([c[0] for c in result["calls"]], ["load_jvg"])
        self.assertEqual(result["table_block"], TABLE_BLOCK, "帧表不得改动")
        self.assertEqual(result["table_sf"], TABLE_SF)
        self.assertEqual(result["frames"], FRAME_TOTAL)
        self.assertEqual(result["status"], 76, "状态基准保持原版 76")
        self.assertEqual(result["esp"], STACK_BASE + 0x8000 + 4, "栈平衡")
        # 失败路径不得触碰表项 (状态次序交换只能在载入成功后发生)
        self.assertEqual(result["block_words"][252], 0x100 + 252)
        self.assertEqual(result["block_words"][253], 0x100 + 253)
        self.assertEqual(result["sf_words"][252], 0x200 + 252)
        self.assertEqual(result["sf_words"][253], 0x200 + 253)

    def test_missing_object_is_noop(self):
        result = self._run(obj_addr=0)
        self.assertEqual(result["calls"], [], "对象未载入时不得调用加载器")
        self.assertEqual(result["frames"], FRAME_TOTAL)
        self.assertEqual(result["status"], 76)
        self.assertEqual(result["esp"], STACK_BASE + 0x8000 + 4, "栈平衡")
        self.assertEqual(result["edx"], 0xDEADBEEF)
        self.assertEqual(result["block_words"][252], 0x100 + 252)
        self.assertEqual(result["sf_words"][253], 0x200 + 253)


def _mu2_mu_frames():
    """加载原版 Mu2.JVG / Mu.JVG 的精灵 (按帧号索引), 不可用时返回 None。"""
    try:
        from editor_utils.jvg_loader import load_mu_sprites
    except Exception:
        return None
    mu2_path, mu_path = GAME_DIR / "Mu2.JVG", GAME_DIR / "Mu.JVG"
    if not (mu2_path.is_file() and mu_path.is_file()):
        return None
    mu2 = load_mu_sprites(str(mu2_path))
    mu = load_mu_sprites(str(mu_path))
    if not mu2 or not mu:
        return None
    return mu2, mu


@unittest.skipUnless(_mu2_mu_frames() is not None,
                     "需要原版游戏目录的 Mu.JVG / Mu2.JVG 与 PIL")
class RealJvgFrameMappingTests(unittest.TestCase):
    """真实 JVG 数据: 补丁后的取帧语义逐帧对照原版 Mu2 与菜单侧 Mu。"""

    @classmethod
    def setUpClass(cls):
        cls.mu2, cls.mu = _mu2_mu_frames()

    @staticmethod
    def _pixels(sprite):
        return sprite.tobytes()

    def test_battle_item_icons_are_mu_plus_130(self):
        """战斗物品图标 (Mu2 帧 0..75) 与菜单图标 (Mu 帧 130..205) 逐字节相同。"""
        self.assertGreaterEqual(len(self.mu2), 76)
        for icon in range(76):
            self.assertEqual(
                self._pixels(self.mu2[icon]),
                self._pixels(self.mu[130 + icon]),
                "图标值 %d: Mu2[%d] 应等于 Mu[%d]" % (icon, icon, 130 + icon))

    def test_status_icons_differ_only_by_swap(self):
        """状态图标: Mu2 帧 76..106 与 Mu 帧 242..272 仅 11/12 (帧 86/87 与 253/252) 次序相反。"""
        self.assertGreaterEqual(len(self.mu2), 107)
        differing = []
        for i in range(31):
            same = (self._pixels(self.mu2[76 + i])
                    == self._pixels(self.mu[242 + i]))
            if not same:
                differing.append(i + 1)
        self.assertEqual(differing, [11, 12], "只有状态 11/12 次序不同")
        # cave 的交换正是这两帧
        swap = icon_cave.STATUS_ORDER_SWAP_FRAME
        # 状态 11 的对象内帧 = 基准 112 + 10 = 122 = Mu 帧 252
        self.assertEqual(icon_cave.STATUS_BASE_SHIFTED + 10,
                         icon_cave.STATUS_ORDER_SWAP_FRAME - icon_cave.ICON_SHIFT)
        self.assertEqual(self._pixels(self.mu2[86]), self._pixels(self.mu[swap + 1]))
        self.assertEqual(self._pixels(self.mu2[87]), self._pixels(self.mu[swap]))

    def test_reloaded_view_is_menu_identical(self):
        """cave 重定位后对象内帧 v = Mu 帧 v+130, 状态帧经交换后 = Mu2 原版。"""
        total = len(self.mu) - icon_cave.ICON_SHIFT      # 对象内总帧数
        self.assertEqual(total, len(self.mu) - 130)
        # 物品图标: 帧 = 图标值, 落在 Mu 帧 = 图标值 + 130 (= 菜单/商店同一张图)
        for frame in (0, 28, 75, 106, 130, total - 1):
            self.assertLess(frame, total, "帧 %d 必须通过 a5<a2[6] 越界检查" % frame)
            self.assertEqual(self._pixels(self.mu[frame + 130]),
                             self._pixels(self.mu[frame + icon_cave.ICON_SHIFT]))
        # 状态图标: 基准 112 -> Mu 帧 242..272, 帧 122/123 交换还原 Mu2 次序
        for status_id in range(1, 32):
            frame = icon_cave.STATUS_BASE_SHIFTED + status_id - 1
            if frame == icon_cave.STATUS_BASE_SHIFTED + 10:
                source = icon_cave.STATUS_ORDER_SWAP_FRAME + 1
            elif frame == icon_cave.STATUS_BASE_SHIFTED + 11:
                source = icon_cave.STATUS_ORDER_SWAP_FRAME
            else:
                source = frame + icon_cave.ICON_SHIFT
            self.assertEqual(self._pixels(self.mu[source]),
                             self._pixels(self.mu2[76 + status_id - 1]),
                             "状态 %d 必须与原版 Mu2 逐像素一致" % status_id)


MOD_DIR = Path(os.environ.get("TKS_MOD_DIR", r"游戏目录（改版）"))


@unittest.skipUnless((MOD_DIR / "Mu.JVG").is_file(),
                     "需要 MOD 目录的 Mu.JVG (含 MOD 追加帧)")
class ModExtendedIconReachTests(unittest.TestCase):
    """MOD Mu.JVG 追加帧: 扩展图标值在重定位后必须可解析 (原版 Mu2 必然越界)。"""

    @classmethod
    def setUpClass(cls):
        from editor_utils.jvg_loader import load_mu_sprites
        cls.sprites = load_mu_sprites(str(MOD_DIR / "Mu.JVG"))
        if not cls.sprites:
            raise unittest.SkipTest("PIL 不可用")

    def test_appended_icons_are_reachable_after_reload(self):
        total = len(self.sprites)
        self.assertGreater(total, 274, "MOD Mu.JVG 应有追加帧")
        valid_frames = total - icon_cave.ICON_SHIFT      # 重定位后对象的总帧数
        appended = [i for i in range(274, total)
                    if self.sprites[i] is not None
                    and self.sprites[i].size == (30, 30)]
        self.assertTrue(appended, "MOD 追加区应含 30x30 图标")
        for frame in appended:
            value = frame - icon_cave.ICON_SHIFT         # 该图标在物品表里填的值
            self.assertGreaterEqual(value, MU2_FRAME_TOTAL,
                                    "该图标值在原版 Mu2 之外 (= 修复前必然空白)")
            self.assertLess(value, valid_frames,
                            "图标值 %d 必须落在重定位后的总帧数 %d 内"
                            % (value, valid_frames))


if __name__ == "__main__":
    unittest.main()
