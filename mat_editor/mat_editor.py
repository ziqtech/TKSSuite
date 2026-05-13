#!/usr/bin/env python3
"""
TKMat.Dat 地图实体编辑器 v2.0 — 参数模式 + 可视化模式
=============================================================
逆向依据:
  sub_412688:21: TKMat.Dat → dword_51AF40 (2304000B, 6000×384B)
  sub_41103C:26: 场景文件 LZSS 解压覆盖实体表
  sub_405CBC: 实体类型分支渲染 (5/10/15/16/20/110/200)
  sub_4077E4: 朝向 [13], sub_407070: 坐标 [10][11]
  sub_40EBD4: 脚本PC[42]/DefUnit索引[44]/子场景[30-35]

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

ENTITY_TYPES = {0:"空槽",5:"入口/传送点",10:"地形块",15:"障碍物",16:"建筑/门",
                20:"事件对象",110:"特殊机关",200:"NPC/角色"}
TYPE_COLORS = {0:"#AAA",5:"#2196F3",10:"#4CAF50",15:"#FF9800",16:"#795548",
               20:"#9C27B0",110:"#E91E63",200:"#F44336"}
TYPE_COLORS_RGBA = {0:(170,170,170),5:(33,150,243),10:(76,175,80),15:(255,152,0),
                    16:(121,85,72),20:(156,39,176),110:(233,30,99),200:(244,67,54)}
DIR_MODES = {0:"静态",4:"NPC四方向",8:"玩家八方向"}
DISPLAY_MODES = {"游戏默认":"auto","动画":"ani","角色":"cha","线框":"wire"}
_JVG_CACHE = {}  # filepath → JVGFile
_SPRITE_CACHE = {}  # (filepath, global_idx) → PhotoImage

BASIC_FIELDS = [
    ("type",0,"实体类型","实体类型: 5=入口 10=地形 15=障碍 16=建筑 20=事件 110=机关 200=NPC"),
    ("scene_id",1,"场景ID","所属场景 (-1=全局)。TKT_ID = scene_id + 300"),
    ("flags",2,"标志位","位域。bit0=启用 bit1=可见 bit2=可交互 bit3=提示 bit4=忙碌 bit5=恢复 bit16=动画循环"),
    ("param",3,"扩展参数","扩展参数 (道具数量/金钱等)"),]
POS_FIELDS = [
    ("x",10,"坐标X","世界坐标X (像素)。sub_407070: a1[10]=x"),
    ("y",11,"坐标Y","世界坐标Y (像素)。sub_407070: a1[11]=y"),
    ("bound_x",18,"碰撞X","碰撞盒/区域X起点。sub_410B74"),
    ("bound_y",19,"碰撞Y","碰撞盒/区域Y起点。sub_410B74"),
    ("direction",13,"朝向","朝向 1~8。sub_4077E4"),]
ANIM_FIELDS = [
    ("anim_set",9,"动画集ID","动画集索引。sub_405CBC: dword_755AC0[v2[9]]"),
    ("dir_mode",53,"方向模式","4=NPC四方向 8=玩家八方向 0=静态。sub_4077E4"),
    ("sub_model",64,"子模型ID","子角色动画模型ID"),("anim_speed",69,"动画速度","动画播放速度"),]
SCRIPT_FIELDS = [
    ("defunit_idx",44,"DefUnit索引","DefUnit记录索引。sub_40EBD4:18"),
    ("cur_define",28,"当前DEFINE","当前DEFINE脚本号"),
    ("max_A",30,"子场景最大A","子场景A最大阶段数"),
    ("max_B",31,"子场景最大B",""),("max_C",32,"子场景最大C",""),
    ("cur_A",33,"子场景当前A",""),("cur_B",34,"子场景当前B",""),("cur_C",35,"子场景当前C",""),
    ("head_A",39,"DefUnit链头A","子场景A链头。sub_4066F0"),
    ("head_B",40,"DefUnit链头B",""),("head_C",41,"DefUnit链头C",""),]
INTERACT_FIELDS = [
    ("char_id",50,"所需角色ID","条件角色。sub_4081F8"),
    ("picture_id",51,"图片ID","角色图片/访问掩码"),
    ("anim_handle",52,"动画句柄","主动画句柄(运行时)"),]
RUNTIME_FIELDS = [
    ("tick",4,"tick","Tick周期(运行时)"),("sub_flags",8,"子标志",""),
    ("timer",12,"计时器",""),("frame_idx",14,"帧索引",""),
    ("frame_count",16,"总帧数",""),("frame_cur",17,"帧计数",""),
    ("script_PC",42,"脚本PC",""),("saved_PC",43,"保存PC",""),
    ("saved_x",56,"保存X",""),("saved_y",57,"保存Y",""),
    ("dest_x",60,"目标X",""),("dest_y",61,"目标Y",""),
    ("sub_handle",65,"子句柄",""),("cur_frame",67,"当前帧",""),
    ("max_frame",68,"最大帧",""),("moving",70,"移动中",""),]
ALL_EDIT_FIELDS = BASIC_FIELDS+POS_FIELDS+ANIM_FIELDS+SCRIPT_FIELDS+INTERACT_FIELDS
FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)
FONT_B = ('Microsoft YaHei UI', 11, 'bold')
MAX_MAP_W, MAX_MAP_H = 1024, 768

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
        self.root.title("TKMat.Dat 地图实体编辑器 v2.0")
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
        self._ani_jvg = None; self._cha_jvg = None  # JVG 精灵数据
        self._vis_display_mode = tk.StringVar(value="游戏默认")
        self._vis_anim_timer = None  # 动画循环 timer ID
        self._vis_anim_frame = {}  # entity_idx → current cycle frame offset
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
        self.root.geometry(f'1280x820+{(sw-1280)//2}+{(sh-820)//2}')

    # =========== UI 构建 ===========
    def _build_ui(self):
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

        # Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # Tab 1: 参数模式
        self.param_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.param_frame, text="参数模式")
        self._build_param_mode()

        # Tab 2: 可视化模式
        self.visual_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.visual_frame, text="可视化模式")
        self._build_visual_mode()

        # 底部路径栏
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0,2))
        self.lbl_path = ttk.Label(pf, text="", foreground="gray")
        self.lbl_path.pack(side=tk.LEFT, padx=10, pady=2)

    # =========== 参数模式 ===========
    def _build_param_mode(self):
        # 工具栏
        tb = ttk.Frame(self.param_frame); tb.pack(fill=tk.X, padx=5, pady=(5,0))
        ttk.Label(tb,text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e_s = ttk.Entry(tb,textvariable=self.search_var,width=16)
        e_s.pack(side=tk.LEFT,padx=2)
        e_s.bind('<Return>',lambda e:self._apply_filter())
        ttk.Button(tb,text="搜索",command=self._apply_filter,width=5).pack(side=tk.LEFT,padx=1)
        ttk.Button(tb,text="清除",command=self._clear_filter,width=5).pack(side=tk.LEFT,padx=1)
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=8)
        ttk.Label(tb,text="类型:").pack(side=tk.LEFT)
        self.filter_type = tk.StringVar(value="全部")
        tc = ["全部"]+[f"{k}-{v}" for k,v in sorted(ENTITY_TYPES.items()) if k!=0]
        cb=ttk.Combobox(tb,textvariable=self.filter_type,values=tc,state='readonly',width=14)
        cb.pack(side=tk.LEFT,padx=2)
        cb.bind('<<ComboboxSelected>>',lambda e:self._apply_filter())
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=8)
        ttk.Label(tb,text="场景:").pack(side=tk.LEFT)
        self.filter_scene=tk.StringVar(value="全部")
        self.cb_scene=ttk.Combobox(tb,textvariable=self.filter_scene,values=["全部"],state='readonly',width=18)
        self.cb_scene.pack(side=tk.LEFT,padx=2)
        self.cb_scene.bind('<<ComboboxSelected>>',lambda e:self._apply_filter())
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=8)
        self.show_empty=tk.BooleanVar(value=False)
        ttk.Checkbutton(tb,text="显示空槽",variable=self.show_empty,command=self._apply_filter).pack(side=tk.LEFT,padx=2)
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=8)
        ttk.Button(tb,text="重新加载",command=self._reload).pack(side=tk.LEFT,padx=2)
        self.status_var=tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb,textvariable=self.status_var,foreground="gray").pack(side=tk.RIGHT,padx=10)

        paned=ttk.PanedWindow(self.param_frame,orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH,expand=True,padx=5,pady=5)
        # 左侧列表
        lf=ttk.Frame(paned); paned.add(lf,weight=2)
        cols=('index','type','scene','x','y')
        self.tree=ttk.Treeview(lf,columns=cols,show='headings',selectmode='browse')
        for cid,cn,cw in [('index','索引',55),('type','类型',100),('scene','场景',140),('x','X',55),('y','Y',55)]:
            self.tree.heading(cid,text=cn,command=lambda c=cid:self._sort_by(c))
            self.tree.column(cid,width=cw,anchor='center' if cid in('index','x','y') else 'w',minwidth=cw)
        vsb=ttk.Scrollbar(lf,orient=tk.VERTICAL,command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT,fill=tk.BOTH,expand=True); vsb.pack(side=tk.RIGHT,fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>',self._on_select)
        for tv,cl in TYPE_COLORS.items(): self.tree.tag_configure(f'type{tv}',foreground=cl)

        # 右侧编辑面板
        rf=ttk.Frame(paned); paned.add(rf,weight=3); self.edit_frame=rf
        self.lbl_title=ttk.Label(rf,text="未选中",font=FONT_B)
        self.lbl_title.pack(anchor=tk.W,pady=(0,6),padx=4)
        mid=ttk.Frame(rf); mid.pack(fill=tk.BOTH,expand=True)
        lc=ttk.Frame(mid); lc.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        scb=ttk.Scrollbar(mid,orient=tk.VERTICAL); scb.pack(side=tk.RIGHT,fill=tk.Y)
        canvas=tk.Canvas(lc,highlightthickness=0); canvas.pack(fill=tk.BOTH,expand=True)
        self.edit_inner=ttk.Frame(canvas); self.edit_inner.columnconfigure(0,weight=1)
        self.edit_inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0),window=self.edit_inner,anchor='nw')
        canvas.configure(yscrollcommand=scb.set)
        canvas.bind('<Configure>',lambda e:self.edit_inner.columnconfigure(0,minsize=e.width))
        def _mw(e): canvas.yview_scroll(int(-1*(e.delta/120)),"units")
        canvas.bind("<Enter>",lambda e:canvas.bind_all("<MouseWheel>",_mw))
        canvas.bind("<Leave>",lambda e:canvas.unbind_all("<MouseWheel>"))
        self._edit_vars={}
        self._build_group("基础属性",BASIC_FIELDS,0)
        self._build_group("位置",POS_FIELDS,1)
        self._build_group("动画",ANIM_FIELDS,2)
        self._build_group("脚本",SCRIPT_FIELDS,3)
        self._build_group("交互/角色",INTERACT_FIELDS,4)
        self._build_group("运行时(只读)",RUNTIME_FIELDS,5)
        # flags ↔ checkbutton 双向同步 (bit0~5 + bit16)
        self._sync_lock = False
        _bit_vars = [(self._bit_enable,1), (self._bit_visible,2), (self._bit_pickable,4),
                     (self._bit_hint,8), (self._bit_busy,0x10), (self._bit_resume,0x20),
                     (self._bit_animloop,0x10000)]
        def _on_cb(*args):
            if self._sync_lock: return
            self._sync_lock = True
            try: flags=int(self._edit_vars['flags'].get())
            except ValueError: flags=0
            for bv,mask in _bit_vars:
                if bv.get(): flags|=mask
                else: flags&=~mask
            self._edit_vars['flags'].set(str(flags))
            self._sync_lock = False
        def _on_flags(*args):
            if self._sync_lock: return
            self._sync_lock = True
            try: flags=int(self._edit_vars['flags'].get())
            except ValueError: self._sync_lock=False; return
            for bv,mask in _bit_vars: bv.set((flags&mask)!=0)
            self._sync_lock = False
        self._edit_vars['flags'].trace_add('write',_on_flags)
        for bv,_ in _bit_vars: bv.trace_add('write',_on_cb)
        bf=ttk.Frame(rf); bf.pack(side=tk.BOTTOM,fill=tk.X,pady=(2,0))
        ttk.Button(bf,text="应用修改",command=self._apply_edit,width=12).pack(side=tk.LEFT)
        ttk.Button(bf,text="重置",command=self._reset_edit,width=8).pack(side=tk.LEFT,padx=2)
        ttk.Button(bf,text="跳转到空槽…",command=self._goto_empty,width=12).pack(side=tk.RIGHT,padx=2)

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
            elif key=='dir_mode':
                cb=ttk.Combobox(frm,state='readonly',values=[f"{k}-{v}" for k,v in DIR_MODES.items()],width=14,font=FONT)
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
        return lf

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

    # =========== 可视化模式 ===========
    def _build_visual_mode(self):
        vf = self.visual_frame
        # 顶部场景选择 + 筛选
        top = ttk.Frame(vf); top.pack(fill=tk.X, padx=5, pady=(5,0))
        ttk.Label(top, text="场景:").pack(side=tk.LEFT)
        self._vis_scene_combo = ttk.Combobox(top, state='readonly', width=25)
        self._vis_scene_combo.pack(side=tk.LEFT, padx=2)
        self._vis_scene_combo.bind('<<ComboboxSelected>>', lambda e: self._on_vis_combo_select())
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        for tval in [5,10,15,16,20,110,200]:
            ttk.Checkbutton(top, text=ENTITY_TYPES.get(tval,f"T{tval}"),
                            variable=self._vis_show_types[tval],
                            command=self._vis_redraw).pack(side=tk.LEFT, padx=2)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(top, text="单位显示:").pack(side=tk.LEFT)
        cb_mode = ttk.Combobox(top, textvariable=self._vis_display_mode,
                               values=list(DISPLAY_MODES.keys()), state='readonly', width=6)
        cb_mode.pack(side=tk.LEFT, padx=2)
        cb_mode.bind('<<ComboboxSelected>>', lambda e: (self._vis_stop_anim(), self._vis_load_scene()))
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(top, text="刷新地图", command=self._vis_load_scene).pack(side=tk.LEFT, padx=2)
        self._vis_status = tk.StringVar(value="")
        ttk.Label(top, textvariable=self._vis_status, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # 主区域：左侧场景列表 + 右侧地图
        paned = ttk.PanedWindow(vf, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧：场景列表
        lf = ttk.Frame(paned); paned.add(lf, weight=1)
        cols = ('sid', 'sname', 'cnt')
        self._vis_tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        self._vis_tree.heading('sid', text='SC#'); self._vis_tree.column('sid', width=45, anchor='center')
        self._vis_tree.heading('sname', text='场景名称 (TKT[SC+300])'); self._vis_tree.column('sname', width=160)
        self._vis_tree.heading('cnt', text='实体'); self._vis_tree.column('cnt', width=45, anchor='center')
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self._vis_tree.yview)
        self._vis_tree.configure(yscrollcommand=vsb.set)
        self._vis_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._vis_tree.bind('<<TreeviewSelect>>', self._on_vis_scene_select)

        # 右侧：地图画布
        rf = ttk.Frame(paned); paned.add(rf, weight=4)
        # 信息栏
        info_bar = ttk.Frame(rf); info_bar.pack(fill=tk.X)
        self._vis_info = ttk.Label(info_bar, text="", font=FONT_S, foreground='#666')
        self._vis_info.pack(side=tk.LEFT, padx=4)

        # Canvas + 滚动条
        cf = ttk.Frame(rf); cf.pack(fill=tk.BOTH, expand=True)
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
        self._vis_canvas.bind('<MouseWheel>', lambda e: self._vis_canvas.yview_scroll(int(-1*(e.delta/120)),"units"))

        # 编辑弹窗（轻量）
        self._vis_edit_win = None

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

    def _on_vis_combo_select(self):
        val = self._vis_scene_combo.get()
        try: sid = int(val.split(':')[0])
        except ValueError: return
        self._vis_scene_id.set(sid)
        self._vis_stop_anim()
        self._vis_load_scene()

    def _on_vis_scene_select(self, event):
        sel = self._vis_tree.selection()
        if not sel: return
        sid = int(self._vis_tree.item(sel[0], 'values')[0])
        self._vis_scene_id.set(sid)
        for v in self._vis_scene_combo['values']:
            if v.startswith(f"{sid}:"): self._vis_scene_combo.set(v); break
        self._vis_stop_anim()
        self._vis_load_scene()

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
            self._vis_status.set(f"SC.GRP #{sid}: {sname} — 无实体 (空场景)")
            self._vis_canvas.configure(scrollregion=(0,0,MAX_MAP_W,MAX_MAP_H))
            return

        # 绘制实体
        for r in ents:
            self._vis_draw_entity(r)

        # 更新滚动区域
        xs = [r['d10'] for r in ents]; ys = [r['d11'] for r in ents]
        minx, maxx = min(xs)-50, max(xs)+50
        miny, maxy = min(ys)-50, max(ys)+50
        w = max(MAX_MAP_W, maxx - minx + 200)
        h = max(MAX_MAP_H, maxy - miny + 200)
        self._vis_canvas.configure(scrollregion=(0, 0, w, h))

        self._vis_status.set(f"SC.GRP #{sid}: {sname} — {len(ents)} 个实体")
        # 动画模式下启动帧循环
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
                    sprite = _jvg_sprite_to_tk(jvg, blk_idx, fi)
                    if sprite:
                        sx = x + blk.frames[fi].x_off; sy = y + blk.frames[fi].y_off

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
                sprite = _jvg_sprite_to_tk(jvg, bi, fi)
                if sprite:
                    sx = x + blk.frames[fi].x_off; sy = y + blk.frames[fi].y_off

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
        for r in self.records:
            if has_data(r) and r['d1'] == sid:
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
            self._vis_info.config(text=f"选中: #{found} [{tname}] 坐标({rec['d10']},{rec['d11']}) — 拖拽可移动")
            self._vis_drag = (found, cx, cy, rec['d10'], rec['d11'])
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

        self.records[eidx]['d10'] = new_x
        self.records[eidx]['d11'] = new_y
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
            self._vis_drag = (eidx, cx, cy, rec['d10'], rec['d11'])
            # 如果参数模式也打开了同一实体，同步显示
            if hasattr(self, '_current_param_idx') and self._current_param_idx == eidx:
                self._show_record(rec)

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
        # 加载 Ani.JVG / Cha.JVG
        self._ani_jvg = _get_jvg(os.path.join(d, "Ani.JVG"))
        self._cha_jvg = _get_jvg(os.path.join(d, "Cha.JVG"))
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
        # 填充可视化模式的场景列表
        self._vis_populate_scenes()

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children(): self._set_ws(c, en)
    def _set_ws(self, w, en):
        try:
            if isinstance(w,(ttk.Entry,ttk.Spinbox)): w.configure(state='normal' if en else 'disabled')
            elif isinstance(w,ttk.Combobox): w.configure(state='readonly' if en else 'disabled')
            elif isinstance(w,(ttk.Checkbutton,ttk.Radiobutton,ttk.Button)): w.state(['!disabled'] if en else ['disabled'])
        except: pass
        for c in w.winfo_children(): self._set_ws(c, en)
    def _on_tab_changed(self, event):
        tab = self.notebook.index(self.notebook.select())
        if tab != 1:  # 非可视化模式
            self._vis_stop_anim()

    def _on_close(self):
        self._vis_stop_anim()
        if self._dirty and not messagebox.askyesno("未保存","有未保存的修改, 确定退出?"): return
        self.root.destroy()
    def _update_path(self):
        G,R="#228B22","#CC3333"
        if not self.dat_path: self.lbl_path.config(text="(未加载)",foreground=R)
        elif not os.path.exists(self.dat_path): self.lbl_path.config(text=f"(不存在){self.dat_path}",foreground=R)
        else: self.lbl_path.config(text=self.dat_path,foreground=G)

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
        self._show_record(self.records[idx])

    def _show_record(self,rec):
        self._sync_lock=True
        idx=rec['index']; tval=rec['d0']; tname=ENTITY_TYPES.get(tval,f"未知({tval})")
        sname=scene_name(self.tkt_scenes,rec['d1'])
        self.lbl_title.config(text=f"实体 #{idx} [{tname}] {sname} ({rec['d10']},{rec['d11']})")
        for key,di,label,cmt in ALL_EDIT_FIELDS:
            val=rec[f'd{di}']
            if key=='type': self._edit_vars[key].set(f"{val}-{ENTITY_TYPES.get(val,'未知')}")
            elif key=='dir_mode': self._edit_vars[key].set(f"{val}-{DIR_MODES.get(val,'其他')}" if val in DIR_MODES else f"{val}-其他")
            else: self._edit_vars[key].set(str(val))
        for key,di,label,cmt in RUNTIME_FIELDS:
            if key in self._edit_vars: self._edit_vars[key].set(str(rec[f'd{di}']))
        if '_scene_label' in self._edit_vars: self._edit_vars['_scene_label'].config(text=sname)
        flags=rec['d2']
        self._bit_enable.set((flags&1)!=0)
        self._bit_visible.set((flags&2)!=0)
        self._bit_pickable.set((flags&4)!=0)
        self._bit_hint.set((flags&8)!=0)
        self._bit_busy.set((flags&0x10)!=0)
        self._bit_resume.set((flags&0x20)!=0)
        self._bit_animloop.set((flags&0x10000)!=0)
        self._sync_lock=False
    def _clear_form(self):
        self._sync_lock=True
        for key,var in self._edit_vars.items():
            if isinstance(var,tk.StringVar): var.set("")
            elif isinstance(var,ttk.Combobox): var.set("")
        if '_scene_label' in self._edit_vars: self._edit_vars['_scene_label'].config(text="")
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
        if not sel: return
        new_vals=self._read_form()
        if new_vals is None: messagebox.showwarning("输入错误","字段值必须是整数"); return
        idx=int(self.tree.item(sel[0],'values')[0])
        rec=self.records[idx]
        for key,val in new_vals.items(): rec[key]=val
        self._dirty=True; self._show_record(rec); self._apply_filter()
        # 如果可视化模式在看同一场景，重绘
        if rec['d1'] == self._vis_scene_id.get():
            for iid in self._vis_entities.get(idx, []): self._vis_canvas.delete(iid)
            self._vis_draw_entity(rec)
    def _reset_edit(self):
        sel=self.tree.selection()
        if not sel: return
        self._show_record(self.records[int(self.tree.item(sel[0],'values')[0])])

    # =========== 新增/复制/清空 ===========
    def _new_record(self):
        if not self.records: return
        empty_idx=None
        for rec in self.records:
            if is_empty(rec): empty_idx=rec['index']; break
        if empty_idx is None: messagebox.showinfo("无空槽",f"所有{REC_COUNT}条记录均已占用"); return
        rec=self.records[empty_idx]
        for di in range(DWORD_COUNT): rec[f'd{di}']=0
        rec['d0']=200; rec['d1']=-1
        self._dirty=True; self._apply_filter()
        for item in self.tree.get_children():
            if self.tree.item(item,'values')[0]==str(empty_idx): self.tree.selection_set(item); self.tree.see(item); self._show_record(rec); break
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
        if not self.dat_path: self._save_as(); return
        try: save_mat(self.dat_path,self.records); self._dirty=False; self.status_var.set("已保存")
        except Exception as e: messagebox.showerror("保存失败",str(e))
    def _save_as(self):
        fp=filedialog.asksaveasfilename(title="另存 TKMat.Dat",defaultextension=".Dat",filetypes=[("DAT 文件","*.Dat;*.dat"),("所有文件","*.*")])
        if not fp: return
        try: save_mat(fp,self.records); self.dat_path=fp; self._dirty=False; self._update_path(); self.status_var.set("已保存")
        except Exception as e: messagebox.showerror("保存失败",str(e))
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
             " [30-35]sub-scene [39-41]chain heads [42-43]PC [44]defunit_idx [53]dir_mode")
        messagebox.showinfo("字段说明",msg)
    def _show_about(self):
        messagebox.showinfo("关于","TKMat.Dat 地图实体编辑器 v2.0\n\n模式: 参数模式 + 可视化模式\n逆向依据: sub_412688, sub_405CBC\n格式: 6000条 × 384B = 2,304,000B")

# ============================================================
def main():
    root=tk.Tk(); app=MatEditor(root); root.mainloop()

if __name__=='__main__': main()
