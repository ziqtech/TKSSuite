"""
ddraw.dll 补丁移除工具

从 tks_launcher_gui/tools/ddraw/ddraw.dll 中移除指定的内存补丁和 Hook（清零处理）。

补丁 (patch): DLL 在 .data 段中以明文 ASCII 字符串定义，格式为:
    "0x游戏地址,补丁字节,原指令描述,新指令描述"
本脚本将这些字符串清零，使 DLL 的补丁解析器跳过它们。

Hook: DLL 在 .data 段中以 32 字节条目定义，结构为:
    [8字节地址字符串] [8字节null填充] [16字节Hook名称]
本脚本将地址字符串清零，使 DLL 的 Hook 安装器跳过它们。

可移除的补丁组 (共 44 个):
  - wisdom:       智慧 WORD→BYTE 补丁 (9个) — 已移除于修补版
  - benevolence:  仁德 WORD→BYTE 补丁 (9个) — 已移除于修补版
  - gold_cap:     金钱上限 30K 扩展补丁 (9个) — 已移除于修补版
  - money_field:  金钱字段 WORD→DWORD 扩展补丁 (17个) — 修补版中仍生效

可移除的 Hook (共 6 个):
  - SkimFstDlg / NoTmpDatRead / NoTmpDatWrite / NoEnemy / ReadSave / WriteSave
"""

import sys
import shutil
from pathlib import Path

# ============================================================
# 补丁地址定义
# ============================================================

# 智慧 (wisdom): 将 game 对 word[0x756884] 的操作改为 byte[0x756887]
WISDOM_PATCH_ADDRS = {
    "0x0040E187",  # Attribute() add
    "0x0040E720",  # CheckTeam() case 2: mov dx
    "0x00412875",  # 存档加载: mov word, ax
    "0x004175A5",  # 其他写入: mov word, dx
    "0x0041A3D2",  # 存档预览: movsx ecx
    "0x00422A8B",  # sub word
    "0x00422B13",  # add word
    "0x00422B6E",  # cmp word
    "0x00422B78",  # mov word, 0
}

# 仁德 (benevolence): 将 game 对 word[0x756886] 的操作改为 byte[0x756886]
BENEVOLENCE_PATCH_ADDRS = {
    "0x0040E1FB",  # Attribute() add
    "0x0040E730",  # CheckTeam() case 3: mov cx
    "0x00412882",  # 存档加载: mov word, dx
    "0x004175B3",  # 其他写入: mov word, cx
    "0x0041A3F2",  # 存档预览: movsx edx
    "0x00422AAA",  # sub word
    "0x00422B32",  # add word
    "0x00422B81",  # cmp word
    "0x00422B8B",  # mov word, 0
}

# 金钱上限 (gold cap): 将金钱上限从 9999 扩展到 30000
GOLD_CAP_PATCH_ADDRS = {
    "0x0040CE49",  # mov eax → NOP + mov
    "0x0040CE5F",  # add → addex (30K)
    "0x0040CE66",  # _mov30K → _addex
    "0x0040CE6A",  # mov → movzx
    "0x0040CE6E",  # add → addex
    "0x0040CE77",  # mov 0x00 → NoChg
    "0x0040E4F8",  # mov ax → XChg
    "0x0040E4FE",  # _mov ax → XChg
    "0x00412372",  # mov 30K → NoChg
}

# 金钱字段 WORD→DWORD 扩展 (money field): 将 SEG2+0x02 (0x756882) 的金钱运算
# 从 WORD(16位) 扩展为 DWORD(32位)，支持更大数值。共 17 个。
# 参考: ddraw_dll_analysis.md Section 4.2-D "保留的补丁"
MONEY_FIELD_PATCH_ADDRS = {
    "0x004197D9",  # SEG2 数据读取修正: movzdx→mov
    "0x0041D0F9",  # 栈操作修正: push→NoChg
    "0x00423AFD",  # [ecx+0x29C] mov→movzx 零扩展读取
    "0x00423B04",  # sub word[0x756882]→sub dword 减法扩展
    "0x00423B10",  # [edx+0x29C] mov→movzx 零扩展读取
    "0x00423B17",  # add word[0x756882]→add dword 加法扩展
    "0x00423E96",  # [edx+0x29C] mov→movzx 零扩展读取
    "0x00423E9D",  # sub word[0x756882]→sub dword 减法扩展
    "0x00423EA9",  # [edx+0x29C] mov→movzx 零扩展读取
    "0x00423EB0",  # add word[0x756882]→add dword 加法扩展
    "0x00424DB3",  # movzx eax,word[0x756882]→mov eax,[0x756882]
    "0x004250A6",  # mov ax,[ecx]→movzx ax,byte[ecx]
    "0x004250B0",  # cmp word[0x756882]→cmp dword 比较扩展
    "0x00425149",  # movzx eax,word[0x756882]→mov eax,[0x756882]
    "0x00425153",  # mov edx,0x7530→mov edx,0xFF7530 立即数替换
    "0x00438D39",  # movzx ecx,word[0x756882]→mov ecx,[0x756882]
    "0x00439123",  # movzx ecx,word[0x756882]→mov ecx,[0x756882]
}

# ============================================================
# Hook 定义
# ============================================================
# Hook 以 32 字节条目存储在 .data 段:
#   [8字节地址] [8字节null] [16字节名称]
# 移除方式: 将地址字符串清零

# ReadSave Hook: 拦截存档加载 (游戏地址 0x0041116E)
READSAVE_HOOK = {
    "name": "ReadSave",
    "addr": "0041116E",
}

# WriteSave Hook: 拦截存档保存 (游戏地址 0x00410FA2)
WRITESAVE_HOOK = {
    "name": "WriteSave",
    "addr": "00410FA2",
}

# SkimFstDlg Hook: 快速对话跳过/加速 (游戏地址 0x00403C63)
SKIMFSTDLG_HOOK = {
    "name": "SkimFstDlg",
    "addr": "00403C63",
}

# NoTmpDatRead Hook: 拦截 TmpDat 读取 (游戏地址 0x0047881A)
NOTMPDATREAD_HOOK = {
    "name": "NoTmpDatRead",
    "addr": "0047881A",
}

# NoTmpDatWrite Hook: 拦截 TmpDat 写入 (游戏地址 0x00478842)
NOTMPDATWRITE_HOOK = {
    "name": "NoTmpDatWrite",
    "addr": "00478842",
}

# NoEnemy Hook: 无敌/无敌方模式 (游戏地址 0x004084FD)
NOENEMY_HOOK = {
    "name": "NoEnemy",
    "addr": "004084FD",
}

# Hook 组注册表: 名称 → (hook定义列表, 描述)
HOOK_GROUPS = {
    "skimfstdlg":    ([SKIMFSTDLG_HOOK],    "SkimFstDlg Hook (快速对话跳过)"),
    "notmpdatread":  ([NOTMPDATREAD_HOOK],  "NoTmpDatRead Hook (TmpDat读取拦截)"),
    "notmpdatwrite": ([NOTMPDATWRITE_HOOK], "NoTmpDatWrite Hook (TmpDat写入拦截)"),
    "noenemy":       ([NOENEMY_HOOK],       "NoEnemy Hook (无敌模式)"),
    "readsave":      ([READSAVE_HOOK],      "ReadSave Hook (存档加载拦截)"),
    "writesave":     ([WRITESAVE_HOOK],     "WriteSave Hook (存档保存拦截)"),
}

# 补丁组注册表: 名称 → (地址集合, 描述)
PATCH_GROUPS = {
    "wisdom":      (WISDOM_PATCH_ADDRS,      "智慧 WORD→BYTE 补丁 (9个)"),
    "benevolence": (BENEVOLENCE_PATCH_ADDRS,  "仁德 WORD→BYTE 补丁 (9个)"),
    "gold_cap":    (GOLD_CAP_PATCH_ADDRS,     "金钱上限 30K 扩展补丁 (9个)"),
    "money_field": (MONEY_FIELD_PATCH_ADDRS,  "金钱字段 WORD→DWORD 扩展补丁 (17个)"),
}


def find_patch_strings(data: bytearray) -> list[tuple[int, int, str]]:
    """扫描 DLL 二进制数据，找到所有形如 "0x004XXXXX,..." 的补丁定义字符串。

    Returns:
        list of (start_offset, end_offset, string_content)
    """
    strings = []
    i = 0
    while i < len(data) - 10:
        if data[i:i + 5] == b'0x004':
            end = i
            while end < len(data) and 32 <= data[end] < 127:
                end += 1
            s = data[i:end].decode('ascii', errors='replace')
            if ',' in s:
                strings.append((i, end, s))
            i = end + 1
        else:
            i += 1
    return strings


def remove_patches(data: bytearray, remove_addrs: set[str]) -> tuple[list, list]:
    """将匹配地址的补丁字符串清零。

    Returns:
        (removed_list, kept_list)  各为 [(offset, string), ...]
    """
    removed = []
    kept = []
    for off, end, s in find_patch_strings(data):
        addr = s.split(',')[0]
        if addr in remove_addrs:
            removed.append((off, s))
            for j in range(off, end):
                data[j] = 0x00
        else:
            kept.append((off, s))
    return removed, kept


def find_hook_entries(data: bytearray) -> list[tuple[int, int, str, str]]:
    """扫描 DLL 二进制数据，找到所有 Hook 定义条目。

    Hook 条目结构: [8字节地址ASCII] [8字节null] [16字节名称ASCII]
    通过扫描已知 Hook 名称来定位条目。

    Returns:
        list of (entry_offset, addr_offset, addr_string, name_string)
    """
    # 收集所有已知的 hook 名称
    all_names = set()
    for hooks, _ in HOOK_GROUPS.values():
        for h in hooks:
            all_names.add(h["name"])

    entries = []
    for name in all_names:
        name_bytes = name.encode('ascii')
        idx = 0
        while True:
            pos = data.find(name_bytes, idx)
            if pos == -1:
                break
            # 检查名称是否为 null 终止（后面是 \x00 或段尾）
            name_end = pos + len(name_bytes)
            if name_end < len(data) and data[name_end] != 0:
                idx = pos + 1
                continue
            # 向前找地址字符串: 在名称前 16 字节处
            # 布局: addr(pos-16..pos-8) + null(pos-8..pos) + name(pos..)
            addr_off = pos - 16
            if addr_off >= 0:
                addr_chunk = data[addr_off:addr_off + 8]
                if all(32 <= b < 127 for b in addr_chunk):
                    addr_str = addr_chunk.decode('ascii')
                    entry_off = addr_off
                    entries.append((entry_off, addr_off, addr_str, name))
            idx = pos + 1
    return entries


def remove_hooks(data: bytearray, hook_names: set[str]) -> tuple[list, list]:
    """将匹配名称的 Hook 条目的地址字符串清零。

    Args:
        data: DLL 二进制数据 (会被原地修改)
        hook_names: 要移除的 Hook 名称集合 (如 {"ReadSave", "WriteSave"})

    Returns:
        (removed_list, kept_list)  各为 [(offset, addr, name), ...]
    """
    removed = []
    kept = []
    for entry_off, addr_off, addr_str, name in find_hook_entries(data):
        if name in hook_names:
            removed.append((entry_off, addr_str, name))
            # 清零地址字符串 (8 字节)
            for j in range(addr_off, addr_off + 8):
                data[j] = 0x00
        else:
            kept.append((entry_off, addr_str, name))
    return removed, kept


def patch_ddraw(dll_path: Path, groups: list[str], backup: bool = True) -> None:
    """从 ddraw.dll 中移除指定的补丁组和/或 Hook。

    Args:
        dll_path: ddraw.dll 文件路径
        groups:   要移除的组名称列表
                  补丁组: "wisdom", "benevolence", "gold_cap"
                  Hook:   "readsave", "writesave"
                  特殊:   "all" (移除全部补丁和 Hook)
        backup:   是否先备份原文件
    """
    all_group_names = list(PATCH_GROUPS.keys()) + list(HOOK_GROUPS.keys())

    if "all" in groups:
        # "all" 排除 SkimFstDlg 和 NoEnemy — 快速对话跳过和无敌模式是基础功能，应保留
        groups = [g for g in all_group_names if g not in ("skimfstdlg", "noenemy")]

    # 分类: 补丁组 vs Hook 组
    addrs_to_remove = set()
    hooks_to_remove = set()
    for name in groups:
        if name in PATCH_GROUPS:
            addr_set, desc = PATCH_GROUPS[name]
            addrs_to_remove |= addr_set
            print(f"  将移除: {desc}")
        elif name in HOOK_GROUPS:
            hook_defs, desc = HOOK_GROUPS[name]
            for h in hook_defs:
                hooks_to_remove.add(h["name"])
            print(f"  将移除: {desc}")
        else:
            print(f"[WARN] 未知组: {name}, 跳过")

    if not addrs_to_remove and not hooks_to_remove:
        print("没有需要移除的补丁或 Hook")
        return

    # 备份
    if backup:
        bak = dll_path.with_suffix('.dll.bak')
        if not bak.exists():
            shutil.copy2(dll_path, bak)
            print(f"  备份: {bak}")

    # 读取
    data = bytearray(dll_path.read_bytes())

    # 移除补丁字符串
    if addrs_to_remove:
        removed, kept = remove_patches(data, addrs_to_remove)
        print(f"\n  [补丁] 移除了 {len(removed)} 个:")
        for off, s in removed:
            print(f"    [0x{off:06X}] {s}")
        print(f"\n  [补丁] 保留了 {len(kept)} 个:")
        for off, s in kept:
            print(f"    [0x{off:06X}] {s}")

    # 移除 Hook
    if hooks_to_remove:
        removed_h, kept_h = remove_hooks(data, hooks_to_remove)
        print(f"\n  [Hook] 移除了 {len(removed_h)} 个:")
        for entry_off, addr_str, name in removed_h:
            print(f"    [0x{entry_off:06X}] addr={addr_str} name={name}")
        print(f"\n  [Hook] 保留了 {len(kept_h)} 个:")
        for entry_off, addr_str, name in kept_h:
            print(f"    [0x{entry_off:06X}] addr={addr_str} name={name}")

    # 写回
    dll_path.write_bytes(data)
    print(f"\n  已保存到: {dll_path}")


def main():
    """CLI 入口"""
    import argparse

    # 默认 ddraw.dll 路径 (相对于本脚本)
    default_dll = Path(__file__).parent.parent / "tks_launcher_gui" / "tools" / "ddraw" / "ddraw.dll"

    parser = argparse.ArgumentParser(
        description="从 ddraw.dll 中移除指定的内存补丁字符串",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
补丁组:
  wisdom       智慧 WORD→BYTE 补丁 (9个)
  benevolence  仁德 WORD→BYTE 补丁 (9个)
  gold_cap     金钱上限 30K 扩展补丁 (9个)
  money_field  金钱字段 WORD→DWORD 扩展补丁 (17个)

Hook:
  skimfstdlg     SkimFstDlg Hook (快速对话跳过)
  notmpdatread   NoTmpDatRead Hook (TmpDat读取拦截)
  notmpdatwrite  NoTmpDatWrite Hook (TmpDat写入拦截)
  noenemy        NoEnemy Hook (无敌模式)
  readsave       ReadSave Hook (存档加载拦截)
  writesave      WriteSave Hook (存档保存拦截)

特殊:
  all          移除以上全部补丁和 Hook (共 44 补丁 + 6 Hook)

示例:
  python strip_ddraw_patches.py                              # 移除全部 (默认)
  python strip_ddraw_patches.py -g wisdom benevolence        # 只移除智慧/仁德
  python strip_ddraw_patches.py -g money_field               # 只移除金钱字段扩展
  python strip_ddraw_patches.py -g readsave writesave        # 只移除存档 Hook
  python strip_ddraw_patches.py -g all -d path/to/ddraw.dll
""",
    )
    parser.add_argument(
        "-d", "--dll", type=Path, default=default_dll,
        help=f"ddraw.dll 路径 (默认: {default_dll})",
    )
    parser.add_argument(
        "-g", "--groups", nargs="+", default=["all"],
        help="要移除的补丁组 (默认: all)",
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="不备份原文件",
    )

    args = parser.parse_args()

    if not args.dll.exists():
        print(f"[ERROR] 找不到: {args.dll}")
        sys.exit(1)

    print(f"目标: {args.dll}")
    print(f"操作: 移除补丁组 {args.groups}\n")

    patch_ddraw(args.dll, args.groups, backup=not args.no_backup)


if __name__ == "__main__":
    main()
