#!/usr/bin/env python3
"""
TKMat.Dat 地图实体编辑器 v2.3 — PySide6 Godot 风格版
=============================================================
逆向依据 (已通过 运行时转储 反编译源码逐字段验证):
  sub_412688:21: TKMat.Dat → dword_51AF40 (2304000B, 6000×384B, 96 DWORD/实体) ✓已验证
  sub_402E88: TKDefUnit.dat 加载 (5000×16B) ✓已验证
  sub_405CBC: 实体类型分支渲染 (5/10/15/16/20/110/200) ✓已验证
  sub_4077E4: 朝向 [13] ✓已验证
  sub_407070: 坐标 [10][11], 碰撞盒 [18][19][20][21] ✓已验证
  sub_406864: 渲染混合 [24](switch 0-5), blend_param[25], 优先级[22], 精灵偏移[26][27], 阴影帧[55] ✓已验证
  sub_409618: 主Tick循环 — A链=自动(d33>0) B链=触发(交互), d4=Tick周期, d3=等待计时器 ✓已验证
  sub_4081F8: type=10 出入传送点 — d50条件, d51方向掩码, d52目标场景, d53/d54目标XY, d56朝向 ✓已验证
  sub_4084E0: type=16 随机战斗区 — d50条件, d51方向掩码, d52-d54战斗ID组(3连), d55-d57概率组(3连, v4[3]=*(v4+12B)对齐), d60冷却基准, d61冷却计时, d62等级同步(0固定/1追随队伍均级) ✓已验证
  sub_408704: type=20 事件对象 — 动画帧推进(d14/d17递增), d66循环等待, d67帧起点, d68终点, d69保留末帧, d71-d95音效事件对(偶数=音效ID/奇数=触发帧, 汇编: mov edx,[eax+0x140]传入PlaySound) ✓已验证
  type=5: 脚本对象 — sub_409618 显式跳过(无专用tick), 仅执行脚本(sub_40EBD4) ✓已验证
  sub_408E5C: 玩家点击交互 — B链触发, d34条件脚本 ✓已验证
  sub_408B30: 特殊机关(110) — d50帧计数器, d51帧偏移, d52行为模式(0/1/2), d53-d64物品组 ✓已验证
  sub_40EBD4: 脚本VM — d42=PC, d43=saved_PC, d30-d32=max链, d33-d35=cur链, End模式0xFFFF-0xFFFA ✓已验证
  sub_405CBC+sub_4077E4+sub_408E5C: type=200 NPC — d51立绘ID→d52句柄, d53方向模式(4/8), d55阴影帧, d56-d62寻路备份, d64行走动画, d70站桩/行走 ✓已验证
  
  验证方法: 反编译 .c 文件中 entity 指针偏移量 ÷ 4 = dword 索引, 与编辑器字段索引对照确认

用法:
  python mat_editor_v2.py
"""

import struct, os, sys, re, csv, json, base64, time
from collections import OrderedDict, defaultdict, Counter

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QSplitter, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton,
    QCheckBox, QTextEdit, QPlainTextEdit, QComboBox, QMessageBox, QFileDialog,
    QDialog, QGridLayout, QFrame, QScrollArea, QTabWidget, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QSizePolicy, QStatusBar
)
from PySide6.QtGui import (
    QAction, QKeySequence, QColor, QFont, QIcon, QPixmap, QImage,
    QPainter, QTextCursor, QTextCharFormat, QSyntaxHighlighter
)
from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QSize, QThread, Signal, QTranslator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import ThemeManager
from editor_utils.dock_components import DockHeader, create_dock
from editor_utils.lzss import lzss_decompress_dat as lzss_decompress, lzss_decompress_save, lzss_compress_save
from editor_utils.ui_helpers import export_csv, confirm_close
from editor_utils.mod_exporter import (
    diff_records, diff_text_defines, compute_crc32, generate_mod_json,
    pack_tksmod, build_data_diff_json, build_text_diff_json, ModMetadataDialog,
    ask_reference_directory, load_reference_dat_fields,
    get_tksmod_info, import_tksmod_records, import_tksmod_text_defines,
    import_tksmod_blocks,
    ModImportPreviewDialog,
    diff_binary_blocks, build_block_diff_json, load_grp_raw_sections,
)

# ============================================================
# 常量
# ============================================================
REC_SIZE = 384; REC_COUNT = 6000; FILE_SIZE = 2304000; DWORD_COUNT = 96
SCENE_NAME_TKT_BASE = 300
DEFUNIT_REC_SIZE = 16; DEFUNIT_REC_COUNT = 5000; DEFUNIT_FILE_SIZE = 80000

ENTITY_TYPES = {0:"空槽",5:"脚本对象",10:"出入传送点",15:"事件触发区",16:"随机战斗区",
                20:"事件对象",110:"特殊机关",200:"NPC角色"}
TYPE_COLORS = {0:"#AAA",5:"#2196F3",10:"#4CAF50",15:"#FF9800",16:"#795548",
               20:"#9C27B0",110:"#E91E63",200:"#F44336"}
TYPE_COLORS_RGBA = {0:(170,170,170),5:(33,150,243),10:(76,175,80),15:(255,152,0),
                    16:(121,85,72),20:(156,39,176),110:(233,30,99),200:(244,67,54)}
ANIM_SETS = {0:"空(无动画)",1:"Cha.JVG(角色)",4:"Ani.JVG(动画)",5:"Cur.JVG(光标)"}
DISPLAY_MODES = {"游戏默认":"auto","动画":"ani","角色":"cha","线框":"wire"}
_JVG_CACHE = {}  # filepath → JVGFile
_SPRITE_CACHE = {}  # filepath, global_idx → PIL.Image

# ============================================================
# TKT 文本颜色渲染 (依据 tkt_editor.py / sub_44E49C)
# ============================================================
# FCOLOR 1-32 调色板 (dword_A2C524[32], RGB565 LE)
_GAME_PALETTE_565 = [
    0x0000, 0x0000, 0x8410, 0x8000, 0x8400, 0x0400, 0x0410, 0x0010, 0x8010,
    0x8200, 0x8008, 0x4400, 0x0408, 0x4010, 0x0210, 0x0000, 0x0000,
    0xF79B, 0xC618, 0xF800, 0xFFE0, 0x07E0, 0x07FF, 0x001F, 0xF81F,
    0xFC08, 0xFA10, 0x87E8, 0x47F0, 0x821F, 0x441F, 0x31EA, 0xFFFF,
]

def _rgb565_to_hex(rgb565):
    r5 = (rgb565 >> 11) & 0x1F; g6 = (rgb565 >> 5) & 0x3F; b5 = rgb565 & 0x1F
    r8 = (r5 << 3) | (r5 >> 2); g8 = (g6 << 2) | (g6 >> 4); b8 = (b5 << 3) | (b5 >> 2)
    return f'#{r8:02X}{g8:02X}{b8:02X}'

GAME_COLORS = {i: _rgb565_to_hex(_GAME_PALETTE_565[i]) for i in range(1, 33)}
DEFAULT_TKT_FCOLOR = GAME_COLORS[32]  # 白色

# 控制字节映射 (sub_4019D0): code -> (name, data_bytes)
_CONTROL_TAGS = {
    0x01: ("FRESET",  1), 0x02: ("FCOLOR",  1), 0x03: ("FCOLORD", 3),
    0x04: ("FSIZE",   1), 0x05: ("FTYPE",   1), 0x14: ("TEXT",    2),
    0x15: ("VARNUM",  1), 0x16: ("VARTXT",  1), 0x1D: ("NAME",    1),
}
_LINE_SEP = 0x1E

def decode_tkt_bytes(data):
    """将原始 TKT 字节流解码为含 <TAG,n> 标记的 UTF 文本。
    依据 tkt_editor.py decode_line() — 控制字节 → <TAG,n>, Big5 → UTF"""
    out = []; buf = bytearray(); i, n = 0, len(data)
    def flush():
        if buf:
            try: out.append(buf.decode('big5', errors='replace'))
            except: out.append(buf.decode('gbk', errors='replace'))
            buf.clear()
    while i < n:
        b = data[i]
        if b in _CONTROL_TAGS:
            tag_name, dlen = _CONTROL_TAGS[b]
            if i + dlen < n:
                flush()
                if dlen == 1:
                    out.append(f'<{tag_name},{data[i+1]}>')
                elif dlen == 2:
                    val = data[i+1] | (data[i+2] << 8)
                    out.append(f'<{tag_name},{val}>')
                else:  # dlen==3: FCOLORD
                    out.append(f'<{tag_name},{data[i+1]},{data[i+2]},{data[i+3]}>')
                i += 1 + dlen; continue
        if b == _LINE_SEP:
            flush(); out.append('\n'); i += 1; continue
        if b < 0x20:
            flush(); out.append(f'<RAW,0x{b:02X}>'); i += 1; continue
        if b >= 0x80 and i + 1 < n:
            buf.append(b); buf.append(data[i+1]); i += 2
        else:
            buf.append(b); i += 1
    flush()
    return ''.join(out)

_TKT_TAG_RE = re.compile(r'<([A-Z]+),(\d+(?:,\d+)*)>')

def parse_tkt_colored_segments(text):
    """将含 <FCOLOR,n>/<FCOLORD,r,g,b>/<FRESET,n> 的 TKT 文本解析为 [(text, color_hex), ...]。
    忽略字体控制标签 (FSIZE/FTYPE/NAME 等), 只处理颜色。"""
    segments = []
    cur_color = DEFAULT_TKT_FCOLOR
    prev_color = cur_color
    buf = []
    i, n = 0, len(text)

    def flush():
        if buf:
            segments.append((''.join(buf), cur_color))
            buf.clear()

    while i < n:
        m = _TKT_TAG_RE.match(text, i)
        if m:
            flush()
            tag_name = m.group(1); val_str = m.group(2)
            if tag_name == 'FCOLOR':
                try:
                    val = int(val_str)
                    if 1 <= val <= 32:
                        prev_color = cur_color
                        cur_color = GAME_COLORS[val]
                except ValueError: pass
            elif tag_name == 'FCOLORD':
                parts = val_str.split(',')
                if len(parts) == 3:
                    try:
                        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                            prev_color = cur_color
                            cur_color = f'#{r:02X}{g:02X}{b:02X}'
                    except ValueError: pass
            elif tag_name == 'FRESET':
                try:
                    val = int(val_str)
                    if val == 1:
                        cur_color = DEFAULT_TKT_FCOLOR
                    elif val == 2:
                        cur_color = prev_color
                except ValueError: pass
            # 其他标签 (TEXT/VARNUM/VARTXT/NAME/FSIZE/FTYPE) 作为文本保留
            else:
                buf.append(text[m.start():m.end()])
            i = m.end()
        elif text[i] == '<' and i + 6 < n:
            rm = re.match(r'<RAW,0x([0-9A-Fa-f]{2})>', text[i:])
            if rm:
                flush()
                buf.append(f'[RAW:{rm.group(1)}]')
                i += rm.end()
                continue
            buf.append(text[i]); i += 1
        else:
            buf.append(text[i]); i += 1
    flush()
    return segments

BASIC_FIELDS = [
    ("type",0,"实体类型","实体类型: 5=脚本 10=出入传送 15=触发区 16=战斗区 20=事件 110=机关 200=NPC。源码: sub_405CBC *v2==10/20/110/200 分支, sub_409618 类型调度"),
    ("scene_id",1,"场景ID","所属场景 (-1=全局)。TKT_ID = scene_id + 300。源码: sub_405CBC v13[1]<0||v13[1]==dword_755B58 场景过滤"),
    ("param",3,"等待计时","等待计时(帧数)。SetWait(min,max)写入随机值; >0时每帧递减并挂起实体, ==0时就绪, <0时永久挂起。源码: sub_40BF88 SetWait写入, sub_409618 if(d3!=0){d3>0则d3--}跳过; else进入tick"),
    ("tick",4,"执行间隔","执行间隔(帧数)。每帧累加计数器, 达到此值时触发实体类型逻辑和A链脚本并归零。0或1=每帧执行。源码: sub_40C388 SetTick写入, sub_409618 if(++d5>=d4){d5=0; 执行}"),
    ("cursor_id",8,"光标动画","鼠标悬停光标动画编号。传送点(type=10)设为3显示开门动画。源码: sub_411BA4→sub_45408C 选择Cur.JVG块, sub_412390 设置光标"),
    ("anim_set",9,"动画集ID","动画集索引。源码: sub_405CBC dword_755AC0[v2[9]]查JVG表, sub_406864 a1[9]获取精灵资源"),
    ("x",10,"坐标X","世界坐标X (像素)。源码: sub_407070 a1[10]=a2 设置, sub_406864 byte+40 屏幕坐标=entity[d10]-camera_x+d[d26]"),
    ("y",11,"坐标Y","世界坐标Y (像素)。源码: sub_407070 a1[11]=a3 设置, sub_406864 byte+44 屏幕坐标=entity[d11]-camera_y+d[d27]"),
    ("direction",13,"朝向","朝向 1~8。源码: sub_4077E4 a1[13]=a2, 仅1~8有效, type=200时更新帧索引"),
    ("hint_id",23,"提示文本ID","鼠标悬停提示的TKT文本ID。传送点(type=10): 设为 300+目标场景ID 以显示目标场景名。源码: sub_412390"),
    ("blend_mode",24,"混合模式","主精灵渲染混合模式。源码: sub_406864 byte+96 switch(0~5): 0=正常sub_4544EC 1=染色sub_454D24 2=加法sub_4559D0 3=减法sub_458020 4=亮度alpha 5=翻转sub_458D08"),
    ("blend_param",25,"混合参数","混合参数, byte+100为WORD。源码: sub_406864 mode=1时param作颜色索引, mode=2时param作加法缩放(0或>31=全加法)"),
    ("shadow_frame",55,"阴影帧","type=200: Cha.JVG全局帧索引(0=无1=小2=大)。源码: sub_406864 byte+220 *(int*)(ptr+220)>0时调用sub_458020/sub_45AA08绘制阴影帧"),]
FLAG_FIELDS = [
    ("flags",2,"标志位","位域。bit0=启用 bit1=可见 bit2=可交互 bit3=提示 bit4=忙碌 bit5=恢复 bit8=已拾取(type110) bit16=动画循环。源码: sub_406864 byte+8 bit0/1/2检查, sub_409618 byte+8 bit0启用, sub_408B30 byte+9 bit0=已拾取, sub_408E5C byte+8 bit4/5繁忙/恢复"),]
POS_FIELDS = [
    ("bound_x",18,"碰撞X","碰撞盒X起点。type=5可点击区域, type=10/16碰撞检测。源码: sub_408108/sub_410B74"),
    ("bound_y",19,"碰撞Y","碰撞盒Y起点。type=5可点击区域, type=10/16碰撞检测。源码: sub_408108/sub_410B74"),
    ("bound_w",20,"碰撞宽","碰撞盒/区域宽度。type=10出入传送点和type=16随机战斗区使用。源码: sub_408108/sub_4084E0 AABB碰撞检测"),
    ("bound_h",21,"碰撞高","碰撞盒/区域高度。type=10出入传送点和type=16随机战斗区使用。源码: sub_408108/sub_4084E0 AABB碰撞检测"),]
ANIM_FIELDS = [
    ("dir_mode",53,"方向模式/目标X","type=200:方向模式(0=静态/4=四向/8=八向) type=5:目标X type=16:战斗组2-ID type=110:组1物品ID(复用ITEM字段)。源码: sub_4077E4 a1[53]==4/8方向分支, sub_4081F8 byte+212(传送目标X), sub_4084E0 a2+212(战斗组2-ID), sub_408B30 byte+212"),
    ("target_y",54,"目标Y/物品上限","type=200:目标Y type=5:目标Y type=16:战斗组3-ID type=110:组1物品ID上限(复用ITEM字段)。源码: sub_4081F8 byte+216(传送目标Y), sub_4084E0 a2+216(战斗组3-ID), sub_408B30 byte+216"),
    ("sub_model",64,"子模型ID","type=20/200:Ani.JVG块(type=20事件动画/type=200行走动画) type=110:组3数量上限(复用ITEM字段)。type=20 100%有值(1~592)。源码: sub_405CBC v2[64]作为sub_4540E8/sub_45410C的JVG块参数"),
    ("anim_cycle_wait",66,"动画循环等待","动画循环后随机等待帧数上限。<0:不循环 0:立即循环 >0:random(N)等待。type=20/200共用。源码: sub_408704 if(*(a2+264)>0)d3=random(*(a2+264)), if(*(a2+264)<0)帧终点不重置"),
    ("end_frame_hold",69,"结束保留帧","非零时动画播放到终点后保留最后一帧不重置。type=20/200共用。源码: sub_408704 if(*(a2+276)) d68--, d14-- (帧回退保留)")]
class TktLazyDict:
    """延迟解析 TKT 文本：只在第一次用到某条文本时才执行耗时的 decode_tkt_bytes"""
    def __init__(self, raw_dict):
        self.raw = raw_dict
        self.cache = {}

    def get(self, eid, default=''):
        if eid in self.cache:
            return self.cache[eid]
        if eid in self.raw:
            txt = decode_tkt_bytes(self.raw[eid])
            self.cache[eid] = txt
            return txt
        return default

    def __getitem__(self, eid):
        return self.get(eid, '')

    def __contains__(self, eid):
        return eid in self.raw

def load_tkt_raw(tkt_path):
    """仅提取字节流块 — 委托给 editor_utils.tkt_loader"""
    from editor_utils.tkt_loader import load_tkt_raw as _load
    return _load(tkt_path)

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

SCRIPT_FIELDS = [
    ("dialog_color",28,"对话颜色","TalkA/TalkB 文字颜色索引(0~31), 第2参数=TKT文本ID。源码: sub_44B028 查表 dword_A2C528"),
    ("max_A",30,"A链·长度","DEFINE链A 的节点总数。Tick自动执行时 cur_A 从1递增至此值后归零循环。源码: sub_40EBD4 byte+120=d30, End(1): if(++d33>d30)d33=0"),
    ("max_B",31,"B链·长度","DEFINE链B 的节点总数。交互触发时 cur_B 从1递增至此值后归零循环。源码: sub_40EBD4 byte+124=d31, End(2): if(++d34>d31)d34=0"),
    ("max_C",32,"C链·长度","DEFINE链C 的节点总数。保留链, 通常不使用。源码: sub_40EBD4 byte+128=d32, End(3): if(++d35>d32)d35=0"),
    ("cur_A",33,"A链·进度","当前 Tick 执行的 DEFINE 节点位置(1-based)。SetNowDef命令可跳转。源码: sub_40EBD4 byte+132=d33, End(4):d33=0重置到起点"),
    ("cur_B",34,"B链·进度","当前交互触发的 DEFINE 节点位置(1-based)。源码: sub_40EBD4 byte+136=d34, End(5):d34=0重置"),
    ("cur_C",35,"C链·进度","当前 C链 DEFINE 节点位置(1-based)。源码: sub_40EBD4 byte+140=d35, End(6):d35=0重置"),
    ("head_A",39,"A链·头索引","DEFINE链A 的首个 TKDefUnit 记录索引。sub_4066F0(entity,0)沿此遍历链表。修改后需同步 DefUnit 数据"),
    ("head_B",40,"B链·头索引","DEFINE链B 的首个 TKDefUnit 记录索引。sub_4066F0(entity,1)沿此遍历。交互/传送/战斗触发时执行此链"),
    ("head_C",41,"C链·头索引","DEFINE链C 的首个 TKDefUnit 记录索引。保留链, 当前游戏未使用"),
    ("defunit_idx",44,"当前DefUnit#","运行时: sub_4066F0 链遍历时填入当前节点的 DefUnit 索引。文件中值=-1为正常(尚未遍历)。源码: sub_40EBD4 line18 dword_51AF40[96*a1+44], dword_753500+16*idx+4读取链数据"),]
INTERACT_FIELDS = [
    ("cond_id",50,"条件参数","语义视实体类型而定: type=10传送/15触发/16战斗→门禁阈值(须=player_d22); type=110机关→动画触发器(d52=0时>0播放拾取动画); type=200NPC→引擎不使用; type=5脚本→自由字段。源码: sub_4081F8:15/408408:13/4084E0:25 比对player_d22; sub_408B30:74 帧递增"),
    ("dir_mask",51,"方向掩码","bit0-7对应朝向1-8, 0=任意方向。type=110(d52=0):动画帧基偏移。type=200:立绘ID(Cha.JVG块)。源码: sub_4081F8 byte+204=d51作方向掩码(d51&(1<<(player_d13-1))), sub_408B30 byte+204"),
    ("target_scene",52,"功能参数","语义视类型而定: type=10→目标地图ID(ChangeScene参数); type=16→战斗组1-ID(连续3组:d52-d54=ID, d55-d57=概率); type=110→行为模式(0=标记+动画 1=清除隐藏 2+无, 游戏中全为1); type=5/15/20/200→引擎不使用(全为0)。源码: sub_4081F8 *(_WORD*)(a2+208)传送; sub_4084E0 a2+208战斗ID组起始; sub_408B30 byte+208=d52行为模式"),
    ("interact_dist",15,"交互距离","玩家可交互的最大曼哈顿距离(像素)。0=无距离限制。源码: sub_40818C dist=|px-ex|+|py-ey|, d15==0则return 1(总是可交互), dist>d15则return 0(太远), 被sub_408E5C(点击)和sub_4099B0(接近)调用"),]
RUNTIME_FIELDS = [
    ("tick_counter",5,"帧累加器","运行时帧累加器。每帧+1, 达到d[4](执行间隔)时归零并触发实体逻辑。源码: sub_409618 if(++d5>=d4){d5=0; 执行}。纯运行时字段, 地图文件中几乎全为0"),
    ("timer",12,"计时器","d[12](byte+48), 非[等待计时]字段。注: 等待计时是d[3](byte+12)=param, 由SetWait设置; 本字段(d[12])为另一运行时字段"),
    ("frame_idx",14,"当前帧","当前渲染帧索引(JVG全局帧号)。sub_405CBC初始化: d14=d17+d65; sub_4077E4朝向变更: d14=d17+d52+d16*dir_mult; sub_408704动画tick: d14++并循环。sub_406864读取d14传给渲染函数决定显示哪帧"),
    ("frame_count",16,"总帧数","JVG块内总帧数。源码: sub_405CBC v2[16]=sub_4540E8(JVG,block), sub_4077E4 d16用于方向帧计算"),
    ("frame_cur",17,"帧计数","动画当前帧/基础帧。源码: sub_4077E4 a1[17], sub_405CBC type200行走动画"),
    ("priority",22,"优先级/α","普通实体: 渲染优先级。玩家实体: 被脚本复用为剧情进度寄存器, 与 d50(通过条件) 配合实现门禁系统。sub_4081F8/408408/4084E0 均读取 player_d22 与实体 d50 比对。源码: sub_406864 byte+88=d22 渲染; sub_4081F8:15 门禁比对"),
    ("sprite_off_x",26,"精灵偏移X","精灵 X 屏幕偏移, 叠加到坐标。源码: sub_406864 byte+104=d26, screen_x+=sprite_off_x"),
    ("sprite_off_y",27,"精灵偏移Y","精灵 Y 屏幕偏移, 叠加到坐标。源码: sub_406864 byte+108=d27, screen_y+=sprite_off_y"),
    ("rt_ref_id",36,"运行时引用A","运行时实体身份指针。hi16=自身索引, lo16=0。格式: entity_index<<16。纯运行时字段, 地图文件中非零值为运行时残留。源码: 运行时转储反编译中无任何实体逻辑函数引用byte+144(d36), 属未文档化的运行时内部状态"),
    ("rt_ref_id2",37,"运行时引用B","运行时实体身份指针。hi16=自身索引, lo16=256(0x100标志)。格式: (entity_index<<16)|0x100。纯运行时字段。源码: 运行时转储反编译中无任何实体逻辑函数引用byte+148(d37), 属未文档化的运行时内部状态"),
    ("script_PC",42,"执行位置","[PC] 脚本字节码当前执行位置。0=链起点 -1=空闲(无脚本执行)。WaitWalk等阻塞操作将当前偏移写回此处实现断点恢复。源码: sub_40EBD4 byte+168=d42 作为 VM 入口 PC, sub_4081F8/408408/408E5C/409618 均在调用前 reset=0"),
    ("saved_PC",43,"调用返回","[SP] 跨链调用前的执行位置保存(调用栈)。sub_4081F8/408408/408E5C 触发 B 链前: d43=d42; End(0) 恢复: d42=d43 然后 d43=-1。新实体初始=-1。源码: sub_4081F8:25 *(a2+172)=*(a2+168)"),
    ("target_dir",56,"目标朝向","type=5:目标朝向(1-8) type=16:战斗组2-概率 type=110:组1Ymin type=200:寻路X(运行时)。源码: sub_408E5C byte+224=d56, sub_4081F8 byte+224(传送朝向), sub_4084E0 a2+224(概率2), sub_408B30"),
    ("saved_y",57,"保存Y","type=5:相机Y偏移 type=16:战斗组3-概率 type=110:组2Xmin type=200:寻路Y(运行时)。源码: sub_408E5C byte+228=d57, sub_4081F8(相机), sub_4084E0 a2+228(概率3), sub_408B30"),
    ("alt_tele_x",60,"备选传送X","type=10:相机偏移X type=16:冷却基准 type=110:组2Ymax type=200:备选传送X。源码: sub_408E5C byte+240=d60, sub_4081F8:31,sub_4084E0 a2+240,sub_408B30"),
    ("alt_tele_y",61,"备选传送Y","type=10:相机偏移Y type=16:冷却计时 type=110:组3Xmin type=200:备选传送Y。源码: sub_408E5C byte+244=d61, sub_4081F8:31,sub_4084E0 a2+244,sub_408B30"),
    ("sub_handle",65,"子句柄","type=16:未使用 type=20:动画句柄(运行时) type=110:组3Xmax? type=200:动画基址(运行时)。源码: sub_405CBC v2[65]=sub_45410C(Ani,v2[64]),sub_408B30 (type=16无引用)"),
    ("cur_frame",67,"当前帧","type=20:动画帧起点(循环重置目标)。源码: sub_408704 d17=d67"),
    ("max_frame",68,"最大帧","动画帧终点-1。type=20/200共用(type=20: 91%有值1~139)。源码: sub_408704 if(++d17>d68)到达终点; sub_405CBC if(v2[16]<=v2[68])v2[68]=v2[16]-1"),
    ("moving",70,"移动中","type=200移动模式:0=静止 1=行走。type=20不使用(sub_409618仅对type200检查d70)。源码: sub_409618 byte+280=d70, type200时检查d70==1触发行走动画"),]
ITEM_FIELDS = [
    ("item_g1_id",   53, "组1-物品ID",   "type110: 物品ID随机范围最小值; Xmin==Xmax→固定掉落。源码: sub_408B30 byte+212=d53, sub_452AC0随机范围"),
    ("item_g1_idmax",54, "组1-物品上限",  "type110: 物品ID随机范围最大值。源码: sub_408B30 byte+216=d54, 若d53>=d54则固定值"),
    ("item_g1_qty",  55, "组1-数量",     "type110: 数量随机范围最小值; Ymin==Ymax→固定数量。源码: sub_408B30 byte+220=d55, sub_452AC0随机范围"),
    ("item_g1_qtymax",56,"组1-数量上限",  "type110: 数量随机范围最大值。源码: sub_408B30 byte+224=d56, 若d55>=d56则固定值"),
    ("item_g2_id",   57, "组2-物品ID",   "type110: 第二组物品ID (此游戏未使用)。源码: sub_408B30 byte+228=d57"),
    ("item_g2_idmax",58, "组2-物品上限",  "type110: 第二组物品ID上限。源码: sub_408B30 byte+232=d58"),
    ("item_g2_qty",  59, "组2-数量",     "type110: 第二组数量。源码: sub_408B30 byte+236=d59"),
    ("item_g2_qtymax",60,"组2-数量上限",  "type110: 第二组数量上限。源码: sub_408B30 byte+240=d60"),
    ("item_g3_id",   61, "组3-物品ID",   "type110: 第三组物品ID (此游戏未使用)。源码: sub_408B30 byte+244=d61"),
    ("item_g3_idmax",62, "组3-物品上限",  "type110: 第三组物品ID上限。源码: sub_408B30 byte+248=d62"),
    ("item_g3_qty",  63, "组3-数量",     "type110: 第三组数量。源码: sub_408B30 byte+252=d63"),
    ("item_g3_qtymax",64,"组3-数量上限",  "type110: 第三组数量上限。源码: sub_408B30 byte+256=d64"),
]
ALL_EDIT_FIELDS = BASIC_FIELDS+FLAG_FIELDS+POS_FIELDS+ANIM_FIELDS+SCRIPT_FIELDS+INTERACT_FIELDS+ITEM_FIELDS

# 类型相关字段映射: type → {dword: (label, comment)}
# 仅列出与 type=200(NPC) 默认语义不同的字段
_TYPE_LABELS = {
    5: {  # 脚本对象 — 无专用tick, 仅执行脚本 (sub_409618 显式跳过)
        # type=5 无类型特定处理, d50~d62 由脚本自由使用 (通过 SetVar/GetItem 等命令读写)
    },
    10: {  # 出入传送点 sub_4081F8 + 地形块连线 sub_405CBC
        50:("通过条件","0=无限制, >0时须与玩家 d22 相等才可传送。源码: sub_4081F8:15 if(d50>0&&player_d22≠d50)阻断"),
        51:("面向要求","bit0=上 bit1=右上 bit2=右 bit3=右下 bit4=下 bit5=左下 bit6=左 bit7=左上。0=不限;>0=须面朝置位方向。源码: d51&(1<<(player_d13-1))"),
        52:("目标地图ID","ChangeScene的目标场景ID。源码: sub_4081F8 *(_WORD*)(a2+208)作为ChangeScene第1参数"),
        53:("目标X","传送后X坐标。源码: sub_4081F8 *(_WORD*)(a2+212)作为ChangeScene第2参数"),
        54:("目标Y","传送后Y坐标。源码: sub_4081F8 *(_WORD*)(a2+216)作为ChangeScene第3参数"),
        56:("目标朝向","传送后玩家朝向1-8。源码: sub_4081F8 *(_WORD*)(a2+224)作为ChangeScene第4参数"),
        57:("相机X","相机目标X。源码: sub_408E5C byte+228=d57相机位置"), 58:("相机Y",""),
        59:("相机Z",""), 60:("相机偏移X","。源码: sub_408E5C byte+240=d60"),
        61:("相机偏移Y","。源码: sub_408E5C byte+244=d61"),
        62:("路径封锁","SetBlock写入。>0=封锁(路径网格清零) 0=开放(写入路径标记)。sub_4081F8:+248 d62非零跳过传送; sub_40DC1C SetBlock写入; sub_405CBC封锁时清除网格"),
        63:("路径1·编号","非零=启用路径1; 低字节=路径编号(BYTE标记值)。sub_4526D0(v2[64]..v2[67], *(BYTE*)(a2+252), grid)"), 64:("路径1·X1","路径1起点X。sub_4526D0参数a1"), 65:("路径1·Y1","路径1起点Y。sub_4526D0参数a2"),
        66:("路径1·X2","路径1终点X。sub_4526D0参数a3"), 67:("路径1·Y2","路径1终点Y。sub_4526D0参数a4"),
        68:("路径2·编号","非零=启用; 低字节=编号。sub_4526D0(v2[69]..v2[72], *(BYTE*)(a2+272), grid)"),
        69:("路径2·X1",""), 70:("路径2·Y1",""), 71:("路径2·X2",""), 72:("路径2·Y2",""),
        73:("路径3·编号",""), 74:("路径3·X1",""), 75:("路径3·Y1",""), 76:("路径3·X2",""), 77:("路径3·Y2",""),
        78:("路径4·编号",""), 79:("路径4·X1",""), 80:("路径4·Y1",""), 81:("路径4·X2",""), 82:("路径4·Y2",""),
        83:("路径5·编号",""), 84:("路径5·X1",""), 85:("路径5·Y1",""), 86:("路径5·X2",""), 87:("路径5·Y2",""),
    },
    15: {  # 事件触发区 — 玩家接近碰撞盒时自动触发脚本 (sub_408408)
        34:("脚本开关","d34(cur_B)非零时触发才生效。源码: sub_408408 a2[34]==0则return 0"),
        50:("通过条件","0=无限制, >0时须与玩家 d22 相等才触发。源码: sub_408408:13 if(d50>0&&player_d22≠d50)阻断"),
        51:("面向要求","bit0=上 bit1=右上 bit2=右 bit3=右下 bit4=下 bit5=左下 bit6=左 bit7=左上。0=不限;>0=须面朝置位方向。源码: d51&(1<<(player_d13-1))"),
    },
    16: {  # 随机战斗区 — 玩家进入碰撞盒概率触发战斗 (sub_4084E0)
        # ★ 数据布局: 3个战斗ID (d52-d54) 连续, 后跟 3个概率 (d55-d57) 连续 — 非交错!
        # 源码 sub_4084E0: v4=a2+208; while轮中 *v4 读ID, v4[3]=*(v4+12字节) 读概率, ++v4 指针前进4字节
        50:("通过条件","0=无限制, >0时须与玩家 d22 相等才触发战斗。源码: sub_4084E0:25 if(d50<=0||d50==player_d22)放行"),
        51:("面向要求","bit0=上 bit1=右上 bit2=右 bit3=右下 bit4=下 bit5=左下 bit6=左 bit7=左上。0=不限;>0=须面朝置位方向。源码: d51&(1<<(player_d13-1))"),
        52:("战斗组1-ID","第1组战斗ID。源码: sub_4084E0 v4[0]=*(a2+208)"),
        53:("战斗组2-ID","第2组战斗ID。源码: sub_4084E0 ++v4后v4[0]=*(a2+212)"),
        54:("战斗组3-ID","第3组战斗ID。源码: sub_4084E0 二次++v4后v4[0]=*(a2+216)"),
        55:("战斗组1-概率","第1组遇敌概率阈值(0-100)。源码: sub_4084E0 v4[3]=*(a2+220)"),
        56:("战斗组2-概率","第2组遇敌概率阈值(0-100)。源码: sub_4084E0 ++v4后v4[3]=*(a2+224)"),
        57:("战斗组3-概率","第3组遇敌概率阈值(0-100)。源码: sub_4084E0 二次++v4后v4[3]=*(a2+228)"),
        58:("(保留/未使用)","type=16 战斗引擎不访问 d58-d59 (sub_4084E0 无引用)"),
        59:("(保留/未使用)","type=16 战斗引擎不访问"),
        60:("冷却基准","遇敌后冷却计时基准值。源码: sub_4084E0 d[61]=d[60]; 难度调整: d[61]+=d[60]/2(bit1) 或 d[61]+=3*d[60]/10(bit0)"),
        61:("冷却计时","当前冷却剩余帧数(运行时递减)。源码: sub_4084E0 if(d[61]<=0)遇敌检查; else if(player忙碌) d[61]--"),
        62:("等级同步","敌人等级是否追随队伍。0=固定等级(使用战斗数据预设值); 1=自动调级(敌人等级=队伍均值±2~5)。数据: 89%实体的d62=1。源码: sub_4084E0→sub_40EB10→sub_436BD4→sub_4307CC(a1), if(a1)word_9D6C86=队伍均级 else=0; sub_430578用此值缩放敌人等级"),
        63:("(保留/未使用)","type=16 战斗引擎不访问 d63-d70 (sub_4084E0 无引用)"),
        64:("(保留/未使用)","type=16 战斗引擎不访问"),
        65:("(保留/未使用)","type=16 战斗引擎不访问 (勿受'目标地图'旧标注误导)"),
        66:("(保留/未使用)","type=16 战斗引擎不访问"),
        67:("(保留/未使用)","type=16 战斗引擎不访问"),
        68:("(保留/未使用)","type=16 战斗引擎不访问"),
        69:("(保留/未使用)","type=16 战斗引擎不访问"),
        70:("(保留/未使用)","type=16 战斗引擎不访问 (移动模式仅type=20/200使用, sub_409618)"),
    },
    20: {  # 事件对象 — 动画精灵 (sub_408704 + sub_406864), 非角色! anim_set全为4(Ani.JVG)
        # ★ 音效事件对布局: 偶数dword=音效ID(传给PlaySound的第3参数), 奇数dword=触发帧号(d17==此帧时播放)
        # 汇编铁证 sub_408704: test [eax+0x140]; cmp [ecx+0x44],[edx+0x144]; mov edx,[edx+0x140]; call PlaySound
        50:("(未使用)","type=20 不使用门禁/传送/战斗参数 (sub_408704 无引用)"),
        51:("(未使用)",""),
        52:("(未使用)",""),
        53:("(未使用)",""),
        54:("(未使用)",""),
        55:("阴影帧","0=无 1=小阴影(39×23) 2=大阴影(65×33)。源码: sub_406864 if((type20||type200)&&d55>0)绘制阴影帧"),
        56:("(未使用)",""),
        57:("(未使用)",""),
        58:("(未使用)",""),
        59:("(未使用)",""),
        60:("(未使用)",""),
        61:("(未使用)",""),
        62:("(未使用)",""),
        63:("(未使用)",""),
        64:("子模型(Ani.JVG块)","Ani.JVG动画块索引。100%实体有值(1~592)。源码: sub_405CBC v2[64]→sub_45410C(Ani,block)"),
        65:("动画句柄(运行时)","sub_45410C返回值, 精灵绘制句柄。文件值=初始化后残留。源码: sub_405CBC v2[65]"),
        66:("循环等待","动画循环后随机等待帧数。<0=-1不循环 0=立即循环 >0=random(N)等待。源码: sub_408704 if(d66>0)random(d66); if(d66<0)不重置"),
        67:("帧起点","动画循环时重置到此帧。源码: sub_408704 d17=d67"),
        68:("最大帧","动画终点=此值-1。91%实体有值。源码: sub_408704 if(++d17>d68)到达终点"),
        69:("保留末帧","非零时动画播完停在最后一帧不循环。源码: sub_408704 if(d69)d68--,d14--"),
        70:("(未使用)","移动模式仅type=200使用。type=20 不走路 (sub_409618 只对type200检查d70)"),
        # 音效事件对 #9-11 (极少使用, <1%)
        71:("音效9·ID","第9音效事件: 音效ID (传PlaySound)。源码: sub_408704 a2+0x11C"),
        72:("音效9·触发帧","第9音效事件: d17==此值时播放。源码: sub_408704 a2+0x120"),
        73:("音效10·ID",""), 74:("音效10·触发帧",""),
        75:("音效11·ID",""), 76:("音效11·触发帧",""),
        # d77-d79: 间隙, sub_408704 不访问
        77:("(间隙·未使用)","offset 0x134-0x13C, sub_408704 不检查"),
        78:("(间隙·未使用)",""),
        79:("(间隙·未使用)",""),
        # 音效事件对 #1-8 (d80/d81最常用, 49%实体使用)
        80:("音效1·ID","第1音效事件: 音效ID。最常用(49%实体)。典型值:22/21/29/39/53。源码: sub_408704 a2+0x140→edx→PlaySound(arg3)"),
        81:("音效1·触发帧","第1音效事件: d17==此帧时播放音效。0=动画起始帧。典型值:0/5。源码: sub_408704 a2+0x144"),
        82:("音效2·ID",""), 83:("音效2·触发帧",""),
        84:("音效3·ID",""), 85:("音效3·触发帧",""),
        86:("音效4·ID",""), 87:("音效4·触发帧",""),
        88:("音效5·ID",""), 89:("音效5·触发帧",""),
        90:("音效6·ID",""), 91:("音效6·触发帧",""),
        92:("音效7·ID",""), 93:("音效7·触发帧",""),
        94:("音效8·ID",""), 95:("音效8·触发帧",""),
    },
    110: {  # 特殊机关 sub_408B30
        50:("帧计数器","d52=0时>0启用拾取后动画(帧递增); 此游戏全为0。源码: sub_408B30:74 if(d50){++d68; d14=d68+d51}"),
        51:("动画帧基偏移","d52=0时: frame_idx=frame_cur+d51。源码: sub_408B30 byte+204=d51, v2[51]=sub_45410C(JVG,v2[50],0), d14=d17+d51"),
        52:("行为模式","0=标记bit8+可选动画 1=清除实体(禁用+隐藏) 2+=无行为; 此游戏全为1。源码: sub_408B30 byte+208=d52, V3==0:设bit8, V3==1:清bit0+清bit1"),
        53:("组1-物品ID","随机范围最小值; Xmin==Xmax=固定掉落。源码: sub_408B30 byte+212=d53"),
        54:("组1-物品ID上限","随机范围最大值。源码: sub_408B30 byte+216=d54"),
        55:("组1-数量","随机范围最小值; Ymin==Ymax=固定数量。源码: sub_408B30 byte+220=d55"),
        56:("组1-数量上限","随机范围最大值。源码: sub_408B30 byte+224=d56"),
        57:("组2-物品ID","(此游戏未使用)。源码: sub_408B30 byte+228=d57"),
        58:("组2-物品ID上限","。源码: sub_408B30 byte+232=d58"),
        59:("组2-数量","。源码: sub_408B30 byte+236=d59"),
        60:("组2-数量上限","。源码: sub_408B30 byte+240=d60"),
        61:("组3-物品ID","(此游戏未使用)。源码: sub_408B30 byte+244=d61"),
        62:("组3-物品ID上限","。源码: sub_408B30 byte+248=d62"),
        63:("组3-数量","。源码: sub_408B30 byte+252=d63"),
        64:("组3-数量上限","。源码: sub_408B30 byte+256=d64"),
    },
    200: {  # NPC角色 sub_405CBC(init) + sub_4077E4(dir) + sub_406864(render) + sub_408E5C(click) + sub_408704(walk)
        # ★ 初始化 sub_405CBC: d51→立绘(d52=句柄), d53→方向模式(d16=帧/d53), d64→行走动画(d65=句柄), d70→站桩(0)/行走(1)分支
        # ★ 交互 sub_408E5C: B链触发(d34>0), 寻路状态 d56-d58→d60-d62 备份/恢复, 交互距离 sub_40818C
        # ★ 行走 sub_408704: d70==1时触发, d66循环等待, d67帧起点, d68终点; d71-d95音效事件(同type=20, 偶数=音效ID/奇数=触发帧, 此游戏NPC几乎不用)
        50:("通过条件","⚠️ 待验证: 100%实体有值(96.4%=8, 范围2-13)。C代码未找到type=200访问d50的证据(sub_408E5C仅检查d34), 疑为脚本层剧情门控值。数据推翻旧标注'NPC未使用'"),
        51:("立绘ID","Cha.JVG块索引。96%有值(1~177)。源码: sub_405CBC v2[51]→sub_45410C(Cha.JVG, v2[51])"),
        52:("立绘句柄","立绘精灵句柄(运行时)。源码: sub_405CBC v2[52]=sub_45410C(Cha, v2[51]); sub_4077E4: d14=d17+d52+..."),
        53:("方向模式","4=四向(962个=98%), 8=八向(3个), 0=静态(3个)。源码: sub_4077E4 a1[53]==4四向分支/a1[53]==8八向分支; sub_405CBC: d16/=d53"),
        54:("(未使用)","数据: 全为零(<1%异常值)"),
        55:("阴影帧","0=无 1=小阴影(746个) 2=大阴影(151个)。源码: sub_406864 if((type20||type200)&&d55>0)绘制"),
        56:("寻路X","运行时。交互时 sub_408E5C: d60=d56 备份; 交互结束后 d56=d60 恢复。文件值=残留"),
        57:("寻路Y","运行时。sub_408E5C: d61=d57 备份; 交互结束后 d57=d61 恢复"),
        58:("寻路参数","运行时。sub_408E5C: d62=d58 备份。数据: 全为零"),
        59:("(未使用)",""),
        60:("寻路X·备份","运行时。sub_408E5C: d60=d56 (交互前保存原位置)。文件值=残留"),
        61:("寻路Y·备份","运行时。sub_408E5C: d61=d57"),
        62:("寻路参数·备份","运行时。sub_408E5C: d62=d58"),
        63:("(未使用)",""),
        64:("子模型","Ani.JVG行走动画块索引。35%使用(行走NPC)。源码: sub_405CBC v2[64]→sub_45410C(Ani, v2[64])"),
        65:("行走句柄","行走动画精灵句柄(运行时)。源码: sub_405CBC v2[65]=sub_45410C(Ani, v2[64])"),
        66:("循环等待","行走动画循环后等待帧数。18%使用。源码: sub_408704 if(d66>0)random(d66); if(d66<0)不循环"),
        67:("帧起点","行走动画循环重置帧。源码: sub_408704: d17=d67; sub_405CBC: if(d67>d68)d67=0"),
        68:("最大帧","行走动画终点-1。37%使用。源码: sub_408704 if(++d17>d68)循环; sub_405CBC: if(d16<=d68)d68=d16-1"),
        69:("保留末帧","非零时行走动画停最后帧。源码: sub_408704 if(d69)d68--,d14--"),
        70:("移动模式","0=站桩(Cha.JVG方向帧, 70%=690个) 1=行走(Ani.JVG动画, 30%=297个)。源码: sub_405CBC d70==0→站桩方向帧/d70==1→行走动画; sub_409618 d70==1→sub_408704"),
        # 音效事件对 — sub_408704 同type=20机制(偶数=音效ID, 奇数=触发帧), 此游戏NPC几乎不用
        71:("音效·事件1","仅在5个NPC使用"), 72:("音效·触发帧1",""),
        73:("音效·事件2",""), 74:("音效·触发帧2",""),
        75:("音效·事件3",""), 76:("音效·触发帧3",""),
        # d77-d79: 间隙 (sub_408704 不检查)
        77:("(间隙)",""), 78:("(间隙)",""), 79:("(间隙)",""),
        80:("音效·事件4",""), 81:("音效·触发帧4",""),
        82:("音效·事件5",""), 83:("音效·触发帧5",""),
        84:("音效·事件6",""), 85:("音效·触发帧6",""),
        86:("音效·事件7",""), 87:("音效·触发帧7",""),
        88:("音效·事件8",""), 89:("音效·触发帧8",""),
        90:("音效·事件9",""), 91:("音效·触发帧9",""),
        92:("音效·事件10",""), 93:("音效·触发帧10",""),
        94:("音效·事件11",""), 95:("音效·触发帧11",""),
    },
}
MAX_MAP_W, MAX_MAP_H = 1024, 768



# TKD.dat 脚本 I/O (来自 script_editor.py)
# ============================================================

_TKT_XOR_TABLE = bytes([i ^ 0xFF for i in range(256)])  # XOR 密钥表, load_tkd/save_tkd 用

def load_tkd(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    decoded = data.translate(_TKT_XOR_TABLE)
    try:
        text = decoded.decode('big5', errors='replace')
    except Exception:
        text = decoded.decode('gbk', errors='replace')
    return text

def save_tkd(filepath, text):
    try:
        encoded = text.encode('big5')
    except (UnicodeEncodeError, UnicodeDecodeError):
        encoded = text.encode('gbk', errors='replace')
    encrypted = encoded.translate(_TKT_XOR_TABLE)
    with open(filepath, 'wb') as f:
        f.write(encrypted)

def parse_defines(text):
    lines = text.split('\n')
    defines = []
    current = None
    header_lines = []; pending_prefix = []; seen_first_define = False
    for i, line in enumerate(lines):
        raw_line = line.rstrip('\r')
        stripped = raw_line.strip()
        if stripped.startswith('DEFINE') and not stripped.startswith('//'):
            parts = stripped.split(None, 1)
            define_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            if not seen_first_define: seen_first_define = True
            current = {'define_id': define_id, 'comment': '',
                       'prefix_lines': list(pending_prefix), 'body_lines': [],
                       'line_start': i, 'line_end': -1, 'header_line': raw_line}
            pending_prefix = []
        elif stripped.startswith('};') and current is not None:
            current['line_end'] = i
            current['comment'] = stripped[2:].replace(' end', '').strip()
            current['body_lines'].append(raw_line)
            defines.append(current); current = None
        elif current is not None:
            current['body_lines'].append(raw_line)
        else:
            if not seen_first_define and stripped and not stripped.startswith('//'):
                header_lines.append(raw_line)
            elif not seen_first_define and stripped.startswith('////'):
                header_lines.append(raw_line)
            else:
                pending_prefix.append(raw_line)
    return defines, '\n'.join(header_lines)

def rebuild_text(defines, header):
    parts = []
    if header:
        for hl in header.split('\n'): parts.append(hl)
    for d in defines:
        for pl in d.get('prefix_lines', []): parts.append(pl)
        parts.append(d['header_line'])
        for bl in d['body_lines']: parts.append(bl)
    parts.append(''); parts.append('')
    return '\r\n'.join(parts)

# 脚本命令完整列表 — 基于 DEFCMD.LST 权威操作码表 + TKD_decoded.txt 实际用法
# DEFCMD.LST 操作码映射 (格式: 操作码=命令名(参数数)):
#   [Normal]
#   0=End(1), 1=TalkB(4), 2=SetTalkB(4), 3=DoTalkB(0), 4=SetNowDef(3),
#   5=SysTalk(6), 6=SetHint(3), 7=MenuTalk(2), 8=SetScene(2), 9=SetWalk(3),
#   10=WaitWalk(2), 11=StopWalk(2), 12=SetEnabled(2), 13=SetVisible(2),
#   14=SetWait(3), 15=Nop(0), 16=SetCursor(3), 17=FadeOut(4), 18=FadeIn(4),
#   19=ChangeScene(4), 20=SetAni(7), 21=SetTick(2), 22=SetShadow(2),
#   23=SetPos(4), 24=Disable(1), 25=Enable(1), 26=Redraw(1), 27=SetPlayer(1),
#   28=SetCamera(1), 29=SetView(2), 30=SlideTo(3), 31=PlayerAct(1),
#   32=SetFlag(2), 33=AddFlag(2), 34=TalkA(5), 35=Switch(2), 36=SetVar(2),
#   37=Random(3), 38=SetFlagVar(2), 39=AddFlagVar(2), 40=GetItem(2),
#   41=BlackTalk(4), 42=SetChaPic(2), 43=SetWeather(2), 44=ShowMenu(2),
#   45=TeamMember(2), 46=Note(2), 47=SetBlock(2), 48=Attribute(3),
#   49=SetSwitch(2), 50=BuyMenu(3), 51=PlaySound(2), 52=StopSound(1),
#   53=PlayMusic(2), 54=SetMusic(2), 55=TheEnd(1), 56=Fix(1)
#   [Special]
#   60=CheckResult(2), 61=CheckFlag(3), 62=CheckItem(3), 63=CheckTeam(3),
#   64=MiniGame(3), 65=CheckMember(4), 66=War(1)
#   [NoArg]
#   82=Else
SCRIPT_COMMANDS = [
    # [Normal] — 按 DEFCMD.LST 操作码顺序排列
    'End', 'TalkB', 'SetTalkB', 'DoTalkB', 'SetNowDef', 'SysTalk', 'SetHint',
    'MenuTalk', 'SetScene', 'SetWalk', 'WaitWalk', 'StopWalk', 'SetEnabled',
    'SetVisible', 'SetWait', 'Nop', 'SetCursor', 'FadeOut', 'FadeIn',
    'ChangeScene', 'SetAni', 'SetTick', 'SetShadow', 'SetPos', 'Disable',
    'Enable', 'Redraw', 'SetPlayer', 'SetCamera', 'SetView', 'SlideTo',
    'PlayerAct', 'SetFlag', 'AddFlag', 'TalkA', 'Switch', 'SetVar', 'Random',
    'SetFlagVar', 'AddFlagVar', 'GetItem', 'BlackTalk', 'SetChaPic',
    'SetWeather', 'ShowMenu', 'TeamMember', 'Note', 'SetBlock', 'Attribute',
    'SetSwitch', 'BuyMenu', 'PlaySound', 'StopSound', 'PlayMusic', 'SetMusic',
    'TheEnd', 'Fix',
    # [Special]
    'CheckResult', 'CheckFlag', 'CheckItem', 'CheckTeam', 'MiniGame',
    'CheckMember', 'War',
    # [NoArg]
    'Else',
    # TKD 文本层额外命令 (非 DEFCMD.LST 标准但实际出现)
    'Yield', 'Jump', 'ShowText', 'MenuChoice', 'SetPosFade', 'SceneFade',
    'SceneBGM', 'Camera', 'WaitInput', 'SetGlobal', 'SetWord', 'WaitTimer',
    'Music',
]

# 脚本命令描述模板 — 用于预览窗口的人类可读描述
# 键为命令名, 值为 lambda, 接收 (args, tkt) 返回描述字符串
# tkt 为 TKT 全文查找表 (id→text)
def _tkt_text(tkt, id_str, max_len=60):
    """从 TKT 获取文本, id_str 为字符串形式的 ID, 返回截断文本或空串"""
    try:
        tid = int(id_str)
        txt = tkt.get(tid, '')
        return txt[:max_len] + ('...' if len(txt) > max_len else '') if txt else ''
    except (ValueError, TypeError):
        return ''

def _tkt_scene(tkt, scene_id_str, max_len=20):
    """从 TKT 获取场景名称, scene_id_str 为字符串形式的场景ID
    场景名称存储在 TKT_ID = scene_id + 300"""
    try:
        sid = int(scene_id_str)
        tkt_id = sid + 300  # SCENE_NAME_TKT_BASE = 300
        txt = tkt.get(tkt_id, '')
        if txt:
            # 只取第一行作为场景名
            name = txt.split('\n')[0].strip()
            return name[:max_len] + ('...' if len(name) > max_len else '') if name else ''
        return ''
    except (ValueError, TypeError):
        return ''

def _item_name(item_names, id_str):
    """从 item_names 获取物品名称, id_str 为字符串形式的物品ID"""
    try:
        if not item_names: return ''
        tid = int(id_str)
        return item_names.get(tid, '')
    except (ValueError, TypeError):
        return ''

def _sign_qty(qty_str):
    """格式化数量: 正数加+号, 负数保持-号"""
    try:
        v = int(qty_str)
        return f"+{v}" if v >= 0 else str(v)
    except ValueError:
        return qty_str

# CheckTeam 角色名缓存 (由 MatEditor._reload 从 WarPC.dat + TKT.dat 动态填充)
_char_name_cache = {}

def _load_char_names(tks_dir, tkt_lookup):
    """从 WarPC.dat 加载角色名映射 index→name.
    类似 warpc_editor 的做法: 读 WarPC 每条记录的 [0] name_id, 查 TKT 得到名称."""
    global _char_name_cache
    wp = os.path.join(tks_dir, 'WarPC.dat')
    if not os.path.exists(wp):
        return
    try:
        with open(wp, 'rb') as f:
            raw = f.read()
        dec = lzss_decompress(raw)
        REC = 1054  # 527 int16
        cnt = min(50, len(dec) // REC)
        for i in range(cnt):
            off = i * REC
            name_id = struct.unpack_from('<h', dec, off)[0]
            if name_id > 0 and name_id in tkt_lookup:
                name = tkt_lookup[name_id].split('\n')[0].strip()
                if name:
                    _char_name_cache[i] = name
        # 主角 (index 0): TKT#9000 是控制字符占位, 用 "主角"
        if 0 not in _char_name_cache:
            _char_name_cache[0] = "主角"
    except Exception:
        pass

def _dir_name(dir_str, entity=""):
    """朝向值->方向名。entity=0主角(八向), 其他NPC(四向)"""
    _D8 = {1:"上",2:"右上",3:"右",4:"右下",5:"下",6:"左下",7:"左",8:"左上"}
    _D4 = {1:"右上",2:"右上",3:"右下",4:"右下",5:"左下",6:"左下",7:"左上",8:"左上"}
    try:
        v = int(dir_str)
        return _D8.get(v, dir_str) if entity == "0" else _D4.get(v, dir_str)
    except:
        return dir_str

def _cm(char_id):
    """角色ID→名称, fallback 到 '角色#N'"""
    try: cid=int(char_id); return _char_name_cache.get(cid, f"角色#{cid}")
    except: return f"角色#{char_id}"

# CheckTeam arg1 语义映射 (基于 TKD脚本注释 + save_editor SEG2字段)
# ┌──────┬──────────┬─────────────────────┬──────────────────────────────┐
# │ arg1 │ 属性     │ SEG2地址            │ 证据                         │
# ├──────┼──────────┼─────────────────────┼──────────────────────────────┤
# │  1   │ 角色存在 │ word_75688C[6]      │ TKD: CheckTeam(1,N,0)角色操作│
# │  2   │ 智慧     │ byte_756886         │ TKD注释: "智慧>150"          │
# │  3   │ 仁德     │ byte_756887         │ TKD注释: "仁德>150"          │
# │  4   │ 勇气     │ word_756888         │ TKD注释: "勇氣>150"          │
# │  5   │ 队伍人数 │ word_75688C[6]      │ TKD: -2=有空位 1=已满        │
# │  6   │ 医术     │ word_75688A         │ TKD注释+上限100              │
#     │ 10   │ 事件完成度│ —                   │ 游戏内事件完成百分比       │
# │ 11   │ 特殊物品 │ — (sub_40E11C)      │ TKD注释:"26個特殊物品"       │
# └──────┴──────────┴─────────────────────┴──────────────────────────────┘
_CAT_NAMES = {1:"角色", 2:"智慧", 3:"仁德", 4:"勇气", 5:"队伍人数", 6:"医术", 10:"事件完成度", 11:"特殊物品"}
# CheckTeam arg3 比较运算符 (基于TKD脚本注释语义 + 队伍人数检查模式推断)
_CMP_OPS = {'0':"==", '1':"≥", '-1':"<", '-2':"≤", '2':">"}

def _checkteam_desc(args):
    """根据逆向 + TKD.dat 脚本注释生成 CheckTeam 的人类可读描述。
    ┌──────┬──────────┬──────────────────────────────────────┐
    │ arg1 │ 语义     │ 逆向依据                             │
    ├──────┼──────────┼──────────────────────────────────────┤
    │  1   │ 角色存在 │ TKD: CheckTeam(1,N,0) 后跟角色操作    │
    │  2   │ 智慧     │ TKD注释+save_editor SEG2 byte_756886 │
    │  3   │ 仁德     │ TKD注释+save_editor SEG2 byte_756887 │
    │  4   │ 勇气     │ TKD注释+save_editor SEG2 word_756888 │
    │  5   │ 队伍人数 │ TKD:-2=有空位/1=已满 word_75688C[6]  │
    │  6   │ 医术     │ TKD注释+save_editor SEG2 word_75688A │
    │ 10   │ 随机概率 │ TKD注释:"事件概率N%触发"             │
    │ 11   │ 特殊物品 │ TKD注释+save_editor sub_40E11C case11│
    └──────┴──────────┴──────────────────────────────────────┘
    arg3: 0=存在/==  1=≥  -1=<  -2=≤  2=>"""
    if not args:
        return "检查队伍"
    cat = args[0] if len(args) >= 1 else '?'
    val = args[1] if len(args) >= 2 else '?'
    op  = args[2] if len(args) >= 3 else '0'

    cat_name = _CAT_NAMES.get(int(cat) if cat.lstrip('-').isdigit() else 0, f"队伍属性{cat}")
    op_str = _CMP_OPS.get(op, op)

    if cat == '1':
        # 角色是否在队伍中: CheckTeam(1, char_id, 0)
        try:
            cid = int(val)
            cname = _char_name_cache.get(cid, f"角色#{cid}")
            return f"判断角色 {cname} 在队中" if op == '0' else f"判断角色 {cname} {op_str} {val}"
        except ValueError:
            return f"判断角色 {op_str} {val}"
    elif cat == '5':
        # 队伍人数检查: CheckTeam(5, max_slots, op)
        try:
            mx = int(val)
            if op == '-2' and mx >= 5:
                return "判断队伍有空位"
            elif op == '1' and mx >= 5:
                return "判断队伍已满"
            elif op == '0':
                return f"判断队伍人数 {op_str} {mx}"
        except ValueError:
            pass
        return f"判断队伍人数 {op_str} {val}"
    elif cat == '10':
        # 事件完成度: CheckTeam(10, percent, op)
        return f"判断事件完成度 {op_str} {val}%"
    else:
        # 属性检查: CheckTeam(attr, threshold, op)
        return f"判断{cat_name} {op_str} {val}"

# Attribute arg2 语义映射 (来源: TKD_decoded.txt 664处用法 + 脚本注释)
# arg2: 1=智慧 2=仁德 3=勇气 5=体力值恢复 6=内力值恢复 10=事件完成度 11=特殊物品
_ATTR_NAMES = {1:"智慧", 2:"仁德", 3:"勇气", 5:"体力值恢复", 6:"内力值恢复", 10:"事件完成度", 11:"特殊物品"}

# SetCursor 光标动画名称
# SetCursor arg1→Cur.JVG块 (sub_411BA4→sub_45408C), arg2→帧延迟(dword_8242CC, sub_411D18)
# ┌──────────┬───────┬──────────┬──────────────────────────────┐
# │ cursor_id│ block │ 帧数/尺寸│ 语义                         │
# ├──────────┼───────┼──────────┼──────────────────────────────┤
# │    0     │  blk0 │ 1帧29x40│ 禁止点击                     │
# │    1     │  blk1 │ 1帧28x40│ 正常(脚本默认)               │
# │    2     │  blk2 │ 3帧29x26│ 对话气泡                     │
# │    3     │  blk3 │ 3帧29x43│ 开门(传送)                   │
# │    4     │  blk4 │ 4帧33x47│ 拾取                         │
# │  5-8     │blk5-8 │ 1帧28x40│ 同正常(战斗/备用)            │
# │    9     │  blk9 │ 1帧24x37│ 调查                         │
# │   10     │ blk10 │38帧30x42│ 苍溟(特殊)                   │
# └──────────┴───────┴──────────┴──────────────────────────────┘
_CURSOR_BLOCKS = {0:"禁止", 1:"常规", 2:"对话", 3:"开门", 4:"拾取", 5:"常规", 6:"常规", 7:"常规", 8:"常规", 9:"调查", 10:"苍溟"}

def _setcursor_desc(args):
    """SetCursor(Cur.JVG块, 帧延迟, 开关): arg1选择光标精灵块, arg2动画帧延迟, arg3显示开关"""
    if not args or len(args) < 3:
        return "设置光标"
    ent = args[0]; spd = args[1]; en = args[2]
    en_str = "隐藏" if en == '0' else "显示" if en == '1' else f"模式{en}"
    block_name = _CURSOR_BLOCKS.get(int(ent) if ent.lstrip('-').isdigit() else -1, f"块{ent}")
    spd_str = f"延迟{spd}t" if spd != '3' else ""  # 3=引擎默认, 不显示
    ent_str = "玩家" if ent == '1' else "当前" if ent == '-1' else f"实体{ent}"
    return f"{ent_str}光标 {en_str} [{block_name}]{' '+spd_str if spd_str else ''}"

def _attribute_desc(args):
    """根据 TKD脚本注释生成 Attribute 的人类可读描述。
    Attribute(实体, 属性, 变化值): arg2=1智慧 2仁德 3勇气 5体力 6内力 10事件 11特殊"""
    if not args or len(args) < 3:
        return "属性变更"
    try:
        attr = int(args[1])
        val = int(args[2])
        name = _ATTR_NAMES.get(attr, f"属性{attr}")
        sign = "+" if val >= 0 else ""
        if attr in (5, 6) and val >= 9999:
            return f"{name}完全恢复"
        return f"属性变更 {name}{sign}{val}"
    except (ValueError, TypeError):
        return f"属性变更 ({','.join(args[:3])})"

SCRIPT_CMD_DESC = {
    # ===== [Normal] 按 DEFCMD.LST 操作码顺序 =====
    # opcode 0: End(1) — 结束脚本, 参数=结束模式
    # 逆向: sub_40EBD4 case 0; 负值→uint16: -1=0xFFFF -2=0xFFFE ...
    # 0xFFFF/1:A链递增 0xFFFE/2:B链递增 0xFFFD/3:C链递增
    # 0xFFFC/4:A链重置 0xFFFB/5:B链重置 0xFFFA/6:C链重置
    'End':          lambda a, t: (
        "结束 (正常返回, 不修改链)" if not a or a[0] == '0' else
        f"结束 → A链递增 (下一DEFINE)" if a[0] in ('1', '-1') else
        f"结束 → B链递增 (下一DEFINE)" if a[0] in ('2', '-2') else
        f"结束 → C链递增 (下一DEFINE)" if a[0] in ('3', '-3') else
        f"结束 → A链重置 (cur_A=0)" if a[0] in ('4', '-4') else
        f"结束 → B链重置 (cur_B=0)" if a[0] in ('5', '-5') else
        f"结束 → C链重置 (cur_C=0)" if a[0] in ('6', '-6') else
        f"结束 (模式={a[0]})"
    ),
    # opcode 1: TalkB(4) — 阻塞式对话: 实体, 文本ID, 参数, 参数
    'TalkB':        lambda a, t: f"对话(等待) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"对话(等待) 实体#{a[0]}" if a else "对话(等待)",
    # opcode 2: SetTalkB(4) — 设置对话不等待: 实体, 文本ID, 参数, 参数
    'SetTalkB':     lambda a, t: f"设置对话(不等待) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"设置对话 实体#{a[0]}" if a else "设置对话",
    # opcode 3: DoTalkB(0) — 执行对话显示
    'DoTalkB':      lambda a, t: "执行对话显示",
    # opcode 4: SetNowDef(3) — 切换DEFINE链位置: 实体(-1=上下文/-2=自身), 链(1=A/2=B/3=C), 新位置
    # sub_40B520: 修改目标实体的 cur_A/B/C, 实现 DEFINE 链跳转 (相当于 goto 到链中指定位置)
    'SetNowDef':    lambda a, t: (
        "切换当前定义 (无参数)" if not a else
        f"切换定义 ID={a[0]}" if len(a) < 3 else
        f"切换DEFINE → {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} "
        f"{'A链' if a[1]=='1' else 'B链' if a[1]=='2' else 'C链' if a[1]=='3' else '链'+a[1]} "
        f"→位置{a[2]}"
    ),
    # opcode 5: SysTalk(6) — 系统对话 (sub_40B1B4)
    # 参数: 实体, 文本ID, 颜色索引, 位置X, 位置Y, 模式(0=阻塞 1=非阻塞)
    'SysTalk':      lambda a, t: (
        f"系统对话 实体#{a[0]} 文本={a[1]} 色{a[2]} ({a[3]},{a[4]}) {'非阻塞' if a[5]=='1' else '阻塞'}"
        if len(a)>=6 else f"系统对话 ({','.join(a)})" if a else "系统对话"
    ),
    # opcode 6: SetHint(3) — 设置提示 (sub_40B650)
    # 参数: 实体(-1=上下文 -2=自身), 提示文本ID, 开关(0=关闭提示 >0=开启提示)
    'SetHint':      lambda a, t: (
        f"设置提示 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} 文本={a[1]} {'开启' if a[2]!='0' else '关闭'}"
        if len(a)>=3 else f"设置提示 ({','.join(a)})" if a else "设置提示"
    ),
    # opcode 7: MenuTalk(2) — 菜单对话 (sub_40B710)
    # 参数: 文本ID, 变量槽(存储选择结果)
    'MenuTalk':     lambda a, t: f"菜单对话 文本={a[0]}→变量[{a[1]}]" if len(a)>=2 else f"菜单对话 ({','.join(a)})" if a else "菜单对话",
    # opcode 8: SetScene(2) — 设置场景状态 (sub_40BB70)
    # 参数: 实体(-1=上下文 -2=自身), 场景ID
    'SetScene':     lambda a, t: (
        f"设置场景 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} →场景{a[1]}"
        if len(a)>=2 else f"设置场景 ({','.join(a)})" if a else "设置场景"
    ),
    # opcode 9: SetWalk(3) — 设置行走 (sub_40BC10)
    # 参数: 实体(-1=上下文 -2=自身), 目标X, 目标Y (仅type=200有效)
    'SetWalk':      lambda a, t: (
        f"行走 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}→({a[1]},{a[2]})"
        if len(a)>=3 else f"行走 ({','.join(a)})" if a else "行走"
    ),
    # opcode 10: WaitWalk(2) — 等待行走完成 (sub_40BCC0)
    # 参数: 实体(-1=上下文 -2=自身), 模式(0=异步 1=同步阻塞)
    # 同步模式下脚本暂停直到行走完成; 异步模式检查flags bit4判断是否在行走
    'WaitWalk':     lambda a, t: (
        f"等待行走 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} {'同步' if len(a)>=2 and a[1]!='0' else '异步'}"
        if a else "等待行走"
    ),
    # opcode 11: StopWalk(2) — 停止行走 (sub_40BD84)
    # 参数: 实体(-1=上下文 -2=自身), 方向(1-8, 0=清除方向重置动画)
    'StopWalk':     lambda a, t: (
        f"停止行走 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} 方向={a[1] if len(a)>=2 and a[1]!='0' else '重置'}"
        if a else "停止行走"
    ),
    # opcode 12: SetEnabled(2) — 启用/禁用实体 (sub_40BE30)
    # 参数: 实体(-1=上下文 -2=自身), 标志(0=禁用flags bit0清零, 1=启用flags bit0置位)
    'SetEnabled':   lambda a, t: (
        f"{'启用' if len(a)>=2 and a[1]!='0' else '禁用'} {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}"
        if a else "启用/禁用"
    ),
    # opcode 13: SetVisible(2) — 设置实体可见性, 修改 flags bit1
    # 逆向: sub_40CB?? — arg1=实体(-1=上下文 -2=自身) arg2=0隐藏/1显示
    'SetVisible':   lambda a, t: (
        f"显示 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}" if len(a)>=2 and a[1]=='1' else
        f"隐藏 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}" if len(a)>=2 and a[1]=='0' else
        f"设置可见性 实体#{a[0]} 标志={a[1]}" if len(a)>=2 else
        "设置可见性"
    ),
    # opcode 14: SetWait(3) — 设置等待/延时 (sub_40BF88)
    # 参数: 实体(-1=上下文 -2=自身), 最小tick, 最大tick
    # 实体param字段 = random(min, max), 用于随机延时触发
    'SetWait':      lambda a, t: (
        f"设置等待 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} [{a[1]},{a[2]}]tick"
        if len(a)>=3 else f"设置等待 ({','.join(a)})" if a else "设置等待"
    ),
    # opcode 15: Nop(0) — 空操作
    'Nop':          lambda a, t: f"空操作 (填充={a[0]})" if a else "空操作",
    # opcode 16: SetCursor(3) — 设置光标
    # 逆向: sub_411BA4/sub_412390, TKMat[d8]=cursor_id
    # 参数: (实体, 光标动画, 开关)  动画:0=默认 1=标准 3=开门(传送)  开关:0=隐藏 1=显示
    'SetCursor':    lambda a, t: _setcursor_desc(a),
    # opcode 17: FadeOut(4) — 淡出 (sub_409830)
    # 参数: R, G, B, 速度(越大越快)
    'FadeOut':      lambda a, t: f"淡出 RGB({a[0]},{a[1]},{a[2]}) 速度={a[3]}" if len(a)>=4 else "淡出",
    # opcode 18: FadeIn(4) — 淡入: R, G, B, 速度
    'FadeIn':       lambda a, t: f"淡入 RGB({a[0]},{a[1]},{a[2]}) 速度={a[3]}" if len(a)>=4 else "淡入",
    # opcode 19: ChangeScene(4) — 切换场景 (sub_40C044)
    # 参数: 场景ID, 玩家X, 玩家Y, 朝向(1-8)
    # 加载新场景文件, 设置玩家位置和朝向, 重置天气/对话等状态
    # 场景名称通过 TKT_ID = scene_id + 300 获取
    'ChangeScene':  lambda a, t: (
        f"切换场景→#{a[0]} {_tkt_scene(t, a[0])} ({a[1]},{a[2]})朝向{a[3]}"
        if len(a)>=4 else
        f"切换场景→#{a[0]} {_tkt_scene(t, a[0])}" if a else "切换场景"
    ),
    # opcode 20: SetAni(7) — 设置动画 (sub_40C1A4)
    # 参数: 实体(-1=上下文 -2=自身), Ani.JVG块ID, 帧起点(-1=不变), 帧终点(-1=不变), 
    #        当前帧(-1=不变), 动画速度(-1=不变), 循环标志(0=不循环 1=循环 -1=不变)
    # 仅type=20/200有效; 设置anim_set=4(Ani.JVG), 修改子模型和动画参数
    'SetAni':       lambda a, t: (
        f"设置动画 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} 块={a[1]}"
        if len(a)>=2 else f"设置动画 ({','.join(a)})" if a else "设置动画"
    ),
    # opcode 21: SetTick(2) — 设置Tick周期 (sub_40C388)
    # 参数: 实体(-1=上下文 -2=自身), tick周期值
    # 修改实体的tick字段(dword[4]), 控制自动脚本执行频率
    'SetTick':      lambda a, t: (
        f"设置Tick {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}={a[1]}帧"
        if len(a)>=2 else f"设置Tick ({','.join(a)})" if a else "设置Tick"
    ),
    # opcode 22: SetShadow(2) — 设置阴影 (sub_40C428)
    # 参数: 实体(-1=上下文 -2=自身), 阴影帧(0=无 1=小 2=大)
    # 仅type=20/200有效, 修改shadow_frame字段(dword[55])
    'SetShadow':    lambda a, t: (
        f"设置阴影 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}={'无' if a[1]=='0' else '小' if a[1]=='1' else '大' if a[1]=='2' else a[1]}"
        if len(a)>=2 else f"设置阴影 ({','.join(a)})" if a else "设置阴影"
    ),
    # opcode 23: SetPos(4) — 设置位置: 实体, X, Y, 朝向
    'SetPos':       lambda a, t: (
        f"设置位置 实体#{a[0]}→({a[1]},{a[2]})朝向{a[3]}({_dir_name(a[3],a[0])})" if len(a)>=4 else
        f"设置位置 实体#{a[0]}" if a else "设置位置"),
    # opcode 24: Disable(1) — 禁用实体 (sub_40C5A4)
    # 参数: 实体(-1=上下文 -2=自身)
    # 同时清除flags bit0(启用)和bit1(可见), 实体完全不可见不可交互
    'Disable':      lambda a, t: (
        f"禁用 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}"
        if a else "禁用"
    ),
    # opcode 25: Enable(1) — 启用实体 (sub_40C648)
    # 参数: 实体(-1=上下文 -2=自身)
    # 同时设置flags bit0(启用)和bit1(可见), 与Disable相反
    'Enable':       lambda a, t: (
        f"启用 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}"
        if a else "启用"
    ),
    # opcode 26: Redraw(1) — 重绘画面 (sub_40C6EC)
    # 参数: 帧数(持续渲染N帧)
    # 强制执行完整的渲染循环N帧, 包含天气/对话框/光标等所有UI元素
    'Redraw':       lambda a, t: f"重绘 {a[0]}帧" if a else "重绘画面",
    # opcode 27: SetPlayer(1) — 设置玩家角色 (sub_40C7CC)
    # 参数: 实体ID(必须是type=200)
    # 设置当前操控的玩家角色, 修改dword_755B5C和dword_8242E0
    'SetPlayer':    lambda a, t: f"设置玩家→实体#{a[0]}" if a else "设置玩家",
    # opcode 28: SetCamera(1) — 设置镜头跟随目标 (sub_40C854)
    # 参数: 实体(-1=禁用镜头跟随, 其他=跟随该实体)
    # 修改dword_8242E4, 镜头会跟随目标实体移动
    'SetCamera':    lambda a, t: (
        f"镜头→{'禁用' if a[0]=='-1' else '实体#'+a[0]}"
        if a else "设置镜头"
    ),
    # opcode 29: SetView(2) — 设置视角 (sub_40C8E0)
    # 参数: X, Y (世界坐标)
    # 直接设置镜头视口位置, 与SetCamera不同的是不跟随实体
    'SetView':      lambda a, t: f"视角→({a[0]},{a[1]})" if len(a)>=2 else f"设置视角" if a else "设置视角",
    # opcode 30: SlideTo(3) — 平滑移动镜头 (sub_40C9E8)
    # 参数: 目标X, 目标Y, 帧数(移动持续时间)
    # 镜头从当前位置平滑移动到目标位置, 每帧更新
    'SlideTo':      lambda a, t: f"镜头滑动→({a[0]},{a[1]}) {a[2]}帧" if len(a)>=3 else "镜头滑动",
    # opcode 31: PlayerAct(1) — 玩家操作
    # TKD用法: PlayerAct(0)=锁定(脚本开头) PlayerAct(1)=恢复(脚本结尾)
    'PlayerAct':   lambda a, t: (
        "锁定玩家操作" if a and a[0] == '0' else
        "恢复玩家操作" if a and a[0] == '1' else
        f"玩家操作 模式={a[0]}" if a else "玩家操作"),
    # opcode 32: SetFlag(2) — 设置标志 (sub_40CB08→word_756080[1024])
    # 存储位置: 存档 Frame2 SEG1 +0x568, 1024个int16, 随存档持久化
    'SetFlag':      lambda a, t: f"设置标志 #{a[0]}={a[1]}" if len(a)>=2 else f"设置标志 #{a[0]}" if a else "设置标志",
    # opcode 33: AddFlag(2) — 增加标志 (sub_40CB4C→word_756080[flag_id]+=value)
    'AddFlag':      lambda a, t: f"增加标志 #{a[0]}+{a[1]}" if len(a)>=2 else f"增加标志 #{a[0]}" if a else "增加标志",
    # opcode 34: TalkA(5) — 即时式对话: 实体, 文本ID, 参数, 参数, 参数
    'TalkA':        lambda a, t: f"对话(即时) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"对话(即时) 实体#{a[0]}" if a else "对话(即时)",
    # opcode 35: Switch(2) — NPC状态切换 (sub_40CB90)
    # 参数: 实体(-1=上下文 -2=自身), 模式(0=常规/站桩 1=动画/行走)
    # 仅type=200有效; arg2=0: anim_set→1(Cha.JVG)+移动模式→0(静止)
    # arg2=1: anim_set→4(Ani.JVG)+移动模式→1(行走)
    # TKD中成对使用: Switch(N,0)在对话/菜单前 → Switch(N,1)在结束后
    'Switch':       lambda a, t: (
        f"切换NPC·{'常规' if a[1]=='0' else '动画'} {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else 'NPC#'+a[0]}"
        if len(a)>=2 else "NPC状态切换"
    ),
    # opcode 36: SetVar(2) — 设置脚本变量 (case 36)
    # 参数: 变量槽(0-249), 值
    # 变量存储在word_755E80[256], 超出范围会报错
    'SetVar':       lambda a, t: f"变量[{a[0]}]={a[1]}" if len(a)>=2 else f"变量[{a[0]}]" if a else "设置变量",
    # opcode 37: Random(3) — 随机数 (case 37)
    # 参数: 变量槽, 最小值, 最大值
    # 生成[min, max]范围的随机数存入变量槽; max必须>min否则报错
    'Random':       lambda a, t: f"随机→变量[{a[0]}] [{a[1]},{a[2]}]" if len(a)>=3 else "随机",
    # opcode 38: SetFlagVar(2) — 设置标志变量
    'SetFlagVar':   lambda a, t: f"标志变量 标志={a[0]},变量槽={a[1]}" if len(a)>=2 else f"标志变量 标志={a[0]}" if a else "设置标志变量",
    # opcode 39: AddFlagVar(2) — 增加标志变量
    'AddFlagVar':   lambda a, t: f"增加标志变量 标志={a[0]},变量槽={a[1]}" if len(a)>=2 else f"增加标志变量 标志={a[0]}" if a else "增加标志变量",
    # opcode 40: GetItem(2) — 道具/金钱增减 (sub_40CE30)
    # 参数: 道具ID(10000=金钱), 数量(正=获得 负=移除)
    # 道具数量上限99, 金钱上限30000; 获得时显示SysTalk提示
    'GetItem':      lambda a, t, i=None: (
        f"金钱 {_sign_qty(a[1])}" if a and len(a)>=2 and a[0]=='10000' else
        f"道具 {a[0]}({_item_name(i, a[0])}) {_sign_qty(a[1])}" if a and len(a)>=2 and i else
        f"道具 {a[0]}({_item_name(i, a[0])})" if a and i else
        f"道具 ID={a[0]}" if a else "道具增减"
    ),
    # opcode 41: BlackTalk(4) — 黑屏对话/旁白
    # 逆向: sub_40B05C(text_id, x, y, color)→sub_4067E8加载TKT+sub_44B028设颜色, 循环渲染至按键
    'BlackTalk':    lambda a, t: (
        f"黑屏对话 文本={a[0]} ({a[1]},{a[2]}) 色{a[3]} — {_tkt_text(t, a[0])}" if len(a)>=4 else
        f"黑屏对话 文本={a[0]} — {_tkt_text(t, a[0])}" if a else "黑屏对话"),
    # opcode 42: SetChaPic(2) — 设置角色立绘 (sub_40D0CC)
    # 参数: 实体(-1=上下文 -2=自身), Cha.JVG块ID
    # 仅type=200有效; 修改立绘ID(dword[51])和相关动画参数
    'SetChaPic':    lambda a, t: (
        f"设置立绘 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}→块{a[1]}"
        if len(a)>=2 else f"设置立绘 ({','.join(a)})" if a else "设置立绘"
    ),
    # opcode 43: SetWeather(2) — 设置天气效果 (sub_40D2A0)
    # 参数: 天气类型(0=关闭 1=雨), 保留
    # a1=0: 清除天气粒子(sub_405B98)
    # a1=1: 开启下雨效果(sub_405BE0), 参数: 类型=1, 粒子数=5, 最大=400, 增速=10, 速度=5
    'SetWeather':   lambda a, t: (
        f"天气→{'关闭' if a[0]=='0' else '下雨' if a[0]=='1' else '类型'+a[0]}"
        if a else "设置天气"
    ),
    # opcode 44: ShowMenu(2) — 显示菜单
    # 逆向: sub_40D2D0(__int16 a1), 参数: 0=主菜单 1=存档/读档菜单
    'ShowMenu':     lambda a, t: (
        f"显示主菜单" if a and a[0] == '0' else
        f"显示存档菜单" if a and a[0] == '1' else
        f"显示菜单 类型={a[0]}" if a else "显示菜单"
    ),
    # opcode 45: TeamMember(2) — 队伍成员增减 (sub_40DA00, a2=1加入/0离开, a1=0清空全队)
    'TeamMember':   lambda a, t: (
        f"角色 {_cm(a[0])} 加入队伍" if len(a)>=2 and a[1]=='1' else
        f"角色 {_cm(a[0])} 离开队伍" if len(a)>=2 and a[1]=='0' else
        "清空全队" if a and a[0]=='0' else "队伍成员"),
    # opcode 46: Note(2) — 注释/标记 (sub_40DBF4)
    # 参数: 标记槽(0-999), 值
    # 存储在word_7568D8[1000], 用于脚本状态标记, 不影响游戏逻辑
    'Note':         lambda a, t: f"标记[{a[0]}]={a[1]}" if len(a)>=2 else f"标记 ({','.join(a)})" if a else "注释",
    # opcode 47: SetBlock(2) — 路径封锁开关 (仅type=10传送点使用)
    # sub_40DC1C: v3[62]=a2; >0封锁(路径网格清零)sub_4526D0(...,0,...); 0开放sub_4526D0(...,*(BYTE*)(a2+252),...)
    # 同时 sub_4081F8 检查 d62 阻止传送
    'SetBlock':     lambda a, t: (
        f"解锁传送点#{a[0]}" if len(a)>=2 and a[1]=="0" else
        f"封锁传送点#{a[0]}" if len(a)>=2 and a[1]!="0" else
        f"传送点路径封锁#{a[0]}" if a else "传送点路径封锁"),
    # 来源: TKD_decoded.txt 664处用法 + 脚本注释
    # arg2: 1=智慧 2=仁德 3=勇气 5=体力值恢复 6=内力值恢复 10=事件完成度 11=特殊物品
    # arg3: 正=增加 负=减少
    'Attribute':   lambda a, t: _attribute_desc(a),
    # opcode 49: SetSwitch(2) — 设置全局运行时开关 (case 49)
    # 参数: 开关槽(0-31), 值
    # 存储在word_755E10[32], 仅运行时有效不存档; 用于UI流程/事件控制
    # 与SetFlag(存档持久)不同: SetSwitch是临时状态
    'SetSwitch':    lambda a, t: f"开关[{a[0]}]={a[1]}" if len(a)>=2 else f"开关[{a[0]}]" if a else "设置开关",
    # opcode 50: BuyMenu(3) — 商店菜单
    # 逆向: sub_40D804(__int16 a1, __int16 a2, __int16 a3)
    # a1=商品ID, a2=商品索引, a3=商店模式(0-4: 0=武器 1=防具 2=药品 3=杂货 4=特殊)
    'BuyMenu':      lambda a, t: (
        f"商店菜单 商品={a[0]} 索引={a[1]} 模式={'武器' if a[2]=='0' else '防具' if a[2]=='1' else '药品' if a[2]=='2' else '杂货' if a[2]=='3' else '特殊' if a[2]=='4' else a[2]}"
        if len(a)>=3 else "商店菜单"
    ),
    # opcode 51: PlaySound(2) — 播放音效 (sub_451780 + sub_451C38)
    # 参数: 音效ID, 循环(0=不循环 1=循环)
    # 音效文件: sound\%04d.wav; 使用DirectSound播放
    'PlaySound':    lambda a, t: (
        f"播放音效 {a[0]} {'循环' if len(a)>=2 and a[1]!='0' else '单次'}"
        if a else "播放音效"
    ),
    # opcode 52: StopSound(1) — 停止音效 (sub_451D2C)
    # 无参数; 停止当前播放的音效
    'StopSound':    lambda a, t: "停止音效",
    # opcode 53: PlayMusic(2) — 播放音乐 (sub_44AC50 + sub_44AC90)
    # 参数: 音乐ID, 循环(0=不循环 1=循环)
    # 音乐文件: sound\%04d.mp3; 使用DirectShow播放
    'PlayMusic':    lambda a, t: (
        f"播放音乐 {a[0]} {'循环' if len(a)>=2 and a[1]!='0' else '单次'}"
        if a else "播放音乐"
    ),
    # opcode 54: SetMusic(2) — 设置场景BGM映射 (case 54)
    # 参数: 场景ID(0-255), 音乐ID(-1=停止当前)
    # 存储在byte_755B74[256], 切换场景时自动播放对应BGM
    # 如果设置的是当前场景的BGM且值<0, 则停止当前音乐
    'SetMusic':     lambda a, t: (
        f"场景BGM 场景{a[0]}→{'停止' if a[1]=='-1' else '音乐'+a[1]}"
        if len(a)>=2 else f"场景BGM ({','.join(a)})" if a else "场景BGM"
    ),
    # opcode 55: TheEnd(1) — 游戏结局 (case 55)
    # 参数: 结局ID(0-99)
    # 设置word_951940 = 结局ID + 100, 然后返回-1终止脚本执行
    # 触发游戏结局画面
    'TheEnd':       lambda a, t: f"游戏结局 #{a[0]}" if a else "游戏结局",
    # opcode 56: Fix(1) — 修正/空操作 (case 56)
    # 参数: 保留
    # 仅word_755AB2 += 2, 不执行任何操作; 可能用于版本兼容或调试
    'Fix':          lambda a, t: f"修正(保留={a[0]})" if a else "修正",
    # ===== [Special] 条件跳转类 =====
    # opcode 60: CheckResult(2) — 检查变量结果跳转 (case 60)
    # 参数: 变量槽, 期望值, 跳转偏移(隐含在字节码中)
    # 如果word_755E50[变量槽] == 期望值, 继续执行; 否则跳转
    # word_755E50存储上次比较操作的结果
    'CheckResult':  lambda a, t: f"检查结果 变量[{a[0]}]=={a[1]}?" if len(a)>=2 else "检查结果",
    # opcode 61: CheckFlag(3) — 检查标志条件跳转 (sub_40E40C)
    # 参数: 标志ID(0-1023), 期望值, 操作符(0=== 1=>= -1=< -2=<= 2=> 3=!=)
    # 比较word_756080[标志ID]与期望值, 结果存入dword_755AA0
    # 字节码中隐含跳转偏移: 如果比较失败则跳转
    'CheckFlag':    lambda a, t: (
        f"检查标志 #{a[0]} {_CMP_OPS.get(a[2], a[2])} {a[1]}?"
        if len(a)>=3 else f"检查标志 #{a[0]}" if a else "检查标志"
    ),
    # opcode 62: CheckItem(3) — 检查道具条件跳转 (sub_40E4E4)
    # 参数: 道具ID(10000=金钱), 期望数量, 操作符(0=== 1=>= -1=< -2=<= 2=> 3=!=)
    # 统计背包+队伍装备中的道具总数, 与期望值比较
    # 结果存入dword_755AA0, 字节码中隐含跳转偏移
    'CheckItem':    lambda a, t: (
        f"检查道具 {a[0]} {_CMP_OPS.get(a[2], a[2])} {a[1]}?"
        if len(a)>=3 else f"检查道具 {a[0]}" if a else "检查道具"
    ),
    # opcode 63: CheckTeam(3) — 检查队伍条件跳转
    'CheckTeam':    lambda a, t, i=None: _checkteam_desc(a),
    # opcode 64: MiniGame(3) — 小游戏 (sub_40E97C)
    # 参数: 游戏类型(1-7), 难度/参数, 跳转偏移(失败时跳转)
    # 游戏类型: 1=华容道 2=八阵图 3=骰子 4=串珠 5=四四同数 6=拼图 7=龙蛇百变
    # 返回dword_755AA0: 1=成功 0=失败; 失败时跳转到指定偏移
    'MiniGame':     lambda a, t: (
        f"小游戏 {'华容道' if a[0]=='1' else '八阵图' if a[0]=='2' else '骰子' if a[0]=='3' else '串珠' if a[0]=='4' else '四四同数' if a[0]=='5' else '拼图' if a[0]=='6' else '龙蛇百变' if a[0]=='7' else '类型'+a[0]}"
        if a else "小游戏"
    ),
    # opcode 65: CheckMember(4) — 检查队伍成员属性 (sub_40E88C)
    # 参数: 角色ID, 属性类型(0=等级), 期望值, 操作符(0=== 1=>= -1=< -2=<= 2=> 3=!=)
    # 检查指定角色的属性值, 结果存入dword_755AA0
    # 字节码中隐含跳转偏移: 如果比较失败则跳转
    'CheckMember':  lambda a, t: (
        f"检查成员 角色#{a[0]} 属性{a[1]} {_CMP_OPS.get(a[3], a[3])} {a[2]}?"
        if len(a)>=4 else f"检查成员 ({','.join(a)})" if a else "检查成员"
    ),
    # opcode 66: War(1) — 战斗 (sub_40EB10)
    # 参数: 战斗ID
    # 触发战斗, 播放战斗BGM, 切换到战斗场景
    # 返回dword_755AA0: 1=胜利 0=失败; 字节码中隐含跳转偏移
    'War':          lambda a, t: f"战斗 #{a[0]}" if a else "战斗",
    # ===== [NoArg] =====
    # opcode 82: Else — 条件分支的否则 (case 82)
    # 参数: 跳转偏移(隐含在字节码中)
    # 如果dword_755AAC <= 0(上次条件为真), 跳转到指定偏移; 否则继续执行
    # 用于实现if-else结构
    'Else':         lambda a, t: "否则 (条件分支)",
    # ===== TKD 文本层额外命令 (非 DEFCMD.LST 标准，但在脚本中实际出现或用于兼容) =====
    'Yield':        lambda a, t: "让出控制权 (暂停当前帧)",
    'Jump':         lambda a, t: f"跳转到偏移={a[0]}" if a else "跳转",
    'ShowText':     lambda a, t: f"显示文本 ID={a[0]} — {_tkt_text(t, a[0])}" if a else "显示文本",
    'MenuChoice':   lambda a, t: f"菜单选择 实体#{a[0]}" if a else "菜单选择",
    'SetPosFade':   lambda a, t: f"淡入位置 实体#{a[0]}→({a[1]},{a[2]})" if len(a)>=3 else "淡入位置",
    'SceneFade':    lambda a, t: f"场景过渡→#{a[0]}" if a else "场景过渡",
    'SceneBGM':     lambda a, t: f"场景BGM 场景#{a[0]}" if a else "场景BGM",
    'Camera':       lambda a, t: f"镜头控制 ({a[0]},{a[1]},{a[2]})" if len(a)>=3 else "镜头控制",
    'WaitInput':    lambda a, t: "等待玩家输入 (按键继续)",
    'SetGlobal':    lambda a, t: f"设置全局变量={a[0]}" if a else "设置全局变量",
    'SetWord':      lambda a, t: f"设置字={a[0]}" if a else "设置字",
    'WaitTimer':    lambda a, t: f"定时等待 {a[0]}×{a[1]}ms" if len(a)>=2 else "定时等待",
    'Music':        lambda a, t: f"播放音乐 ID={a[0]}" if a else "播放音乐",
}

# ============================================================
# TKT 场景名 (延迟解析版)
# ============================================================
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
    """保存 TKDefUnit.dat — 5000 条 × 16 字节"""
    buf = bytearray(DEFUNIT_FILE_SIZE)
    for rec in defunit_recs:
        off = rec['index'] * DEFUNIT_REC_SIZE
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

# ============================================================
# JVG 精灵帧辅助
# ============================================================
def _get_jvg(filepath):
    """加载 JVG 文件 (缓存)"""
    if filepath in _JVG_CACHE: return _JVG_CACHE[filepath]
    if not os.path.exists(filepath): return None
    _grp_dir = os.path.normpath(os.path.join(os.path.dirname(__file__),'..','grp_editor'))
    _jvg_dir = os.path.normpath(os.path.join(os.path.dirname(__file__),'..','jvg_editor'))
    for d in [_grp_dir, _jvg_dir]:
        if d not in sys.path: sys.path.insert(0, d)
    try:
        from jvg_editor import load_jvg
        jvg = load_jvg(filepath)
        _JVG_CACHE[filepath] = jvg
        return jvg
    except ImportError:
        return None

def _get_jvg_frame(jvg, global_idx):
    """按全局索引获取 JVG (block, frame_in_block)"""
    if not jvg or global_idx < 0: return None, None, None
    for blk in jvg.blocks:
        if global_idx < blk.frame_count:
            return blk, blk.frames[global_idx], global_idx
        global_idx -= blk.frame_count
    return None, None, None

def _jvg_sprite_to_pil(jvg, block_idx, frame_idx=0):
    """从 JVG 的 block[block_idx].frames[frame_idx] 提取 PIL Image (缓存)"""
    key = (id(jvg), block_idx, frame_idx)
    if key in _SPRITE_CACHE: return _SPRITE_CACHE[key]
    if not jvg or block_idx < 0 or block_idx >= jvg.block_count: return None
    blk = jvg.blocks[block_idx]
    if frame_idx < 0 or frame_idx >= blk.frame_count: return None
    frame = blk.frames[frame_idx]
    if frame.width <= 0 or frame.height <= 0: return None
    pr = blk.palette.to_rgb888()
    rgba = bytearray(frame.width * frame.height * 4)
    px, al = frame.pixels, frame.alpha
    for y in range(frame.height):
        for x in range(frame.width):
            p = y * frame.width + x; off = p * 4
            if p < len(al) and al[p] == 0: continue
            ci = px[p] if p < len(px) else 0
            rgba[off] = pr[ci*3]; rgba[off+1] = pr[ci*3+1]
            rgba[off+2] = pr[ci*3+2]; rgba[off+3] = 255
    from PIL import Image
    img = Image.frombytes('RGBA', (frame.width, frame.height), bytes(rgba))
    _SPRITE_CACHE[key] = img
    return img

_SHADOW_CACHE = {}  # (jvg_id, block_idx, frame_idx) → PIL.Image (减法混合近似)

def _make_subtractive_shadow(jvg, block_idx, frame_idx):
    """将 JVG 阴影帧转为减法混合近似: 黑底 + alpha=src亮度
    sub_45871C: dst=max(dst-src,0) → Canvas alpha 近似: dst*(1-L/255)"""
    key = (id(jvg), block_idx, frame_idx)
    if key in _SHADOW_CACHE: return _SHADOW_CACHE[key]
    if not jvg or block_idx < 0 or block_idx >= jvg.block_count: return None
    blk = jvg.blocks[block_idx]
    if frame_idx < 0 or frame_idx >= blk.frame_count: return None
    frame = blk.frames[frame_idx]
    if frame.width <= 0 or frame.height <= 0: return None
    pr = blk.palette.to_rgb888()
    rgba = bytearray(frame.width * frame.height * 4)
    px, al = frame.pixels, frame.alpha
    for y in range(frame.height):
        for x in range(frame.width):
            p = y * frame.width + x; off = p * 4
            if p < len(al) and al[p] == 0: continue
            ci = px[p] if p < len(px) else 0
            r, g, b = pr[ci*3], pr[ci*3+1], pr[ci*3+2]
            L = int(0.299*r + 0.587*g + 0.114*b)  # NTSC 亮度
            rgba[off] = 0; rgba[off+1] = 0; rgba[off+2] = 0; rgba[off+3] = L
    from PIL import Image
    img = Image.frombytes('RGBA', (frame.width, frame.height), bytes(rgba))
    _SHADOW_CACHE[key] = img
    return img

_BLEND_CACHE = {}  # (jvg_id, blk_idx, frame_idx, mode, param) → PIL.Image

def _get_blended_sprite(jvg, block_idx, frame_idx, mode=0, param=0):
    """取 JVG 精灵帧并按混合模式处理，带缓存。
    mode: 0=正常 1=染色 2=加法发光 3=减法压暗 4=亮度alpha 5=水平翻转"""
    if mode == 0:
        return _jvg_sprite_to_pil(jvg, block_idx, frame_idx)
    key = (id(jvg), block_idx, frame_idx, mode, param)
    if key in _BLEND_CACHE: return _BLEND_CACHE[key]
    if not jvg or block_idx < 0 or block_idx >= jvg.block_count: return None
    blk = jvg.blocks[block_idx]
    if frame_idx < 0 or frame_idx >= blk.frame_count: return None
    frame = blk.frames[frame_idx]
    if frame.width <= 0 or frame.height <= 0: return None
    pr = blk.palette.to_rgb888()
    rgba = bytearray(frame.width * frame.height * 4)
    px, al = frame.pixels, frame.alpha
    for y in range(frame.height):
        for x in range(frame.width):
            p = y * frame.width + x; off = p * 4
            if p < len(al) and al[p] == 0: continue
            ci = px[p] if p < len(px) else 0
            rgba[off] = pr[ci*3]; rgba[off+1] = pr[ci*3+1]
            rgba[off+2] = pr[ci*3+2]; rgba[off+3] = 255
    from PIL import Image, ImageOps
    img = Image.frombytes('RGBA', (frame.width, frame.height), bytes(rgba))
    if mode == 5:
        img = ImageOps.mirror(img)
    elif mode == 1:
        # 染色: 按 param 颜色值乘入 RGB 通道 (sub_454D24)
        from PIL import ImageChops
        r_tint = (param >> 10) & 0x1F; g_tint = (param >> 5) & 0x1F; b_tint = param & 0x1F
        if param > 0 and param <= 31:
            sf_r = r_tint / 31.0; sf_g = g_tint / 31.0; sf_b = b_tint / 31.0
            r_ch, g_ch, b_ch, a_ch = img.split()
            r_ch = r_ch.point(lambda v: int(v * sf_r))
            g_ch = g_ch.point(lambda v: int(v * sf_g))
            b_ch = b_ch.point(lambda v: int(v * sf_b))
            img = Image.merge('RGBA', (r_ch, g_ch, b_ch, a_ch))
    elif mode == 2:
        # 加法发光近似: 白色半透明叠加 (sub_4559D0)
        # param=0或>31 → scale=1.0; 0<param<=31 → scale=param/32
        scale = 1.0 if param == 0 or param > 31 else param / 32.0
        if scale > 0:
            r_ch, g_ch, b_ch, a_ch = img.split()
            # 像素越亮 → 加法贡献越大; alpha = 亮度 * scale
            lum = r_ch.point(lambda v: int(v * 0.299)) if False else r_ch
            from PIL import ImageChops
            lum = ImageChops.add(
                ImageChops.add(
                    r_ch.point(lambda v: int(v * 0.299)),
                    g_ch.point(lambda v: int(v * 0.587))),
                b_ch.point(lambda v: int(v * 0.114)))
            new_a = lum.point(lambda v: int(min(255, v * scale)))
            white = Image.new('L', img.size, 255)
            img = Image.merge('RGBA', (white, white, white, new_a))
    elif mode == 3:
        # 减法压暗: 同阴影处理 — 黑底+亮度为alpha (sub_45871C)
        px_new = img.load()
        for y in range(img.height):
            for x in range(img.width):
                r, g, b, a = px_new[x, y]
                if a == 0: continue
                L = int(0.299*r + 0.587*g + 0.114*b)
                px_new[x, y] = (0, 0, 0, L)
    elif mode == 4:
        # 亮度 alpha: 按 src 亮度修改 alpha 通道 (sub_459854)
        r_ch, g_ch, b_ch, a_ch = img.split()
        from PIL import ImageChops
        lum = ImageChops.add(
            ImageChops.add(
                r_ch.point(lambda v: int(v * 0.299)),
                g_ch.point(lambda v: int(v * 0.587))),
            b_ch.point(lambda v: int(v * 0.114)))
        # 亮度 0~255 → 5-bit (0~31) → alpha 0~255
        new_a = lum.point(lambda v: int(v * 31 / 255) * 8)
        img = Image.merge('RGBA', (r_ch, g_ch, b_ch, new_a))
    _BLEND_CACHE[key] = img
    return img

def _get_dir_frame(blk, d13, d16, d53, anim_cycle=0):
    """按朝向计算 JVG block 内的帧索引。
    sub_4077E4: [14] = [17] + [52] + [16] * dir_mult
    [16] 是 sub_4540E8 返回的总帧数, 需按方向数折算 fpd (frames_per_direction)
    帧在 block 内按方向分组: [dir0_f0..dir0_fn][dir1_f0..dir1_fn]... """
    if not blk or blk.frame_count == 0: return 0, 1
    if d53 == 4:
        fpd = max(1, blk.frame_count // 4)
        dir_grp = max(0, min(3, (d13 - 1) >> 1))
    elif d53 == 8:
        fpd = max(1, blk.frame_count // 8)
        dir_grp = max(0, min(7, d13 - 1))
    else:
        fpd = blk.frame_count; dir_grp = 0
    base = dir_grp * fpd
    frame = base + (anim_cycle % fpd)
    if frame >= blk.frame_count: frame = base
    return frame, fpd

# ============================================================
# PIL 图像合成 (sub_406864 switch d24 → 严格按逆向实现)
# ============================================================
_RGBA_CACHE = {}  # (jvg_id, block_idx, frame_idx) → PIL.Image(RGBA)

def _get_jvg_frame_rgba(jvg, block_idx, frame_idx):
    """取 JVG 帧为 PIL RGBA Image (缓存), 供合成函数使用"""
    key = (id(jvg), block_idx, frame_idx)
    if key in _RGBA_CACHE: return _RGBA_CACHE[key].copy()
    if not jvg or block_idx < 0 or block_idx >= jvg.block_count: return None
    blk = jvg.blocks[block_idx]
    if frame_idx < 0 or frame_idx >= blk.frame_count: return None
    frame = blk.frames[frame_idx]
    if frame.width <= 0 or frame.height <= 0: return None
    pr = blk.palette.to_rgb888()
    rgba = bytearray(frame.width * frame.height * 4)
    px, al = frame.pixels, frame.alpha
    for y in range(frame.height):
        for x in range(frame.width):
            p = y * frame.width + x; off = p * 4
            if p < len(al) and al[p] == 0: continue
            ci = px[p] if p < len(px) else 0
            rgba[off] = pr[ci*3]; rgba[off+1] = pr[ci*3+1]
            rgba[off+2] = pr[ci*3+2]; rgba[off+3] = 255
    from PIL import Image
    img = Image.frombytes('RGBA', (frame.width, frame.height), bytes(rgba))
    _RGBA_CACHE[key] = img.copy()
    return img

def _pil_normal(composite, rgba_src, dx, dy):
    """mode 0: 正常 alpha 贴图"""
    if composite is None or rgba_src is None: return
    try:
        composite.paste(rgba_src, (dx, dy), rgba_src)
    except Exception:
        pass

def _pil_tint(rgba_src, param):
    """mode 1: 染色 — sub_454D24 按 param 5-bit RGB 分量缩放通道。
    param=0 或 >31 → 不变; 0<param<=31 → R*=r/31, G*=g/31, B*=b/31"""
    if rgba_src is None: return None
    if param <= 0 or param > 31: return rgba_src
    r_tint = (param >> 10) & 0x1F; g_tint = (param >> 5) & 0x1F; b_tint = param & 0x1F
    r_ch, g_ch, b_ch, a_ch = rgba_src.split()
    r_ch = r_ch.point(lambda v: int(v * r_tint / 31))
    g_ch = g_ch.point(lambda v: int(v * g_tint / 31))
    b_ch = b_ch.point(lambda v: int(v * b_tint / 31))
    from PIL import Image
    return Image.merge('RGBA', (r_ch, g_ch, b_ch, a_ch))

def _pil_additive(composite, rgba_src, dx, dy, param):
    """mode 2: 加法饱和混合 — sub_4559D0/sub_4573A0
    param=0或>31 → full min(dst+src, 255); 0<param<=31 → min(dst+src*param/32, 255)"""
    if composite is None or rgba_src is None: return
    try:
        from PIL import Image, ImageChops
        sw, sh = rgba_src.size; cw, ch = composite.size
        l = max(0, dx); t = max(0, dy)
        r = min(cw, dx + sw); b = min(ch, dy + sh)
        if r <= l or b <= t: return
        sl, st = l - dx, t - dy; sr, sb = r - dx, b - dy
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA': sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
        masked = Image.composite(src_rgb, zero_bg, alpha)
        if 0 < param <= 31:
            factor = param / 32.0
            masked = masked.point(lambda v, f=factor: int(v * f))
        dst_crop = composite.crop((l, t, r, b))
        blended = ImageChops.add(dst_crop, masked)  # saturated: min(a+b, 255)
        composite.paste(blended, (l, t))
    except Exception:
        try: composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception: pass

def _pil_subtract(composite, rgba_src, dx, dy):
    """mode 3: 减法饱和混合 — sub_45871C
    dst.RGB = max(dst - src, 0) 逐通道独立"""
    if composite is None or rgba_src is None: return
    try:
        from PIL import Image, ImageChops
        sw, sh = rgba_src.size; cw, ch = composite.size
        l = max(0, dx); t = max(0, dy)
        r = min(cw, dx + sw); b = min(ch, dy + sh)
        if r <= l or b <= t: return
        sl, st = l - dx, t - dy; sr, sb = r - dx, b - dy
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA': sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
        masked = Image.composite(src_rgb, zero_bg, alpha)
        dst_crop = composite.crop((l, t, r, b))
        blended = ImageChops.subtract(dst_crop, masked)  # saturated: max(a-b, 0)
        composite.paste(blended, (l, t))
    except Exception:
        try: composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception: pass

def _pil_luma_alpha(composite, rgba_src, dx, dy):
    """mode 4: 按 src 亮度做 alpha blend — sub_459854
    α = NTSC_luma_5bit(src); α=0跳过; α>28覆盖; else dst*(32-α)/32+src*α/32"""
    if composite is None or rgba_src is None: return
    try:
        from PIL import Image, ImageChops
        sw, sh = rgba_src.size; cw, ch = composite.size
        l = max(0, dx); t = max(0, dy)
        r = min(cw, dx + sw); b = min(ch, dy + sh)
        if r <= l or b <= t: return
        sl, st = l - dx, t - dy; sr, sb = r - dx, b - dy
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA': sub = sub.convert('RGBA')
        src_alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        luma = src_rgb.convert('L')  # ITU-R 601-2: 0.299R+0.587G+0.114B (游戏用 0.30/0.59/0.11, 差<0.2%)
        mask_luma = luma.point(lambda v: 0 if v == 0 else (255 if v > 224 else v))
        alpha_bin = src_alpha.point(lambda v: 255 if v > 0 else 0)
        mask = ImageChops.multiply(mask_luma, alpha_bin)
        dst_crop = composite.crop((l, t, r, b))
        blended = Image.composite(src_rgb, dst_crop, mask)
        composite.paste(blended, (l, t))
    except Exception:
        try: composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception: pass

# ============================================================
# SC.GRP 场景背景加载
# ============================================================
def load_scene_background(sc_grp_path, sc_idx_path, scene_id):
    """加载 SC.GRP 中原始 section 索引对应的背景图。
    SC.GRP 中 image+data 混排 (206图像+8数据=214段),
    必须按原始索引映射, 不能直接用 grp.sections 数组下标。"""
    if not os.path.exists(sc_grp_path): return None
    try:
        _grp_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'grp_editor'))
        if _grp_dir not in sys.path: sys.path.insert(0, _grp_dir)
        from grp_editor import load_grp, _decode_section_a
    except ImportError:
        return None

    try:
        grp = load_grp(sc_grp_path, sc_idx_path)
        if not grp: return None
        idx_map = {sec.index: sec for sec in grp.sections}
        sec = idx_map.get(scene_id)
        if not sec or sec.width <= 0 or sec.height <= 0: return None

        _decode_section_a(grp, sec)
        if not sec.pixels: return None

        from PIL import Image
        # PIL C 引擎直接解码 RGB565 字节流，替代纯 Python 的 225 万次位移循环
        img = Image.frombytes('RGB', (sec.width, sec.height), sec.pixels, 'raw', 'BGR;16')
        return img
    except Exception:
        return None


def load_scene_background_from_bytes(section_data: bytes):
    """从原始 GRP section 字节数据直接解码场景背景图。
    用于从内存中的 _sc_grp_pending 数据渲染场景。"""
    if not section_data or len(section_data) < 12:
        return None
    try:
        _grp_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'grp_editor'))
        if _grp_dir not in sys.path: sys.path.insert(0, _grp_dir)
        from grp_editor import lzss_decompress as grp_lzss_decompress
    except ImportError:
        return None

    try:
        w, h, comp_a, comp_b = struct.unpack_from('<HHII', section_data, 0)
        if w <= 0 or h <= 0 or w > 4096 or h > 4096:
            return None
        if 12 + comp_a + comp_b > len(section_data):
            return None
        # 解压 frame A: 前4字节为未压缩大小，其余为 LZSS 数据
        fa_data = section_data[12:12 + comp_a]
        if len(fa_data) < 4:
            return None
        uncomp_sz = struct.unpack_from('<I', fa_data, 0)[0]
        lzss_data = fa_data[4:]
        target_size = w * h * 2
        pixels = grp_lzss_decompress(lzss_data, min(uncomp_sz, target_size))
        if len(pixels) < target_size:
            pixels = pixels + b'\x00' * (target_size - len(pixels))

        from PIL import Image
        img = Image.frombytes('RGB', (w, h), pixels[:target_size], 'raw', 'BGR;16')
        return img
    except Exception:
        return None


# ============================================================
# PIL → QPixmap 转换工具
# ============================================================
def _pil_to_qpixmap(pil_img):
    """将 PIL Image (RGBA/RGB) 转换为 QPixmap (不依赖 numpy)"""
    if pil_img is None:
        return QPixmap()
    if pil_img.mode != 'RGBA':
        pil_img = pil_img.convert('RGBA')
    data = pil_img.tobytes('raw', 'RGBA')
    w, h = pil_img.size
    qimg = QImage(data, w, h, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class CodeEditor(QPlainTextEdit):
    """代码编辑器 — 支持 Tab 缩进、多行缩进/反缩进、自动换行等 VSCode 风格操作"""
    INDENT = "  "  # 2 空格缩进

    def keyPressEvent(self, event):
        # Tab 键: 插入缩进或多行缩进
        if event.key() == Qt.Key_Tab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_lines(cursor, indent=True)
            else:
                cursor.insertText(self.INDENT)
            return
        # Shift+Tab: 多行反缩进
        if event.key() == Qt.Key_Backtab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_lines(cursor, indent=False)
            return
        # Enter 键: 自动缩进 (保持上一行的缩进级别)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            block = cursor.block()
            line_text = block.text()
            # 计算当前行的缩进
            indent = ""
            for ch in line_text:
                if ch == ' ':
                    indent += ' '
                elif ch == '\t':
                    indent += '  '
                else:
                    break
            # 如果上一行以 { 结尾，额外增加一级缩进
            stripped = line_text.rstrip()
            if stripped.endswith('{'):
                indent += self.INDENT
            cursor.insertText('\n' + indent)
            return
        super().keyPressEvent(event)

    def _indent_lines(self, cursor, indent=True):
        """对选中的多行进行缩进或反缩进"""
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.beginEditBlock()

        # 移动到选区起始行
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.StartOfBlock)
        start_block = cursor.block()

        # 移动到选区结束行
        cursor.setPosition(end)
        if cursor.atBlockStart() and end > start:
            # 如果选区正好在行首，不包含这一行
            cursor.movePosition(QTextCursor.PreviousBlock)
        cursor.movePosition(QTextCursor.EndOfBlock)
        end_block = cursor.block()

        # 遍历每一行
        block = start_block
        while True:
            line_text = block.text()
            if indent:
                # 缩进: 在行首插入2个空格
                cursor.setPosition(block.position())
                cursor.insertText(self.INDENT)
            else:
                # 反缩进: 删除行首最多2个空格
                if line_text.startswith(self.INDENT):
                    cursor.setPosition(block.position())
                    cursor.setPosition(block.position() + 2, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()
                elif line_text.startswith(' '):
                    cursor.setPosition(block.position())
                    cursor.setPosition(block.position() + 1, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()

            if block == end_block:
                break
            block = block.next()

        cursor.endEditBlock()


class ScriptSyntaxHighlighter(QSyntaxHighlighter):
    """脚本编辑器语法高亮 — 配色方案与 Godot 4.6 代码编辑器保持一致。
    优先级 (高→低): block > command > number > comment > keyword,
    按升序 setFormat 使高优先级后涂覆盖低优先级。"""
    # (浅色, 深色) 配色对 — 参考 Godot 4.6 编辑器主题
    _PALETTE = {
        'keyword': ('#d63547', '#ff7085'),    # 关键字: 红色/粉色
        'comment': ('#6a737d', '#6a737d'),    # 注释: 灰色
        'number':  ('#2e9c6e', '#a1ffe0'),    # 数字: 绿色/青绿色
        'command': ('#6b89ff', '#a1bfff'),    # 命令: 蓝色/浅蓝色
        'block':   ('#c75000', '#ffce7b'),    # 块符号: 橙色/暖黄色
    }

    def __init__(self, document, is_dark=False):
        super().__init__(document)
        self._is_dark = is_dark
        self._build_formats()

    def _build_formats(self):
        def _fmt(key):
            f = QTextCharFormat()
            f.setForeground(QColor(self._PALETTE[key][1 if self._is_dark else 0]))
            return f
        self.fmt_keyword = _fmt('keyword')  # DEFINE
        self.fmt_comment = _fmt('comment')  # // 注释
        self.fmt_number  = _fmt('number')   # 数字
        self.fmt_command = _fmt('command')  # 命令名
        self.fmt_block   = _fmt('block')    # { } 块

    def set_dark(self, is_dark):
        """切换主题后重建格式并重涂"""
        if self._is_dark == is_dark:
            return
        self._is_dark = is_dark
        self._build_formats()
        self.rehighlight()

    def highlightBlock(self, text):
        line = text
        stripped = line.strip()
        line_len = len(line)
        comment_start = line.find('//')
        # 1. keyword (最低优先级)
        if stripped.startswith('DEFINE'):
            self.setFormat(0, line_len, self.fmt_keyword)
        # 2. comment
        if comment_start >= 0:
            self.setFormat(comment_start, line_len - comment_start, self.fmt_comment)
        # 3. number (跳过注释内的数字)
        for m in re.finditer(r'-?\d+', line):
            if comment_start >= 0 and m.start() >= comment_start:
                continue
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_number)
        # 4. command (Cmd( 中的命令名部分)
        for cmd in SCRIPT_COMMANDS:
            needle = cmd + '('
            idx = 0
            while True:
                pos = line.find(needle, idx)
                if pos < 0:
                    break
                self.setFormat(pos, len(cmd), self.fmt_command)
                idx = pos + 1
        # 5. block (最高优先级, 整行)
        if stripped.startswith('{') or stripped.startswith('}'):
            self.setFormat(0, line_len, self.fmt_block)


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
            import traceback
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
            import traceback
            print("Background asset load error:", e, traceback.format_exc())
            self.jvg_result = {}
            self.finished_jvg.emit()


class MatEditorApp(QMainWindow):
    """TKMat.Dat 地图实体编辑器 PySide6 版"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKMat.Dat 地图实体编辑器 v2.3 (PySide6)")
        self.resize(1560, 860)
        self.setMinimumSize(1340, 640)

        # 加载图标
        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        # 主题状态: 根据操作系统自动判断
        app_inst = QApplication.instance()
        self._is_dark = (
            app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark
            if app_inst else True
        )

        # 应用 Godot 风格窗口标题栏 (与 editor_themes 主题一致)
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from editor_utils.window_theme import apply_godot_theme
        apply_godot_theme(self, self._is_dark)

        # 数据状态
        self.dat_path = None
        self.tkt_path = None
        self.records = []
        self.tkt_scenes = {}
        self.filtered_indices = []
        self._dirty = False

        # 可视化模式状态
        self._vis_scene_id = 0
        self._vis_show_types = {t: True for t in [5, 10, 15, 16, 20, 110, 200]}
        self._vis_bg_pil = None
        self._vis_bg_pixmap = None
        self._vis_entities = {}
        self._vis_hit_regions = {}
        self._vis_selected = None
        self._vis_drag = None
        self._vis_edit_mode = False  # 编辑开关: 默认关闭(禁止拖动)
        self._undo_pos = None  # 单步撤销: (entity_idx, old_x, old_y)
        self._sc_grp_section_count = 0
        self._sc_grp_pending = None  # 待保存的 SC.GRP 数据 (list[bytes])，仅在保存时写入文件
        self.item_names = {}
        self._ani_jvg = None
        self._cha_jvg = None
        self._cur_jvg = None
        self._vis_display_mode = "游戏默认"
        self._vis_anim_playing = False
        self._vis_anim_timer = None
        self._vis_anim_frame = {}
        self._vis_sel_anim_active = False
        self._vis_sel_anim_timer = None
        self.defunit_recs = []
        self.defunit_next = {}
        self.defunit_entity = {}
        self.tkd_defines = []
        self.tkd_header = ''
        self.tkd_define_map = {}
        self.tkt_all = {}
        self._preview_win = None
        self._preview_step = 0
        self._preview_cmds = []
        self._current_param_idx = None
        self._current_edit_define_id = None
        self._script_dirty = False
        self._edit_debounce = None

        # 存档模式状态
        self._save_mode = False   # True = 编辑的是 sav.N 中的 TKMat 数据
        self._save_path = None    # 当前存档文件路径
        self._save_slot = 0       # 槽位号
        self._game_dir = None     # 游戏资源目录 (TKDefUnit/TKD/SC.GRP 所在目录)

        # 画布重绘防抖定时器，避免 resizeEvent 卡死主线程
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._do_resize_redraw)

        # 字段编辑组件映射
        self._edit_vars = {}  # key -> widget (canonical, 多为"全部"页持有)
        self._raw_mirrors = {}  # di -> [QLineEdit, ...] 同一字段在参数页/全部页的镜像控件
        self._type_vars = {}  # tval -> {key: widget}
        self._type_frames = {}  # tval -> QWidget
        self._active_type = None
        self._param_labels = {}
        self._all_labels = {}
        self._sched_labels = {}

        # 构建 UI
        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

    # =========== QSS 主题 ===========
    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()
        # 更新窗口标题栏颜色
        from editor_utils.window_theme import apply_godot_theme
        apply_godot_theme(self, self._is_dark)

    def _apply_theme(self):
        qss = ThemeManager.dark_qss() if self._is_dark else ThemeManager.light_qss()
        self.setStyleSheet(qss)
        self._update_path()
        self._update_entity_type_colors()
        self._update_vis_background()
        # 主题切换时，强制重绘 PIL 底图以匹配新背景色
        if hasattr(self, 'records') and self.records:
            self._vis_redraw()
        # 同步脚本编辑器语法高亮配色至当前主题
        if hasattr(self, '_script_highlighter') and self._script_highlighter:
            self._script_highlighter.set_dark(self._is_dark)
        # 同步行预览面板配色至当前主题 (行预览仅在加载 DEFINE 时渲染一次,
        # 切换主题后须重渲染, 否则保留旧主题配色 — 旧浅色 #333 落在深色背景上呈暗灰)
        if hasattr(self, 'script_preview') and self._current_edit_define_id is not None:
            self._update_line_preview()
        self._refresh_table()

    def _update_entity_type_colors(self):
        """根据当前主题更新实体列表的类型颜色"""
        if self._is_dark:
            # 深色背景: 使用明亮色彩
            colors = {0: "#AAAAAA", 5: "#2196F3", 10: "#4CAF50", 15: "#FF9800",
                      16: "#795548", 20: "#9C27B0", 110: "#E91E63", 200: "#F44336"}
        else:
            # 白色背景: 使用深色彩以保证可读性
            colors = {0: "#777777", 5: "#1565C0", 10: "#2E7D32", 15: "#E65100",
                      16: "#5D4037", 20: "#6A1B9A", 110: "#AD1457", 200: "#C62828"}
        self._entity_type_colors = {tv: QColor(cl) for tv, cl in colors.items()}

    def _update_vis_background(self):
        """设置中间预览区 QGraphicsView 的背景色, 使深色区域填满整个预览区
        (对应 v1 tk.Canvas 的 bg)。场景矩形外的空白也以此色填充。"""
        if not hasattr(self, '_vis_gview'):
            return
        # 与 editor_themes/*.qss 的 QGraphicsView background-color 一致
        bg = QColor('#1a1e27') if self._is_dark else QColor('#ffffff')
        self._vis_gview.setBackgroundBrush(bg)

    # =========== UI 构建 ===========
    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # --- Menu Bar ---
        menu_bar = self.menuBar()
        fm = menu_bar.addMenu("文件(F)")
        fm.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_dir)
        fm.addAction("加载存档 (从游戏目录)…", QKeySequence("Ctrl+Shift+O"), self._load_save_dir)
        fm.addAction("重载", self._reload)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("另存为…", self._save_as)
        fm.addSeparator()
        fm.addAction("导出场景…", self._export_scene)
        fm.addAction("导出场景为 MOD (.tksmod)…", self._export_scene_as_tksmod)
        fm.addAction("导入场景…", self._import_scene)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = menu_bar.addMenu("编辑(E)")
        em.addAction("新增记录", QKeySequence("Ctrl+N"), self._new_record)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)
        em.addSeparator()
        em.addAction("删除当前场景…", self._delete_scene)

        vm = menu_bar.addMenu("查看(V)")
        vm.addAction("统计信息", self._show_stats)

        hm = menu_bar.addMenu("帮助(H)")
        hm.addAction("导出 CSV…", self._export_csv)
        hm.addAction("字段说明", self._show_field_ref)
        hm.addAction("关于", self._show_about)

        # --- Main Splitter (三栏) ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(7)
        main_layout.addWidget(self.splitter, 1)

        # Left pane
        self._build_left_panel()
        # Center pane
        self._build_center_panel()
        # Right pane
        self._build_right_panel()

        self.splitter.setSizes([460, 640, 550])
        # 左右面板拉伸因子=0, 中间=1: 窗口放大时多余空间全归中间, 左右保持初始宽度
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)

        # Bottom path bar
        path_layout = QHBoxLayout()
        self.lbl_path = QLabel("(未加载)")
        self.lbl_cha = QLabel("Cha")
        self.lbl_ani = QLabel("Ani")
        self.lbl_cur = QLabel("Cur")
        self.lbl_sc = QLabel("SC")
        path_layout.addWidget(self.lbl_path)
        path_layout.addSpacing(20)
        for lbl in [self.lbl_cha, self.lbl_ani, self.lbl_cur, self.lbl_sc]:
            path_layout.addWidget(lbl)
            path_layout.addSpacing(10)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

        # Status bar
        self._vis_info_label = QLabel("")
        self._vis_coord_label = QLabel("")
        sb = QStatusBar()
        sb.addWidget(self._vis_info_label, 1)
        sb.addPermanentWidget(self._vis_coord_label)
        self.setStatusBar(sb)

    def _create_dock(self, title, widget_content, header_layout=None):
        """Dock 面板包裹 — 委托给 editor_utils.dock_components"""
        return create_dock(title, widget_content, header_layout)

    # =========== 左侧面板: 场景列表 + 实体列表 ===========
    def _build_left_panel(self):
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Splitter for scene list / entity list
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setHandleWidth(5)

        # Scene list
        self.scene_tree = QTreeWidget()
        self.scene_tree.setHeaderLabels(["SC#", "场景名称", "实体"])
        self.scene_tree.setColumnWidth(0, 50)
        self.scene_tree.setColumnWidth(2, 45)
        self.scene_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)  # 场景名称列自动拉伸
        self.scene_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scene_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.scene_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.scene_tree.setRootIsDecorated(False)
        self.scene_tree.setUniformRowHeights(True)
        self.scene_tree.setProperty("class", "CompactTree")
        self.scene_tree.itemSelectionChanged.connect(self._on_vis_scene_select)
        left_splitter.addWidget(self._create_dock("场景列表 (SC.GRP)", self.scene_tree))

        # Entity list: 按钮在 body 内, 不在 DockHeader
        self.entity_tree = QTreeWidget()
        self.entity_tree.setHeaderLabels(["索引", "类型", "场景", "X", "Y", "脚本", "Tick"])
        self.entity_tree.setColumnWidth(0, 50)   # 索引
        self.entity_tree.setColumnWidth(1, 85)   # 类型
        self.entity_tree.setColumnWidth(3, 45)   # X
        self.entity_tree.setColumnWidth(4, 45)   # Y
        self.entity_tree.setColumnWidth(5, 70)   # 脚本
        self.entity_tree.setColumnWidth(6, 40)   # Tick
        self.entity_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)  # 场景列自动拉伸
        self.entity_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.entity_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.entity_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.entity_tree.setRootIsDecorated(False)
        self.entity_tree.setSortingEnabled(False)
        self.entity_tree.setUniformRowHeights(True)
        self.entity_tree.setProperty("class", "CompactTree")
        self.entity_tree.itemSelectionChanged.connect(self._on_select)
        # 点击列头排序
        self.entity_tree.header().setSortIndicatorShown(True)
        self.entity_tree.header().sectionClicked.connect(self._sort_entity_by_column)
        # 表格实体类型颜色 (根据主题切换)
        self._update_entity_type_colors()

        # 实体列表面板
        ent_panel = QWidget()
        ent_panel_layout = QVBoxLayout(ent_panel)
        ent_panel_layout.setContentsMargins(0, 0, 0, 0)
        ent_panel_layout.setSpacing(0)
        # 标题栏 (DockHeader)
        ent_panel_layout.addWidget(DockHeader("实体列表"))
        # Body 区域
        ent_body = QWidget()
        ent_body.setObjectName("DockBody")
        ent_body_layout = QVBoxLayout(ent_body)
        ent_body_layout.setContentsMargins(8, 8, 8, 8)
        ent_body_layout.setSpacing(4)
        # 新增/删除 + 筛选工具栏 (新增/删除置于原搜索位置)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(2)
        btn_new = QPushButton("➕ 新增")
        btn_new.clicked.connect(self._new_record)
        filter_row.addWidget(btn_new)
        btn_del = QPushButton("🗑️ 删除")
        btn_del.clicked.connect(self._clear_current)
        filter_row.addWidget(btn_del)
        # 分隔线
        sep0 = QFrame(); sep0.setFrameShape(QFrame.VLine); sep0.setFrameShadow(QFrame.Sunken)
        filter_row.addWidget(sep0)
        filter_row.addWidget(QLabel("类型:"))
        self.filter_type = QComboBox()
        self.filter_type.addItems(["全部"] + [f"{k}-{v}" for k, v in sorted(ENTITY_TYPES.items()) if k != 0])
        self.filter_type.currentIndexChanged.connect(self._apply_filter)
        self.filter_type.setFixedWidth(120)
        filter_row.addWidget(self.filter_type)
        # 分隔线
        sep3 = QFrame(); sep3.setFrameShape(QFrame.VLine); sep3.setFrameShadow(QFrame.Sunken)
        filter_row.addWidget(sep3)
        self.show_empty_cb = QCheckBox("空槽")
        self.show_empty_cb.stateChanged.connect(self._apply_filter)
        filter_row.addWidget(self.show_empty_cb)
        self.show_global_cb = QCheckBox("全局")
        self.show_global_cb.setToolTip("显示 d1==-1 的全局实体 (不属于任何具体场景)")
        self.show_global_cb.stateChanged.connect(self._apply_filter)
        filter_row.addWidget(self.show_global_cb)
        filter_row.addStretch()
        ent_body_layout.addLayout(filter_row)
        # 状态栏
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        self.status_var.setProperty("class", "StatusHint")
        ent_body_layout.addWidget(self.status_var)
        # 实体列表
        ent_body_layout.addWidget(self.entity_tree, 1)
        ent_panel_layout.addWidget(ent_body, 1)

        left_splitter.addWidget(ent_panel)
        left_splitter.setSizes([300, 400])

        left_layout.addWidget(left_splitter)
        left_widget.setMinimumWidth(460)
        self.splitter.addWidget(left_widget)

    # =========== 中间面板: 地图预览 ===========
    def _build_center_panel(self):
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(2)

        # Top toolbar row 1
        top = QHBoxLayout()
        top.addWidget(QLabel("场景:"))
        self._vis_scene_combo = QComboBox()
        self._vis_scene_combo.setMinimumWidth(200)
        self._vis_scene_combo.currentIndexChanged.connect(self._on_vis_combo_select)
        top.addWidget(self._vis_scene_combo)
        top.addSpacing(10)
        top.addWidget(QLabel("显示:"))
        self._display_mode_combo = QComboBox()
        self._display_mode_combo.addItems(list(DISPLAY_MODES.keys()))
        self._display_mode_combo.currentIndexChanged.connect(self._on_display_mode_change)
        top.addWidget(self._display_mode_combo)
        top.addSpacing(10)
        self._vis_play_btn = QPushButton("▶️ 播放全部")
        self._vis_play_btn.setFixedWidth(80)
        self._vis_play_btn.setProperty("class", "CompactBtn")
        self._vis_play_btn.setToolTip("播放/暂停精灵动画")
        self._vis_play_btn.clicked.connect(self._vis_toggle_anim)
        top.addWidget(self._vis_play_btn)
        self._vis_sel_anim_btn = QPushButton("⏯️ 播放选中")
        self._vis_sel_anim_btn.setFixedWidth(80)
        self._vis_sel_anim_btn.setProperty("class", "CompactBtn")
        self._vis_sel_anim_btn.setToolTip("播放/暂停当前选中实体的动画")
        self._vis_sel_anim_btn.clicked.connect(self._vis_toggle_sel_anim)
        top.addWidget(self._vis_sel_anim_btn)
        top.addSpacing(10)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setFixedWidth(60)
        btn_refresh.setProperty("class", "CompactBtn")
        btn_refresh.clicked.connect(self._vis_load_scene)
        top.addWidget(btn_refresh)
        top.addSpacing(10)
        self._vis_edit_cb = QCheckBox("允许拖动")
        self._vis_edit_cb.stateChanged.connect(self._on_edit_mode_change)
        top.addWidget(self._vis_edit_cb)
        top.addStretch()
        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        top.addWidget(btn_theme)
        center_layout.addLayout(top)

        # Top toolbar row 2: type filters
        top2 = QHBoxLayout()
        top2.addWidget(QLabel("类型:"))
        self._type_filter_cbs = {}
        for tval in [5, 10, 15, 16, 20, 110, 200]:
            cb = QCheckBox(ENTITY_TYPES.get(tval, f"T{tval}"))
            cb.setChecked(True)
            cb.stateChanged.connect(self._vis_redraw)
            self._type_filter_cbs[tval] = cb
            top2.addWidget(cb)
        top2.addStretch()
        center_layout.addLayout(top2)

        # Map canvas using QGraphicsView
        self._vis_gscene = QGraphicsScene()
        self._vis_gview = QGraphicsView(self._vis_gscene)
        self._vis_gview.setRenderHint(QPainter.SmoothPixmapTransform)
        self._vis_gview.setDragMode(QGraphicsView.NoDrag)
        self._vis_gview.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self._vis_gview.setMouseTracking(True)
        # 左上角对齐 (对应 v1 的 anchor='nw'): 地图原点贴齐视口左上, 放大时多余空间留在右下
        self._vis_gview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # 深色背景填满整个预览区 (含场景矩形外的空白), 与 v1 画布 bg 一致
        self._update_vis_background()
        self._vis_gview.mousePressEvent = self._vis_canvas_click
        self._vis_gview.mouseMoveEvent = self._vis_canvas_mouse_move
        self._vis_gview.mouseReleaseEvent = self._vis_canvas_release
        self._vis_gview.wheelEvent = self._vis_canvas_wheel
        self._vis_bg_item = None  # QGraphicsPixmapItem for scene background
        center_layout.addWidget(self._vis_gview, 1)
        center_widget.setMinimumWidth(400)
        self.splitter.addWidget(center_widget)

    # =========== 右侧面板: 编辑区 ===========
    def _build_right_panel(self):
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        self.lbl_title = QLabel("未选中")
        self.lbl_title.setProperty("class", "RecordHeader")
        right_layout.addWidget(self.lbl_title)

        # Notebook (QTabWidget)
        self.notebook = QTabWidget()
        right_layout.addWidget(self.notebook, 1)

        # Tab "参数"
        self.tab_param = QWidget()
        self.tab_param_layout = QVBoxLayout(self.tab_param)
        self.tab_param_layout.setContentsMargins(0, 0, 0, 0)
        self.notebook.addTab(self.tab_param, "参数")

        # Build per-type parameter pages
        self._build_type_param_pages()

        # Tab "脚本"
        self.tab_script = QWidget()
        self.notebook.addTab(self.tab_script, "脚本")
        self._build_script_tab()

        # Tab "全部"
        self.tab_all = QWidget()
        self.notebook.addTab(self.tab_all, "全部")
        self._build_all_tab()

        # 参数页 / 全部页的镜像 QLineEdit 双向同步 (等价 v1 StringVar 互通)
        self._wire_raw_mirrors()

        # Bottom buttons
        bf = QHBoxLayout()
        btn_apply = QPushButton("应用修改")
        btn_apply.clicked.connect(self._apply_edit)
        bf.addWidget(btn_apply)
        btn_reset = QPushButton("重置")
        btn_reset.clicked.connect(self._reset_edit)
        bf.addWidget(btn_reset)
        bf.addStretch()
        btn_goto = QPushButton("跳转到空槽…")
        btn_goto.clicked.connect(self._goto_empty)
        bf.addWidget(btn_goto)
        right_layout.addLayout(bf)

        self.edit_frame = right_widget
        right_widget.setMinimumWidth(460)
        self.splitter.addWidget(right_widget)

    def _build_type_param_pages(self):
        """为每种实体类型构建独立的参数编辑页"""
        _TYPE_ORDER = [200, 10, 20, 110, 15, 16, 5]
        _SKIP_DWORDS = {
            5:  {9,24,25}|set(range(29,96)),
            10: {9,24,25,55,57,58,59}|set(range(63,71)),
            15: {9,13,24,25,28}|set(range(52,96)),
            16: {8,9,13,23,24,28,50,51,58,59}|set(range(63,71)),
            20: set(range(50,96)) - {55,64,65,66,68,80,81},
            110: {9,14,16,23,50,51}|set(range(57,96)),
            200: {23,54}|set(range(56,96)),
        }

        for tval in _TYPE_ORDER:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QWidget()
            inner_layout = QVBoxLayout(inner)
            inner_layout.setContentsMargins(4, 4, 16, 4)
            inner_layout.setSpacing(6)

            tvars = {}
            skip = _SKIP_DWORDS.get(tval, set())
            type_labels = _TYPE_LABELS.get(tval, {})

            # === 基础属性 ===
            self._build_type_basic_group(inner_layout, tvars, tval, type_labels)

            # === 显示/动画/位置 [8-28] ===
            GROUP_8_28 = []
            _seen8 = set()
            _skip_8_28 = {12, 17, 25, 26, 27}
            for fields in (BASIC_FIELDS, RUNTIME_FIELDS, POS_FIELDS, INTERACT_FIELDS, SCRIPT_FIELDS):
                for f in fields:
                    if 8 <= f[1] <= 28 and f[1] not in _seen8 and f[1] not in _skip_8_28:
                        GROUP_8_28.append(f)
                        _seen8.add(f[1])
            _order_8_28 = {13: 21.5, 15: 21.6}
            GROUP_8_28.sort(key=lambda f: _order_8_28.get(f[1], f[1]))
            GROUP_8_28 = [f for f in GROUP_8_28 if f[1] not in skip]
            if GROUP_8_28:
                self._build_field_group(inner_layout, "显示/动画/位置 [8-28]", GROUP_8_28, tvars, type_labels, 4, tval=tval)

            # === 交互/动画/物品 [50-70] ===
            GROUP_50_70 = []
            _seen50 = set()
            for fields in (INTERACT_FIELDS, RUNTIME_FIELDS, ANIM_FIELDS, ITEM_FIELDS):
                for f in fields:
                    if 50 <= f[1] <= 70 and f[1] not in _seen50:
                        GROUP_50_70.append(f)
                        _seen50.add(f[1])
            GROUP_50_70.sort(key=lambda f: f[1])
            GROUP_50_70 = [f for f in GROUP_50_70 if f[1] not in skip]
            if GROUP_50_70:
                self._build_field_group(inner_layout, "交互/动画/物品 [50-70]", GROUP_50_70, tvars, type_labels, 4, tval=tval)

            # === 音效事件 [71-95] (type=20 专用) ===
            if tval == 20 and type_labels:
                sound_events = [(di, type_labels[di][0], type_labels[di][1])
                               for di in range(71, 96) if di in type_labels and di not in skip]
                if sound_events:
                    snd_fields = [(f'snd_{di}', di, tl, tc) for di, tl, tc in sound_events]
                    self._build_field_group(inner_layout, "音效事件 [71-95]", snd_fields, tvars, type_labels, 4, tval=tval, is_sound=True)

            inner_layout.addStretch()
            scroll.setWidget(inner)
            self._type_frames[tval] = scroll
            self._type_vars[tval] = tvars

    def _make_raw_edit(self, di):
        """为 dword di 创建一个独立的 QLineEdit 并登记到镜像表。
        v2 不再共享同一 QLineEdit 控件 (一个 QWidget 只能有一个父窗口, 会被
        后续 addWidget re-parent 走, 导致其余页变空壳); 改为每页各建一个,
        构建完成后用 _wire_raw_mirrors 双向同步, 等价于 v1 的 StringVar 互通。"""
        ev = QLineEdit()
        self._raw_mirrors.setdefault(di, []).append(ev)
        return ev

    def _wire_raw_mirrors(self):
        """为每个 dword 的所有镜像 QLineEdit 接入 textChanged 双向同步。
        用 blockSignals 防回环。构建后过滤已被 Qt 回收的对象。"""
        for di in list(self._raw_mirrors):
            eds = self._raw_mirrors[di]
            # 过滤已被 Qt 回收的孤儿对象 (addWidget re-parent 后未保持强引用)
            alive = []
            for ed in eds:
                try:
                    _ = ed.text()
                    alive.append(ed)
                except RuntimeError:
                    pass
            self._raw_mirrors[di] = alive
            if len(alive) < 2:
                continue
            # 为每个控件分别创建 handler, 通过闭包捕获 src 避免 sender() 失效
            for src_ed in alive:
                def _make_handler(_src=src_ed, _eds=alive):
                    def _on_changed(txt):
                        for ed in _eds:
                            if ed is _src:
                                continue
                            if ed.text() == txt:
                                continue
                            ed.blockSignals(True)
                            ed.setText(txt)
                            ed.blockSignals(False)
                    return _on_changed
                src_ed.textChanged.connect(_make_handler())

    def _build_type_basic_group(self, parent_layout, tvars, tval, type_labels):
        """构建类型页面的基础属性组 (DockHeader + DockBody, 垂直单元格, 等宽列)"""
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0, 0, 0, 0); gl.setSpacing(0)
        gl.addWidget(DockHeader("基础属性"))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8, 8, 8, 8)
        grid = QGridLayout(); grid.setVerticalSpacing(4); grid.setHorizontalSpacing(8)

        def _cell(lbl_widget, input_widget):
            """返回 (QWidget, QVBoxLayout) — QWidget 作为 grid 单元格, 保证内部控件有父"""
            cw = QWidget()
            cell = QVBoxLayout(cw); cell.setSpacing(2); cell.setContentsMargins(0, 0, 0, 0)
            cell.addWidget(lbl_widget)
            input_widget.setMinimumHeight(24)
            cell.addWidget(input_widget)
            return cw

        # Type combobox
        lbl = QLabel("[00] 实体类型")
        lbl.setToolTip("[00] 实体类型: 5=脚本 10=出入传送 15=触发区 16=战斗区 20=事件 110=机关 200=NPC。源码: sub_405CBC")
        lbl.setProperty("class", "PropLabel")
        cb = QComboBox()
        cb.addItems([f"{k}-{v}" for k, v in sorted(ENTITY_TYPES.items())])
        tvars['type'] = cb
        wrapper = QFrame(); wrapper.setObjectName("FakeInputBox")
        wl = QHBoxLayout(wrapper); wl.setContentsMargins(0, 0, 0, 0); wl.addWidget(cb)
        grid.addWidget(_cell(lbl, wrapper), 0, 0, Qt.AlignTop)

        # Scene ID
        lbl2 = QLabel("[01] 场景ID")
        lbl2.setToolTip("[01] 所属场景 (-1=全局)。TKT_ID = scene_id + 300。源码: sub_405CBC")
        lbl2.setProperty("class", "PropLabel")
        ev = self._make_raw_edit(1)
        tvars['scene_id'] = ev
        wrapper2 = QFrame(); wrapper2.setObjectName("FakeInputBox")
        wl2 = QHBoxLayout(wrapper2); wl2.setContentsMargins(0, 0, 0, 0); wl2.addWidget(ev)
        scene_lbl = QLabel(""); scene_lbl.setProperty("class", "ExtraPreviewText")
        wl2.addWidget(scene_lbl)
        tvars['_scene_label'] = scene_lbl
        grid.addWidget(_cell(lbl2, wrapper2), 0, 1, Qt.AlignTop)

        # Flags
        lbl3 = QLabel("[02] 标志位")
        lbl3.setToolTip("[02] 位域。bit0=启用 bit1=可见 bit2=可交互 bit3=提示 bit4=忙碌 bit5=恢复 bit8=已拾取 bit16=动画循环")
        lbl3.setProperty("class", "PropLabel")
        ev2 = self._make_raw_edit(2)
        tvars['flags'] = ev2
        wrapper3 = QFrame(); wrapper3.setObjectName("FakeInputBox")
        wl3 = QHBoxLayout(wrapper3); wl3.setContentsMargins(0, 0, 0, 0); wl3.addWidget(ev2)
        grid.addWidget(_cell(lbl3, wrapper3), 0, 2, Qt.AlignTop)

        # Flag checkboxes
        bit_attrs = [
            ("_bit_enable", "启用", 1), ("_bit_visible", "显示", 2),
            ("_bit_pickable", "可交互", 4), ("_bit_hint", "提示", 8),
            ("_bit_busy", "忙碌", 0x10), ("_bit_resume", "恢复", 0x20),
            ("_bit_taken", "已拾取", 0x100), ("_bit_animloop", "循环动画", 0x10000),
            ("_bit_ev12", "事件标志A", 0x1000), ("_bit_ev13", "事件标志B", 0x2000),
            ("_bit_ev14", "事件标志C", 0x4000),
        ]
        bit_vars = {}
        bit_cbs = []
        flags_frame = QWidget()
        flags_grid = QGridLayout(flags_frame)
        flags_grid.setContentsMargins(0, 0, 0, 0)
        flags_grid.setSpacing(2)
        for bi, (attr, text, mask) in enumerate(bit_attrs):
            cb_bit = QCheckBox(text)
            cb_bit.setToolTip(f"{attr}: mask=0x{mask:X}")
            bit_vars[attr] = cb_bit
            bit_cbs.append(cb_bit)
            r, c = divmod(bi, 4)
            flags_grid.addWidget(cb_bit, r, c)

        tvars['_bit_vars'] = bit_vars
        tvars['_bit_cbs'] = bit_cbs
        tvars['_bit_event_idxs'] = [i for i, (attr, _, _) in enumerate(bit_attrs)
                                     if attr in ('_bit_ev12', '_bit_ev13', '_bit_ev14')]

        # Wire up flag<->entry sync
        def _on_flags_changed(*_args):
            try:
                flags = int(ev2.text() or 0)
            except ValueError:
                return
            for attr, _text, mask in bit_attrs:
                bit_vars[attr].setChecked((flags & mask) != 0)

        def _on_cb_changed(*_args):
            flags = 0
            for attr, _text, mask in bit_attrs:
                if bit_vars[attr].isChecked():
                    flags |= mask
            ev2.setText(str(flags))

        ev2.textChanged.connect(_on_flags_changed)
        for bv in bit_vars.values():
            bv.stateChanged.connect(_on_cb_changed)

        grid.addWidget(flags_frame, 1, 0, 1, 3)

        for c in range(3):
            grid.setColumnStretch(c, 1)
        bl.addLayout(grid); gl.addWidget(body); parent_layout.addWidget(grp)

    def _build_field_group(self, parent_layout, title, fields, tvars, type_labels, cols, tval=0, is_sound=False):
        """构建通用字段组 (DockHeader + DockBody, 垂直单元格, 等宽列)"""
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0, 0, 0, 0); gl.setSpacing(0)
        gl.addWidget(DockHeader(title))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8, 8, 8, 8)
        grid = QGridLayout(); grid.setVerticalSpacing(4); grid.setHorizontalSpacing(8)

        for fi, field_tuple in enumerate(fields):
            key, di, label, cmt = field_tuple
            r, c = divmod(fi, cols)

            # Label with type-specific override
            if di in type_labels:
                tl, tc = type_labels[di]
                lbl_text = f"[{di:02d}] {tl}"
                tip = f"[{di:02d}] {tl}: {tc}" if tc else None
            else:
                lbl_text = f"[{di:02d}] {label}"
                tip = f"[{di:02d}] {cmt}" if cmt else None

            lbl = QLabel(lbl_text)
            if tip:
                lbl.setToolTip(tip)
            lbl.setProperty("class", "PropLabel")
            if di in type_labels:
                lbl.setProperty("class", "TypeFieldLabel")

            # Input widget (组合框字段不创建 QLineEdit 镜像, 由"全部"页 raw_N 充当存储,
            # 经 _sync_type_cb_to_raw 单向同步; 文本类字段各自建镜像并双向同步)
            ev = None

            # Check if this needs a combobox
            if key == 'anim_set':
                cb = QComboBox()
                cb.addItems([f"{k}-{v}" for k, v in ANIM_SETS.items()])
                tvars[key] = cb
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(cb)
                # Sync combobox to raw entry
                cb.currentIndexChanged.connect(lambda _, d=di, _cb=cb: self._sync_type_cb_to_raw(tvars, d, _cb))
            elif key == 'blend_mode':
                cb = QComboBox()
                cb.addItems(["0-正常", "1-染色", "2-加法发光", "3-减法压暗", "4-亮度alpha", "5-水平翻转"])
                tvars[key] = cb
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(cb)
                cb.currentIndexChanged.connect(lambda _, d=di, _cb=cb: self._sync_type_cb_to_raw(tvars, d, _cb))
            elif key == 'shadow_frame':
                cb = QComboBox()
                cb.addItems(["0-无阴影", "1-小阴影(39×23)", "2-大阴影(65×33)"])
                tvars[key] = cb
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(cb)
                cb.currentIndexChanged.connect(lambda _, d=di, _cb=cb: self._sync_type_cb_to_raw(tvars, d, _cb))
            elif key == 'cursor_id':
                cb = QComboBox()
                cb.addItems([f"{k}-{v}" for k, v in sorted(_CURSOR_BLOCKS.items())])
                tvars[key] = cb
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(cb)
                cb.currentIndexChanged.connect(lambda _, d=di, _cb=cb: self._sync_type_cb_to_raw(tvars, d, _cb))
            elif key == 'dialog_color':
                # 对话颜色选择器: FCOLOR 1-32 调色板
                dc_ev = self._make_raw_edit(di)
                tvars[key] = dc_ev
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.setSpacing(2)
                wl.addWidget(dc_ev, 1)
                # Color swatch
                dc_swatch = QFrame()
                dc_swatch.setFixedSize(20, 20)
                dc_swatch.setProperty("class", "ColorSwatch")
                wl.addWidget(dc_swatch)
                tvars['_dialog_color_swatch'] = dc_swatch
                # Picker button
                dc_btn = QPushButton("选色")
                dc_btn.setFixedWidth(40)
                dc_btn.setCursor(Qt.PointingHandCursor)
                def _make_dc_picker(_swatch=dc_swatch, _ev=dc_ev):
                    def _pick():
                        menu = QMenu(self)
                        for i in range(32):
                            hc = GAME_COLORS.get(i + 1, '#000')
                            px = QPixmap(16, 16)
                            px.fill(QColor(hc))
                            act = menu.addAction(QIcon(px), f"  {i:2d}  FCOLOR({i+1:2d})")
                            act.setData(i)
                        chosen = menu.exec(dc_btn.mapToGlobal(QPoint(0, dc_btn.height())))
                        if chosen:
                            val = chosen.data()
                            _ev.setText(str(val))
                            _swatch.setStyleSheet(f"background-color: {GAME_COLORS.get(val+1,'#000')};")
                    return _pick
                dc_btn.clicked.connect(_make_dc_picker())
                wl.addWidget(dc_btn)
                tvars['_dialog_color_btn'] = dc_btn
            elif key == 'dir_mask' and tval in (10, 15):
                # 方向掩码 checkbox 网格 (8个朝向) — 垂直布局: 数值输入在上, checkbox 在下
                dm_ev = self._make_raw_edit(di)
                dm_ev.setMaximumWidth(80)
                tvars[key] = dm_ev
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl_wrap = QVBoxLayout(wrapper)
                wl_wrap.setContentsMargins(4, 2, 4, 2)
                wl_wrap.setSpacing(2)
                wl_wrap.addWidget(dm_ev)
                # Direction checkboxes grid: 4行×2列
                dir_frame = QWidget()
                dir_grid = QGridLayout(dir_frame)
                dir_grid.setContentsMargins(0, 0, 0, 0)
                dir_grid.setSpacing(1)
                dir_labels = ["上", "右上", "右", "右下", "下", "左下", "左", "左上"]
                dir_bv = {}
                for bit_i in range(8):
                    bv_cb = QCheckBox(dir_labels[bit_i])
                    bv_cb.setProperty("class", "DirCheckBox")
                    dir_bv[bit_i] = bv_cb
                    r2, c2 = divmod(bit_i, 2)
                    dir_grid.addWidget(bv_cb, r2, c2)
                def _make_dir_sync(_ev=dm_ev, _dir_bv=dir_bv):
                    def _on_dir(*_a):
                        mask = sum((1 << i) for i, cb in _dir_bv.items() if cb.isChecked())
                        _ev.blockSignals(True)
                        _ev.setText(str(mask))
                        _ev.blockSignals(False)
                    return _on_dir
                dir_sync_fn = _make_dir_sync()
                for bv_cb in dir_bv.values():
                    bv_cb.stateChanged.connect(dir_sync_fn)
                tvars["_dir_bv"] = dir_bv
                wl_wrap.addWidget(dir_frame)
            else:
                ev = self._make_raw_edit(di)
                tvars[key] = ev
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(ev)

            cell_widget = QWidget()
            cell = QVBoxLayout(cell_widget); cell.setSpacing(2); cell.setContentsMargins(0, 0, 0, 0)
            cell.addWidget(lbl)
            cell.addWidget(wrapper)
            # Hint label — 输入框外部下方, 与输入框左边线对齐
            if key == 'hint_id':
                hl = QLabel("")
                hl.setProperty("class", "FieldHint")
                hl.setWordWrap(True)
                cell.addWidget(hl)
                tvars['_hint_label'] = hl
            # Item name label — type=110 物品ID输入框下方 (显示方式参考 hint_id)
            # 注意: d53/d57/d61 在 GROUP_50_70 中已被 ANIM/RUNTIME 的 dir_mode/saved_y/alt_tele_y
            # 抢先占用 (按 di 去重), key 不会是 item_gN_id, 故按 di 判定 (与 mat_editor.py 一致)
            if tval == 110 and di in (53, 57, 61):
                _item_lbl_key = {53: '_item_g1_id_label', 57: '_item_g2_id_label', 61: '_item_g3_id_label'}[di]
                il = QLabel("")
                il.setProperty("class", "FieldHint")
                il.setWordWrap(True)
                cell.addWidget(il)
                tvars[_item_lbl_key] = il
            wrapper.setMinimumHeight(24)
            grid.addWidget(cell_widget, r, c, Qt.AlignTop)

        # 所有列等宽
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        # 填充末行空白占位, 防止列宽不均
        if fields:
            last_row_count = len(fields) % cols
            if last_row_count != 0:
                last_row = len(fields) // cols
                for c in range(last_row_count, cols):
                    grid.addWidget(QWidget(), last_row, c)

        # grid 必须关联父 QWidget, 否则内部 widget 无父 → 被 GC 回收
        grid_widget = QWidget()
        grid_widget.setLayout(grid)
        bl.addWidget(grid_widget); gl.addWidget(body); parent_layout.addWidget(grp)

    def _sync_type_cb_to_raw(self, tvars, di, cb_widget):
        """类型页面 Combobox 值同步到 raw_N"""
        try:
            v = int(cb_widget.currentText().split('-')[0])
            rk = f'raw_{di}'
            if rk in self._edit_vars:
                self._edit_vars[rk].setText(str(v))
        except ValueError:
            pass

    # =========== 脚本标签页 ===========
    def _build_script_tab(self):
        """构建脚本编辑标签页"""
        layout = QVBoxLayout(self.tab_script)
        layout.setContentsMargins(4, 4, 4, 4)

        # Script splitter (vertical)
        script_splitter = QSplitter(Qt.Vertical)

        # Top: 脚本调度信息 + DefUnit链列表
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 调度信息
        sched_group = QFrame()
        sched_group.setObjectName("PreviewFrame")
        sched_layout = QGridLayout(sched_group)
        sched_layout.setContentsMargins(8, 8, 8, 8)
        sched_layout.setSpacing(4)

        sched_items = [
            ('enabled', '启用', 'flags bit0=启用'),
            ('pickable', '可交互', 'flags bit2=可交互'),
            ('tick', 'Tick周期', 'd4=Tick'),
            ('timer', '定时器', 'd3=定时器'),
            ('chain_a', 'A链(自动)', 'DEFINE链A = Tick自动执行'),
            ('chain_b', 'B链(触发)', 'DEFINE链B = 触发执行'),
            ('chain_c', 'C链(保留)', 'DEFINE链C = 保留链'),
            ('trigger', '触发方式', '基于实体类型'),
        ]
        for ri, (key, label, tip) in enumerate(sched_items):
            r, c = divmod(ri, 4)
            lbl = QLabel(f"{label}:")
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(tip)
            val = QLabel("")
            val.setProperty("class", "ExtraPreviewText")
            sched_layout.addWidget(lbl, r, c * 2)
            sched_layout.addWidget(val, r, c * 2 + 1)
            self._sched_labels[key] = val
        top_layout.addWidget(sched_group)

        # DefUnit chain list
        chain_toolbar = QHBoxLayout()
        for text, chain in [("➕ A链", "A"), ("➕ B链", "B"), ("➕ C链", "C")]:
            btn = QPushButton(text)
            btn.setFixedWidth(65)
            btn.setProperty("class", "CompactBtn")
            btn.clicked.connect(lambda _, c=chain: self._add_chain_entry(c))
            chain_toolbar.addWidget(btn)
        btn_del_chain = QPushButton("🗑️ 删除")
        btn_del_chain.setFixedWidth(65)
        btn_del_chain.setProperty("class", "CompactBtn")
        btn_del_chain.clicked.connect(self._delete_chain_entry)
        chain_toolbar.addWidget(btn_del_chain)
        btn_refr = QPushButton("🔄 刷新")
        btn_refr.setFixedWidth(65)
        btn_refr.setProperty("class", "CompactBtn")
        btn_refr.clicked.connect(self._refresh_chain_list)
        chain_toolbar.addWidget(btn_refr)
        chain_toolbar.addStretch()
        self.chain_info_lbl = QLabel("")
        self.chain_info_lbl.setProperty("class", "PropLabel")
        chain_toolbar.addWidget(self.chain_info_lbl)
        top_layout.addLayout(chain_toolbar)

        self.chain_tree = QTreeWidget()
        self.chain_tree.setHeaderLabels(["子场景", "序号", "DefUnit#", "DEFINE ID", "f0", "标记"])
        self.chain_tree.setColumnWidth(0, 60)
        self.chain_tree.setColumnWidth(1, 35)
        self.chain_tree.setColumnWidth(2, 55)
        self.chain_tree.setColumnWidth(3, 70)
        self.chain_tree.setColumnWidth(4, 35)
        self.chain_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.chain_tree.setRootIsDecorated(False)
        self.chain_tree.itemSelectionChanged.connect(self._on_chain_select)
        top_layout.addWidget(self.chain_tree, 1)

        script_splitter.addWidget(top_widget)

        # Bottom: 脚本编辑器 + 预览
        bot_widget = QWidget()
        bot_layout = QVBoxLayout(bot_widget)
        bot_layout.setContentsMargins(0, 0, 0, 0)

        # Script toolbar
        stb = QHBoxLayout()
        self.script_info_lbl = QLabel("(未选中 DEFINE)")
        self.script_info_lbl.setProperty("class", "PropLabel")
        stb.addWidget(self.script_info_lbl, 1)
        btn_preview = QPushButton("▶ 预览")
        btn_preview.setFixedWidth(70)
        btn_preview.setToolTip("预览当前脚本执行流程")
        btn_preview.clicked.connect(self._preview_script)
        stb.addWidget(btn_preview)
        bot_layout.addLayout(stb)

        # Editor + preview (horizontal splitter)
        editor_splitter = QSplitter(Qt.Horizontal)

        # Left: Script editor (CodeEditor)
        self.script_text = CodeEditor()
        self.script_text.setFont(QFont("Consolas", 10))
        self.script_text.setTabStopDistance(40)
        self.script_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.script_text.textChanged.connect(self._on_script_edit)
        # 语法高亮器 (逻辑对应 mat_editor.py _apply_syntax_highlight)
        self._script_highlighter = ScriptSyntaxHighlighter(self.script_text.document(), self._is_dark)
        editor_splitter.addWidget(self.script_text)

        # Right: Line preview
        self.script_preview = QPlainTextEdit()
        self.script_preview.setFont(QFont("Consolas", 10))
        self.script_preview.setReadOnly(True)
        self.script_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor_splitter.addWidget(self.script_preview)

        editor_splitter.setSizes([400, 400])
        bot_layout.addWidget(editor_splitter, 1)

        script_splitter.addWidget(bot_widget)
        script_splitter.setSizes([350, 400])
        layout.addWidget(script_splitter)

        # State
        self.script_text.setReadOnly(True)
        self._disable_scroll_sync = False

        # 滚动同步: 编辑器 <-> 行预览
        self._script_sb = self.script_text.verticalScrollBar()
        self._preview_sb = self.script_preview.verticalScrollBar()
        def _on_editor_scroll(val, _ps=self._preview_sb, _es=self._script_sb):
            if not self._disable_scroll_sync:
                ratio = val / max(1, _es.maximum())
                _ps.setValue(int(ratio * max(1, _ps.maximum())))
        def _on_preview_scroll(val, _ps=self._preview_sb, _es=self._script_sb):
            if not self._disable_scroll_sync:
                ratio = val / max(1, _ps.maximum())
                _es.setValue(int(ratio * max(1, _es.maximum())))
        self._script_sb.valueChanged.connect(_on_editor_scroll)
        self._preview_sb.valueChanged.connect(_on_preview_scroll)

    # =========== 全部标签页 ===========
    def _build_all_tab(self):
        """Tab '全部': 按 d0~d95 顺序展示全部 96 个字段"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QGridLayout(inner)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(4, 4, 4, 4)

        known = {}
        for fields in (BASIC_FIELDS, FLAG_FIELDS, POS_FIELDS, ANIM_FIELDS, SCRIPT_FIELDS, INTERACT_FIELDS, RUNTIME_FIELDS):
            for name, di, label, cmt in fields:
                known[di] = (name, label, cmt)

        for di in range(96):
            r, c = divmod(di, 4)
            if di in known:
                name, label, cmt = known[di]
                key = f'raw_{di}'
                lbl_text = f"[{di:02d}] {label}"
            else:
                key = f'd{di}'
                label = f'd{di}'
                cmt = ""
                lbl_text = f"[{di:02d}] d{di}"

            lbl = QLabel(lbl_text)
            lbl.setProperty("class", "PropLabel")
            if cmt:
                lbl.setToolTip(f"[{di:02d}] {cmt}")

            # "全部"页为每个字段创建独立 QLineEdit 并登记镜像。
            # canonical _edit_vars[key] 指向"全部"页控件; 参数页镜像双向同步。
            ev = self._make_raw_edit(di)
            self._edit_vars[key] = ev
            ev.setMaximumWidth(80)

            inner_layout.addWidget(lbl, r, c * 2, Qt.AlignRight | Qt.AlignVCenter)
            inner_layout.addWidget(ev, r, c * 2 + 1)
            self._all_labels[di] = lbl

        scroll.setWidget(inner)
        layout = QVBoxLayout(self.tab_all)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    # =========== 编辑控件启用/禁用 ===========
    def _set_edit_enabled(self, en):
        self.edit_frame.setEnabled(en)



    # =========== 路径更新 ===========
    def _get_game_dir(self):
        """获取游戏资源目录 (TKMat.Dat/SC.GRP/JVG 等所在目录)。
        存档模式下返回 self._game_dir，普通模式返回 dat_path 的父目录。"""
        if self._save_mode and self._game_dir:
            return self._game_dir
        return os.path.dirname(self.dat_path) if self.dat_path else ''

    def _update_path(self):
        if not self.dat_path:
            self.lbl_path.setText("(未加载)")
            self.lbl_path.setProperty("status", "missing")
        elif not os.path.exists(self.dat_path):
            self.lbl_path.setText(f"(不存在){self.dat_path}")
            self.lbl_path.setProperty("status", "missing")
        else:
            self.lbl_path.setText(self.dat_path)
            self.lbl_path.setProperty("status", "loaded")
        self.lbl_path.style().unpolish(self.lbl_path)
        self.lbl_path.style().polish(self.lbl_path)

        for lbl, jvg, name in [(self.lbl_cha, self._cha_jvg, "Cha.JVG"),
                                (self.lbl_ani, self._ani_jvg, "Ani.JVG"),
                                (self.lbl_cur, self._cur_jvg, "Cur.JVG")]:
            if jvg is not None:
                lbl.setText(f"{name}✓")
                lbl.setProperty("status", "loaded")
            elif self.dat_path and os.path.exists(self.dat_path):
                lbl.setText(f"{name}✗")
                lbl.setProperty("status", "missing")
            else:
                lbl.setText(name)
                lbl.setProperty("status", "unloaded")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

        if self._sc_grp_section_count > 0:
            self.lbl_sc.setText(f"SC.GRP✓({self._sc_grp_section_count})")
            self.lbl_sc.setProperty("status", "loaded")
        elif self.dat_path and os.path.exists(self.dat_path):
            self.lbl_sc.setText("SC.GRP✗")
            self.lbl_sc.setProperty("status", "missing")
        else:
            self.lbl_sc.setText("SC.GRP")
            self.lbl_sc.setProperty("status", "unloaded")
        self.lbl_sc.style().unpolish(self.lbl_sc)
        self.lbl_sc.style().polish(self.lbl_sc)

    # =========== 筛选/列表 ===========
    def _apply_filter(self):
        ftype = self.filter_type.currentText()
        show_empty = self.show_empty_cb.isChecked()
        show_global = self.show_global_cb.isChecked()
        sid = self._vis_scene_id
        ftype_val = int(ftype.split('-')[0]) if ftype and ftype != "全部" else None
        self.filtered_indices = []
        for rec in self.records:
            if is_empty(rec):
                if not show_empty:
                    continue
            else:
                # 按当前选中场景联动筛选; 全局实体(d1==-1)仅在勾选「全局」时显示
                if rec['d1'] != sid and not (show_global and rec['d1'] == -1):
                    continue
                if ftype_val is not None and rec['d0'] != ftype_val:
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()

    def _refresh_table(self):
        sel_idx = None
        sel = self.entity_tree.selectedItems()
        if sel:
            sel_idx = int(sel[0].text(0))

        # 性能关键: 禁用排序+信号+更新, 批量添加
        self.entity_tree.setUpdatesEnabled(False)
        self.entity_tree.blockSignals(True)
        self.entity_tree.setSortingEnabled(False)
        self.entity_tree.clear()

        # 限制显示数量，避免实例化过多 QTreeWidgetItem 对象
        DISPLAY_LIMIT = 500
        show_indices = self.filtered_indices[:DISPLAY_LIMIT]

        # 批量构建所有 item 后一次性添加
        items = []
        for idx in show_indices:
            rec = self.records[idx]
            tval = rec['d0']
            sname = scene_name(self.tkt_scenes, rec['d1'])
            script_lbl, tick_lbl = get_script_info(rec)
            vals = [str(idx), f"{tval}-{ENTITY_TYPES.get(tval, '未知')}", sname,
                    str(rec['d10']), str(rec['d11']), script_lbl, tick_lbl]
            item = QTreeWidgetItem(vals)
            # Color by type
            color = self._entity_type_colors.get(tval)
            if color:
                for c in range(7):
                    item.setForeground(c, color)
            items.append(item)

        self.entity_tree.addTopLevelItems(items)

        # Restore selection
        if sel_idx is not None:
            for i in range(self.entity_tree.topLevelItemCount()):
                item = self.entity_tree.topLevelItem(i)
                if item and int(item.text(0)) == sel_idx:
                    self.entity_tree.setCurrentItem(item)
                    break

        self.entity_tree.setUpdatesEnabled(True)
        self.entity_tree.setSortingEnabled(True)
        self.entity_tree.blockSignals(False)

        if not self.entity_tree.selectedItems():
            self._current_param_idx = None
            self.lbl_title.setText("未选中")
            self._clear_form()

        # 截断提示
        if len(self.filtered_indices) > DISPLAY_LIMIT:
            self._vis_info_label.setText(f"列表已截断显示前 {DISPLAY_LIMIT}/{len(self.filtered_indices)} 条，使用筛选缩小范围")

    def _sort_entity_by_column(self, col):
        """点击列头排序实体列表"""
        # 列: 索引(0) 类型(1) 场景(2) X(3) Y(4) 脚本(5) Tick(6)
        key_map = {0: 'index', 1: 'd0', 2: 'd1', 3: 'd10', 4: 'd11', 6: 'd4'}
        key = key_map.get(col)
        if key is None:
            return  # 脚本/Tick 列不支持排序
        # 切换排序方向
        current_order = self.entity_tree.header().sortIndicatorOrder()
        reverse = (current_order == Qt.DescendingOrder)
        # 对 filtered_indices 排序并刷新
        self.filtered_indices.sort(
            key=lambda i: self.records[i].get(key, 0) if isinstance(self.records[i].get(key, 0), (int, float)) else 0,
            reverse=reverse)
        self._refresh_table()

    # =========== 选择事件 ===========
    def _on_select(self):
        sel = self.entity_tree.selectedItems()
        if not sel:
            self.lbl_title.setText("未选中")
            self._clear_form()
            return
        idx = int(sel[0].text(0))
        self._current_param_idx = idx
        rec = self.records[idx]
        self._show_record(rec)
        # Sync highlight on map
        if rec['d1'] == self._vis_scene_id:
            self._vis_selected = idx
            self._vis_redraw()
            tname = ENTITY_TYPES.get(rec['d0'], '?')
            self._vis_info_label.setText(f"选中: #{idx} [{tname}] 坐标({rec['d10']},{rec['d11']})")

    # =========== 场景选择 ===========
    def _on_vis_scene_select(self):
        sel = self.scene_tree.selectedItems()
        if not sel:
            return
        sid = int(sel[0].text(0))
        self._vis_scene_id = sid
        # Sync combo
        for i in range(self._vis_scene_combo.count()):
            if self._vis_scene_combo.itemText(i).startswith(f"{sid}:"):
                self._vis_scene_combo.setCurrentIndex(i)
                break
        self._vis_stop_anim()
        self._vis_load_scene()
        self._apply_filter()

    def _on_vis_combo_select(self):
        val = self._vis_scene_combo.currentText()
        try:
            sid = int(val.split(':')[0])
        except ValueError:
            return
        self._vis_scene_id = sid
        self._vis_stop_anim()
        self._vis_load_scene()
        self._apply_filter()

    def _sync_entity_list_select(self, idx):
        for i in range(self.entity_tree.topLevelItemCount()):
            item = self.entity_tree.topLevelItem(i)
            if item and int(item.text(0)) == idx:
                self.entity_tree.setCurrentItem(item)
                self.entity_tree.scrollToItem(item)
                return True
        return False

    # =========== 显示记录 ===========
    def _show_record(self, rec):
        idx = rec['index']
        tval = rec['d0']
        tname = ENTITY_TYPES.get(tval, f"未知({tval})")
        sname = scene_name(self.tkt_scenes, rec['d1'])
        self.lbl_title.setText(f"实体 #{idx} [{tname}] {sname} ({rec['d10']},{rec['d11']})")

        BLEND_MODES = {0: "正常", 1: "染色", 2: "加法发光", 3: "减法压暗", 4: "亮度alpha", 5: "水平翻转"}
        SHADOW_LABELS = {0: "无阴影", 1: "小阴影(39×23)", 2: "大阴影(65×33)"}

        # Fill all 96 raw fields
        for di in range(96):
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                w = self._edit_vars.get(key)
                if isinstance(w, QLineEdit):
                    w.setText(str(rec[f'd{di}']))

        # Scene label
        sl = self._edit_vars.get('_scene_label')
        if isinstance(sl, QLabel):
            sl.setText(sname)

        # Hint label
        hl = self._edit_vars.get('_hint_label')
        if isinstance(hl, QLabel):
            hid = rec['d23']
            hl.setText("" if hid == 0 else self.tkt_scenes.get(hid, ""))

        # Item name labels
        for key, di in [('_item_g1_id_label', 53), ('_item_g2_id_label', 57), ('_item_g3_id_label', 61)]:
            lbl = self._edit_vars.get(key)
            if isinstance(lbl, QLabel):
                item_id = rec[f'd{di}']
                if item_id and item_id in self.item_names:
                    lbl.setText(self.item_names[item_id])
                elif item_id:
                    lbl.setText(f"物品 #{item_id}")
                else:
                    lbl.setText("")

        # Switch to correct type page
        self._update_param_labels(tval)

        # Fill active type page
        if tval in self._type_vars:
            tvars = self._type_vars[tval]
            for key, di, label, cmt in ALL_EDIT_FIELDS:
                val = rec[f'd{di}']
                w = tvars.get(key)
                if isinstance(w, QComboBox):
                    if key == 'type':
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                    elif key == 'anim_set':
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                    elif key == 'blend_mode':
                        bm = BLEND_MODES.get(val, '未知')
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                    elif key == 'shadow_frame':
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                    elif key == 'cursor_id':
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                elif isinstance(w, QLineEdit):
                    w.setText(str(val))

            for key, di, label, cmt in RUNTIME_FIELDS:
                w = tvars.get(key)
                if isinstance(w, QLineEdit):
                    w.setText(str(rec[f'd{di}']))

            # Scene label
            sl2 = tvars.get('_scene_label')
            if isinstance(sl2, QLabel):
                sl2.setText(sname)
            # Hint label
            hl2 = tvars.get('_hint_label')
            if isinstance(hl2, QLabel):
                hid = rec['d23']
                hl2.setText("" if hid == 0 else self.tkt_scenes.get(hid, ""))
            # Item labels
            for key, di in [('_item_g1_id_label', 53), ('_item_g2_id_label', 57), ('_item_g3_id_label', 61)]:
                lbl = tvars.get(key)
                if isinstance(lbl, QLabel):
                    item_id = rec[f'd{di}']
                    if item_id and item_id in self.item_names:
                        lbl.setText(self.item_names[item_id])
                    elif item_id:
                        lbl.setText(f"物品 #{item_id}")
                    else:
                        lbl.setText("")

            # Flag checkboxes
            flags = rec['d2']
            bit_vars = tvars.get('_bit_vars')
            if bit_vars:
                for attr, mask in [("_bit_enable", 1), ("_bit_visible", 2), ("_bit_pickable", 4),
                                    ("_bit_hint", 8), ("_bit_busy", 0x10), ("_bit_resume", 0x20),
                                    ("_bit_taken", 0x100), ("_bit_animloop", 0x10000),
                                    ("_bit_ev12", 0x1000), ("_bit_ev13", 0x2000), ("_bit_ev14", 0x4000)]:
                    cb = bit_vars.get(attr)
                    if cb:
                        cb.blockSignals(True)
                        cb.setChecked((flags & mask) != 0)
                        cb.blockSignals(False)

            # Dialog color swatch update
            dc_swatch = tvars.get('_dialog_color_swatch')
            if dc_swatch and isinstance(dc_swatch, QFrame):
                dc_val = rec['d28']
                dc_swatch.setStyleSheet(
                    f"background-color: {GAME_COLORS.get(dc_val + 1, '#000')};")

            # Direction mask checkboxes update
            dir_bv = tvars.get('_dir_bv')
            if dir_bv:
                d51_val = rec['d51']
                for bit_i in dir_bv:
                    dir_bv[bit_i].blockSignals(True)
                    dir_bv[bit_i].setChecked((d51_val & (1 << bit_i)) != 0)
                    dir_bv[bit_i].blockSignals(False)

            # Event flag checkbox visibility (bit12/13/14 only for type=20/200)
            self._update_type_flags_visibility(tvars, tval)

        # Update all tab labels
        self._update_all_tab_labels(tval)
        # Refresh chain list
        self._refresh_chain_list()
        # Update sched info
        self._update_sched_info(rec)

    def _update_param_labels(self, tval):
        """Switch to the correct type parameter page"""
        # Hide current
        if self._active_type and self._active_type in self._type_frames:
            self._type_frames[self._active_type].setVisible(False)
            # Remove from layout
            self.tab_param_layout.removeWidget(self._type_frames[self._active_type])
        # Show target
        if tval in self._type_frames:
            self.tab_param_layout.addWidget(self._type_frames[tval])
            self._type_frames[tval].setVisible(True)
            self._active_type = tval

    def _update_all_tab_labels(self, tval):
        """Update '全部' tab labels based on entity type"""
        type_labels = _TYPE_LABELS.get(tval, {})
        known = {}
        for fields in (BASIC_FIELDS, FLAG_FIELDS, POS_FIELDS, ANIM_FIELDS, ITEM_FIELDS, SCRIPT_FIELDS, INTERACT_FIELDS, RUNTIME_FIELDS):
            for name, di, label, cmt in fields:
                known[di] = (name, label, cmt)
        for di in range(96):
            if di not in self._all_labels:
                continue
            lbl = self._all_labels[di]
            if di in type_labels:
                tl, tc = type_labels[di]
                lbl.setText(f"[{di:02d}] {tl}")
                lbl.setProperty("class", "TypeFieldLabel")
            elif di in known:
                name, label, cmt = known[di]
                lbl.setText(f"[{di:02d}] {label}")
                lbl.setProperty("class", "PropLabel")
            else:
                lbl.setText(f"[{di:02d}] d{di}")
                lbl.setProperty("class", "UnknownFieldLabel")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _update_type_flags_visibility(self, tvars, tval):
        """根据实体类型显示/隐藏事件标志 checkbox (bit12/13/14)"""
        bit_event_idxs = tvars.get('_bit_event_idxs', [])
        bit_cbs = tvars.get('_bit_cbs', [])
        show = tval in (20, 200)
        for i in bit_event_idxs:
            if i < len(bit_cbs):
                bit_cbs[i].setVisible(show)

    def _update_flags_visibility(self, tval):
        """根据实体类型更新全局 flags 事件标志可见性"""
        # For type pages
        if tval in self._type_vars:
            self._update_type_flags_visibility(self._type_vars[tval], tval)

    def _clear_form(self):
        for key, var in self._edit_vars.items():
            if isinstance(var, QLineEdit):
                var.clear()
            elif isinstance(var, QComboBox):
                var.setCurrentIndex(0)
        for lbl_key in ('_scene_label', '_hint_label', '_item_g1_id_label', '_item_g2_id_label', '_item_g3_id_label'):
            lbl = self._edit_vars.get(lbl_key)
            if isinstance(lbl, QLabel):
                lbl.setText("")
        # Clear type pages
        for tval in self._type_vars:
            tvars = self._type_vars[tval]
            for key, var in tvars.items():
                if isinstance(var, QLineEdit):
                    var.clear()
                elif isinstance(var, QComboBox):
                    var.setCurrentIndex(0)
                elif isinstance(var, QCheckBox):
                    var.setChecked(False)
        # Clear script tab
        self.script_text.setReadOnly(False)
        self.script_text.blockSignals(True)
        self.script_text.clear()
        self.script_text.blockSignals(False)
        self.script_text.setReadOnly(True)
        self.script_preview.clear()
        self.chain_tree.clear()
        self._current_edit_define_id = None
        self._update_sched_info(None)

    # =========== 编辑操作 ===========
    def _read_form(self):
        vals = {}
        covered = set()
        # From active type page
        if self._active_type and self._active_type in self._type_vars:
            tvars = self._type_vars[self._active_type]
            for fields in (ALL_EDIT_FIELDS, RUNTIME_FIELDS):
                for cb_key, cb_di, *_ in fields:
                    w = tvars.get(cb_key)
                    if isinstance(w, QComboBox):
                        try:
                            v = int(w.currentText().split('-')[0])
                            vals[f'd{cb_di}'] = v
                            covered.add(cb_di)
                        except ValueError:
                            pass
                    elif isinstance(w, QLineEdit) and cb_di not in covered:
                        try:
                            v = int(w.text())
                            vals[f'd{cb_di}'] = v
                            covered.add(cb_di)
                        except ValueError:
                            pass
        # From "全部" tab
        for di in range(96):
            if di in covered:
                continue
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                w = self._edit_vars.get(key)
                if isinstance(w, QLineEdit):
                    try:
                        v = int(w.text())
                        vals[f'd{di}'] = v
                        covered.add(di)
                        break
                    except ValueError:
                        return None
        # Fill remaining
        for di in range(96):
            if di not in covered:
                vals[f'd{di}'] = 0
        return vals

    def _apply_edit(self):
        sel = self.entity_tree.selectedItems()
        if sel:
            idx = int(sel[0].text(0))
        elif self._current_param_idx is not None:
            idx = self._current_param_idx
        else:
            return
        new_vals = self._read_form()
        if new_vals is None:
            QMessageBox.warning(self, "输入错误", "字段值必须是整数")
            return
        rec = self.records[idx]
        for key, val in new_vals.items():
            rec[key] = val
        self._dirty = True
        self._show_record(rec)
        self._apply_filter()
        self._sync_entity_list_select(idx)
        if rec['d1'] == self._vis_scene_id:
            self._vis_redraw()

    def _reset_edit(self):
        sel = self.entity_tree.selectedItems()
        if sel:
            idx = int(sel[0].text(0))
        elif self._current_param_idx is not None:
            idx = self._current_param_idx
        else:
            return
        self._show_record(self.records[idx])

    # =========== 新增/复制/清空 ===========
    def _new_record(self):
        if not self.records:
            return
        empty_idx = None
        for rec in self.records:
            if is_empty(rec):
                empty_idx = rec['index']
                break
        if empty_idx is None:
            QMessageBox.information(self, "无空槽", f"所有{REC_COUNT}条记录均已占用")
            return

        # Type/scene selection dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("新增实体")
        dlg.resize(400, 200)
        dl = QVBoxLayout(dlg)

        dl.addWidget(QLabel("实体类型:"))
        type_cb = QComboBox()
        type_cb.addItems([f"{k}-{v}" for k, v in sorted(ENTITY_TYPES.items()) if k != 0])
        type_cb.setCurrentIndex(6)  # 200-NPC角色
        dl.addWidget(type_cb)

        dl.addWidget(QLabel("场景 ID:"))
        scene_entry = QLineEdit(str(self._vis_scene_id))
        dl.addWidget(scene_entry)
        scene_lbl = QLabel(scene_name(self.tkt_scenes, self._vis_scene_id))
        dl.addWidget(scene_lbl)

        def _on_scene_change():
            try:
                sid = int(scene_entry.text())
                scene_lbl.setText(scene_name(self.tkt_scenes, sid))
            except ValueError:
                pass
        scene_entry.textChanged.connect(_on_scene_change)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        confirmed = [False]
        def _ok():
            confirmed[0] = True
            dlg.accept()
        btn_ok.clicked.connect(_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        dl.addLayout(btn_layout)

        if dlg.exec() != QDialog.Accepted or not confirmed[0]:
            return

        try:
            sel_type = int(type_cb.currentText().split('-')[0])
        except ValueError:
            return
        try:
            sel_scene = int(scene_entry.text())
        except ValueError:
            sel_scene = self._vis_scene_id

        rec = self.records[empty_idx]
        for di in range(DWORD_COUNT):
            rec[f'd{di}'] = 0
        rec['d0'] = sel_type
        rec['d1'] = sel_scene
        rec['d2'] = 3       # 启用+可见
        rec['d42'] = -1     # 执行位置·PC: -1=空闲
        rec['d43'] = -1     # 调用返回·SP: -1=空栈
        rec['d44'] = -1     # 当前DefUnit#: -1=未遍历
        rec['d8'] = 3 if sel_type == 10 else 0
        rec['d18'] = 400
        rec['d19'] = 384
        rec['d20'] = 30 if sel_type == 110 else 40
        rec['d21'] = 30 if sel_type == 110 else 24
        rec['d10'] = rec['d18'] + rec['d20'] // 2
        rec['d11'] = rec['d19'] + rec['d21'] // 2
        if sel_type in (20, 200):
            rec['d9'] = 1
            rec['d55'] = 1
            if sel_type == 20:
                rec['d53'] = 0
            else:
                rec['d53'] = 4
                rec['d13'] = 4
        _d15_defaults = {200: 64, 20: 64, 10: 0, 16: 300, 110: 80, 15: 64, 5: 0}
        rec['d15'] = _d15_defaults.get(sel_type, 64)

        self._dirty = True
        self._apply_filter()
        for i in range(self.entity_tree.topLevelItemCount()):
            item = self.entity_tree.topLevelItem(i)
            if item and int(item.text(0)) == empty_idx:
                self.entity_tree.setCurrentItem(item)
                self.entity_tree.scrollToItem(item)
                self._show_record(rec)
                break
        if sel_scene == self._vis_scene_id:
            self._vis_redraw()

    def _copy_record(self):
        sel = self.entity_tree.selectedItems()
        if not sel:
            QMessageBox.information(self, "提示", "请先选择记录")
            return
        idx = int(sel[0].text(0))
        src = self.records[idx]
        empty_idx = None
        for rec in self.records:
            if is_empty(rec):
                empty_idx = rec['index']
                break
        if empty_idx is None:
            QMessageBox.information(self, "无空槽", f"所有{REC_COUNT}条记录均已占用")
            return
        dst = self.records[empty_idx]
        for di in range(DWORD_COUNT):
            dst[f'd{di}'] = src[f'd{di}']
        dst['index'] = empty_idx
        self._dirty = True
        self._apply_filter()
        for i in range(self.entity_tree.topLevelItemCount()):
            item = self.entity_tree.topLevelItem(i)
            if item and int(item.text(0)) == empty_idx:
                self.entity_tree.setCurrentItem(item)
                self._show_record(dst)
                break

    def _clear_current(self):
        sel = self.entity_tree.selectedItems()
        if not sel:
            return
        idx = int(sel[0].text(0))
        if QMessageBox.question(self, "确认", f"清空实体 #{idx}? (type 设为 0)", QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        for di in range(DWORD_COUNT):
            self.records[idx][f'd{di}'] = 0
        self._dirty = True
        self._apply_filter()
        self._show_record(self.records[idx])

    def _goto_empty(self):
        for rec in self.records:
            if is_empty(rec):
                self.filter_type.setCurrentIndex(0)
                self.show_empty_cb.setChecked(True)
                self._apply_filter()
                for i in range(self.entity_tree.topLevelItemCount()):
                    item = self.entity_tree.topLevelItem(i)
                    if item and int(item.text(0)) == rec['index']:
                        self.entity_tree.setCurrentItem(item)
                        self.entity_tree.scrollToItem(item)
                        self._show_record(rec)
                        return
        QMessageBox.information(self, "提示", "无空槽")

    # =========== 可视化 ===========
    def _vis_load_scene(self):
        """加载场景到画布 (PIL 预合成)"""
        sid = self._vis_scene_id
        self._vis_gscene.clear()
        self._vis_entities.clear()
        self._vis_selected = None
        self._vis_drag = None
        self._vis_stop_sel_anim()
        self._vis_hit_regions = {}
        self._vis_anim_frame.clear()
        self._vis_bg_item = None

        # Limit caches
        for cache in (_SPRITE_CACHE, _SHADOW_CACHE, _BLEND_CACHE, _RGBA_CACHE):
            if len(cache) > 300:
                for k in list(cache.keys())[:len(cache) - 300]:
                    del cache[k]
        if not self.records:
            return

        # 获取当前预览窗口视口的实际像素大小
        view_w = self._vis_gview.viewport().width()
        view_h = self._vis_gview.viewport().height()

        # Background PIL Image
        self._vis_bg_pil = None
        # 优先从内存中的 _sc_grp_pending 加载背景（MOD 导入后尚未保存的数据）
        if self._sc_grp_pending is not None and 0 <= sid < len(self._sc_grp_pending):
            section_bytes = self._sc_grp_pending[sid]
            if section_bytes:
                try:
                    bg = load_scene_background_from_bytes(section_bytes)
                    if bg:
                        self._vis_bg_pil = bg
                except Exception:
                    pass
        # 回退到从磁盘文件加载
        if self._vis_bg_pil is None and self.dat_path:
            d = self._get_game_dir()
            grp_path = os.path.join(d, "SC.GRP")
            idx_path = os.path.join(d, "SC.IDX")
            if os.path.exists(grp_path):
                try:
                    bg = load_scene_background(grp_path, idx_path, sid)
                    if bg:
                        self._vis_bg_pil = bg
                except Exception:
                    pass

        ents = [r for r in self.records if has_data(r) and r['d1'] == sid]
        sname = scene_name(self.tkt_scenes, sid)
        if not ents:
            # 空场景: 如果有背景图也要渲染
            bg_w = self._vis_bg_pil.width if self._vis_bg_pil else 0
            bg_h = self._vis_bg_pil.height if self._vis_bg_pil else 0
            w = min(max(view_w, MAX_MAP_W, bg_w), 8192)
            h = min(max(view_h, MAX_MAP_H, bg_h), 8192)
            self._vis_render_scene(ents, w, h)
            self._vis_info_label.setText(f"SC.GRP #{sid}: {sname} — 无实体 (空场景)")
            return
        ents.sort(key=lambda r: r['d19'] if r['d0'] == 10 else r['d11'])

        # 过滤垃圾废弃坐标 (>10000)，防止画布被撑到 8192 导致显卡卡死
        xs = [r['d10'] for r in ents if -10000 < r['d10'] < 10000]
        ys = [r['d11'] for r in ents if -10000 < r['d11'] < 10000]
        if not xs: xs = [0]
        if not ys: ys = [0]
        right = max(r['d18'] + r['d20'] for r in ents if r['d20'] > 0 and -10000 < r['d18'] < 10000) if any(r['d20'] > 0 and -10000 < r['d18'] < 10000 for r in ents) else max(xs)
        bottom = max(r['d19'] + r['d21'] for r in ents if r['d21'] > 0 and -10000 < r['d19'] < 10000) if any(r['d21'] > 0 and -10000 < r['d19'] < 10000 for r in ents) else max(ys)
        # 场景尺寸 = max(视口大小, 实体范围, 背景图尺寸, 最小尺寸)
        bg_w = self._vis_bg_pil.width if self._vis_bg_pil else 0
        bg_h = self._vis_bg_pil.height if self._vis_bg_pil else 0
        w = min(max(view_w, MAX_MAP_W, max(max(xs), right) + 300, bg_w), 8192)
        h = min(max(view_h, MAX_MAP_H, max(max(ys), bottom) + 300, bg_h), 8192)
        self._vis_render_scene(ents, w, h)
        self._vis_info_label.setText(f"SC.GRP #{sid}: {sname} — {len(ents)} 个实体")
        if self._vis_anim_playing:
            self._vis_start_anim()

    def _vis_render_scene(self, ents, w, h):
        """PIL 预合成整个场景并显示到 QGraphicsView"""
        from PIL import Image, ImageDraw, ImageOps
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')

        # Background — 匹配 QGraphicsView 的 QSS 主题背景色
        # 深色主题 #1a1e27 → (26, 30, 39), 浅色主题 #ffffff → (255, 255, 255)
        bg_color = (26, 30, 39) if self._is_dark else (255, 255, 255)
        if self._vis_bg_pil:
            composite = self._vis_bg_pil.copy()
            if composite.width < w or composite.height < h:
                new_bg = Image.new('RGB', (w, h), bg_color)
                new_bg.paste(composite, (0, 0))
                composite = new_bg
        else:
            composite = Image.new('RGB', (w, h), bg_color)

        dr = ImageDraw.Draw(composite)

        for r in ents:
            tval = r['d0']
            show = self._type_filter_cbs.get(tval)
            if show and not show.isChecked():
                continue
            idx = r['index']
            x = r['d10']
            y = r['d11']
            ox = r.get('d26', 0)
            oy = r.get('d27', 0)
            color = TYPE_COLORS_RGBA.get(tval, (128, 128, 128))

            sprite_rgba = None
            jvg = None
            blk_idx = 0
            should_animate = False
            if mode != 'wire':
                if mode == 'auto':
                    if tval == 200:
                        if r['d70'] == 1 and r['d64'] > 0 and self._ani_jvg:
                            jvg = self._ani_jvg
                            blk_idx = r['d64']
                            should_animate = True
                        elif r['d51'] > 0 and self._cha_jvg:
                            jvg = self._cha_jvg
                            blk_idx = r['d51']
                    elif tval in (20, 110) and r['d64'] > 0 and self._ani_jvg:
                        jvg = self._ani_jvg
                        blk_idx = r['d64']
                        should_animate = True
                elif mode == 'ani':
                    if tval in (200, 20, 110) and r['d64'] > 0 and self._ani_jvg:
                        jvg = self._ani_jvg
                        blk_idx = r['d64']
                        should_animate = True
                elif mode == 'cha':
                    if tval == 200 and r['d51'] > 0 and self._cha_jvg:
                        jvg = self._cha_jvg
                        blk_idx = r['d51']
                    elif tval in (20, 110) and r['d64'] > 0 and self._ani_jvg:
                        jvg = self._ani_jvg
                        blk_idx = r['d64']

            if jvg and blk_idx < jvg.block_count:
                blk = jvg.blocks[blk_idx]
                if blk.frames:
                    if should_animate and idx not in self._vis_anim_frame:
                        self._vis_anim_frame[idx] = 0
                    anim = self._vis_anim_frame.get(idx, 0) if should_animate else 0
                    fi, fpd = _get_dir_frame(blk, r['d13'], r['d16'], r['d53'], anim)
                    if fi < len(blk.frames):
                        blend_mode = r.get('d24', 0)
                        blend_param = r.get('d25', 0)
                        sprite_rgba = _get_jvg_frame_rgba(jvg, blk_idx, fi)
                        if sprite_rgba:
                            sx = x + ox + blk.frames[fi].x_off
                            sy = y + oy + blk.frames[fi].y_off
                            if blend_mode == 5:
                                sprite_rgba = ImageOps.mirror(sprite_rgba)
                            if blend_mode == 1:
                                sprite_rgba = _pil_tint(sprite_rgba, blend_param)
                            # Shadow
                            shadow_fi = r.get('d55', 0)
                            if shadow_fi > 0 and (tval == 200 or tval == 20) and jvg is self._cha_jvg and jvg.block_count > 0:
                                blk0 = jvg.blocks[0]
                                if blk0.frames and shadow_fi < blk0.frame_count:
                                    shadow_rgba = _get_jvg_frame_rgba(jvg, 0, shadow_fi)
                                    _pil_subtract(composite, shadow_rgba,
                                                  x + ox + jvg.blocks[0].frames[shadow_fi].x_off,
                                                  y + oy + jvg.blocks[0].frames[shadow_fi].y_off)
                            # Store hit region
                            bx, by = r['d18'], r['d19']
                            bw = r['d20'] if r['d20'] > 0 else sprite_rgba.width
                            bh = r['d21'] if r['d21'] > 0 else sprite_rgba.height
                            self._vis_hit_regions[idx] = (bx, by, bx + bw, by + bh)
                            # Composite sprite
                            blend_func = {0: _pil_normal, 2: _pil_additive, 3: _pil_subtract,
                                          4: _pil_luma_alpha, 5: _pil_normal}.get(blend_mode, _pil_normal)
                            if blend_mode == 2:
                                _pil_additive(composite, sprite_rgba, sx, sy, blend_param)
                            elif blend_mode == 3:
                                _pil_subtract(composite, sprite_rgba, sx, sy)
                            elif blend_mode == 4:
                                _pil_luma_alpha(composite, sprite_rgba, sx, sy)
                            else:
                                _pil_normal(composite, sprite_rgba, sx, sy)

                # Draw collision box
                bx, by = r['d18'], r['d19']
                bw = r['d20'] if r['d20'] > 0 else 0
                bh = r['d21'] if r['d21'] > 0 else 0
                if bw > 0 and bh > 0:
                    dr.rectangle([bx, by, bx + bw, by + bh], outline=color, width=1)

            # Draw geometric shape when no sprite
            if sprite_rgba is None:
                bx, by = r['d18'], r['d19']
                bw = r['d20'] if r['d20'] > 0 else 40
                bh = r['d21'] if r['d21'] > 0 else 40
                dr.rectangle([bx, by, bx + bw, by + bh], outline=color, width=2)
                self._vis_hit_regions[idx] = (bx, by, bx + bw, by + bh)

            # Label
            label = f"#{idx}"
            if tval == 10:
                d62 = r.get("d62", 0)
                label = f"T{idx}[锁]" if d62 > 0 else f"T{idx}"
            elif tval == 15: label = f"E{idx}"
            elif tval == 16: label = f"B{idx}"
            elif tval == 20: label = f"V{idx}"
            elif tval == 110: label = f"M{idx}"
            elif tval == 200: label = f"N{idx}"
            elif tval == 5: label = f"P{idx}"
            cur_a = r.get('d33', 0)
            cur_b = r.get('d34', 0)
            script_icon = ""
            if cur_a > 0: script_icon += "⚡"
            if cur_b > 0: script_icon += "👆"
            if script_icon: label = f"{label} {script_icon}"
            bx_c = r['d18'] + r['d20'] // 2
            dr.text((bx_c - len(label) * 3, r['d19'] - 12), label, fill=color)

            # type=10 path lines
            if tval == 10:
                d62 = r.get("d62", 0)
                lc = (255, 80, 80) if d62 > 0 else (80, 255, 80)
                segs = [
                    (r.get("d63", 0), r.get("d64", 0), r.get("d65", 0), r.get("d66", 0), r.get("d67", 0)),
                    (r.get("d68", 0), r.get("d69", 0), r.get("d70", 0), r.get("d71", 0), r.get("d72", 0)),
                    (r.get("d73", 0), r.get("d74", 0), r.get("d75", 0), r.get("d76", 0), r.get("d77", 0)),
                    (r.get("d78", 0), r.get("d79", 0), r.get("d80", 0), r.get("d81", 0), r.get("d82", 0)),
                    (r.get("d83", 0), r.get("d84", 0), r.get("d85", 0), r.get("d86", 0), r.get("d87", 0)),
                ]
                for en, x1, y1, x2, y2 in segs:
                    if en and x1 > 0 and y1 > 0 and x2 > 0 and y2 > 0:
                        dr.line([x1, y1, x2, y2], fill=lc, width=2)

        # Selected entity highlight
        if self._vis_selected is not None and self._vis_selected in self._vis_hit_regions:
            x1, y1, x2, y2 = self._vis_hit_regions[self._vis_selected]
            dr.rectangle([x1 - 2, y1 - 2, x2 + 2, y2 + 2], outline=(255, 215, 0), width=2)

        # Convert to QPixmap and display
        pixmap = _pil_to_qpixmap(composite)
        self._vis_bg_pixmap = pixmap
        self._vis_bg_item = self._vis_gscene.addPixmap(pixmap)
        self._vis_gscene.setSceneRect(0, 0, composite.width, composite.height)

    def _vis_redraw(self):
        sid = self._vis_scene_id
        self._vis_gscene.clear()
        self._vis_hit_regions = {}
        self._vis_bg_item = None
        if not self.records:
            return

        # 获取当前预览窗口视口的实际像素大小
        view_w = self._vis_gview.viewport().width()
        view_h = self._vis_gview.viewport().height()

        ents = [r for r in self.records if has_data(r) and r['d1'] == sid]
        bg_w = self._vis_bg_pil.width if self._vis_bg_pil else 0
        bg_h = self._vis_bg_pil.height if self._vis_bg_pil else 0
        if not ents:
            # 空场景: 如果有背景图也要渲染
            w = min(max(view_w, MAX_MAP_W, bg_w), 8192)
            h = min(max(view_h, MAX_MAP_H, bg_h), 8192)
            self._vis_render_scene(ents, w, h)
            return
        ents.sort(key=lambda r: r['d19'] if r['d0'] == 10 else r['d11'])
        # 过滤垃圾废弃坐标 (>10000)，防止画布被撑到 8192 导致显卡卡死
        xs = [r['d10'] for r in ents if -10000 < r['d10'] < 10000]
        ys = [r['d11'] for r in ents if -10000 < r['d11'] < 10000]
        if not xs: xs = [0]
        if not ys: ys = [0]
        right = max(r['d18'] + r['d20'] for r in ents if r['d20'] > 0 and -10000 < r['d18'] < 10000) if any(r['d20'] > 0 and -10000 < r['d18'] < 10000 for r in ents) else max(xs)
        bottom = max(r['d19'] + r['d21'] for r in ents if r['d21'] > 0 and -10000 < r['d19'] < 10000) if any(r['d21'] > 0 and -10000 < r['d19'] < 10000 for r in ents) else max(ys)
        w = min(max(view_w, MAX_MAP_W, max(max(xs), right) + 300, bg_w), 8192)
        h = min(max(view_h, MAX_MAP_H, max(max(ys), bottom) + 300, bg_h), 8192)
        self._vis_render_scene(ents, w, h)

    # =========== 画布交互 ===========
    def _vis_canvas_click(self, event):
        pos = event.position().toPoint()
        scene_pos = self._vis_gview.mapToScene(pos)
        cx, cy = int(scene_pos.x()), int(scene_pos.y())
        self._vis_selected = None
        self._vis_drag = None
        found = None
        for idx, (x1, y1, x2, y2) in self._vis_hit_regions.items():
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                found = idx
        if found is not None:
            if self._vis_sel_anim_active and self._vis_selected != found:
                self._vis_stop_sel_anim()
            self._vis_selected = found
            rec = self.records[found]
            tname = ENTITY_TYPES.get(rec['d0'], '?')
            pos_x, pos_y = rec['d10'], rec['d11']
            self._undo_pos = (found, pos_x, pos_y)
            if self._vis_edit_mode:
                self._vis_info_label.setText(f"选中: #{found} [{tname}] 坐标({pos_x},{pos_y}) — 拖拽可移动")
                self._vis_drag = (found, cx, cy, pos_x, pos_y)
            else:
                self._vis_info_label.setText(f"选中: #{found} [{tname}] 坐标({pos_x},{pos_y}) — 拖动已锁定")
            self._sync_entity_list_select(found)
            self._current_param_idx = found
            self._show_record(rec)
        else:
            self._vis_info_label.setText("")
        self._vis_redraw()

    def _vis_canvas_mouse_move(self, event):
        pos = event.position().toPoint()
        scene_pos = self._vis_gview.mapToScene(pos)
        self._vis_coord_label.setText(f"坐标: ({int(scene_pos.x())}, {int(scene_pos.y())})")
        # Drag handling
        if self._vis_drag is None or not self._vis_edit_mode:
            return
        eidx, sx, sy, ox, oy = self._vis_drag
        cx, cy = int(scene_pos.x()), int(scene_pos.y())
        dx, dy = cx - sx, cy - sy
        new_x, new_y = ox + dx, oy + dy
        rec = self.records[eidx]
        old_d10, old_d11 = rec['d10'], rec['d11']
        rec['d10'], rec['d11'] = new_x, new_y
        rec['d18'] += new_x - old_d10
        rec['d19'] += new_y - old_d11
        self._dirty = True
        self._vis_info_label.setText(f"移动: #{eidx} → ({new_x},{new_y})")
        self._vis_redraw()

    def _vis_canvas_release(self, event):
        if self._vis_drag:
            eidx = self._vis_drag[0]
            rec = self.records[eidx]
            pos = event.position().toPoint()
            scene_pos = self._vis_gview.mapToScene(pos)
            cx, cy = int(scene_pos.x()), int(scene_pos.y())
            px, py = rec['d10'], rec['d11']
            self._vis_drag = (eidx, cx, cy, px, py)
            if hasattr(self, '_current_param_idx') and self._current_param_idx == eidx:
                self._show_record(rec)

    def _vis_canvas_wheel(self, event):
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ShiftModifier:
            self._vis_gview.horizontalScrollBar().setValue(
                self._vis_gview.horizontalScrollBar().value() - delta)
        else:
            self._vis_gview.verticalScrollBar().setValue(
                self._vis_gview.verticalScrollBar().value() - delta)

    # =========== 动画控制 ===========
    def _vis_toggle_anim(self):
        if self._vis_anim_playing:
            self._vis_stop_anim()
            self._vis_anim_playing = False
            self._vis_play_btn.setText("▶️ 播放全部")
        else:
            self._vis_anim_playing = True
            self._vis_start_anim()
            self._vis_play_btn.setText("⏸️ 暂停全部")

    def _vis_start_anim(self):
        if self._vis_anim_timer:
            return
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')
        if mode in ('wire', 'cha'):
            return
        timer = QTimer(self)
        timer.timeout.connect(self._vis_anim_tick)
        timer.start(200)
        self._vis_anim_timer = timer

    def _vis_anim_tick(self):
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')
        if mode in ('wire', 'cha'):
            self._vis_stop_anim()
            return
        for idx in list(self._vis_anim_frame.keys()):
            self._vis_anim_frame[idx] += 1
        self._vis_redraw()

    def _vis_stop_anim(self):
        if self._vis_anim_timer:
            self._vis_anim_timer.stop()
            self._vis_anim_timer = None

    def _vis_toggle_sel_anim(self):
        if self._vis_selected is None:
            self._vis_info_label.setText("请先选中一个实体再播放动画")
            return
        if self._vis_anim_playing:
            self._vis_info_label.setText("全局动画已开启，无需单独播放")
            return
        idx = self._vis_selected
        rec = self.records[idx]
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')
        tval = rec['d0']
        can_animate = False
        if mode in ('auto', 'ani'):
            if tval in (200, 20, 110) and rec['d64'] > 0 and self._ani_jvg:
                can_animate = True
        if not can_animate:
            tname = ENTITY_TYPES.get(tval, '?')
            self._vis_info_label.setText(f"实体 #{idx} [{tname}] 不支持动画")
            return
        if self._vis_sel_anim_active:
            self._vis_stop_sel_anim()
        else:
            self._vis_start_sel_anim(idx)

    def _vis_start_sel_anim(self, idx):
        self._vis_sel_anim_active = True
        self._vis_sel_anim_btn.setText("⏸️ 播放选中")
        self._vis_anim_frame[idx] = 0
        timer = QTimer(self)
        timer.timeout.connect(lambda: self._vis_sel_anim_tick(idx))
        timer.start(200)
        self._vis_sel_anim_timer = timer

    def _vis_sel_anim_tick(self, idx):
        if not self._vis_sel_anim_active:
            return
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')
        if mode in ('wire', 'cha'):
            self._vis_stop_sel_anim()
            return
        if idx in self._vis_anim_frame:
            self._vis_anim_frame[idx] += 1
        self._vis_redraw()

    def _vis_stop_sel_anim(self):
        self._vis_sel_anim_active = False
        if self._vis_sel_anim_timer:
            self._vis_sel_anim_timer.stop()
            self._vis_sel_anim_timer = None
        self._vis_sel_anim_btn.setText("⏯️ 播放选中")

    def _on_display_mode_change(self):
        self._vis_stop_anim()
        self._vis_stop_sel_anim()
        self._vis_anim_playing = False
        self._vis_play_btn.setText("▶️ 播放全部")
        self._vis_display_mode = self._display_mode_combo.currentText()
        self._vis_load_scene()

    def _on_edit_mode_change(self):
        self._vis_edit_mode = self._vis_edit_cb.isChecked()
        if self._vis_edit_mode:
            self._vis_info_label.setText("编辑模式已开启 — 可拖动实体")
        else:
            self._vis_drag = None
            self._vis_info_label.setText("编辑模式已锁定 — 拖动已禁用")

    def _vis_canvas_undo(self):
        if self._undo_pos is None:
            return
        eidx, old_x, old_y = self._undo_pos
        rec = self.records[eidx]
        cur_d10, cur_d11 = rec['d10'], rec['d11']
        rec['d10'], rec['d11'] = old_x, old_y
        rec['d18'] += old_x - cur_d10
        rec['d19'] += old_y - cur_d11
        self._dirty = True
        self._vis_info_label.setText(f"已撤销: #{eidx} → ({old_x},{old_y})")
        self._vis_redraw()
        self._undo_pos = None
        if hasattr(self, '_current_param_idx') and self._current_param_idx == eidx:
            self._show_record(rec)

    # =========== 数据加载 ===========
    def _load_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d:
            return
        mat_p = os.path.join(d, "TKMat.Dat")
        tkt_p = os.path.join(d, "TKT.dat")
        if not os.path.exists(mat_p):
            QMessageBox.warning(self, "文件缺失", f"未找到 TKMat.Dat\n{d}")
            return
        self._save_mode = False
        self.dat_path = mat_p
        self.tkt_path = tkt_p if os.path.exists(tkt_p) else None
        self._reload()

    def _load_save_dir(self):
        """从存档文件 sav.N 加载 TKMat 地图实体数据 (先选游戏目录, 再自动定位 save/)"""
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录 (含 save 子文件夹)")
        if not d: return
        # 确认选中的是游戏目录 (包含 TKMat.Dat 或 TKT.dat)
        is_game_dir = os.path.exists(os.path.join(d, 'TKMat.Dat')) or os.path.exists(os.path.join(d, 'TKT.dat'))
        if not is_game_dir:
            # 用户可能选了 save/ 子文件夹，尝试向上修正
            parent = os.path.dirname(d.rstrip('/\\'))
            if os.path.exists(os.path.join(parent, 'TKMat.Dat')) or os.path.exists(os.path.join(parent, 'TKT.dat')):
                d = parent  # 自动修正到游戏目录
            else:
                QMessageBox.warning(self, "目录不正确",
                    f"所选目录不是 TKS 游戏目录 (未找到 TKMat.Dat/TKT.dat):\n{d}\n\n"
                    f"请选择包含 TKMat.Dat 和 save/ 文件夹的游戏根目录。")
                return
        game_dir = d
        # 在游戏目录下查找 save 子文件夹
        save_dir = os.path.join(d, 'save')
        if not os.path.exists(save_dir):
            save_dir = d  # 降级: 直接在游戏目录下找
        if not any(os.path.exists(os.path.join(save_dir, f'sav.{s}')) for s in range(1, 10)):
            QMessageBox.warning(self, "未找到存档",
                f"在游戏目录下未找到 save 文件夹或 sav.N 文件:\n{d}")
            return
        # 扫描可用槽位
        slots = []
        for s in range(1, 10):
            sp = os.path.join(save_dir, f'sav.{s}')
            if os.path.exists(sp):
                ip = os.path.join(save_dir, f'{s}.sav')
                summary = ""
                if os.path.exists(ip):
                    try:
                        idx_data = open(ip, 'rb').read()
                        if len(idx_data) >= 28:
                            import datetime as _dt
                            ts = struct.unpack_from('<I', idx_data, 8)[0]
                            dt_str = _dt.datetime.fromtimestamp(ts).strftime('%m/%d %H:%M')
                            gold = struct.unpack_from('<H', idx_data, 6)[0]
                            summary = f"{dt_str} | 金{gold}"
                    except Exception:
                        summary = "(索引异常)"
                slots.append((s, sp, summary))
        if not slots:
            QMessageBox.warning(self, "无可用槽位", "目录中没有存档数据"); return
        # 槽位选择对话框
        dlg = QDialog(self); dlg.setWindowTitle("选择存档槽位 — 加载 TKMat 数据")
        dlg.resize(450, 380)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"存档目录: {save_dir}"))
        table = QTableWidget(len(slots), 3)
        table.setHorizontalHeaderLabels(['槽位', '文件', '摘要'])
        table.setColumnWidth(0, 50); table.setColumnWidth(1, 150)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row, (s, sp, summary) in enumerate(slots):
            table.setItem(row, 0, QTableWidgetItem(str(s)))
            table.setItem(row, 1, QTableWidgetItem(os.path.basename(sp)))
            table.setItem(row, 2, QTableWidgetItem(summary))
        layout.addWidget(table, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(QPushButton("取消", clicked=dlg.reject))
        btn_row.addWidget(QPushButton("打开", clicked=dlg.accept))
        layout.addLayout(btn_row)
        if dlg.exec() != QDialog.Accepted: return
        sel = table.selectedItems()
        if not sel: return
        slot_num = slots[sel[0].row()][0]
        save_path = slots[sel[0].row()][1]
        # 设置存档模式
        self._save_mode = True
        self._save_path = save_path
        self._save_slot = slot_num
        self._game_dir = game_dir  # 直接存储游戏目录
        self.dat_path = save_path  # DataLoaderThread 从此路径加载附属文件 (TKD/TKDefUnit)
        tkt_p = os.path.join(game_dir, 'TKT.dat')
        self.tkt_path = tkt_p if os.path.exists(tkt_p) else None
        # 预加载 TKMat records (从存档 Frame1)
        self.status_var.setText(f"从存档加载 TKMat 数据 (槽位{slot_num})…")
        QApplication.processEvents()
        try:
            self._preloaded_records = load_mat_from_save(save_path)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法从存档读取 TKMat 数据:\n{e}")
            self._save_mode = False
            return
        self._reload()
        self.setWindowTitle(f"TKMat.Dat 地图实体编辑器 v2.3 (PySide6) [存档模式 槽位{slot_num}]")

    def _reload(self):
        if not self.dat_path:
            return
        self.status_var.setText("后台高速解析结构中…")
        self._set_edit_enabled(False)
        # 清空贴图引用，防止切换目录时旧缓存残留
        self._ani_jvg = None
        self._cha_jvg = None
        self._cur_jvg = None
        self._update_path()
        # 存档模式下使用 game_dir 加载附属文件，并传入预加载的 TKMat records
        game_dir = self._game_dir if self._save_mode else os.path.dirname(self.dat_path)
        preloaded = getattr(self, '_preloaded_records', None) if self._save_mode else None
        self._loader_thread = DataLoaderThread(self.dat_path, self.tkt_path,
                                                game_dir=game_dir, preloaded_records=preloaded)
        self._loader_thread.finished_load.connect(self._on_load_success)
        self._loader_thread.error_load.connect(self._on_load_error)
        self._loader_thread.start()

    def _on_load_error(self, err_msg):
        """加载报错回调"""
        QMessageBox.critical(self, "加载失败", f"数据解析异常:\n{err_msg}")
        self.records = []
        self._set_edit_enabled(True)
        self.status_var.setText("加载失败")

    def _on_load_success(self):
        """加载完毕回调：应用数据并刷新 UI"""
        self.setUpdatesEnabled(False)
        result = self._loader_thread.result_data

        self.tkt_scenes = result.get('tkt_scenes', {})
        self.tkt_all = result.get('tkt_all', {})
        self.defunit_recs = result.get('defunit_recs', [])
        self.defunit_next = result.get('defunit_next', {})
        self.defunit_entity = result.get('defunit_entity', {})
        self.tkd_defines = result.get('tkd_defines', [])
        self.tkd_header = result.get('tkd_header', '')
        self.tkd_define_map = result.get('tkd_define_map', {})
        self.item_names = result.get('item_names', {})
        self._sc_grp_section_count = result.get('sc_grp_section_count', 0)
        self.records = result.get('records', [])

        # 保存原始快照用于 MOD 导出
        self._original_mat_records = [[r.get(f'd{i}', 0) for i in range(DWORD_COUNT)] for r in self.records]
        self._original_defunit_recs = [[r.get(f'f{i}', 0) for i in range(8)] for r in self.defunit_recs]

        nonempty = sum(1 for r in self.records if has_data(r))
        scenes = set(r['d1'] for r in self.records if has_data(r))

        self._update_path()
        self._set_edit_enabled(True)
        self._apply_filter()
        self._vis_populate_scenes()

        # 延迟启动 JVG 贴图加载，让主线程先完成 UI 渲染，避免 GIL 锁竞争
        self.status_var.setText(
            f"{REC_COUNT}条 | 有效{nonempty} | TKMat场景{len(scenes)} | "
            f"SC.GRP {self._sc_grp_section_count}区段 (正在后台加载贴图…)")
        QTimer.singleShot(300, self._start_jvg_thread)

        # 自动选中首个有效场景 (静默信号，防止触发无意义的首次重绘)
        if self.scene_tree.topLevelItemCount() > 0:
            first = self.scene_tree.topLevelItem(1 if self.scene_tree.topLevelItemCount() > 1 else 0)
            self.scene_tree.blockSignals(True)
            self.scene_tree.setCurrentItem(first)
            self.scene_tree.blockSignals(False)
            sid = int(first.text(0))
            self._vis_scene_id = sid
            for i in range(self._vis_scene_combo.count()):
                if self._vis_scene_combo.itemText(i).startswith(f"{sid}:"):
                    self._vis_scene_combo.setCurrentIndex(i)
                    break
            self._vis_load_scene()

        # 所有初始化完成后才重置脏标记，防止 UI 刷新链路误触
        self._dirty = False
        self._script_dirty = False
        self.setUpdatesEnabled(True)

    def _start_jvg_thread(self):
        """延迟触发的后台资源加载线程 (贴图+TKD+物品)"""
        game_dir = self._game_dir if self._save_mode else None
        self._jvg_thread = JvgLoaderThread(self.dat_path, getattr(self, 'tkt_all', None), game_dir=game_dir)
        self._jvg_thread.finished_jvg.connect(self._on_jvg_success)
        self._jvg_thread.start()

    def _on_jvg_success(self):
        """后台资源加载完毕回调 (贴图+TKD+物品)"""
        result = self._jvg_thread.jvg_result
        # 接收贴图
        self._ani_jvg = result.get('ani_jvg')
        self._cha_jvg = result.get('cha_jvg')
        self._cur_jvg = result.get('cur_jvg')

        # 接收 TKD 脚本与物品数据
        if 'tkd_defines' in result:
            self.tkd_defines = result['tkd_defines']
            self.tkd_header = result.get('tkd_header', '')
            self.tkd_define_map = result.get('tkd_define_map', {})
            self.item_names = result.get('item_names', {})
            # 保存 TKD 原始快照用于 MOD 导出 (dict: {define_id_str: full_text})
            self._original_tkd_defines = {
                str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                for dd in self.tkd_defines
            }
            # 刷新当前脚本预览
            if self._current_edit_define_id is not None:
                self._update_line_preview()

        self._update_path()
        cur = self.status_var.text()
        self.status_var.setText(cur.replace("(正在后台加载贴图…)", "(全部资源就绪)"))
        # 触发重绘让实体显示彩色立绘
        if hasattr(self, 'records') and self.records:
            self._vis_redraw()

    def _vis_populate_scenes(self):
        self.scene_tree.setUpdatesEnabled(False)
        self.scene_tree.blockSignals(True)
        self.scene_tree.clear()
        if not self.records:
            self.scene_tree.blockSignals(False)
            self.scene_tree.setUpdatesEnabled(True)
            return
        smap = defaultdict(list)
        for r in self.records:
            if has_data(r) and r['d1'] >= 0:
                smap[r['d1']].append(r['index'])
        total_scenes = max(self._sc_grp_section_count, max(smap.keys()) + 1 if smap else 0)
        combo_vals = []
        scene_items = []
        for sid in range(total_scenes):
            sname = scene_name(self.tkt_scenes, sid)
            cnt = len(smap.get(sid, []))
            is_virtual = self._sc_grp_section_count > 0 and sid >= self._sc_grp_section_count
            display_name = f"{sname} [虚拟场景]" if is_virtual else sname
            item = QTreeWidgetItem([str(sid), display_name, str(cnt)])
            if is_virtual:
                for c in range(3):
                    item.setForeground(c, QColor("#3366cc"))
            scene_items.append(item)
            combo_vals.append(f"{sid}: {sname} ({cnt}实体)")
        self.scene_tree.addTopLevelItems(scene_items)
        self.scene_tree.blockSignals(False)
        self.scene_tree.setUpdatesEnabled(True)
        # 阻止 combo 信号，避免 clear/addItems 触发 _on_vis_combo_select 导致 _vis_scene_id 被意外修改
        self._vis_scene_combo.blockSignals(True)
        self._vis_scene_combo.clear()
        self._vis_scene_combo.addItems(combo_vals)
        self._vis_scene_combo.blockSignals(False)

    # =========== 场景列表/实体列表 ===========
    def _vis_scene_tree_to_combo(self):
        """Sync scene tree selection to combo"""
        pass

    # =========== 保存 ===========
    def _save(self):
        if self._save_mode:
            self._save_to_save_file(); return
        d = os.path.dirname(self.dat_path) if self.dat_path else None
        if not d:
            self._save_as()
            return
        self._save_editor_to_define()
        du_p = os.path.join(d, "TKDefUnit.Dat")
        tkd_p = os.path.join(d, "TKD.dat")
        has_sc_pending = self._sc_grp_pending is not None
        files_msg = f"TKMat.Dat: {self.dat_path}\nTKDefUnit.Dat: {du_p}\nTKD.dat: {tkd_p}"
        if has_sc_pending:
            files_msg += f"\nSC.GRP: {os.path.join(d, 'SC.GRP')}\nSC.IDX: {os.path.join(d, 'SC.IDX')}"
        file_count = 5 if has_sc_pending else 3
        if QMessageBox.question(self, f"确认保存 — 将写入以下 {file_count} 个文件", files_msg, QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        errors = []
        try:
            save_mat(self.dat_path, self.records)
        except Exception as e:
            errors.append(f"TKMat.Dat: {e}")
        try:
            save_defunit(du_p, self.defunit_recs)
        except Exception as e:
            errors.append(f"TKDefUnit.Dat: {e}")
        try:
            tkd_text = rebuild_text(self.tkd_defines, self.tkd_header)
            save_tkd(tkd_p, tkd_text)
        except Exception as e:
            errors.append(f"TKD.dat: {e}")
        # 保存待写入的 SC.GRP/SC.IDX
        if has_sc_pending:
            try:
                grp_path = os.path.join(d, "SC.GRP")
                idx_path = os.path.join(d, "SC.IDX")
                offsets = []
                grp_data = bytearray()
                for section in self._sc_grp_pending:
                    offsets.append(len(grp_data))
                    grp_data.extend(section)
                offsets.append(len(grp_data))  # 末尾哨兵
                with open(grp_path, 'wb') as f:
                    f.write(bytes(grp_data))
                with open(idx_path, 'wb') as f:
                    for off in offsets:
                        f.write(struct.pack('<I', off))
                self._sc_grp_pending = None  # 已写入，清除待保存标记
            except Exception as e:
                errors.append(f"SC.GRP/IDX: {e}")
        if errors:
            QMessageBox.critical(self, "保存失败", '\n'.join(errors))
        else:
            self._dirty = False
            self._script_dirty = False
            self.status_var.setText(f"已保存 — {file_count} 个文件")

    def _save_as(self):
        if self._save_mode:
            QMessageBox.information(self, "提示", "存档模式下不支持另存为")
            return
        fp, _ = QFileDialog.getSaveFileName(self, "另存 TKMat.Dat", "", "DAT 文件 (*.Dat *.dat);;所有文件 (*.*)")
        if not fp:
            return
        self.dat_path = fp
        self._save()

    def _save_to_save_file(self):
        """存档模式下保存 TKMat 数据回 sav.N，TKDefUnit/TKD 写入游戏目录"""
        if not self._save_path or not self.records:
            QMessageBox.information(self, "提示", "无存档数据"); return
        game_dir = self._game_dir or os.path.dirname(os.path.dirname(self._save_path))
        du_p = os.path.join(game_dir, "TKDefUnit.Dat")
        tkd_p = os.path.join(game_dir, "TKD.dat")
        files_msg = (f"存档 TKMat: {self._save_path} (槽位 {self._save_slot})\n"
                     f"TKDefUnit.Dat: {du_p}\nTKD.dat: {tkd_p}")
        has_sc = self._sc_grp_pending is not None
        if has_sc:
            files_msg += f"\nSC.GRP/SC.IDX: {game_dir}"
        if QMessageBox.question(self, f"确认保存到存档", files_msg,
                                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        errors = []
        try:
            save_mat_to_save(self._save_path, self.records)
        except Exception as e:
            errors.append(f"存档 TKMat: {e}")
        try:
            save_defunit(du_p, self.defunit_recs)
        except Exception as e:
            errors.append(f"TKDefUnit.Dat: {e}")
        try:
            tkd_text = rebuild_text(self.tkd_defines, self.tkd_header)
            save_tkd(tkd_p, tkd_text)
        except Exception as e:
            errors.append(f"TKD.dat: {e}")
        if has_sc:
            try:
                grp_path = os.path.join(game_dir, "SC.GRP")
                idx_path = os.path.join(game_dir, "SC.IDX")
                offsets = []
                grp_data = bytearray()
                for section in self._sc_grp_pending:
                    offsets.append(len(grp_data))
                    grp_data.extend(section)
                offsets.append(len(grp_data))
                with open(grp_path, 'wb') as f: f.write(bytes(grp_data))
                with open(idx_path, 'wb') as f:
                    for off in offsets: f.write(struct.pack('<I', off))
                self._sc_grp_pending = None
            except Exception as e:
                errors.append(f"SC.GRP/IDX: {e}")
        if errors:
            QMessageBox.critical(self, "保存失败", '\n'.join(errors))
        else:
            self._dirty = False
            self._script_dirty = False
            self.status_var.setText(f"已保存到存档 {self._save_path} 槽位{self._save_slot}")

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件 (TKMat + TKDefUnit + TKD 三文件联动)"""
        if not self.records or not hasattr(self, '_original_mat_records'):
            QMessageBox.information(self, "提示", "请先加载数据"); return
        from PySide6.QtWidgets import QDialog
        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata(); self._last_mod_metadata = metadata

        data_files = {}; components = []

        # TKMat.Dat 差异
        current_mat = [[r.get(f'd{i}', 0) for i in range(DWORD_COUNT)] for r in self.records]
        mat_diff = diff_records(self._original_mat_records, current_mat, DWORD_COUNT, len(self._original_mat_records))
        if mat_diff['modified'] or mat_diff['appended']:
            crc = compute_crc32(self.dat_path) if self.dat_path else "0x00000000"
            mat_json = build_data_diff_json(target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=len(self._original_mat_records), original_crc32=crc, diff_result=mat_diff)
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # TKDefUnit.Dat 差异
        if hasattr(self, '_original_defunit_recs') and hasattr(self, 'defunit_recs'):
            current_du = [[r.get(f'f{i}', 0) for i in range(8)] for r in self.defunit_recs]
            du_diff = diff_records(self._original_defunit_recs, current_du, 8, len(self._original_defunit_recs))
            if du_diff['modified'] or du_diff['appended']:
                du_path = os.path.join(self._get_game_dir(), "TKDefUnit.Dat")
                crc = compute_crc32(du_path) if os.path.exists(du_path) else "0x00000000"
                du_json = build_data_diff_json(target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE, field_type="uint16",
                    field_count=8, original_count=len(self._original_defunit_recs), original_crc32=crc, diff_result=du_diff)
                data_files["data/TKDefUnit.dat.json"] = du_json
                components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # TKD.dat 脚本差异
        if hasattr(self, '_original_tkd_defines') and hasattr(self, 'tkd_defines'):
            self._save_editor_to_define()  # 确保当前编辑中的脚本已回写
            current_tkd = {
                str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                for dd in self.tkd_defines
            }
            tkd_diff = diff_text_defines(self._original_tkd_defines, current_tkd)
            if tkd_diff['modified'] or tkd_diff['appended'] or tkd_diff['deleted']:
                tkd_path = os.path.join(self._get_game_dir(), "TKD.dat")
                crc = compute_crc32(tkd_path) if os.path.exists(tkd_path) else "0x00000000"
                tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc, diff_result=tkd_diff)
                data_files["data/TKD.dat.json"] = tkd_json
                components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        if not data_files:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。"); return

        mod_json = generate_mod_json(metadata, components)
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{metadata['id']}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, data_files)
            total = sum(len(v.get('modified', [])) + len(v.get('appended', [])) for v in data_files.values())
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} ({len(components)}文件, {total}处变更)")
            QMessageBox.information(self, "导出成功", f"已导出:\n{fp}\n\n包含 {len(components)} 个数据文件")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对 (TKMat + TKDefUnit)"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据"); return
        ref_dir = ask_reference_directory(self)
        if not ref_dir: return

        # 加载参考目录中的 TKMat.Dat
        ref_mat = load_reference_dat_fields(ref_dir, "TKMat.Dat",
            rec_size=REC_SIZE, field_count=DWORD_COUNT, field_fmt='i', use_lzss=False)
        if ref_mat is None:
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 TKMat.Dat"); return

        from PySide6.QtWidgets import QDialog
        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata(); self._last_mod_metadata = metadata

        data_files = {}; components = []

        # TKMat.Dat 差异
        current_mat = [[r.get(f'd{i}', 0) for i in range(DWORD_COUNT)] for r in self.records]
        mat_diff = diff_records(ref_mat, current_mat, DWORD_COUNT, len(ref_mat))
        if mat_diff['modified'] or mat_diff['appended']:
            crc = compute_crc32(os.path.join(ref_dir, "TKMat.Dat"))
            mat_json = build_data_diff_json(target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=len(ref_mat), original_crc32=crc, diff_result=mat_diff)
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # TKDefUnit.Dat 差异
        if hasattr(self, 'defunit_recs'):
            ref_du = load_reference_dat_fields(ref_dir, "TKDefUnit.Dat",
                rec_size=DEFUNIT_REC_SIZE, field_count=8, field_fmt='H', use_lzss=False)
            if ref_du is not None:
                current_du = [[r.get(f'f{i}', 0) for i in range(8)] for r in self.defunit_recs]
                du_diff = diff_records(ref_du, current_du, 8, len(ref_du))
                if du_diff['modified'] or du_diff['appended']:
                    crc = compute_crc32(os.path.join(ref_dir, "TKDefUnit.Dat"))
                    du_json = build_data_diff_json(target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE,
                        field_type="uint16", field_count=8, original_count=len(ref_du), original_crc32=crc, diff_result=du_diff)
                    data_files["data/TKDefUnit.dat.json"] = du_json
                    components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # TKD.dat 脚本差异
        if hasattr(self, 'tkd_defines'):
            ref_tkd_path = os.path.join(ref_dir, "TKD.dat")
            if os.path.exists(ref_tkd_path):
                self._save_editor_to_define()  # 确保当前编辑中的脚本已回写
                ref_tkd_text = load_tkd(ref_tkd_path)
                ref_tkd_defs, _ = parse_defines(ref_tkd_text)
                ref_tkd_map = {
                    str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                    for dd in ref_tkd_defs
                }
                current_tkd = {
                    str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                    for dd in self.tkd_defines
                }
                tkd_diff = diff_text_defines(ref_tkd_map, current_tkd)
                if tkd_diff['modified'] or tkd_diff['appended'] or tkd_diff['deleted']:
                    crc = compute_crc32(ref_tkd_path)
                    tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc, diff_result=tkd_diff)
                    data_files["data/TKD.dat.json"] = tkd_json
                    components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        if not data_files:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。"); return

        mod_json = generate_mod_json(metadata, components)
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{metadata['id']}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, data_files)
            total = sum(len(v.get('modified', [])) + len(v.get('appended', [])) for v in data_files.values())
            self.status_var.setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n包含 {len(components)} 个数据文件, {total} 处变更")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_scene_as_tksmod(self):
        """导出当前场景为 .tksmod MOD 文件 — 直接导出选中场景全部数据（不判断差异）"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        sid = self._vis_scene_id
        if sid < 0:
            QMessageBox.warning(self, "无效场景", "请先在可视化面板中选择一个场景")
            return

        # ── 1. 筛选属于本场景的实体 ──
        scene_entity_indices = [i for i, r in enumerate(self.records)
                                if has_data(r) and r['d1'] == sid]
        if not scene_entity_indices:
            QMessageBox.warning(self, "空场景", f"场景 {sid} 无实体数据")
            return

        # ── 2. 追踪 DefUnit 链 ──
        def find_du(idx):
            return next((r for r in self.defunit_recs if r['index'] == idx), None)

        all_defunit_indices = set()

        def collect_chain(head_idx):
            cur = head_idx
            visited = set()
            while cur >= 0 and cur not in visited:
                visited.add(cur)
                du = find_du(cur)
                if du is None:
                    break
                all_defunit_indices.add(cur)
                nxt = du.get('f6', 0)
                if nxt == 0 or nxt in visited:
                    break
                cur = nxt

        for eidx in scene_entity_indices:
            rec = self.records[eidx]
            for chain_di, max_di in [(39, 30), (40, 31), (41, 32)]:
                head = rec.get(f'd{chain_di}', -1)
                mx = rec.get(f'd{max_di}', 0)
                if head > 0 and mx > 0:
                    collect_chain(head)

        # ── 3. 追踪 TKD DEFINE 块 ──
        scene_define_ids = set()
        for du_idx in all_defunit_indices:
            du = find_du(du_idx)
            if du:
                did = (du.get('f1', 0) << 16) | du.get('f0', 0)
                if did > 0:
                    scene_define_ids.add(str(did))

        # ── 4. 弹出 MOD 元数据对话框 ──
        from PySide6.QtWidgets import QDialog
        sname = scene_name(self.tkt_scenes, sid).replace('/', '_').replace('\\', '_')
        defaults = getattr(self, '_last_mod_metadata', None) or {}
        if not defaults.get('id'):
            defaults['id'] = f"scene_{sid}_{sname}"
        if not defaults.get('name'):
            defaults['name'] = f"场景 {sname} (ID={sid})"
        if not defaults.get('type'):
            defaults['type'] = 'story'
        dlg = ModMetadataDialog(self, defaults)
        if dlg.exec() != QDialog.Accepted:
            return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # ── 5. 直接导出 TKMat.Dat 场景实体（全量字段，不做差异比对）──
        data_files = {}
        components = []

        mat_entries = []
        for eidx in scene_entity_indices:
            rec = self.records[eidx]
            # 导出所有字段（含零值），确保导入时能完整覆盖目标槽位
            fields = {}
            for fi in range(DWORD_COUNT):
                fields[f"f{fi}"] = rec.get(f'd{fi}', 0)
            mat_entries.append({"index": eidx, "fields": fields})

        if mat_entries:
            crc = compute_crc32(self.dat_path) if self.dat_path else "0x00000000"
            original_count = len(self.records)
            mat_json = build_data_diff_json(
                target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=original_count,
                original_crc32=crc, diff_result={'modified': mat_entries, 'appended': []})
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # ── 6. 直接导出 TKDefUnit.Dat（全量字段，不做差异比对）──
        if hasattr(self, 'defunit_recs') and all_defunit_indices:
            du_entries = []
            for du_idx in sorted(all_defunit_indices):
                du = find_du(du_idx)
                if du:
                    # 导出所有字段（含零值）
                    fields = {}
                    for fi in range(8):
                        fields[f"f{fi}"] = du.get(f'f{fi}', 0)
                    du_entries.append({"index": du_idx, "fields": fields})

            if du_entries:
                du_path = os.path.join(self._get_game_dir(), "TKDefUnit.Dat")
                crc = compute_crc32(du_path) if os.path.exists(du_path) else "0x00000000"
                original_du_count = len(self.defunit_recs)
                du_json = build_data_diff_json(
                    target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE, field_type="uint16",
                    field_count=8, original_count=original_du_count,
                    original_crc32=crc, diff_result={'modified': du_entries, 'appended': []})
                data_files["data/TKDefUnit.dat.json"] = du_json
                components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # ── 7. 直接导出 TKD.dat 脚本（全量内容，不做差异比对）──
        if hasattr(self, 'tkd_defines') and scene_define_ids:
            self._save_editor_to_define()
            tkd_modified = {}
            for dd in self.tkd_defines:
                did_str = str(dd['define_id'])
                if did_str in scene_define_ids:
                    tkd_modified[did_str] = '\r\n'.join([dd['header_line']] + dd['body_lines'])

            if tkd_modified:
                tkd_path = os.path.join(self._get_game_dir(), "TKD.dat")
                crc = compute_crc32(tkd_path) if os.path.exists(tkd_path) else "0x00000000"
                tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc,
                    diff_result={'modified': tkd_modified, 'appended': [], 'deleted': []})
                data_files["data/TKD.dat.json"] = tkd_json
                components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        # ── 8. 直接导出 SC.GRP 场景区段（不做差异比对）──
        if self.dat_path:
            game_dir = self._get_game_dir()
            grp_path = os.path.join(game_dir, "SC.GRP")
            idx_path = os.path.join(game_dir, "SC.IDX")
            if os.path.exists(grp_path) and os.path.exists(idx_path):
                try:
                    with open(idx_path, 'rb') as f:
                        idata = f.read()
                    offs = [struct.unpack_from('<I', idata, i)[0] for i in range(0, len(idata), 4)]
                    if sid < len(offs):
                        start = offs[sid]
                        end = offs[sid + 1] if sid + 1 < len(offs) else os.path.getsize(grp_path)
                        with open(grp_path, 'rb') as f:
                            f.seek(start)
                            section_data = f.read(end - start)
                        if section_data:
                            total_sections = len(offs) - 1 if len(offs) > 1 else len(offs)
                            sc_diff = {
                                'modified': [{'index': sid, 'data_b64': base64.b64encode(section_data).decode('ascii')}],
                                'appended': [],
                                'deleted_indices': [],
                            }
                            crc = compute_crc32(grp_path)
                            sc_json = build_block_diff_json(
                                target="SC.GRP", block_type="grp_section",
                                original_count=total_sections,
                                original_crc32=crc, diff_result=sc_diff)
                            data_files["data/SC.GRP.json"] = sc_json
                            components.append({"file": "data/SC.GRP.json", "target": "SC.GRP"})
                except Exception:
                    pass

        # ── 9. 最终打包 ──
        if not data_files:
            QMessageBox.information(self, "无数据",
                f"场景 {sid} 未收集到任何可导出数据。")
            return

        # 在 mod.json 中附加 scene_scope 字段
        metadata['scene_scope'] = [sid]
        mod_json = generate_mod_json(metadata, components)
        mod_json['scene_scope'] = [sid]
        mod_json['scene_name'] = scene_name(self.tkt_scenes, sid)

        fp, _ = QFileDialog.getSaveFileName(
            self, "导出场景为 MOD",
            f"{metadata['id']}.tksmod",
            "TKS MOD (*.tksmod);;所有文件 (*.*)")
        if not fp:
            return
        try:
            pack_tksmod(fp, mod_json, data_files)
            n_mat = len(mat_entries)
            n_du = len(data_files.get('data/TKDefUnit.dat.json', {}).get('modified', []))
            n_tkd = len(data_files.get('data/TKD.dat.json', {}).get('modified', {}))
            has_sc = 'data/SC.GRP.json' in data_files
            summary = (f"场景 {scene_name(self.tkt_scenes, sid)} (ID={sid})\n"
                       f"实体: {n_mat} 条\n"
                       f"DefUnit: {n_du} 条\n"
                       f"脚本: {n_tkd} 块\n"
                       f"SC.GRP: {'包含' if has_sc else '无'}\n\n"
                       f"已保存到:\n{fp}")
            self.status_var.setText(f"已导出场景 MOD: {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", summary)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    @staticmethod
    def _extract_define_id_from_text(text: str) -> str:
        """从 DEFINE 块文本中提取 define_id 字符串"""
        for line in text.split('\n'):
            stripped = line.strip().rstrip('\r')
            if stripped.startswith('DEFINE') and not stripped.startswith('//'):
                parts = stripped.split(None, 2)
                if len(parts) >= 2:
                    return parts[1]
        return ''

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器 (TKMat + TKDefUnit + TKD 三文件联动)"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件"); return

        # 检查是否包含相关数据
        targets = info.get("targets", [])
        has_mat = "TKMat.Dat" in targets
        has_du = "TKDefUnit.Dat" in targets
        has_tkd = "TKD.dat" in targets
        has_sc = "SC.GRP" in targets
        if not has_mat and not has_du and not has_tkd and not has_sc:
            QMessageBox.warning(self, "不兼容",
                "此 MOD 不包含 TKMat/TKDefUnit/TKD/SC.GRP 的数据\n\n"
                f"包含的数据: {', '.join(targets)}"); return

        from PySide6.QtWidgets import QDialog
        dlg = ModImportPreviewDialog(self, info)
        if dlg.exec() != QDialog.Accepted: return

        ref_dir = ask_reference_directory(self, "选择原始游戏目录 (作为基底数据)")
        if not ref_dir: return

        imported_parts = []

        # 导入 TKMat.Dat
        if has_mat:
            mod_json, mat_records = import_tksmod_records(
                fp, ref_dir, "TKMat.Dat",
                rec_size=REC_SIZE, field_count=DWORD_COUNT,
                field_fmt='i', use_lzss=False
            )
            if mat_records is not None:
                new_records = []
                for i, fields in enumerate(mat_records):
                    rec = {'index': i}
                    for di in range(DWORD_COUNT):
                        rec[f'd{di}'] = fields[di] if di < len(fields) else 0
                    new_records.append(rec)
                self.records = new_records
                self._original_mat_records = [list(row) for row in mat_records]
                imported_parts.append(f"TKMat ({len(mat_records)}条)")

        # 导入 TKDefUnit.Dat
        if has_du:
            _, du_records = import_tksmod_records(
                fp, ref_dir, "TKDefUnit.Dat",
                rec_size=DEFUNIT_REC_SIZE, field_count=8,
                field_fmt='H', use_lzss=False
            )
            if du_records is not None and hasattr(self, 'defunit_recs'):
                new_du = []
                for i, fields in enumerate(du_records):
                    rec = {'index': i}
                    for fi in range(8):
                        rec[f'f{fi}'] = fields[fi] if fi < len(fields) else 0
                    new_du.append(rec)
                self.defunit_recs = new_du
                self._original_defunit_recs = [list(row) for row in du_records]
                imported_parts.append(f"TKDefUnit ({len(du_records)}条)")

        # 导入 TKD.dat
        if has_tkd:
            _, defines = import_tksmod_text_defines(fp, ref_dir)
            if defines is not None and hasattr(self, 'tkd_defines'):
                # 将 defines dict 转化为编辑器内部 tkd_defines 格式
                new_tkd = []
                for did_str, content in sorted(defines.items(),
                        key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                    lines = content.split('\r\n') if '\r\n' in content else content.split('\n')
                    header_line = lines[0] if lines else ''
                    body_lines = lines[1:] if len(lines) > 1 else []
                    new_tkd.append({
                        'define_id': int(did_str) if did_str.isdigit() else 0,
                        'header_line': header_line,
                        'body_lines': body_lines,
                    })
                self.tkd_defines = new_tkd
                self.tkd_define_map = {dd['define_id']: dd for dd in new_tkd}
                self._original_tkd_defines = dict(defines)
                imported_parts.append(f"TKD ({len(new_tkd)}块)")
                # 刷新脚本编辑器
                self._current_edit_define_id = None

        # 导入 SC.GRP（只存入内存，等用户保存时才写入文件）
        if has_sc:
            # 先加载原始块列表，再应用diff
            from editor_utils.mod_exporter import load_grp_raw_sections
            ref_sc_path = os.path.join(ref_dir, "SC.GRP")
            sc_blocks = load_grp_raw_sections(ref_sc_path)
            if sc_blocks is not None:
                # 检查 scene_scope 中是否有超出原始范围的场景索引
                scene_scope = info.get('scene_scope', [])
                if scene_scope:
                    max_idx = max(scene_scope)
                    # 扩展 sc_blocks 数组以容纳最大索引
                    while len(sc_blocks) <= max_idx:
                        sc_blocks.append(b'')  # 空区段占位
                
                # 现在应用 diff
                import zipfile, json, base64 as b64
                with zipfile.ZipFile(fp, 'r') as zf:
                    mod_json = json.loads(zf.read('mod.json'))
                    sc_diff_data = None
                    for comp in mod_json.get('components', []):
                        if comp.get('target') == 'SC.GRP':
                            internal = comp.get('file', '')
                            if internal:
                                sc_diff_data = json.loads(zf.read(internal))
                                break
                
                if sc_diff_data:
                    for entry in sc_diff_data.get('modified', []):
                        idx = entry.get('index', -1)
                        data_b64 = entry.get('data_b64', '')
                        if 0 <= idx < len(sc_blocks) and data_b64:
                            sc_blocks[idx] = b64.b64decode(data_b64)
                
                self._sc_grp_pending = sc_blocks
                self._sc_grp_section_count = len(sc_blocks)
                imported_parts.append(f"SC.GRP ({len(sc_blocks)}区段, 待保存)")

        if not imported_parts:
            QMessageBox.warning(self, "导入失败",
                "无法导入任何数据。\n请确认参考目录中包含有效的游戏文件"); return

        self._dirty = bool(has_sc)  # 有 SC.GRP 待保存则标记为 dirty
        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "type": info.get("type", "data"),
            "mode": info.get("mode", "mixed"),
            "load_order": info.get("load_order", 100),
        }

        self._apply_filter()
        self._vis_populate_scenes()

        # 自动跳转到导入的场景 (scene_scope)
        scene_scope = info.get('scene_scope', [])
        if scene_scope:
            target_sid = scene_scope[0]
        else:
            target_sid = self._vis_scene_id  # 保持原场景

        if target_sid is not None and target_sid >= 0:
            self._vis_scene_id = target_sid
            # 同步 combo 和 tree 的选中状态（阻止信号避免触发 _on_vis_combo_select）
            self._vis_scene_combo.blockSignals(True)
            for i in range(self._vis_scene_combo.count()):
                if self._vis_scene_combo.itemText(i).startswith(f"{target_sid}:"):
                    self._vis_scene_combo.setCurrentIndex(i)
                    break
            self._vis_scene_combo.blockSignals(False)
            self.scene_tree.blockSignals(True)
            for i in range(self.scene_tree.topLevelItemCount()):
                item = self.scene_tree.topLevelItem(i)
                if item and item.text(0) == str(target_sid):
                    self.scene_tree.setCurrentItem(item)
                    break
            self.scene_tree.blockSignals(False)

        self._vis_load_scene()
        self.status_var.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{', '.join(imported_parts)}")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"导入内容: {', '.join(imported_parts)}\n\n"
            f"您现在可以继续编辑并重新导出。")

    # =========== 脚本编辑 ===========
    def _save_editor_to_define(self):
        if self._current_edit_define_id is None:
            return
        text = self.script_text.toPlainText()
        d = self.tkd_define_map.get(self._current_edit_define_id)
        if d is None:
            d = {'define_id': self._current_edit_define_id, 'comment': '', 'prefix_lines': [],
                 'body_lines': [], 'line_start': -1, 'line_end': -1,
                 'header_line': f'DEFINE {self._current_edit_define_id}'}
            for line in text.split('\n'):
                s = line.strip()
                if s.startswith('};'):
                    d['comment'] = s[2:].replace(' end', '').strip()
                    break
            self.tkd_defines.append(d)
            self.tkd_define_map[self._current_edit_define_id] = d
        d['body_lines'] = text.split('\n')
        for line in reversed(d['body_lines']):
            s = line.strip()
            if s.startswith('};'):
                d['comment'] = s[2:].replace(' end', '').strip()
                break

    def _load_define_to_editor(self, define_id):
        self._current_edit_define_id = define_id
        self.script_text.setReadOnly(False)
        # 阻止信号，避免 setPlainText 触发 _on_script_edit
        self.script_text.blockSignals(True)
        self.script_text.clear()
        d = self.tkd_define_map.get(define_id)
        if d:
            self.script_text.setPlainText('\n'.join(d.get('body_lines', [])))
            comment = d.get('comment', '')
            self.script_info_lbl.setText(f"DEFINE {define_id}" + (f" — {comment}" if comment else ""))
        else:
            self.script_text.setPlainText('{\nEnd(0)\n}; end\n')
            self.script_info_lbl.setText(f"DEFINE {define_id} (新建)")
        self.script_text.blockSignals(False)
        self._apply_syntax_highlight()
        self._update_line_preview()
        self._script_dirty = False

    def _clear_script_editor(self):
        self._save_editor_to_define()
        self.script_text.setReadOnly(False)
        self.script_text.blockSignals(True)
        self.script_text.clear()
        self.script_text.blockSignals(False)
        self.script_text.setReadOnly(True)
        self.script_preview.clear()
        self._current_edit_define_id = None
        self.script_info_lbl.setText("(未选中 DEFINE)")

    def _on_script_edit(self):
        self._script_dirty = True
        if self._edit_debounce:
            self._edit_debounce.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._do_script_update)
        timer.start(150)
        self._edit_debounce = timer

    def _do_script_update(self):
        self._apply_syntax_highlight()

    def _apply_syntax_highlight(self):
        """语法高亮 — 逻辑对应 mat_editor.py _apply_syntax_highlight。
        实际逐行高亮由 ScriptSyntaxHighlighter 自动完成, 此处触发一次整文档重涂。"""
        if hasattr(self, '_script_highlighter') and self._script_highlighter:
            self._script_highlighter.rehighlight()

    def _update_line_preview(self):
        """更新右侧行功能预览 (带颜色分类) — 解析与着色逻辑对应 mat_editor.py _update_line_preview"""
        content = self.script_text.toPlainText()
        lines = content.split('\n')
        self.script_preview.clear()
        cursor = self.script_preview.textCursor()

        # 颜色格式 (对应 v1 的 pv_* tag); 灰色系在深色背景 #1a1e27 上对比度不足,
        # 深色模式提亮并复用本主题 QSS 既有灰阶 (#dcdcdc/#a5b0cb/#8a96b3), 浅色保持 v1 原值
        def mkfmt(color):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            return f
        dark = self._is_dark
        # 深色配色优化: 背景 #1a1e27 上彩色类提亮至对比度>=4.5:1 且与左侧高亮器色板语义一致
        # (白=普通命令, 紫=对话, 蓝=流程, 橙=分支, 红=道具, 绿=场景/队员); 灰阶类按
        # comment>block>raw 分层, 注释/未识别弱化以突出命令行
        fmt_cmd     = mkfmt('#333333' if not dark else '#dcdcdc')  # pv_cmd   普通命令(深色=白色)
        fmt_talk    = mkfmt('#7B30D0' if not dark else '#b884ff')  # pv_talk  对话
        fmt_flow    = mkfmt('#0066CC' if not dark else '#5b8aff')  # pv_flow  流程
        fmt_branch  = mkfmt('#CC6600' if not dark else '#e0a040')  # pv_branch 分支
        fmt_getitem = mkfmt('#CC0000' if not dark else '#ff7b7b')  # pv_getitem 道具
        fmt_scene   = mkfmt('#008800' if not dark else '#6ab04c')  # pv_scene  场景/队员
        fmt_comment = mkfmt('#AAA'    if not dark else '#6a7590')  # pv_comment 注释(弱化)
        fmt_block   = mkfmt('#BBB'    if not dark else '#7a86a8')  # pv_block  块/DEFINE
        fmt_raw     = mkfmt('#999'    if not dark else '#5a6480')  # pv_raw   未识别(最弱)

        def trunc(s, max_len=28):
            s = s.replace('\n', ' ').replace('\r', '')
            if len(s) <= max_len:
                return s
            return s[:max_len - 1] + '…'

        talk_cmds = {'TalkB', 'TalkA', 'SetTalkB', 'BlackTalk', 'ShowText', 'MenuChoice',
                     'SysTalk', 'DoTalkB', 'MenuTalk', 'SetHint'}
        flow_cmds = {'End', 'Yield', 'Jump', 'Else', 'SetNowDef'}
        branch_cmds = {'CheckFlag', 'CheckResult', 'CheckItem', 'CheckTeam', 'CheckMember',
                       'Switch', 'Random'}

        for i, line in enumerate(lines):
            stripped = line.strip()
            if i > 0:
                cursor.insertText('\n')
            if not stripped:
                continue
            if stripped.startswith('//'):
                cursor.insertText(trunc(stripped), fmt_comment)
                continue
            if stripped in ('{', '}; end') or stripped.startswith('};'):
                cursor.insertText(trunc(stripped), fmt_block)
                continue
            if stripped.startswith('DEFINE'):
                cursor.insertText(trunc(stripped), fmt_block)
                continue
            m = re.match(r'([A-Za-z_]\w*)\s*\((.*)\)', stripped)
            if m:
                cmd_name = m.group(1)
                args_str = m.group(2).strip()
                args = [a.strip() for a in args_str.split(',') if a.strip()] if args_str else []
                desc = self._format_cmd_desc(cmd_name, args)
                fmt = fmt_cmd
                if cmd_name in talk_cmds:
                    fmt = fmt_talk
                elif cmd_name in flow_cmds:
                    fmt = fmt_flow
                elif cmd_name in branch_cmds:
                    fmt = fmt_branch
                elif cmd_name == 'GetItem':
                    fmt = fmt_getitem
                elif cmd_name in ('TeamMember', 'ChangeScene'):
                    fmt = fmt_scene
                cursor.insertText(trunc(desc), fmt)
            else:
                m2 = re.match(r'([A-Za-z_]\w+)\s*$', stripped)
                if m2 and m2.group(1) in SCRIPT_CMD_DESC:
                    desc = self._format_cmd_desc(m2.group(1), [])
                    cursor.insertText(trunc(desc), fmt_cmd)
                else:
                    cursor.insertText(trunc(stripped, 40), fmt_raw)

    def _format_cmd_desc(self, cmd_name, args):
        desc_fn = SCRIPT_CMD_DESC.get(cmd_name)
        if desc_fn:
            try:
                return desc_fn(args, self.tkt_all, self.item_names)
            except TypeError:
                try:
                    return desc_fn(args, self.tkt_all)
                except Exception:
                    pass
            except Exception:
                pass
        args_str = ', '.join(args) if args else ''
        return f"{cmd_name}({args_str})"

    # =========== DefUnit 链 ===========
    def _refresh_chain_list(self):
        self.chain_tree.clear()
        if not self.records:
            return
        rec = None
        if hasattr(self, '_current_param_idx') and self._current_param_idx is not None:
            if 0 <= self._current_param_idx < len(self.records):
                rec = self.records[self._current_param_idx]
        if not rec or not has_data(rec):
            self._clear_script_editor()
            self._update_sched_info(None)
            return
        entity_id = rec['index']

        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0)
            mx = rec.get(f'd{mx_di}', 0)
            cur = rec.get(f'd{cur_di}', 0)
            if h <= 0 or mx <= 0:
                continue
            cur_str = f'当前={cur}' if cur > 0 else '未激活'
            # Group header
            group_item = QTreeWidgetItem([f'{sub_name}链', '', '', '', '', f'head=#{h} max={mx} {cur_str}'])
            group_item.setForeground(0, QColor("#3366cc"))
            self.chain_tree.addTopLevelItem(group_item)
            # Traverse chain (with loop detection)
            idx = h
            visited_chain = set()
            for step in range(mx):
                if idx in visited_chain:
                    # 循环检测: 标记循环节点
                    loop_item = QTreeWidgetItem([f'  {sub_name}', str(step + 1), f'(循环→{idx})', '', '', '⚠循环'])
                    loop_item.setForeground(0, QColor("#CC0000"))
                    self.chain_tree.addTopLevelItem(loop_item)
                    break
                visited_chain.add(idx)
                du_rec = next((r for r in self.defunit_recs if r['index'] == idx), None)
                if du_rec is None:
                    # 空槽检测
                    empty_item = QTreeWidgetItem([f'  {sub_name}', str(step + 1), f'#{idx}(空槽)', '', '', '⚠断开'])
                    empty_item.setForeground(0, QColor("#CC6600"))
                    self.chain_tree.addTopLevelItem(empty_item)
                    break
                define_id = (du_rec['f1'] << 16) | du_rec['f0']
                marks = []
                if (step + 1) == cur:
                    marks.append('当前')
                if step == 0:
                    marks.append('链头')
                child = QTreeWidgetItem([f'  {sub_name}', str(step + 1), str(idx), str(define_id), str(du_rec['f0']), ','.join(marks)])
                self.chain_tree.addTopLevelItem(child)
                idx = du_rec['f6']
                if idx == 0:
                    break

        total = self.chain_tree.topLevelItemCount()
        self.chain_info_lbl.setText(f"entity={entity_id}, {total} 条节点")
        if total == 0:
            self._clear_script_editor()
            self.script_info_lbl.setText("(无关联 DEFINE)")
        else:
            for i in range(self.chain_tree.topLevelItemCount()):
                item = self.chain_tree.topLevelItem(i)
                if item.text(2).isdigit():
                    self.chain_tree.setCurrentItem(item)
                    self._on_chain_select()
                    break
        self._update_sched_info(rec)

    def _on_chain_select(self):
        sel = self.chain_tree.selectedItems()
        if not sel:
            return
        item = sel[0]
        du_str = item.text(2)
        define_str = item.text(3)
        if not du_str.isdigit() or not define_str.isdigit():
            return
        define_id = int(define_str)
        du_idx = int(du_str)
        self._save_editor_to_define()
        self._load_define_to_editor(define_id)
        self.chain_info_lbl.setText(f"DefUnit #{du_idx} → DEFINE {define_id}")

    def _add_chain_entry(self, sub_scene):
        rec = None
        if hasattr(self, '_current_param_idx') and self._current_param_idx is not None:
            if 0 <= self._current_param_idx < len(self.records):
                rec = self.records[self._current_param_idx]
        if not rec or not has_data(rec):
            return
        entity_id = rec['index']

        # Find empty DefUnit slot
        empty_idx = None
        for i in range(DEFUNIT_REC_COUNT):
            existing = next((r for r in self.defunit_recs if r['index'] == i), None)
            if existing is None:
                empty_idx = i
                break
        if empty_idx is None:
            QMessageBox.information(self, "无空槽", f"TKDefUnit.dat 所有 {DEFUNIT_REC_COUNT} 条记录均已占用")
            return

        existing_blocks = [r['f0'] for r in self.defunit_recs if r['f1'] == entity_id and r['f0'] >= 256]
        new_f0 = max(existing_blocks) + 1 if existing_blocks else 256
        if new_f0 > 266:
            new_f0 = max(existing_blocks) + 1
        define_id = (entity_id << 16) | new_f0

        new_rec = {'index': empty_idx, 'f0': new_f0, 'f1': entity_id,
                   'f2': 0, 'f3': 0, 'f4': 0, 'f5': 0, 'f6': 0, 'f7': 0}
        self.defunit_recs.append(new_rec)
        self.defunit_entity.setdefault(entity_id, []).append(empty_idx)

        h_di, mx_di, cur_di = {'A': (39, 30, 33), 'B': (40, 31, 34), 'C': (41, 32, 35)}[sub_scene]
        head = rec.get(f'd{h_di}', 0)
        mx = rec.get(f'd{mx_di}', 0)
        if head == 0 or mx == 0:
            rec[f'd{h_di}'] = empty_idx
            rec[f'd{mx_di}'] = 1
            rec[f'd{cur_di}'] = 1
        else:
            idx = head
            tail = head
            for _ in range(mx):
                du_r = next((r for r in self.defunit_recs if r['index'] == idx), None)
                if du_r is None or du_r['f6'] == 0:
                    break
                idx = du_r['f6']
                tail = idx
            du_tail = next((r for r in self.defunit_recs if r['index'] == tail), None)
            if du_tail:
                du_tail['f6'] = empty_idx
            rec[f'd{mx_di}'] = mx + 1

        if define_id not in self.tkd_define_map:
            d = {'define_id': define_id, 'comment': '', 'prefix_lines': [],
                 'body_lines': ['{', 'End(0)', '}; end'], 'line_start': -1, 'line_end': -1,
                 'header_line': f'DEFINE {define_id}'}
            self.tkd_defines.append(d)
            self.tkd_define_map[define_id] = d

        self._dirty = True
        self._script_dirty = True
        self._sync_form_dwords(rec, (h_di, mx_di, cur_di))
        self._refresh_chain_list()
        QMessageBox.information(self, "新增成功", f"DefUnit #{empty_idx} → DEFINE {define_id} ({sub_scene}场景)")

    def _delete_chain_entry(self):
        sel = self.chain_tree.selectedItems()
        if not sel:
            return
        item = sel[0]
        du_str = item.text(2)
        define_str = item.text(3)
        if not du_str.isdigit() or not define_str.isdigit():
            return
        du_idx = int(du_str)
        define_id = int(define_str)
        du_rec = next((r for r in self.defunit_recs if r['index'] == du_idx), None)
        if du_rec is None:
            return
        entity_id = du_rec['f1']
        if QMessageBox.question(self, "确认删除",
                                f"删除 DefUnit #{du_idx} → DEFINE {define_id}?\n此操作同时从 TKD.dat 删除对应 DEFINE 块。",
                                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return

        rec = self.records[self._current_param_idx]
        _modified_dis = []
        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0)
            mx = rec.get(f'd{mx_di}', 0)
            if h <= 0:
                continue
            prev = None
            idx = h
            for _ in range(mx):
                if idx == du_idx:
                    break
                prev = idx
                du_r = next((r for r in self.defunit_recs if r['index'] == idx), None)
                idx = du_r['f6'] if du_r else 0
            if idx != du_idx:
                continue
            if prev is None:
                rec[f'd{h_di}'] = du_rec['f6']
            else:
                prev_rec = next((r for r in self.defunit_recs if r['index'] == prev), None)
                if prev_rec:
                    prev_rec['f6'] = du_rec['f6']
            rec[f'd{mx_di}'] = max(0, mx - 1)
            cur = rec.get(f'd{cur_di}', 0)
            if cur > mx - 1:
                rec[f'd{cur_di}'] = max(1, mx - 1)
            _modified_dis = [h_di, mx_di, cur_di]
            break

        du_rec['f0'] = du_rec['f1'] = du_rec['f6'] = 0
        self.defunit_recs = [r for r in self.defunit_recs if r['index'] != du_idx]
        if entity_id in self.defunit_entity and du_idx in self.defunit_entity[entity_id]:
            self.defunit_entity[entity_id].remove(du_idx)
        if define_id in self.tkd_define_map:
            d = self.tkd_define_map.pop(define_id)
            if d in self.tkd_defines:
                self.tkd_defines.remove(d)

        self._dirty = True
        self._script_dirty = True
        if _modified_dis:
            self._sync_form_dwords(rec, _modified_dis)
        self.script_text.setReadOnly(False)
        self.script_text.blockSignals(True)
        self.script_text.clear()
        self.script_text.blockSignals(False)
        self.script_text.setReadOnly(True)
        self._current_edit_define_id = None
        self._refresh_chain_list()

    def _sync_form_dwords(self, rec, dis):
        for di in dis:
            val = str(rec[f'd{di}'])
            for fields in (ALL_EDIT_FIELDS, RUNTIME_FIELDS):
                for key, f_di, label, cmt in fields:
                    if f_di == di and key in self._edit_vars:
                        w = self._edit_vars[key]
                        if isinstance(w, QLineEdit):
                            w.setText(val)
                        break
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                w = self._edit_vars.get(key)
                if isinstance(w, QLineEdit):
                    w.setText(val)
                    break

    # =========== 脚本调度信息 ===========
    def _update_sched_info(self, rec):
        if rec is None or is_empty(rec):
            for key in self._sched_labels:
                self._sched_labels[key].setText("")
            return
        flags = rec.get('d2', 0)
        tval = rec.get('d0', 0)
        en = (flags & 1) != 0
        self._sched_labels['enabled'].setText("✓ 已启用" if en else "✗ 未启用")
        self._sched_labels['enabled'].setProperty("status", "loaded" if en else "missing")
        self._sched_labels['enabled'].style().unpolish(self._sched_labels['enabled'])
        self._sched_labels['enabled'].style().polish(self._sched_labels['enabled'])
        pk = (flags & 4) != 0
        self._sched_labels['pickable'].setText("✓ 可交互" if pk else "✗ 不可交互")
        tick = rec.get('d4', 0)
        self._sched_labels['tick'].setText(f"{tick} (越大越慢)" if tick > 0 else "0 (无Tick)")
        timer = rec.get('d3', 0)
        self._sched_labels['timer'].setText(f"{timer} (暂停中)" if timer > 0 else "0 (正常运行)")
        cur_a = rec.get('d33', 0)
        head_a = rec.get('d39', 0)
        max_a = rec.get('d30', 0)
        if head_a > 0 and max_a > 0:
            a_status = "⚡ 自动执行中" if cur_a > 0 else "已定义(未激活)"
            self._sched_labels['chain_a'].setText(f"✓ {a_status} [head=#{head_a},max={max_a},cur={cur_a}]")
        else:
            self._sched_labels['chain_a'].setText("— 无")
        cur_b = rec.get('d34', 0)
        head_b = rec.get('d40', 0)
        max_b = rec.get('d31', 0)
        if head_b > 0 and max_b > 0:
            b_status = "👆 交互触发" if cur_b > 0 else "已定义(未激活)"
            self._sched_labels['chain_b'].setText(f"✓ {b_status} [head=#{head_b},max={max_b},cur={cur_b}]")
        else:
            self._sched_labels['chain_b'].setText("— 无")
        cur_c = rec.get('d35', 0)
        head_c = rec.get('d41', 0)
        max_c = rec.get('d32', 0)
        if head_c > 0 and max_c > 0:
            c_status = "✱ 活跃" if cur_c > 0 else "已定义(未激活)"
            self._sched_labels['chain_c'].setText(f"✓ {c_status} [head=#{head_c},max={max_c},cur={cur_c}]")
        else:
            self._sched_labels['chain_c'].setText("— 无")
        trigger_map = {
            5: "仅脚本", 10: "接近传送", 15: "接近触发", 16: "接近遇敌",
            20: "点击对话", 110: "点击机关", 200: "点击对话",
        }
        trigger = trigger_map.get(tval, "未知")
        if cur_a > 0:
            trigger += " + A链自动(Tick)"
        self._sched_labels['trigger'].setText(trigger)

    # =========== 脚本预览 ===========
    def _preview_script(self):
        self._save_editor_to_define()
        if self._current_edit_define_id is None:
            QMessageBox.information(self, "预览", "请先选择一个 DEFINE 脚本块")
            return
        d = self.tkd_define_map.get(self._current_edit_define_id)
        if d is None:
            QMessageBox.information(self, "预览", "未找到当前 DEFINE 数据")
            return
        body_lines = d.get('body_lines', [])
        commands = self._parse_script_commands(body_lines)
        if not commands:
            QMessageBox.information(self, "预览", "未解析到有效命令")
            return
        self._preview_cmds = commands
        self._preview_step = 0

        win = QDialog(self)
        win.setWindowTitle(f"脚本预览 — DEFINE {self._current_edit_define_id}")
        win.resize(780, 680)
        # 图标
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            win.setWindowIcon(QIcon(ico))
        main_layout = QVBoxLayout(win)

        # 顶部信息栏
        info_row = QHBoxLayout()
        comment = d.get('comment', '')
        info_text = f"DEFINE {self._current_edit_define_id}"
        if comment:
            info_text += f"  —  {comment}"
        info_text += f"  |  {len(commands)} 条命令"
        info_lbl = QLabel(info_text)
        info_lbl.setProperty("class", "InfoTitle")
        info_row.addWidget(info_lbl, 1)
        self._pv_info_lbl = QLabel("")
        info_row.addWidget(self._pv_info_lbl)
        main_layout.addLayout(info_row)

        # 命令列表 + 详情面板 (垂直分割)
        splitter = QSplitter(Qt.Vertical)

        # 命令列表 (带颜色标签)
        self._pv_tree = QTreeWidget()
        self._pv_tree.setHeaderLabels(["#", "命令", "描述"])
        self._pv_tree.setColumnWidth(0, 35)
        self._pv_tree.setColumnWidth(1, 110)
        self._pv_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._pv_tree.setRootIsDecorated(False)

        # 填充命令 (带颜色分类)
        talk_cmds = {'TalkB', 'TalkA', 'BlackTalk', 'ShowText', 'MenuChoice',
                     'SysTalk', 'SetTalkB', 'SetHint', 'DoTalkB', 'MenuTalk'}
        flow_cmds = {'End', 'Yield', 'Jump', 'Else'}
        branch_cmds = {'CheckFlag', 'CheckResult', 'CheckItem', 'CheckTeam',
                       'CheckMember', 'Switch', 'Random'}
        # 配色与右侧行预览 (_update_line_preview) 统一, 按主题切换深/浅色板
        dark = self._is_dark
        c_talk    = QColor('#7B30D0' if not dark else '#b884ff')   # 紫=对话
        c_flow    = QColor('#0066CC' if not dark else '#5b8aff')   # 蓝=流程
        c_branch  = QColor('#CC6600' if not dark else '#e0a040')   # 橙=分支
        c_getitem = QColor('#CC0000' if not dark else '#ff7b7b')   # 红=道具
        c_default = QColor('#333333' if not dark else '#dcdcdc')   # 普通命令(深色=白色)
        for si, (cmd_name, args, line_text, line_idx) in enumerate(commands):
            desc = self._format_cmd_desc(cmd_name, args)
            item = QTreeWidgetItem([str(si + 1), cmd_name, desc])
            # 颜色分类
            if cmd_name in talk_cmds:
                color = c_talk
            elif cmd_name in flow_cmds:
                color = c_flow
            elif cmd_name in branch_cmds:
                color = c_branch
            elif cmd_name == 'GetItem':
                color = c_getitem
            else:
                color = c_default
            for c in range(3):
                item.setForeground(c, color)
            item.setData(0, Qt.UserRole, si)  # 存储步骤索引
            self._pv_tree.addTopLevelItem(item)

        splitter.addWidget(self._pv_tree)

        # 详情面板 (QTextEdit 支持富文本颜色)
        self._pv_detail = QTextEdit()
        self._pv_detail.setReadOnly(True)
        self._pv_detail.setFont(QFont("Consolas", 10))
        # 预配置 FCOLOR 1-32 颜色格式
        self._pv_color_formats = {}
        for ci in range(1, 33):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(GAME_COLORS[ci]))
            self._pv_color_formats[f'tkt_c{ci}'] = fmt
        # 物品名红色格式
        self._pv_item_red_fmt = QTextCharFormat()
        self._pv_item_red_fmt.setForeground(QColor("#FF4444"))
        self._pv_item_red_fmt.setFontWeight(QFont.Bold)
        # 动态 FCOLORD 格式缓存
        self._pv_dynamic_color_tags = {}
        splitter.addWidget(self._pv_detail)
        splitter.setSizes([380, 200])
        main_layout.addWidget(splitter, 1)

        # 选中事件
        self._pv_tree.itemSelectionChanged.connect(self._preview_on_select)
        # 选中第一步
        if self._pv_tree.topLevelItemCount() > 0:
            self._pv_tree.setCurrentItem(self._pv_tree.topLevelItem(0))

        self._preview_win = win
        win.exec()

    def _preview_on_select(self):
        """预览窗口: 选中命令 → 更新详情面板"""
        sel = self._pv_tree.selectedItems()
        if not sel:
            return
        step = sel[0].data(0, Qt.UserRole)
        if step is None:
            return
        self._preview_step = step
        if 0 <= step < len(self._preview_cmds):
            cmd_name, args, line_text, _ = self._preview_cmds[step]
            self._pv_detail.clear()
            self._pv_detail.append(f"<b>原始:</b> {line_text}")
            self._pv_detail.append(f"<b>命令:</b> {cmd_name}({', '.join(args)})")
            self._pv_detail.append(f"<b>描述:</b> {self._format_cmd_desc(cmd_name, args)}")
            # 对话命令: 解析 TKT 文本并用颜色渲染
            if cmd_name in ('TalkB', 'TalkA', 'SetTalkB', 'BlackTalk') and len(args) >= 2:
                text_idx = 0 if cmd_name == 'BlackTalk' else 1
                tkt_text = _tkt_text(self.tkt_all, args[text_idx], max_len=500)
                if tkt_text:
                    self._pv_detail.append(f"\n<b>━━━ TKT 对话文本 (ID={args[text_idx]}) ━━━</b>")
                    self._insert_colored_tkt(tkt_text)
            elif cmd_name in ('ShowText', 'MenuTalk', 'SysTalk') and args:
                tkt_text = _tkt_text(self.tkt_all, args[0], max_len=500)
                if tkt_text:
                    self._pv_detail.append(f"\n<b>━━━ TKT 对话文本 (ID={args[0]}) ━━━</b>")
                    self._insert_colored_tkt(tkt_text)
            # GetItem: 物品名称用红色显示
            if cmd_name == 'GetItem' and args and self.item_names:
                try:
                    item_id = int(args[0])
                    item_name = self.item_names.get(item_id, '')
                    if item_name:
                        self._pv_detail.append(f"\n<b>━━━ 物品名称 (ID={args[0]}) ━━━</b>")
                        cursor = self._pv_detail.textCursor()
                        cursor.movePosition(QTextCursor.End)
                        cursor.insertText(item_name, self._pv_item_red_fmt)
                except (ValueError, TypeError):
                    pass
            # 更新信息标签
            self._pv_info_lbl.setText(f"步骤 {step+1}/{len(self._preview_cmds)}")
        # 高亮当前步骤 (黄色背景)
        for i in range(self._pv_tree.topLevelItemCount()):
            item = self._pv_tree.topLevelItem(i)
            si = item.data(0, Qt.UserRole)
            if si == step:
                for c in range(3):
                    item.setBackground(c, QColor("#FFEE88") if not self._is_dark else QColor("#5a5520"))
            else:
                for c in range(3):
                    item.setBackground(c, QColor("transparent"))

    def _insert_colored_tkt(self, text):
        """将含 <FCOLOR,n> 等标签的 TKT 文本按颜色分段插入详情面板"""
        segments = parse_tkt_colored_segments(text)
        cursor = self._pv_detail.textCursor()
        cursor.movePosition(QTextCursor.End)
        for seg_text, color in segments:
            fmt = self._get_tkt_color_format(color)
            cursor.insertText(seg_text, fmt)

    def _get_tkt_color_format(self, color_hex):
        """获取 TKT 颜色的 QTextCharFormat。FCOLOR 1-32 用预配置, FCOLORD 动态创建"""
        for ci in range(1, 33):
            if GAME_COLORS[ci] == color_hex:
                return self._pv_color_formats[f'tkt_c{ci}']
        # FCOLORD 动态颜色
        if color_hex not in self._pv_dynamic_color_tags:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color_hex))
            self._pv_dynamic_color_tags[color_hex] = fmt
        return self._pv_dynamic_color_tags[color_hex]

    def _parse_script_commands(self, body_lines):
        commands = []
        for i, line in enumerate(body_lines):
            stripped = line.strip()
            if not stripped or stripped.startswith('//') or stripped.startswith('{') or stripped.startswith('}'):
                continue
            if stripped.startswith('DEFINE'):
                continue
            m = re.match(r'([A-Za-z_]\w*)\s*\((.*)\)', stripped)
            if m:
                cmd_name = m.group(1)
                args_str = m.group(2).strip()
                args = [a.strip() for a in args_str.split(',') if a.strip()] if args_str else []
                commands.append((cmd_name, args, stripped, i))
            elif stripped and not stripped.startswith('//'):
                m2 = re.match(r'([A-Za-z_]\w+)\s*$', stripped)
                if m2 and m2.group(1) in SCRIPT_CMD_DESC:
                    commands.append((m2.group(1), [], stripped, i))
        return commands

    # =========== 删除场景 ===========
    def _delete_scene(self):
        sid = self._vis_scene_id
        sname = scene_name(self.tkt_scenes, sid)
        scene_entities = [r for r in self.records if has_data(r) and r['d1'] == sid]
        if not scene_entities:
            QMessageBox.information(self, "空场景", f"场景 {sname} (ID={sid}) 无实体, 无需删除")
            return
        n = len(scene_entities)
        if QMessageBox.question(self, "确认删除场景",
                                f"将删除场景 {sname} (ID={sid})\n\n  TKMat 实体: {n} 个\n\n此操作不可撤销!",
                                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        all_du_indices = set()
        all_define_ids = set()
        for rec in scene_entities:
            for di in [39, 40, 41]:
                head = rec.get(f'd{di}', -1)
                if head < 0:
                    continue
                cur = head
                visited = set()
                while cur >= 0 and cur not in visited:
                    visited.add(cur)
                    du = next((r for r in self.defunit_recs if r['index'] == cur), None)
                    if du is None:
                        break
                    all_du_indices.add(cur)
                    did = (du.get('f1', 0) << 16) | du.get('f0', 0)
                    if did > 0:
                        all_define_ids.add(did)
                    nxt = du.get('f6', 0)
                    if nxt == 0 or nxt in visited:
                        break
                    cur = nxt
        for did in all_define_ids:
            if did in self.tkd_define_map:
                d = self.tkd_define_map.pop(did)
                if d in self.tkd_defines:
                    self.tkd_defines.remove(d)
        self.defunit_recs = [r for r in self.defunit_recs if r['index'] not in all_du_indices]
        for rec in scene_entities:
            for di in range(DWORD_COUNT):
                rec[f'd{di}'] = 0
        self._dirty = True
        self._script_dirty = True
        self._apply_filter()
        self._vis_populate_scenes()
        self._vis_load_scene()
        QMessageBox.information(self, "删除完成",
                                f"已删除场景 {sname} (ID={sid})\n实体: {n} 个\nDefUnit: {len(all_du_indices)} 条\nDEFINE: {len(all_define_ids)} 个")

    # =========== 统计/导出/导入 ===========
    def _show_stats(self):
        if not self.records:
            return
        tc = Counter()
        sc = Counter()
        for r in self.records:
            if has_data(r):
                tc[r['d0']] += 1
                sc[r['d1']] += 1
        ne = sum(tc.values())
        msg = f"TKMat.Dat 统计\n{'─' * 40}\n总槽位:{REC_COUNT} | 有效:{ne} | 空:{REC_COUNT - ne}\n场景数:{len(sc)}\n\n类型分布:\n"
        for tval in sorted(tc.keys()):
            msg += f"  {tval}-{ENTITY_TYPES.get(tval, '?')}: {tc[tval]} ({tc[tval] / ne * 100:.1f}%)\n"
        QMessageBox.information(self, "统计信息", msg)

    def _export_csv(self):
        if not self.records: return
        filtered = [r for r in self.records if has_data(r)]
        hdr = ['index'] + [f'd{i}' for i in range(DWORD_COUNT)] + ['type_name', 'scene_name']
        def row_func(rec):
            return [str(rec['index'])] + [str(rec[f'd{di}']) for di in range(DWORD_COUNT)] + \
                   [ENTITY_TYPES.get(rec['d0'], ''), scene_name(self.tkt_scenes, rec['d1'])]
        export_csv(self, filtered, hdr, row_func, "TKMat.csv")

    def _show_field_ref(self):
        msg = ("TKMat.Dat 实体表字段说明\n" + '─' * 50 + "\n\n加载: sub_412688:21\n结构: 6000条×384B(96×int32)\n\n已证实字段:\n"
               " [0]type [1]scene_id [2]flags [3]timer [4]tick\n [10][11]x/y [13]direction [18][19]bound\n"
               " [30-35]sub-scene [39-41]chain heads [42-43]PC [44]defunit_idx\n"
               " [50]条件角色 [51]访问掩码 [52]目标场景 [53]目标X [54]目标Y [56]目标朝向\n"
               "注意: [52-56]字段语义与实体类型相关 (type=10: 传送参数; type=200: 动画参数)")
        QMessageBox.information(self, "字段说明", msg)

    def _show_about(self):
        QMessageBox.information(self, "关于",
                                "TKMat.Dat 地图实体编辑器 v2.3 (PySide6)\n\n"
                                "模式: 参数 + 可视化 + 脚本编辑 + 脚本调度分析\n"
                                "逆向依据: sub_412688, sub_405CBC, sub_4066F0, sub_40EBD4, sub_409618\n"
                                "脚本调度: A链=自动(Tick) B链=触发(交互) C链=其他\n"
                                "格式: TKMat 6000×384B + TKDefUnit 5000×16B + TKD脚本\n"
                                "保存时一次性写入三个文件")

    def _export_scene(self):
        """导出当前场景: TKMat实体 + DefUnit链 + TKD脚本 → .tkmat JSON"""
        if not self.records:
            QMessageBox.warning(self, "无数据", "请先加载 TKS 目录")
            return
        sid = self._vis_scene_id
        if self._sc_grp_section_count > 0 and sid >= self._sc_grp_section_count:
            QMessageBox.warning(self, "虚拟场景", "虚拟场景没有对应的 SC.GRP 数据, 不允许导出。")
            return
        scene_entities = [r for r in self.records if has_data(r) and r['d1'] == sid]
        if not scene_entities:
            QMessageBox.warning(self, "空场景", f"场景 {sid} 无实体数据")
            return

        tkt_scene_text = None
        if self.tkt_all:
            tkt_id = sid + 300
            tkt_scene_text = self.tkt_all.get(tkt_id, '')

        sc_grp_section = None
        sc_idx_data = None
        if self.dat_path:
            d = self._get_game_dir()
            grp_path = os.path.join(d, "SC.GRP")
            idx_path = os.path.join(d, "SC.IDX")
            if os.path.exists(grp_path) and os.path.exists(idx_path):
                try:
                    with open(idx_path, 'rb') as f:
                        idata = f.read()
                    sc_idx_data = base64.b64encode(idata).decode('ascii')
                    offs = [struct.unpack_from('<I', idata, i)[0] for i in range(0, len(idata), 4)]
                    if sid < len(offs):
                        start = offs[sid]
                        end = offs[sid + 1] if sid + 1 < len(offs) else os.path.getsize(grp_path)
                        with open(grp_path, 'rb') as f:
                            f.seek(start)
                            sc_grp_section = base64.b64encode(f.read(end - start)).decode('ascii')
                except Exception:
                    pass

        def find_du(idx):
            return next((r for r in self.defunit_recs if r['index'] == idx), None)

        all_defunit_indices = set()
        entity_exports = []

        def collect_chain(head_idx):
            indices = []
            cur = head_idx
            visited = set()
            while cur >= 0 and cur not in visited:
                visited.add(cur)
                du = find_du(cur)
                if du is None:
                    break
                indices.append(cur)
                all_defunit_indices.add(cur)
                nxt = du.get('f6', 0)
                if nxt == 0 or nxt in visited:
                    break
                cur = nxt
            return indices

        for rec in scene_entities:
            chains = {}
            for chain_name, di in [('A', 39), ('B', 40), ('C', 41)]:
                max_di = {39: 30, 40: 31, 41: 32}[di]
                head = rec.get(f'd{di}', -1)
                mx = rec.get(f'd{max_di}', 0)
                if head > 0 and mx > 0:
                    chains[chain_name] = collect_chain(head)
            entity_exports.append({
                'dwords': [rec.get(f'd{i}', 0) for i in range(96)],
                'defunit_chains': chains,
            })

        defunits = []
        for idx in sorted(all_defunit_indices):
            du = find_du(idx)
            if du:
                defunits.append({'index': idx, 'fields': [du.get(f'f{i}', 0) for i in range(8)]})

        defines_export = []
        seen_dids = set()
        for rec in scene_entities:
            for chain_name, di in [('A', 39), ('B', 40), ('C', 41)]:
                max_di = {39: 30, 40: 31, 41: 32}[di]
                head = rec.get(f'd{di}', -1)
                mx = rec.get(f'd{max_di}', 0)
                if not (head > 0 and mx > 0):
                    continue
                cur = head
                visited = set()
                while cur >= 0 and cur not in visited:
                    visited.add(cur)
                    du = find_du(cur)
                    if du is None:
                        break
                    did = (du.get('f1', 0) << 16) | du.get('f0', 0)
                    if did > 0 and did not in seen_dids:
                        seen_dids.add(did)
                        d = self.tkd_define_map.get(did)
                        if d:
                            text = '\r\n'.join([d['header_line']] + d['body_lines'])
                            defines_export.append({'id': did, 'text': text})
                    nxt = du.get('f6', 0)
                    if nxt == 0 or nxt in visited:
                        break
                    cur = nxt

        export_data = {
            'format': 'tkmat_scene_export',
            'version': 1,
            'scene_id': sid,
            'scene_name': scene_name(self.tkt_scenes, sid),
            'tkt_scene_text': tkt_scene_text,
            'sc_grp_section': sc_grp_section,
            'sc_idx_data': sc_idx_data,
            'entity_count': len(entity_exports),
            'entities': entity_exports,
            'defunits': defunits,
            'defines': defines_export,
        }

        sname = scene_name(self.tkt_scenes, sid).replace('/', '_').replace('\\', '_')
        fp, _ = QFileDialog.getSaveFileName(
            self, f"导出场景 {sname}",
            f"scene_{sid}_{sname}.tkmat",
            "TKMat 场景导出 (*.tkmat);;所有文件 (*.*)")
        if not fp:
            return
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "导出完成",
                                f"场景 {sname} (ID={sid})\n实体: {len(entity_exports)} 个\n"
                                f"DefUnit记录: {len(defunits)} 条\n"
                                f"DEFINE块: {len(defines_export)} 个\n已保存到:\n{fp}")

    def _import_scene(self):
        """导入 .tkmat 文件: 作为全新场景追加"""
        if not self.records:
            QMessageBox.warning(self, "无数据", "请先加载 TKS 目录")
            return
        fp, _ = QFileDialog.getOpenFileName(self, "导入场景", "", "TKMat 场景导出 (*.tkmat);;所有文件 (*.*)")
        if not fp:
            return
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"无法解析文件:\n{e}")
            return
        if data.get('format') != 'tkmat_scene_export':
            QMessageBox.critical(self, "格式错误", "不是有效的 .tkmat 场景导出文件")
            return

        n_entities = len(data.get('entities', []))
        n_defunits = len(data.get('defunits', []))
        n_defines = len(data.get('defines', []))
        if QMessageBox.question(self, "确认导入",
                                f"将作为新场景导入:\n  实体: {n_entities} 个\n  DefUnit: {n_defunits} 条\n  DEFINE块: {n_defines} 个\n\n确定继续?",
                                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return

        empty_slots = sorted([i for i, r in enumerate(self.records) if r['d0'] == 0], reverse=True)
        empty_slots = sorted(empty_slots[:n_entities])
        if len(empty_slots) < n_entities:
            QMessageBox.critical(self, "空槽不足", f"需要 {n_entities} 个空槽, 但只有 {len(empty_slots)} 个")
            return

        # Build old_entity mapping
        old_entity_ids = []
        for ent in data['entities']:
            chains = ent.get('defunit_chains', {})
            for chain_indices in chains.values():
                if chain_indices:
                    for du_entry in data['defunits']:
                        if du_entry['index'] == chain_indices[0]:
                            old_entity_ids.append(du_entry['fields'][1])
                            break
                    break
        while len(old_entity_ids) < n_entities:
            old_entity_ids.append(-1)
        entity_old_to_new = {}
        for i, old_id in enumerate(old_entity_ids):
            if old_id >= 0:
                entity_old_to_new[old_id] = empty_slots[i]

        # Import DefUnit
        du_old_to_new = {}
        for du_entry in data['defunits']:
            old_du_idx = du_entry['index']
            new_du_idx = len(self.defunit_recs)
            du_old_to_new[old_du_idx] = new_du_idx
            fields = du_entry['fields']
            old_f1 = fields[1]
            new_f1 = entity_old_to_new.get(old_f1, old_f1)
            rec = {'index': new_du_idx}
            for fi in range(8):
                val = fields[fi] if fi < len(fields) else 0
                if fi == 1:
                    val = new_f1
                rec[f'f{fi}'] = val
            self.defunit_recs.append(rec)
        for du_entry in data['defunits']:
            new_du_idx = du_old_to_new[du_entry['index']]
            old_f6 = du_entry['fields'][6]
            if old_f6 in du_old_to_new:
                du_rec = next((r for r in self.defunit_recs if r['index'] == new_du_idx), None)
                if du_rec:
                    du_rec['f6'] = du_old_to_new[old_f6]

        # Import DEFINE
        for d_entry in data['defines']:
            old_did = d_entry['id']
            text = d_entry['text']
            new_did = old_did
            for du_entry in data['defunits']:
                fields = du_entry['fields']
                if (fields[1] << 16) | fields[0] == old_did:
                    new_f1 = entity_old_to_new.get(fields[1], fields[1])
                    new_f0 = fields[0]
                    new_did = (new_f1 << 16) | new_f0
                    break
            if new_did != old_did:
                text = text.replace(f'DEFINE {old_did}', f'DEFINE {new_did}', 1)
            lines = text.replace('\r\n', '\n').split('\n')
            header = ''
            body = []
            for line in lines:
                if line.strip().startswith('DEFINE') and not line.strip().startswith('//'):
                    header = line.rstrip('\r')
                elif header:
                    body.append(line.rstrip('\r'))
            define = {
                'define_id': new_did,
                'comment': '', 'prefix_lines': [],
                'body_lines': body if body else ['{', 'End(0)', '}; end'],
                'line_start': -1, 'line_end': -1,
                'header_line': header if header else f'DEFINE {new_did}',
            }
            self.tkd_defines.append(define)
            self.tkd_define_map[new_did] = define

        # Import entities
        existing_scenes = {r['d1'] for r in self.records if has_data(r) and r['d1'] >= 0}
        new_scene_id = max(existing_scenes) + 1 if existing_scenes else 0
        for i, ent in enumerate(data['entities']):
            slot = empty_slots[i]
            dwords = ent['dwords']
            chains = ent.get('defunit_chains', {})
            rec = self.records[slot]
            rec['index'] = slot
            for di in range(min(96, len(dwords))):
                rec[f'd{di}'] = dwords[di]
            rec['d1'] = new_scene_id
            for chain_name, di in [('A', 39), ('B', 40), ('C', 41)]:
                old_indices = chains.get(chain_name, [])
                if old_indices and old_indices[0] in du_old_to_new:
                    rec[f'd{di}'] = du_old_to_new[old_indices[0]]
                else:
                    rec[f'd{di}'] = -1

        self._dirty = True
        self._apply_filter()
        self._vis_populate_scenes()
        self._vis_load_scene()
        QMessageBox.information(self, "导入完成",
                                f"成功导入:\n  实体: {n_entities} 个\n  DefUnit: {n_defunits} 条\n  DEFINE: {n_defines} 个")

    # =========== 窗口缩放事件 ===========
    def resizeEvent(self, event):
        """窗口大小改变时，防抖触发自适应重绘"""
        super().resizeEvent(event)
        if hasattr(self, 'records') and self.records:
            self._resize_timer.start(100)

    def _do_resize_redraw(self):
        """防抖定时器触发的真正重绘逻辑"""
        if hasattr(self, 'records') and self.records:
            self._vis_redraw()

    # =========== 关闭事件 ===========
    def closeEvent(self, event):
        self._vis_stop_anim()
        self._vis_stop_sel_anim()
        if not confirm_close(self, self._dirty or self._script_dirty,
                             text="有未保存的修改 (含脚本), 确定退出?"):
            event.ignore()
            return
        event.accept()


# ============================================================
# 入口
# ============================================================
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _t = QTranslator()
    _t.load("qtbase_zh_CN", os.path.join(os.path.dirname(__file__), '..', 'editor_utils'))
    app.installTranslator(_t)
    editor = MatEditorApp()
    editor.show()
    sys.exit(app.exec())
