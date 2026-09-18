import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from capstone import (Cs, CS_ARCH_X86, CS_MODE_32,
                      CS_GRP_CALL, CS_GRP_JUMP, CS_GRP_RET)
from capstone.x86 import X86_OP_IMM
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_EDI,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)
from unicorn import UC_HOOK_CODE


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tks_launcher_gui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LAUNCHER) not in sys.path:
    sys.path.insert(0, str(LAUNCHER))

from core.exe_builder import (  # noqa: E402
    BytesPatchEntry,
    BytesPatchItem,
    ExeBuilder,
    SitesPatchItem,
)
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from editor_utils.skill_extension import (  # noqa: E402
    SparseSkillOverride,
    create_original_game_extension,
    create_skill_extension,
    parse_skill_extension,
)


PATCH_JSON = LAUNCHER / "patches" / "skill_ext_learn_state" / "patch.json"
GAME_DIR = Path(r"游戏目录（原版）")

CAVE = 0x00400000
EXT = 0x00660000
TEMP = 0x0068B000
WARPC = 0x00700000
STACK = 0x7FF00000
STOP = 0x00100000
OVERRIDE_COUNT = 0x006BAFF0
OVERRIDE_TABLE = 0x006BB000
EFFECT_SCRATCH = 0x006BC800
BATTLE_MAP = 0x006B8000


def state_addr(actor, skill=350):
    return EXT + actor * 347 + (skill - 350)


def _load_cave():
    raw = json.loads(PATCH_JSON.read_text(encoding="utf-8"))
    entries = {
        key: int(value, 16) if isinstance(value, str) else int(value)
        for key, value in raw["cave_entries"].items()
    }
    return bytes.fromhex(raw["cave_code"].replace(" ", "")), entries


def _emu_base():
    cave, entries = _load_cave()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE, 0x3000)
    uc.mem_map(EXT, 0x60000)
    uc.mem_map(0x004B0000, 0x5000)
    # fopen is intentionally absent in the original sample.  Return NULL
    # so init_extension_defaults keeps the built-in defaults during tests.
    uc.mem_write(0x004B1FC8, b"\x31\xC0\xC3")
    uc.mem_map(WARPC, 0x10000)
    uc.mem_map(STACK - 0x10000, 0x20000)
    uc.mem_write(CAVE, cave)
    uc.mem_write(0x006B8040, struct.pack("<H", 347))
    uc.mem_write(0x006B8044, struct.pack("<I", 697))
    esp = STACK - 0x100
    uc.mem_write(esp, struct.pack("<I", STOP))
    uc.reg_write(UC_X86_REG_ESP, esp)
    return uc, entries


def _run_effect_entry(entry, *, eax=0, ecx=0, edx=0,
                      actor=9, override=None, registered_skills=347):
    uc, entries = _emu_base()
    uc.mem_write(0x006B8040, struct.pack("<H", registered_skills))
    uc.mem_write(
        0x006B8044, struct.pack("<I", 350 + registered_skills))
    uc.mem_map(0x009D6000, 0x1000)
    uc.mem_write(0x9D6F58, struct.pack("<h", actor))
    if override is not None:
        uc.mem_write(OVERRIDE_COUNT, struct.pack("<H", 1))
        uc.mem_write(
            OVERRIDE_TABLE,
            struct.pack("<HHhH", override[0], override[1],
                        override[2], 0),
        )
    uc.reg_write(UC_X86_REG_EAX, eax)
    uc.reg_write(UC_X86_REG_ECX, ecx)
    uc.reg_write(UC_X86_REG_EDX, edx)
    uc.emu_start(CAVE + entries[entry], STOP)
    return uc


class SkillLearnStateTests(unittest.TestCase):
    def _assert_battle_init_preserves_extension(self, uc):
        _, entries = _load_cave()
        metadata = bytes(uc.mem_read(BATTLE_MAP + 0x40, 8))
        states = bytes(uc.mem_read(EXT, 500 * 347))
        continuation = STOP + 0x100
        uc.mem_map(STOP, 0x1000)
        uc.mem_write(continuation, bytes.fromhex("8b e5 5d c3"))
        sp = STACK - 0x100
        uc.mem_write(sp, struct.pack("<II", continuation, STOP))
        uc.mem_write(BATTLE_MAP, b"\xab" * (32 * 2))
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.emu_start(CAVE + entries["init_battle_map"], STOP, count=20_000)
        self.assertEqual(uc.reg_read(UC_X86_REG_EIP), STOP)
        self.assertEqual(uc.reg_read(UC_X86_REG_ESP), sp + 8)
        self.assertEqual(uc.mem_read(BATTLE_MAP, 32 * 2), b"\0" * (32 * 2))
        self.assertEqual(uc.mem_read(BATTLE_MAP + 0x40, 8), metadata)
        self.assertEqual(uc.mem_read(EXT, 500 * 347), states)

    def _run_state_entry(self, entry, actor=9, skill=350, item_skill=350,
                         ext_state=None, related_delta=0, equip_mode=False):
        uc, entries = _emu_base()
        uc.mem_map(0x009D6000, 0x1000)
        frame = STACK - 0x5000
        item = WARPC + 0x800
        uc.mem_write(frame + 0xC, struct.pack("<h", actor))
        uc.mem_write(frame + 0x10, struct.pack("<h", skill))
        if entry == "read_menu_ecx":
            uc.mem_write(frame - 2, struct.pack("<h", skill))
        if entry.startswith("addr_item"):
            uc.mem_write(frame - 4, struct.pack("<I", item))
        if entry.startswith("addr_neg6"):
            uc.mem_write(frame - 6, struct.pack("<h", skill))
        if equip_mode:
            uc.mem_write(frame - 8, struct.pack("<I", item))
            uc.mem_write(frame + 0xC, struct.pack("<I", 0x757F08 + actor * 1054))
        if entry.startswith(("read_related", "add_related")):
            uc.mem_write(frame - 0x10, struct.pack("<I", item))
        uc.mem_write(item, struct.pack("<h", item_skill))
        uc.mem_write(item + 0x2E, struct.pack("<h", item_skill))
        uc.mem_write(item + 0x30, struct.pack("<h", item_skill))
        uc.mem_write(item + 0x2C, struct.pack("<h", item_skill))
        uc.mem_write(item + 2, bytes([related_delta]))
        if ext_state is not None:
            uc.mem_write(state_addr(actor, skill), bytes([ext_state]))
        uc.mem_write(0x9D6F58, struct.pack("<h", actor))
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.emu_start(CAVE + entries[entry], STOP)
        return uc

    def test_globals_relocations_cover_reachable_address_operands(self):
        raw = json.loads(PATCH_JSON.read_text(encoding="utf-8"))
        cave, entries = _load_cave()
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = True
        pending = list(entries.values())
        visited, offsets = set(), set()
        while pending:
            pos = pending.pop()
            while 0 <= pos < len(cave) and pos not in visited:
                visited.add(pos)
                ins = next(decoder.disasm(cave[pos:pos + 15], pos, count=1), None)
                self.assertIsNotNone(ins, f"无法解码 cave+{pos:#x}")
                branch = ins.group(CS_GRP_JUMP) or ins.group(CS_GRP_CALL)
                if branch and ins.operands[0].type == X86_OP_IMM:
                    target = ins.operands[0].imm
                    if 0 <= target < len(cave):
                        pending.append(target)
                operands = ((ins.disp_offset, ins.disp_size),
                            (ins.imm_offset, ins.imm_size))
                for offset, size in operands:
                    if size != 4 or (branch and offset == ins.imm_offset):
                        continue
                    value = int.from_bytes(cave[pos + offset:pos + offset + 4],
                                           "little")
                    if EXT <= value < EXT + 0x60000:
                        offsets.add(pos + offset)
                if ins.group(CS_GRP_RET) or ins.mnemonic == "jmp":
                    break
                pos += ins.size
        self.assertEqual(raw["globals_relocations"], sorted(offsets))
        self.assertIn(0x120C, offsets)
        self.assertNotIn(0x1209, offsets)

    def test_scan_builder_overlays_extended_skill_350(self):
        uc, entries = _emu_base()
        # WarPC learn state: skill 0 and skill 343 are preserved.
        uc.mem_write(
            WARPC + 9 * 1054 + 176,
            bytes([5]) + bytes(342) + bytes([7]),
        )
        uc.mem_write(state_addr(9, 350), bytes([20]))
        frame = STACK - 0x5000
        uc.mem_write(frame - 4, struct.pack("<i", 0))       # start skill
        uc.mem_write(frame + 0xC, struct.pack("<h", 9))     # character ID
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.reg_write(UC_X86_REG_EAX, WARPC)                 # base + start
        uc.reg_write(UC_X86_REG_EDX, 9 * 527)

        uc.emu_start(CAVE + entries["scan_redirect"], STOP)

        self.assertEqual(uc.reg_read(UC_X86_REG_EDX), TEMP)
        self.assertEqual(uc.reg_read(UC_X86_REG_EAX), TEMP)
        self.assertEqual(uc.mem_read(TEMP, 1), b"\x05")
        self.assertEqual(uc.mem_read(TEMP + 343, 1), b"\x07")
        self.assertEqual(uc.mem_read(TEMP + 344, 6), b"\0" * 6)
        self.assertEqual(uc.mem_read(TEMP + 350, 1), b"\x14")

    def test_learn_write_routes_skill_350_to_external_state(self):
        uc, entries = _emu_base()
        frame = STACK - 0x5000
        uc.mem_write(frame + 0xC, struct.pack("<h", 9))
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.reg_write(UC_X86_REG_EAX, 350)
        uc.reg_write(UC_X86_REG_ECX, 9 * 1054)

        uc.emu_start(CAVE + entries["learn_write"], STOP)

        target = uc.reg_read(UC_X86_REG_EDX) + 350
        self.assertEqual(target, state_addr(9, 350))

    def test_learn_write_keeps_legacy_skill_address(self):
        uc, entries = _emu_base()
        frame = STACK - 0x5000
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.reg_write(UC_X86_REG_EAX, 349)
        uc.reg_write(UC_X86_REG_ECX, 3)

        uc.emu_start(CAVE + entries["learn_write"], STOP)

        self.assertEqual(
            uc.reg_read(UC_X86_REG_EDX), 3 * 2 + 0x757FB8)

    def test_state_address_helpers_route_only_new_skills(self):
        uc = self._run_state_entry("addr_neg6_eax", skill=350)
        self.assertEqual(uc.reg_read(UC_X86_REG_EAX), state_addr(9, 350))

        uc = self._run_state_entry("addr_neg6_eax", skill=349)
        self.assertEqual(
            uc.reg_read(UC_X86_REG_EAX),
            0x757F08 + 9 * 1054 + 349 + 0xB0)

        uc = self._run_state_entry("addr_item23_edx", item_skill=350)
        self.assertEqual(uc.reg_read(UC_X86_REG_EDX), state_addr(9, 350))

        uc = self._run_state_entry("addr_item24_ecx", item_skill=350)
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), state_addr(9, 350))

        uc = self._run_state_entry(
            "addr_neg6_eax", actor=199, skill=399)
        self.assertEqual(
            uc.reg_read(UC_X86_REG_EAX), state_addr(199, 399))

    def test_direct_state_reads_and_writes_use_external_table(self):
        uc = self._run_state_entry("read_menu_ecx", skill=350, ext_state=20)
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 20)

        uc = self._run_state_entry(
            "read_equip_item_ecx", item_skill=350, ext_state=10,
            equip_mode=True)
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 10)

        uc = self._run_state_entry(
            "write_equip_item_30", item_skill=350, equip_mode=True)
        self.assertEqual(uc.mem_read(state_addr(9, 350), 1), b"\x1e")

        uc = self._run_state_entry(
            "write_equip_item_20", item_skill=350, equip_mode=True)
        self.assertEqual(uc.mem_read(state_addr(9, 350), 1), b"\x14")

        uc = self._run_state_entry(
            "write_equip_item_10", item_skill=350, equip_mode=True)
        self.assertEqual(uc.mem_read(state_addr(9, 350), 1), b"\x0a")

        uc, entries = _emu_base()
        uc.mem_map(0x009D6000, 0x1000)
        frame = STACK - 0x5000
        actor_slot = 2
        persistent_actor = 9
        uc.mem_write(
            BATTLE_MAP + actor_slot * 2,
            struct.pack("<H", persistent_actor + 1),
        )
        uc.mem_write(0x9D6F58, struct.pack("<h", actor_slot))
        uc.mem_write(frame - 2, struct.pack("<h", 350))
        uc.mem_write(state_addr(persistent_actor, 350), b"\x14")
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.emu_start(CAVE + entries["read_menu_mapped_ecx"], STOP)
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 20)

    def test_battle_map_records_source_actor(self):
        uc, entries = _emu_base()
        frame = STACK - 0x5000
        # [ebp-2] is the game's own flag-table index at the site; [ebp-6] is
        # the source WarPC character being copied; [ebp-4] is the battle slot.
        # Use a distinct [ebp-2] so the old bug (helper leaving eax=[ebp-6]) fails.
        uc.mem_write(frame - 2, struct.pack("<h", 7))
        uc.mem_write(frame - 6, struct.pack("<h", 9))
        uc.mem_write(frame - 4, struct.pack("<h", 2))
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.emu_start(CAVE + entries["record_battle_map"], STOP)
        # battle map records source actor ([ebp-6]) + 1 at slot [ebp-4]
        self.assertEqual(uc.mem_read(BATTLE_MAP + 2 * 2, 2), b"\x0a\x00")
        # the game's replayed registers are preserved: eax=[ebp-2], ecx=[ebp-4]
        self.assertEqual(uc.reg_read(UC_X86_REG_EAX), 7)
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 2)

    def test_battle_map_uses_word_for_high_actor_ids(self):
        _cave, entries = _load_cave()
        for actor_id in (254, 255, 499):
            uc, _entries = _emu_base()
            frame = STACK - 0x5000
            battle_slot = 2
            skill = 350
            uc.mem_write(frame - 6, struct.pack("<h", actor_id))
            uc.mem_write(frame - 4, struct.pack("<h", battle_slot))
            esp0 = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EBP, frame)
            uc.emu_start(CAVE + entries["record_battle_map"], STOP)
            self.assertEqual(
                struct.unpack(
                    "<H",
                    bytes(uc.mem_read(
                        BATTLE_MAP + battle_slot * 2, 2)),
                )[0],
                actor_id + 1,
            )

            uc.mem_write(
                state_addr(actor_id, skill),
                b"\x14",
            )
            uc.mem_map(0x009D6000, 0x1000)
            uc.mem_write(0x9D6F58, struct.pack("<h", battle_slot))
            uc.mem_write(frame - 2, struct.pack("<h", skill))
            uc.mem_write(esp0, struct.pack("<I", STOP))
            uc.reg_write(UC_X86_REG_ESP, esp0)
            uc.reg_write(UC_X86_REG_EBP, frame)
            uc.emu_start(CAVE + entries["read_menu_mapped_ecx"], STOP)
            self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 20)

    def test_mapped_menu_state_is_capped_at_twelve_entries(self):
        uc, entries = _emu_base()
        uc.mem_map(0x009D6000, 0x1000)
        frame = STACK - 0x5000
        uc.mem_write(frame - 2, struct.pack("<h", 350))
        uc.mem_write(0x9D6F58, struct.pack("<h", 2))
        uc.mem_write(
            BATTLE_MAP + 2 * 2,
            struct.pack("<H", 10),
        )
        uc.mem_write(state_addr(9, 350), b"\x14")
        uc.mem_write(0x9D6C8A, struct.pack("<H", 12))
        uc.reg_write(UC_X86_REG_EBP, frame)

        uc.emu_start(CAVE + entries["read_menu_mapped_ecx"], STOP)

        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 0)

    def test_unregistered_skills_are_not_exposed_or_resolved(self):
        uc, entries = _emu_base()
        uc.mem_map(0x009D6000, 0x1000)
        uc.mem_write(0x006B8040, struct.pack("<H", 1))
        uc.mem_write(0x006B8044, struct.pack("<I", 351))
        frame = STACK - 0x5000
        uc.mem_write(BATTLE_MAP + 2 * 2, struct.pack("<H", 10))
        uc.mem_write(0x9D6F58, struct.pack("<h", 2))
        uc.mem_write(frame - 2, struct.pack("<h", 351))
        uc.mem_write(state_addr(9, 351), b"\x14")
        uc.reg_write(UC_X86_REG_EBP, frame)

        uc.emu_start(CAVE + entries["read_menu_mapped_ecx"], STOP)
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 0)

        uc = _run_effect_entry(
            "effect_player", ecx=351, registered_skills=1)
        player_base = uc.reg_read(UC_X86_REG_EAX)
        word = struct.unpack(
            "<h", bytes(uc.mem_read(player_base + 351 * 2, 2)))[0]
        self.assertEqual(word, 0)

    def test_initial_and_summon_copy_hooks_use_word_map(self):
        _cave, entries = _load_cave()

        uc, _entries = _emu_base()
        frame = STACK - 0x5000
        uc.mem_write(frame - 6, struct.pack("<h", 499))
        uc.mem_write(frame - 4, struct.pack("<h", 5))
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.emu_start(CAVE + entries["record_battle_map_player"], STOP)
        self.assertEqual(
            uc.mem_read(BATTLE_MAP + 5 * 2, 2), b"\xf4\x01")
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 0x107)

        uc, _entries = _emu_base()
        frame = STACK - 0x5000
        uc.mem_write(frame + 8, struct.pack("<h", 499))
        uc.mem_write(frame - 4, struct.pack("<h", 6))
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.emu_start(CAVE + entries["record_battle_map_summon"], STOP)
        self.assertEqual(
            uc.mem_read(BATTLE_MAP + 6 * 2, 2), b"\xf4\x01")
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 0x107)

    def test_extension_init_clears_full_matrix_and_battle_map(self):
        uc, entries = _emu_base()
        uc.mem_write(state_addr(499, 696), b"\x1e")
        uc.mem_write(BATTLE_MAP, b"\xab" * (32 * 2))
        uc.mem_write(OVERRIDE_COUNT, struct.pack("<H", 1))
        uc.emu_start(CAVE + entries["init_extension_defaults"], STOP,
                     count=20_000_000)

        self.assertEqual(uc.reg_read(UC_X86_REG_EIP), STOP)
        self.assertEqual(uc.mem_read(state_addr(0, 350), 1), b"\x0a")
        self.assertEqual(uc.mem_read(state_addr(1, 350), 1), b"\x01")
        self.assertEqual(uc.mem_read(state_addr(499, 696), 1), b"\x01")
        self.assertEqual(uc.mem_read(BATTLE_MAP, 32 * 2), b"\0" * (32 * 2))
        self.assertEqual(uc.mem_read(OVERRIDE_COUNT, 2), b"\0\0")

    def test_extension_init_applies_war_pc_tksx_template(self):
        extension = create_skill_extension(
            500,
            347,
            mapping_version=1,
            overrides=[SparseSkillOverride(9, 350, 584)],
        ).with_learn_state(9, 350, 20)
        template = extension.to_bytes()
        uc, entries = _emu_base()
        file_ptr = 0x12340000
        uc.mem_write(
            0x004B1FC8,
            b"\xB8" + struct.pack("<I", file_ptr) + b"\xC3",
        )
        uc.mem_write(0x004B1C3C, b"\x31\xC0\xC3")

        def hook(uc_, address, _size, _user):
            if address != 0x004B2208:
                return
            esp = uc_.reg_read(UC_X86_REG_ESP)
            ptr = struct.unpack(
                "<I", bytes(uc_.mem_read(esp + 4, 4)))[0]
            size = struct.unpack(
                "<I", bytes(uc_.mem_read(esp + 8, 4)))[0]
            count = struct.unpack(
                "<I", bytes(uc_.mem_read(esp + 12, 4)))[0]
            need = min(len(template), size * count)
            uc_.mem_write(ptr, template[:need])
            uc_.reg_write(UC_X86_REG_EAX, need // max(1, size))
            ret = struct.unpack(
                "<I", bytes(uc_.mem_read(esp, 4)))[0]
            uc_.reg_write(UC_X86_REG_ESP, esp + 4)
            uc_.reg_write(UC_X86_REG_EIP, ret)

        uc.hook_add(UC_HOOK_CODE, hook, begin=0x004B2208, end=0x004B2208)
        uc.emu_start(CAVE + entries["init_extension_defaults"], STOP,
                     count=20_000_000)
        self.assertEqual(uc.reg_read(UC_X86_REG_EIP), STOP)

        self.assertEqual(uc.mem_read(state_addr(9, 350), 1), b"\x14")
        self.assertEqual(
            struct.unpack(
                "<HHhH", bytes(uc.mem_read(OVERRIDE_TABLE, 8))),
            (9, 350, 584, 0),
        )
        self.assertEqual(uc.mem_read(OVERRIDE_COUNT, 2), b"\x01\x00")

    def test_new_game_hook_consumes_synthetic_return_address(self):
        uc, entries = _emu_base()
        caller_words = STACK - 0x100
        frame_words = caller_words - 0x20
        saved_edi = 0x11111111
        saved_esi = 0x22222222
        caller_return = STOP
        hook_return = STOP

        uc.mem_write(frame_words - 4, struct.pack("<I", hook_return))
        uc.mem_write(frame_words + 0x18, struct.pack("<I", saved_edi))
        uc.mem_write(frame_words + 0x1c, struct.pack("<I", saved_esi))
        uc.mem_write(frame_words + 0x20, struct.pack("<I", caller_return))
        uc.reg_write(UC_X86_REG_ESP, frame_words - 4)
        uc.reg_write(UC_X86_REG_EDI, 0)
        uc.reg_write(UC_X86_REG_ESI, 0)

        uc.emu_start(CAVE + entries["init_new_game_state"], STOP,
                     count=20_000_000)
        self.assertEqual(uc.reg_read(UC_X86_REG_EIP), STOP)

        self.assertEqual(
            uc.reg_read(UC_X86_REG_ESP),
            caller_words + 4,
        )
        self.assertEqual(
            struct.unpack(
                "<I", bytes(uc.mem_read(caller_words, 4)))[0],
            caller_return,
        )
        self.assertEqual(uc.reg_read(UC_X86_REG_EDI), saved_edi)
        self.assertEqual(uc.reg_read(UC_X86_REG_ESI), saved_esi)
        self._assert_battle_init_preserves_extension(uc)

    def test_related_skill_progress_uses_external_table(self):
        uc = self._run_state_entry(
            "read_related_ecx", item_skill=350, ext_state=9)
        self.assertEqual(uc.reg_read(UC_X86_REG_ECX), 9)

        uc = self._run_state_entry(
            "add_related_state", item_skill=350,
            ext_state=5, related_delta=3)
        self.assertEqual(uc.mem_read(state_addr(9, 350), 1), b"\x08")

        uc = self._run_state_entry("write_current_30", skill=350)
        self.assertEqual(uc.mem_read(state_addr(9, 350), 1), b"\x1e")

    def _run_file_io(self, entry, file_data, ext_data=b"",
                     override_data=b""):
        uc, entries = _emu_base()
        if ext_data:
            uc.mem_write(EXT, ext_data)
        if override_data:
            uc.mem_write(
                OVERRIDE_COUNT,
                struct.pack("<H", len(override_data) // 8),
            )
            uc.mem_write(OVERRIDE_TABLE, override_data)
        iat_base = 0x00A63000
        uc.mem_map(iat_base, 0x1000)
        uc.mem_write(0x00A63B50, struct.pack("<I", 0x004B3000))
        uc.mem_write(0x00A63320, struct.pack("<I", 0x004B3400))
        stream = 0x12345678
        file_buf = bytearray(file_data)
        reads = []
        exit_code = None

        def read_u32(addr):
            return struct.unpack("<I", uc.mem_read(addr, 4))[0]

        def hook(uc_, address, _size, _user):
            esp = uc_.reg_read(UC_X86_REG_ESP)
            ret = read_u32(esp)
            if address == 0x004B2488:  # fwrite
                ptr = read_u32(esp + 4)
                size = read_u32(esp + 8)
                count = read_u32(esp + 12)
                payload = bytes(uc_.mem_read(ptr, size * count))
                file_buf.extend(payload)
                uc_.reg_write(UC_X86_REG_EAX, count)
            elif address == 0x004B2208:  # fread
                ptr = read_u32(esp + 4)
                size = read_u32(esp + 8)
                count = read_u32(esp + 12)
                need = size * count
                pos = len(b"".join(reads))
                chunk = bytes(file_buf[pos:pos + need])
                uc_.mem_write(ptr, chunk)
                reads.append(chunk)
                got = len(chunk) // size if size and len(chunk) % size == 0 else 0
                uc_.reg_write(UC_X86_REG_EAX, got)
            elif address == 0x004B1C3C:  # fclose
                uc_.reg_write(UC_X86_REG_EAX, 0)
            elif address == 0x004B3000:  # MessageBoxA
                uc_.reg_write(UC_X86_REG_EAX, 1)
                uc_.reg_write(UC_X86_REG_ESP, esp + 0x14)
                uc_.reg_write(UC_X86_REG_EIP, ret)
                return
            elif address == 0x004B3400:  # ExitProcess
                nonlocal exit_code
                exit_code = read_u32(esp + 4)
                uc_.emu_stop()
                return
            else:
                return
            uc_.reg_write(UC_X86_REG_ESP, esp + 4)
            uc_.reg_write(UC_X86_REG_EIP, ret)

        for address in (0x004B2488, 0x004B2208, 0x004B1C3C,
                        0x004B3000, 0x004B3400):
            uc.hook_add(UC_HOOK_CODE, hook, begin=address, end=address)
        esp = uc.reg_read(UC_X86_REG_ESP)
        uc.reg_write(UC_X86_REG_EAX, entry)
        # The entry expects the stream argument immediately above ret.
        uc.mem_write(esp + 4, struct.pack("<I", stream))
        uc.emu_start(CAVE + entry, STOP, count=20_000_000)
        if exit_code is None:
            self.assertEqual(uc.reg_read(UC_X86_REG_EIP), STOP)
        return uc, bytes(file_buf), exit_code

    def test_save_append_writes_valid_tksx(self):
        _cave, entries = _load_cave()
        extension = create_skill_extension(500, 347, mapping_version=1)
        extension = extension.with_learn_state(9, 350, 20)

        _uc, written, exit_code = self._run_file_io(
            entries["save_append"], b"", extension.learn)
        self.assertIsNone(exit_code)
        self.assertEqual(len(written), 64 + 500 * 347)
        parsed = parse_skill_extension(written)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.actor_count, 500)
        self.assertEqual(parsed.skill_count, 347)
        self.assertEqual(parsed.learn_state(9, 350), 20)

    def test_load_append_restores_and_rejects_invalid(self):
        _cave, entries = _load_cave()
        extension = create_skill_extension(500, 347, mapping_version=1)
        extension = extension.with_learn_state(9, 350, 20)

        uc, _, exit_code = self._run_file_io(
            entries["load_append"], extension.to_bytes())
        self.assertIsNone(exit_code)
        self.assertEqual(uc.mem_read(state_addr(9, 350), 1), b"\x14")

        corrupted = bytearray(extension.to_bytes())
        corrupted[-1] ^= 0x80
        _uc, _, exit_code = self._run_file_io(
            entries["load_append"], bytes(corrupted))
        self.assertEqual(exit_code, 1)

        _uc, _, exit_code = self._run_file_io(
            entries["load_append"], b"TKSX")
        self.assertEqual(exit_code, 1)

        uc, _, exit_code = self._run_file_io(
            entries["load_append"], b"")
        self.assertIsNone(exit_code)
        self.assertEqual(uc.mem_read(EXT, 1), b"\x0a")
        self.assertEqual(uc.mem_read(EXT + 1, 499), b"\x01" * 499)
        self._assert_battle_init_preserves_extension(uc)

    def test_load_append_rejects_identity_and_invalid_effect(self):
        _cave, entries = _load_cave()
        base = create_skill_extension(500, 347, mapping_version=1)

        invalid_identity = bytearray(base.to_bytes())
        struct.pack_into("<I", invalid_identity, 16, 12345)
        _uc, _written, exit_code = self._run_file_io(
            entries["load_append"], bytes(invalid_identity))
        self.assertEqual(exit_code, 1)

        invalid_effect = bytearray(base.to_bytes())
        invalid_effect.extend(b"\0" * 8)
        override_offset = 64 + 500 * 347
        struct.pack_into("<HHhH", invalid_effect, override_offset,
                         9, 350, -1, 0)
        struct.pack_into("<H", invalid_effect, 26, 1)
        struct.pack_into(
            "<I", invalid_effect, 8, len(invalid_effect) - 64)
        struct.pack_into(
            "<I", invalid_effect, 12,
            zlib.crc32(invalid_effect[64:]) & 0xFFFFFFFF,
        )
        _uc, _written, exit_code = self._run_file_io(
            entries["load_append"], bytes(invalid_effect))
        self.assertEqual(exit_code, 1)

    def test_load_append_updates_registered_skill_limit(self):
        _cave, entries = _load_cave()
        extension = create_original_game_extension(
            actor_count=1, skill_count=1)

        uc, _written, exit_code = self._run_file_io(
            entries["load_append"], extension.to_bytes())

        self.assertIsNone(exit_code)
        self.assertEqual(uc.mem_read(0x006B8040, 2), b"\x01\x00")
        self.assertEqual(uc.mem_read(0x006B8044, 4), b"\x5f\x01\x00\x00")
        self._assert_battle_init_preserves_extension(uc)

    def test_sparse_override_roundtrip_and_effect_resolution(self):
        extension = create_skill_extension(
            500,
            347,
            mapping_version=1,
            overrides=[SparseSkillOverride(9, 350, 656)],
        )
        extension = extension.with_learn_state(9, 350, 20)

        _uc, written, exit_code = self._run_file_io(
            _load_cave()[1]["save_append"], b"", extension.learn,
            override_data=struct.pack("<HHhH", 9, 350, 656, 0),
        )
        self.assertIsNone(exit_code)
        parsed = parse_skill_extension(written)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.override_for(9, 350).tkkon_id, 656)

        uc, _, exit_code = self._run_file_io(
            _load_cave()[1]["load_append"], extension.to_bytes())
        self.assertIsNone(exit_code)
        self.assertEqual(uc.mem_read(OVERRIDE_COUNT, 2), b"\x01\x00")
        self.assertEqual(
            struct.unpack("<HHhH", bytes(uc.mem_read(OVERRIDE_TABLE, 8))),
            (9, 350, 656, 0),
        )

        uc = _run_effect_entry("effect_player", ecx=350)
        player_base = uc.reg_read(UC_X86_REG_EAX)
        word = struct.unpack(
            "<h", bytes(uc.mem_read(player_base + 350 * 2, 2)))[0]
        self.assertEqual(word, 590)

        uc = _run_effect_entry("effect_player", ecx=351)
        player_base = uc.reg_read(UC_X86_REG_EAX)
        word = struct.unpack(
            "<h", bytes(uc.mem_read(player_base + 351 * 2, 2)))[0]
        self.assertEqual(word, 590)

        uc = _run_effect_entry(
            "effect_player", ecx=350,
            override=(9, 350, 656),
        )
        player_base = uc.reg_read(UC_X86_REG_EAX)
        word = struct.unpack(
            "<h", bytes(uc.mem_read(player_base + 350 * 2, 2)))[0]
        self.assertEqual(word, 656)

        uc = _run_effect_entry("effect_ai_first", eax=350)
        ai_base = uc.reg_read(UC_X86_REG_EDX)
        word = struct.unpack(
            "<h",
            bytes(uc.mem_read(ai_base + 350 * 2 + 0x222, 2)),
        )[0]
        self.assertEqual(word, 590)

        uc = _run_effect_entry("effect_ai_second", edx=350)
        ai_base = uc.reg_read(UC_X86_REG_ECX)
        word = struct.unpack(
            "<h",
            bytes(uc.mem_read(ai_base + 350 * 2 + 0x222, 2)),
        )[0]
        self.assertEqual(word, 590)

        uc = _run_effect_entry("effect_player", ecx=349, edx=3)
        self.assertEqual(uc.reg_read(UC_X86_REG_EAX), 3 * 2 + 0x9D729C)

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file(),
        "需要原版 TKS.exe 才能验证学习状态位点构建",
    )
    def test_learn_state_builds_without_scan_bound_dependency(self):
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        patch = next(p for p in cfg.patches
                     if p.id == "skill_ext_learn_state")
        cave, entries = _load_cave()
        site_item = SitesPatchItem(
            patch_id=patch.id,
            name=patch.name,
            sites=patch.sites,
            cave_code=cave,
            cave_entries=entries,
            globals_ph_base=patch.globals_ph_base,
            globals_rebase_span=patch.globals_rebase_span,
            globals_alloc_size=patch.globals_alloc_size,
            globals_relocations=patch.globals_relocations,
        )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "TKS_skill_learn.exe"
            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [], str(out),
                sites_patches=[site_item],
            )
            self.assertTrue(result.success, "\n".join(result.log))
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
