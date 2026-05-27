#!/usr/bin/env python3
"""
TKMat.Dat 地图实体编辑器 v2.3 — 融合脚本编辑
=============================================================
逆向依据:
  sub_412688:21: TKMat.Dat → dword_51AF40 (2304000B, 6000×384B)
  sub_41103C:26: 场景文件 LZSS 解压覆盖实体表
  sub_405CBC: 实体类型分支渲染 (5/10/15/16/20/110/200)
  sub_4077E4: 朝向 [13], sub_407070: 坐标 [10][11]
  sub_40EBD4: 脚本PC[42]/DefUnit索引[44]/子场景[30-35]
  sub_4066F0: DefUnit链遍历 [39-41]
  sub_402E88: TKDefUnit.dat 加载 (5000×16B)
  sub_409618: 主Tick循环 — A链=自动(d33>0) B链=触发(交互)
  sub_408E5C: 玩家点击交互 — B链触发

用法:
  python mat_editor.py
"""

import struct, os, sys, re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# LZSS 解压 (用于 TKItem.dat)
# ============================================================
def lzss_decompress(data):
    if len(data) < 12: return b''
    ts = struct.unpack_from('<I', data, 0)[0]; bs = struct.unpack_from('<I', data, 4)[0]
    w = bytearray([0x20]*4096); wp = 4078; out = bytearray(); flags = 0; pos = 12; bc = 4
    while bc < bs:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data): break
            flags = data[pos] | 0xFF00; pos += 1; bc += 1
        if flags & 1:
            if pos >= len(data): break
            b = data[pos]; pos += 1; bc += 1
            out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(data): break
            b1, b2 = data[pos], data[pos+1]; pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1; rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]; out.append(b)
                w[wp] = b; wp = (wp + 1) & 0xFFF
    return bytes(out[:ts])

# ============================================================
# 常量
# ============================================================
REC_SIZE = 384; REC_COUNT = 6000; FILE_SIZE = 2304000; DWORD_COUNT = 96
SCENE_NAME_TKT_BASE = 300
DEFUNIT_REC_SIZE = 16; DEFUNIT_REC_COUNT = 5000; DEFUNIT_FILE_SIZE = 80000

ENTITY_TYPES = {0:"空槽",5:"入口/传送点",10:"地形块",15:"障碍物",16:"建筑/门",
                20:"事件对象",110:"特殊机关",200:"NPC/角色"}
TYPE_COLORS = {0:"#AAA",5:"#2196F3",10:"#4CAF50",15:"#FF9800",16:"#795548",
               20:"#9C27B0",110:"#E91E63",200:"#F44336"}
TYPE_COLORS_RGBA = {0:(170,170,170),5:(33,150,243),10:(76,175,80),15:(255,152,0),
                    16:(121,85,72),20:(156,39,176),110:(233,30,99),200:(244,67,54)}
ANIM_SETS = {0:"空(无动画)",1:"Cha.JVG(角色)",4:"Ani.JVG(动画)",5:"Cur.JVG(光标)"}
DISPLAY_MODES = {"游戏默认":"auto","动画":"ani","角色":"cha","线框":"wire"}
_JVG_CACHE = {}  # filepath → JVGFile
_SPRITE_CACHE = {}  # (filepath, global_idx) → PhotoImage

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
    ("type",0,"实体类型","实体类型: 5=入口 10=地形 15=障碍 16=建筑 20=事件 110=机关 200=NPC"),
    ("scene_id",1,"场景ID","所属场景 (-1=全局)。TKT_ID = scene_id + 300"),
    ("flags",2,"标志位","位域。bit0=启用 bit1=可见 bit2=可交互 bit3=提示 bit4=忙碌 bit5=恢复 bit8=已拾取(type110) bit16=动画循环"),
    ("param",3,"扩展参数","扩展参数 (道具数量/金钱等)"),
    ("hint_id",23,"提示文本ID","鼠标悬停提示的TKT文本ID。传送点(type=10): 设为 300+目标场景ID 以显示目标场景名。sub_412390"),
    ("cursor_id",8,"光标动画","鼠标悬停光标动画编号。传送点(type=10)设为3显示开门动画。sub_411BA4/sub_412390"),
    ("blend_mode",24,"混合模式","sub_406864:39 — 主精灵渲染混合: 0=正常 1=染色 2=加法发光 3=减法压暗 4=亮度alpha 5=水平翻转"),
    ("blend_param",25,"混合参数","sub_406864:45/54 — d24=1时颜色索引, d24=2时加法缩放(0或>31=全加法)"),
    ("shadow_frame",55,"阴影帧","type=16:把手1概率 type=110:组1Ymin type=200:Cha.JVG阴影帧(0=无1=小2=大)。sub_406864:37,sub_4084E0,sub_408B30"),]
POS_FIELDS = [
    ("x",10,"坐标X","世界坐标X (像素)。sub_407070: a1[10]=x"),
    ("y",11,"坐标Y","世界坐标Y (像素)。sub_407070: a1[11]=y"),
    ("bound_x",18,"碰撞X","碰撞盒/区域X起点。sub_410B74"),
    ("bound_y",19,"碰撞Y","碰撞盒/区域Y起点。sub_410B74"),
    ("bound_w",20,"碰撞宽","碰撞盒/区域宽度。仅地形块(type=10)使用"),
    ("bound_h",21,"碰撞高","碰撞盒/区域高度。仅地形块(type=10)使用"),
    ("direction",13,"朝向","朝向 1~8。sub_4077E4"),]
ANIM_FIELDS = [
    ("anim_set",9,"动画集ID","动画集索引。sub_405CBC: dword_755AC0[v2[9]]"),
    ("dir_mode",53,"目标X/方向模式","type=5:目标X type=16:把手2道具 type=110:组1Xmin type=200:方向模式(0=静态/4=四向/8=八向)。sub_4081F8:30,sub_4084E0,sub_408B30,sub_4077E4"),
    ("target_y",54,"目标Y坐标","type=5:目标Y type=16:把手3道具 type=110:组1Xmax type=200:目标Y。sub_4081F8:30,sub_4084E0,sub_408B30"),
    ("sub_model",64,"子模型ID","type=110:组3Ymax type=200:Ani.JVG块(行走动画)。sub_405CBC,sub_408B30"),("anim_speed",69,"动画速度","动画播放速度"),]
def load_tkt_all(tkt_path):
    """加载 TKT.dat 全文数据库 (用于脚本预览解析对话文本)
    与 load_tkt_scene_names 相同格式, 但返回完整文本而非首行"""
    if not tkt_path or not os.path.exists(tkt_path): return {}
    with open(tkt_path,'rb') as f: raw = f.read()
    total_size = struct.unpack_from('<I',raw,0)[0]
    count = struct.unpack_from('<I',raw,4)[0]
    dec = bytes(b^0xFF for b in raw[8:8+total_size])
    id_sz, off_sz = count*4, count*4; tb = id_sz+off_sz; lookup = {}
    for i in range(count):
        eid = struct.unpack_from('<i',dec,i*4)[0]
        off = struct.unpack_from('<I',dec,id_sz+i*4)[0]; ao = tb+off
        if ao>=len(dec): continue
        end=ao
        while end<len(dec) and dec[end]!=0: end+=1
        txt=dec[ao:end]
        s = decode_tkt_bytes(txt)
        if s: lookup[eid]=s
    return lookup

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
    ("defunit_idx",44,"DefUnit索引","文件值=-1为正常; 运行时由 sub_4066F0 沿链遍历计算填入。sub_40EBD4:18 读取"),
    ("dialog_color",28,"对话颜色","TalkA/TalkB 文字颜色索引(0~31), 第2参数=TKT文本ID。sub_44B028 查表 dword_A2C528"),
    ("max_A",30,"子场景最大A","子场景A DefUnit链长度"),
    ("max_B",31,"子场景最大B",""),("max_C",32,"子场景最大C",""),
    ("cur_A",33,"子场景当前A","当前在链中的位置(1-based)。SetNowDef可修改"),
    ("cur_B",34,"子场景当前B",""),("cur_C",35,"子场景当前C",""),
    ("head_A",39,"DefUnit链头A","子场景A的 TKDefUnit 链表头索引。sub_4066F0:39 从这开始遍历"),
    ("head_B",40,"DefUnit链头B",""),("head_C",41,"DefUnit链头C",""),]
INTERACT_FIELDS = [
    ("cond_id",50,"条件匹配","0=无条件。type=5/15/16:与player[d22]匹配才可交互。type=110(d52=0):帧计数器>0启用拾取后动画。type=200:条件角色。sub_4081F8:200, sub_408408:200, sub_4084E0:200, sub_408B30:200"),
    ("dir_mask",51,"方向掩码","bit0-7对应朝向1-8, 0=任意方向。type=110(d52=0):动画帧基偏移(frame_idx=frame_cur+d51)。type=200:立绘ID(Cha.JVG块)。sub_4081F8:204, sub_408408:204, sub_4084E0:204"),
    ("target_scene",52,"目标场景","type=5:目标地图ID type=16:把手1道具 type=110:行为模式(0=标记bit8+动画 1=清除实体 2+=无行为)。type=200:动画句柄(运行时)。sub_4081F8:208, sub_4084E0:208, sub_408B30:208"),]
RUNTIME_FIELDS = [
    ("tick",4,"tick","Tick周期(运行时)"),
    ("timer",12,"计时器",""),("frame_idx",14,"帧索引",""),
    ("frame_count",16,"总帧数",""),("frame_cur",17,"帧计数",""),
    ("script_PC",42,"脚本PC",""),("saved_PC",43,"保存PC",""),
    ("target_dir",56,"目标朝向","type=5:目标朝向(1-8) type=16:把手2概率 type=110:组1Ymax type=200:寻路X(运行时)。sub_4081F8:30,sub_4084E0,sub_408B30"),
    ("saved_y",57,"保存Y","type=5:相机X type=16:把手3概率 type=110:组2Xmin type=200:寻路Y(运行时)。sub_4081F8,sub_4084E0,sub_408B30"),
    ("alt_tele_x",60,"备选传送X","type=5:相机偏移X type=110:组2Ymax type=200:备选传送X。sub_4081F8:31,sub_408B30"),
    ("alt_tele_y",61,"备选传送Y","type=5:相机偏移Y type=16:冷却计时 type=110:组3Xmin type=200:备选传送Y。sub_4081F8:31,sub_4084E0,sub_408B30"),
    ("sub_handle",65,"子句柄","type=16:目标地图 type=110:组3Xmax? type=200:动画基址(运行时)。sub_4084E0,sub_408B30"),("cur_frame",67,"当前帧",""),
    ("max_frame",68,"最大帧",""),("moving",70,"移动中",""),
    ("priority",22,"优先级/α","sub_406864:35 — 实体优先级/像素透明度。sub_406E50 计算, 决定简单/变换渲染分支"),
    ("sprite_off_x",26,"精灵偏移X","sub_406864:30 — 精灵 X 屏幕偏移, 叠加到坐标"),
    ("sprite_off_y",27,"精灵偏移Y","sub_406864:31 — 精灵 Y 屏幕偏移, 叠加到坐标"),]
ITEM_FIELDS = [
    ("item_g1_id",   53, "组1-物品ID",   "type110: 物品ID随机范围最小值; Xmin==Xmax→固定掉落"),
    ("item_g1_idmax",54, "组1-物品上限",  "type110: 物品ID随机范围最大值"),
    ("item_g1_qty",  55, "组1-数量",     "type110: 数量随机范围最小值; Ymin==Ymax→固定数量"),
    ("item_g1_qtymax",56,"组1-数量上限",  "type110: 数量随机范围最大值"),
    ("item_g2_id",   57, "组2-物品ID",   "type110: 第二组物品ID (此游戏未使用)"),
    ("item_g2_idmax",58, "组2-物品上限",  "type110: 第二组物品ID上限"),
    ("item_g2_qty",  59, "组2-数量",     "type110: 第二组数量"),
    ("item_g2_qtymax",60,"组2-数量上限",  "type110: 第二组数量上限"),
    ("item_g3_id",   61, "组3-物品ID",   "type110: 第三组物品ID (此游戏未使用)"),
    ("item_g3_idmax",62, "组3-物品上限",  "type110: 第三组物品ID上限"),
    ("item_g3_qty",  63, "组3-数量",     "type110: 第三组数量"),
    ("item_g3_qtymax",64,"组3-数量上限",  "type110: 第三组数量上限"),
]
ALL_EDIT_FIELDS = BASIC_FIELDS+POS_FIELDS+ANIM_FIELDS+SCRIPT_FIELDS+INTERACT_FIELDS+ITEM_FIELDS

# 类型相关字段映射: type → {dword: (label, comment)}
# 仅列出与 type=200(NPC) 默认语义不同的字段
_TYPE_LABELS = {
    5: {  # 入口/传送点 sub_4081F8
        50:("条件匹配","0=无条件, 非零须与player[d22]匹配"), 51:("方向掩码","bit0-7对应朝向1-8, 0=任意"),
        52:("目标地图ID",""), 53:("目标X","传送后X坐标"),
        54:("目标Y","传送后Y坐标"), 56:("目标朝向","传送后玩家朝向1-8"),
        57:("相机X","相机目标X"), 58:("相机Y",""),
        59:("相机Z",""), 60:("相机偏移X",""),
        61:("相机偏移Y",""), 62:("过程锁","非零时锁定"),
    },
    10: {  # 地形块 sub_405CBC + sub_40DC1C
        62:("连线组数","连线组数量>0启用"),
        63:("线1-启用",""), 64:("线1-X1",""), 65:("线1-Y1",""), 66:("线1-X2",""), 67:("线1-Y2",""),
        68:("线2-启用",""), 69:("线2-X1",""), 70:("线2-Y1",""), 71:("线2-X2",""), 72:("线2-Y2",""),
        73:("线3-启用",""), 74:("线3-X1",""), 75:("线3-Y1",""), 76:("线3-X2",""), 77:("线3-Y2",""),
        78:("线4-启用",""), 79:("线4-X1",""), 80:("线4-Y1",""), 81:("线4-X2",""), 82:("线4-Y2",""),
        83:("线5-启用",""), 84:("线5-X1",""), 85:("线5-Y1",""), 86:("线5-X2",""), 87:("线5-Y2",""),
    },
    15: {  # 障碍物 sub_408408
        34:("触发开关","非零可触发"), 50:("条件匹配","0=无条件, 非零须与player[d22]匹配"),
        51:("方向掩码","bit0-7对应朝向1-8, 0=任意"),
    },
    16: {  # 建筑/门 sub_4084E0
        50:("条件匹配","0=无条件, 非零须与player[d22]匹配"), 51:("方向掩码","bit0-7对应朝向1-8, 0=任意"),
        52:("把手1道具",""), 53:("把手2道具",""),
        54:("把手3道具",""), 55:("把手1概率",""),
        56:("把手2概率",""), 57:("把手3概率",""),
        61:("冷却计时",""), 62:("目标地图",""),
    },
    110: {  # 特殊机关 sub_408B30
        50:("帧计数器","d52=0时>0启用拾取后动画; 此游戏全为0"),
        51:("动画帧基偏移","d52=0时: frame_idx=frame_cur+d51"),
        52:("行为模式","0=标记bit8+可选动画 1=清除实体(禁用+隐藏) 2+=无行为; 此游戏全为1"),
        53:("组1-物品ID","随机范围最小值; Xmin==Xmax=固定掉落"),
        54:("组1-物品ID上限","随机范围最大值"),
        55:("组1-数量","随机范围最小值; Ymin==Ymax=固定数量"),
        56:("组1-数量上限","随机范围最大值"),
        57:("组2-物品ID","(此游戏未使用)"),
        58:("组2-物品ID上限",""),
        59:("组2-数量",""),
        60:("组2-数量上限",""),
        61:("组3-物品ID","(此游戏未使用)"),
        62:("组3-物品ID上限",""),
        63:("组3-数量",""),
        64:("组3-数量上限",""),
    },
    200: {  # NPC/角色 sub_406864 + sub_405CBC
        50:("条件角色",""), 51:("立绘ID","Cha.JVG块索引"),
        52:("动画句柄","运行时"), 53:("方向模式","4=四向 8=八向 0=静态"),
        55:("阴影帧","Cha.JVG全局帧索引"), 56:("寻路X","运行时"),
        57:("寻路Y","运行时"), 64:("子模型","Ani.JVG块索引"),
        65:("动画基址","运行时"), 66:("动画间隔","随机动画帧间隔"),
        67:("帧起点","动画帧循环起点"), 68:("帧终点","动画帧终点=max-1"),
        70:("移动模式","0=静止 1=行走"),
        71:("事件1帧",""),72:("事件1动作",""), 73:("事件2帧",""),74:("事件2动作",""),
        75:("事件3帧",""),76:("事件3动作",""), 77:("事件4帧",""),78:("事件4动作",""),
        79:("事件5帧",""),80:("事件5动作",""), 81:("事件6帧",""),82:("事件6动作",""),
        83:("事件7帧",""),84:("事件7动作",""), 85:("事件8帧",""),86:("事件8动作",""),
        87:("事件9帧",""),88:("事件9动作",""), 89:("事件10帧",""),90:("事件10动作",""),
        91:("事件11帧",""),92:("事件11动作",""),
        93:("事件12帧",""),94:("事件12动作",""),
        95:("事件13帧",""),
    },
}
# 注意: type=20(事件对象) 字段语义与 type=200 相同

FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)
FONT_B = ('Microsoft YaHei UI', 11, 'bold')
FONT_MONO = ('Consolas', 10)
MAX_MAP_W, MAX_MAP_H = 1024, 768

# ============================================================
# TKD.dat 脚本 I/O (来自 script_editor.py)
# ============================================================

def load_tkd(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    decoded = bytes([b ^ 0xFF for b in data])
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
    encrypted = bytes([b ^ 0xFF for b in encoded])
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

def _item_name(item_names, id_str):
    """从 item_names 获取物品名称, id_str 为字符串形式的物品ID"""
    try:
        if not item_names: return ''
        tid = int(id_str)
        return item_names.get(tid, '')
    except (ValueError, TypeError):
        return ''

SCRIPT_CMD_DESC = {
    # ===== [Normal] 按 DEFCMD.LST 操作码顺序 =====
    # opcode 0: End(1) — 结束脚本, 参数=结束模式
    # End 模式速查: 0=正常返回  1=A链递增  2=B链递增  3=C链递增  4=A链重置  5=B链重置  6=C链重置
    'End':          lambda a, t: (
        "结束 (正常返回, 不修改链)" if not a or a[0] == '0' else
        f"结束 → A链递增 (下一DEFINE)" if a[0] == '1' else
        f"结束 → B链递增 (下一DEFINE)" if a[0] == '2' else
        f"结束 → C链递增 (下一DEFINE)" if a[0] == '3' else
        f"结束 → A链重置 (cur_A=0)" if a[0] == '4' else
        f"结束 → B链重置 (cur_B=0)" if a[0] == '5' else
        f"结束 → C链重置 (cur_C=0)" if a[0] == '6' else
        f"结束 (模式={a[0]})"  # fallback for unknown modes
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
    # opcode 5: SysTalk(6) — 系统对话
    'SysTalk':      lambda a, t: f"系统对话 参数=({','.join(a[:6])})" if len(a)>=6 else f"系统对话" if not a else f"系统对话 参数=({','.join(a)})",
    # opcode 6: SetHint(3) — 设置提示: 实体, 参数, 参数
    'SetHint':      lambda a, t: f"设置提示 实体#{a[0]} — {_tkt_text(t, a[0])}" if a else "设置提示",
    # opcode 7: MenuTalk(2) — 菜单对话
    'MenuTalk':     lambda a, t: f"菜单对话 ID={a[0]}" if a else "菜单对话",
    # opcode 8: SetScene(2) — 设置场景状态
    'SetScene':     lambda a, t: f"设置场景状态 ID={a[0]}" if a else "设置场景状态",
    # opcode 9: SetWalk(3) — 设置行走: 实体, X, Y
    'SetWalk':      lambda a, t: f"行走 实体#{a[0]}→({a[1]},{a[2]})" if len(a)>=3 else f"行走 实体#{a[0]}" if a else "行走",
    # opcode 10: WaitWalk(2) — 等待行走完成: 实体, 模式
    'WaitWalk':     lambda a, t: f"等待行走完成 实体#{a[0]}" if a else "等待行走",
    # opcode 11: StopWalk(2) — 停止行走
    'StopWalk':     lambda a, t: f"停止行走 实体#{a[0]}" if a else "停止行走",
    # opcode 12: SetEnabled(2) — 启用/禁用实体: 实体, 标志
    'SetEnabled':   lambda a, t: f"启用/禁用 实体#{a[0]} 标志={a[1]}" if len(a)>=2 else f"启用/禁用 实体#{a[0]}" if a else "启用/禁用",
    # opcode 13: SetVisible(2) — 设置可见性: 实体, 标志
    'SetVisible':   lambda a, t: f"设置可见性 实体#{a[0]} 标志={a[1]}" if len(a)>=2 else "设置可见性",
    # opcode 14: SetWait(3) — 设置等待: 实体, 模式, 帧数
    'SetWait':      lambda a, t: f"设置等待 实体#{a[0]} 标志={a[1]}" if len(a)>=2 else "设置等待",
    # opcode 15: Nop(0) — 空操作
    'Nop':          lambda a, t: f"空操作 (填充={a[0]})" if a else "空操作",
    # opcode 16: SetCursor(3) — 设置光标
    'SetCursor':    lambda a, t: f"设置光标 ({a[0]},{a[1]},{a[2]})" if len(a)>=3 else "设置光标" if a else "设置光标",
    # opcode 17: FadeOut(4) — 淡出: R, G, B, 速度
    'FadeOut':      lambda a, t: f"淡出 RGB({a[0]},{a[1]},{a[2]}) 速度={a[3]}" if len(a)>=4 else "淡出",
    # opcode 18: FadeIn(4) — 淡入: R, G, B, 速度
    'FadeIn':       lambda a, t: f"淡入 RGB({a[0]},{a[1]},{a[2]}) 速度={a[3]}" if len(a)>=4 else "淡入",
    # opcode 19: ChangeScene(4) — 切换场景: 场景ID, X, Y, 朝向
    'ChangeScene':  lambda a, t: f"切换场景→#{a[0]} ({a[1]},{a[2]})朝向{a[3]}" if len(a)>=4 else f"切换场景→#{a[0]}" if a else "切换场景",
    # opcode 20: SetAni(7) — 设置动画: 实体+6参数
    'SetAni':       lambda a, t: f"设置动画 实体#{a[0]}" if a else "设置动画",
    # opcode 21: SetTick(2) — 设置Tick回调
    'SetTick':      lambda a, t: f"设置Tick回调 实体#{a[0]}" if a else "设置Tick",
    # opcode 22: SetShadow(2) — 设置阴影
    'SetShadow':    lambda a, t: f"设置阴影 实体#{a[0]}" if a else "设置阴影",
    # opcode 23: SetPos(4) — 设置位置: 实体, X, Y, 朝向
    'SetPos':       lambda a, t: f"设置位置 实体#{a[0]}→({a[1]},{a[2]})朝向{a[3]}" if len(a)>=4 else f"设置位置 实体#{a[0]}" if a else "设置位置",
    # opcode 24: Disable(1) — 禁用实体
    'Disable':      lambda a, t: f"禁用 实体#{a[0]}" if a else "禁用",
    # opcode 25: Enable(1) — 启用实体
    'Enable':       lambda a, t: f"启用 实体#{a[0]}" if a else "启用",
    # opcode 26: Redraw(1) — 重绘画面
    'Redraw':       lambda a, t: "重绘画面",
    # opcode 27: SetPlayer(1) — 设置玩家
    'SetPlayer':    lambda a, t: f"设置玩家实体#{a[0]}" if a else "设置玩家",
    # opcode 28: SetCamera(1) — 设置镜头
    'SetCamera':    lambda a, t: f"设置镜头 实体#{a[0]}" if a else "设置镜头",
    # opcode 29: SetView(2) — 设置视角
    'SetView':      lambda a, t: f"设置视角 参数=({','.join(a[:2])})" if len(a)>=2 else f"设置视角" if a else "设置视角",
    # opcode 30: SlideTo(3) — 滑动到
    'SlideTo':      lambda a, t: f"滑动到 ({a[0]},{a[1]},{a[2]})" if len(a)>=3 else "滑动",
    # opcode 31: PlayerAct(1) — 玩家行动
    'PlayerAct':   lambda a, t: f"玩家行动 模式={a[0]}" if a else "玩家行动",
    # opcode 32: SetFlag(2) — 设置标志
    'SetFlag':      lambda a, t: f"设置标志 #{a[0]}={a[1]}" if len(a)>=2 else f"设置标志 #{a[0]}" if a else "设置标志",
    # opcode 33: AddFlag(2) — 增加标志
    'AddFlag':      lambda a, t: f"增加标志 #{a[0]}+{a[1]}" if len(a)>=2 else f"增加标志 #{a[0]}" if a else "增加标志",
    # opcode 34: TalkA(5) — 即时式对话: 实体, 文本ID, 参数, 参数, 参数
    'TalkA':        lambda a, t: f"对话(即时) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"对话(即时) 实体#{a[0]}" if a else "对话(即时)",
    # opcode 35: Switch(2) — 开关切换
    'Switch':       lambda a, t: f"开关切换 ({','.join(a[:2])})" if len(a)>=2 else "开关切换",
    # opcode 36: SetVar(2) — 设置变量
    'SetVar':       lambda a, t: f"变量[{a[0]}]={a[1]}" if len(a)>=2 else f"变量[{a[0]}]" if a else "设置变量",
    # opcode 37: Random(3) — 随机: 变量槽, 最小值, 最大值
    'Random':       lambda a, t: f"随机→变量[{a[0]}] 范围[{a[1]},{a[2]}]" if len(a)>=3 else "随机",
    # opcode 38: SetFlagVar(2) — 设置标志变量
    'SetFlagVar':   lambda a, t: f"标志变量 标志={a[0]},变量槽={a[1]}" if len(a)>=2 else f"标志变量 标志={a[0]}" if a else "设置标志变量",
    # opcode 39: AddFlagVar(2) — 增加标志变量
    'AddFlagVar':   lambda a, t: f"增加标志变量 标志={a[0]},变量槽={a[1]}" if len(a)>=2 else f"增加标志变量 标志={a[0]}" if a else "增加标志变量",
    # opcode 40: GetItem(2) — 获得道具: 道具ID, 数量
    'GetItem':      lambda a, t, i=None: (
        f"获得道具 {a[0]}({_item_name(i, a[0])}) ×{a[1]}" if a and len(a)>=2 and i else
        f"获得道具 {a[0]}({_item_name(i, a[0])})" if a and i else
        f"获得道具 ID={a[0]}" if a else "获得道具"
    ),
    # opcode 41: BlackTalk(4) — 黑屏对话/旁白
    'BlackTalk':    lambda a, t: f"黑屏对话 文本={a[0]} — {_tkt_text(t, a[0])}" if a else "黑屏对话",
    # opcode 42: SetChaPic(2) — 设置角色图片
    'SetChaPic':    lambda a, t: f"设置角色图片 实体#{a[0]}" if a else "设置角色图片",
    # opcode 43: SetWeather(2) — 设置天气
    'SetWeather':   lambda a, t: f"设置天气 参数=({','.join(a[:2])})" if len(a)>=2 else f"设置天气" if a else "设置天气",
    # opcode 44: ShowMenu(2) — 显示菜单
    'ShowMenu':     lambda a, t: f"显示菜单 ID={a[0]}" if a else "显示菜单",
    # opcode 45: TeamMember(2) — 队伍成员
    'TeamMember':   lambda a, t: "队伍成员检查",
    # opcode 46: Note(2) — 注释命令
    'Note':         lambda a, t: f"注释: {', '.join(a)}" if a else "注释",
    # opcode 47: SetBlock(2) — 设置阻挡
    'SetBlock':     lambda a, t: f"设置阻挡 实体#{a[0]}" if a else "设置阻挡",
    # opcode 48: Attribute(3) — 属性变更
    'Attribute':   lambda a, t: f"属性变更 参数=({','.join(a[:3])})" if len(a)>=3 else f"属性变更" if a else "属性变更",
    # opcode 49: SetSwitch(2) — 设置开关
    'SetSwitch':    lambda a, t: f"开关[{a[0]}]={a[1]}" if len(a)>=2 else f"开关[{a[0]}]" if a else "设置开关",
    # opcode 50: BuyMenu(3) — 商店菜单
    'BuyMenu':      lambda a, t: f"商店菜单 参数=({','.join(a[:3])})" if len(a)>=3 else "商店菜单",
    # opcode 51: PlaySound(2) — 播放音效
    'PlaySound':    lambda a, t: f"播放音效 ID={a[0]}" if a else "播放音效",
    # opcode 52: StopSound(1) — 停止声音
    'StopSound':    lambda a, t: "停止声音",
    # opcode 53: PlayMusic(2) — 播放音乐
    'PlayMusic':    lambda a, t: f"播放音乐 ID={a[0]}" if a else "播放音乐",
    # opcode 54: SetMusic(2) — 设置背景音乐
    'SetMusic':     lambda a, t: f"设置音乐 ID={a[0]}" if a else "设置音乐",
    # opcode 55: TheEnd(1) — 游戏结局
    'TheEnd':       lambda a, t: "游戏结束",
    # opcode 56: Fix(1) — 修正/修复命令
    'Fix':          lambda a, t: f"修正 参数={a[0]}" if a else "修正",
    # ===== [Special] 条件跳转类 =====
    # opcode 60: CheckResult(2) — 检查变量结果跳转
    'CheckResult':  lambda a, t: f"条件跳转 变量[{a[0]}]=={a[1]}?" if len(a)>=2 else "条件跳转",
    # opcode 61: CheckFlag(3) — 检查标志条件跳转: 标志ID, 操作符, 值
    'CheckFlag':    lambda a, t: f"检查标志 标志={a[0]}, 操作={a[1]}, 值={a[2]}" if len(a)>=3 else f"检查标志 标志={a[0]}" if a else "检查标志",
    # opcode 62: CheckItem(3) — 检查道具条件跳转
    'CheckItem':    lambda a, t: f"检查道具 参数=({','.join(a[:3])})" if len(a)>=3 else "检查道具",
    # opcode 63: CheckTeam(3) — 检查队伍条件跳转
    'CheckTeam':    lambda a, t: f"检查队伍 ID={a[0]}" if a else "检查队伍",
    # opcode 64: MiniGame(3) — 小游戏
    'MiniGame':     lambda a, t: f"小游戏 ID={a[0]}" if a else "小游戏",
    # opcode 65: CheckMember(4) — 检查成员条件跳转
    'CheckMember':  lambda a, t: f"检查成员 参数=({','.join(a[:4])})" if len(a)>=4 else f"检查成员 ID={a[0]}" if a else "检查成员",
    # opcode 66: War(1) — 战斗
    'War':          lambda a, t: f"战斗 ID={a[0]}" if a else "战斗",
    # ===== [NoArg] =====
    # opcode 82: Else — 条件分支的否则
    'Else':         lambda a, t: "否则 (条件分支)",
    # ===== TKD 文本层额外命令 (非 DEFCMD.LST 标准，但在脚本中实际出现或用于兼容) =====
    'Yield':        lambda a, t: "让出控制权 (暂停)",
    'Jump':         lambda a, t: f"跳转到偏移={a[0]}" if a else "跳转",
    'ShowText':     lambda a, t: f"显示文本 ID={a[0]} — {_tkt_text(t, a[0])}" if a else "显示文本",
    'MenuChoice':   lambda a, t: f"菜单选择 实体#{a[0]}" if a else "菜单选择",
    'SetPosFade':   lambda a, t: f"淡入位置 实体#{a[0]}→({a[1]},{a[2]})" if len(a)>=3 else "淡入位置",
    'SceneFade':    lambda a, t: f"场景过渡→#{a[0]}" if a else "场景过渡",
    'SceneBGM':     lambda a, t: f"场景BGM 场景#{a[0]}" if a else "场景BGM",
    'Camera':       lambda a, t: f"镜头控制 ({a[0]},{a[1]},{a[2]})" if len(a)>=3 else "镜头控制",
    'WaitInput':    lambda a, t: "等待输入",
    'SetGlobal':    lambda a, t: f"设置全局变量={a[0]}" if a else "设置全局变量",
    'SetWord':      lambda a, t: f"设置字={a[0]}" if a else "设置字",
    'WaitTimer':    lambda a, t: f"定时等待 {a[0]}×{a[1]}ms" if len(a)>=2 else "定时等待",
    'Music':        lambda a, t: f"播放音乐 ID={a[0]}" if a else "播放音乐",
}

# ============================================================
# TKT 场景名
# ============================================================
def load_tkt_scene_names(tkt_path):
    if not tkt_path or not os.path.exists(tkt_path): return {}
    with open(tkt_path,'rb') as f: raw = f.read()
    total_size = struct.unpack_from('<I',raw,0)[0]
    count = struct.unpack_from('<I',raw,4)[0]
    dec = bytes(b^0xFF for b in raw[8:8+total_size])
    id_sz, off_sz = count*4, count*4; tb = id_sz+off_sz; lookup = {}
    for i in range(count):
        eid = struct.unpack_from('<i',dec,i*4)[0]
        off = struct.unpack_from('<I',dec,id_sz+i*4)[0]; ao = tb+off
        if ao>=len(dec): continue
        end=ao
        while end<len(dec) and dec[end]!=0: end+=1
        txt=dec[ao:end]
        s = decode_tkt_bytes(txt)
        if s: lookup[eid]=s.split('\n')[0].strip()
    return lookup

def scene_name(tkt, sid):
    if sid==-1: return "全局(所有场景)"
    return tkt.get(SCENE_NAME_TKT_BASE+sid,f"场景{sid}")

# ============================================================
# 数据 IO
# ============================================================
def load_mat(fp):
    with open(fp,'rb') as f: raw=f.read()
    if len(raw)!=FILE_SIZE: raise ValueError(f"文件大小异常:{len(raw)}")
    recs=[]
    for i in range(REC_COUNT):
        off=i*REC_SIZE
        dw=struct.unpack_from('<'+'i'*DWORD_COUNT,raw,off)
        rec={'index':i}
        for di in range(DWORD_COUNT): rec[f'd{di}']=dw[di]
        recs.append(rec)
    return recs

def save_mat(fp, recs):
    buf=bytearray(FILE_SIZE)
    for rec in recs[:REC_COUNT]:
        off=rec['index']*REC_SIZE
        for di in range(DWORD_COUNT): struct.pack_into('<i',buf,off+di*4,rec.get(f'd{di}',0))
    with open(fp,'wb') as f: f.write(bytes(buf))
    return True

def is_empty(rec): return rec['d0']==0
def has_data(rec): return rec['d0']!=0

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

def _jvg_sprite_to_tk(jvg, block_idx, frame_idx=0):
    """从 JVG 的 block[block_idx].frames[frame_idx] 提取 PhotoImage (缓存)"""
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
    from PIL import Image, ImageTk
    img = Image.frombytes('RGBA', (frame.width, frame.height), bytes(rgba))
    ptk = ImageTk.PhotoImage(img)
    _SPRITE_CACHE[key] = ptk
    return ptk

_SHADOW_CACHE = {}  # (jvg_id, block_idx, frame_idx) → PhotoImage (减法混合近似)

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
    from PIL import Image, ImageTk
    img = Image.frombytes('RGBA', (frame.width, frame.height), bytes(rgba))
    ptk = ImageTk.PhotoImage(img)
    _SHADOW_CACHE[key] = ptk
    return ptk

_BLEND_CACHE = {}  # (jvg_id, blk_idx, frame_idx, mode, param) → PhotoImage

def _get_blended_sprite(jvg, block_idx, frame_idx, mode=0, param=0):
    """取 JVG 精灵帧并按混合模式处理，带缓存。
    mode: 0=正常 1=染色 2=加法发光 3=减法压暗 4=亮度alpha 5=水平翻转"""
    if mode == 0:
        return _jvg_sprite_to_tk(jvg, block_idx, frame_idx)
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
    from PIL import Image, ImageTk, ImageOps
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
    ptk = ImageTk.PhotoImage(img)
    _BLEND_CACHE[key] = ptk
    return ptk

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
        from grp_editor import load_grp, _decode_section_a, rgb565_to_rgba
    except ImportError:
        return None

    try:
        grp = load_grp(sc_grp_path, sc_idx_path)
        if not grp: return None
        # 构建 原始 section 索引 → image section 的映射
        idx_map = {sec.index: sec for sec in grp.sections}
        sec = idx_map.get(scene_id)
        if not sec or sec.width <= 0 or sec.height <= 0: return None

        _decode_section_a(grp, sec)
        if not sec.pixels: return None

        rgba = rgb565_to_rgba(sec.pixels, sec.width, sec.height)
        from PIL import Image
        img = Image.frombytes('RGBA', (sec.width, sec.height), bytes(rgba))
        return img.convert('RGB')  # 背景转 RGB 供 PIL 合成
    except Exception:
        return None

# ============================================================
# MatEditor
# ============================================================
class MatEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKMat.Dat 地图实体编辑器 v2.3")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico): self.root.iconbitmap(default=ico)
        self.root.geometry("1280x820"); self.root.minsize(1024,640)

        self.dat_path = None; self.tkt_path = None
        self.records = []; self.tkt_scenes = {}
        self.filtered_indices = []; self._dirty = False

        # 可视化模式状态
        self._vis_scene_id = tk.IntVar(value=0)
        self._vis_show_types = {t:tk.BooleanVar(value=True) for t in [5,10,15,16,20,110,200]}
        self._vis_bg_image = None; self._vis_bg_id = None
        self._vis_entities = {}; self._vis_hit_regions = {}
        self._vis_selected = None; self._vis_drag = None
        self._vis_edit_mode = tk.BooleanVar(value=False)  # 编辑开关: 默认关闭(禁止拖动)
        self._undo_pos = None  # 单步撤销: (entity_idx, old_x, old_y)
        self._sc_grp_section_count = 0
        self.item_names = {}  # item_id → 物品名称 (来自 TKItem.dat + TKT)
        self._ani_jvg = None; self._cha_jvg = None; self._cur_jvg = None  # JVG 精灵数据
        self._vis_display_mode = tk.StringVar(value="游戏默认")
        self._vis_anim_playing = False      # 动画播放状态(默认暂停)
        self._vis_anim_timer = None         # 动画循环 timer ID
        self._vis_anim_frame = {}           # entity_idx → current cycle frame offset
        self._vis_play_btn = None           # 播放按钮引用
        self._vis_sel_anim_active = False  # 选中实体动画播放状态
        self._vis_sel_anim_timer = None    # 选中实体动画 timer ID
        self._vis_sel_anim_btn = None      # 选中动画按钮引用
        self.defunit_recs = []; self.defunit_next = {}; self.defunit_entity = {}  # DefUnit链
        self.tkd_defines = []; self.tkd_header = ''; self.tkd_define_map = {}  # TKD脚本
        self.tkt_all = {}  # TKT全文数据库 (用于脚本预览解析对话文本)
        self._preview_win = None   # 脚本预览窗口
        self._preview_step = 0     # 当前预览步骤
        self._preview_cmds = []    # 预览解析的命令列表
        self._bit_enable = tk.BooleanVar(value=False)    # d2 bit0: 启用
        self._bit_visible = tk.BooleanVar(value=False)   # d2 bit1: 可见
        self._bit_pickable = tk.BooleanVar(value=False)  # d2 bit2: 可拾取
        self._bit_hint = tk.BooleanVar(value=False)      # d2 bit3: 提示标记
        self._bit_busy = tk.BooleanVar(value=False)      # d2 bit4: 忙碌
        self._bit_resume = tk.BooleanVar(value=False)    # d2 bit5: 恢复
        self._bit_taken = tk.BooleanVar(value=False)    # d2 bit8: 已拾取(type110)
        self._bit_animloop = tk.BooleanVar(value=False)  # d2 bit16: 动画循环
        self._bit_ev12 = tk.BooleanVar(value=False)      # d2 bit12: 事件标志
        self._bit_ev13 = tk.BooleanVar(value=False)      # d2 bit13: 事件标志(最常用)
        self._bit_ev14 = tk.BooleanVar(value=False)      # d2 bit14: 事件标志
        self._sync_lock = False

        self._build_ui(); self._set_edit_enabled(False)
        sw,sh = self.root.winfo_screenwidth(),self.root.winfo_screenheight()
        w,h = int(sw*0.85), int(sh*0.85)
        self.root.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')

    # =========== UI 构建 ===========
    def _build_ui(self):
        # 菜单栏 (不变)
        mb = tk.Menu(self.root); self.root.config(menu=mb)
        fm = tk.Menu(mb,tearoff=0)
        fm.add_command(label="加载 TKS 目录…",command=self._load_dir,accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存",command=self._save,accelerator="Ctrl+S")
        fm.add_command(label="另存为…",command=self._save_as)
        fm.add_separator(); fm.add_command(label="退出",command=self.root.quit)
        mb.add_cascade(label="文件",menu=fm)
        em = tk.Menu(mb,tearoff=0)
        em.add_command(label="新增记录",command=self._new_record,accelerator="Ctrl+N")
        em.add_command(label="复制当前记录",command=self._copy_record)
        em.add_command(label="清空当前记录",command=self._clear_current)
        mb.add_cascade(label="编辑",menu=em)
        vm = tk.Menu(mb,tearoff=0)
        vm.add_command(label="统计信息",command=self._show_stats)
        mb.add_cascade(label="查看",menu=vm)
        hm = tk.Menu(mb,tearoff=0)
        hm.add_command(label="导出 CSV…",command=self._export_csv)
        hm.add_command(label="字段说明",command=self._show_field_ref)
        hm.add_command(label="关于",command=self._show_about)
        mb.add_cascade(label="帮助",menu=hm)
        self.root.bind('<Control-o>',lambda e:self._load_dir())
        self.root.bind('<Control-s>',lambda e:self._save())
        self.root.bind('<Control-n>',lambda e:self._new_record())
        self.root.bind('<Control-z>', self._vis_canvas_undo)
        self.root.protocol("WM_DELETE_WINDOW",self._on_close)

        # 三栏水平布局
        main_pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pw.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧面板
        self._build_left_panel(main_pw)
        # 中间面板
        self._build_center_panel(main_pw)
        # 右侧编辑面板
        self._build_right_panel(main_pw)

        # 底部路径栏
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0,2))
        self.lbl_path = ttk.Label(pf, text="", foreground="gray")
        self.lbl_path.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        self.lbl_cha = ttk.Label(pf, text="Cha", foreground="gray", font=FONT_S)
        self.lbl_cha.pack(side=tk.LEFT, padx=3, pady=2)
        self.lbl_ani = ttk.Label(pf, text="Ani", foreground="gray", font=FONT_S)
        self.lbl_ani.pack(side=tk.LEFT, padx=3, pady=2)
        self.lbl_cur = ttk.Label(pf, text="Cur", foreground="gray", font=FONT_S)
        self.lbl_cur.pack(side=tk.LEFT, padx=3, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        self.lbl_sc = ttk.Label(pf, text="SC", foreground="gray", font=FONT_S)
        self.lbl_sc.pack(side=tk.LEFT, padx=3, pady=2)

        # 状态栏
        sb = ttk.Frame(self.root)
        sb.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=(0,3))
        self._vis_info = ttk.Label(sb, text="", font=FONT_S, foreground='#666')
        self._vis_info.pack(side=tk.LEFT, padx=4)
        self._vis_coord_label = ttk.Label(sb, text="", font=FONT_S, foreground='#999')
        self._vis_coord_label.pack(side=tk.RIGHT, padx=4)

        # 初始 sash 位置: 2:6:3 → 左~18% 中~55% 右~27%
        def _set_sash(tries=0):
            self.root.update_idletasks()
            w = self.root.winfo_width()
            if w > 100:
                main_pw.sashpos(0, int(w * 2 / 11))
                main_pw.sashpos(1, int(w * 8 / 11))
            elif tries < 5:
                self.root.after(200, lambda: _set_sash(tries+1))
        self.root.after(200, _set_sash)

    # =========== 左侧面板: 场景列表 + 实体列表 ===========
    def _build_left_panel(self, main_pw):
        left_frame = ttk.Frame(main_pw)
        main_pw.add(left_frame, weight=2)
        left_pw = ttk.PanedWindow(left_frame, orient=tk.VERTICAL)
        left_pw.pack(fill=tk.BOTH, expand=True)

        # 上方: 场景列表 (SC.GRP 区段)
        scene_frame = ttk.LabelFrame(left_pw, text="场景列表 (SC.GRP)", padding=2)
        left_pw.add(scene_frame, weight=2)
        cols = ('sid', 'sname', 'cnt')
        self._vis_tree = ttk.Treeview(scene_frame, columns=cols, show='headings', selectmode='browse')
        self._vis_tree.heading('sid', text='SC#'); self._vis_tree.column('sid', width=45, anchor='center')
        self._vis_tree.heading('sname', text='场景名称'); self._vis_tree.column('sname', width=120)
        self._vis_tree.heading('cnt', text='实体'); self._vis_tree.column('cnt', width=40, anchor='center')
        vsb0 = ttk.Scrollbar(scene_frame, orient=tk.VERTICAL, command=self._vis_tree.yview)
        self._vis_tree.configure(yscrollcommand=vsb0.set)
        self._vis_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb0.pack(side=tk.RIGHT, fill=tk.Y)
        self._vis_tree.bind('<<TreeviewSelect>>', self._on_vis_scene_select)

        # 下方: 实体列表 + 搜索工具栏
        entity_frame = ttk.LabelFrame(left_pw, text="实体列表", padding=2)
        left_pw.add(entity_frame, weight=1)
        # 搜索/筛选工具栏
        tb = ttk.Frame(entity_frame); tb.pack(fill=tk.X, pady=(0,2))
        ttk.Label(tb,text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e_s = ttk.Entry(tb,textvariable=self.search_var,width=12)
        e_s.pack(side=tk.LEFT,padx=2)
        e_s.bind('<Return>',lambda e:self._apply_filter())
        ttk.Button(tb,text="搜索",command=self._apply_filter,width=4).pack(side=tk.LEFT,padx=1)
        ttk.Button(tb,text="清除",command=self._clear_filter,width=4).pack(side=tk.LEFT,padx=1)
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=4)
        ttk.Label(tb,text="类型:").pack(side=tk.LEFT)
        self.filter_type = tk.StringVar(value="全部")
        tc = ["全部"]+[f"{k}-{v}" for k,v in sorted(ENTITY_TYPES.items()) if k!=0]
        cb=ttk.Combobox(tb,textvariable=self.filter_type,values=tc,state='readonly',width=12)
        cb.pack(side=tk.LEFT,padx=2)
        cb.bind('<<ComboboxSelected>>',lambda e:self._apply_filter())
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=4)
        ttk.Label(tb,text="场景:").pack(side=tk.LEFT)
        self.filter_scene=tk.StringVar(value="全部")
        self.cb_scene=ttk.Combobox(tb,textvariable=self.filter_scene,values=["全部"],state='readonly',width=14)
        self.cb_scene.pack(side=tk.LEFT,padx=2)
        self.cb_scene.bind('<<ComboboxSelected>>',lambda e:self._apply_filter())
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=4)
        self.show_empty=tk.BooleanVar(value=False)
        ttk.Checkbutton(tb,text="空槽",variable=self.show_empty,command=self._apply_filter).pack(side=tk.LEFT,padx=1)
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=4)
        ttk.Button(tb,text="重载",command=self._reload,width=4).pack(side=tk.LEFT,padx=1)
        self.status_var=tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb,textvariable=self.status_var,foreground="gray",font=FONT_S).pack(side=tk.RIGHT,padx=4)
        # 实体 Treeview
        cols2 = ('index','type','scene','x','y','script','tick')
        self.tree = ttk.Treeview(entity_frame, columns=cols2, show='headings', selectmode='browse')
        for cid,cn,cw in [('index','索引',40),('type','类型',75),('scene','场景',95),('x','X',40),('y','Y',40),('script','脚本',65),('tick','Tick',38)]:
            self.tree.heading(cid,text=cn,command=lambda c=cid:self._sort_by(c))
            self.tree.column(cid,width=cw,anchor='center' if cid in('index','x','y','tick') else 'w',minwidth=cw)
        vsb = ttk.Scrollbar(entity_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        for tv,cl in TYPE_COLORS.items(): self.tree.tag_configure(f'type{tv}', foreground=cl)

    # =========== 中间面板: 地图预览 ===========
    def _build_center_panel(self, main_pw):
        center_frame = ttk.Frame(main_pw)
        main_pw.add(center_frame, weight=6)

        # 顶部工具栏
        top = ttk.Frame(center_frame); top.pack(fill=tk.X, pady=(0,2))
        ttk.Label(top, text="场景:").pack(side=tk.LEFT)
        self._vis_scene_combo = ttk.Combobox(top, state='readonly', width=20)
        self._vis_scene_combo.pack(side=tk.LEFT, padx=2)
        self._vis_scene_combo.bind('<<ComboboxSelected>>', lambda e: self._on_vis_combo_select())
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=3)
        for tval in [5,10,15,16,20,110,200]:
            ttk.Checkbutton(top, text=ENTITY_TYPES.get(tval,f"T{tval}"),
                            variable=self._vis_show_types[tval],
                            command=self._vis_redraw).pack(side=tk.LEFT, padx=1)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=3)
        ttk.Label(top, text="显示:").pack(side=tk.LEFT)
        cb_mode = ttk.Combobox(top, textvariable=self._vis_display_mode,
                               values=list(DISPLAY_MODES.keys()), state='readonly', width=6)
        cb_mode.pack(side=tk.LEFT, padx=2)
        cb_mode.bind('<<ComboboxSelected>>', lambda e: self._on_display_mode_change())
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=3)
        # 动画播放按钮
        self._vis_play_btn = ttk.Button(top, text="▶", command=self._vis_toggle_anim, width=3)
        self._vis_play_btn.pack(side=tk.LEFT, padx=1)
        self._bind_tooltip(self._vis_play_btn, "播放/暂停精灵动画")
        # 选中实体动画按钮
        self._vis_sel_anim_btn = ttk.Button(top, text="▷", command=self._vis_toggle_sel_anim, width=3)
        self._vis_sel_anim_btn.pack(side=tk.LEFT, padx=1)
        self._bind_tooltip(self._vis_sel_anim_btn, "播放/暂停当前选中实体的动画")
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=3)
        ttk.Button(top, text="刷新", command=self._vis_load_scene, width=4).pack(side=tk.LEFT, padx=1)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=3)
        # 编辑开关(默认关闭,防止误拖动)
        self._vis_edit_check = ttk.Checkbutton(top, text="允许拖动", variable=self._vis_edit_mode,
                                                command=self._on_edit_mode_change)
        self._vis_edit_check.pack(side=tk.LEFT, padx=1)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=3)
        ttk.Button(top, text="新增实体", command=self._new_record, width=8).pack(side=tk.LEFT, padx=1)

        # 地图画布
        cf = ttk.Frame(center_frame); cf.pack(fill=tk.BOTH, expand=True)
        self._vis_canvas = tk.Canvas(cf, bg='#1a1a2e', highlightthickness=0, cursor='crosshair')
        hsb = ttk.Scrollbar(cf, orient=tk.HORIZONTAL, command=self._vis_canvas.xview)
        vsb2 = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self._vis_canvas.yview)
        self._vis_canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb2.set)
        self._vis_canvas.grid(row=0, column=0, sticky='nsew')
        hsb.grid(row=1, column=0, sticky='ew'); vsb2.grid(row=0, column=1, sticky='ns')
        cf.rowconfigure(0, weight=1); cf.columnconfigure(0, weight=1)

        self._vis_canvas.bind('<Button-1>', self._vis_canvas_click)
        self._vis_canvas.bind('<B1-Motion>', self._vis_canvas_drag)
        self._vis_canvas.bind('<ButtonRelease-1>', self._vis_canvas_release)
        self._vis_canvas.bind('<MouseWheel>', lambda e: self._vis_canvas.xview_scroll(int(-1*(e.delta/120)),"units") if e.state & 0x1 else self._vis_canvas.yview_scroll(int(-1*(e.delta/120)),"units"))
        self._vis_canvas.bind('<Motion>', lambda e: self._vis_coord_label.config(text=f"坐标: ({int(self._vis_canvas.canvasx(e.x))}, {int(self._vis_canvas.canvasy(e.y))})"))

    # =========== 右侧面板: 编辑区 ===========
    def _build_right_panel(self, main_pw):
        rf = ttk.Frame(main_pw); main_pw.add(rf, weight=3); self.edit_frame = rf
        self.lbl_title = ttk.Label(rf, text="未选中", font=FONT_B)
        self.lbl_title.pack(anchor=tk.W, pady=(0,4), padx=4)

        # Notebook 双标签
        self.notebook = ttk.Notebook(rf)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # === Tab "参数" — 现有字段编辑区 ===
        tab_param = ttk.Frame(self.notebook)
        self.notebook.add(tab_param, text="参数")
        mid = ttk.Frame(tab_param); mid.pack(fill=tk.BOTH, expand=True)
        lc = ttk.Frame(mid); lc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scb = ttk.Scrollbar(mid, orient=tk.VERTICAL); scb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas = tk.Canvas(lc, highlightthickness=0); canvas.pack(fill=tk.BOTH, expand=True)
        self.edit_inner = ttk.Frame(canvas); self.edit_inner.columnconfigure(0, weight=1)
        self.edit_inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0), window=self.edit_inner, anchor='nw')
        canvas.configure(yscrollcommand=scb.set)
        canvas.bind('<Configure>', lambda e: self.edit_inner.columnconfigure(0, minsize=e.width))
        def _mw(e): canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        # 构建编辑字段组 + 位域 checkbutton 双向同步
        self._edit_vars = {}
        self._param_labels = {}  # di → (label_widget, default_text, default_tooltip)
        self._build_group("基础属性", BASIC_FIELDS, 0)
        self._build_group("位置", POS_FIELDS, 1)
        self._build_group("动画", ANIM_FIELDS, 2)
        self._build_group("物品", ITEM_FIELDS, 3)
        self._build_group("脚本", SCRIPT_FIELDS, 4)
        self._build_group("交互/角色", INTERACT_FIELDS, 5)
        self._build_group("运行时(只读)", RUNTIME_FIELDS, 6)
        # flags ↔ checkbutton 双向同步
        self._sync_lock = False
        _bit_vars = [(self._bit_enable,1), (self._bit_visible,2), (self._bit_pickable,4),
                     (self._bit_hint,8), (self._bit_busy,0x10), (self._bit_resume,0x20),
                     (self._bit_taken,0x100), (self._bit_animloop,0x10000),
                     (self._bit_ev12,0x1000), (self._bit_ev13,0x2000), (self._bit_ev14,0x4000)]
        def _on_cb(*args):
            if self._sync_lock: return
            self._sync_lock = True
            try: flags = int(self._edit_vars['flags'].get())
            except ValueError: flags = 0
            for bv, mask in _bit_vars:
                if bv.get(): flags |= mask
                else: flags &= ~mask
            self._edit_vars['flags'].set(str(flags))
            self._sync_lock = False
        def _on_flags(*args):
            if self._sync_lock: return
            self._sync_lock = True
            try: flags = int(self._edit_vars['flags'].get())
            except ValueError: self._sync_lock = False; return
            for bv, mask in _bit_vars: bv.set((flags & mask) != 0)
            self._sync_lock = False
        self._edit_vars['flags'].trace_add('write', _on_flags)
        for bv, _ in _bit_vars: bv.trace_add('write', _on_cb)

        # === Tab "脚本" — 占位 (稍后 _build_script_tab 填充) ===
        self.tab_script = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_script, text="脚本")
        self._build_script_tab()

        # === Tab "全部" — 所有 96 dword 按序显示 ===
        self.tab_all = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_all, text="全部")
        self._build_all_tab()

        # 按钮 (Notebook 外面底部)
        bf = ttk.Frame(rf); bf.pack(side=tk.BOTTOM, fill=tk.X, pady=(2,0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(side=tk.LEFT)
        ttk.Button(bf, text="重置", command=self._reset_edit, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="跳转到空槽…", command=self._goto_empty, width=12).pack(side=tk.RIGHT, padx=2)

    def _build_group(self,title,fields,row):
        lf=ttk.LabelFrame(self.edit_inner,text=title,padding=4)
        lf.grid(row=row,column=0,sticky='ew',padx=2,pady=2)
        grid=ttk.Frame(lf); grid.pack(fill=tk.X)
        for fi,(key,di,label,cmt) in enumerate(fields):
            r,c=divmod(fi,3); frm=ttk.Frame(grid); frm.grid(row=r,column=c,sticky='nw',padx=4,pady=2)
            lbl=ttk.Label(frm,text=f"[{di:02d}] {label}",font=FONT_S); lbl.pack(anchor=tk.W)
            if cmt: self._bind_tooltip(lbl,f"[{di:02d}] {cmt}")
            # 存储标签引用 + 默认文本 + tooltip, 供 _show_record 动态更新
            self._param_labels[di] = (lbl, label, cmt)
            if key=='type':
                cb=ttk.Combobox(frm,state='readonly',values=[f"{k}-{v}" for k,v in sorted(ENTITY_TYPES.items())],width=14,font=FONT)
                cb.pack(fill=tk.X); self._edit_vars[key]=cb
            elif key=='anim_set':
                cb=ttk.Combobox(frm,state='readonly',values=[f"{k}-{v}" for k,v in ANIM_SETS.items()],width=16,font=FONT)
                cb.pack(fill=tk.X); self._edit_vars[key]=cb
            elif key=='blend_mode':
                cb=ttk.Combobox(frm,state='readonly',values=["0-正常","1-染色","2-加法发光","3-减法压暗","4-亮度alpha","5-水平翻转"],width=16,font=FONT)
                cb.pack(fill=tk.X); self._edit_vars[key]=cb
            elif key=='shadow_frame':
                cb=ttk.Combobox(frm,state='readonly',values=["0-无阴影","1-小阴影(39×23)","2-大阴影(65×33)"],width=16,font=FONT)
                cb.pack(fill=tk.X); self._edit_vars[key]=cb
            elif key=='flags':
                ev=tk.StringVar(); self._edit_vars[key]=ev
                ttk.Entry(frm,textvariable=ev,width=14,font=FONT).pack(fill=tk.X)
                cbf=ttk.Frame(frm); cbf.pack(fill=tk.X, pady=(2,0))
                # 位域 checkbutton: 按实体类型显示/隐藏对应行
                # 第1行: 通用 bit0~3
                bits_r1=[("_bit_enable","启用","bit0=启用(Enabled): 参与游戏循环和脚本执行"),
                         ("_bit_visible","显示","bit1=可见(Visible): 渲染到屏幕"),
                         ("_bit_pickable","可交互","bit2=可交互(Interactive): 可被点击触发交互"),
                         ("_bit_hint","提示","bit3=提示标记(Hint): 显示浮动提示")]
                # 第2行: 通用 bit4~5 + type110 bit8 + 通用 bit16
                bits_r2=[("_bit_busy","忙碌","bit4=忙碌(Busy): 脚本交互执行中, 阻塞移动"),
                         ("_bit_resume","恢复","bit5=恢复(Resume): 交互结束恢复标记"),
                         ("_bit_taken","已拾取","bit8=已拾取: type110 d52=0模式标记, sub_408B30检查"),
                         ("_bit_animloop","循环动画","bit16=动画循环: 精灵动画循环播放")]
                # 第3行: type20/200 事件标志 bit12~14 (仅事件相关实体显示)
                bits_r3=[("_bit_ev12","事件标志A","bit12=事件标志: type20/200渲染/行为控制位"),
                         ("_bit_ev13","事件标志B","bit13=事件标志(最常用): type20/200 共104实体使用"),
                         ("_bit_ev14","事件标志C","bit14=事件标志: type20/200 共29实体使用")]
                self._flags_row_frames = []
                for ri,row_bits in enumerate([bits_r1,bits_r2,bits_r3]):
                    rf=ttk.Frame(cbf); rf.pack(fill=tk.X)
                    self._flags_row_frames.append(rf)
                    for attr,text,ttip in row_bits:
                        cb=ttk.Checkbutton(rf,text=text,variable=getattr(self,attr))
                        cb.pack(side=tk.LEFT,padx=1)
                        self._bind_tooltip(cb,ttip)
            else:
                ev=tk.StringVar(); self._edit_vars[key]=ev
                ttk.Entry(frm,textvariable=ev,width=14,font=FONT).pack(fill=tk.X)
            if key=='scene_id':
                nl=ttk.Label(frm,text="",foreground='#3366cc',font=FONT_S,wraplength=150)
                nl.pack(anchor=tk.W); self._edit_vars['_scene_label']=nl
            if key=='hint_id':
                hl=ttk.Label(frm,text="",foreground='#3366cc',font=FONT_S,wraplength=150)
                hl.pack(anchor=tk.W); self._edit_vars['_hint_label']=hl
            if key in ('item_g1_id','item_g2_id','item_g3_id'):
                il=ttk.Label(frm,text="",foreground='#996600',font=FONT_S,wraplength=150)
                il.pack(anchor=tk.W); self._edit_vars[f'_{key}_label']=il
        return lf

    def _build_script_tab(self):
        """构建 Tab "脚本" — 脚本调度信息 + DefUnit 链列表 + 脚本编辑器"""
        pw = ttk.PanedWindow(self.tab_script, orient=tk.VERTICAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # 上方: 脚本调度信息 (基于逆向 sub_409618/sub_408E5C/sub_4081F8 等)
        sched_f = ttk.LabelFrame(pw, text="脚本调度信息", padding=4)
        pw.add(sched_f, weight=1)
        self._sched_labels = {}
        sg = ttk.Frame(sched_f); sg.pack(fill=tk.X)
        sched_items = [
            ('enabled', '启用', 'flags bit0=启用: 实体参与游戏循环。sub_409618: 检查d2&1'),
            ('pickable', '可交互', 'flags bit2=可交互: 写入拾取缓冲区可被点击。sub_408E5C: 点击触发交互'),
            ('tick', 'Tick周期', 'd4=Tick: 控制脚本执行频率。sub_409618: d5递增到d4时触发'),
            ('timer', '定时器', 'd3=定时器: >0时实体暂停处理。sub_409618: 每帧递减'),
            ('chain_a', 'A链(自动)', '子场景A = 自动运行(Tick)脚本。sub_409618: cur_A>0时每Tick自动执行'),
            ('chain_b', 'B链(触发)', '子场景B = 触发(交互)脚本。sub_4081F8/408408/4084E0/408E5C: 交互时执行'),
            ('chain_c', 'C链(其他)', '子场景C = 保留链。可能由特定游戏事件触发'),
            ('trigger', '触发方式', '基于实体类型和逆向分析: type=5/10:接近触发 type=15:接近+条件 type=16:接近+道具 type=20/200:点击对话 type=110:点击机关'),
        ]
        for ri, (key, label, tip) in enumerate(sched_items):
            r, c = divmod(ri, 4)
            frm = ttk.Frame(sg); frm.grid(row=r, column=c, sticky='w', padx=4, pady=1)
            lbl = ttk.Label(frm, text=f"{label}:", font=FONT_S, foreground='#555')
            lbl.pack(side=tk.LEFT)
            val = ttk.Label(frm, text="", font=FONT_S, foreground='black', width=16)
            val.pack(side=tk.LEFT, padx=(2,0))
            if tip: self._bind_tooltip(lbl, tip)
            self._sched_labels[key] = val

        # 中间: DefUnit 链编辑区
        top_f = ttk.LabelFrame(pw, text="DefUnit 链节点", padding=4)
        pw.add(top_f, weight=3)
        tb = ttk.Frame(top_f); tb.pack(fill=tk.X, pady=(0,2))
        ttk.Button(tb, text="新增到A", command=lambda: self._add_chain_entry('A'), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="新增到B", command=lambda: self._add_chain_entry('B'), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="新增到C", command=lambda: self._add_chain_entry('C'), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="删除选中", command=self._delete_chain_entry, width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="刷新", command=self._refresh_chain_list, width=5).pack(side=tk.LEFT, padx=(8,0))
        self.chain_info_lbl = ttk.Label(tb, text="", font=FONT_S, foreground='#666')
        self.chain_info_lbl.pack(side=tk.RIGHT, padx=4)

        cols_chain = ('seq', 'sub', 'du_idx', 'define_id', 'block_id', 'mark')
        self.chain_tree = ttk.Treeview(top_f, columns=cols_chain, show='headings', selectmode='browse')
        col_defs_chain = [('seq', '序号', 35), ('sub', '子场景', 35),
                          ('du_idx', 'DefUnit#', 55), ('define_id', 'DEFINE ID', 110),
                          ('block_id', 'f0', 35), ('mark', '标记', 50)]
        for cid, cn, cw in col_defs_chain:
            self.chain_tree.heading(cid, text=cn)
            self.chain_tree.column(cid, width=cw, anchor='center' if cid != 'define_id' else 'w', minwidth=cw)
        csb = ttk.Scrollbar(top_f, orient=tk.VERTICAL, command=self.chain_tree.yview)
        self.chain_tree.configure(yscrollcommand=csb.set)
        self.chain_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); csb.pack(side=tk.RIGHT, fill=tk.Y)
        self.chain_tree.bind('<<TreeviewSelect>>', self._on_chain_select)

        # 下方: 脚本编辑器 + 预览按钮
        bot_f = ttk.LabelFrame(pw, text="DEFINE 脚本", padding=4)
        pw.add(bot_f, weight=5)
        # 脚本工具栏: 信息 + 预览按钮
        stb = ttk.Frame(bot_f); stb.pack(fill=tk.X, pady=(0,2))
        self.script_info_lbl = ttk.Label(stb, text="(未选中 DEFINE)", font=FONT_S, foreground='#666')
        self.script_info_lbl.pack(side=tk.LEFT)
        ttk.Button(stb, text="▶ 预览", command=self._preview_script, width=8).pack(side=tk.RIGHT, padx=2)
        self._bind_tooltip(stb.winfo_children()[-1], "预览当前脚本执行流程\n解析脚本命令, 显示人类可读的执行步骤\n对话文本会自动从 TKT 解析")
        ef = ttk.Frame(bot_f); ef.pack(fill=tk.BOTH, expand=True)
        self.script_text = tk.Text(ef, font=FONT_MONO, wrap=tk.NONE, undo=True,
                                   tabs=('4c',), bg='#fafafa')
        ssb_y = ttk.Scrollbar(ef, orient=tk.VERTICAL, command=self.script_text.yview)
        ssb_x = ttk.Scrollbar(ef, orient=tk.HORIZONTAL, command=self.script_text.xview)
        self.script_text.configure(yscrollcommand=ssb_y.set, xscrollcommand=ssb_x.set)
        self.script_text.grid(row=0, column=0, sticky='nsew')
        ssb_y.grid(row=0, column=1, sticky='ns'); ssb_x.grid(row=1, column=0, sticky='ew')
        ef.rowconfigure(0, weight=1); ef.columnconfigure(0, weight=1)
        self.script_text.bind('<KeyRelease>', self._on_script_edit)
        # 语法高亮 tag 配置
        for tag, fg in [('keyword','#0000FF'), ('comment','#008000'), ('number','#B07000'),
                         ('command','#7B30D0'), ('block','#C00000')]:
            self.script_text.tag_configure(tag, foreground=fg)
        self.script_text.config(state='disabled')
        self._current_edit_define_id = None
        self._script_dirty = False

    def _bind_tooltip(self,widget,text):
        tip={'win':None}
        def _enter(e):
            if tip['win']: return
            x=widget.winfo_rootx()+10; y=widget.winfo_rooty()+widget.winfo_height()+2
            w=tk.Toplevel(widget); w.wm_overrideredirect(True); w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w,text=text,background='#FFFFE0',relief='solid',borderwidth=1,font=FONT_S,wraplength=450,padding=3).pack()
            tip['win']=w
        def _leave(e):
            if tip['win']: tip['win'].destroy(); tip['win']=None
        widget.bind('<Enter>',_enter); widget.bind('<Leave>',_leave)

    # =========== 可视化模式逻辑 ===========
    def _vis_populate_scenes(self):
        """以 SC.GRP section 顺序填充场景列表 (SC.GRP 为权威源)"""
        self._vis_tree.delete(*self._vis_tree.get_children())
        if not self.records: return

        # 统计 TKMat 中各 scene_id 的实体数
        from collections import defaultdict
        smap = defaultdict(list)
        for r in self.records:
            if has_data(r) and r['d1'] >= 0:
                smap[r['d1']].append(r['index'])

        # 以 SC.GRP section 数作为权威范围
        total_scenes = self._sc_grp_section_count if self._sc_grp_section_count > 0 else max(smap.keys()) + 1
        scenes = []
        for sid in range(total_scenes):
            sname = scene_name(self.tkt_scenes, sid)
            cnt = len(smap.get(sid, []))
            scenes.append((sid, sname, cnt))

        combo_vals = [f"{sid}: {sname} ({cnt}实体)" for sid, sname, cnt in scenes]
        self._vis_scene_combo['values'] = combo_vals
        for sid, sname, cnt in scenes:
            self._vis_tree.insert('', 'end', values=(str(sid), sname, str(cnt)))

    def _build_all_tab(self):
        """Tab '全部': 按 d0~d95 顺序展示全部 96 个字段"""
        mid = ttk.Frame(self.tab_all); mid.pack(fill=tk.BOTH, expand=True)
        lc = ttk.Frame(mid); lc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scb = ttk.Scrollbar(mid, orient=tk.VERTICAL); scb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas = tk.Canvas(lc, highlightthickness=0); canvas.pack(fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scb.set)
        scb.configure(command=canvas.yview)
        def _mw(e): canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # 构建所有已知字段映射: di → (name, label, comment)
        known = {}
        for fields in (BASIC_FIELDS, POS_FIELDS, ANIM_FIELDS, SCRIPT_FIELDS, INTERACT_FIELDS, RUNTIME_FIELDS):
            for name, di, label, cmt in fields:
                known[di] = (name, label, cmt)

        # 每行 4 个字段, 独立 key 避免与 "参数"tab 的 Combobox 冲突
        self._all_labels = {}  # di → label_widget
        for di in range(96):
            r, c = divmod(di, 4)
            frm = ttk.Frame(inner); frm.grid(row=r, column=c, sticky='nw', padx=2, pady=1)
            if di in known:
                name, label, cmt = known[di]
                key = f'raw_{di}'
                lbl = ttk.Label(frm, text=f"[{di:02d}] {label}", font=FONT_S)
            else:
                key = f'd{di}'; label = f'd{di}'; cmt = ""
                lbl = ttk.Label(frm, text=f"[{di:02d}] d{di}", font=FONT_S, foreground='#888')
            lbl.pack(anchor=tk.W)
            if cmt: self._bind_tooltip(lbl, f"[{di:02d}] {cmt}")
            ev = tk.StringVar(); self._edit_vars[key] = ev
            ttk.Entry(frm, textvariable=ev, width=10, font=FONT_S).pack(fill=tk.X)
            self._all_labels[di] = lbl

    def _update_param_labels(self, tval):
        """根据实体类型更新'参数'tab的字段标签和tooltip"""
        type_labels = _TYPE_LABELS.get(tval, {})
        if tval == 20: type_labels = _TYPE_LABELS.get(200, {})
        known = {}
        for fields in (BASIC_FIELDS, POS_FIELDS, ANIM_FIELDS, ITEM_FIELDS, SCRIPT_FIELDS, INTERACT_FIELDS, RUNTIME_FIELDS):
            for name, di, label, cmt in fields:
                known[di] = (label, cmt)
        for di, (lbl, def_label, def_cmt) in self._param_labels.items():
            if di in type_labels:
                tl, tc = type_labels[di]
                lbl.config(text=f"[{di:02d}] {tl}", foreground='#cc6600')
                tt = f"[{di:02d}] {tl}"
                if tc: tt += f": {tc}"
                self._bind_tooltip(lbl, tt)
            else:
                lbl.config(text=f"[{di:02d}] {def_label}", foreground='black')
                if def_cmt: self._bind_tooltip(lbl, f"[{di:02d}] {def_cmt}")

    def _update_all_tab_labels(self, tval):
        """根据实体类型更新'全部'tab的字段标签"""
        type_labels = _TYPE_LABELS.get(tval, {})
        # type=20 与 type=200 共享语义
        if tval == 20:
            type_labels = _TYPE_LABELS.get(200, {})
        known = {}
        for fields in (BASIC_FIELDS, POS_FIELDS, ANIM_FIELDS, ITEM_FIELDS, SCRIPT_FIELDS, INTERACT_FIELDS, RUNTIME_FIELDS):
            for name, di, label, cmt in fields:
                known[di] = (name, label, cmt)
        for di in range(96):
            if di not in self._all_labels: continue
            lbl = self._all_labels[di]
            if di in type_labels:
                tl, tc = type_labels[di]
                lbl.config(text=f"[{di:02d}] {tl}", foreground='#cc6600')  # 橙色=类型特有
                if tc: self._bind_tooltip(lbl, f"[{di:02d}] {tl}: {tc}")
            elif di in known:
                name, label, cmt = known[di]
                lbl.config(text=f"[{di:02d}] {label}", foreground='black')
            else:
                lbl.config(text=f"[{di:02d}] d{di}", foreground='#888')

    def _update_flags_visibility(self, tval):
        """根据实体类型显示/隐藏 flags 复选框行"""
        if not hasattr(self, '_flags_row_frames') or not self._flags_row_frames:
            return
        # 第3行 (bit12~14): 仅 type=20(事件对象) 或 type=200(NPC) 时显示
        row3 = self._flags_row_frames[2]
        if tval in (20, 200):
            row3.pack(fill=tk.X)
        else:
            row3.pack_forget()

    def _sync_entity_filter_to_scene(self, sid):
        """场景选中后同步筛选左侧实体列表为该场景的实体"""
        for v in self.cb_scene['values']:
            if v == "全部": continue
            try:
                if int(v.split(':')[0]) == sid:
                    self.filter_scene.set(v); break
            except ValueError: continue
        else:
            self.filter_scene.set(f"{sid}: {scene_name(self.tkt_scenes, sid)}")
        self._apply_filter()

    def _sync_entity_list_select(self, idx):
        """在实体列表中选中并滚动到指定实体"""
        for item in self.tree.get_children():
            if self.tree.item(item, 'values')[0] == str(idx):
                self.tree.selection_set(item)
                self.tree.see(item)
                return True
        return False

    def _on_vis_combo_select(self):
        val = self._vis_scene_combo.get()
        try: sid = int(val.split(':')[0])
        except ValueError: return
        self._vis_scene_id.set(sid)
        self._vis_stop_anim()
        self._vis_load_scene()
        self._sync_entity_filter_to_scene(sid)

    def _on_vis_scene_select(self, event):
        sel = self._vis_tree.selection()
        if not sel: return
        sid = int(self._vis_tree.item(sel[0], 'values')[0])
        self._vis_scene_id.set(sid)
        for v in self._vis_scene_combo['values']:
            if v.startswith(f"{sid}:"): self._vis_scene_combo.set(v); break
        self._vis_stop_anim()
        self._vis_load_scene()
        self._sync_entity_filter_to_scene(sid)

    def _vis_load_scene(self):
        """加载场景到画布 (PIL 预合成)"""
        sid = self._vis_scene_id.get()
        self._vis_canvas.delete('all')
        self._vis_entities.clear(); self._vis_selected = None; self._vis_drag = None
        self._vis_stop_sel_anim()
        self._vis_hit_regions = {}
        self._vis_anim_frame.clear()
        # 限制缓存
        for cache in (_SPRITE_CACHE, _SHADOW_CACHE, _BLEND_CACHE, _RGBA_CACHE):
            if len(cache) > 300:
                for k in list(cache.keys())[:len(cache)-300]: del cache[k]
        if not self.records: return

        # 背景 PIL Image
        self._vis_bg_pil = None; self._vis_bg_image = None
        if self.dat_path:
            d = os.path.dirname(self.dat_path)
            grp_path = os.path.join(d, "SC.GRP"); idx_path = os.path.join(d, "SC.IDX")
            if os.path.exists(grp_path):
                try:
                    bg = load_scene_background(grp_path, idx_path, sid)
                    if bg: self._vis_bg_pil = bg
                except Exception: pass

        ents = [r for r in self.records if has_data(r) and r['d1'] == sid]
        sname = scene_name(self.tkt_scenes, sid)
        if not ents:
            self._vis_info.config(text=f"SC.GRP #{sid}: {sname} — 无实体 (空场景)")
            self._vis_canvas.configure(scrollregion=(0,0,MAX_MAP_W,MAX_MAP_H))
            return
        ents.sort(key=lambda r: r['d19'] if r['d0'] == 10 else r['d11'])

        # 画布尺寸
        xs = [r['d10'] for r in ents]; ys = [r['d11'] for r in ents]
        minx, maxx = min(xs)-50, max(xs)+50; miny, maxy = min(ys)-50, max(ys)+50
        w = max(MAX_MAP_W, maxx - minx + 200); h = max(MAX_MAP_H, maxy - miny + 200)
        self._vis_canvas.configure(scrollregion=(0, 0, w, h))

        self._vis_render_scene(ents, w, h)
        self._vis_info.config(text=f"SC.GRP #{sid}: {sname} — {len(ents)} 个实体")
        if self._vis_anim_playing: self._vis_start_anim()

    def _vis_start_anim(self):
        """启动精灵动画循环 (~200ms/帧)"""
        if self._vis_anim_timer: return
        mode = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')
        if mode in ('wire', 'cha'): return
        def _tick():
            m = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')
            if m in ('wire', 'cha'):
                self._vis_anim_timer = None; return
            for idx in list(self._vis_anim_frame.keys()):
                self._vis_anim_frame[idx] += 1
            self._vis_redraw()
            self._vis_anim_timer = self.root.after(200, _tick)
        self._vis_anim_timer = self.root.after(200, _tick)

    def _vis_stop_anim(self):
        if self._vis_anim_timer:
            self.root.after_cancel(self._vis_anim_timer)
            self._vis_anim_timer = None

    def _vis_render_scene(self, ents, w, h):
        """PIL 预合成整个场景并显示到 Canvas"""
        from PIL import Image, ImageDraw, ImageTk, ImageOps
        mode = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')

        # 背景
        if self._vis_bg_pil:
            composite = self._vis_bg_pil.copy()
            # 扩展到画布尺寸
            if composite.width < w or composite.height < h:
                new_bg = Image.new('RGB', (w, h), (26, 26, 46))
                new_bg.paste(composite, (0, 0))
                composite = new_bg
        else:
            composite = Image.new('RGB', (w, h), (26, 26, 46))  # 深蓝黑底色

        for r in ents:
            tval = r['d0']
            if not self._vis_show_types.get(tval, tk.BooleanVar(value=True)).get():
                continue
            idx = r['index']; x = r['d10']; y = r['d11']
            color = TYPE_COLORS_RGBA.get(tval, (128,128,128))

            # JVG 精灵选择 (与旧逻辑一致)
            sprite_rgba = None; shadow_rgba = None
            sx = sy = 0; jvg = None; blk_idx = 0; should_animate = False
            if mode != 'wire':
                if mode == 'auto':
                    if tval == 200:
                        if r['d70'] == 1 and r['d64'] > 0 and self._ani_jvg:
                            jvg = self._ani_jvg; blk_idx = r['d64']; should_animate = True
                        elif r['d51'] > 0 and self._cha_jvg:
                            jvg = self._cha_jvg; blk_idx = r['d51']
                    elif tval in (20, 110) and r['d64'] > 0 and self._ani_jvg:
                        jvg = self._ani_jvg; blk_idx = r['d64']; should_animate = True
                elif mode == 'ani':
                    if tval in (200, 20, 110) and r['d64'] > 0 and self._ani_jvg:
                        jvg = self._ani_jvg; blk_idx = r['d64']; should_animate = True
                elif mode == 'cha':
                    if tval == 200 and r['d51'] > 0 and self._cha_jvg:
                        jvg = self._cha_jvg; blk_idx = r['d51']
                    elif tval in (20, 110) and r['d64'] > 0 and self._ani_jvg:
                        jvg = self._ani_jvg; blk_idx = r['d64']
            if jvg and blk_idx < jvg.block_count:
                blk = jvg.blocks[blk_idx]
                if blk.frames:
                    if should_animate and idx not in self._vis_anim_frame:
                        self._vis_anim_frame[idx] = 0
                    anim = self._vis_anim_frame.get(idx, 0) if should_animate else 0
                    fi, fpd = _get_dir_frame(blk, r['d13'], r['d16'], r['d53'], anim)
                    if fi < len(blk.frames):
                        blend_mode = r.get('d24', 0); blend_param = r.get('d25', 0)
                        sprite_rgba = _get_jvg_frame_rgba(jvg, blk_idx, fi)
                        if sprite_rgba:
                            sx = x + blk.frames[fi].x_off; sy = y + blk.frames[fi].y_off
                            # mode 5: 水平翻转
                            if blend_mode == 5:
                                sprite_rgba = ImageOps.mirror(sprite_rgba)
                            # mode 1: 染色
                            if blend_mode == 1:
                                sprite_rgba = _pil_tint(sprite_rgba, blend_param)
                            # 阴影: sub_406864:37 — d55>0时以该值为Cha.JVG全局帧索引绘阴影
                            shadow_fi = r.get('d55', 0)
                            if shadow_fi > 0 and (tval == 200 or tval == 20) and jvg is self._cha_jvg and jvg.block_count > 0:
                                blk0 = jvg.blocks[0]
                                if blk0.frames and shadow_fi < blk0.frame_count:
                                    shadow_rgba = _get_jvg_frame_rgba(jvg, 0, shadow_fi)
                            # 存储命中区域
                            fw = sprite_rgba.width; fh = sprite_rgba.height
                            self._vis_hit_regions[idx] = (sx, sy, sx+fw, sy+fh)
                            # 合成
                            if shadow_rgba:
                                _pil_subtract(composite, shadow_rgba, x + jvg.blocks[0].frames[shadow_fi].x_off,
                                             y + jvg.blocks[0].frames[shadow_fi].y_off)
                            blend_func = {0:_pil_normal, 2:_pil_additive, 3:_pil_subtract, 4:_pil_luma_alpha,
                                          5:_pil_normal}.get(blend_mode, _pil_normal)
                            if blend_mode == 2:
                                _pil_additive(composite, sprite_rgba, sx, sy, blend_param)
                            elif blend_mode == 3:
                                _pil_subtract(composite, sprite_rgba, sx, sy)
                            elif blend_mode == 4:
                                _pil_luma_alpha(composite, sprite_rgba, sx, sy)
                            else:
                                _pil_normal(composite, sprite_rgba, sx, sy)

            # 无精灵时画几何形状
            if sprite_rgba is None and mode == 'wire' and jvg and blk_idx < jvg.block_count:
                blk = jvg.blocks[blk_idx]
                if blk.frames:
                    fi, _ = _get_dir_frame(blk, r['d13'], r['d16'], r['d53'], 0)
                    self._vis_hit_regions[idx] = (x-10, y-10, x+10, y+10)
            elif sprite_rgba is None:
                # 几何形状绘制
                dr = ImageDraw.Draw(composite)
                if tval == 10:
                    bx, by = r['d18'], r['d19']
                    bw = r['d20'] if r['d20'] > 0 else 40; bh = r['d21'] if r['d21'] > 0 else 40
                    dr.rectangle([bx, by, bx+bw, by+bh], outline=color, width=2)
                    self._vis_hit_regions[idx] = (bx, by, bx+bw, by+bh)
                elif tval == 5:
                    s = 12
                    dr.polygon([x, y-s, x+s, y, x, y+s, x-s, y], outline=color)
                    self._vis_hit_regions[idx] = (x-s, y-s, x+s, y+s)
                else:
                    s = 10
                    dr.rectangle([x-s, y-s, x+s, y+s], outline=color, width=2)
                    self._vis_hit_regions[idx] = (x-s, y-s, x+s, y+s)

            # 标签
            label = f"#{idx}"
            if tval == 10: label = f"T{idx}"
            elif tval == 5: label = f"P{idx}"
            elif tval == 200: label = f"N{idx}"
            # 脚本类型图标 (基于逆向 sub_409618/sub_408E5C)
            cur_a = r.get('d33', 0); cur_b = r.get('d34', 0)
            script_icon = ""
            if cur_a > 0: script_icon += "⚡"  # 自动(Tick)脚本
            if cur_b > 0: script_icon += "👆"  # 触发(交互)脚本
            if script_icon: label = f"{label} {script_icon}"
            dr = ImageDraw.Draw(composite)
            dr.text((x, y-16), label, fill=color)

        # 选中实体高亮覆盖
        if self._vis_selected is not None and self._vis_selected in self._vis_hit_regions:
            x1, y1, x2, y2 = self._vis_hit_regions[self._vis_selected]
            dr = ImageDraw.Draw(composite)
            dr.rectangle([x1-2, y1-2, x2+2, y2+2], outline=(255, 215, 0), width=2)

        # 转 PhotoImage 显示
        self._vis_bg_image = ImageTk.PhotoImage(composite)
        self._vis_canvas.create_image(0, 0, anchor='nw', image=self._vis_bg_image)

    def _vis_redraw(self):
        """重新绘制当前场景"""
        sid = self._vis_scene_id.get()
        self._vis_canvas.delete('all')
        self._vis_hit_regions = {}
        if not self.records: return
        ents = [r for r in self.records if has_data(r) and r['d1'] == sid]
        if not ents: return
        ents.sort(key=lambda r: r['d19'] if r['d0'] == 10 else r['d11'])
        xs = [r['d10'] for r in ents]; ys = [r['d11'] for r in ents]
        w = max(MAX_MAP_W, max(xs)-min(xs)+250); h = max(MAX_MAP_H, max(ys)-min(ys)+250)
        self._vis_render_scene(ents, w, h)

    def _vis_canvas_click(self, event):
        """点击画布：选中实体 (PIL 合成 → 矩形命中)"""
        cx = int(self._vis_canvas.canvasx(event.x))
        cy = int(self._vis_canvas.canvasy(event.y))
        self._vis_selected = None; self._vis_drag = None
        found = None
        for idx, (x1, y1, x2, y2) in self._vis_hit_regions.items():
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                found = idx
        if found is not None:
            # 切换到不同实体时停止选中动画
            if self._vis_sel_anim_active and self._vis_selected != found:
                self._vis_stop_sel_anim()
            self._vis_selected = found
            rec = self.records[found]
            tname = ENTITY_TYPES.get(rec['d0'], '?')
            pos_x = rec['d18'] if rec['d0'] == 10 else rec['d10']
            pos_y = rec['d19'] if rec['d0'] == 10 else rec['d11']
            # 保存拖动前位置(用于 Ctrl+Z 撤销)
            self._undo_pos = (found, pos_x, pos_y)
            if self._vis_edit_mode.get():
                self._vis_info.config(text=f"选中: #{found} [{tname}] 坐标({pos_x},{pos_y}) — 拖拽可移动")
                self._vis_drag = (found, cx, cy, pos_x, pos_y)
            else:
                self._vis_info.config(text=f"选中: #{found} [{tname}] 坐标({pos_x},{pos_y}) — 拖动已锁定")
            self._sync_entity_list_select(found)
            self._current_param_idx = found
            self._show_record(rec)
        else:
            self._vis_info.config(text="")
        self._vis_redraw()

    def _vis_canvas_drag(self, event):
        """拖拽实体移动"""
        if self._vis_drag is None: return
        if not self._vis_edit_mode.get(): return  # 编辑模式关闭时禁止拖动
        eidx, sx, sy, ox, oy = self._vis_drag
        cx = int(self._vis_canvas.canvasx(event.x))
        cy = int(self._vis_canvas.canvasy(event.y))
        dx, dy = cx - sx, cy - sy
        new_x, new_y = ox + dx, oy + dy
        rec = self.records[eidx]
        if rec['d0'] == 10:
            rec['d18'], rec['d19'] = new_x, new_y
            rec['d10'], rec['d11'] = new_x, new_y
        else:
            rec['d10'], rec['d11'] = new_x, new_y
        self._dirty = True
        self._vis_info.config(text=f"移动: #{eidx} → ({new_x},{new_y})")
        self._vis_redraw()

    def _vis_canvas_release(self, event):
        """释放拖拽 — 更新拖拽锚点"""
        if self._vis_drag:
            eidx = self._vis_drag[0]
            rec = self.records[eidx]
            cx = int(self._vis_canvas.canvasx(event.x))
            cy = int(self._vis_canvas.canvasy(event.y))
            px = rec['d18'] if rec['d0'] == 10 else rec['d10']
            py = rec['d19'] if rec['d0'] == 10 else rec['d11']
            self._vis_drag = (eidx, cx, cy, px, py)
            if hasattr(self, '_current_param_idx') and self._current_param_idx == eidx:
                self._show_record(rec)

    # ---- 编辑模式与撤销 ----
    def _on_edit_mode_change(self):
        """编辑开关切换: 控制光标样式和拖动权限"""
        if self._vis_edit_mode.get():
            self._vis_canvas.config(cursor='crosshair')
            self._vis_info.config(text="编辑模式已开启 — 可拖动实体")
        else:
            self._vis_canvas.config(cursor='arrow')
            self._vis_drag = None  # 取消进行中的拖动
            self._vis_info.config(text="编辑模式已锁定 — 拖动已禁用 (勾选工具栏「允许拖动」可解锁)")

    def _vis_canvas_undo(self, event=None):
        """Ctrl+Z 撤销: 恢复到本次拖动前的位置"""
        if self._undo_pos is None: return
        eidx, old_x, old_y = self._undo_pos
        rec = self.records[eidx]
        if rec['d0'] == 10:
            rec['d18'], rec['d19'] = old_x, old_y
            rec['d10'], rec['d11'] = old_x, old_y
        else:
            rec['d10'], rec['d11'] = old_x, old_y
        self._dirty = True
        self._vis_info.config(text=f"已撤销: #{eidx} → ({old_x},{old_y})")
        self._vis_redraw()
        self._undo_pos = None
        if hasattr(self, '_current_param_idx') and self._current_param_idx == eidx:
            self._show_record(rec)

    # ---- 动画播放控制 ----
    def _vis_toggle_anim(self):
        """切换动画播放/暂停"""
        if self._vis_anim_playing:
            self._vis_stop_anim()
            self._vis_anim_playing = False
            if self._vis_play_btn: self._vis_play_btn.config(text="▶")
        else:
            self._vis_anim_playing = True
            self._vis_start_anim()
            if self._vis_play_btn: self._vis_play_btn.config(text="⏸")

    # ---- 选中实体动画 ----
    def _vis_toggle_sel_anim(self):
        """切换当前选中实体的独立动画播放"""
        if self._vis_selected is None:
            self._vis_info.config(text="请先选中一个实体再播放动画")
            return
        if self._vis_anim_playing:
            self._vis_info.config(text="全局动画已开启，无需单独播放")
            return

        idx = self._vis_selected
        rec = self.records[idx]
        mode = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')
        # 检查该实体是否支持动画
        tval = rec['d0']
        can_animate = False
        if mode in ('auto', 'ani'):
            if tval in (200, 20, 110) and rec['d64'] > 0 and self._ani_jvg:
                can_animate = True
        if not can_animate:
            tname = ENTITY_TYPES.get(tval, '?')
            self._vis_info.config(text=f"实体 #{idx} [{tname}] 不支持动画 (需 Ani.JVG 且 d64>0)")
            return

        if self._vis_sel_anim_active:
            self._vis_stop_sel_anim()
        else:
            self._vis_start_sel_anim(idx)

    def _vis_start_sel_anim(self, idx):
        """启动选中实体动画循环 (~200ms/帧)"""
        self._vis_sel_anim_active = True
        if self._vis_sel_anim_btn: self._vis_sel_anim_btn.config(text="⏸")
        # 初始化帧计数器
        self._vis_anim_frame[idx] = 0

        def _tick():
            if not self._vis_sel_anim_active:
                return
            m = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')
            if m in ('wire', 'cha'):
                self._vis_stop_sel_anim()
                return
            if idx in self._vis_anim_frame:
                self._vis_anim_frame[idx] += 1
            self._vis_redraw()
            self._vis_sel_anim_timer = self.root.after(200, _tick)

        self._vis_sel_anim_timer = self.root.after(200, _tick)
        tname = ENTITY_TYPES.get(self.records[idx]['d0'], '?')
        self._vis_info.config(text=f"选中动画: #{idx} [{tname}] 播放中")

    def _vis_stop_sel_anim(self):
        """停止选中实体动画"""
        self._vis_sel_anim_active = False
        if self._vis_sel_anim_timer:
            self.root.after_cancel(self._vis_sel_anim_timer)
            self._vis_sel_anim_timer = None
        if self._vis_sel_anim_btn: self._vis_sel_anim_btn.config(text="▷")

    def _on_display_mode_change(self):
        """显示模式切换: 停止动画, 重置播放状态, 重载场景"""
        self._vis_stop_anim()
        self._vis_stop_sel_anim()
        self._vis_anim_playing = False
        if self._vis_play_btn: self._vis_play_btn.config(text="▶")
        self._vis_load_scene()

    # =========== 数据加载 ===========
    def _load_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d: return
        mat_p = os.path.join(d, "TKMat.Dat"); tkt_p = os.path.join(d, "TKT.dat")
        if not os.path.exists(mat_p):
            messagebox.showwarning("文件缺失", f"未找到 TKMat.Dat\n{d}"); return
        self.dat_path = mat_p
        self.tkt_path = tkt_p if os.path.exists(tkt_p) else None
        self._reload()

    def _reload(self):
        if not self.dat_path: return
        self.status_var.set("加载中…"); self.root.update()
        if self.tkt_path: self.tkt_scenes = load_tkt_scene_names(self.tkt_path)
        # 读取 SC.GRP section 数作为场景权威源
        self._sc_grp_section_count = 0
        d = os.path.dirname(self.dat_path)
        # 加载 TKDefUnit.dat — 用于 DefUnit 链查看
        self.defunit_recs = []; self.defunit_next = {}; self.defunit_entity = {}
        du_p = os.path.join(d, "TKDefUnit.Dat")
        if os.path.exists(du_p):
            try:
                with open(du_p, 'rb') as f: du_raw = f.read()
                for i in range(DEFUNIT_REC_COUNT):
                    off = i * DEFUNIT_REC_SIZE
                    fields = struct.unpack_from('<HHHHHHHH', du_raw, off)
                    f0, f1, f6 = fields[0], fields[1], fields[6]
                    if f0 == 0 and f1 == 0: continue
                    rec = {'index': i, 'f0': f0, 'f1': f1, 'f2': fields[2],
                           'f3': fields[3], 'f4': fields[4], 'f5': fields[5],
                           'f6': f6, 'f7': fields[7]}
                    self.defunit_recs.append(rec)
                    if f6 != 0: self.defunit_next[i] = f6
                    self.defunit_entity.setdefault(f1, []).append(i)
            except Exception: pass
        # 加载 TKD.dat — 用于脚本编辑
        self.tkd_defines = []; self.tkd_header = ''; self.tkd_define_map = {}
        tkd_p = os.path.join(d, "TKD.dat")
        if os.path.exists(tkd_p):
            try:
                tkd_text = load_tkd(tkd_p)
                self.tkd_defines, self.tkd_header = parse_defines(tkd_text)
                self.tkd_define_map = {d['define_id']: d for d in self.tkd_defines}
            except Exception: pass
        # 加载 TKT 全文 (用于脚本预览对话文本解析)
        self.tkt_all = load_tkt_all(self.tkt_path)
        # 加载 TKItem.dat → item_id → 物品名称映射 (用于类型110物品字段显示)
        self.item_names = {}
        item_p = os.path.join(d, "TKItem.dat")
        if os.path.exists(item_p) and self.tkt_scenes:
            try:
                with open(item_p, 'rb') as f: item_raw = f.read()
                item_dec = lzss_decompress(item_raw)
                ITEM_REC = 64; ITEM_CNT = 600
                for i in range(min(ITEM_CNT, len(item_dec) // ITEM_REC)):
                    off = i * ITEM_REC
                    fields = struct.unpack_from('<' + 'h' * 32, item_dec, off)
                    item_id = fields[0]       # offset 0: item_id
                    name_id = fields[2]       # offset 4: name_id (TKT text ID)
                    if item_id > 0 and name_id > 0:
                        name = self.tkt_all.get(name_id, '') or self.tkt_scenes.get(name_id, '')
                        if name:
                            self.item_names[item_id] = name.split('\n')[0].strip()
            except Exception: pass
        grp_path = os.path.join(d, "SC.GRP"); idx_path = os.path.join(d, "SC.IDX")
        if os.path.exists(grp_path) and os.path.exists(idx_path):
            try:
                idata = open(idx_path, 'rb').read()
                fsize = os.path.getsize(grp_path)
                offs = [struct.unpack_from('<I', idata, i)[0] for i in range(0, len(idata), 4)]
                if offs and offs[-1] == fsize:
                    self._sc_grp_section_count = len(offs) - 1
            except Exception:
                pass
        # 加载 Ani.JVG / Cha.JVG / Cur.JVG
        self._ani_jvg = _get_jvg(os.path.join(d, "Ani.JVG"))
        self._cha_jvg = _get_jvg(os.path.join(d, "Cha.JVG"))
        self._cur_jvg = _get_jvg(os.path.join(d, "Cur.JVG"))
        try:
            self.records = load_mat(self.dat_path); self._dirty = False
            nonempty = sum(1 for r in self.records if has_data(r))
            scenes = set(r['d1'] for r in self.records if has_data(r))
            self.status_var.set(
                f"{REC_COUNT}条 | 有效{nonempty} | TKMat场景{len(scenes)} | "
                f"SC.GRP {self._sc_grp_section_count}区段")
            sc = ["全部"]+[f"{s}: {scene_name(self.tkt_scenes,s)}" for s in sorted(scenes)]
            self.cb_scene['values'] = sc
        except Exception as e:
            messagebox.showerror("加载失败", str(e)); self.records = []
        self._update_path(); self._set_edit_enabled(True)
        self._apply_filter()
        # 填充场景列表并自动选中第一个有效场景
        self._vis_populate_scenes()
        children = self._vis_tree.get_children()
        if children:
            first = children[1] if len(children) > 1 else children[0]  # 跳过场景0(大地图,太卡)
            self._vis_tree.selection_set(first)
            sid = int(self._vis_tree.item(first, 'values')[0])
            self._vis_scene_id.set(sid)
            for v in self._vis_scene_combo['values']:
                if v.startswith(f"{sid}:"): self._vis_scene_combo.set(v); break
            self._vis_load_scene()
            self._sync_entity_filter_to_scene(sid)

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children(): self._set_ws(c, en)
    def _set_ws(self, w, en):
        try:
            if isinstance(w,(ttk.Entry,ttk.Spinbox)): w.configure(state='normal' if en else 'disabled')
            elif isinstance(w,ttk.Combobox): w.configure(state='readonly' if en else 'disabled')
            elif isinstance(w,(ttk.Checkbutton,ttk.Radiobutton,ttk.Button)): w.state(['!disabled'] if en else ['disabled'])
        except: pass
        for c in w.winfo_children(): self._set_ws(c, en)
    def _on_close(self):
        self._vis_stop_anim()
        dirty = self._dirty or self._script_dirty
        if dirty and not messagebox.askyesno("未保存","有未保存的修改 (含脚本), 确定退出?"): return
        self.root.destroy()
    def _update_path(self):
        G,R="#228B22","#CC3333"
        if not self.dat_path: self.lbl_path.config(text="(未加载)",foreground=R)
        elif not os.path.exists(self.dat_path): self.lbl_path.config(text=f"(不存在){self.dat_path}",foreground=R)
        else: self.lbl_path.config(text=self.dat_path,foreground=G)
        for lbl, jvg, name in [(self.lbl_cha, self._cha_jvg, "Cha.JVG"),
                                (self.lbl_ani, self._ani_jvg, "Ani.JVG"),
                                (self.lbl_cur, self._cur_jvg, "Cur.JVG")]:
            if jvg is not None:
                lbl.config(text=f"{name}✓", foreground=G)
            elif self.dat_path and os.path.exists(self.dat_path):
                lbl.config(text=f"{name}✗", foreground=R)
            else:
                lbl.config(text=name, foreground="gray")
        if self._sc_grp_section_count > 0:
            self.lbl_sc.config(text=f"SC.GRP✓({self._sc_grp_section_count})", foreground=G)
        elif self.dat_path and os.path.exists(self.dat_path):
            self.lbl_sc.config(text="SC.GRP✗", foreground=R)
        else:
            self.lbl_sc.config(text="SC.GRP", foreground="gray")

    # =========== 筛选/列表 (参数模式) ===========
    def _apply_filter(self):
        q = self.search_var.get().strip().lower(); ftype = self.filter_type.get()
        fscene = self.filter_scene.get(); self.filtered_indices = []
        for rec in self.records:
            if not self.show_empty.get() and is_empty(rec): continue
            if ftype and ftype!="全部" and rec['d0']!=int(ftype.split('-')[0]): continue
            if fscene and fscene!="全部" and rec['d1']!=int(fscene.split(':')[0]): continue
            if q:
                parts=[str(rec['index']),str(rec['d0']),str(rec['d1']),str(rec['d10']),str(rec['d11']),
                       scene_name(self.tkt_scenes,rec['d1']),ENTITY_TYPES.get(rec['d0'],'')]
                if q not in ' '.join(parts).lower(): continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
    def _clear_filter(self):
        self.search_var.set(""); self.filter_type.set("全部"); self.filter_scene.set("全部"); self._apply_filter()
    def _refresh_table(self):
        sel_idx=None; sel=self.tree.selection()
        if sel:
            vals=self.tree.item(sel[0],'values')
            if vals: sel_idx=vals[0]
        self.tree.delete(*self.tree.get_children())
        for idx in self.filtered_indices:
            rec=self.records[idx]; tval=rec['d0']; sname=scene_name(self.tkt_scenes,rec['d1'])
            script_lbl, tick_lbl = get_script_info(rec)
            vals=(str(idx),f"{tval}-{ENTITY_TYPES.get(tval,'未知')}",sname,str(rec['d10']),str(rec['d11']),script_lbl,tick_lbl)
            tag=f'type{tval}' if tval in TYPE_COLORS else ''
            self.tree.insert('','end',values=vals,tags=(tag,))
        if sel_idx:
            for item in self.tree.get_children():
                if self.tree.item(item,'values')[0]==sel_idx: self.tree.selection_set(item); self.tree.see(item); break
        if not self.tree.selection():
            self._current_param_idx = None
            self.lbl_title.config(text="未选中")
            self._clear_form()
    def _sort_by(self,col):
        ci={'index':0,'type':1,'scene':2,'x':3,'y':4,'script':5,'tick':6}.get(col,0)
        items=[(self.tree.item(item,'values'),item) for item in self.tree.get_children()]
        try: items.sort(key=lambda x:(int(x[0][ci]) if x[0][ci].lstrip('-').isdigit() else 0) if ci in(0,3,4) else x[0][ci])
        except: pass
        for i,(_,item) in enumerate(items): self.tree.move(item,'',i)

    # =========== 编辑 (参数模式) ===========
    def _on_select(self,event):
        sel=self.tree.selection()
        if not sel: self.lbl_title.config(text="未选中"); self._clear_form(); return
        idx=int(self.tree.item(sel[0],'values')[0])
        self._current_param_idx = idx
        rec = self.records[idx]
        self._show_record(rec)
        # 同步高亮中间地图：若实体在当前场景中则高亮并重绘
        if rec['d1'] == self._vis_scene_id.get():
            self._vis_selected = idx
            self._vis_redraw()
            tname = ENTITY_TYPES.get(rec['d0'], '?')
            pos_x = rec['d18'] if rec['d0'] == 10 else rec['d10']
            pos_y = rec['d19'] if rec['d0'] == 10 else rec['d11']
            self._vis_info.config(text=f"选中: #{idx} [{tname}] 坐标({pos_x},{pos_y})")

    def _trace_defunit_chain(self, head_idx, max_n, cur_n):
        """追踪 DefUnit 链表, 返回节点字符串列表。
        sub_4066F0: 沿 f6 走 max 步, cur 标记当前位置"""
        if head_idx <= 0 or max_n <= 0:
            return []
        nodes = []; idx = head_idx; visited = set()
        for step in range(max_n):
            if idx in visited:
                nodes.append(f"(循环→{idx})"); break
            visited.add(idx)
            rec = next((r for r in self.defunit_recs if r['index'] == idx), None)
            if rec is None:
                nodes.append(f"#{idx}(空槽)"); break
            define_id = (rec['f1'] << 16) | rec['f0']
            mark = " ◀" if (step + 1) == cur_n else ""
            nodes.append(f"#{idx}→DEFINE {define_id}{mark}")
            idx = rec['f6']
            if idx == 0: break
        return nodes

    # =========== 脚本标签页 — 链列表 ===========

    def _clear_script_editor(self):
        """清空脚本编辑器"""
        self._save_editor_to_define()
        self.script_text.config(state='normal')
        self.script_text.delete('1.0', tk.END)
        self.script_text.config(state='disabled')
        self._current_edit_define_id = None
        self.script_info_lbl.config(text="(未选中 DEFINE)")

    def _refresh_chain_list(self):
        """刷新 DefUnit 链 Treeview (按子场景 A/B/C 分组, 标记链类型)"""
        self.chain_tree.delete(*self.chain_tree.get_children())
        if not self.records: return
        rec = self.records[self._current_param_idx] if hasattr(self, '_current_param_idx') and self._current_param_idx is not None and 0 <= self._current_param_idx < len(self.records) else None
        if not rec or not has_data(rec):
            self._clear_script_editor()
            self._update_sched_info(None)
            return
        entity_id = rec['index']
        # 链类型标签 (基于逆向分析 sub_409618/sub_408E5C 等)
        chain_labels = {
            'A': ('⚡ 自动(Tick)', 'A链=自动运行: 每Tick周期自动执行 (sub_409618: cur_A>0触发)'),
            'B': ('👆 触发(交互)', 'B链=触发执行: 玩家交互时执行 (sub_4081F8/408408/4084E0/408E5C)'),
            'C': ('✱ 其他', 'C链=保留: 可能由特定游戏事件触发'),
        }
        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0); mx = rec.get(f'd{mx_di}', 0)
            cur = rec.get(f'd{cur_di}', 0)
            if h <= 0 or mx <= 0: continue
            # 插入分组标题 — 显示链类型
            type_lbl, type_tip = chain_labels[sub_name]
            cur_str = f'当前={cur}' if cur > 0 else '未激活'
            head_iid = self.chain_tree.insert('', 'end', values=('', f'{sub_name}{type_lbl}', '', '', '', f'head=#{h} max={mx} {cur_str}'), tags=('group',))
            # 遍历链
            idx = h; visited_chain = set()
            for step in range(mx):
                if idx in visited_chain: break
                visited_chain.add(idx)
                du_rec = next((r for r in self.defunit_recs if r['index'] == idx), None)
                if du_rec is None: break
                define_id = (du_rec['f1'] << 16) | du_rec['f0']
                marks = []
                if (step + 1) == cur: marks.append('当前')
                if step == 0: marks.append('链头')
                self.chain_tree.insert('', 'end', values=(str(step + 1), f'  {sub_name}', str(idx), str(define_id), str(du_rec['f0']), ','.join(marks)),
                                       tags=('entry',))
                idx = du_rec['f6']
                if idx == 0: break
        self.chain_tree.tag_configure('group', font=FONT_B, foreground='#3366cc')
        # 更新信息标签
        total = len(self.chain_tree.get_children())
        self.chain_info_lbl.config(text=f"{entity_id=}, {total} 条节点")
        if total == 0:
            self._clear_script_editor()
            self.script_info_lbl.config(text="(无关联 DEFINE)")
        else:
            # 自动选中当前项 (cur=1 的链头)
            for item in self.chain_tree.get_children():
                tags = self.chain_tree.item(item, 'tags')
                if 'entry' in tags:
                    self.chain_tree.selection_set(item)
                    self.chain_tree.see(item)
                    self._on_chain_select()
                    break
        # 更新脚本调度信息面板
        self._update_sched_info(rec)

    def _on_chain_select(self, event=None):
        """选中链列表项 → 保存当前编辑 → 加载新 DEFINE"""
        sel = self.chain_tree.selection()
        if not sel: return
        tags = self.chain_tree.item(sel[0], 'tags')
        if 'group' in tags: return  # 分组标题不可选
        vals = self.chain_tree.item(sel[0], 'values')
        if not vals or not vals[3].isdigit(): return
        define_id = int(vals[3])
        du_idx = int(vals[2]) if vals[2].isdigit() else 0
        # 保存当前编辑
        self._save_editor_to_define()
        # 加载新 DEFINE
        self._load_define_to_editor(define_id)
        self.chain_info_lbl.config(text=f"DefUnit #{du_idx} → DEFINE {define_id}")

    # =========== 脚本调度信息 (基于逆向) ===========

    def _update_sched_info(self, rec):
        """更新脚本调度信息面板。基于逆向分析:
        sub_409618: 主Tick循环, 检查enabled/d3定时器/d4Tick周期/d33自动脚本
        sub_408E5C: 玩家点击交互, 检查pickable/d34触发脚本
        sub_4081F8: type=5/10接近触发
        sub_408408: type=15条件触发
        sub_4084E0: type=16门/建筑交互"""
        if rec is None or is_empty(rec):
            for key in self._sched_labels:
                self._sched_labels[key].config(text="", foreground='black')
            return
        flags = rec.get('d2', 0)
        tval = rec.get('d0', 0)
        # 启用
        en = (flags & 1) != 0
        self._sched_labels['enabled'].config(
            text="✓ 已启用" if en else "✗ 未启用",
            foreground='#228B22' if en else '#CC3333')
        # 可交互
        pk = (flags & 4) != 0
        self._sched_labels['pickable'].config(
            text="✓ 可交互" if pk else "✗ 不可交互",
            foreground='#228B22' if pk else '#999')
        # Tick周期
        tick = rec.get('d4', 0)
        if tick > 0:
            self._sched_labels['tick'].config(text=f"{tick} (越大越慢)", foreground='#333')
        else:
            self._sched_labels['tick'].config(text="0 (无Tick)", foreground='#999')
        # 定时器
        timer = rec.get('d3', 0)
        if timer > 0:
            self._sched_labels['timer'].config(text=f"{timer} (暂停中)", foreground='#CC6600')
        else:
            self._sched_labels['timer'].config(text="0 (正常运行)", foreground='#333')
        # A链
        cur_a = rec.get('d33', 0); head_a = rec.get('d39', 0); max_a = rec.get('d30', 0)
        if head_a > 0 and max_a > 0:
            a_status = "⚡ 自动执行中" if cur_a > 0 else "已定义(未激活)"
            self._sched_labels['chain_a'].config(
                text=f"✓ {a_status} [head=#{head_a},max={max_a},cur={cur_a}]",
                foreground='#228B22' if cur_a > 0 else '#666')
        else:
            self._sched_labels['chain_a'].config(text="— 无", foreground='#999')
        # B链
        cur_b = rec.get('d34', 0); head_b = rec.get('d40', 0); max_b = rec.get('d31', 0)
        if head_b > 0 and max_b > 0:
            b_status = "👆 交互触发" if cur_b > 0 else "已定义(未激活)"
            self._sched_labels['chain_b'].config(
                text=f"✓ {b_status} [head=#{head_b},max={max_b},cur={cur_b}]",
                foreground='#2196F3' if cur_b > 0 else '#666')
        else:
            self._sched_labels['chain_b'].config(text="— 无", foreground='#999')
        # C链
        cur_c = rec.get('d35', 0); head_c = rec.get('d41', 0); max_c = rec.get('d32', 0)
        if head_c > 0 and max_c > 0:
            c_status = "✱ 活跃" if cur_c > 0 else "已定义(未激活)"
            self._sched_labels['chain_c'].config(
                text=f"✓ {c_status} [head=#{head_c},max={max_c},cur={cur_c}]",
                foreground='#9C27B0' if cur_c > 0 else '#666')
        else:
            self._sched_labels['chain_c'].config(text="— 无", foreground='#999')
        # 触发方式 (基于实体类型和逆向分析)
        trigger_map = {
            5:  "接近触发 — 玩家走到传送点上 (sub_4081F8)",
            10: "接近触发 — 玩家踩上地形块 (sub_4081F8)",
            15: "接近+条件 — 需d34!=0且方向匹配 (sub_408408)",
            16: "接近+道具 — 可能有道具检查 (sub_4084E0)",
            20: "点击对话 — 点击NPC/事件对象 (sub_408E5C)",
            110: "点击机关 — 点击触发特殊效果 (sub_408B30)",
            200: "点击对话 — 点击NPC交互 (sub_408E5C)",
        }
        trigger = trigger_map.get(tval, "未知")
        auto_note = ""
        if cur_a > 0:
            auto_note = " + A链自动(Tick)"
        self._sched_labels['trigger'].config(
            text=f"{trigger}{auto_note}",
            foreground='#333')

    # =========== 脚本标签页 — 编辑器 ===========

    def _load_define_to_editor(self, define_id):
        """加载 DEFINE 块脚本到 Text 编辑器"""
        self._current_edit_define_id = define_id
        self.script_text.config(state='normal')
        self.script_text.delete('1.0', tk.END)
        d = self.tkd_define_map.get(define_id)
        if d:
            self.script_text.insert('1.0', '\n'.join(d.get('body_lines', [])))
            comment = d.get('comment', '')
            self.script_info_lbl.config(text=f"DEFINE {define_id}" + (f" — {comment}" if comment else ""))
        else:
            # 新 DEFINE (内存中尚未持久化)
            self.script_text.insert('1.0', '{\nEnd(0)\n}; end\n')
            self.script_info_lbl.config(text=f"DEFINE {define_id} (新建)")
        self._apply_syntax_highlight()
        self.script_text.edit_reset()
        self._script_dirty = False

    def _save_editor_to_define(self):
        """将 Text 编辑器内容写回 self.tkd_defines"""
        if self._current_edit_define_id is None: return
        text = self.script_text.get('1.0', 'end-1c')
        d = self.tkd_define_map.get(self._current_edit_define_id)
        if d is None:
            # 新建 DEFINE
            d = {'define_id': self._current_edit_define_id, 'comment': '', 'prefix_lines': [],
                 'body_lines': [], 'line_start': -1, 'line_end': -1,
                 'header_line': f'DEFINE {self._current_edit_define_id}'}
            # 提取注释 (body 第一行可能是 };comment end)
            for line in text.split('\n'):
                s = line.strip()
                if s.startswith('};'):
                    d['comment'] = s[2:].replace(' end', '').strip()
                    break
            self.tkd_defines.append(d)
            self.tkd_define_map[self._current_edit_define_id] = d
        # 更新 body_lines
        d['body_lines'] = text.split('\n')
        # 更新注释
        for line in reversed(d['body_lines']):
            s = line.strip()
            if s.startswith('};'):
                d['comment'] = s[2:].replace(' end', '').strip()
                break

    def _on_script_edit(self, event=None):
        """脚本编辑事件 — 标记脏状态, 触发语法高亮"""
        self._script_dirty = True
        self._apply_syntax_highlight()

    def _apply_syntax_highlight(self, event=None):
        """语法高亮 (来自 script_editor.py)"""
        for tag in ('keyword', 'comment', 'number', 'command', 'block'):
            self.script_text.tag_remove(tag, '1.0', tk.END)
        content = self.script_text.get('1.0', tk.END)
        lines = content.split('\n')
        for i, line in enumerate(lines):
            ln = i + 1
            stripped = line.strip()
            comment_start = line.find('//')
            if comment_start >= 0:
                self.script_text.tag_add('comment', f"{ln}.{comment_start}", f"{ln}.{len(line)}")
            if stripped.startswith('{') or stripped.startswith('}'):
                self.script_text.tag_add('block', f"{ln}.0", f"{ln}.{len(line)}")
            if stripped.startswith('DEFINE'):
                self.script_text.tag_add('keyword', f"{ln}.0", f"{ln}.{len(line)}")
            for cmd in SCRIPT_COMMANDS:
                idx = 0
                while True:
                    pos = line.find(cmd + '(', idx)
                    if pos < 0: break
                    self.script_text.tag_add('command', f"{ln}.{pos}", f"{ln}.{pos + len(cmd)}")
                    idx = pos + 1
            import re
            for m in re.finditer(r'-?\d+', line):
                if comment_start >= 0 and m.start() >= comment_start: continue
                self.script_text.tag_add('number', f"{ln}.{m.start()}", f"{ln}.{m.end()}")

    # =========== 脚本预览 ===========
    def _parse_script_commands(self, body_lines):
        """解析 DEFINE body_lines 中的脚本命令, 返回 [(cmd_name, args_list, line_text, line_idx), ...]"""
        import re
        commands = []
        for i, line in enumerate(body_lines):
            stripped = line.strip()
            # 跳过空行、注释、花括号
            if not stripped or stripped.startswith('//') or stripped.startswith('{') or stripped.startswith('}'):
                continue
            # 跳过 DEFINE 头部行 (预防 body_lines 包含 header 的情况)
            if stripped.startswith('DEFINE'):
                continue
            # 匹配 CommandName(args) — 支持行尾注释
            m = re.match(r'([A-Za-z_]\w*)\s*\((.*)\)', stripped)
            if m:
                cmd_name = m.group(1)
                args_str = m.group(2).strip()
                # 按逗号分割参数, 各参数可包含空格 (去除首尾空格)
                args = [a.strip() for a in args_str.split(',') if a.strip()] if args_str else []
                commands.append((cmd_name, args, stripped, i))
            elif stripped and not stripped.startswith('//'):
                # 无括号的裸命令名 (如单独一行的 End 或 Yield)
                m2 = re.match(r'([A-Za-z_]\w+)\s*$', stripped)
                if m2 and m2.group(1) in SCRIPT_CMD_DESC:
                    commands.append((m2.group(1), [], stripped, i))
        return commands

    def _format_cmd_desc(self, cmd_name, args):
        """将命令和参数格式化为人类可读的描述"""
        # 尝试精确描述 (传递 item_names 供 GetItem 等命令解析物品名, 旧 lambda 用 TypeError 回退)
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
        # 回退: 通用格式
        args_str = ', '.join(args) if args else ''
        return f"{cmd_name}({args_str})"

    def _preview_script(self):
        """预览当前 DEFINE 脚本的执行流程"""
        # 保存当前编辑内容
        self._save_editor_to_define()
        if self._current_edit_define_id is None:
            messagebox.showinfo("预览", "请先选择一个 DEFINE 脚本块")
            return
        d = self.tkd_define_map.get(self._current_edit_define_id)
        if d is None:
            messagebox.showinfo("预览", "未找到当前 DEFINE 数据")
            return
        body_lines = d.get('body_lines', [])
        # 过滤花括号行
        cmd_lines = [l for l in body_lines if l.strip() and not l.strip().startswith('{') and not l.strip().startswith('}')]
        if not cmd_lines:
            messagebox.showinfo("预览", "当前 DEFINE 脚本为空")
            return

        # 解析命令
        commands = self._parse_script_commands(body_lines)
        if not commands:
            messagebox.showinfo("预览", "未解析到有效命令")
            return
        self._preview_cmds = commands
        self._preview_step = 0

        # 创建预览窗口
        if self._preview_win and self._preview_win.winfo_exists():
            self._preview_win.destroy()
        win = tk.Toplevel(self.root)
        win.title(f"脚本预览 — DEFINE {self._current_edit_define_id}")
        win.transient(self.root)
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico): win.iconbitmap(default=ico)
        # 居中: 先隐藏, 计算, 再显示
        win.withdraw()
        win.geometry("780x680")
        win.update_idletasks()
        rw = self.root.winfo_width(); rh = self.root.winfo_height()
        rx = self.root.winfo_rootx(); ry = self.root.winfo_rooty()
        w = win.winfo_width(); h = win.winfo_height()
        x = rx + (rw - w) // 2; y = ry + (rh - h) // 2
        win.geometry(f"+{x}+{y}")
        win.deiconify()

        # 顶部信息
        info_f = ttk.Frame(win)
        info_f.pack(fill=tk.X, padx=8, pady=(8,4))
        comment = d.get('comment', '')
        info_text = f"DEFINE {self._current_edit_define_id}"
        if comment: info_text += f"  —  {comment}"
        info_text += f"  |  {len(commands)} 条命令"
        ttk.Label(info_f, text=info_text, font=FONT_B).pack(side=tk.LEFT)
        self._preview_info_lbl = ttk.Label(info_f, text="", font=FONT_S, foreground='#666')
        self._preview_info_lbl.pack(side=tk.RIGHT)

        # 命令列表 + 详情面板 (PanedWindow 可拖动分割)
        paned = ttk.PanedWindow(win, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # 命令列表
        list_f = ttk.Frame(paned)
        paned.add(list_f, weight=3)

        cols_pv = ('step', 'cmd', 'desc')
        self._preview_tree = ttk.Treeview(list_f, columns=cols_pv, show='headings',
                                           selectmode='browse', height=16)
        self._preview_tree.heading('step', text='#')
        self._preview_tree.heading('cmd', text='命令')
        self._preview_tree.heading('desc', text='描述')
        self._preview_tree.column('step', width=35, anchor='center', minwidth=30)
        self._preview_tree.column('cmd', width=110, anchor='w', minwidth=80)
        self._preview_tree.column('desc', width=480, anchor='w', minwidth=200)

        pv_sb = ttk.Scrollbar(list_f, orient=tk.VERTICAL, command=self._preview_tree.yview)
        self._preview_tree.configure(yscrollcommand=pv_sb.set)
        self._preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pv_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 配置标签颜色
        self._preview_tree.tag_configure('talk', foreground='#7B30D0')
        self._preview_tree.tag_configure('flow', foreground='#0066CC')
        self._preview_tree.tag_configure('action', foreground='#333333')
        self._preview_tree.tag_configure('branch', foreground='#CC6600')
        self._preview_tree.tag_configure('end_tag', foreground='#CC0000')
        self._preview_tree.tag_configure('getitem', foreground='#FF0000')  # 获得道具行: 纯红色
        self._preview_tree.tag_configure('current', background='#FFEE88')

        # 填充命令列表
        for si, (cmd_name, args, line_text, line_idx) in enumerate(commands):
            desc = self._format_cmd_desc(cmd_name, args)
            # 选择标签颜色
            tag = 'action'
            if cmd_name in ('TalkB', 'TalkA', 'BlackTalk', 'ShowText', 'MenuChoice',
                           'SysTalk', 'SetTalkB', 'SetHint', 'DoTalkB', 'MenuTalk'):
                tag = 'talk'
            elif cmd_name in ('End', 'Yield', 'Jump', 'Else'):
                tag = 'flow'
            elif cmd_name in ('CheckFlag', 'CheckResult', 'CheckFlag61', 'CheckFlag62', 'CheckFlag63', 'Check65', 'Check66', 'CheckTeam', 'CheckMember'):
                tag = 'branch'
            elif cmd_name in ('GetItem',):
                tag = 'getitem'
            elif cmd_name == 'End':
                tag = 'end_tag'
            self._preview_tree.insert('', 'end', values=(str(si+1), cmd_name, desc), tags=(tag,))

        # 详情面板 (可拖动调整大小)
        detail_f = ttk.LabelFrame(paned, text="命令详情", padding=4)
        paned.add(detail_f, weight=1)
        self._preview_detail = tk.Text(detail_f, height=5, font=FONT_MONO, wrap=tk.WORD,
                                        bg='#313c52', fg='#CCCCCC', insertbackground='#CCCCCC')
        self._preview_detail.tag_configure('item_red', foreground='#FF4444', font=FONT_B)  # 亮红, 暗底更显眼
        # 预配置 FCOLOR 1-32 颜色标签 (TKT 文本颜色渲染, 游戏调色板专为暗底设计)
        for ci in range(1, 33):
            self._preview_detail.tag_configure(f'tkt_c{ci}', foreground=GAME_COLORS[ci])
        self._preview_detail._tkt_color_tags = set()  # 跟踪已配置的动态颜色标签
        detail_sb = ttk.Scrollbar(detail_f, orient=tk.VERTICAL, command=self._preview_detail.yview)
        self._preview_detail.configure(yscrollcommand=detail_sb.set)
        self._preview_detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 选中事件
        self._preview_tree.bind('<<TreeviewSelect>>', self._preview_on_select)

        # 选中第一步
        children = self._preview_tree.get_children()
        if children:
            self._preview_tree.selection_set(children[0])
            self._preview_tree.see(children[0])

        self._preview_win = win

    def _preview_on_select(self, event=None):
        """预览窗口: 选中命令 → 更新详情"""
        sel = self._preview_tree.selection()
        if not sel: return
        vals = self._preview_tree.item(sel[0], 'values')
        if not vals: return
        step = int(vals[0]) - 1
        self._preview_step = step
        if 0 <= step < len(self._preview_cmds):
            cmd_name, args, line_text, line_idx = self._preview_cmds[step]
            self._preview_detail.config(state='normal')
            self._preview_detail.delete('1.0', tk.END)
            # 基本信息
            self._preview_detail.insert(tk.END, f"原始: {line_text}\n")
            self._preview_detail.insert(tk.END, f"命令: {cmd_name}({', '.join(args)})\n")
            self._preview_detail.insert(tk.END, f"描述: {self._format_cmd_desc(cmd_name, args)}\n")
            # 对话命令: 解析 TKT 文本并用颜色渲染
            if cmd_name in ('TalkB', 'TalkA', 'SetTalkB', 'BlackTalk') and len(args) >= 2:
                text_idx = 0 if cmd_name == 'BlackTalk' else 1
                tkt_text = _tkt_text(self.tkt_all, args[text_idx], max_len=500)
                if tkt_text:
                    self._preview_detail.insert(tk.END, f"\n━━━ TKT 对话文本 (ID={args[text_idx]}) ━━━\n")
                    self._insert_colored_tkt(tkt_text)
            elif cmd_name in ('ShowText', 'MenuTalk', 'SysTalk') and args:
                tkt_text = _tkt_text(self.tkt_all, args[0], max_len=500)
                if tkt_text:
                    self._preview_detail.insert(tk.END, f"\n━━━ TKT 对话文本 (ID={args[0]}) ━━━\n")
                    self._insert_colored_tkt(tkt_text)
            # GetItem: 物品名称用红色显示
            if cmd_name == 'GetItem' and args and self.item_names:
                try:
                    item_id = int(args[0])
                    item_name = self.item_names.get(item_id, '')
                    if item_name:
                        self._preview_detail.insert(tk.END, f"\n━━━ 物品名称 (ID={args[0]}) ━━━\n")
                        self._preview_detail.insert(tk.END, item_name, 'item_red')
                except (ValueError, TypeError):
                    pass
            self._preview_detail.config(state='disabled')
            # 更新信息标签
            self._preview_info_lbl.config(text=f"步骤 {step+1}/{len(self._preview_cmds)}")

    def _insert_colored_tkt(self, text):
        """将含 <FCOLOR,n> 等标签的 TKT 文本按颜色分段插入 _preview_detail"""
        segments = parse_tkt_colored_segments(text)
        for seg_text, color in segments:
            tag = self._get_tkt_color_tag(color)
            self._preview_detail.insert(tk.END, seg_text, tag)

    def _get_tkt_color_tag(self, color_hex):
        """获取或创建 TKT 颜色标签。FCOLOR 1-32 用预配置的 tkt_cN, FCOLORD 动态创建"""
        # 检查是否为标准调色板颜色
        for ci in range(1, 33):
            if GAME_COLORS[ci] == color_hex:
                return f'tkt_c{ci}'
        # FCOLORD 动态颜色: 用颜色值作为 tag 名
        tag_name = f'tkt_d{color_hex.replace("#","")}'
        if tag_name not in getattr(self._preview_detail, '_tkt_color_tags', set()):
            self._preview_detail.tag_configure(tag_name, foreground=color_hex)
            self._preview_detail._tkt_color_tags.add(tag_name)
        return tag_name

    def _preview_next(self):
        """下一步"""
        if not self._preview_cmds: return
        self._preview_step = min(self._preview_step + 1, len(self._preview_cmds) - 1)
        self._preview_goto_step(self._preview_step)

    def _preview_prev(self):
        """上一步"""
        if not self._preview_cmds: return
        self._preview_step = max(self._preview_step - 1, 0)
        self._preview_goto_step(self._preview_step)

    def _preview_end(self):
        """跳到结束"""
        if not self._preview_cmds: return
        self._preview_step = len(self._preview_cmds) - 1
        self._preview_goto_step(self._preview_step)

    def _preview_reset(self):
        """重新开始"""
        self._preview_step = 0
        self._preview_goto_step(0)

    def _preview_auto_play(self):
        """自动播放脚本步骤"""
        if not self._preview_cmds: return
        self._preview_step = 0
        self._preview_goto_step(0)
        self._auto_play_tick()

    def _auto_play_tick(self):
        """自动播放定时器"""
        if self._preview_win is None or not self._preview_win.winfo_exists():
            return
        if self._preview_step >= len(self._preview_cmds) - 1:
            return
        self._preview_step += 1
        self._preview_goto_step(self._preview_step)
        # 根据命令类型调整速度
        cmd_name = self._preview_cmds[self._preview_step][0]
        delay = 800 if cmd_name in ('TalkB', 'TalkA', 'BlackTalk', 'ShowText', 'MenuChoice') else 400
        self._preview_win.after(delay, self._auto_play_tick)

    def _preview_goto_step(self, step):
        """跳转到指定步骤"""
        if not self._preview_win or not self._preview_win.winfo_exists(): return
        children = self._preview_tree.get_children()
        if 0 <= step < len(children):
            self._preview_tree.selection_set(children[step])
            self._preview_tree.see(children[step])
            # 清除之前的高亮
            for item in children:
                self._preview_tree.item(item, tags=self._preview_tree.item(item, 'tags')[:1] if self._preview_tree.item(item, 'tags') else ())
            # 高亮当前步骤 - 重新设置tags保留原来的颜色标签
            for i, item in enumerate(children):
                old_tags = self._preview_tree.item(item, 'tags')
                base_tag = old_tags[0] if old_tags else 'action'
                new_tags = (base_tag,) if i != step else (base_tag, 'current')
                self._preview_tree.item(item, tags=new_tags)

    # =========== 链增删 ===========

    def _add_chain_entry(self, sub_scene):
        """新增 DefUnit 节点到指定子场景"""
        rec = self.records[self._current_param_idx] if hasattr(self, '_current_param_idx') and self._current_param_idx is not None and 0 <= self._current_param_idx < len(self.records) else None
        if not rec or not has_data(rec): return
        entity_id = rec['index']

        # 找空 DefUnit 槽
        empty_idx = None
        for r in self.defunit_recs:
            if r['f0'] == 0 and r['f1'] == 0:
                empty_idx = r['index']  # 实际上未加载空记录, 需要查全局
                break
        # 查全局 (遍历 5000 条)
        if empty_idx is None:
            for i in range(DEFUNIT_REC_COUNT):
                existing = next((r for r in self.defunit_recs if r['index'] == i), None)
                if existing is None:
                    empty_idx = i; break
        if empty_idx is None:
            messagebox.showinfo("无空槽", f"TKDefUnit.dat 所有 {DEFUNIT_REC_COUNT} 条记录均已占用"); return

        # 确定 DEFINE ID 和 block_id
        # 使用 entity 当前最大的 f0+1 (在同一组 256+ 内)
        existing_blocks = [r['f0'] for r in self.defunit_recs if r['f1'] == entity_id and r['f0'] >= 256]
        new_f0 = max(existing_blocks) + 1 if existing_blocks else 256
        if new_f0 > 266: new_f0 = max(existing_blocks) + 1  # 超出 256-266 范围则递增
        define_id = (entity_id << 16) | new_f0

        # 创建新 DefUnit 记录
        new_rec = {'index': empty_idx, 'f0': new_f0, 'f1': entity_id,
                   'f2': 0, 'f3': 0, 'f4': 0, 'f5': 0, 'f6': 0, 'f7': 0}
        self.defunit_recs.append(new_rec)
        self.defunit_entity.setdefault(entity_id, []).append(empty_idx)

        # 更新链: 找到链尾, 修改其 f6 指向新节点
        h_di, mx_di, cur_di = {'A': (39, 30, 33), 'B': (40, 31, 34), 'C': (41, 32, 35)}[sub_scene]
        head = rec.get(f'd{h_di}', 0); mx = rec.get(f'd{mx_di}', 0)
        if head == 0 or mx == 0:
            # 链之前为空
            rec[f'd{h_di}'] = empty_idx
            rec[f'd{mx_di}'] = 1
            rec[f'd{cur_di}'] = 1
        else:
            # 找到链尾
            idx = head; tail = head
            for _ in range(mx):
                du_r = next((r for r in self.defunit_recs if r['index'] == idx), None)
                if du_r is None or du_r['f6'] == 0: break
                idx = du_r['f6']; tail = idx
            # tail 是最后一个节点
            du_tail = next((r for r in self.defunit_recs if r['index'] == tail), None)
            if du_tail:
                du_tail['f6'] = empty_idx
            rec[f'd{mx_di}'] = mx + 1

        # 在 tkd_defines 中插入空模板 DEFINE
        if define_id not in self.tkd_define_map:
            d = {'define_id': define_id, 'comment': '', 'prefix_lines': [],
                 'body_lines': ['{', 'End(0)', '}; end'], 'line_start': -1, 'line_end': -1,
                 'header_line': f'DEFINE {define_id}'}
            self.tkd_defines.append(d)
            self.tkd_define_map[define_id] = d

        self._dirty = True; self._script_dirty = True
        # 同步被修改的字段到表单 StringVars，防止 _apply_edit 用旧值覆盖
        self._sync_form_dwords(rec, (h_di, mx_di, cur_di))
        self._refresh_chain_list()
        # 选中新节点
        for item in self.chain_tree.get_children():
            if self.chain_tree.item(item, 'values')[2] == str(empty_idx):
                self.chain_tree.selection_set(item)
                self.chain_tree.see(item)
                self._on_chain_select()
                break
        messagebox.showinfo("新增成功", f"DefUnit #{empty_idx} → DEFINE {define_id} ({sub_scene}场景)")

    def _delete_chain_entry(self):
        """删除选中的 DefUnit 节点"""
        sel = self.chain_tree.selection()
        if not sel: return
        vals = self.chain_tree.item(sel[0], 'values')
        tags = self.chain_tree.item(sel[0], 'tags')
        if 'group' in tags: return
        if not vals or not vals[2].isdigit(): return
        du_idx = int(vals[2])
        define_id = int(vals[3]) if vals[3].isdigit() else 0
        du_rec = next((r for r in self.defunit_recs if r['index'] == du_idx), None)
        if du_rec is None: return
        entity_id = du_rec['f1']

        if not messagebox.askyesno("确认删除", f"删除 DefUnit #{du_idx} → DEFINE {define_id}?\n此操作同时从 TKD.dat 删除对应 DEFINE 块。"):
            return

# 找到链中前驱节点
        rec = self.records[self._current_param_idx]
        _modified_dis = []  # 记录被修改的 dword 索引，用于同步表单
        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0); mx = rec.get(f'd{mx_di}', 0)
            if h <= 0: continue
            prev = None; idx = h
            for _ in range(mx):
                if idx == du_idx: break
                prev = idx
                du_r = next((r for r in self.defunit_recs if r['index'] == idx), None)
                idx = du_r['f6'] if du_r else 0
            if idx != du_idx: continue  # 不在这个链中
            # 更新前驱的 f6
            if prev is None:
                rec[f'd{h_di}'] = du_rec['f6']  # 删除的是头
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

        # 清零 DefUnit 记录
        du_rec['f0'] = du_rec['f1'] = du_rec['f6'] = 0
        self.defunit_recs = [r for r in self.defunit_recs if r['index'] != du_idx]
        if entity_id in self.defunit_entity and du_idx in self.defunit_entity[entity_id]:
            self.defunit_entity[entity_id].remove(du_idx)

        # 从 tkd_defines 删除
        if define_id in self.tkd_define_map:
            d = self.tkd_define_map.pop(define_id)
            if d in self.tkd_defines:
                self.tkd_defines.remove(d)

        self._dirty = True; self._script_dirty = True
        # 同步被修改的字段到表单 StringVars，防止 _apply_edit 用旧值覆盖
        if _modified_dis:
            self._sync_form_dwords(rec, _modified_dis)
        # 清空编辑器
        self.script_text.config(state='normal')
        self.script_text.delete('1.0', tk.END)
        self.script_text.config(state='disabled')
        self._current_edit_define_id = None
        self._refresh_chain_list()

    def _sync_form_dwords(self, rec, dis):
        """同步指定 dword 索引列表对应的表单字段值，防止 _apply_edit 用旧值覆盖程序性修改。
        同时更新命名键 (参数tab, 如 head_A) 和 raw 键 (全部tab, 如 raw_39)。"""
        self._sync_lock = True
        for di in dis:
            val = str(rec[f'd{di}'])
            # 更新命名键 (参数 tab): 从 ALL_EDIT_FIELDS/RUNTIME_FIELDS 查找 di→key 映射
            for fields in (ALL_EDIT_FIELDS, RUNTIME_FIELDS):
                for key, f_di, label, cmt in fields:
                    if f_di == di and key in self._edit_vars:
                        var = self._edit_vars[key]
                        if isinstance(var, tk.StringVar):
                            var.set(val)
                        break
            # 更新 raw 键 (全部 tab)
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                if key in self._edit_vars:
                    var = self._edit_vars[key]
                    if isinstance(var, tk.StringVar):
                        var.set(val)
                    break
        self._sync_lock = False

    def _show_record(self,rec):
        self._sync_lock=True
        idx=rec['index']; tval=rec['d0']; tname=ENTITY_TYPES.get(tval,f"未知({tval})")
        sname=scene_name(self.tkt_scenes,rec['d1'])
        self.lbl_title.config(text=f"实体 #{idx} [{tname}] {sname} ({rec['d10']},{rec['d11']})")
        for key,di,label,cmt in ALL_EDIT_FIELDS:
            val=rec[f'd{di}']
            BLEND_MODES = {0:"正常",1:"染色",2:"加法发光",3:"减法压暗",4:"亮度alpha",5:"水平翻转"}
            SHADOW_LABELS = {0:"无阴影",1:"小阴影(39×23)",2:"大阴影(65×33)"}
            if key=='type': self._edit_vars[key].set(f"{val}-{ENTITY_TYPES.get(val,'未知')}")
            elif key=='anim_set': self._edit_vars[key].set(f"{val}-{ANIM_SETS.get(val,'未知')}" if val in ANIM_SETS else f"{val}-未知")
            elif key=='blend_mode': self._edit_vars[key].set(f"{val}-{BLEND_MODES.get(val,'未知')}")
            elif key=='shadow_frame': self._edit_vars[key].set(f"{val}-{SHADOW_LABELS.get(val,'未知')}")
            else: self._edit_vars[key].set(str(val))
        for key,di,label,cmt in RUNTIME_FIELDS:
            if key in self._edit_vars: self._edit_vars[key].set(str(rec[f'd{di}']))
        # 填充"全部"标签页的字段 (raw_N 已知 + dN 未知)
        for di in range(96):
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                if key in self._edit_vars:
                    self._edit_vars[key].set(str(rec[f'd{di}']))
        if '_scene_label' in self._edit_vars: self._edit_vars['_scene_label'].config(text=sname)
        if '_hint_label' in self._edit_vars:
            hid=rec['d23']; self._edit_vars['_hint_label'].config(text="" if hid==0 else self.tkt_scenes.get(hid,""))
        # 物品名称标签: 组1/2/3 的物品ID下方显示 (通过TKItem.dat+TKT解析)
        for key, di in [('_item_g1_id_label', 53), ('_item_g2_id_label', 57), ('_item_g3_id_label', 61)]:
            if key in self._edit_vars:
                item_id = rec[f'd{di}']
                if item_id and item_id in self.item_names:
                    self._edit_vars[key].config(text=self.item_names[item_id])
                elif item_id:
                    self._edit_vars[key].config(text=f"物品 #{item_id}")
                else:
                    self._edit_vars[key].config(text="")
        flags=rec['d2']
        self._bit_enable.set((flags&1)!=0)
        self._bit_visible.set((flags&2)!=0)
        self._bit_pickable.set((flags&4)!=0)
        self._bit_hint.set((flags&8)!=0)
        self._bit_busy.set((flags&0x10)!=0)
        self._bit_resume.set((flags&0x20)!=0)
        self._bit_taken.set((flags&0x100)!=0)
        self._bit_animloop.set((flags&0x10000)!=0)
        self._bit_ev12.set((flags&0x1000)!=0)
        self._bit_ev13.set((flags&0x2000)!=0)
        self._bit_ev14.set((flags&0x4000)!=0)
        self._sync_lock=False
        # 根据实体类型动态更新参数tab + 全部tab标签
        self._update_param_labels(tval)
        self._update_all_tab_labels(tval)
        # 根据实体类型更新 flags 复选框行的可见性
        self._update_flags_visibility(tval)
        # 刷新脚本标签页链列表
        self._refresh_chain_list()

    def _clear_form(self):
        self._sync_lock=True
        for key,var in self._edit_vars.items():
            if isinstance(var,tk.StringVar): var.set("")
            elif isinstance(var,ttk.Combobox): var.set("")
        if '_scene_label' in self._edit_vars: self._edit_vars['_scene_label'].config(text="")
        if '_hint_label' in self._edit_vars: self._edit_vars['_hint_label'].config(text="")
        for key in ('_item_g1_id_label', '_item_g2_id_label', '_item_g3_id_label'):
            if key in self._edit_vars: self._edit_vars[key].config(text="")
        # 恢复参数tab标签为默认
        for di, (lbl, def_label, _) in self._param_labels.items():
            lbl.config(text=f"[{di:02d}] {def_label}", foreground='black')
        # 清空脚本标签页
        self._clear_script_editor()
        self.chain_tree.delete(*self.chain_tree.get_children())
        self.chain_info_lbl.config(text="")
        # 清空调度信息
        self._update_sched_info(None)
        for bv in (self._bit_enable,self._bit_visible,self._bit_pickable,
                    self._bit_hint,self._bit_busy,self._bit_resume,
                    self._bit_taken,self._bit_animloop,
                    self._bit_ev12,self._bit_ev13,self._bit_ev14):
            bv.set(False)
        # 隐藏 type20 专属 flags 行
        if hasattr(self, '_flags_row_frames') and len(self._flags_row_frames) >= 3:
            self._flags_row_frames[2].pack_forget()
        self._sync_lock=False

    def _read_form(self):
        vals = {}
        # 已覆盖的索引 (避免 "全部"tab 的 raw_/d_ 覆盖 "参数"tab 的值)
        covered = set()
        for fields in (ALL_EDIT_FIELDS, RUNTIME_FIELDS):
            for key, di, label, cmt in fields:
                if key not in self._edit_vars: continue
                var = self._edit_vars[key]
                if isinstance(var, ttk.Combobox):
                    try: v = int(var.get().split('-')[0])
                    except: return None
                else:
                    try: v = int(var.get())
                    except: return None
                vals[f'd{di}'] = v
                covered.add(di)
        # 填充 "全部"tab 的未知字段
        for di in range(96):
            if di in covered: continue
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                if key in self._edit_vars:
                    try: v = int(self._edit_vars[key].get())
                    except: return None
                    vals[f'd{di}'] = v
                    break
        return vals
    def _apply_edit(self):
        sel=self.tree.selection()
        if sel:
            idx=int(self.tree.item(sel[0],'values')[0])
        elif hasattr(self,'_current_param_idx') and self._current_param_idx is not None:
            idx=self._current_param_idx
        else:
            return
        new_vals=self._read_form()
        if new_vals is None: messagebox.showwarning("输入错误","字段值必须是整数"); return
        rec=self.records[idx]
        for key,val in new_vals.items(): rec[key]=val
        self._dirty=True; self._show_record(rec); self._apply_filter()
        self._sync_entity_list_select(idx)  # 刷新后重新选中
        # 如果可视化模式在看同一场景，重绘
        if rec['d1'] == self._vis_scene_id.get():
            self._vis_redraw()
    def _reset_edit(self):
        sel=self.tree.selection()
        if sel:
            idx=int(self.tree.item(sel[0],'values')[0])
        elif hasattr(self,'_current_param_idx') and self._current_param_idx is not None:
            idx=self._current_param_idx
        else:
            return
        self._show_record(self.records[idx])

    # =========== 新增/复制/清空 ===========
    def _new_record(self):
        if not self.records: return
        empty_idx=None
        for rec in self.records:
            if is_empty(rec): empty_idx=rec['index']; break
        if empty_idx is None: messagebox.showinfo("无空槽",f"所有{REC_COUNT}条记录均已占用"); return

        # 类型/场景选择对话框
        win=tk.Toplevel(self.root)
        win.title("新增实体")
        win.transient(self.root); win.grab_set(); win.resizable(False,False)

        ttk.Label(win,text="实体类型:").grid(row=0,column=0,padx=10,pady=(10,5),sticky='w')
        type_var=tk.StringVar()
        tc=[f"{k}-{v}" for k,v in sorted(ENTITY_TYPES.items()) if k!=0]
        cb_type=ttk.Combobox(win,textvariable=type_var,values=tc,state='readonly',width=22)
        cb_type.grid(row=0,column=1,padx=10,pady=(10,5),sticky='w')
        cb_type.current(6)  # 200-NPC/角色

        ttk.Label(win,text="场景 ID:").grid(row=1,column=0,padx=10,pady=5,sticky='w')
        scene_var=tk.IntVar(value=self._vis_scene_id.get())
        entry_scene=ttk.Entry(win,textvariable=scene_var,width=10)
        entry_scene.grid(row=1,column=1,padx=10,pady=5,sticky='w')
        lbl_sn=ttk.Label(win,text=scene_name(self.tkt_scenes,self._vis_scene_id.get()),
                          foreground='#666',font=FONT_S)
        lbl_sn.grid(row=1,column=2,padx=5,pady=5,sticky='w')
        def _on_sv(*_):
            try: lbl_sn.config(text=scene_name(self.tkt_scenes,scene_var.get()))
            except: pass
        scene_var.trace_add('write',_on_sv)

        confirmed=[False]
        def _ok(): confirmed[0]=True; win.destroy()
        win.protocol("WM_DELETE_WINDOW",win.destroy)
        bf=ttk.Frame(win); bf.grid(row=2,column=0,columnspan=3,pady=(5,10))
        ttk.Button(bf,text="确定",command=_ok).pack(side=tk.LEFT,padx=8)
        ttk.Button(bf,text="取消",command=win.destroy).pack(side=tk.LEFT,padx=8)
        win.wait_window()
        if not confirmed[0]: return

        # 创建实体
        try: sel_type=int(type_var.get().split('-')[0])
        except ValueError: return
        sel_scene=scene_var.get()
        rec=self.records[empty_idx]
        for di in range(DWORD_COUNT): rec[f'd{di}']=0
        rec['d0']=sel_type; rec['d1']=sel_scene
        rec['d2']=3       # 启用+可见
        rec['d8']=3 if sel_type==10 else 0  # 传送点光标动画=开门
        rec['d10']=400; rec['d11']=384  # 地图中心附近
        rec['d18']=400; rec['d19']=384  # 地形块用 bound_x/y 定位
        rec['d20']=40; rec['d21']=40    # 地形块默认大小

        self._dirty=True; self._apply_filter()
        for item in self.tree.get_children():
            if self.tree.item(item,'values')[0]==str(empty_idx):
                self.tree.selection_set(item); self.tree.see(item); self._show_record(rec); break

        # 若在当前场景则重绘
        if sel_scene==self._vis_scene_id.get():
            self._vis_redraw()
    def _copy_record(self):
        sel=self.tree.selection()
        if not sel: messagebox.showinfo("提示","请先选择记录"); return
        idx=int(self.tree.item(sel[0],'values')[0]); src=self.records[idx]
        empty_idx=None
        for rec in self.records:
            if is_empty(rec): empty_idx=rec['index']; break
        if empty_idx is None: messagebox.showinfo("无空槽",f"所有{REC_COUNT}条记录均已占用"); return
        dst=self.records[empty_idx]
        for di in range(DWORD_COUNT): dst[f'd{di}']=src[f'd{di}']
        dst['index']=empty_idx; self._dirty=True; self._apply_filter()
        for item in self.tree.get_children():
            if self.tree.item(item,'values')[0]==str(empty_idx): self.tree.selection_set(item); self.tree.see(item); self._show_record(dst); break
    def _clear_current(self):
        sel=self.tree.selection()
        if not sel: return
        idx=int(self.tree.item(sel[0],'values')[0])
        if not messagebox.askyesno("确认",f"清空实体 #{idx}? (type 设为 0)"): return
        for di in range(DWORD_COUNT): self.records[idx][f'd{di}']=0
        self._dirty=True; self._apply_filter(); self._show_record(self.records[idx])
    def _goto_empty(self):
        for rec in self.records:
            if is_empty(rec):
                self.search_var.set(""); self.filter_type.set("全部"); self.filter_scene.set("全部")
                self.show_empty.set(True); self._apply_filter()
                for item in self.tree.get_children():
                    if self.tree.item(item,'values')[0]==str(rec['index']): self.tree.selection_set(item); self.tree.see(item); self._show_record(rec); return
        messagebox.showinfo("提示","无空槽")

    # =========== 统计/导出 ===========
    def _show_stats(self):
        if not self.records: return
        from collections import Counter
        tc=Counter(); sc=Counter()
        for r in self.records:
            if has_data(r): tc[r['d0']]+=1; sc[r['d1']]+=1
        ne=sum(tc.values())
        msg=f"TKMat.Dat 统计\n{'─'*40}\n总槽位:{REC_COUNT} | 有效:{ne} | 空:{REC_COUNT-ne}\n场景数:{len(sc)}\n\n类型分布:\n"
        for tval in sorted(tc.keys()): msg+=f"  {tval}-{ENTITY_TYPES.get(tval,'?')}: {tc[tval]} ({tc[tval]/ne*100:.1f}%)\n"
        messagebox.showinfo("统计信息",msg)
    def _save(self):
        d = os.path.dirname(self.dat_path) if self.dat_path else None
        if not d: self._save_as(); return
        # 保存当前脚本编辑
        self._save_editor_to_define()
        # 确认对话框
        du_p = os.path.join(d, "TKDefUnit.Dat")
        tkd_p = os.path.join(d, "TKD.dat")
        files_msg = f"TKMat.Dat: {self.dat_path}\nTKDefUnit.Dat: {du_p}\nTKD.dat: {tkd_p}"
        if not messagebox.askyesno("确认保存 — 将写入以下 3 个文件", files_msg): return
        # 写入
        errors = []
        try: save_mat(self.dat_path, self.records)
        except Exception as e: errors.append(f"TKMat.Dat: {e}")
        try: save_defunit(du_p, self.defunit_recs)
        except Exception as e: errors.append(f"TKDefUnit.Dat: {e}")
        try:
            tkd_text = rebuild_text(self.tkd_defines, self.tkd_header)
            save_tkd(tkd_p, tkd_text)
        except Exception as e: errors.append(f"TKD.dat: {e}")
        if errors:
            messagebox.showerror("保存失败", '\n'.join(errors))
        else:
            self._dirty = False; self._script_dirty = False
            self.status_var.set(f"已保存 — 3 个文件")

    def _save_as(self):
        fp = filedialog.asksaveasfilename(title="另存 TKMat.Dat (同时保存 DefUnit/TKD 到同目录)",
            defaultextension=".Dat", filetypes=[("DAT 文件","*.Dat;*.dat"),("所有文件","*.*")])
        if not fp: return
        self.dat_path = fp
        self._save()
    def _export_csv(self):
        fp=filedialog.asksaveasfilename(title="导出 CSV",defaultextension=".csv",filetypes=[("CSV 文件","*.csv")])
        if not fp: return
        with open(fp,'w',encoding='utf-8-sig') as f:
            hd=['index']+[f'd{i}' for i in range(DWORD_COUNT)]+['type_name','scene_name']
            f.write(','.join(hd)+'\n')
            for rec in self.records:
                if not has_data(rec): continue
                row=[str(rec['index'])]+[str(rec[f'd{di}']) for di in range(DWORD_COUNT)]
                row+=[ENTITY_TYPES.get(rec['d0'],''),scene_name(self.tkt_scenes,rec['d1'])]
                f.write(','.join(row)+'\n')
        messagebox.showinfo("导出完成",f"已导出到 {fp}")
    def _show_field_ref(self):
        msg=("TKMat.Dat 实体表字段说明\n"+'─'*50+"\n\n加载: sub_412688:21\n结构: 6000条×384B(96×int32)\n\n已证实字段:\n"
             " [0]type [1]scene_id [2]flags [3]timer [4]tick\n [10][11]x/y [13]direction [18][19]bound\n"
             " [30-35]sub-scene [39-41]chain heads [42-43]PC [44]defunit_idx\n"
             " [50]条件角色 [51]访问掩码 [52]目标场景 [53]目标X [54]目标Y [56]目标朝向\n"
             "注意: [52-56]字段语义与实体类型相关 (type=10: 传送参数; type=200: 动画参数)")
        messagebox.showinfo("字段说明",msg)
    def _show_about(self):
        messagebox.showinfo("关于","TKMat.Dat 地图实体编辑器 v2.3\n\n"
            "模式: 参数 + 可视化 + 脚本编辑 + 脚本调度分析\n"
            "逆向依据: sub_412688, sub_405CBC, sub_4066F0, sub_40EBD4, sub_409618\n"
            "脚本调度: A链=自动(Tick) B链=触发(交互) C链=其他\n"
            "格式: TKMat 6000×384B + TKDefUnit 5000×16B + TKD脚本\n"
            "保存时一次性写入三个文件")

# ============================================================
def main():
    root=tk.Tk(); app=MatEditor(root); root.mainloop()

if __name__=='__main__': main()
