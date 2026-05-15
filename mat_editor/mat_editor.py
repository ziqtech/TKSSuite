#!/usr/bin/env python3
"""
TKMat.Dat 地图实体编辑器 v2.2 — 融合脚本编辑
=============================================================
逆向依据:
  sub_412688:21: TKMat.Dat → dword_51AF40 (2304000B, 6000×384B)
  sub_41103C:26: 场景文件 LZSS 解压覆盖实体表
  sub_405CBC: 实体类型分支渲染 (5/10/15/16/20/110/200)
  sub_4077E4: 朝向 [13], sub_407070: 坐标 [10][11]
  sub_40EBD4: 脚本PC[42]/DefUnit索引[44]/子场景[30-35]
  sub_4066F0: DefUnit链遍历 [39-41]
  sub_402E88: TKDefUnit.dat 加载 (5000×16B)

用法:
  python mat_editor.py
"""

import struct, os, sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

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

BASIC_FIELDS = [
    ("type",0,"实体类型","实体类型: 5=入口 10=地形 15=障碍 16=建筑 20=事件 110=机关 200=NPC"),
    ("scene_id",1,"场景ID","所属场景 (-1=全局)。TKT_ID = scene_id + 300"),
    ("flags",2,"标志位","位域。bit0=启用 bit1=可见 bit2=可交互 bit3=提示 bit4=忙碌 bit5=恢复 bit16=动画循环"),
    ("param",3,"扩展参数","扩展参数 (道具数量/金钱等)"),
    ("hint_id",23,"提示文本ID","鼠标悬停提示的TKT文本ID。传送点(type=10): 设为 300+目标场景ID 以显示目标场景名。sub_412390"),
    ("cursor_id",8,"光标动画","鼠标悬停光标动画编号。传送点(type=10)设为3显示开门动画。sub_411BA4/sub_412390"),
    ("blend_mode",24,"混合模式","sub_406864:39 — 主精灵渲染混合: 0=正常 1=染色 2=加法发光 3=减法压暗 4=亮度alpha 5=水平翻转"),
    ("blend_param",25,"混合参数","sub_406864:45/54 — d24=1时颜色索引, d24=2时加法缩放(0或>31=全加法)"),]
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
    ("dir_mode",53,"目标X/方向模式","传送点(type=10): 目标X坐标 sub_4081F8:30; NPC(type=200): 方向模式(0=静态/4=四方向/8=八方向) sub_4077E4"),
    ("target_y",54,"目标Y坐标","传送点(type=10): 目标Y坐标。sub_4081F8:30"),
    ("sub_model",64,"子模型ID","子角色动画模型ID"),("anim_speed",69,"动画速度","动画播放速度"),]
SCRIPT_FIELDS = [
    ("defunit_idx",44,"DefUnit索引","文件值=-1为正常; 运行时由 sub_4066F0 沿链遍历计算填入。sub_40EBD4:18 读取"),
    ("cur_define",28,"当前DEFINE","当前DEFINE脚本号"),
    ("max_A",30,"子场景最大A","子场景A DefUnit链长度"),
    ("max_B",31,"子场景最大B",""),("max_C",32,"子场景最大C",""),
    ("cur_A",33,"子场景当前A","当前在链中的位置(1-based)。SetNowDef可修改"),
    ("cur_B",34,"子场景当前B",""),("cur_C",35,"子场景当前C",""),
    ("head_A",39,"DefUnit链头A","子场景A的 TKDefUnit 链表头索引。sub_4066F0:39 从这开始遍历"),
    ("head_B",40,"DefUnit链头B",""),("head_C",41,"DefUnit链头C",""),]
INTERACT_FIELDS = [
    ("char_id",50,"条件角色","传送点: 所需角色ID在队伍中; NPC: 条件角色。sub_4081F8:15"),
    ("access_mask",51,"访问掩码","传送点: 访问标志位 (bitmask, 位=朝向-1); NPC: 图片ID。sub_4081F8:17"),
    ("target_scene",52,"目标场景","传送点(type=10): 目标场景ID; NPC: 动画句柄(运行时)。sub_4081F8:30"),]
RUNTIME_FIELDS = [
    ("tick",4,"tick","Tick周期(运行时)"),
    ("timer",12,"计时器",""),("frame_idx",14,"帧索引",""),
    ("frame_count",16,"总帧数",""),("frame_cur",17,"帧计数",""),
    ("script_PC",42,"脚本PC",""),("saved_PC",43,"保存PC",""),
    ("target_dir",56,"目标朝向","传送点(type=10): 目标朝向(1-8) sub_4081F8:30; NPC: 保存X(运行时)"),
    ("saved_y",57,"保存Y",""),
    ("alt_tele_x",60,"备选传送X","传送点(type=10): 备选传送后X坐标 sub_4081F8:31"),
    ("alt_tele_y",61,"备选传送Y","传送点(type=10): 备选传送后Y坐标 sub_4081F8:31"),
    ("sub_handle",65,"子句柄",""),("cur_frame",67,"当前帧",""),
    ("max_frame",68,"最大帧",""),("moving",70,"移动中",""),]
ALL_EDIT_FIELDS = BASIC_FIELDS+POS_FIELDS+ANIM_FIELDS+SCRIPT_FIELDS+INTERACT_FIELDS
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

SCRIPT_COMMANDS = [
    'SetSwitch', 'End', 'CheckFlag', 'Enable', 'Disable', 'SetWalk',
    'WaitWalk', 'SetPos', 'TalkB', 'TalkA', 'War', 'ChangeScene',
    'FadeIn', 'FadeOut', 'PlayerAct', 'SetCursor', 'SetWait',
    'SetNowDef', 'SetFlag', 'AddFlag', 'SetVar', 'Random',
    'SetBlock', 'SetTick', 'SetShadow', 'SetAni', 'SetCamera',
    'SetPlayer', 'SetEnabled', 'SetVisible', 'SetHint', 'SetScene',
    'SetChaPic', 'SetGlobal', 'WaitInput', 'Camera', 'Music',
    'SceneBGM', 'SetWord', 'Nop', 'CheckResult', 'MenuChoice',
    'CheckTeam', 'CheckMember', 'ShowText', 'SceneFade', 'SetPosFade',
    'WaitTimer', 'Yield', 'Jump', 'Else', 'MiniGame', 'Note',
    'StopSound', 'BlackTalk', 'TalkA',
]

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
        txt=dec[ao:end].replace(b'\x1e',b'\n')
        try: s=txt.decode('big5',errors='replace')
        except: s=txt.decode('gbk',errors='replace')
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
        from PIL import Image, ImageTk
        img = Image.frombytes('RGBA', (sec.width, sec.height), bytes(rgba))
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

# ============================================================
# MatEditor
# ============================================================
class MatEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKMat.Dat 地图实体编辑器 v2.2")
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
        self._vis_entities = {}; self._vis_selected = None; self._vis_drag = None
        self._sc_grp_section_count = 0
        self._ani_jvg = None; self._cha_jvg = None; self._cur_jvg = None  # JVG 精灵数据
        self._vis_display_mode = tk.StringVar(value="游戏默认")
        self._vis_anim_playing = False      # 动画播放状态(默认暂停)
        self._vis_anim_timer = None         # 动画循环 timer ID
        self._vis_anim_frame = {}           # entity_idx → current cycle frame offset
        self._vis_play_btn = None           # 播放按钮引用
        self.defunit_recs = []; self.defunit_next = {}; self.defunit_entity = {}  # DefUnit链
        self.tkd_defines = []; self.tkd_header = ''; self.tkd_define_map = {}  # TKD脚本
        self._bit_enable = tk.BooleanVar(value=False)    # d2 bit0: 启用
        self._bit_visible = tk.BooleanVar(value=False)   # d2 bit1: 可见
        self._bit_pickable = tk.BooleanVar(value=False)  # d2 bit2: 可拾取
        self._bit_hint = tk.BooleanVar(value=False)      # d2 bit3: 提示标记
        self._bit_busy = tk.BooleanVar(value=False)      # d2 bit4: 忙碌
        self._bit_resume = tk.BooleanVar(value=False)    # d2 bit5: 恢复
        self._bit_animloop = tk.BooleanVar(value=False)  # d2 bit16: 动画循环
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
        cols2 = ('index','type','scene','x','y')
        self.tree = ttk.Treeview(entity_frame, columns=cols2, show='headings', selectmode='browse')
        for cid,cn,cw in [('index','索引',45),('type','类型',85),('scene','场景',110),('x','X',45),('y','Y',45)]:
            self.tree.heading(cid,text=cn,command=lambda c=cid:self._sort_by(c))
            self.tree.column(cid,width=cw,anchor='center' if cid in('index','x','y') else 'w',minwidth=cw)
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
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=3)
        ttk.Button(top, text="刷新", command=self._vis_load_scene, width=4).pack(side=tk.LEFT, padx=1)
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
        self._build_group("基础属性", BASIC_FIELDS, 0)
        self._build_group("位置", POS_FIELDS, 1)
        self._build_group("动画", ANIM_FIELDS, 2)
        self._build_group("脚本", SCRIPT_FIELDS, 3)
        self._build_group("交互/角色", INTERACT_FIELDS, 4)
        self._build_group("运行时(只读)", RUNTIME_FIELDS, 5)
        # flags ↔ checkbutton 双向同步
        self._sync_lock = False
        _bit_vars = [(self._bit_enable,1), (self._bit_visible,2), (self._bit_pickable,4),
                     (self._bit_hint,8), (self._bit_busy,0x10), (self._bit_resume,0x20),
                     (self._bit_animloop,0x10000)]
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
            if key=='type':
                cb=ttk.Combobox(frm,state='readonly',values=[f"{k}-{v}" for k,v in sorted(ENTITY_TYPES.items())],width=14,font=FONT)
                cb.pack(fill=tk.X); self._edit_vars[key]=cb
            elif key=='anim_set':
                cb=ttk.Combobox(frm,state='readonly',values=[f"{k}-{v}" for k,v in ANIM_SETS.items()],width=16,font=FONT)
                cb.pack(fill=tk.X); self._edit_vars[key]=cb
            elif key=='blend_mode':
                cb=ttk.Combobox(frm,state='readonly',values=["0-正常","1-染色","2-加法发光","3-减法压暗","4-亮度alpha","5-水平翻转"],width=16,font=FONT)
                cb.pack(fill=tk.X); self._edit_vars[key]=cb
            elif key=='flags':
                ev=tk.StringVar(); self._edit_vars[key]=ev
                ttk.Entry(frm,textvariable=ev,width=14,font=FONT).pack(fill=tk.X)
                cbf=ttk.Frame(frm); cbf.pack(fill=tk.X, pady=(2,0))
                # 位域 checkbutton: 第一行 bit0~3, 第二行 bit4~5+bit16
                bits_r1=[("_bit_enable","启用","bit0=启用(Enabled): 参与游戏循环和脚本执行。SetEnabled(40BE30), Disable(40C5A4)清除, Enable(40C648)设置"),
                         ("_bit_visible","显示","bit1=可见(Visible): 渲染到屏幕。SetVisible(40BEDC), Disable清除, Enable设置"),
                         ("_bit_pickable","可交互","bit2=可交互(Interactive): 写入鼠标拾取缓冲区, 可被点击触发交互(对话/开锁/拾物)。406864:117渲染写入word_78E276, 410B74鼠标点击读出, 408E5C交互校验"),
                         ("_bit_hint","提示","bit3=提示标记(Hint): 显示浮动提示。SetHint(40B650)控制")]
                bits_r2=[("_bit_busy","忙碌","bit4=忙碌(Busy): 脚本交互执行中, 阻塞移动。引擎交互状态机管理"),
                         ("_bit_resume","恢复","bit5=恢复(Resume): 交互结束恢复标记。引擎交互状态机管理"),
                         ("_bit_animloop","循环动画","bit16=动画循环(AnimLoop): 动画循环播放。SetAni(40C1A4)控制")]
                for ri,row_bits in enumerate([bits_r1,bits_r2]):
                    rf=ttk.Frame(cbf); rf.pack(fill=tk.X)
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
        return lf

    def _build_script_tab(self):
        """构建 Tab "脚本" — DefUnit 链列表 + 脚本编辑器"""
        pw = ttk.PanedWindow(self.tab_script, orient=tk.VERTICAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # 上方: DefUnit 链编辑区
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

        cols_chain = ('sub', 'du_idx', 'define_id', 'block_id', 'mark')
        self.chain_tree = ttk.Treeview(top_f, columns=cols_chain, show='headings', selectmode='browse')
        col_defs_chain = [('sub', '子场景', 40), ('du_idx', 'DefUnit#', 60),
                          ('define_id', 'DEFINE ID', 110), ('block_id', 'f0', 35),
                          ('mark', '标记', 50)]
        for cid, cn, cw in col_defs_chain:
            self.chain_tree.heading(cid, text=cn)
            self.chain_tree.column(cid, width=cw, anchor='center' if cid != 'define_id' else 'w', minwidth=cw)
        csb = ttk.Scrollbar(top_f, orient=tk.VERTICAL, command=self.chain_tree.yview)
        self.chain_tree.configure(yscrollcommand=csb.set)
        self.chain_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); csb.pack(side=tk.RIGHT, fill=tk.Y)
        self.chain_tree.bind('<<TreeviewSelect>>', self._on_chain_select)

        # 下方: 脚本编辑器
        bot_f = ttk.LabelFrame(pw, text="DEFINE 脚本", padding=4)
        pw.add(bot_f, weight=5)
        self.script_info_lbl = ttk.Label(bot_f, text="(未选中 DEFINE)", font=FONT_S, foreground='#666')
        self.script_info_lbl.pack(anchor=tk.W, pady=(0,3))
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
        """加载场景到画布"""
        sid = self._vis_scene_id.get()
        self._vis_canvas.delete('all')
        self._vis_entities.clear(); self._vis_selected = None; self._vis_drag = None
        self._vis_anim_frame.clear()  # 新场景重置动画帧
        # 限制精灵缓存: 保留最近 200 个
        if len(_SPRITE_CACHE) > 200:
            for k in list(_SPRITE_CACHE.keys())[:len(_SPRITE_CACHE)-200]:
                del _SPRITE_CACHE[k]

        if not self.records: return

        # 尝试加载背景
        self._vis_bg_id = None
        if self.dat_path:
            d = os.path.dirname(self.dat_path)
            grp_path = os.path.join(d, "SC.GRP")
            idx_path = os.path.join(d, "SC.IDX")
            if os.path.exists(grp_path):
                try:
                    bg = load_scene_background(grp_path, idx_path, sid)
                    if bg:
                        self._vis_bg_image = bg  # keep reference
                        self._vis_bg_id = self._vis_canvas.create_image(0, 0, anchor='nw', image=bg)
                except Exception:
                    pass

        # 收集场景实体 (scene_id 匹配 SC.GRP section ID)
        ents = [r for r in self.records if has_data(r) and r['d1'] == sid]
        sname = scene_name(self.tkt_scenes, sid)
        if not ents:
            self._vis_info.config(text=f"SC.GRP #{sid}: {sname} — 无实体 (空场景)")
            self._vis_canvas.configure(scrollregion=(0,0,MAX_MAP_W,MAX_MAP_H))
            return

        # 绘制实体 (按Y坐标排序，Y值大的在上面)
        ents.sort(key=lambda r: r['d19'] if r['d0'] == 10 else r['d11'])
        for r in ents:
            self._vis_draw_entity(r)

        # 更新滚动区域
        xs = [r['d10'] for r in ents]; ys = [r['d11'] for r in ents]
        minx, maxx = min(xs)-50, max(xs)+50
        miny, maxy = min(ys)-50, max(ys)+50
        w = max(MAX_MAP_W, maxx - minx + 200)
        h = max(MAX_MAP_H, maxy - miny + 200)
        self._vis_canvas.configure(scrollregion=(0, 0, w, h))

        self._vis_info.config(text=f"SC.GRP #{sid}: {sname} — {len(ents)} 个实体")
        # 动画模式: 若正在播放则恢复, 否则不自动启动
        if self._vis_anim_playing:
            self._vis_start_anim()

    def _vis_start_anim(self):
        """启动精灵动画循环 (~200ms/帧); auto/ani 模式开, cha/wire 模式关"""
        if self._vis_anim_timer: return
        mode = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')
        if mode in ('wire', 'cha'): return
        def _tick():
            m = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')
            if m in ('wire', 'cha'):
                self._vis_anim_timer = None; return
            updated = False
            for idx in list(self._vis_anim_frame.keys()):
                self._vis_anim_frame[idx] += 1
                updated = True
            if updated:
                self._vis_redraw()
            self._vis_anim_timer = self.root.after(200, _tick)
        self._vis_anim_timer = self.root.after(200, _tick)

    def _vis_stop_anim(self):
        if self._vis_anim_timer:
            self.root.after_cancel(self._vis_anim_timer)
            self._vis_anim_timer = None

    def _vis_draw_entity(self, r):
        """在画布上绘制单个实体"""
        tval = r['d0']
        if not self._vis_show_types.get(tval, tk.BooleanVar(value=True)).get():
            return

        x, y = r['d10'], r['d11']
        color = '#%02x%02x%02x' % TYPE_COLORS_RGBA.get(tval, (128,128,128))
        idx = r['index']
        items = []
        mode = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')

        # JVG 精灵选择: auto模式按d70逐实体判断 (sub_405CBC逻辑)
        #   type 200: d70=1→Ani.JVG+d64(行走动画) d70=0→Cha.JVG+d51(立绘)
        #   type 20/110: Ani.JVG+d64
        sprite = None; sx = x; sy = y
        jvg = None; blk_idx = 0; should_animate = False
        if mode == 'wire':
            pass
        elif mode == 'auto':
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
                if should_animate:
                    if idx not in self._vis_anim_frame: self._vis_anim_frame[idx] = 0
                    anim = self._vis_anim_frame[idx]
                else:
                    anim = 0
                fi, fpd = _get_dir_frame(blk, r['d13'], r['d16'], r['d53'], anim)
                if fi < len(blk.frames):
                    sprite = _get_blended_sprite(jvg, blk_idx, fi, r.get('d24', 0), r.get('d25', 0))
                    if sprite:
                        sx = x + blk.frames[fi].x_off; sy = y + blk.frames[fi].y_off

        # 逆: sub_406864:37 / sub_43339C:68 — 主精灵前先绘阴影
        # Cha.JVG block[0] 经实测: frames[0]=1x480工具帧, frames[1]=39x23小阴影, frames[2]=65x33大阴影
        # sub_43BF20:41 — 原游戏通过角色数据表选择阴影大小; 此处以角色精灵宽度近似
        shadow_sprite = None; shadow_sx = shadow_sy = 0
        if (tval == 200 or tval == 20) and jvg is self._cha_jvg and jvg.block_count > 0:
            blk0 = jvg.blocks[0]
            if blk0.frames and len(blk0.frames) >= 3:
                char_w = blk.frames[fi].width if blk_idx < jvg.block_count and blk_idx != 0 and blk.frames else 0
                shadow_fi = 2 if char_w > 50 else 1
                shadow_sprite = _make_subtractive_shadow(jvg, 0, shadow_fi)
                if shadow_sprite:
                    shadow_sx = x + blk0.frames[shadow_fi].x_off
                    shadow_sy = y + blk0.frames[shadow_fi].y_off
        if shadow_sprite and mode != 'wire':
            items.append(self._vis_canvas.create_image(shadow_sx, shadow_sy, anchor='nw', image=shadow_sprite, tags=('entity', f'e{idx}')))
        if sprite and mode != 'wire':
            items.append(self._vis_canvas.create_image(sx, sy, anchor='nw', image=sprite, tags=('entity', f'e{idx}')))
            items.append(self._vis_canvas.create_text(x, y-4, text=f"#{idx}", fill='#FFD700', font=('',6), tags=('entity',f'e{idx}')))
        elif tval == 10:  # 地形块
            bx, by = r['d18'], r['d19']
            bw = r['d20'] if r['d20'] > 0 else 40
            bh = r['d21'] if r['d21'] > 0 else 40
            items.append(self._vis_canvas.create_rectangle(bx, by, bx+bw, by+bh, outline=color, width=2, tags=('entity', f'e{idx}')))
            items.append(self._vis_canvas.create_text(bx+bw//2, by+bh//2, text=f"T{idx}", fill=color, font=('',7), tags=('entity',f'e{idx}')))
        elif tval == 5:
            s = 12
            items.append(self._vis_canvas.create_polygon(x, y-s, x+s, y, x, y+s, x-s, y, outline=color, fill='', width=2, tags=('entity', f'e{idx}')))
            items.append(self._vis_canvas.create_text(x, y-16, text=f"P{idx}", fill=color, font=('',7), tags=('entity',f'e{idx}')))
        elif tval == 200:
            s = 10
            items.append(self._vis_canvas.create_oval(x-s, y-s-4, x+s, y+s-4, outline=color, width=2, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_line(x, y+6, x, y+14, fill=color, width=2, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_text(x, y-20, text=f"N{idx}", fill=color, font=('',7), tags=('entity',f'e{idx}')))
        else:
            s = 10
            items.append(self._vis_canvas.create_rectangle(x-s, y-s, x+s, y+s, outline=color, width=2, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_text(x, y-16, text=f"#{idx}", fill=color, font=('',7), tags=('entity',f'e{idx}')))

        self._vis_entities[idx] = items

    def _vis_draw_entity_highlighted(self, r):
        """绘制高亮选中的实体 (金黄边框)"""
        tval = r['d0']
        x, y = r['d10'], r['d11']
        hcolor = '#FFD700'; idx = r['index']; items = []
        mode = DISPLAY_MODES.get(self._vis_display_mode.get(), 'auto')

        # JVG 精灵选择 (高亮版): 与 _vis_draw_entity 同等逻辑
        sprite = None; sx = x; sy = y
        jvg = None; bi = 0; should_animate = False
        if mode == 'wire':
            pass
        elif mode == 'auto':
            if tval == 200:
                if r['d70'] == 1 and r['d64'] > 0 and self._ani_jvg:
                    jvg = self._ani_jvg; bi = r['d64']; should_animate = True
                elif r['d51'] > 0 and self._cha_jvg:
                    jvg = self._cha_jvg; bi = r['d51']
            elif tval in (20, 110) and r['d64'] > 0 and self._ani_jvg:
                jvg = self._ani_jvg; bi = r['d64']; should_animate = True
        elif mode == 'ani':
            if tval in (200, 20, 110) and r['d64'] > 0 and self._ani_jvg:
                jvg = self._ani_jvg; bi = r['d64']; should_animate = True
        elif mode == 'cha':
            if tval == 200 and r['d51'] > 0 and self._cha_jvg:
                jvg = self._cha_jvg; bi = r['d51']
            elif tval in (20, 110) and r['d64'] > 0 and self._ani_jvg:
                jvg = self._ani_jvg; bi = r['d64']
        if jvg and bi < jvg.block_count and jvg.blocks[bi].frames:
            blk = jvg.blocks[bi]
            anim = self._vis_anim_frame.get(idx, 0) if should_animate else 0
            fi, _ = _get_dir_frame(blk, r['d13'], r['d16'], r['d53'], anim)
            if fi < len(blk.frames):
                sprite = _get_blended_sprite(jvg, bi, fi, r.get('d24', 0), r.get('d25', 0))
                if sprite:
                    sx = x + blk.frames[fi].x_off; sy = y + blk.frames[fi].y_off

        # 逆: sub_406864:72 / sub_43339C:68 — 主精灵前先绘阴影 (高亮版)
        shadow_sprite = None; shadow_sx = shadow_sy = 0
        if (tval == 200 or tval == 20) and jvg is self._cha_jvg and jvg.block_count > 0:
            blk0 = jvg.blocks[0]
            if blk0.frames and len(blk0.frames) >= 3:
                char_w = blk.frames[fi].width if bi < jvg.block_count and bi != 0 and blk.frames else 0
                shadow_fi = 2 if char_w > 50 else 1
                shadow_sprite = _make_subtractive_shadow(jvg, 0, shadow_fi)
                if shadow_sprite:
                    shadow_sx = x + blk0.frames[shadow_fi].x_off
                    shadow_sy = y + blk0.frames[shadow_fi].y_off
        if shadow_sprite and mode != 'wire':
            items.append(self._vis_canvas.create_image(shadow_sx, shadow_sy, anchor='nw', image=shadow_sprite, tags=('entity', f'e{idx}')))
        if sprite and mode != 'wire':
            items.append(self._vis_canvas.create_image(sx, sy, anchor='nw', image=sprite, tags=('entity', f'e{idx}')))
            fw, fh = sprite.width(), sprite.height()
            items.append(self._vis_canvas.create_rectangle(sx, sy, sx+fw, sy+fh, outline=hcolor, width=2, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_text(x, y-4, text=f"#{idx}", fill=hcolor, font=('',7,'bold'), tags=('entity',f'e{idx}')))
        elif tval == 10:
            bx, by = r['d18'], r['d19']
            bw = r['d20'] if r['d20']>0 else 40; bh = r['d21'] if r['d21']>0 else 40
            items.append(self._vis_canvas.create_rectangle(bx, by, bx+bw, by+bh, outline=hcolor, width=3, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_text(bx+bw//2, by+bh//2, text=f"T{idx}", fill=hcolor, font=('',8,'bold'), tags=('entity',f'e{idx}')))
        elif tval == 5:
            s=12
            items.append(self._vis_canvas.create_polygon(x, y-s, x+s, y, x, y+s, x-s, y, outline=hcolor, fill='', width=3, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_text(x, y-16, text=f"P{idx}", fill=hcolor, font=('',8,'bold'), tags=('entity',f'e{idx}')))
        elif tval == 200:
            s=10
            items.append(self._vis_canvas.create_oval(x-s, y-s-4, x+s, y+s-4, outline=hcolor, width=3, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_line(x, y+6, x, y+14, fill=hcolor, width=3, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_text(x, y-20, text=f"N{idx}", fill=hcolor, font=('',8,'bold'), tags=('entity',f'e{idx}')))
        else:
            s=10
            items.append(self._vis_canvas.create_rectangle(x-s, y-s, x+s, y+s, outline=hcolor, width=3, tags=('entity',f'e{idx}')))
            items.append(self._vis_canvas.create_text(x, y-16, text=f"#{idx}", fill=hcolor, font=('',8,'bold'), tags=('entity',f'e{idx}')))
        self._vis_entities[idx] = items

    def _vis_redraw(self):
        """重新绘制当前场景"""
        sid = self._vis_scene_id.get()
        self._vis_canvas.delete('all')
        self._vis_entities.clear(); self._vis_selected = None
        if self._vis_bg_id:
            self._vis_bg_id = self._vis_canvas.create_image(0,0,anchor='nw',image=self._vis_bg_image)
        if not self.records: return
        # 按Y坐标排序绘制 (Y值大的在上面)
        ents = [r for r in self.records if has_data(r) and r['d1'] == sid]
        ents.sort(key=lambda r: r['d19'] if r['d0'] == 10 else r['d11'])
        for r in ents:
            self._vis_draw_entity(r)

    # ---- 画布交互 ----
    def _vis_canvas_click(self, event):
        """点击画布：选中实体"""
        cx = self._vis_canvas.canvasx(event.x)
        cy = self._vis_canvas.canvasy(event.y)
        # 重绘以清除旧选中高亮
        if self._vis_selected is not None:
            old = self._vis_selected
            if old in self._vis_entities:
                for iid in self._vis_entities[old]:
                    self._vis_canvas.delete(iid)
                del self._vis_entities[old]
                self._vis_draw_entity(self.records[old])
        # 查找点击的实体
        overlapping = self._vis_canvas.find_overlapping(cx-5, cy-5, cx+5, cy+5)
        found = None
        for iid in overlapping:
            tags = self._vis_canvas.gettags(iid)
            for t in tags:
                if t.startswith('e') and t[1:].isdigit():
                    found = int(t[1:])
                    break
            if found is not None: break

        if found is not None and found in self._vis_entities:
            self._vis_selected = found
            # 删除后重绘为高亮版本
            for iid in self._vis_entities[found]:
                self._vis_canvas.delete(iid)
            del self._vis_entities[found]
            self._vis_draw_entity_highlighted(self.records[found])
            rec = self.records[found]
            tname = ENTITY_TYPES.get(rec['d0'], '?')
            pos_x = rec['d18'] if rec['d0'] == 10 else rec['d10']
            pos_y = rec['d19'] if rec['d0'] == 10 else rec['d11']
            self._vis_info.config(text=f"选中: #{found} [{tname}] 坐标({pos_x},{pos_y}) — 拖拽可移动")
            self._vis_drag = (found, cx, cy, pos_x, pos_y)
            # 同步左侧实体列表选中 + 右侧编辑面板
            self._sync_entity_list_select(found)
            self._current_param_idx = found
            self._show_record(rec)
        else:
            self._vis_selected = None
            self._vis_drag = None
            self._vis_info.config(text="")

    def _vis_canvas_drag(self, event):
        """拖拽实体移动"""
        if self._vis_drag is None: return
        eidx, sx, sy, ox, oy = self._vis_drag
        cx = self._vis_canvas.canvasx(event.x)
        cy = self._vis_canvas.canvasy(event.y)
        dx, dy = int(cx - sx), int(cy - sy)
        new_x, new_y = ox + dx, oy + dy

        rec = self.records[eidx]
        if rec['d0'] == 10:
            rec['d18'], rec['d19'] = new_x, new_y
            rec['d10'], rec['d11'] = new_x, new_y  # 同步坐标字段
        else:
            rec['d10'], rec['d11'] = new_x, new_y
        self._dirty = True

        # 重绘该实体
        for iid in self._vis_entities.get(eidx, []):
            self._vis_canvas.delete(iid)
        if eidx in self._vis_entities:
            del self._vis_entities[eidx]
        if self._vis_selected == eidx:
            self._vis_draw_entity_highlighted(self.records[eidx])
        else:
            self._vis_draw_entity(self.records[eidx])
        self._vis_info.config(text=f"移动: #{eidx} → ({new_x},{new_y})")

    def _vis_canvas_release(self, event):
        """释放拖拽"""
        if self._vis_drag:
            # 重新设置拖拽起点为当前位置
            eidx, _, _, _, _ = self._vis_drag
            rec = self.records[eidx]
            cx = self._vis_canvas.canvasx(event.x)
            cy = self._vis_canvas.canvasy(event.y)
            pos_x = rec['d18'] if rec['d0'] == 10 else rec['d10']
            pos_y = rec['d19'] if rec['d0'] == 10 else rec['d11']
            self._vis_drag = (eidx, cx, cy, pos_x, pos_y)
            # 如果参数模式也打开了同一实体，同步显示
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

    def _on_display_mode_change(self):
        """显示模式切换: 停止动画, 重置播放状态, 重载场景"""
        self._vis_stop_anim()
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
            vals=(str(idx),f"{tval}-{ENTITY_TYPES.get(tval,'未知')}",sname,str(rec['d10']),str(rec['d11']))
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
        ci={'index':0,'type':1,'scene':2,'x':3,'y':4}.get(col,0)
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
        # 同步高亮中间地图：若实体在当前场景中则高亮
        if rec['d1'] == self._vis_scene_id.get() and idx in self._vis_entities:
            if self._vis_selected is not None and self._vis_selected != idx:
                old = self._vis_selected
                if old in self._vis_entities:
                    for iid in self._vis_entities[old]: self._vis_canvas.delete(iid)
                    del self._vis_entities[old]
                    self._vis_draw_entity(self.records[old])
            self._vis_selected = idx
            for iid in self._vis_entities.get(idx, []): self._vis_canvas.delete(iid)
            if idx in self._vis_entities: del self._vis_entities[idx]
            self._vis_draw_entity_highlighted(rec)
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
        """刷新 DefUnit 链 Treeview (按子场景 A/B/C 分组)"""
        self.chain_tree.delete(*self.chain_tree.get_children())
        if not self.records: return
        rec = self.records[self._current_param_idx] if hasattr(self, '_current_param_idx') and self._current_param_idx is not None and 0 <= self._current_param_idx < len(self.records) else None
        if not rec or not has_data(rec):
            self._clear_script_editor()
            return
        entity_id = rec['index']
        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0); mx = rec.get(f'd{mx_di}', 0)
            cur = rec.get(f'd{cur_di}', 0)
            if h <= 0 or mx <= 0: continue
            # 插入分组标题
            head_iid = self.chain_tree.insert('', 'end', values=(f'子场景{sub_name}', '', '', '', f'head=#{h} max={mx}'), tags=('group',))
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
                self.chain_tree.insert('', 'end', values=(f'  {sub_name}', str(idx), str(define_id), str(du_rec['f0']), ','.join(marks)),
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
            return
        # 自动选中当前项 (cur=1 的链头)
        for item in self.chain_tree.get_children():
            tags = self.chain_tree.item(item, 'tags')
            if 'entry' in tags:
                self.chain_tree.selection_set(item)
                self.chain_tree.see(item)
                self._on_chain_select()
                break

    def _on_chain_select(self, event=None):
        """选中链列表项 → 保存当前编辑 → 加载新 DEFINE"""
        sel = self.chain_tree.selection()
        if not sel: return
        tags = self.chain_tree.item(sel[0], 'tags')
        if 'group' in tags: return  # 分组标题不可选
        vals = self.chain_tree.item(sel[0], 'values')
        if not vals or not vals[2].isdigit(): return
        define_id = int(vals[2])
        du_idx = int(vals[1]) if vals[1].isdigit() else 0
        # 保存当前编辑
        self._save_editor_to_define()
        # 加载新 DEFINE
        self._load_define_to_editor(define_id)
        self.chain_info_lbl.config(text=f"DefUnit #{du_idx} → DEFINE {define_id}")

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
        self._refresh_chain_list()
        # 选中新节点
        for item in self.chain_tree.get_children():
            if self.chain_tree.item(item, 'values')[1] == str(empty_idx):
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
        if not vals or not vals[1].isdigit(): return
        du_idx = int(vals[1])
        define_id = int(vals[2]) if vals[2].isdigit() else 0
        du_rec = next((r for r in self.defunit_recs if r['index'] == du_idx), None)
        if du_rec is None: return
        entity_id = du_rec['f1']

        if not messagebox.askyesno("确认删除", f"删除 DefUnit #{du_idx} → DEFINE {define_id}?\n此操作同时从 TKD.dat 删除对应 DEFINE 块。"):
            return

        # 找到链中前驱节点
        rec = self.records[self._current_param_idx]
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
        # 清空编辑器
        self.script_text.config(state='normal')
        self.script_text.delete('1.0', tk.END)
        self.script_text.config(state='disabled')
        self._current_edit_define_id = None
        self._refresh_chain_list()

    def _show_record(self,rec):
        self._sync_lock=True
        idx=rec['index']; tval=rec['d0']; tname=ENTITY_TYPES.get(tval,f"未知({tval})")
        sname=scene_name(self.tkt_scenes,rec['d1'])
        self.lbl_title.config(text=f"实体 #{idx} [{tname}] {sname} ({rec['d10']},{rec['d11']})")
        for key,di,label,cmt in ALL_EDIT_FIELDS:
            val=rec[f'd{di}']
            BLEND_MODES = {0:"正常",1:"染色",2:"加法发光",3:"减法压暗",4:"亮度alpha",5:"水平翻转"}
            if key=='type': self._edit_vars[key].set(f"{val}-{ENTITY_TYPES.get(val,'未知')}")
            elif key=='anim_set': self._edit_vars[key].set(f"{val}-{ANIM_SETS.get(val,'未知')}" if val in ANIM_SETS else f"{val}-未知")
            elif key=='blend_mode': self._edit_vars[key].set(f"{val}-{BLEND_MODES.get(val,'未知')}")
            else: self._edit_vars[key].set(str(val))
        for key,di,label,cmt in RUNTIME_FIELDS:
            if key in self._edit_vars: self._edit_vars[key].set(str(rec[f'd{di}']))
        if '_scene_label' in self._edit_vars: self._edit_vars['_scene_label'].config(text=sname)
        if '_hint_label' in self._edit_vars:
            hid=rec['d23']; self._edit_vars['_hint_label'].config(text="" if hid==0 else self.tkt_scenes.get(hid,""))
        flags=rec['d2']
        self._bit_enable.set((flags&1)!=0)
        self._bit_visible.set((flags&2)!=0)
        self._bit_pickable.set((flags&4)!=0)
        self._bit_hint.set((flags&8)!=0)
        self._bit_busy.set((flags&0x10)!=0)
        self._bit_resume.set((flags&0x20)!=0)
        self._bit_animloop.set((flags&0x10000)!=0)
        self._sync_lock=False
        # 刷新脚本标签页链列表
        self._refresh_chain_list()

    def _clear_form(self):
        self._sync_lock=True
        for key,var in self._edit_vars.items():
            if isinstance(var,tk.StringVar): var.set("")
            elif isinstance(var,ttk.Combobox): var.set("")
        if '_scene_label' in self._edit_vars: self._edit_vars['_scene_label'].config(text="")
        if '_hint_label' in self._edit_vars: self._edit_vars['_hint_label'].config(text="")
        # 清空脚本标签页
        self._clear_script_editor()
        self.chain_tree.delete(*self.chain_tree.get_children())
        self.chain_info_lbl.config(text="")
        for bv in (self._bit_enable,self._bit_visible,self._bit_pickable,
                    self._bit_hint,self._bit_busy,self._bit_resume,self._bit_animloop):
            bv.set(False)
        self._sync_lock=False

    def _read_form(self):
        vals={}
        for key,di,label,cmt in ALL_EDIT_FIELDS:
            var=self._edit_vars[key]
            if isinstance(var,ttk.Combobox):
                try: v=int(var.get().split('-')[0])
                except: return None
            else:
                try: v=int(var.get())
                except: return None
            vals[f'd{di}']=v
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
        # 如果可视化模式在看同一场景，重绘实体
        if rec['d1'] == self._vis_scene_id.get():
            for iid in self._vis_entities.get(idx, []): self._vis_canvas.delete(iid)
            self._vis_draw_entity(rec)
            # 若该实体正被高亮选中，重绘为高亮版
            if self._vis_selected == idx:
                for iid in self._vis_entities.get(idx, []): self._vis_canvas.delete(iid)
                if idx in self._vis_entities: del self._vis_entities[idx]
                self._vis_draw_entity_highlighted(rec)
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

        # 若在当前场景则绘入画布
        if sel_scene==self._vis_scene_id.get():
            for iid in self._vis_entities.get(empty_idx,[]): self._vis_canvas.delete(iid)
            if empty_idx in self._vis_entities: del self._vis_entities[empty_idx]
            self._vis_draw_entity(rec)
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
        messagebox.showinfo("关于","TKMat.Dat 地图实体编辑器 v2.2\n\n"
            "模式: 参数 + 可视化 + 脚本编辑\n"
            "逆向依据: sub_412688, sub_405CBC, sub_4066F0, sub_40EBD4\n"
            "格式: TKMat 6000×384B + TKDefUnit 5000×16B + TKD脚本\n"
            "保存时一次性写入三个文件")

# ============================================================
def main():
    root=tk.Tk(); app=MatEditor(root); root.mainloop()

if __name__=='__main__': main()
