# -*- coding: utf-8 -*-
"""mat_editor 后台加载线程 — TKMat/TKT/TKDefUnit 主加载与 JVG 贴图/脚本专线。
从 mat_editor.py 原样迁出 (§工程化拆分)。"""
import os
import struct
import time
import traceback
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from PySide6.QtCore import QThread, Signal

from mat_constants import DEFUNIT_REC_COUNT
from editor_utils.lzss import lzss_decompress_dat as lzss_decompress
from mat_text_codec import load_tkt_raw, TktLazyDict, load_tkd, parse_defines
from mat_dat_io import load_mat
from mat_script_desc import _load_char_names
from mat_render import _get_jvg


# ============================================================
# 后台异步加载器
# ============================================================
class DataLoaderThread(QThread):
    finished_load = Signal()
    error_load = Signal(str)

    def __init__(self, dat_path, tkt_path, game_dir=None, preloaded_records=None):
        super().__init__()
        self.dat_path = dat_path
        self.tkt_path = tkt_path
        self.game_dir = game_dir or os.path.dirname(dat_path) if dat_path else ''
        self.preloaded_records = preloaded_records

    def run(self):
        try:
            d = self.game_dir
            result = {}

            # 1. TKT (延迟解析：只切字节块，首次访问时才解码)
            if self.tkt_path:
                raw_tkt = load_tkt_raw(self.tkt_path)
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

            # 3 & 4. TKD 脚本与 TKItem 物品数据 (LZSS 解压耗时，已移至后台线程)
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

            # 6. TKMat (JVG 贴图已剥离至独立线程 JvgLoaderThread)
            if self.preloaded_records is not None:
                result['records'] = self.preloaded_records
            else:
                result['records'] = load_mat(self.dat_path)

            self.result_data = result
            self.finished_load.emit()
        except Exception as e:

            self.error_load.emit(str(e) + "\n" + traceback.format_exc())


# ============================================================
# 后台异步加载器 (贴图专线)
# ============================================================
class JvgLoaderThread(QThread):
    finished_jvg = Signal()

    def __init__(self, dat_path, tkt_lazy=None, game_dir=None):
        super().__init__()
        self.dat_path = dat_path
        self.tkt_lazy = tkt_lazy
        self.game_dir = game_dir or os.path.dirname(dat_path) if dat_path else ''
        self.jvg_result = {}

    def run(self):
        try:
            d = self.game_dir
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
            if os.path.exists(item_p) and self.tkt_lazy:
                with open(item_p, 'rb') as f:
                    item_raw = f.read()
                item_dec = lzss_decompress(item_raw)
                # 兜底: 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
                if len(item_raw) % 64 == 0 and (len(item_dec) == 0 or len(item_dec) % 64 != 0):
                    item_dec = item_raw
                ITEM_CNT = 600
                for i, fields in enumerate(struct.iter_unpack('<' + 'h' * 32, item_dec)):
                    if i >= ITEM_CNT: break
                    item_id, name_id = fields[0], fields[2]
                    if item_id > 0 and name_id > 0:
                        name = self.tkt_lazy.get(name_id, '')
                        if name:
                            item_names[item_id] = name.split('\n')[0].strip()
            res['item_names'] = item_names

            # 角色名
            time.sleep(0.001)
            if self.tkt_lazy:
                _load_char_names(d, self.tkt_lazy)

            # JVG 贴图
            time.sleep(0.001)
            res['ani_jvg'] = _get_jvg(os.path.join(d, "Ani.JVG"))
            res['cha_jvg'] = _get_jvg(os.path.join(d, "Cha.JVG"))
            res['cur_jvg'] = _get_jvg(os.path.join(d, "Cur.JVG"))

            self.jvg_result = res
            self.finished_jvg.emit()
        except Exception as e:

            print("Background asset load error:", e, traceback.format_exc())
            self.jvg_result = {}
            self.finished_jvg.emit()
