# -*- coding: utf-8 -*-
"""mat_editor_v2 数据文件 IO 层 — TKMat/TKDefUnit/存档读写, 记录空判定与脚本信息。
从 mat_editor_v2.py 原样迁出, 无 UI 逻辑 (§工程化拆分)。"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mat_constants import (DWORD_COUNT, FILE_SIZE, REC_COUNT, REC_SIZE,
                           SCENE_NAME_TKT_BASE, DEFUNIT_FILE_SIZE, DEFUNIT_REC_SIZE,
                           DEFUNIT_REC_COUNT, DEFUNIT_ORIG_COUNT)
from editor_utils.lzss import lzss_decompress_save, lzss_compress_save


def get_script_info(rec):
    """根据逆向分析 (sub_409618/sub_408E5C/sub_4081F8等) 判断实体的脚本执行方式。
    返回 (script_label, tick_label):
      script_label: "A⚡B👆" 形式, A=自动(Tick), B=触发(交互), C=其他
      tick_label: tick周期数值 (d4) 或 空"""
    if is_empty(rec):
        return "", ""
    parts = []
    cur_a = rec.get('d33', 0)
    cur_b = rec.get('d34', 0)
    cur_c = rec.get('d35', 0)
    head_a = rec.get('d39', 0)
    head_b = rec.get('d40', 0)
    head_c = rec.get('d41', 0)
    max_a = rec.get('d30', 0)
    max_b = rec.get('d31', 0)
    max_c = rec.get('d32', 0)
    # A链: 自动运行 (sub_409618 中 d33>0 时自动执行)
    if head_a > 0 and max_a > 0:
        label = "A⚡" if cur_a > 0 else "A"
        parts.append(label)
    # B链: 触发/交互 (sub_4081F8/sub_408408/sub_4084E0/sub_408E5C 中交互时执行B链)
    if head_b > 0 and max_b > 0:
        label = "B👆" if cur_b > 0 else "B"
        parts.append(label)
    # C链: 其他/保留
    if head_c > 0 and max_c > 0:
        label = "C*" if cur_c > 0 else "C"
        parts.append(label)
    script_label = " ".join(parts)
    tick_val = rec.get('d4', 0)
    tick_label = str(tick_val) if tick_val > 0 else ""
    return script_label, tick_label

def scene_name(tkt, sid):
    if sid == -1: return "全局(所有场景)"
    txt = tkt.get(SCENE_NAME_TKT_BASE + sid, "")
    return txt.split('\n')[0].strip() if txt else f"场景{sid}"

# ============================================================
# 数据 IO
# ============================================================
# 预生成键名元组，消灭加载时的 6000×96 次字符串拼接
MAT_KEYS = tuple(f'd{i}' for i in range(DWORD_COUNT))

def load_mat(fp):
    with open(fp,'rb') as f: raw=f.read()
    if len(raw)!=FILE_SIZE: raise ValueError(f"文件大小异常:{len(raw)}")
    recs=[]
    fmt = '<' + 'i' * DWORD_COUNT
    for i, dw in enumerate(struct.iter_unpack(fmt, raw)):
        if i >= REC_COUNT: break
        rec = dict(zip(MAT_KEYS, dw))
        rec['index'] = i
        rec['_has_data'] = any(dw)
        recs.append(rec)
    return recs

def save_mat(fp, recs):
    buf=bytearray(FILE_SIZE)
    for rec in recs[:REC_COUNT]:
        off=rec['index']*REC_SIZE
        for di in range(DWORD_COUNT): struct.pack_into('<i',buf,off+di*4,rec.get(f'd{di}',0))
    with open(fp,'wb') as f: f.write(bytes(buf))
    return True

def is_empty(rec): return not rec.get('_has_data', rec['d0'] != 0)
def has_data(rec): return rec.get('_has_data', rec['d0'] != 0)

def save_defunit(fp, defunit_recs):
    """保存 TKDefUnit.dat — 每条 16 字节, 文件长度动态确定。

    写出条数 = max(原版 5000, 最高非空记录索引+1), 上限 DEFUNIT_REC_COUNT:
      - 仅用到 ≤5000 条时写出 80000 字节 (与原版一致, 未打补丁的引擎可直接加载);
      - 剧情扩充用到 5000+ 条时文件相应增长, 需 tks_launcher_gui 的 tkdefunit_count
        补丁配合 (使引擎按文件实际条数分配缓冲区)。如此既不无谓增大未扩充
        存档的文件, 又能支持扩充。
    """
    max_idx = -1
    for rec in defunit_recs:
        idx = rec.get('index', -1)
        if 0 <= idx < DEFUNIT_REC_COUNT and any(rec.get(f'f{i}', 0) for i in range(8)):
            if idx > max_idx:
                max_idx = idx
    count = min(max(DEFUNIT_ORIG_COUNT, max_idx + 1), DEFUNIT_REC_COUNT)
    buf = bytearray(count * DEFUNIT_REC_SIZE)
    for rec in defunit_recs:
        off = rec['index'] * DEFUNIT_REC_SIZE
        if off < 0 or off + DEFUNIT_REC_SIZE > len(buf):
            continue
        for fi in range(8):
            struct.pack_into('<H', buf, off + fi * 2, rec.get(f'f{fi}', 0))
    with open(fp, 'wb') as f:
        f.write(bytes(buf))
    return True

# ============================================================
# 存档文件读写 (来自 sub_410ED4 SaveTKMat / sub_41103C LoadTKMat)
# ============================================================
SAVE_SEG1_SIZE = 3432
SAVE_SEG2_SIZE = 5768
SAVE_WARPC_OFFSET = 9200

def load_mat_from_save(save_path):
    """从存档 sav.N 解压 Frame1 并解析为 TKMat records (同 load_mat 格式)"""
    with open(save_path, 'rb') as f:
        raw = f.read()
    if 4 > len(raw):
        raise ValueError("文件太短")
    comp1 = struct.unpack_from('<I', raw, 0)[0]
    if 4 + comp1 + 4 > len(raw):
        raise ValueError("Frame2 大小字段缺失")
    frame1 = lzss_decompress_save(raw[4:4 + comp1])
    if len(frame1) != FILE_SIZE:
        raise ValueError(f"Frame1 解压大小异常: {len(frame1)} (期望 {FILE_SIZE})")
    # 解析为 records (与 load_mat 一致)
    recs = []
    fmt = '<' + 'i' * DWORD_COUNT
    for i, dw in enumerate(struct.iter_unpack(fmt, frame1)):
        if i >= REC_COUNT: break
        rec = dict(zip(MAT_KEYS, dw))
        rec['index'] = i
        rec['_has_data'] = any(dw)
        recs.append(rec)
    return recs

def save_mat_to_save(save_path, records):
    """将 TKMat records 写回存档 sav.N 的 Frame1 (保留 Frame2 不变)"""
    with open(save_path, 'rb') as f:
        raw = f.read()
    # 读取 Frame2 原始压缩块 (保留不变)
    comp1 = struct.unpack_from('<I', raw, 0)[0]
    off2 = 4 + comp1
    comp2 = struct.unpack_from('<I', raw, off2)[0]
    frame2_block = raw[off2 + 4:off2 + 4 + comp2]
    # 构建新 Frame1
    buf = bytearray(FILE_SIZE)
    for rec in records[:REC_COUNT]:
        off = rec['index'] * REC_SIZE
        for di in range(DWORD_COUNT):
            struct.pack_into('<i', buf, off + di * 4, rec.get(f'd{di}', 0))
    comp1_new = lzss_compress_save(bytes(buf))
    # 回读验证
    dec1 = lzss_decompress_save(comp1_new)
    if dec1 != bytes(buf):
        raise RuntimeError("Frame1 压缩回写验证失败!")
    # 备份
    if os.path.exists(save_path):
        try:
            with open(save_path, 'rb') as s:
                with open(save_path + '.bak', 'wb') as d: d.write(s.read())
        except Exception:
            pass
    # 写入
    with open(save_path, 'wb') as f:
        f.write(struct.pack('<I', len(comp1_new)))
        f.write(comp1_new)
        f.write(struct.pack('<I', len(frame2_block)))
        f.write(frame2_block)
    return True
