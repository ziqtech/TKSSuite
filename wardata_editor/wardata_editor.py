#!/usr/bin/env python3
"""
WarData.dat 可视化编辑器
=========================
逆向依据:
  - sub_42FDF8: WarData.dat 加载 (498字节/条, 219条, fopen/fread/fseek, 无LZSS)
  - sub_42FE70: WarWay.dat 加载 (1024字节/条, 100条, 32x32有符号字节网格)
  - sub_451600 + grp_editor: WSC.GRP 背景图加载 (RGB565 LZSS Frame A)
  - sub_4307CC: 战场初始化 — 解析 byte_9537D8 全部字段
  - sub_431428: 场景布置 — treasure放置/区域系统
  - sub_434D7C/sub_434188: 战场渲染 — 32x32网格遍历+地格特效
  - sub_4355C4: 网格更新循环 — -1永久障碍/0可通行/1-5特殊区域

WarData.dat 格式 (每条498字节, 219条, flat binary — sub_42FDF8):
  字段通过 TKS.exe反编译 + War.dll官方编辑器(战场编辑器v2.0) 双重验证:

  [0]     byte    flags       — sub_4307CC:200 &4=随机敌军; sub_43CA64:102 &2=失败条件
  [1]     byte    (reserved)  — 反编译未引用; 原误读为battle_id高字节, sub_436BD4:30 word_4EB728=a1实为函数参数
  [2-7]   byte[6] must_chars  — sub_4307CC:51 v20=&unk_9537DA (+1编码; 0/255=空)
  [8-29]  byte[22] (reserved) — 反编译未引用
  [30-31] uint16  name_id     — sub_43A8D8:39 word_9537F6→sub_4067E8(TKT)
  [32-33] uint16  map_id  — sub_42FE70:16; War.dll标签"地图编号"
  [34-69] uint16[18] enemy_id — sub_4307CC:219; War.dll标签"人物编号" (WarPC索引)
  [70-87] byte[18]  enemy_lv  — sub_4307CC:260; sub_444FD4:79; War.dll标签"等级范围"
  [88-105] byte[18] enemy_grp — sub_4307CC:217; sub_444FD4:26; 属性加成倍率(sub_4302D8:53); 0=普通士兵(可增援), >=1=将领(HP×N倍加成)
  [106-141] byte[36] enemy_lv_range — sub_4307CC:227; sub_444FD4:48; level params(18 pairs a3,a4)
                                18对X,Y(int8), X=106+2*i, Y=107+2*i
  [142-177] byte[36]  enemy_xy — sub_431428:94-98 grid coords(18 pairs int8 X,Y); War.dll"敌人朝向"
  [178-189] byte[12]  ally_xy   — sub_431428:74 unk_95388A; 6对X,Y(int8), 同enemy_xy格式
  [190-207] byte[18] enemy_del  — sub_4307CC:242 v9[102]; sub_444FD4:61; War.dll标签"属性加成"
  [208-213] byte[6] ally_facing — War.dll标签"我方朝向"; 6个友军朝向值(byte)
  [214-269] byte[56] trap_xy    — sub_431428:204 (char*)v43-172/-171; 28组陷阱/宝物坐标(int8对, 共享)
  [270-325] byte[56] trap_pwr   — sub_431428:296 (char*)v45-116/-115; 28组陷阱威力(min,max) byte
  [326-345] uint16[10] trea_sub — sub_431428:202; 10组宝物物品ID (TKItem, sub_431428:303)
  [346-385] uint16[20] trea_quant — sub_434510:36-37; 10对宝物数量(min,max) uint16
  [386-441] uint16[28] trap_type — sub_431428:199,295 unk_95395A; 28组陷阱类型 (1=山崩 2=泥沼 3=漩渦 4=火焰 5=滾木 6=瘴氣)
  ★ 已验证: offset 386-441 全为陷阱类型(1-6), 无TKItem ID; offset 270-325 全为陷阱威力(1-4)
    真正的宝物数据在 trea_sub(326-345) 和 trea_quant(346-385)
  [442-477] uint16[18] enemy_flg — sub_4307CC:263 v5[204]; sub_444FD4:81 word_953992
                                  bit0=精英, bit1=特殊, bit13/14=阵营标记
  [478]    byte    default_lv_p1 — sub_430578:17 byte_9539B6; level param default 1
  [480]    byte    default_lv_p2 — sub_430578:18 byte_9539B8; level param default 2
  [482-483] uint16 turn_limit — sub_43CA64:29 word_9539BA (>0时回合限制)
  [484-497] byte[14] (reserved) — 反编译未引用; 全219条数据为零

War.dll 官方编辑器(战场编辑器v2.0)证据:
  - sub_401DE5: 读取→UI填充, sub_4024B4: UI→保存回写
  - 编辑控件: a1+140(人物编号) a1+212(等级范围) a1+284(人物归属)
              a1+356(敌人位置) a1+428(敌人朝向) a1+500(我方位置)
              a1+572(属性加成) a1+644(我方朝向) a1+716(物品编号)
              a1+788(物品数量) a1+860(地图编号)
  - 记录访问: *(a3+880) + 498*(a2+1) — 1-based索引, 跳过文件首498字节
  - 69条战斗名称硬编码于DLL字符串表(0x66A8起)

WarWay.dat 格式 (每条1024字节, 共100条, 32x32有符号字节网格):
  值语义 (sub_4355C4 + sub_431428):
    -1 (0xFF): 障碍物/不可通行 — sub_4355C4更新循环跳过, 永久不变
     0 (0x00): 普通可通行地面 — 默认值, 不触发特效
     1-5:      特殊区域/放置区 — sub_431428:106取值分组, sub_434D7C:60触发地格特效

用法: python wardata_editor.py
"""

import struct, os, sys, random, tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

HAS_PIL = False
try:
    from PIL import Image, ImageTk, ImageDraw
    HAS_PIL = True
except ImportError:
    pass

# ── 常量 ──────────────────────────────────────────────
WAR_REC_SIZE = 498    # sub_42FDF8: 498字节/条
WAR_REC_COUNT = 219   # 109062 / 498 = 219
WSC_ENTRIES = 84      # WSC.IDX: 336/4 = 84条目

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 12

# ═══════════════════════════════════════════════════════════
# LZSS 解压 (sub_452B14, 兼容 grp_editor 格式)
# ═══════════════════════════════════════════════════════════

RING_SIZE, RING_INIT, RING_INIT_VAL = 4096, 4078, 0x20

def lzss_decompress(data: bytes, target_size: int) -> bytes:
    ring = bytearray([RING_INIT_VAL] * RING_SIZE)
    ring_pos, pos = RING_INIT, 0
    out = bytearray()
    while pos < len(data) and len(out) < target_size:
        flag = data[pos]; pos += 1
        for bit in range(8):
            if pos >= len(data) or len(out) >= target_size:
                break
            if flag & (1 << bit):
                b = data[pos]; pos += 1; out.append(b)
                ring[ring_pos % RING_SIZE] = b; ring_pos += 1
            else:
                if pos + 2 > len(data): break
                b1, b2 = data[pos], data[pos + 1]; pos += 2
                offset = b1 | ((b2 & 0xF0) << 4)
                length = (b2 & 0x0F) + 3
                for k in range(length):
                    b = ring[(offset + k) % RING_SIZE]; out.append(b)
                    ring[ring_pos % RING_SIZE] = b; ring_pos += 1
    return bytes(out[:target_size])

# RGB565 -> RGBA 查找表
_RGB565_LUT = bytearray(65536 * 3)
for _v in range(65536):
    r5 = (_v >> 11) & 0x1F; g6 = (_v >> 5) & 0x3F; b5 = _v & 0x1F
    _RGB565_LUT[_v * 3] = (r5 << 3) | (r5 >> 2)
    _RGB565_LUT[_v * 3 + 1] = (g6 << 2) | (g6 >> 4)
    _RGB565_LUT[_v * 3 + 2] = (b5 << 3) | (b5 >> 2)

def rgb565_to_rgba(raw: bytes, w: int, h: int) -> bytes:
    total = w * h; rgba = bytearray(total * 4)
    for i in range(min(total, len(raw) // 2)):
        lo = raw[i * 2]; hi = raw[i * 2 + 1]
        off3 = (lo | (hi << 8)) * 3; off4 = i * 4
        rgba[off4:off4 + 3] = _RGB565_LUT[off3:off3 + 3]
        rgba[off4 + 3] = 255
    return bytes(rgba)

def rle_bp_decompress(data: bytes, target_size: int) -> bytes:
    out = bytearray(); pos = 0
    while pos + 1 < len(data) and len(out) < target_size:
        count = data[pos]; value = data[pos + 1]; pos += 2
        out.extend(bytes([value] * count))
    return bytes(out[:target_size])

def rle_bp_probe(data: bytes, expected_size: int) -> bool:
    total, pos = 0, 0
    while pos + 1 < len(data):
        total += data[pos]; pos += 2
    return total == expected_size


# ═══════════════════════════════════════════════════════════
# WSC.GRP 战场背景图加载 (基于 grp_editor 解码逻辑)
# ═══════════════════════════════════════════════════════════

def load_wsc_idx(idx_path: str) -> list:
    """加载 WSC.IDX — 返回84个GRP偏移量 (uint32 each)"""
    data = Path(idx_path).read_bytes()
    count = len(data) // 4
    return [struct.unpack_from('<I', data, i * 4)[0] for i in range(count)]

def load_wsc_entry(grp_path: str, idx_offsets: list, entry_index: int):
    """加载 WSC.GRP 中第 entry_index 个条目, 返回 (width, height, rgba_bytes) 或 None"""
    if not HAS_PIL:
        return None
    if entry_index < 0 or entry_index >= len(idx_offsets) - 1:
        return None

    data = Path(grp_path).read_bytes()
    offset = idx_offsets[entry_index]
    end_offset = idx_offsets[entry_index + 1]
    chunk = data[offset:end_offset]

    if len(chunk) < 12:
        return None

    # 解析 header: width, height, comp_a, comp_b (uint16:2 + uint32:2 = 12 bytes)
    w, h, ca, cb = struct.unpack_from('<HHII', chunk, 0)
    if w == 0 or h == 0 or w > 4096 or h > 4096:
        return None

    # Frame A: RGB565 LZSS 压缩
    fa_off = 12
    if fa_off + 4 > len(chunk):
        return None
    uncomp_sz = struct.unpack_from('<I', chunk, fa_off)[0]
    lzss_data = chunk[fa_off + 4 : fa_off + ca]
    raw_a = lzss_decompress(lzss_data, min(uncomp_sz, w * h * 2))

    if len(raw_a) < w * h * 2:
        raw_a = raw_a + b'\x00' * (w * h * 2 - len(raw_a))

    rgba = rgb565_to_rgba(raw_a, w, h)
    return (w, h, rgba)


# ═══════════════════════════════════════════════════════════
# WarData.dat 加载/保存 (sub_42FDF8: 498字节/条, flat binary)
# ═══════════════════════════════════════════════════════════

def load_warway(filepath: str, map_id: int) -> bytes:
    """加载 WarWay.dat 中指定 map_id 的 1024 字节 32x32 网格"""
    if not filepath or not os.path.exists(filepath):
        return None
    data = Path(filepath).read_bytes()
    off = map_id * 1024
    if off + 1024 > len(data):
        return None
    return data[off:off + 1024]


def load_wardata(filepath: str) -> list:
    """加载 WarData.dat, 返回 dict 列表 (每条498字节解析为字段)"""
    data = Path(filepath).read_bytes()
    count = len(data) // WAR_REC_SIZE
    records = []
    for i in range(count):
        off = i * WAR_REC_SIZE
        chunk = data[off:off + WAR_REC_SIZE]

        rec = {'index': i}
        # 解析已知字段
        rec['battle_id'] = i  # 战场序号即记录索引, 文件offset0不存储battle_id
        rec['flags'] = chunk[0]  # byte, bit1/bit2 (sub_4307CC:200, sub_43CA64:102)
        rec['must_chars'] = list(chunk[2:8])  # 6 bytes, +1 encoded
        # offset 8-29: reserved (22 bytes)
        rec['battle_name_id'] = struct.unpack_from('<H', chunk, 30)[0]  # sub_43A8D8:39 word_9537F6→TKT文本
        rec['map_id'] = struct.unpack_from('<H', chunk, 32)[0]

        # 18敌军槽位
        rec['enemy_ids'] = list(struct.unpack_from('<' + 'H' * 18, chunk, 34))
        rec['enemy_lv'] = list(chunk[70:88])
        rec['enemy_power'] = list(chunk[88:106])  # 属性加成倍率: 0=普通士兵, >=1=将领(Boss)属性加成
        rec['enemy_lv_range'] = list(struct.unpack_from('<' + 'b' * 36, chunk, 106))  # lv params (a3,a4), sub_430578  # X=106+2*i, Y=107+2*i

        # 敌人朝向: War.dll标签"敌人朝向"; sub_431428:94 (char*)v32+108
        rec['enemy_xy'] = list(struct.unpack_from('<' + 'b' * 36, chunk, 142))  # grid coords (18 pairs X,Y), sub_431428  # byte[36] place_req, sub_431428:94-98

        # 友军坐标: sub_431428:74 unk_95388A — 6对int8 (X,Y), 同 enemy_xy格式
        rec['ally_xy'] = list(struct.unpack_from('<' + 'b' * 12, chunk, 178))

        # 敌军时序(Delay): sub_4307CC:242 v9[102]; sub_444FD4:61; War.dll标签"属性加成"
        rec['enemy_delay'] = list(chunk[190:208])

        # 友军朝向: War.dll标签"我方朝向"
        rec['ally_facing'] = list(chunk[208:214])

        # 28组陷阱+宝物数据 (sub_431428:198-323, 共用XY坐标)
        rec['trap_xy'] = list(struct.unpack_from('<' + 'b' * 56, chunk, 214))    # X,Y坐标 28对 (陷阱/宝物共享)
        rec['trap_pwr'] = list(chunk[270:326])                                     # 陷阱威力(min,max) 28对 byte
        rec['trea_sub'] = list(struct.unpack_from('<' + 'H' * 10, chunk, 326))    # 宝物物品ID 10组 (TKItem)
        rec['trea_quant'] = list(struct.unpack_from('<' + 'H' * 20, chunk, 346))  # 宝物数量(min,max) 10对 uint16
        rec['trap_type'] = list(struct.unpack_from('<' + 'H' * 28, chunk, 386))   # 陷阱类型 28组 (1-6)

        # 敌军标志位: sub_4307CC:263 v5[204]; sub_444FD4:81 word_953992
        rec['enemy_flags'] = list(struct.unpack_from('<' + 'H' * 18, chunk, 442))

        # 默认敌军坐标: sub_430578:17-18 byte_9539B6/byte_9539B8
        rec['default_lv_p1'] = chunk[478]  # lv param default 1, sub_430578:17
        rec['default_lv_p2'] = chunk[480]  # lv param default 2, sub_430578:18
        rec['battle_turn_limit'] = struct.unpack_from('<H', chunk, 482)[0]  # sub_43CA64:29 word_9539BA

        # 保存原始字节 (用于未解析字段)
        rec['_raw'] = chunk
        records.append(rec)
    return records


def save_wardata(filepath: str, records: list):
    """保存 WarData.dat — 更新已知字段到原始字节, 写回文件"""
    buf = bytearray(len(records) * WAR_REC_SIZE)
    for rec in records:
        i = rec['index']
        off = i * WAR_REC_SIZE
        chunk = bytearray(rec['_raw'])

        # 回写已知字段
        chunk[0] = rec['flags'] & 0xFF  # offset 0: flags (byte)
        for j in range(6):
            chunk[2 + j] = rec['must_chars'][j] & 0xFF
        struct.pack_into('<H', chunk, 30, rec['battle_name_id'])
        struct.pack_into('<H', chunk, 32, rec['map_id'])

        for j in range(18):
            struct.pack_into('<H', chunk, 34 + j * 2, rec['enemy_ids'][j])
            chunk[70 + j] = rec['enemy_lv'][j] & 0xFF
            chunk[88 + j] = rec['enemy_power'][j] & 0xFF

        for j in range(36):
            struct.pack_into('<b', chunk, 106 + j, rec['enemy_lv_range'][j])

        # 敌人朝向/place_req: byte[36] at offset 142-177
        for j in range(36):
            struct.pack_into('<b', chunk, 142 + j, rec['enemy_xy'][j])

        # 友军坐标: int8[12] at offset 178-189 (6对 X,Y)
        for j in range(12):
            struct.pack_into('<b', chunk, 178 + j, rec['ally_xy'][j])

        for j in range(18):
            chunk[190 + j] = rec['enemy_delay'][j] & 0xFF
        for j in range(6):
            chunk[208 + j] = rec['ally_facing'][j] & 0xFF

        for j in range(56):
            struct.pack_into('<b', chunk, 214 + j, rec['trap_xy'][j])

        for j in range(56):
            chunk[270 + j] = rec['trap_pwr'][j] & 0xFF

        for j in range(10):
            struct.pack_into('<H', chunk, 326 + j * 2, rec['trea_sub'][j])

        for j in range(20):
            struct.pack_into('<H', chunk, 346 + j * 2, rec['trea_quant'][j])

        for j in range(28):
            struct.pack_into('<H', chunk, 386 + j * 2, rec['trap_type'][j])

        for j in range(18):
            struct.pack_into('<H', chunk, 442 + j * 2, rec['enemy_flags'][j])

        chunk[478] = rec['default_lv_p1'] & 0xFF  # lv param default 1
        chunk[480] = rec['default_lv_p2'] & 0xFF  # lv param default 2
        struct.pack_into('<H', chunk, 482, rec['battle_turn_limit'])

        buf[off:off + WAR_REC_SIZE] = chunk

    # 备份旧文件
    if os.path.exists(filepath):
        bak = filepath + '.bak'
        if not os.path.exists(bak):
            Path(filepath).rename(bak)
    Path(filepath).write_bytes(bytes(buf))


# ═══════════════════════════════════════════════════════════
# TKT 文本加载 (sub_4067E8)
# ═══════════════════════════════════════════════════════════

def load_tkt(tkt_path: str) -> dict:
    """加载 TKT.dat, 返回 {id: text} 映射"""
    if not tkt_path or not os.path.exists(tkt_path):
        return {}
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]
    cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8 + ts]
    dec = bytes([b ^ 0xFF for b in enc])
    idsz = cnt * 4; ofsz = cnt * 4; lookup = {}
    SKIP = set(range(0, 10))
    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i * 4)[0]
        if eid in SKIP:
            continue
        off = struct.unpack_from('<I', dec, idsz + i * 4)[0]
        ao = idsz + ofsz + off
        if ao < len(dec):
            end = ao
            while end < len(dec) and dec[end] != 0:
                end += 1
            txt = dec[ao:end].replace(b'\x1e', b'\n')
            try:
                s = txt.decode('big5', errors='replace')
            except:
                s = txt.decode('gbk', errors='replace')
            if s and s != '0':
                lookup[eid] = s.split('\n')[0].strip()
    return lookup


def load_warpc_names(warpc_path: str, tkt: dict) -> dict:
    """加载 WarPC.dat, 返回 {warpc_index: character_name} 映射
    WarPC 每条1054字节(527×int16), LZSS压缩, field[0]=name_id
    """
    if not warpc_path or not os.path.exists(warpc_path):
        return {}
    with open(warpc_path, 'rb') as f:
        raw = f.read()
    # LZSS decompress (same as other DAT files)
    ts = struct.unpack_from('<I', raw, 0)[0]
    bs = struct.unpack_from('<I', raw, 4)[0]
    w = bytearray([0x20] * 4096); wp = 4078
    out = bytearray(); flags = 0; pos = 12; bc = 4
    while bc < bs:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(raw): break
            flags = raw[pos] | 0xFF00; pos += 1; bc += 1
        if flags & 1:
            if pos >= len(raw): break
            b = raw[pos]; pos += 1; bc += 1
            out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(raw): break
            b1, b2 = raw[pos], raw[pos + 1]; pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1; rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]; out.append(b)
                w[wp] = b; wp = (wp + 1) & 0xFFF
    dec = bytes(out[:ts])

    WARPC_REC = 1054
    count = len(dec) // WARPC_REC
    names = {}
    for i in range(count):
        off = i * WARPC_REC
        name_id = struct.unpack_from('<h', dec, off)[0]
        if name_id and name_id in tkt:
            names[i] = tkt[name_id]
        elif name_id:
            names[i] = f"PC#{i}"
        else:
            names[i] = f"(空#{i})"
    return names


def load_tkitem_names(tkitem_path: str, tkt: dict) -> dict:
    """加载 TKItem.dat, 返回 {item_index: item_name} 映射
    TKItem 每条64字节(32×int16), LZSS压缩, field[2]=name_id → TKT
    """
    if not tkitem_path or not os.path.exists(tkitem_path):
        return {}
    with open(tkitem_path, 'rb') as f:
        raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]
    bs = struct.unpack_from('<I', raw, 4)[0]
    w = bytearray([0x20] * 4096); wp = 4078
    out = bytearray(); flags = 0; pos = 12; bc = 4
    while bc < bs:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(raw): break
            flags = raw[pos] | 0xFF00; pos += 1; bc += 1
        if flags & 1:
            if pos >= len(raw): break
            b = raw[pos]; pos += 1; bc += 1
            out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(raw): break
            b1, b2 = raw[pos], raw[pos + 1]; pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1; rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]; out.append(b)
                w[wp] = b; wp = (wp + 1) & 0xFFF
    dec = bytes(out[:ts])

    ITEM_REC = 64
    count = len(dec) // ITEM_REC
    by_index = {}   # 记录索引 → 名称 (trea_id 用)
    by_item_id = {} # item_id → 名称   (trea_sub 用)
    for i in range(count):
        off = i * ITEM_REC
        item_id = struct.unpack_from('<h', dec, off)[0]
        name_id = struct.unpack_from('<h', dec, off + 4)[0]
        if item_id <= 1:  # 空槽/占位
            continue
        if name_id and name_id in tkt:
            item_name = tkt[name_id]
        elif name_id:
            item_name = f"Item#{item_id}"
        else:
            continue
        by_index[i] = item_name
        by_item_id[item_id] = item_name
    return (by_index, by_item_id)


# ═══════════════════════════════════════════════════════════
# GUI 编辑器
# ═══════════════════════════════════════════════════════════

class WarDataEditor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WarData.dat 可视化编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1400x860")
        self.root.minsize(1100, 700)

        # 数据状态
        self.wardata_path = None
        self.warway_path = None
        self.warway_grid = None
        self.wsc_grp_path = None
        self.wsc_idx_path = None
        self.tkt_path = None
        self.warpc_path = None
        self.warpc_names = {}
        self.tkitem_path = None
        self.tkitem_names = {}
        self.tkitem_names_by_id = {}
        self.records = []
        self.wsc_offsets = []
        self.tkt = {}
        self._dirty = False
        self._current_idx = -1

        # 场景预览状态
        self._wsc_cache = {}
        self._wsc_res_cache = {}  # map_id → (width, height)
        self._preview_zoom = 0.5
        self._drag_target = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._last_resolved_enemies = {}
        self._last_resolved_treas = {}
        self._last_resolved_allies = {}
        self._last_fixed_trea_indices = set()
        self._last_fixed_enemy_slots = set()
        self._last_active_slots = 18
        self._last_enemy_zone_reqs = []
        self._last_trea_zone_reqs = []

        self._build_ui()
        self._set_edit_enabled(False)

        # 居中窗口
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1400) // 2
        y = (sh - 860) // 2
        self.root.geometry(f'1400x860+{x}+{y}')

    def _build_ui(self):
        # ── 菜单栏 ──
        mb = tk.Menu(self.root); self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="另存为…", command=self._save_as)
        fm.add_separator()
        fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)

        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="新增战场", command=self._new_battle, accelerator="Ctrl+N")
        em.add_command(label="复制当前记录", command=self._copy_record)
        em.add_command(label="删除当前记录", command=self._delete_record)
        mb.add_cascade(label="编辑", menu=em)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段参考 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)

        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_battle())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── 工具栏 ──
        tb = ttk.Frame(self.root); tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.search_var, width=20)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # ── 主 PanedWindow ──
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ── 左侧: TreeView 战斗列表 ──
        self._build_left_panel()

        # ── 右侧: Notebook 标签页 ──
        self._build_right_panel()

        # ── 底部状态栏 ──
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_wardata = ttk.Label(pf, text="", foreground="gray")
        self.lbl_wardata.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_warway = ttk.Label(pf, text="", foreground="gray")
        self.lbl_warway.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_wsc = ttk.Label(pf, text="", foreground="gray")
        self.lbl_wsc.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray")
        self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_extra = ttk.Label(pf, text="", foreground="gray")
        self.lbl_extra.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_left_panel(self):
        lf = ttk.Frame(self.paned); self.paned.add(lf, weight=1)
        cols = ('index', 'map_info', 'enemy_count', 'trea_count', 'trap_count', 'trea_detail', 'chars_info', 'flags_info')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        col_config = [
            ('index', '序号', 40),
            ('map_info', '地图', 80),
            ('enemy_count', '敌军数', 40),
            ('trea_count', '宝物数', 40),
            ('trap_count', '陷阱数', 40),
            ('trea_detail', '固定/随机', 64),
            ('chars_info', '参战人物', 120),
            ('flags_info', '参数', 70),
        ]
        for cid, cn, cw in col_config:
            self.tree.heading(cid, text=cn)
            self.tree.column(cid, width=cw, anchor='center' if cid not in ('chars_info', 'flags_info') else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

    def _get_wsc_resolution(self, map_id):
        """获取 WSC 背景图原始分辨率 (仅读header, 缓存)"""
        if map_id in self._wsc_res_cache:
            return self._wsc_res_cache[map_id]
        if not self.wsc_grp_path or not self.wsc_offsets:
            return None
        if map_id < 0 or map_id >= len(self.wsc_offsets) - 1:
            return None
        # 仅读取 header 获取分辨率, 避免完整LZSS解压
        try:
            data = Path(self.wsc_grp_path).read_bytes()
            offset = self.wsc_offsets[map_id]
            if offset + 12 > len(data):
                return None
            w, h = struct.unpack_from('<HH', data, offset)
            if w == 0 or h == 0 or w > 4096 or h > 4096:
                return None
            self._wsc_res_cache[map_id] = (w, h)
            return (w, h)
        except Exception:
            return None

    def _trea_detail_str(self, rec):
        """返回宝物摘要: "固N/随M" """
        fixed = random_trea = 0
        for i in range(10):
            if rec['trea_sub'][i] <= 0: continue
            tx = rec['trap_xy'][i * 2]
            if tx >= 0: fixed += 1
            else: random_trea += 1
        return f"固{fixed}/随{random_trea}" if fixed or random_trea else "-"

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for rec in self.records:
            enemy_count = sum(1 for eid in rec['enemy_ids'] if eid > 0)
            trea_count = sum(1 for i in range(10) if rec['trea_sub'][i] > 0)
            trap_count = sum(1 for i in range(28) if 1 <= self._trap_type_at(rec, i) <= 6)
            trea_detail = self._trea_detail_str(rec)
            # 地图列: map_id + 分辨率
            mid = rec['map_id']
            res = self._get_wsc_resolution(mid)
            if res:
                map_info = f"{mid} ({res[0]}x{res[1]})"
            else:
                map_info = str(mid)
            # 参战人物: 敌军角色 (enemy_ids), 去重后前三个，多余显示"等"
            enemy_names = []
            seen = set()
            for eid in rec['enemy_ids']:
                if eid > 0 and eid not in seen:
                    seen.add(eid)
                    enemy_names.append(self._enemy_name(eid))
            if enemy_names:
                names = [n[:4] for n in enemy_names[:3]]
                chars_info = ','.join(names)
                if len(enemy_names) > 3:
                    chars_info += '等'
            else:
                chars_info = '-'
            flags = rec['flags']
            flag_parts = []
            if flags & 2: flag_parts.append('续')
            if flags & 4: flag_parts.append('随')
            flags_info = ','.join(flag_parts) if flag_parts else '-'
            self.tree.insert('', 'end',
                values=(rec['index'], map_info, enemy_count, trea_count,
                        trap_count, trea_detail, chars_info, flags_info))

    def _build_right_panel(self):
        rf = ttk.Frame(self.paned); self.paned.add(rf, weight=3)
        self.notebook = ttk.Notebook(rf)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # 7个标签页
        self.tab_scene = ttk.Frame(self.notebook)
        self.tab_enemy = ttk.Frame(self.notebook)
        self.tab_ally = ttk.Frame(self.notebook)
        self.tab_drops = ttk.Frame(self.notebook)
        self.tab_traps = ttk.Frame(self.notebook)
        self.tab_params = ttk.Frame(self.notebook)
        self.tab_allparams = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_scene, text="场景预览")
        self.notebook.add(self.tab_enemy, text="敌军配置")
        self.notebook.add(self.tab_ally, text="友军配置")
        self.notebook.add(self.tab_drops, text="宝物/奖励")
        self.notebook.add(self.tab_traps, text="陷阱")
        self.notebook.add(self.tab_params, text="战场参数")
        self.notebook.add(self.tab_allparams, text="全部参数")

        self._build_params_tab()
        self._build_allparams_tab()
        self._build_enemy_tab()
        self._build_ally_tab()
        self._build_drops_tab()
        self._build_trap_tab()
        self._build_scene_tab()

    def _set_edit_enabled(self, enabled: bool):
        state = 'normal' if enabled else 'disabled'
        # Will be expanded as tabs are built

    def _update_paths(self):
        """更新底部状态栏各文件路径显示 (与 item_editor 样式一致)"""
        g, r = "#228B22", "#CC3333"
        def _f(lb, p):
            if not p: lb.config(text="(未加载)", foreground=r)
            elif not os.path.exists(p): lb.config(text=f"(不存在){p}", foreground=r)
            else: lb.config(text=p, foreground=g)
        _f(self.lbl_wardata, self.wardata_path)
        _f(self.lbl_warway, self.warway_path)
        if self.wsc_grp_path:
            _f(self.lbl_wsc, self.wsc_grp_path)
        else:
            self.lbl_wsc.config(text="WSC: (未加载)", foreground=r)
        _f(self.lbl_tkt, self.tkt_path)
        extra_parts = []
        if self.warpc_path and os.path.exists(self.warpc_path):
            extra_parts.append(f"WarPC: {len(self.warpc_names)}人")
        if self.tkitem_path and os.path.exists(self.tkitem_path):
            extra_parts.append(f"TKItem: {len(self.tkitem_names)}件")
        if extra_parts:
            self.lbl_extra.config(text=" | ".join(extra_parts), foreground=g)
        else:
            self.lbl_extra.config(text="(WarPC/TKItem: 未加载)", foreground=r)

    # ── Task 6: File loading ──

    def _load_tks_dir(self):
        """加载 TKS 游戏目录 — 自动检测所有关联文件"""
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d:
            return

        wd = os.path.join(d, 'WarData.dat')
        ww = os.path.join(d, 'WarWay.dat')
        wsc_g = os.path.join(d, 'WSC.GRP')
        wsc_i = os.path.join(d, 'WSC.IDX')
        tkt = os.path.join(d, 'TKT.dat')
        warpc = os.path.join(d, 'WarPC.dat')
        tkitem = os.path.join(d, 'TKItem.dat')

        missing = []
        for p, n in [(wd, 'WarData.dat'), (ww, 'WarWay.dat'), (wsc_g, 'WSC.GRP'),
                      (wsc_i, 'WSC.IDX'), (tkt, 'TKT.dat'), (warpc, 'WarPC.dat'),
                      (tkitem, 'TKItem.dat')]:
            if not os.path.exists(p):
                missing.append(n)

        if missing:
            if 'WarData.dat' in missing:
                messagebox.showerror("错误", f"缺少必要文件 WarData.dat")
                return
            messagebox.showwarning("警告",
                f"以下文件未找到, 相关功能将受限:\n  " + "\n  ".join(missing))

        self.wardata_path = wd
        self.warway_path = ww if os.path.exists(ww) else None
        self.wsc_grp_path = wsc_g if os.path.exists(wsc_g) else None
        self.wsc_idx_path = wsc_i if os.path.exists(wsc_i) else None
        self.tkt_path = tkt if os.path.exists(tkt) else None
        self.warpc_path = warpc if os.path.exists(warpc) else None
        self.tkitem_path = tkitem if os.path.exists(tkitem) else None

        self.records = load_wardata(self.wardata_path)
        if self.wsc_idx_path:
            self.wsc_offsets = load_wsc_idx(self.wsc_idx_path)
        else:
            self.wsc_offsets = []
        self.tkt = load_tkt(self.tkt_path) if self.tkt_path else {}
        self.warpc_names = load_warpc_names(self.warpc_path, self.tkt) if self.warpc_path else {}
        if self.tkitem_path:
            self.tkitem_names, self.tkitem_names_by_id = load_tkitem_names(self.tkitem_path, self.tkt)
        else:
            self.tkitem_names, self.tkitem_names_by_id = {}, {}

        self._wsc_cache.clear()
        self._wsc_res_cache.clear()
        self._refresh_tree()
        self._set_edit_enabled(True)
        self._dirty = False

        # 底部状态栏: 各文件路径 (与 item_editor 样式一致)
        self._update_paths()
        self.status_var.set(f"已加载 {len(self.records)} 场战斗")

    def _char_name(self, warpc_idx):
        """WarPC角色索引 → 角色名称 (via WarPC.name_id → TKT)
        WarPC[0-34]=玩家/独特角色, WarPC[35-142]=敌军角色.
        must_chars 用 v-1 解码得到 0-34 的玩家索引。
        enemy_ids 需 +35 得到敌军索引, 调用方应使用 _enemy_name()."""
        if warpc_idx in self.warpc_names:
            return self.warpc_names[warpc_idx]
        return f"PC#{warpc_idx}" if warpc_idx >= 0 else "?"

    def _enemy_name(self, enemy_id):
        """敌军角色ID → 角色名称 (enemy_id + 35 = WarPC索引)"""
        return self._char_name(enemy_id + 35)

    def _battle_name(self, rec):
        """生成战斗名称 — 使用 battle_id 或 must_chars 推断"""
        bid = rec['battle_id']
        chars = [c for c in rec['must_chars'] if c > 0 and c != 255]
        if chars:
            names = []
            for c in chars[:3]:
                cid = c - 1  # +1编码解码
                names.append(self._char_name(cid))
            return f"#{bid} " + ",".join(names) if names else f"战场#{bid}"
        return f"战场#{bid}"

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for rec in self.records:
            # 搜索范围: 序号/地图ID/敌军角色名
            enemy_names = []
            seen = set()
            for eid in rec['enemy_ids']:
                if eid > 0 and eid not in seen:
                    seen.add(eid)
                    enemy_names.append(self._enemy_name(eid))
            char_names = ','.join(enemy_names) if enemy_names else ''
            if query and query not in str(rec['index']) and query not in str(rec['map_id']) \
               and query not in char_names.lower():
                continue
            enemy_count = sum(1 for eid in rec['enemy_ids'] if eid > 0)
            trea_count = sum(1 for i in range(10) if rec['trea_sub'][i] > 0)
            trap_count = sum(1 for i in range(28) if 1 <= self._trap_type_at(rec, i) <= 6)
            trea_detail = self._trea_detail_str(rec)
            # 地图列: map_id + 分辨率
            mid = rec['map_id']
            res = self._get_wsc_resolution(mid)
            if res:
                map_info = f"{mid} ({res[0]}x{res[1]})"
            else:
                map_info = str(mid)
            # 参战人物: 敌军角色 (enemy_ids), 去重后前三个，多余显示"等"
            if enemy_names:
                names = [n[:4] for n in enemy_names[:3]]
                chars_info = ','.join(names)
                if len(enemy_names) > 3:
                    chars_info += '等'
            else:
                chars_info = '-'
            flags = rec['flags']
            flag_parts = []
            if flags & 2: flag_parts.append('续')
            if flags & 4: flag_parts.append('随')
            flags_info = ','.join(flag_parts) if flag_parts else '-'
            self.tree.insert('', 'end',
                values=(rec['index'], map_info, enemy_count, trea_count,
                        trap_count, trea_detail, chars_info, flags_info))

    def _clear_filter(self):
        self.search_var.set('')
        self._refresh_tree()

    def _reload(self):
        if not self.wardata_path:
            return
        self.records = load_wardata(self.wardata_path)
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.warpc_names = load_warpc_names(self.warpc_path, self.tkt) if self.warpc_path else {}
            if self.tkitem_path:
                self.tkitem_names, self.tkitem_names_by_id = load_tkitem_names(self.tkitem_path, self.tkt)
        self._refresh_tree()
        self._dirty = False
        self.status_var.set("已重新加载")

    # ── Task 7: Tree selection + Save ──

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        values = self.tree.item(sel[0], 'values')
        idx = int(values[0])
        self._current_idx = idx
        self._populate_fields(self.records[idx])

    def _populate_fields(self, rec):
        """将记录填充到各标签页的编辑控件"""
        self._current_idx = rec['index']
        self._populate_params_tab(rec)
        self._populate_allparams_tab(rec)
        self._populate_enemy_tab(rec)
        self._populate_ally_tab(rec)
        self._populate_drops_tab(rec)
        self._populate_trap_tab(rec)
        self._redraw_scene()

    def _save(self):
        if not self.wardata_path or not self.records:
            messagebox.showinfo("提示", "请先加载数据")
            return
        if not messagebox.askyesno("确认保存",
            f"保存 {len(self.records)} 条到:\n{self.wardata_path}\n\n原文件将被覆盖 (生成 .bak)."):
            return
        self._apply_current_edit()
        save_wardata(self.wardata_path, self.records)
        self._dirty = False
        self.status_var.set("已保存")

    def _save_as(self):
        fp = filedialog.asksaveasfilename(
            title="另存 WarData.dat",
            defaultextension=".dat",
            filetypes=[("DAT files", "*.dat"), ("All files", "*.*")])
        if fp:
            self._apply_current_edit()
            save_wardata(fp, self.records)
            self.wardata_path = fp
            self._dirty = False
            self.status_var.set(f"已另存为 {fp}")

    def _apply_current_edit(self):
        """Apply edits from current tab to the record"""
        if self._current_idx < 0:
            return
        rec = self.records[self._current_idx]
        self._apply_params_tab(rec)
        self._apply_allparams_tab(rec)
        self._apply_enemy_tab(rec)
        self._apply_ally_tab(rec)
        self._apply_drops_tab(rec)
        self._apply_trap_tab(rec)

    def _on_close(self):
        if self._dirty:
            if messagebox.askyesno("未保存", "有未保存的修改，是否保存后退出?"):
                self._save()
        self.root.quit()

    # ── 记录管理 ──

    def _new_battle(self):
        """新增战场记录"""
        if not self.records:
            return
        new_idx = len(self.records)
        template = bytearray(WAR_REC_SIZE)
        rec = {
            'index': new_idx,
            'battle_id': new_idx,
            'flags': 0,
            'must_chars': [0] * 6,
            'battle_name_id': 0,
            'map_id': 0,
            'enemy_ids': [0] * 18,
            'enemy_lv': [0] * 18,
            'enemy_power': [0] * 18,  # 属性加成倍率: 0=普通士兵, >=1=将领属性加成(HP×N倍等)
            'enemy_lv_range': [0] * 36,  # lv params (a3,a4)
            'enemy_delay': [0] * 18,
            'enemy_xy': [0] * 36,     # byte[36] grid coords (18 pairs X,Y)
            'ally_xy': [0] * 12,      # int8[12] 6对(X,Y), 同 enemy_xy格式
            'ally_facing': [0] * 6,    # byte[6]    "我方朝向"
            'trap_xy': [0] * 56,
            'trap_pwr': [0] * 56,  # 陷阱威力(min,max) 28对 byte
            'trea_sub': [0] * 10,
            'trea_quant': [0] * 20,  # 10对(min,max) uint16
            'trap_type': [0] * 28,
            'enemy_flags': [0] * 18,
            'default_lv_p1': 0,  # lv param default 1
            'default_lv_p2': 0,  # lv param default 2
            'battle_turn_limit': 0,
            '_raw': bytes(template),
        }
        self.records.append(rec)
        self._refresh_tree()
        self._dirty = True
        self.status_var.set(f"已新增战场 #{new_idx}")

    def _copy_record(self):
        """复制当前记录"""
        if self._current_idx < 0:
            return
        src = self.records[self._current_idx]
        new_idx = len(self.records)
        import copy
        rec = copy.deepcopy(src)
        rec['index'] = new_idx
        rec['battle_id'] = new_idx
        rec['_raw'] = bytearray(src['_raw'])
        # 保留 flags (byte0) 不变, offset0-1不在文件中存储battle_id
        self.records.append(rec)
        self._refresh_tree()
        self._dirty = True
        self.status_var.set(f"已复制战场 #{self._current_idx} -> #{new_idx}")

    def _delete_record(self):
        """删除当前记录"""
        if self._current_idx < 0:
            return
        if not messagebox.askyesno("确认删除",
            f"确定要删除战场 #{self._current_idx} 吗?\n此操作不可恢复。"):
            return
        del self.records[self._current_idx]
        for i, rec in enumerate(self.records):
            rec['index'] = i
        self._current_idx = -1
        self._refresh_tree()
        self._dirty = True
        self.status_var.set(f"已删除战场")

    def _show_field_ref(self):
        text = """WarData.dat 字段参考 (基于 TKS.exe 反编译 — 多函数交叉验证)

=== 加载函数 ===
sub_42FDF8: fopen("WarData.dat","rb") → fseek(498*a1) → fread(&byte_9537D8,498,1)
sub_42FE70: fopen("WarWay.dat","rb") → fseek(word_9537F8<<10) → fread(&unk_951942,1024,1)
sub_436BD4: 战场主初始化 — sub_42FDF8(a1)→sub_42FE70()→sub_4307CC(a2)→sub_431428()

=== 字段布局 (byte_9537D8 偏移, 498字节/条, 219条) ===
[0]    byte    flags       — sub_4307CC:200 &4=随机敌军数; sub_43CA64:102 &2=失败条件
[1]    byte    (reserved)  — 反编译未引用; sub_436BD4:30 word_4EB728=a1是函数参数,非文件字段
[2-7]  byte[6] must_chars  — sub_4307CC:51 v20=&unk_9537DA; 6字节(+1编码, 0/255=空)
[8-29] byte[22] (保留)      — 反编译未引用
[30]   uint16  name_id     — sub_43A8D8:39,41,122 word_9537F6→sub_4067E8(TKT) 战场名称
[32]   uint16  map_id  — sub_42FE70:16 word_9537F8<<10; sub_436BD4:34
[34-69] uint16[18] enemy_id — sub_4307CC:219 word_9537FA; sub_444FD4:27 (WarPC索引)
[70-87] byte[18] enemy_lv  — sub_4307CC:260 *(v9-18); sub_444FD4:30,79 byte_95381E
[88-105] byte[18] enemy_grp — sub_4307CC:217 byte_953830; sub_444FD4:26 (属性加成倍率: 0=士兵可增援, >=1=将领HP×N倍, 见sub_4302D8:53)
[106-141] byte[36] enemy_lv_range — sub_430578 a3,a4; 18对 level params (int8)
[142-177] byte[36] enemy_xy — sub_431428:94-98 unk_953866; 18对int8 grid X,Y; War.dll“敌人朝向”
[178-189] byte[12] ally_xy — sub_431428:74 unk_95388A; 6对int8 X,Y, 同 enemy_xy格式
[190-207] byte[18] enemy_del — sub_4307CC:242 v9[102]; sub_444FD4:61 byte_953896
[208-213] byte[6] (保留)     — 反编译未引用
[214-269] byte[56] trea_xy  — sub_431428:204 *(v43-172/-171) 28组宝物坐标(int8对)
[270-325] byte[56] trea_qty — sub_431428:296 *(v45-116/-115); 28组主物品数量(min,max) byte
[326-345] uint16[10] trea_sub — sub_431428:202 *(v43-30) 前10组宝物副物品
[346-385] uint16[20] trea_quant — sub_434510:36-37 word_953932/953934; 10对(min,max) quantity
[386-441] uint16[28] trea_id — sub_431428:199,295 unk_95395A 28组宝物主物品ID
[442-477] uint16[18] enemy_flg — sub_4307CC:263 v5[204]; sub_444FD4:81 word_953992
            bit0=精英, bit1=特殊, bit13=阵营, bit14=形象, bit15=特殊类型
[478]    byte    default_lv_p1 — sub_430578:17 byte_9539B6 (level param default 1)
[480]    byte    default_lv_p2 — sub_430578:18 byte_9539B8 (level param default 2)
[482-483] uint16 turn_limit — sub_43CA64:29,32,109 word_9539BA (>0时回合限制)
[484-497] byte[14] (尾部保留) — 反编译未明确引用

=== WarWay.dat (1024字节/条, 100条, 32x32网格) ===
sub_4355C4: -1=永久障碍(循环跳过), 0=可通行(不触发特效), 1-5=特殊区域(触发特效)
sub_431428:106 — 值1-5分别收集为放置区, 对应place_req的-1~-5请求
sub_434D7C:60 — 非零非-1格触发地格视觉特效(sub_4544EC)
sub_444FD4 — 增援敌军生成函数, 独立验证enemy_xy/enemy_lv/enemy_flags/enemy_delay偏移
sub_434D7C:60 — 非零非-1格触发地格视觉特效(sub_4544EC)"""
        messagebox.showinfo("字段参考", text)

    def _show_about(self):
        messagebox.showinfo("关于",
            "WarData.dat 可视化编辑器\n\n"
            "基于游戏逆向工程 (TKS.exe 反编译)\n"
            "WSC.GRP 战场背景图支持\n"
            "WarWay.dat 32x32 地格编辑\n\n"
            "版本 1.0")

    # ═══════════════════════════════════════════════════════════
    # 字段构建帮助方法
    # ═══════════════════════════════════════════════════════════

    def _build_field(self, parent, row, col, label, var, width=12, tooltip=""):
        frm = ttk.Frame(parent); frm.grid(row=row, column=col, sticky='nw', padx=3, pady=2)
        lbl = ttk.Label(frm, text=label, font=FONT_S); lbl.pack(anchor=tk.W)
        if tooltip:
            self._bind_tooltip(lbl, tooltip)
        entry = ttk.Entry(frm, textvariable=var, width=width, font=FONT)
        entry.pack(fill=tk.X)
        return entry

    def _build_spinbox(self, parent, row, col, label, var, from_, to, tooltip=""):
        frm = ttk.Frame(parent); frm.grid(row=row, column=col, sticky='nw', padx=3, pady=2)
        lbl = ttk.Label(frm, text=label, font=FONT_S); lbl.pack(anchor=tk.W)
        if tooltip:
            self._bind_tooltip(lbl, tooltip)
        sb = ttk.Spinbox(frm, textvariable=var, from_=from_, to=to, width=10, font=FONT)
        sb.pack(fill=tk.X)
        return sb

    def _bind_tooltip(self, widget, text):
        def show(e):
            tw = tk.Toplevel(self.root)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{self.root.winfo_pointerx()+10}+{self.root.winfo_pointery()+10}")
            ttk.Label(tw, text=text, background="#ffffcc", relief='solid', borderwidth=1,
                      font=FONT_S, wraplength=400).pack()
            widget._tooltip = tw
        def hide(e):
            if hasattr(widget, '_tooltip') and widget._tooltip:
                widget._tooltip.destroy()
                widget._tooltip = None
        widget.bind('<Enter>', show)
        widget.bind('<Leave>', hide)

    # ═══════════════════════════════════════════════════════════
    # 战场参数标签页
    # ═══════════════════════════════════════════════════════════

    def _build_params_tab(self):
        pf = ttk.Frame(self.tab_params)
        pf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.pvars = {}
        row = 0

        self.pvars['battle_id'] = tk.StringVar()
        self._build_field(pf, row, 0, "战场序号", self.pvars['battle_id'],
            tooltip="记录索引号(0-218), 非文件存储字段; word_4EB728 来自sub_436BD4函数参数")

        self.pvars['map_id'] = tk.StringVar()
        self._build_field(pf, row, 1, "地图编号", self.pvars['map_id'],
            tooltip="[offset 32] uint16 WSC.GRP背景索引(0-82), 场景预览自动使用")

        row += 1

        self.pvars['battle_name_id'] = tk.StringVar()
        self._build_field(pf, row, 0, "名称文本ID", self.pvars['battle_name_id'],
            tooltip="[offset 30] 战场名称TKT文本ID (sub_43A8D8:39 word_9537F6→sub_4067E8)")

        self.pvars['battle_turn_limit'] = tk.StringVar()
        self._build_field(pf, row, 1, "回合限制", self.pvars['battle_turn_limit'],
            tooltip="[offset 482] >0时限制回合数 (sub_43CA64:29 word_9539BA)")

        row += 1

        self.pvars['flags'] = tk.StringVar()
        self._build_field(pf, row, 0, "参数标志", self.pvars['flags'],
            tooltip="[offset 0] bit1=失败条件(sub_43CA64:102), bit2=随机敌军数(sub_4307CC:200)")

        self.flag_bit1 = tk.BooleanVar()
        ttk.Checkbutton(pf, text="bit1: 失败后继续", variable=self.flag_bit1,
                        command=self._on_flag_change).grid(row=row, column=1, sticky='w', padx=3)
        self.flag_bit2 = tk.BooleanVar()
        ttk.Checkbutton(pf, text="bit2: 随机敌军数量", variable=self.flag_bit2,
                        command=self._on_flag_change).grid(row=row, column=2, sticky='w', padx=3)

        row += 1

        ttk.Label(pf, text="强制出战角色 (6槽位, +1编码):", font=FONT_S).grid(
            row=row, column=0, columnspan=3, sticky='w', padx=3, pady=(8, 2))
        row += 1
        self.pvars['must_chars'] = []
        self.must_char_labels = []
        for i in range(6):
            var = tk.StringVar()
            self.pvars['must_chars'].append(var)
            c = i % 3; r = row + i // 3
            frm = ttk.Frame(pf); frm.grid(row=r, column=c, sticky='w', padx=3, pady=1)
            ttk.Label(frm, text=f"槽{i}:", font=FONT_S, width=3).pack(side=tk.LEFT)
            ttk.Entry(frm, textvariable=var, width=6, font=FONT).pack(side=tk.LEFT, padx=2)
            lbl = ttk.Label(frm, text="", foreground='#3366cc', font=FONT_S)
            lbl.pack(side=tk.LEFT); self.must_char_labels.append(lbl)

    def _on_flag_change(self):
        flags = 0
        if self.flag_bit1.get():
            flags |= 2
        if self.flag_bit2.get():
            flags |= 4
        self.pvars['flags'].set(str(flags))
        self._dirty = True

    def _populate_params_tab(self, rec):
        self.pvars['battle_id'].set(str(rec['battle_id']))
        self.pvars['map_id'].set(str(rec['map_id']))
        self.pvars['battle_name_id'].set(str(rec['battle_name_id']))
        self.pvars['battle_turn_limit'].set(str(rec['battle_turn_limit']))
        self.pvars['flags'].set(str(rec['flags']))
        self.flag_bit1.set((rec['flags'] & 2) != 0)
        self.flag_bit2.set((rec['flags'] & 4) != 0)
        for i in range(6):
            v = rec['must_chars'][i]
            self.pvars['must_chars'][i].set(str(v))
            if v and v != 255:
                cid = v - 1
                self.must_char_labels[i].config(text=self._char_name(cid)[:12])
            else:
                self.must_char_labels[i].config(text="")

    # ═══════════════════════════════════════════════════════════
    # 全部参数标签页
    # ═══════════════════════════════════════════════════════════

    def _build_allparams_tab(self):
        ap = ttk.Frame(self.tab_allparams)
        ap.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(ap, highlightthickness=0)
        sb = ttk.Scrollbar(ap, orient=tk.VERTICAL, command=canvas.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.configure(yscrollcommand=sb.set)
        inner = ttk.Frame(canvas)
        self._ap_win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_canvas_conf(event):
            if event.width > 1:
                canvas.itemconfig(self._ap_win_id, width=event.width)

        canvas.bind('<Configure>', _on_canvas_conf, add='+')
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')), add='+')
        canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(int(-e.delta / 120), 'units'), add='+')

        self.apvars = {}
        row = 0

        # ═══════════════════════════════════════════════════════
        # [000-033] 记录头
        # ═══════════════════════════════════════════════════════
        ttk.Label(inner, text="[000-033] 记录头", font=FONT).grid(
            row=row, column=0, columnspan=6, sticky='w', pady=(5, 2))
        row += 1

        # [index] 战场序号 + [000] flags
        self.apvars['battle_id'] = tk.StringVar()
        self._build_field(inner, row, 0, "[index] 战场序号", self.apvars['battle_id'],
            tooltip="记录索引号(0-218), 非文件存储字段; word_4EB728 来自sub_436BD4函数参数a1", width=8)
        self.apvars['flags'] = tk.StringVar()
        self._build_field(inner, row, 1, "[000] Flags byte", self.apvars['flags'],
            tooltip="bit1(&2)=失败条件(sub_43CA64:102) bit2(&4)=随机敌军(sub_4307CC:200)", width=8)
        self.apflag_bit1 = tk.BooleanVar()
        ttk.Checkbutton(inner, text="bit1:失败后继续", variable=self.apflag_bit1,
                        command=self._on_apflag_change).grid(row=row, column=2, sticky='w')
        self.apflag_bit2 = tk.BooleanVar()
        ttk.Checkbutton(inner, text="bit2:随机敌军数", variable=self.apflag_bit2,
                        command=self._on_apflag_change).grid(row=row, column=3, sticky='w')
        row += 1

        # [002-007] must_chars
        ttk.Label(inner, text="[002-007] 强制出战 byte[6] (+1编码,0/255=空):", font=FONT_S).grid(
            row=row, column=0, columnspan=6, sticky='w', pady=(4, 1))
        row += 1
        self.apvars['must_chars'] = []
        frm_mc = ttk.Frame(inner); frm_mc.grid(row=row, column=0, columnspan=6, sticky='w', padx=3)
        for i in range(6):
            var = tk.StringVar()
            self.apvars['must_chars'].append(var)
            ttk.Label(frm_mc, text=f"槽{i}:", font=FONT_S).pack(side=tk.LEFT)
            ttk.Entry(frm_mc, textvariable=var, width=5, font=FONT).pack(side=tk.LEFT, padx=(0, 6))
        row += 1

        # [008-029] reserved
        ttk.Label(inner, text="[008-029] (保留22字节 — 反编译未引用, 数据全零)", font=FONT_S,
                  foreground='gray').grid(row=row, column=0, columnspan=6, sticky='w', pady=(2, 0))
        row += 1

        # [030-033] name_id + map_id
        self.apvars['battle_name_id'] = tk.StringVar()
        self._build_field(inner, row, 0, "[030-031] 名称文本ID uint16", self.apvars['battle_name_id'],
            tooltip="sub_43A8D8:39 word_9537F6→sub_4067E8(TKT)", width=8)
        self.apvars['map_id'] = tk.StringVar()
        self._build_field(inner, row, 1, "[032-033] 地图编号 uint16", self.apvars['map_id'],
            tooltip="sub_42FE70:16 word_9537F8<<10; sub_436BD4:34", width=8)
        row += 1

        # ═══════════════════════════════════════════════════════
        # [034-177] 敌军配置
        # ═══════════════════════════════════════════════════════
        ttk.Label(inner, text="[034-177] 敌军配置 ×18", font=FONT).grid(
            row=row, column=0, columnspan=9, sticky='w', pady=(10, 2))
        row += 1
        # 表头: 字段名+偏移
        enemy_cols = [
            ('#', 3, ''),
            ('ID\nu16[034-069]', 5, '[34-69] uint16[18] enemy_id — sub_4307CC:219'),
            ('Lv\nu8[070-087]', 4, '[70-87] byte[18] enemy_lv — sub_4307CC:260'),
            ('加成\nu8[088-105]', 4, '[88-105] byte[18] enemy_grp — 属性加成倍率; sub_4307CC:217'),
            ('LvP1\ni8[106-141]', 4, '[106-141] byte[36] enemy_lv_range — sub_430578 a3, LvP1=106+2*i'),
            ('LvP2\ni8[106-141]', 4, 'sub_430578 a4, LvP2=107+2*i (int8)'),
            ('X\ni8[142-177]', 3, '[142-177] byte[36] enemy_xy — sub_431428:94 X=142+2*i; -1~-5=随机区域请求'),
            ('Y\ni8[142-177]', 3, 'sub_431428:97 Y=143+2*i; 0~31=固定位置, 负值=区域请求'),
            ('时序Delay\nu8[190-207]', 6, '[190-207] byte[18] enemy_del — sub_4307CC:242; sub_444FD4:61'),
            ('标志\nu16[442-477]', 5, '[442-477] uint16[18] enemy_flg — bit0=elite bit1=special'),
        ]
        for j, (h, w, tip) in enumerate(enemy_cols):
            lbl = ttk.Label(inner, text=h, font=('', 6), width=w, anchor='n')
            lbl.grid(row=row, column=j, padx=1)
            if tip:
                self._bind_tooltip(lbl, tip)
        row += 1
        self.ap_enemy_vars = []
        for i in range(18):
            vr = {}
            ttk.Label(inner, text=str(i), font=FONT_S).grid(row=row, column=0)
            for j, (k, w) in enumerate([('id',5),('lv',4),('power',4),('x',3),('y',3),('pr_x',4),('pr_y',4),('delay',4),('flags',5)]):
                vr[k] = tk.StringVar()
                if k in ('id', 'flags'):
                    wgt = ttk.Spinbox(inner, textvariable=vr[k], from_=0, to=65535, width=w, font=('', 7))
                elif k in ('x', 'y', 'pr_x', 'pr_y', 'delay'):
                    wgt = ttk.Spinbox(inner, textvariable=vr[k], from_=-128, to=127, width=w, font=('', 7))
                else:
                    wgt = ttk.Entry(inner, textvariable=vr[k], width=w, font=('', 7))
                wgt.grid(row=row, column=j+1, padx=1)
            self.ap_enemy_vars.append(vr)
            row += 1

        # ═══════════════════════════════════════════════════════
        # [178-213] 友军配置
        # ═══════════════════════════════════════════════════════
        ttk.Label(inner, text="[178-213] 友军配置 ×6", font=FONT).grid(
            row=row, column=0, columnspan=4, sticky='w', pady=(10, 2))
        row += 1
        ally_cols = [
            ('#', 3, ''),
            ('X\ni8[178-189]', 4, '[178-189] byte[12] ally_xy — sub_431428:74 X=178+2*i; 0=不使用'),
            ('Y\ni8[178-189]', 4, 'Y=179+2*i (int8); 0,0=该槽位无友军'),
            ('朝向\nu8[208-213]', 6, '[208-213] byte[6] ally_facing — War.dll"我方朝向"'),
        ]
        for j, (h, w, tip) in enumerate(ally_cols):
            lbl = ttk.Label(inner, text=h, font=('', 6), width=w, anchor='n')
            lbl.grid(row=row, column=j, padx=1)
            if tip:
                self._bind_tooltip(lbl, tip)
        row += 1
        self.ap_ally_vars = []
        for i in range(6):
            vr = {}
            ttk.Label(inner, text=str(i), font=FONT_S).grid(row=row, column=0)
            for k, w, col in [('x',4,1),('y',4,2),('facing',6,3)]:
                vr[k] = tk.StringVar()
                ttk.Entry(inner, textvariable=vr[k], width=w, font=('', 7)).grid(
                    row=row, column=col, padx=1)
            self.ap_ally_vars.append(vr)
            row += 1

        # ═══════════════════════════════════════════════════════
        # [214-441] 宝物配置
        # ═══════════════════════════════════════════════════════
        ttk.Label(inner, text="[214-441] 宝物配置 ×28", font=FONT).grid(
            row=row, column=0, columnspan=8, sticky='w', pady=(10, 2))
        row += 1
        trea_cols = [
            ('#', 3, ''),
            ('陷阱类型\nu16[386-441]', 6, '[386-441] uint16[28] trap_type — 1-6 (山崩/泥沼/漩渦/火焰/滾木/瘴氣)'),
            ('副物品\nu16[326-345]', 6, '[326-345] uint16[10] trea_sub — sub_431428:202; 仅前10组'),
            ('X\ni8[214-269]', 3, '[214-269] byte[56] trap_xy — X=214+2*i; 负值=区域随机'),
            ('Y\ni8[214-269]', 3, 'Y=215+2*i (int8); 0~31=固定位置, 负值=区域请求'),
            ('威力Min\nu8[270-325]', 4, '[270-325] byte[56] trap_pwr — power min=270+2*i'),
            ('威力Max\nu8[270-325]', 4, 'power max=271+2*i'),
            ('QtMin\nu16[346-385]', 5, '[346-385] uint16[20] trea_quant min — sub_434510:36 word_953932; 10对'),
            ('QtMax\nu16[346-385]', 5, 'trea_quant max — sub_434510:37 word_953934'),
        ]
        for j, (h, w, tip) in enumerate(trea_cols):
            lbl = ttk.Label(inner, text=h, font=('', 6), width=w, anchor='n')
            lbl.grid(row=row, column=j, padx=1)
            if tip:
                self._bind_tooltip(lbl, tip)
        row += 1
        self.ap_trea_vars = []
        for i in range(28):
            vr = {}
            ttk.Label(inner, text=str(i), font=FONT_S).grid(row=row, column=0)
            for j, (k, w) in enumerate([('tid',6),('sub',6),('x',3),('y',3),('min',4),('max',4),('qty_min',5),('qty_max',5)]):
                vr[k] = tk.StringVar()
                wgt = ttk.Entry(inner, textvariable=vr[k], width=w, font=('', 7))
                wgt.grid(row=row, column=j+1, padx=1)
            self.ap_trea_vars.append(vr)
            row += 1


        # ═══════════════════════════════════════════════════════
        # [478-497] 其他
        # ═══════════════════════════════════════════════════════
        ttk.Label(inner, text="[478-497] 其他", font=FONT).grid(
            row=row, column=0, columnspan=4, sticky='w', pady=(10, 2))
        row += 1

        self.apvars['def_enemy_x'] = tk.StringVar()
        self._build_field(inner, row, 0, "[478] 默认等级下限 byte", self.apvars['def_enemy_x'],
            tooltip="sub_430578:17 byte_9539B6 — 默认等级下限(当enemy_lv_range为0时使用)", width=8)
        self.apvars['def_enemy_y'] = tk.StringVar()
        self._build_field(inner, row, 1, "[480] 默认等级上限 byte", self.apvars['def_enemy_y'],
            tooltip="sub_430578:18 byte_9539B8 — 默认等级上限(当enemy_lv_range为0时使用)", width=8)
        self.apvars['battle_turn_limit'] = tk.StringVar()
        self._build_field(inner, row, 2, "[482-483] 回合限制 uint16", self.apvars['battle_turn_limit'],
            tooltip="sub_43CA64:29 word_9539BA — >0时限制回合数", width=8)
        row += 1

        ttk.Label(inner, text="[484-497] (保留14字节 — 反编译未引用, 全219条数据为零)", font=FONT_S,
                  foreground='gray').grid(row=row, column=0, columnspan=4, sticky='w')

    def _on_apflag_change(self):
        flags = 0
        if self.apflag_bit1.get(): flags |= 2
        if self.apflag_bit2.get(): flags |= 4
        self.apvars['flags'].set(str(flags))
        self._dirty = True

    def _populate_allparams_tab(self, rec):
        self.apvars['battle_id'].set(str(rec['battle_id']))
        self.apvars['map_id'].set(str(rec['map_id']))
        self.apvars['battle_name_id'].set(str(rec['battle_name_id']))
        self.apvars['battle_turn_limit'].set(str(rec['battle_turn_limit']))
        self.apvars['flags'].set(str(rec['flags']))
        self.apflag_bit1.set((rec['flags'] & 2) != 0)
        self.apflag_bit2.set((rec['flags'] & 4) != 0)
        self.apvars['def_enemy_x'].set(str(rec['default_lv_p1']))
        self.apvars['def_enemy_y'].set(str(rec['default_lv_p2']))
        for i in range(6):
            v = rec['must_chars'][i]
            self.apvars['must_chars'][i].set(str(v))
        for i in range(18):
            self.ap_enemy_vars[i]['id'].set(str(rec['enemy_ids'][i]))
            self.ap_enemy_vars[i]['lv'].set(str(rec['enemy_lv'][i]))
            self.ap_enemy_vars[i]['power'].set(str(rec['enemy_power'][i]))
            self.ap_enemy_vars[i]['x'].set(str(rec['enemy_lv_range'][i*2]))
            self.ap_enemy_vars[i]['y'].set(str(rec['enemy_lv_range'][i*2+1]))
            self.ap_enemy_vars[i]['pr_x'].set(str(rec['enemy_xy'][i*2]))
            self.ap_enemy_vars[i]['pr_y'].set(str(rec['enemy_xy'][i*2+1]))
            self.ap_enemy_vars[i]['delay'].set(str(rec['enemy_delay'][i]))
            self.ap_enemy_vars[i]['flags'].set(str(rec['enemy_flags'][i]))
        for i in range(6):
            self.ap_ally_vars[i]['x'].set(str(rec['ally_xy'][i*2]))
            self.ap_ally_vars[i]['y'].set(str(rec['ally_xy'][i*2+1]))
            self.ap_ally_vars[i]['facing'].set(str(rec['ally_facing'][i]))
        for i in range(28):
            self.ap_trea_vars[i]['tid'].set(str(rec['trap_type'][i]))
            self.ap_trea_vars[i]['sub'].set(str(rec['trea_sub'][i]) if i < 10 else '')
            self.ap_trea_vars[i]['x'].set(str(rec['trap_xy'][i*2]))
            self.ap_trea_vars[i]['y'].set(str(rec['trap_xy'][i*2+1]))
            self.ap_trea_vars[i]['min'].set(str(rec['trap_pwr'][i*2]))
            self.ap_trea_vars[i]['max'].set(str(rec['trap_pwr'][i*2+1]))
            self.ap_trea_vars[i]['qty_min'].set(str(rec['trea_quant'][i*2]) if i < 10 else '')
            self.ap_trea_vars[i]['qty_max'].set(str(rec['trea_quant'][i*2+1]) if i < 10 else '')

    def _apply_allparams_tab(self, rec):
        try: rec['battle_id'] = int(self.apvars['battle_id'].get() or 0) & 0xFFFF
        except: pass
        try: rec['map_id'] = int(self.apvars['map_id'].get() or 0) & 0xFFFF
        except: pass
        try: rec['battle_name_id'] = int(self.apvars['battle_name_id'].get() or 0) & 0xFFFF
        except: pass
        try: rec['battle_turn_limit'] = int(self.apvars['battle_turn_limit'].get() or 0) & 0xFFFF
        except: pass
        try: rec['flags'] = int(self.apvars['flags'].get() or 0) & 0xFF
        except: pass
        try: rec['default_lv_p1'] = int(self.apvars['def_enemy_x'].get() or 0) & 0xFF
        except: pass
        try: rec['default_lv_p2'] = int(self.apvars['def_enemy_y'].get() or 0) & 0xFF
        except: pass
        for i in range(6):
            try: rec['must_chars'][i] = int(self.apvars['must_chars'][i].get() or 0) & 0xFF
            except: pass
        for i in range(18):
            try: rec['enemy_ids'][i] = int(self.ap_enemy_vars[i]['id'].get() or 0)
            except: pass
            try: rec['enemy_lv'][i] = int(self.ap_enemy_vars[i]['lv'].get() or 0) & 0xFF
            except: pass
            try: rec['enemy_power'][i] = int(self.ap_enemy_vars[i]['power'].get() or 0) & 0xFF
            except: pass
            try: rec['enemy_lv_range'][i*2] = int(self.ap_enemy_vars[i]['x'].get() or 0)
            except: pass
            try: rec['enemy_lv_range'][i*2+1] = int(self.ap_enemy_vars[i]['y'].get() or 0)
            except: pass
            try: rec['enemy_xy'][i*2] = int(self.ap_enemy_vars[i]['pr_x'].get() or 0)
            except: pass
            try: rec['enemy_xy'][i*2+1] = int(self.ap_enemy_vars[i]['pr_y'].get() or 0)
            except: pass
            try: rec['enemy_delay'][i] = int(self.ap_enemy_vars[i]['delay'].get() or 0) & 0xFF
            except: pass
            try: rec['enemy_flags'][i] = int(self.ap_enemy_vars[i]['flags'].get() or 0) & 0xFFFF
            except: pass
        for i in range(6):
            try: rec['ally_xy'][i*2] = int(self.ap_ally_vars[i]['x'].get() or 0)
            except: pass
            try: rec['ally_xy'][i*2+1] = int(self.ap_ally_vars[i]['y'].get() or 0)
            except: pass
            try: rec['ally_facing'][i] = int(self.ap_ally_vars[i]['facing'].get() or 0) & 0xFF
            except: pass
        for i in range(28):
            try: rec['trap_type'][i] = int(self.ap_trea_vars[i]['tid'].get() or 0) & 0xFFFF
            except: pass
            if i < 10:
                try: rec['trea_sub'][i] = int(self.ap_trea_vars[i]['sub'].get() or 0) & 0xFFFF
                except: pass
                try: rec['trea_quant'][i*2] = int(self.ap_trea_vars[i]['qty_min'].get() or 0) & 0xFFFF
                except: pass
                try: rec['trea_quant'][i*2+1] = int(self.ap_trea_vars[i]['qty_max'].get() or 0) & 0xFFFF
                except: pass
            try: rec['trap_xy'][i*2] = int(self.ap_trea_vars[i]['x'].get() or 0)
            except: pass
            try: rec['trap_xy'][i*2+1] = int(self.ap_trea_vars[i]['y'].get() or 0)
            except: pass
            try: rec['trap_pwr'][i*2] = int(self.ap_trea_vars[i]['min'].get() or 0) & 0xFF
            except: pass
            try: rec['trap_pwr'][i*2+1] = int(self.ap_trea_vars[i]['max'].get() or 0) & 0xFF
            except: pass

    def _apply_params_tab(self, rec):
        try:
            rec['battle_id'] = int(self.pvars['battle_id'].get() or 0) & 0xFFFF
        except: pass
        try:
            rec['map_id'] = int(self.pvars['map_id'].get() or 0) & 0xFFFF
        except: pass
        try:
            rec['battle_name_id'] = int(self.pvars['battle_name_id'].get() or 0) & 0xFFFF
        except: pass
        try:
            rec['battle_turn_limit'] = int(self.pvars['battle_turn_limit'].get() or 0) & 0xFFFF
        except: pass
        try:
            rec['flags'] = int(self.pvars['flags'].get() or 0) & 0xFF
        except: pass
        for i in range(6):
            try:
                rec['must_chars'][i] = int(self.pvars['must_chars'][i].get() or 0) & 0xFF
            except: pass

    # ═══════════════════════════════════════════════════════════
    # 敌军配置标签页
    # ═══════════════════════════════════════════════════════════

    def _build_enemy_tab(self):
        ef = ttk.Frame(self.tab_enemy)
        ef.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        headers = ['槽', '角色ID', '角色名', '等级', '属性加成倍率', 'LvP1', 'LvP2', 'X', 'Y', '时序Delay', '精英/特殊']
        widths = [4, 7, 14, 5, 7, 5, 5, 4, 4, 5, 10]
        for j, (h, w) in enumerate(zip(headers, widths)):
            lbl = ttk.Label(ef, text=h, font=FONT_S, width=w)
            lbl.grid(row=0, column=j, padx=1)
            # 添加反编译来源 tooltip
            tips = {
                1: '[offset 34] sub_4307CC:222 *v5 — enemy WarPC index',
                3: '[offset 70] sub_4307CC:260 *(v9-18) — <10 grunt, >=10 elite',
                4: '[offset 88] 属性加成倍率 — sub_4302D8:53; 0=普通士兵(可增援), >=1=将领(HP×N倍等属性加成)',
                5: '[offset 106] sub_430578 a3 — level param 1 (int8)',
                6: '[offset 107] sub_430578 a4 — level param 2 (int8)',
                7: '[offset 142] sub_431428:94 *((char*)v32+108) — grid X(int8); -1~-5=随机区域请求',
                8: '[offset 143] sub_431428:97 *((char*)v32+109) — grid Y(int8); 0~31=固定位置, 负值=区域请求',
                9: '[offset 190] sub_4307CC:242 v9[102]; sub_444FD4:61 — action delay',
                10: '[offset 442] enemy_flags — bit0=elite,bit1=special,bit13/14=faction',
            }
            if j in tips:
                self._bind_tooltip(lbl, tips[j])

        self.enemy_vars = []
        self.enemy_name_labels = []
        for i in range(18):
            row = i + 1
            vars_row = {}
            ttk.Label(ef, text=str(i), font=FONT_S).grid(row=row, column=0)

            vars_row['id'] = tk.StringVar()
            ttk.Entry(ef, textvariable=vars_row['id'], width=6, font=FONT).grid(row=row, column=1, padx=1)

            lbl = ttk.Label(ef, text="", foreground='#3366cc', font=FONT_S, width=14, anchor='w')
            lbl.grid(row=row, column=2, padx=1)
            self.enemy_name_labels.append(lbl)

            vars_row['lv'] = tk.StringVar()
            ttk.Spinbox(ef, textvariable=vars_row['lv'], from_=0, to=255, width=5, font=FONT).grid(
                row=row, column=3, padx=1)

            vars_row['power'] = tk.StringVar()
            ttk.Entry(ef, textvariable=vars_row['power'], width=5, font=FONT).grid(row=row, column=4, padx=1)

            vars_row['x'] = tk.StringVar()
            ttk.Spinbox(ef, textvariable=vars_row['x'], from_=-128, to=127, width=4, font=FONT).grid(
                row=row, column=5, padx=1)

            vars_row['y'] = tk.StringVar()
            ttk.Spinbox(ef, textvariable=vars_row['y'], from_=-128, to=127, width=4, font=FONT).grid(
                row=row, column=6, padx=1)

            vars_row['pr_x'] = tk.StringVar()
            ttk.Spinbox(ef, textvariable=vars_row['pr_x'], from_=0, to=31, width=4, font=FONT).grid(
                row=row, column=7, padx=1)

            vars_row['pr_y'] = tk.StringVar()
            ttk.Spinbox(ef, textvariable=vars_row['pr_y'], from_=0, to=31, width=4, font=FONT).grid(
                row=row, column=8, padx=1)

            vars_row['delay'] = tk.StringVar()
            ttk.Spinbox(ef, textvariable=vars_row['delay'], from_=0, to=255, width=5, font=FONT).grid(
                row=row, column=9, padx=1)

            vars_row['flags'] = tk.StringVar()
            frm_flags = ttk.Frame(ef); frm_flags.grid(row=row, column=10, padx=1)
            ttk.Entry(frm_flags, textvariable=vars_row['flags'], width=5, font=FONT).pack(side=tk.LEFT)
            vars_row['flag_lbl'] = ttk.Label(frm_flags, text="", foreground='#cc6633', font=('', 7), width=4)
            vars_row['flag_lbl'].pack(side=tk.LEFT)

            self.enemy_vars.append(vars_row)

    def _populate_enemy_tab(self, rec):
        for i in range(18):
            eid = rec['enemy_ids'][i]
            self.enemy_vars[i]['id'].set(str(eid))
            self.enemy_vars[i]['lv'].set(str(rec['enemy_lv'][i]))
            self.enemy_vars[i]['power'].set(str(rec['enemy_power'][i]))
            self.enemy_vars[i]['x'].set(str(rec['enemy_lv_range'][i * 2]))
            self.enemy_vars[i]['y'].set(str(rec['enemy_lv_range'][i * 2 + 1]))
            self.enemy_vars[i]['pr_x'].set(str(rec['enemy_xy'][i * 2]))
            self.enemy_vars[i]['pr_y'].set(str(rec['enemy_xy'][i * 2 + 1]))
            self.enemy_vars[i]['delay'].set(str(rec['enemy_delay'][i]))
            self.enemy_vars[i]['flags'].set(str(rec['enemy_flags'][i]))
            # 标志位解读 (sub_4307CC:264-298; sub_444FD4:82-102)
            f = rec['enemy_flags'][i]
            flag_parts = []
            if f & 1: flag_parts.append('精英')
            if f & 2: flag_parts.append('特殊')
            if f & 0x2000: flag_parts.append('阵营A')
            if f & 0x4000: flag_parts.append('阵营B')
            if f & 0x8000: flag_parts.append('特殊型')
            self.enemy_vars[i]['flag_lbl'].config(text='/'.join(flag_parts) if flag_parts else '')

            if eid:
                self.enemy_name_labels[i].config(text=self._enemy_name(eid)[:14])
            else:
                self.enemy_name_labels[i].config(text="(空)")

    def _apply_enemy_tab(self, rec):
        for i in range(18):
            try:
                rec['enemy_ids'][i] = int(self.enemy_vars[i]['id'].get() or 0)
            except: pass
            try:
                rec['enemy_lv'][i] = int(self.enemy_vars[i]['lv'].get() or 0) & 0xFF
            except: pass
            try:
                rec['enemy_power'][i] = int(self.enemy_vars[i]['power'].get() or 0) & 0xFF
            except: pass
            try:
                rec['enemy_lv_range'][i * 2] = int(self.enemy_vars[i]['x'].get() or 0)
            except: pass
            try:
                rec['enemy_lv_range'][i * 2 + 1] = int(self.enemy_vars[i]['y'].get() or 0)
            except: pass
            try:
                rec['enemy_xy'][i * 2] = int(self.enemy_vars[i]['pr_x'].get() or 0)
            except: pass
            try:
                rec['enemy_xy'][i * 2 + 1] = int(self.enemy_vars[i]['pr_y'].get() or 0)
            except: pass
            try:
                rec['enemy_delay'][i] = int(self.enemy_vars[i]['delay'].get() or 0) & 0xFF
            except: pass
            try:
                rec['enemy_flags'][i] = int(self.enemy_vars[i]['flags'].get() or 0) & 0xFFFF
            except: pass

    # ═══════════════════════════════════════════════════════════
    # 友军配置标签页
    # ═══════════════════════════════════════════════════════════

    def _build_ally_tab(self):
        af = ttk.Frame(self.tab_ally)
        af.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        ttk.Label(af, text="友军坐标+朝向 (sub_431428:74 unk_95388A — int8字节对):",
                  font=FONT_S).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 4))

        headers = ['槽', 'X', 'Y', '朝向']
        for j, h in enumerate(headers):
            ttk.Label(af, text=h, font=FONT_S, width=4 if j in (1,2) else 5 if j==3 else 3).grid(
                row=1, column=j, padx=1)

        self.ally_vars = []  # ally_xy: int8 pairs
        for i in range(6):
            row = i + 2
            ttk.Label(af, text=str(i), font=FONT_S).grid(row=row, column=0)
            vars_row = {}
            vars_row['x'] = tk.StringVar()
            ttk.Spinbox(af, textvariable=vars_row['x'], from_=0, to=31, width=4, font=FONT).grid(
                row=row, column=1, padx=1)
            vars_row['y'] = tk.StringVar()
            ttk.Spinbox(af, textvariable=vars_row['y'], from_=0, to=31, width=4, font=FONT).grid(
                row=row, column=2, padx=1)
            vars_row['facing'] = tk.StringVar()
            ttk.Spinbox(af, textvariable=vars_row['facing'], from_=0, to=255, width=6, font=FONT).grid(
                row=row, column=3, padx=1)
            self.ally_vars.append(vars_row)

        ttk.Label(af, text="\nX,Y: int8(0-31), 0=不使用; 朝向: 0-7(八方), 255=无效",
                  font=FONT_S).grid(row=9, column=0, columnspan=4, sticky='w')

    def _populate_ally_tab(self, rec):
        for i in range(6):
            self.ally_vars[i]['x'].set(str(rec['ally_xy'][i * 2]))
            self.ally_vars[i]['y'].set(str(rec['ally_xy'][i * 2 + 1]))
            self.ally_vars[i]['facing'].set(str(rec['ally_facing'][i]))

    def _apply_ally_tab(self, rec):
        for i in range(6):
            try:
                rec['ally_xy'][i * 2] = int(self.ally_vars[i]['x'].get() or 0)
            except: pass
            try:
                rec['ally_xy'][i * 2 + 1] = int(self.ally_vars[i]['y'].get() or 0)
            except: pass
            try:
                rec['ally_facing'][i] = int(self.ally_vars[i]['facing'].get() or 0) & 0xFF
            except: pass

    # ═══════════════════════════════════════════════════════════
    # 宝物/奖励标签页 (sub_431428:198-323 treasure系统)
    # ═══════════════════════════════════════════════════════════

    def _build_drops_tab(self):
        """10个宝物槽位 (sub_431428:303 trea_sub) + 坐标共享28陷阱槽位"""
        df = self.tab_drops
        canvas = tk.Canvas(df, highlightthickness=0)
        vsb = ttk.Scrollbar(df, orient=tk.VERTICAL, command=canvas.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.configure(yscrollcommand=vsb.set)
        inner = ttk.Frame(canvas)
        self._drops_win = canvas.create_window((0, 0), window=inner, anchor='nw')
        def _drops_canvas_conf(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        inner.bind('<Configure>', _drops_canvas_conf)
        canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(int(-e.delta / 120), 'units'))

        ttk.Label(inner, text="隐藏宝物 (sub_431428:303 trea_sub) — 10个槽位, 与陷阱共享X/Y坐标:", font=FONT).grid(
            row=0, column=0, columnspan=8, sticky='w', pady=(2, 4))

        hdr = ['#', 'X', 'Y', '宝物ID', '宝物名称', '数量Min', '数量Max']
        hdr_widths = [4, 4, 4, 10, 16, 10, 10]
        for j, (h, w) in enumerate(zip(hdr, hdr_widths)):
            ttk.Label(inner, text=h, font=FONT_S, width=w).grid(row=1, column=j, padx=1)

        self.trea_vars = []
        self.trea_name_labels = []
        for i in range(10):
            row = i + 2
            vr = {}
            ttk.Label(inner, text=str(i), font=FONT_S).grid(row=row, column=0)

            vr['x'] = tk.StringVar()
            ttk.Spinbox(inner, textvariable=vr['x'], from_=-128, to=127, width=4, font=FONT).grid(
                row=row, column=1, padx=1)

            vr['y'] = tk.StringVar()
            ttk.Spinbox(inner, textvariable=vr['y'], from_=-128, to=127, width=4, font=FONT).grid(
                row=row, column=2, padx=1)

            vr['tid'] = tk.StringVar()
            ttk.Entry(inner, textvariable=vr['tid'], width=6, font=FONT).grid(
                row=row, column=3, padx=1)
            nlbl = ttk.Label(inner, text="", foreground='#3366cc', font=FONT_S, width=12, anchor='w')
            nlbl.grid(row=row, column=4, padx=1)
            self.trea_name_labels.append(nlbl)

            vr['qty_min'] = tk.StringVar()
            ttk.Entry(inner, textvariable=vr['qty_min'], width=5, font=FONT).grid(
                row=row, column=5, padx=1)

            vr['qty_max'] = tk.StringVar()
            ttk.Entry(inner, textvariable=vr['qty_max'], width=5, font=FONT).grid(
                row=row, column=6, padx=1)

            self.trea_vars.append(vr)

        ttk.Label(inner,
            text="宝物ID: 0=无, 10000=金钱, 其他=TKItem ID (sub_431428:303)\n"
                 "坐标与陷阱tab共享trap_xy (offset 214-269), 负X=区域随机放置\n"
                 "数量来自trea_quant (offset 346-385), sub_434510",
            font=FONT_S, foreground='#666', justify='left').grid(
            row=12, column=0, columnspan=8, sticky='w', pady=(10, 0))

    def _populate_drops_tab(self, rec):
        for i in range(10):
            vr = self.trea_vars[i]
            vr['x'].set(str(rec['trap_xy'][i * 2]))
            vr['y'].set(str(rec['trap_xy'][i * 2 + 1]))
            tid = rec['trea_sub'][i]
            vr['tid'].set(str(tid))
            if tid == 10000:
                self.trea_name_labels[i].config(text="金钱")
            elif tid and tid in self.tkitem_names_by_id:
                self.trea_name_labels[i].config(text=self.tkitem_names_by_id[tid][:12])
            elif tid:
                self.trea_name_labels[i].config(text=f"Item#{tid}")
            else:
                self.trea_name_labels[i].config(text="(空)")
            vr['qty_min'].set(str(rec['trea_quant'][i*2]))
            vr['qty_max'].set(str(rec['trea_quant'][i*2+1]))

    def _apply_drops_tab(self, rec):
        for i in range(10):
            vr = self.trea_vars[i]
            try: rec['trap_xy'][i*2] = int(vr['x'].get() or 0)
            except: pass
            try: rec['trap_xy'][i*2+1] = int(vr['y'].get() or 0)
            except: pass
            try: rec['trea_sub'][i] = int(vr['tid'].get() or 0) & 0xFFFF
            except: pass
            try: rec['trea_quant'][i*2] = int(vr['qty_min'].get() or 0) & 0xFFFF
            except: pass
            try: rec['trea_quant'][i*2+1] = int(vr['qty_max'].get() or 0) & 0xFFFF
            except: pass

    # ═══════════════════════════════════════════════════════════
    # 陷阱标签页 (sub_431428 + sub_434C0C)
    # ═══════════════════════════════════════════════════════════

    TRAP_TYPE_NAMES = {
        0: '0 无',
        1: '1 山崩陷阱',
        2: '2 泥沼陷阱',
        3: '3 漩渦陷阱',
        4: '4 火焰陷阱',
        5: '5 滾木陷阱',
        6: '6 瘴氣陷阱',
    }

    @staticmethod
    def _trap_type_at(rec, slot):
        """读取 slot 0-27 的陷阱类型 (sub_431428: offset 386/406)"""
        if slot < 10:
            return rec['trap_type'][slot]  # slots 0-9: offset 386+slot*2
        else:
            # slots 10-27: offset 406+(slot-10)*2 → rec['trap_type'][10+(slot-10)]
            # trea_id spans offset 386-441 = 28 int16
            return rec['trap_type'][slot]

    @staticmethod
    def _trap_power_at(rec, slot):
        """读取 slot 0-27 的陷阱威力 (min, max)"""
        if slot < 10:
            off = slot * 2  # offset 270+slot*2
        else:
            off = 20 + (slot - 10) * 2  # offset 290+(slot-10)*2
        return (rec['trap_pwr'][off], rec['trap_pwr'][off + 1])

    def _build_trap_tab(self):
        """28个陷阱槽位: X,Y坐标(共享trea_xy) + 陷阱类型 + 威力min/max"""
        df = self.tab_traps
        canvas = tk.Canvas(df, highlightthickness=0)
        vsb = ttk.Scrollbar(df, orient=tk.VERTICAL, command=canvas.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.configure(yscrollcommand=vsb.set)
        inner = ttk.Frame(canvas)
        self._trap_win = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _trap_canvas_conf(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        inner.bind('<Configure>', _trap_canvas_conf)
        canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(int(-e.delta / 120), 'units'))

        ttk.Label(inner, text="战场预置陷阱 (sub_431428:198-323) — 28个槽位, 威力每场随机:", font=FONT).grid(
            row=0, column=0, columnspan=8, sticky='w', pady=(2, 4))

        # 表头
        hdrs = ['#', 'X', 'Y', '陷阱类型', '威力Min', '威力Max']
        hdr_widths = [4, 4, 4, 16, 8, 8]
        for j, (h, w) in enumerate(zip(hdrs, hdr_widths)):
            ttk.Label(inner, text=h, font=FONT_S, width=w).grid(row=1, column=j, padx=1)

        self.trap_vars = []
        for i in range(28):
            row = i + 2
            vr = {}
            ttk.Label(inner, text=str(i), font=FONT_S).grid(row=row, column=0)

            vr['x'] = tk.StringVar()
            ttk.Spinbox(inner, textvariable=vr['x'], from_=-128, to=127, width=4, font=FONT).grid(
                row=row, column=1, padx=1)

            vr['y'] = tk.StringVar()
            ttk.Spinbox(inner, textvariable=vr['y'], from_=-128, to=127, width=4, font=FONT).grid(
                row=row, column=2, padx=1)

            vr['type'] = tk.StringVar(value='0')
            ttk.Combobox(inner, textvariable=vr['type'],
                         values=list(self.TRAP_TYPE_NAMES.values()),
                         width=15, font=FONT_S, state='readonly').grid(
                row=row, column=3, padx=1)

            vr['pwr_min'] = tk.StringVar()
            ttk.Entry(inner, textvariable=vr['pwr_min'], width=6, font=FONT).grid(
                row=row, column=4, padx=1)

            vr['pwr_max'] = tk.StringVar()
            ttk.Entry(inner, textvariable=vr['pwr_max'], width=6, font=FONT).grid(
                row=row, column=5, padx=1)

            self.trap_vars.append(vr)

        ttk.Label(inner,
            text="陷阱类型 1-6 → TKKon[552-557] (sub_434C0C: byte_9DFA92[]+551)\n"
                 "元素增益 (sub_434C0C:17-37): 火→火焰×2, 水→漩渦×2, 毒→瘴氣×2\n"
                 "坐标共享宝物槽位 (trea_xy), 陷阱类型存储在trea_id区域 (offset 386+)",
            font=FONT_S, foreground='#666', justify='left').grid(
            row=30, column=0, columnspan=8, sticky='w', pady=(10, 0))

    def _populate_trap_tab(self, rec):
        for i in range(28):
            vr = self.trap_vars[i]
            tx = rec['trap_xy'][i * 2]
            ty = rec['trap_xy'][i * 2 + 1]
            ttype = self._trap_type_at(rec, i)
            # 负X = 区域随机放置 (zone = |X|)
            if tx < 0:
                vr['x'].set(str(tx))  # 保留负值表示区域
                vr['y'].set(str(ty))
            else:
                vr['x'].set(str(tx))
                vr['y'].set(str(ty))
            if 1 <= ttype <= 6:
                vr['type'].set(self.TRAP_TYPE_NAMES.get(ttype, f'{ttype}'))
            else:
                vr['type'].set('0 无')
            pmin, pmax = self._trap_power_at(rec, i)
            if ttype >= 1:
                vr['pwr_min'].set(str(pmin))
                vr['pwr_max'].set(str(pmax))
            else:
                vr['pwr_min'].set('0')
                vr['pwr_max'].set('0')

    def _apply_trap_tab(self, rec):
        for i in range(28):
            vr = self.trap_vars[i]
            try: rec['trap_xy'][i * 2] = int(vr['x'].get() or 0)
            except: pass
            try: rec['trap_xy'][i * 2 + 1] = int(vr['y'].get() or 0)
            except: pass

            # 解析陷阱类型 (取数字前缀)
            tstr = vr['type'].get()
            ttype = 0
            for c in tstr:
                if c.isdigit():
                    ttype = int(c)
                    break
            ttype = max(0, min(6, ttype))

            # 写入 trea_id 区域
            if i < 10:
                rec['trap_type'][i] = ttype
            else:
                rec['trap_type'][i] = ttype

            # 写入威力
            try: pmin = int(vr['pwr_min'].get() or 0) & 0xFF
            except: pmin = 0
            try: pmax = int(vr['pwr_max'].get() or 0) & 0xFF
            except: pmax = 0

            if i < 10:
                off = i * 2
            else:
                off = 20 + (i - 10) * 2
            rec['trap_pwr'][off] = pmin
            rec['trap_pwr'][off + 1] = pmax

    # ═══════════════════════════════════════════════════════════
    # 场景预览标签页
    # ═══════════════════════════════════════════════════════════

    def _build_scene_tab(self):
        """场景预览标签页 — Canvas + 图层控制"""
        sf = ttk.Frame(self.tab_scene)
        sf.pack(fill=tk.BOTH, expand=True)

        # 图层控制栏
        ctrl = ttk.Frame(sf); ctrl.pack(fill=tk.X, padx=2, pady=2)
        ttk.Label(ctrl, text="图层:", font=FONT_S).pack(side=tk.LEFT, padx=2)

        self.show_bg = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="背景", variable=self.show_bg,
                        command=self._redraw_scene).pack(side=tk.LEFT, padx=2)

        self.show_grid = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="网格", variable=self.show_grid,
                        command=self._redraw_scene).pack(side=tk.LEFT, padx=2)

        ttk.Label(ctrl, text=" 透明度:", font=FONT_S).pack(side=tk.LEFT)
        self.grid_alpha = tk.StringVar(value="25%")
        ttk.Combobox(ctrl, textvariable=self.grid_alpha,
                     values=['0%', '25%', '50%', '75%', '100%'],
                     state='readonly', width=4).pack(side=tk.LEFT, padx=2)
        self.grid_alpha.trace_add('write', lambda *a: self._redraw_scene())

        self.show_units = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="单位", variable=self.show_units,
                        command=self._redraw_scene).pack(side=tk.LEFT, padx=2)

        self.show_trea = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="宝物", variable=self.show_trea,
                        command=self._redraw_scene).pack(side=tk.LEFT, padx=2)

        self.show_trap = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="陷阱", variable=self.show_trap,
                        command=self._redraw_scene).pack(side=tk.LEFT, padx=2)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # 地形类型独立显示/隐藏勾选框
        self.show_obstacle = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="障碍", variable=self.show_obstacle,
                        command=self._redraw_scene).pack(side=tk.LEFT, padx=2)

        self.show_temp_obstacle = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="临时障碍", variable=self.show_temp_obstacle,
                        command=self._redraw_scene).pack(side=tk.LEFT, padx=2)

        self.show_zone = [tk.BooleanVar(value=True) for _ in range(5)]
        for zi in range(5):
            ttk.Checkbutton(ctrl, text=f"区域{zi+1}", variable=self.show_zone[zi],
                            command=self._redraw_scene).pack(side=tk.LEFT, padx=2)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(ctrl, text="缩放:", font=FONT_S).pack(side=tk.LEFT)
        self.zoom_var = tk.StringVar(value="50%")
        ttk.Combobox(ctrl, textvariable=self.zoom_var, values=['25%', '33%', '50%', '66%', '75%', '100%'],
                     state='readonly', width=5).pack(side=tk.LEFT, padx=2)
        self.zoom_var.trace_add('write', lambda *a: self._on_zoom_change())

        ttk.Button(ctrl, text="刷新", command=self._redraw_scene, width=4).pack(side=tk.LEFT, padx=(6, 2))

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        self.edit_mode = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl, text="编辑", variable=self.edit_mode).pack(side=tk.LEFT, padx=2)

        ttk.Label(ctrl, text="背景=map_id(WSC)", font=FONT_S, foreground='gray').pack(side=tk.LEFT, padx=(10, 2))

        self.scene_info_var = tk.StringVar(value="")
        ttk.Label(ctrl, textvariable=self.scene_info_var, foreground='#3366cc',
                  font=FONT).pack(side=tk.RIGHT, padx=10)

        # 地形图例色块
        legend = ttk.Frame(sf); legend.pack(fill=tk.X, padx=2, pady=(0, 2))
        terrain_colors = [
            ('障碍', '#553322'), ('临时障碍', '#665544'),
            ('区域1', '#aa6633'), ('区域2', '#3366aa'), ('区域3', '#aa44aa'),
            ('区域4', '#33aa66'), ('区域5', '#aaaa33'),
        ]
        for label, color in terrain_colors:
            f = ttk.Frame(legend); f.pack(side=tk.LEFT, padx=3)
            c = tk.Canvas(f, width=10, height=10, highlightthickness=0)
            c.create_rectangle(0, 0, 10, 10, fill=color, outline=color)
            c.pack(side=tk.LEFT)
            ttk.Label(f, text=label, font=('Microsoft YaHei UI', 7)).pack(side=tk.LEFT, padx=1)

        # Canvas 容器
        canvas_frame = ttk.Frame(sf); canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.scene_canvas = tk.Canvas(canvas_frame, bg='#333333',
                                       highlightthickness=0, cursor='crosshair')
        hsb = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.scene_canvas.xview)
        vsb = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.scene_canvas.yview)
        self.scene_canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.scene_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 事件绑定 (轻量 — 悬停和缩放)
        self.scene_canvas.bind('<Motion>', self._on_scene_hover)
        self.scene_canvas.bind('<MouseWheel>', self._on_scene_wheel)
        self.scene_canvas.bind('<Button-1>', self._on_scene_click)
        self.scene_canvas.bind('<B1-Motion>', self._on_scene_drag)
        self.scene_canvas.bind('<ButtonRelease-1>', self._on_scene_release)
        self.scene_canvas.bind('<Button-3>', self._on_scene_right_down)
        self.scene_canvas.bind('<B3-Motion>', self._on_scene_right_move)

    def _load_wsc_background(self, wsc_idx: int):
        """加载并缓存 WSC 背景图"""
        if not HAS_PIL:
            return None
        if not self.wsc_grp_path or not self.wsc_offsets:
            return None
        if wsc_idx in self._wsc_cache:
            return self._wsc_cache[wsc_idx]

        result = load_wsc_entry(self.wsc_grp_path, self.wsc_offsets, wsc_idx)
        if result is None:
            return None

        w, h, rgba = result
        img = Image.frombuffer('RGBA', (w, h), rgba, 'raw', 'RGBA', 0, 1)

        zoom = self._preview_zoom
        new_w = int(w * zoom)
        new_h = int(h * zoom)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        photo = ImageTk.PhotoImage(img)
        self._wsc_cache[wsc_idx] = (photo, new_w, new_h)
        return (photo, new_w, new_h)

    def _on_zoom_change(self):
        zs = self.zoom_var.get().rstrip('%')
        try:
            self._preview_zoom = int(zs) / 100.0
        except:
            return
        self._wsc_cache.clear()
        self._redraw_scene()

    def _grid_to_screen(self, gx, gy):
        """等距投影: 网格坐标 → WSC背景图像像素坐标 (经zoom缩放后为canvas坐标)
        sub_42F9C8: px = dword_4E7DF0 + 56*(gx-10) - 56*(gy-15)
                    py = dword_4E7DF4 + 28*(gx-10) + 28*(gy-15)
        dword_4E7DF0=359, dword_4E7DF4=365, 偏移10/15为PE .data段编译时常量
        """
        zoom = self._preview_zoom
        sx = round((359 + 56 * (gx - 10) - 56 * (gy - 15)) * zoom)
        sy = round((365 + 28 * (gx - 10) + 28 * (gy - 15)) * zoom)
        return sx, sy

    def _resolve_scene_placements(self, rec, warway):
        """根据 sub_431428 + sub_4307CC 的游戏规则解析场景布置

        sub_431428 放置顺序: 友军固定→敌军固定→区域放置(1-5)→宝物固定→宝物区域放置
        sub_4307CC:200-210 flags&4 时随机敌军槽位数
        sub_452AC0: RNG = rand() % n → Python random.randrange(n)

        返回: (resolved_enemies, resolved_treas, enemy_zone_reqs, trea_zone_reqs,
               active_slots, fixed_enemy_slots, fixed_trea_indices, resolved_allies)
        """
        # ── 友军数 & 激活槽位数 (sub_4307CC:200-210) ──
        ally_count = sum(1 for c in rec['must_chars'] if c > 0 and c != 255)
        if ally_count < 1:
            ally_count = 1
        flags = rec['flags']
        if flags & 4:
            if random.randint(0, 999) >= 300:
                active_slots = random.randrange(max(1, 2 * ally_count - 2)) + 3
            else:
                active_slots = random.randrange(ally_count // 2 + ally_count) + 1
        else:
            active_slots = 18
        active_slots = min(active_slots, 18)

        # ── WarWay 区域候选格收集 ──
        zone_cells = {1: [], 2: [], 3: [], 4: [], 5: []}
        if warway:
            for gy in range(32):
                for gx in range(32):
                    raw = warway[gy * 32 + gx]
                    val = raw if raw < 128 else raw - 256
                    if 1 <= val <= 5:
                        zone_cells[val].append((gx, gy))

        occupied = set()
        resolved_enemies = {}
        resolved_treas = {}
        resolved_allies = {}
        fixed_enemy_slots = set()
        fixed_trea_indices = set()
        enemy_zone_reqs = []
        trea_zone_reqs = []

        # ═══════════════════════════════════════════════════════
        # 1. 友军固定位置 (sub_431428:74-87)
        # ═══════════════════════════════════════════════════════
        for i in range(6):
            ax = rec['ally_xy'][i * 2]
            ay = rec['ally_xy'][i * 2 + 1]
            if ax > 0 and ay > 0 and 0 <= ax < 32 and 0 <= ay < 32:
                occupied.add((ax, ay))

        # ═══════════════════════════════════════════════════════
        # 2. 敌军固定位置 (sub_431428:88-105)
        # ═══════════════════════════════════════════════════════
        for i in range(active_slots):
            eid = rec['enemy_ids'][i]
            if eid <= 0:
                continue
            ex = rec['enemy_xy'][i * 2]
            ey = rec['enemy_xy'][i * 2 + 1]
            if ex >= 0 and 0 <= ex < 32 and 0 <= ey < 32:
                resolved_enemies[i] = (ex, ey)
                fixed_enemy_slots.add(i)
                occupied.add((ex, ey))

        # ═══════════════════════════════════════════════════════
        # 3. 区域放置 — 遍历24个战斗单位槽位 (sub_431428:106-159)
        #    24 = 18敌军 + 6友军, 按 zone 1→5 顺序处理
        # ═══════════════════════════════════════════════════════
        zone_pool = {z: list(cells) for z, cells in zone_cells.items()}

        def _pick_from_zone(zone):
            """从zone候选池中随机选取一个未被占用的格"""
            candidates = [(x, y) for (x, y) in zone_pool[zone] if (x, y) not in occupied]
            if not candidates:
                return None
            gx, gy = random.choice(candidates)
            occupied.add((gx, gy))
            zone_pool[zone].remove((gx, gy))
            return (gx, gy)

        # sub_431428:138-158 按 zone 1→5, 遍历全部24个战斗槽 (18敌军+6友军)
        for zone in range(1, 6):
            # 18个敌军槽
            for i in range(18):
                eid = rec['enemy_ids'][i]
                if eid <= 0 or i in resolved_enemies:
                    continue
                if i >= active_slots:
                    continue
                ex = rec['enemy_xy'][i * 2]
                if ex != -zone:
                    continue
                pos = _pick_from_zone(zone)
                if pos:
                    resolved_enemies[i] = pos
                else:
                    enemy_zone_reqs.append((zone, i, eid))
            # 6个友军槽 (兼容友军也可能有区域请求)
            for i in range(6):
                ax = rec['ally_xy'][i * 2]
                if ax != -zone:
                    continue
                pos = _pick_from_zone(zone)
                if pos:
                    resolved_allies[i] = pos

        # ═══════════════════════════════════════════════════════
        # 4. 陷阱 + 宝物 固定/区域放置 (sub_431428:198-323)
        # ═══════════════════════════════════════════════════════
        resolved_traps = {}
        fixed_trap_indices = set()
        trap_zone_reqs = []

        # 4a. 固定位置陷阱/宝物 (sub_431428:198-223)
        for i in range(28):
            ttype = rec['trap_type'][i]
            sub_id = rec['trea_sub'][i] if i < 10 else 0
            is_trap = 1 <= ttype <= 6
            is_trea = sub_id > 0 and i < 10
            if not is_trap and not is_trea: continue
            tx = rec['trap_xy'][i * 2]; ty = rec['trap_xy'][i * 2 + 1]
            if tx >= 0 and 0 <= tx < 32 and 0 <= ty < 32:
                if is_trap: resolved_traps[i] = (tx, ty); fixed_trap_indices.add(i)
                if is_trea: resolved_treas[i] = (tx, ty); fixed_trea_indices.add(i)
                occupied.add((tx, ty))

        # 4b. 区域放置陷阱/宝物 (sub_431428:224-323)
        for zone in range(1, 6):
            for i in range(28):
                ttype = rec['trap_type'][i]
                sub_id = rec['trea_sub'][i] if i < 10 else 0
                is_trap = 1 <= ttype <= 6 and i not in resolved_traps
                is_trea = sub_id > 0 and i not in resolved_treas and i < 10
                if not is_trap and not is_trea: continue
                tx = rec['trap_xy'][i * 2]
                if tx != -zone: continue
                pos = _pick_from_zone(zone)
                if is_trap:
                    if pos: resolved_traps[i] = pos
                    else: trap_zone_reqs.append((zone, i, ttype))
                if is_trea:
                    if pos: resolved_treas[i] = pos
                    else: trea_zone_reqs.append((zone, i, self._trea_label(rec, i)))

        return (resolved_enemies, resolved_treas, resolved_traps,
                enemy_zone_reqs, trea_zone_reqs, trap_zone_reqs,
                active_slots, fixed_enemy_slots, fixed_trea_indices, fixed_trap_indices,
                resolved_allies)

    def _trea_label(self, rec, i):
        """宝物槽的显示标签 (trea_sub TKItem ID)"""
        tid = rec['trea_sub'][i] if i < 10 else 0
        if tid == 10000: return "金钱"
        elif tid > 0: return self.tkitem_names_by_id.get(tid, f"Item#{tid}")[:8]
        return ""

    def _redraw_scene(self, rerandomize=True):
        """重绘场景 (背景 + 网格 + 单位 + 宝物)
        游戏坐标体系: sub_42F9C8 等距投影, 所有元素(WSC背景/网格/单位)共享同一坐标系
        敌军/宝物位置按照 sub_431428 游戏规则解析: 固定位置 + 区域随机放置
        rerandomize=False 时复用缓存的解析位置 (拖拽时不重新随机)
        """
        canvas = self.scene_canvas
        canvas.delete('all')

        if self._current_idx < 0:
            return

        rec = self.records[self._current_idx]
        zoom = self._preview_zoom
        tile_w = int(56 * zoom)
        tile_h = int(28 * zoom)

        # ── 图层1: WSC 背景 ──
        bg_w, bg_h = 0, 0
        if self.show_bg.get() and HAS_PIL:
            wsc_idx = rec['map_id']
            if wsc_idx < 0 or wsc_idx >= len(self.wsc_offsets) - 1:
                wsc_idx = 0
            bg = self._load_wsc_background(wsc_idx)
            if bg:
                photo, bg_w, bg_h, *_ = bg
                canvas.create_image(0, 0, anchor='nw', image=photo)

        # ── 预加载 WarWay (用于渲染网格 + 场景布置解析) ──
        warway = load_warway(self.warway_path, rec['map_id']) if self.warway_path else None

        # ── 按游戏规则解析场景布置 (sub_431428 + sub_4307CC) ──
        if rerandomize:
            (resolved_enemies, resolved_treas, resolved_traps,
             enemy_zone_reqs, trea_zone_reqs, trap_zone_reqs,
             active_slots, fixed_enemy_slots, fixed_trea_indices, fixed_trap_indices,
             resolved_allies) = self._resolve_scene_placements(rec, warway)
            self._last_resolved_enemies = resolved_enemies
            self._last_resolved_treas = resolved_treas
            self._last_resolved_traps = resolved_traps
            self._last_resolved_allies = resolved_allies
            self._last_fixed_trea_indices = fixed_trea_indices
            self._last_fixed_trap_indices = fixed_trap_indices
            self._last_active_slots = active_slots
            self._last_fixed_enemy_slots = fixed_enemy_slots
            self._last_enemy_zone_reqs = enemy_zone_reqs
            self._last_trea_zone_reqs = trea_zone_reqs
            self._last_trap_zone_reqs = trap_zone_reqs
        resolved_enemies = self._last_resolved_enemies
        resolved_treas = self._last_resolved_treas
        resolved_traps = getattr(self, '_last_resolved_traps', {})
        resolved_allies = self._last_resolved_allies
        fixed_enemy_slots = getattr(self, '_last_fixed_enemy_slots', set())
        fixed_trea_indices = self._last_fixed_trea_indices
        fixed_trap_indices = getattr(self, '_last_fixed_trap_indices', set())
        trap_zone_reqs = getattr(self, '_last_trap_zone_reqs', [])
        active_slots = getattr(self, '_last_active_slots', 18)
        enemy_zone_reqs = getattr(self, '_last_enemy_zone_reqs', [])
        trea_zone_reqs = getattr(self, '_last_trea_zone_reqs', [])

        # grid原点由 _grid_to_screen 固定使用游戏常量 (dword_4E7DF0=359, dword_4E7DF4=365, 偏移10/15)
        # 这些是PE .data段编译时常量, 不随WSC分辨率变化, 所有战场通用

        # ── 图层2: WarWay 网格 (sub_42F9C8 等距投影) ──
        if self.show_grid.get() and warway:
                for gy in range(32):
                    for gx in range(32):
                        raw = warway[gy * 32 + gx]
                        # sub_4355C4/sub_431428: 地形值为 signed int8
                        val = raw if raw < 128 else raw - 256
                        sx, sy = self._grid_to_screen(gx, gy)
                        # sub_42F9C8: isometric diamond at (sx,sy) with half-width tile_w, half-height tile_h
                        pts = [
                            (sx, sy - tile_h),
                            (sx + tile_w, sy),
                            (sx, sy + tile_h),
                            (sx - tile_w, sy),
                        ]
                        if val == -1:  # WarWay -1 (0xFF) = 永久障碍
                            if not self.show_obstacle.get():
                                continue
                            color = '#553322'
                            outline = '#332211'
                        elif val < -1:  # WarWay < -1 = 临时障碍(sub_4355C4每回合+1直到0)
                            if not self.show_temp_obstacle.get():
                                continue
                            color = '#665544'
                            outline = '#443322'
                        elif val == 0:  # WarWay 0 = 普通地面
                            color = ''
                            outline = '#334422'
                        else:  # WarWay 1-5 = 特殊区域 (PlaceReq), 各区域不同颜色
                            if not self.show_zone[val - 1].get():
                                continue
                            zone_colors = {
                                1: ('#332211', '#aa6633'),  # 区域1: 棕色
                                2: ('#112233', '#3366aa'),  # 区域2: 蓝色
                                3: ('#332233', '#aa44aa'),  # 区域3: 紫色
                                4: ('#113322', '#33aa66'),  # 区域4: 青绿
                                5: ('#333311', '#aaaa33'),  # 区域5: 黄色
                            }
                            color, outline = zone_colors.get(val, ('#224433', '#44aa44'))

                        # 透明度: stipple 模拟 (tkinter Canvas 不支持 RGBA)
                        alpha = self.grid_alpha.get().rstrip('%')
                        stipple_map = {'0': '', '25': 'gray75', '50': 'gray50', '75': 'gray25', '100': 'gray12'}
                        stipple = stipple_map.get(alpha, 'gray50')
                        if alpha == '100':
                            color = ''  # 100%透明 = 无填充
                        if color:
                            canvas.create_polygon(pts, fill=color, outline=outline, width=1,
                                                  stipple=stipple, tags=('grid',))
                        else:
                            canvas.create_polygon(pts, fill='', outline=outline, width=1,
                                                  tags=('grid',))

        # ── 图层3: 宝物 (trea_xy offset 214-269, sub_431428) ──
        # 固定位置: 亮色; 区域放置: 暗色
        if self.show_trea.get():
            for i, (gx, gy) in resolved_treas.items():
                tid = rec['trap_type'][i]
                label = self._trea_label(rec, i)
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(3, tile_h // 2)
                if i in fixed_trea_indices:
                    fill_c = '#FF8C00'
                else:
                    fill_c = '#FFD700'
                canvas.create_rectangle(sx - r, sy - r, sx + r, sy + r,
                                        fill=fill_c, outline='white', width=1,
                                        tags=('trea', f'trea_{i}'))
                tag_char = "固" if i in fixed_trea_indices else "随"
                canvas.create_text(sx, sy, text=tag_char,
                                   fill='white', font=('', max(7, int(9*zoom)), 'bold'),
                                   tags=('trea',))
                canvas.create_text(sx, sy - r - 6, text=label,
                                   fill=fill_c, font=('', max(8, int(10*zoom))),
                                   tags=('trea',))
            # 宝物区域请求标记(无法解析的, 画布底部)
            if trea_zone_reqs:
                zr_x = 10
                by_zone = {}
                for z, i, lbl in trea_zone_reqs:
                    by_zone.setdefault(z, []).append(lbl)
                for zone, labels in sorted(by_zone.items()):
                    txt = f"Z{zone}:" + ",".join(labels)
                    canvas.create_text(zr_x, bg_h - 15, text=txt, anchor='nw',
                                       fill='#FFD700', font=('', max(9, int(11*zoom))),
                                       tags=('trea', 'zone_req'))
                    zr_x += len(txt) * max(7, int(8*zoom)) + 10

        # ── 图层3b: 陷阱 (sub_431428:283-323) ──
        if self.show_trap.get():
            TRAP_COLORS = {1:'#FFD700', 2:'#8B4513', 3:'#4488FF', 4:'#FF4444', 5:'#228B22', 6:'#FF69B4'}
            TRAP_NAMES = {1:'山崩',2:'泥沼',3:'漩渦',4:'火焰',5:'滾木',6:'瘴氣'}
            for i, (gx, gy) in resolved_traps.items():
                ttype = self._trap_type_at(rec, i)
                pmin, pmax = self._trap_power_at(rec, i)
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(3, tile_h // 2)
                fc = TRAP_COLORS.get(ttype, '#FF0000')
                is_fixed = i in fixed_trap_indices
                outline_c = 'white' if is_fixed else '#888'
                pts = [(sx, sy - r), (sx - r, sy + r), (sx + r, sy + r)]
                canvas.create_polygon(pts, fill=fc, outline=outline_c, width=1,
                                      tags=('trap', f'trap_{i}'))
                tname = TRAP_NAMES.get(ttype, '?') + '陷阱'
                canvas.create_text(sx, sy, text='陷',
                                   fill='white', font=('', max(7, int(9*zoom)), 'bold'),
                                   tags=('trap',))
                canvas.create_text(sx, sy - r - 8, text=tname,
                                   fill=fc, font=('', max(8, int(10*zoom))),
                                   tags=('trap',))
            # 区域陷阱无法解析的, 在底部提示
            if trap_zone_reqs:
                zr_x = 10
                by_zone = {}
                for z, i, ttype in trap_zone_reqs:
                    by_zone.setdefault(z, []).append(
                        f'{TRAP_NAMES.get(ttype,"?")}{i}')
                for zone, labels in sorted(by_zone.items()):
                    txt = f'⚠Z{zone}陷阱:' + ','.join(labels)
                    canvas.create_text(zr_x, bg_h - 35, text=txt, anchor='nw',
                                       fill='#FF4444', font=('', max(9, int(11*zoom))),
                                       tags=('trap', 'zone_req'))
                    zr_x += len(txt) * max(7, int(8*zoom)) + 10

        # ── 图层4: 单位 (sub_431428 解析后位置) ──
        # 固定位置: 亮色; 区域放置: 暗色
        if self.show_units.get():
            # 敌军 — 按 sub_431428 规则解析后的位置
            for i, (gx, gy) in resolved_enemies.items():
                eid = rec['enemy_ids'][i]
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(5, tile_h // 2)
                name = self._enemy_name(eid)
                if i in fixed_enemy_slots:
                    fill_c, text_c = '#9932CC', '#BA55D3'
                else:
                    fill_c, text_c = '#cc3333', '#ff6666'
                canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                                   fill=fill_c, outline='white', width=1,
                                   tags=('unit', 'enemy', f'enemy_{i}'))
                tag_char = "固" if i in fixed_enemy_slots else "随"
                canvas.create_text(sx, sy, text=tag_char,
                                   fill='white', font=('', max(7, int(9*zoom)), 'bold'),
                                   tags=('unit',))
                canvas.create_text(sx, sy + r + 8, text=name,
                                   fill=text_c, font=('', max(8, int(10*zoom))),
                                   tags=('unit',))
            # 敌军区域请求标记(无法解析的, 画布顶部)
            if enemy_zone_reqs:
                ezr_x = 10
                by_zone = {}
                for z, i, eid in enemy_zone_reqs:
                    by_zone.setdefault(z, []).append(self._enemy_name(eid))
                for zone, labels in sorted(by_zone.items()):
                    txt = f"Z{zone}:" + ",".join(labels)
                    canvas.create_text(ezr_x, 20, text=txt, anchor='nw',
                                       fill='#ff6666', font=('', max(9, int(11*zoom))),
                                       tags=('unit', 'enemy', 'zone_req'))
                    ezr_x += len(txt) * max(7, int(8*zoom)) + 10
            # 激活槽位提示
            if active_slots < 18:
                canvas.create_text(10, 40, text=f"[激活槽位:0-{active_slots-1}]",
                                   fill='#ff6666', font=('', max(8, int(9*zoom))),
                                   anchor='nw', tags=('unit',))

            # 友军 — ally_xy [178-189] + 区域放置解析
            for i in range(6):
                if i in resolved_allies:
                    gx, gy = resolved_allies[i]
                    fill_c, text_c = '#3366cc', '#6699ff'
                else:
                    ax = rec['ally_xy'][i*2]
                    ay = rec['ally_xy'][i*2+1]
                    if ax == 0 and ay == 0:
                        continue
                    if ax < 0 or ay < 0 or ax >= 32 or ay >= 32:
                        continue
                    gx, gy = ax, ay
                    fill_c, text_c = '#228B22', '#66CD00'
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(5, tile_h // 2)
                canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                                   fill=fill_c, outline='white', width=1,
                                   tags=('unit', 'ally', f'ally_{i}'))
                tag_char = "随" if i in resolved_allies else "固"
                canvas.create_text(sx, sy, text=tag_char,
                                   fill='white', font=('', max(7, int(9*zoom)), 'bold'),
                                   tags=('unit',))

            # 强制出战角色名称 — must_chars [2-7]
            for i in range(6):
                cv = rec['must_chars'][i]
                if cv <= 0:
                    continue
                cid = cv - 1
                name = self._char_name(cid)[:4]
                canvas.create_text(10 + i * 60, 5,
                                   text=f"[{name}]", fill='#66ccff',
                                   font=FONT, anchor='nw', tags=('unit',))

        canvas.configure(scrollregion=canvas.bbox('all'))

    # ── 场景交互 ──

    def _scene_to_grid(self, canvas_x, canvas_y):
        """canvas坐标 → 等距网格坐标 (逆推 sub_42F9C8)
        逆公式: gx = (px/56 + py/28) / 2 + 10
                 gy = (py/28 - px/56) / 2 + 15
        其中 px, py 为WSC背景图像像素坐标 (= canvas / zoom)
        """
        zoom = self._preview_zoom
        if zoom <= 0:
            return None
        px = canvas_x / zoom - 359  # 减去 dword_4E7DF0
        py = canvas_y / zoom - 365  # 减去 dword_4E7DF4
        # 逆等距: px = 56*(gx-10) - 56*(gy-15), py = 28*(gx-10) + 28*(gy-15)
        # 令 a=gx-10, b=gy-15: px=56*(a-b), py=28*(a+b)
        # → a = (px/56 + py/28)/2, b = (py/28 - px/56)/2
        a = (px / 56 + py / 28) / 2
        b = (py / 28 - px / 56) / 2
        gx = round(a + 10)
        gy = round(b + 15)
        if 0 <= gx < 32 and 0 <= gy < 32:
            return (gx, gy)
        return None

    def _find_unit_at(self, gx, gy):
        if self._current_idx < 0:
            return None
        resolved = getattr(self, '_last_resolved_enemies', {})
        for i, (egx, egy) in resolved.items():
            if egx == gx and egy == gy:
                return ('enemy', i)
        resolved_ally = getattr(self, '_last_resolved_allies', {})
        for i, (agx, agy) in resolved_ally.items():
            if agx == gx and agy == gy:
                return ('ally', i)
        rec = self.records[self._current_idx]
        for i in range(6):
            ax = rec['ally_xy'][i*2]
            ay = rec['ally_xy'][i*2+1]
            if ax == gx and ay == gy:
                return ('ally', i)
        return None

    def _find_trea_at(self, gx, gy):
        """查找解析后宝物位置, 返回 (trea_index, is_fixed) 或 None"""
        if self._current_idx < 0:
            return None
        resolved = getattr(self, '_last_resolved_treas', {})
        fixed = getattr(self, '_last_fixed_trea_indices', set())
        for i, (tgx, tgy) in resolved.items():
            if tgx == gx and tgy == gy:
                return (i, i in fixed)
        return None

    def _find_trap_at(self, gx, gy):
        if self._current_idx < 0: return None
        resolved = getattr(self, '_last_resolved_traps', {})
        fixed = getattr(self, '_last_fixed_trap_indices', set())
        for i, (tgx, tgy) in resolved.items():
            if tgx == gx and tgy == gy: return (i, i in fixed)
        return None

    def _on_scene_hover(self, event):
        cx = self.scene_canvas.canvasx(event.x)
        cy = self.scene_canvas.canvasy(event.y)
        g = self._scene_to_grid(cx, cy)
        if g is None: self.scene_info_var.set(""); return
        gx, gy = g
        unit = self._find_unit_at(gx, gy)
        if unit:
            utype, uidx = unit
            rec = self.records[self._current_idx]
            if utype == 'enemy':
                eid = rec['enemy_ids'][uidx]
                uname = self._enemy_name(eid)
                orig_x = rec['enemy_xy'][uidx * 2]
                if orig_x < 0:
                    self.scene_info_var.set(f"({gx},{gy}) 敌军:{uname} Lv.{rec['enemy_lv'][uidx]} [区域Z{abs(orig_x)}→({gx},{gy})]")
                else:
                    self.scene_info_var.set(f"({gx},{gy}) 敌军:{uname} Lv.{rec['enemy_lv'][uidx]} [固定位置]")
            else:
                ally_orig_x = rec['ally_xy'][uidx * 2]
                if ally_orig_x < 0:
                    self.scene_info_var.set(f"({gx},{gy}) 友军槽{uidx} [区域Z{abs(ally_orig_x)}→({gx},{gy})]")
                else:
                    self.scene_info_var.set(f"({gx},{gy}) 友军槽{uidx} [固定位置]")
            return
        trea = self._find_trea_at(gx, gy)
        if trea:
            ti, is_fixed = trea
            rec = self.records[self._current_idx]
            label = self._trea_label(rec, ti)
            type_tag = "固定" if is_fixed else f"区域Z{abs(rec['trap_xy'][ti*2])}→({gx},{gy})"
            if label:
                self.scene_info_var.set(f"({gx},{gy}) 宝物#{ti} {label} [{type_tag}]")
            else:
                self.scene_info_var.set(f"({gx},{gy}) 宝物槽#{ti} (空) [{type_tag}]")
            return
        trap = self._find_trap_at(gx, gy)
        if trap:
            ti, is_fixed = trap
            rec = self.records[self._current_idx]
            ttype = self._trap_type_at(rec, ti)
            TRAP_NAMES = {1:'山崩',2:'泥沼',3:'漩渦',4:'火焰',5:'滾木',6:'瘴氣'}
            tname = TRAP_NAMES.get(ttype, '?') + '陷阱'
            pmin, pmax = self._trap_power_at(rec, ti)
            type_tag = "固定" if is_fixed else f"区域Z{abs(rec['trap_xy'][ti*2])}→({gx},{gy})"
            self.scene_info_var.set(f"({gx},{gy}) 陷阱#{ti} {tname} 威力[{pmin},{pmax}] [{type_tag}]")
            return
        self.scene_info_var.set(f"({gx},{gy})")

    def _on_scene_wheel(self, event):
        zooms = [0.25, 0.33, 0.5, 0.66, 0.75, 1.0]
        current = self._preview_zoom
        if event.delta > 0:
            for z in zooms:
                if z > current:
                    self._preview_zoom = z
                    break
        else:
            for z in reversed(zooms):
                if z < current:
                    self._preview_zoom = z
                    break
        self.zoom_var.set(f"{int(self._preview_zoom * 100)}%")
        self._wsc_cache.clear()
        self._redraw_scene()

    # ── Task 12: Scene interactivity ──

    def _on_scene_click(self, event):
        """左键点击 — 编辑模式下选择/开始拖拽单位"""
        if not self.edit_mode.get():
            return
        cx = self.scene_canvas.canvasx(event.x)
        cy = self.scene_canvas.canvasy(event.y)
        g = self._scene_to_grid(cx, cy)
        if g is None:
            return
        gx, gy = g
        unit = self._find_unit_at(gx, gy)
        if unit:
            self._drag_target = unit
            self._drag_start_x = cx
            self._drag_start_y = cy

    def _on_scene_drag(self, event):
        """左键拖拽 — 移动单位"""
        if not self._drag_target:
            return
        cx = self.scene_canvas.canvasx(event.x)
        cy = self.scene_canvas.canvasy(event.y)
        g = self._scene_to_grid(cx, cy)
        if g is None:
            return
        gx, gy = g
        utype, uidx = self._drag_target
        rec = self.records[self._current_idx]
        if utype == 'enemy':
            rec['enemy_xy'][uidx * 2] = gx
            rec['enemy_xy'][uidx * 2 + 1] = gy
            self._last_resolved_enemies[uidx] = (gx, gy)
        else:
            rec['ally_xy'][uidx * 2] = gx
            rec['ally_xy'][uidx * 2 + 1] = gy
            self._last_resolved_allies[uidx] = (gx, gy)
        self._dirty = True
        self._redraw_scene(rerandomize=False)

    def _on_scene_release(self, event):
        """释放拖拽 — 同步更新编辑标签页"""
        if self._drag_target:
            self._populate_fields(self.records[self._current_idx])
        self._drag_target = None

    def _on_scene_right_down(self, event):
        """右键按下 — 开始平移"""
        self._pan_start_x = event.x
        self._pan_start_y = event.y

    def _on_scene_right_move(self, event):
        """右键拖拽 — 平移画布"""
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y
        self.scene_canvas.xview_scroll(-dx, 'units')
        self.scene_canvas.yview_scroll(-dy, 'units')
        self._pan_start_x = event.x
        self._pan_start_y = event.y

if __name__ == '__main__':
    root = tk.Tk()
    app = WarDataEditor(root)
    root.mainloop()
