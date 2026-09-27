# -*- coding: utf-8 -*-
"""mat_editor 后台加载纯函数 — TKMat/TKT/TKDefUnit 主加载与 JVG 贴图/脚本专线。

原为 QThread 子类 (DataLoaderThread/JvgLoaderThread), T13-b 改为纯函数,
由 mat_editor 经 editor_utils.task_runner.run_background 调度
(fn 在工作线程执行, 只做纯计算/文件 IO)。"""
import os
import struct
import time
import traceback
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mat_constants import DEFUNIT_REC_COUNT
from editor_utils.lzss import lzss_decompress_dat as lzss_decompress
from mat_text_codec import load_tkt_raw, TktLazyDict, load_tkd, parse_defines
from mat_dat_io import load_mat
from mat_script_desc import _load_char_names
from mat_render import _get_jvg


def load_main_data(dat_path, tkt_path, game_dir=None, preloaded_records=None,
                   save_path=None):
    """主数据加载 (原 DataLoaderThread.run), 返回结果字典。异常向上抛出。"""
    d = game_dir or (os.path.dirname(dat_path) if dat_path else '')
    result = {}

    # 1. TKT (延迟解析：只切字节块，首次访问时才解码)
    if tkt_path:
        raw_tkt = load_tkt_raw(tkt_path)
        tkt_lazy = TktLazyDict(raw_tkt)
        result['tkt_all'] = tkt_lazy
        result['tkt_scenes'] = tkt_lazy
    else:
        result['tkt_scenes'] = {}
        result['tkt_all'] = {}

    # 2. TKDefUnit
    defunit_recs = []
    defunit_next = {}
    defunit_entity = {}
    du_p = os.path.join(d, "TKDefUnit.Dat")
    if os.path.exists(du_p):
        with open(du_p, 'rb') as f:
            du_raw = f.read()
        for i, fields in enumerate(struct.iter_unpack('<HHHHHHHH', du_raw)):
            if i >= DEFUNIT_REC_COUNT: break
            f0, f1, f6 = fields[0], fields[1], fields[6]
            if f0 == 0 and f1 == 0: continue
            rec = {'index': i, 'f0': f0, 'f1': f1, 'f2': fields[2],
                   'f3': fields[3], 'f4': fields[4], 'f5': fields[5],
                   'f6': f6, 'f7': fields[7]}
            defunit_recs.append(rec)
            if f6 != 0: defunit_next[i] = f6
            defunit_entity.setdefault(f1, []).append(i)
    result['defunit_recs'] = defunit_recs
    result['defunit_next'] = defunit_next
    result['defunit_entity'] = defunit_entity

    # 3 & 4. TKD 脚本与 TKItem 物品数据 (LZSS 解压耗时, 移至贴图专线 load_assets)
    result['tkd_defines'] = []
    result['tkd_header'] = ''
    result['tkd_define_map'] = {}
    result['item_names'] = {}

    # 5. SC.GRP section count
    sc_grp_section_count = 0
    grp_path = os.path.join(d, "SC.GRP")
    idx_path = os.path.join(d, "SC.IDX")
    if os.path.exists(grp_path) and os.path.exists(idx_path):
        idata = open(idx_path, 'rb').read()
        fsize = os.path.getsize(grp_path)
        offs = [struct.unpack_from('<I', idata, i)[0] for i in range(0, len(idata), 4)]
        if offs and offs[-1] == fsize:
            sc_grp_section_count = len(offs) - 1
    result['sc_grp_section_count'] = sc_grp_section_count

    # 6. TKMat (JVG 贴图已剥离至贴图专线 load_assets)
    if preloaded_records is not None:
        result['records'] = preloaded_records
    elif save_path:
        # 存档模式: 从 sav.N Frame1 解析 TKMat records (P3-3 移入后台)
        from mat_dat_io import load_mat_from_save
        result['records'] = load_mat_from_save(save_path)
    else:
        result['records'] = load_mat(dat_path)

    return result


def load_assets(dat_path, tkt_lazy=None, game_dir=None):
    """贴图/TKD/物品名后台加载 (原 JvgLoaderThread.run)。

    与原线程行为一致: 任何异常打印后返回空结果, 不向上抛出。"""
    try:
        d = game_dir or (os.path.dirname(dat_path) if dat_path else '')
        res = {}

        # TKD 脚本解压与解析
        time.sleep(0.001)
        tkd_p = os.path.join(d, "TKD.dat")
        if os.path.exists(tkd_p):
            tkd_text = load_tkd(tkd_p)
            tkd_defines, tkd_header = parse_defines(tkd_text)
            res['tkd_defines'] = tkd_defines
            res['tkd_header'] = tkd_header
            res['tkd_define_map'] = {dd['define_id']: dd for dd in tkd_defines}

        # TKItem 物品名解压与解析
        time.sleep(0.001)
        item_names = {}
        item_p = os.path.join(d, "TKItem.dat")
        if os.path.exists(item_p) and tkt_lazy:
            with open(item_p, 'rb') as f:
                item_raw = f.read()
            item_dec = lzss_decompress(item_raw)
            # 兜底: 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
            if len(item_raw) % 64 == 0 and (len(item_dec) == 0 or len(item_dec) % 64 != 0):
                item_dec = item_raw
            # iter_unpack 要求缓冲区为 64 的整数倍, 截掉不足一条的尾部;
            # 按实际记录数解析 (tkitem_expand 后可超过原版 600 条)
            for i, fields in enumerate(struct.iter_unpack('<' + 'h' * 32,
                                              item_dec[:len(item_dec) // 64 * 64])):
                item_id, name_id = fields[0], fields[2]
                if item_id > 0 and name_id > 0:
                    name = tkt_lazy.get(name_id, '')
                    if name:
                        item_names[item_id] = name.split('\n')[0].strip()
        res['item_names'] = item_names

        # 角色名
        time.sleep(0.001)
        if tkt_lazy:
            _load_char_names(d, tkt_lazy)

        # JVG 贴图
        time.sleep(0.001)
        res['ani_jvg'] = _get_jvg(os.path.join(d, "Ani.JVG"))
        res['cha_jvg'] = _get_jvg(os.path.join(d, "Cha.JVG"))
        res['cur_jvg'] = _get_jvg(os.path.join(d, "Cur.JVG"))

        return res
    except Exception as e:
        print("Background asset load error:", e, traceback.format_exc())
        return {}
