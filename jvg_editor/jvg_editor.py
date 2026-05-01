#!/usr/bin/env python3
"""
JVG 图集编辑器 — 浏览和编辑三国群侠传 .jvg 格式精灵图集
=============================================================
格式依据: sub_453BD0 (JVG加载), sub_4544EC (RLE渲染)
用法: python jvg_editor.py [file.jvg]
"""

from __future__ import annotations
import os, sys, struct, io, json, zlib, math, tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from typing import List, Tuple, Optional

HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except ImportError:
    pass

JVG_MAGIC = b"@JVG"; JVM_MAGIC = b"@JVM"
SCREEN_W = 640; HEADER_SIZE = 32

# ── JVG 数据模型 ──────────────────────────────────────────
class PaletteRGB565:
    def __init__(self): self.entries: List[int] = [0] * 256
    def to_rgb888(self) -> bytes:
        r = bytearray(768)
        for i, e in enumerate(self.entries):
            r5, g6, b5 = (e>>11)&0x1F, (e>>5)&0x3F, e&0x1F
            r[i*3]=(r5<<3)|(r5>>2); r[i*3+1]=(g6<<2)|(g6>>4); r[i*3+2]=(b5<<3)|(b5>>2)
        return bytes(r)

class JVGFrame:
    def __init__(self):
        self.x_max=0; self.y_max=0; self.width=0; self.height=0
        self.row_count=0; self.pixels=b""; self.alpha=b""; self.encoded_data=b""
        self._palette: Optional[PaletteRGB565] = None  # per-frame palette for imports
    @property
    def x_off(self)->int: v=self.x_max; return (v-65536 if v>=32768 else v)-self.width+1
    @property
    def y_off(self)->int: v=self.y_max; return (v-65536 if v>=32768 else v)-self.height+1

class JVMBlock:
    def __init__(self, name:str=""):
        self.name=name; self.frames:List[JVGFrame]=[]; self.palette=PaletteRGB565()
    @property
    def frame_count(self)->int: return len(self.frames)

class JVGFile:
    def __init__(self): self.blocks:List[JVMBlock]=[]; self.filepath:Optional[str]=None
    @property
    def total_frames(self)->int: return sum(b.frame_count for b in self.blocks)
    @property
    def block_count(self)->int: return len(self.blocks)

# ── JVG 解码器 ─────────────────────────────────────────
def _u16s(v:int)->int: return v-65536 if v>=32768 else v

def _decode_rle(data:bytes, w:int, h:int)->Tuple[bytes,bytes]:
    total=w*h; out=bytearray(total); alpha=bytearray(total)
    recs=[]; pos=0
    while pos+4<=len(data):
        sk=struct.unpack("<H",data[pos:pos+2])[0]; rw=struct.unpack("<H",data[pos+2:pos+4])[0]; pos+=4
        px=data[pos:pos+min(rw,len(data)-pos)] if rw>0 else b""; pos+=len(px); recs.append((sk,rw,px))
    if not recs: return bytes(out),bytes(alpha)
    simple=(recs[0][0]==0 and recs[0][1]==w and all(r[1]==w for r in recs))
    if simple:
        for ri,(_,rw,px) in enumerate(recs):
            if ri>=h: break
            tr=h-1-ri
            for c in range(min(rw,len(px))): out[tr*w+c]=px[rw-1-c]; alpha[tr*w+c]=255
    else:
        gap=max(SCREEN_W-w,0); bp=total-1; pg=0
        for sa,rw,px in recs:
            rem=sa-pg; pg=0
            if rem<0: rem=0
            while rem>0 and bp>=0:
                col=(total-1-bp)%w; tb=w-col
                if rem<=tb: bp-=rem; rem=0
                else: bp-=tb; rem-=tb+gap; rem=max(rem,0)
            cb=(total-1-bp)%w if bp>=0 else 0
            al=min(rw,len(px))
            for k in range(al):
                if 0<=bp<total: out[bp]=px[k]; alpha[bp]=255
                bp-=1
            pg=gap if al>0 and cb+al>=w else 0
    return bytes(out),bytes(alpha)

def load_jvg(filepath:str)->JVGFile:
    data=Path(filepath).read_bytes()
    if len(data)<32 or data[:4]!=JVG_MAGIC: raise ValueError("不是有效的 @JVG 文件")
    jvg=JVGFile(); jvg.filepath=filepath
    bc=struct.unpack("<I",data[8:12])[0]; off=HEADER_SIZE
    for bi in range(bc):
        if off+32>len(data) or data[off:off+4]!=JVM_MAGIC: break
        sc=struct.unpack("<I",data[off+4:off+8])[0]; ds=struct.unpack("<I",data[off+12:off+16])[0]
        s1=off+32; co=[struct.unpack("<I",data[s1+j*4:s1+j*4+4])[0] for j in range(sc+1)]
        po=s1+(sc+1)*4; blk=JVMBlock(f"block_{bi:02d}")
        for j in range(256): blk.palette.entries[j]=struct.unpack("<H",data[po+j*2:po+j*2+2])[0]
        dr=po+512
        for si in range(sc):
            mo=dr+co[si]; ws=struct.unpack("<8H",data[mo:mo+16])
            f=JVGFrame(); f.x_max=ws[0]; f.y_max=ws[1]; f.width=ws[2]; f.height=ws[3]; f.row_count=ws[7]
            eo=mo+16; f.encoded_data=data[eo:eo+co[si+1]-co[si]-16]
            if f.width>0 and f.height>0: f.pixels,f.alpha=_decode_rle(f.encoded_data,f.width,f.height)
            blk.frames.append(f)
        off+=32+(sc+1)*4+512+ds; jvg.blocks.append(blk)
    return jvg

# ── JVG 编码器 ─────────────────────────────────────────
def _encode_rle_simple(px:bytes,w:int,h:int)->bytes:
    buf=bytearray()
    for row in range(h-1,-1,-1): d=px[row*w:(row+1)*w]; buf+=struct.pack("<HH",0,w)+d[::-1]
    return bytes(buf)

def _count_rle_pairs(data:bytes)->int:
    """统计 RLE (skip,run) 对数 — sub_4544EC.c L46: word_A5AECA = row_count"""
    if not data: return 0
    c=0; pos=0
    while pos+4<=len(data):
        _,rw=struct.unpack("<HH",data[pos:pos+4]); pos+=4+rw; c+=1
    return c

def save_jvg(jvg:JVGFile,filepath:str):
    """保存为原游戏兼容格式 (sub_453BD0 加载器兼容)

    关键: @JVG data_size = sum of @JVM data_size (仅帧像素数据, 不含JVM头/Stream1/调色板)
    """
    buf=bytearray()
    total_data_size=0  # sum of @JVM data_size only
    buf+=JVG_MAGIC
    buf+=struct.pack("<I",len(jvg.blocks))            # version
    buf+=struct.pack("<I",len(jvg.blocks))            # block_count
    buf+=struct.pack("<I",0)                           # total_data_size placeholder
    buf+=struct.pack("<I",jvg.total_frames)           # total sub-images
    buf+=bytes(12)

    for blk in jvg.blocks:
        n=blk.frame_count
        buf+=JVM_MAGIC
        buf+=struct.pack("<I",n)
        buf+=struct.pack("<I",0)                       # reserved
        dsp=len(buf)
        buf+=struct.pack("<I",0)                       # data_size placeholder
        buf+=bytes(16)

        # Encode frames
        fd=bytearray(); co=[0]
        for f in blk.frames:
            meta=struct.pack("<8H",f.x_max&0xFFFF,f.y_max&0xFFFF,f.width,f.height,0,0,0,0)
            fd+=meta
            if f.encoded_data:
                enc=f.encoded_data
                rc=_count_rle_pairs(enc)
                struct.pack_into("<H",fd,len(fd)-2,rc)
            elif f.pixels and f.width>0 and f.height>0:
                enc=_encode_rle_simple(f.pixels,f.width,f.height)
                struct.pack_into("<H",fd,len(fd)-2,f.height)
            else:
                enc=b""
            fd+=enc
            co.append(co[-1]+16+len(enc))

        block_data_size=co[-1]  # = sum of (16+encoded_len) per frame
        total_data_size+=block_data_size

        # Stream1 (N+1 cumulative offsets)
        for off in co: buf+=struct.pack("<I",off)
        # Palette (256 × RGB565)
        for e in blk.palette.entries: buf+=struct.pack("<H",e&0xFFFF)
        # Frame data
        buf+=fd
        # Fix up @JVM data_size
        struct.pack_into("<I",buf,dsp,block_data_size)

    # Fix up @JVG total_data_size = sum of @JVM data_size only (NOT including headers)
    struct.pack_into("<I",buf,12,total_data_size)
    Path(filepath).write_bytes(bytes(buf))

# ── 图像导入 (PIL量化) ───────────────────────────────
def _pil_frame(img:'Image.Image')->JVGFrame:
    """PIL 量化 — 使用 PIL convert('P',palette=ADAPTIVE) 快速生成索引像素"""
    if img.mode!='RGBA': img=img.convert('RGBA')
    w,h=img.size; frame=JVGFrame(); frame.width=w; frame.height=h
    # Extract alpha mask
    a_band=img.getchannel('A')
    alpha_data=a_band.tobytes()
    frame.alpha=bytes(255 if b>=128 else 0 for b in alpha_data)
    # Create opaque RGB image (set transparent pixels to black)
    bg=Image.new('RGB',(w,h),(0,0,0))
    rgb=Image.composite(img.convert('RGB'),bg,img.getchannel('A').point(lambda x:255 if x>=128 else 0))
    # Quantize RGB to 255 colors (reserve index 0)
    solid=sum(1 for b in alpha_data if b>=128)
    n_colors=min(255,max(1,solid)) if solid>0 else 1
    q=rgb.quantize(n_colors,method=Image.Quantize.MEDIANCUT)
    # Build palette (index 0 = black/transparent, indices 1..n from quantize)
    raw_pal=q.getpalette() or [0]*768
    frame._palette=PaletteRGB565()
    pal_rgb=[]
    for i in range(256):
        r,g,b=raw_pal[i*3] if i*3+2<len(raw_pal) else 0, \
              raw_pal[i*3+1] if i*3+1<len(raw_pal) else 0, \
              raw_pal[i*3+2] if i*3+2<len(raw_pal) else 0
        pal_rgb.append((r,g,b))
        frame._palette.entries[i]=((r>>3)<<11)|((g>>2)<<5)|(b>>3)
    # Get indexed pixels; force transparent pixels to index 0
    idx_data=bytearray(q.tobytes())
    for i in range(w*h):
        if frame.alpha[i]==0: idx_data[i]=0
    frame.pixels=bytes(idx_data)
    frame.x_max=(w-1 if w-1<32768 else w-1-65536)
    frame.y_max=(h-1 if h-1<32768 else h-1-65536)
    return frame

def import_images(paths:List[str])->List[JVGFrame]:
    frames=[]
    for p in sorted(paths,key=lambda p:Path(p).name.lower()):
        try:
            img=Image.open(p); frames.append(_pil_frame(img))
        except Exception as e: print(f"  skip {Path(p).name}: {e}")
    return frames

# ── 导出 ──────────────────────────────────────────────
def _rgba_png(w:int,h:int,rgba:bytearray)->bytes:
    def ch(ct,d): c=ct+d; return struct.pack(">I",len(d))+c+struct.pack(">I",zlib.crc32(c)&0xFFFFFFFF)
    png=b"\x89PNG\r\n\x1a\n"; png+=ch(b"IHDR",struct.pack(">IIBBBBB",w,h,8,6,0,0,0))
    raw=bytearray()
    for row in range(h): raw.append(0); raw.extend(rgba[row*w*4:(row+1)*w*4])
    png+=ch(b"IDAT",zlib.compress(bytes(raw),9)); png+=ch(b"IEND",b""); return png

def frame_to_rgba(f:JVGFrame,pal:PaletteRGB565)->bytearray:
    pr=pal.to_rgb888(); w,h=f.width,f.height; rgba=bytearray(w*h*4)
    for y in range(h):
        for x in range(w):
            p=y*w+x; off=p*4
            a=f.alpha[p] if p<len(f.alpha) else 0
            if a==0: continue
            idx=f.pixels[p] if p<len(f.pixels) else 0
            rgba[off]=pr[idx*3]; rgba[off+1]=pr[idx*3+1]; rgba[off+2]=pr[idx*3+2]; rgba[off+3]=255
    return rgba

def export_single(f:JVGFrame,pal:PaletteRGB565,path:str):
    rgba=frame_to_rgba(f,pal); Path(path).write_bytes(_rgba_png(f.width,f.height,rgba))

def export_group(blk:JVMBlock,outdir:str,prefix:str="frame"):
    os.makedirs(outdir,exist_ok=True)
    for fi,f in enumerate(blk.frames):
        export_single(f,blk.palette,os.path.join(outdir,f"{prefix}_{fi:03d}.png"))

def export_gridsheet(blk:JVMBlock,outdir:str,padding:int=1,columns:int=0):
    """按游戏虚拟坐标导出 gridsheet — 所有帧同cell大小,偏移位置完美还原"""
    frames=[f for f in blk.frames if f.width>0 and f.height>0]
    if not frames: return
    n=len(frames)
    # 虚拟矩形
    vrs=[]
    for f in frames:
        xm=_u16s(f.x_max); ym=_u16s(f.y_max)
        vl=xm-f.width+1; vt=ym-f.height+1; vrs.append((vl,vt,xm,ym))
    min_vl=min(r[0] for r in vrs); max_vr=max(r[2] for r in vrs)
    min_vt=min(r[1] for r in vrs); max_vb=max(r[3] for r in vrs)
    cw=max_vr-min_vl+1; ch=max_vb-min_vt+1
    cols=columns if columns>0 else max(1,int(math.ceil(math.sqrt(n))))
    rows=math.ceil(n/cols)
    aw=cols*cw+(cols-1)*padding; ah=rows*ch+(rows-1)*padding
    atlas=bytearray(aw*ah*4)
    for fi,f in enumerate(frames):
        ri=fi//cols; ci=fi%cols; cx=ci*(cw+padding); cy=ri*(ch+padding)
        vl,vt,_,_=vrs[fi]; ox=vl-min_vl; oy=vt-min_vt
        pr=blk.palette.to_rgb888()
        for py in range(f.height):
            for px in range(f.width):
                p=py*f.width+px
                if p<len(f.alpha) and f.alpha[p]==0: continue
                idx=f.pixels[p] if p<len(f.pixels) else 0
                dx,dy=cx+ox+px,cy+oy+py
                if 0<=dx<aw and 0<=dy<ah:
                    off=(dy*aw+dx)*4; atlas[off]=pr[idx*3]; atlas[off+1]=pr[idx*3+1]; atlas[off+2]=pr[idx*3+2]; atlas[off+3]=255
    os.makedirs(outdir,exist_ok=True)
    name=f"grid_b{blk.name.replace(' ','_')}.png" if blk.name else "gridsheet.png"
    Path(os.path.join(outdir,name)).write_bytes(_rgba_png(aw,ah,atlas))
    print(f"  Gridsheet: {name} ({aw}x{ah}, {cols}x{rows}, cell {cw}x{ch})")

# ── GUI 编辑器 ──────────────────────────────────────────
class JVGEditor:
    def __init__(self,root:tk.Tk,filepath:Optional[str]=None):
        self.root=root; self.root.title("JVG 图集编辑器"); self.root.geometry("1280x800")
        self.jvg:Optional[JVGFile]=None; self._bi=-1; self._fi=0; self._sel_fi=-1
        self._view="tile"; self._tile_cols=tk.IntVar(value=0); self._anim_job=None
        self._photos={}; self._detail_imgs={}
        self._setup_menu(); self._setup_ui()
        if filepath and os.path.exists(filepath): self._open(filepath)
        else: self._new()
        self.root.protocol("WM_DELETE_WINDOW",self._on_close)

    def _setup_menu(self):
        mb=tk.Menu(self.root)
        fm=tk.Menu(mb,tearoff=0)
        fm.add_command(label="新建 Ctrl+N",command=self._new)
        fm.add_command(label="打开 Ctrl+O",command=self._open_dlg)
        fm.add_command(label="保存 Ctrl+S",command=self._save)
        fm.add_command(label="另存为...",command=self._save_as)
        fm.add_separator()
        em=tk.Menu(fm,tearoff=0)
        em.add_command(label="导出当前帧为PNG",command=lambda:self._export("single"))
        em.add_command(label="导出当前分组(逐帧PNG)",command=lambda:self._export("group"))
        em.add_command(label="导出当前分组(Gridsheet)",command=lambda:self._export("grid"))
        fm.add_cascade(label="导出",menu=em)
        fm.add_separator()
        fm.add_command(label="退出",command=self._on_close)
        mb.add_cascade(label="文件",menu=fm)
        vm=tk.Menu(mb,tearoff=0)
        vm.add_command(label="平铺",command=lambda:self._set_view("tile"))
        vm.add_command(label="逐帧",command=lambda:self._set_view("single"))
        vm.add_command(label="动画",command=lambda:self._set_view("anim"))
        mb.add_cascade(label="视图",menu=vm)
        self.root.config(menu=mb)
        self.root.bind("<Control-n>",lambda e:self._new())
        self.root.bind("<Control-o>",lambda e:self._open_dlg())
        self.root.bind("<Control-s>",lambda e:self._save())
        self.root.bind("<Left>",lambda e:self._nav(-1))
        self.root.bind("<Right>",lambda e:self._nav(1))

    def _setup_ui(self):
        # Main layout
        self.pw=ttk.PanedWindow(self.root,orient=tk.HORIZONTAL); self.pw.pack(fill=tk.BOTH,expand=True)

        # ── LEFT panel ──────────────────────────────
        lf=ttk.Frame(self.pw,width=240); self.pw.add(lf,weight=0)
        hdr=ttk.Frame(lf); hdr.pack(fill=tk.X,padx=4,pady=(4,2))
        ttk.Label(hdr,text="分组列表",font=("",10,"bold")).pack(side=tk.LEFT)
        ttk.Button(hdr,text="+",width=3,command=self._add_block).pack(side=tk.RIGHT,padx=1)
        ttk.Button(hdr,text="-",width=3,command=self._del_block).pack(side=tk.RIGHT,padx=1)

        self._blist=tk.Listbox(lf,exportselection=False,font=("",9))
        self._blist.pack(fill=tk.BOTH,expand=True,padx=4,pady=2)
        self._blist.bind("<<ListboxSelect>>",self._on_block_sel)

        bf=ttk.LabelFrame(lf,text="图片操作",padding=4); bf.pack(fill=tk.X,padx=4,pady=4)
        ttk.Button(bf,text="添加图片",command=self._add_images).pack(fill=tk.X,pady=2)
        ttk.Button(bf,text="删除选中",command=self._del_frame).pack(fill=tk.X,pady=2)

        ef=ttk.LabelFrame(lf,text="导出",padding=4); ef.pack(fill=tk.X,padx=4,pady=4)
        ttk.Button(ef,text="当前帧PNG",command=lambda:self._export("single")).pack(fill=tk.X,pady=1)
        ttk.Button(ef,text="分组序列PNG",command=lambda:self._export("group")).pack(fill=tk.X,pady=1)
        ttk.Button(ef,text="分组Gridsheet",command=lambda:self._export("grid")).pack(fill=tk.X,pady=1)

        # ── RIGHT panel ──────────────────────────────
        self._rp=ttk.PanedWindow(self.pw,orient=tk.VERTICAL); self.pw.add(self._rp,weight=1)

        # Toolbar
        tb=ttk.Frame(self._rp); self._rp.add(tb,weight=0)
        ttk.Button(tb,text="平铺",command=lambda:self._set_view("tile")).pack(side=tk.LEFT,padx=2)
        ttk.Button(tb,text="逐帧",command=lambda:self._set_view("single")).pack(side=tk.LEFT,padx=2)
        ttk.Button(tb,text="动画",command=lambda:self._set_view("anim")).pack(side=tk.LEFT,padx=2)
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=4,pady=2)
        ttk.Label(tb,text="列数:").pack(side=tk.LEFT)
        self._tile_cols=tk.IntVar(value=0)
        ttk.Spinbox(tb,textvariable=self._tile_cols,width=4,from_=0,to=32,
                    command=lambda:self._refresh_view()).pack(side=tk.LEFT,padx=2)
        ttk.Label(tb,text=" gap:").pack(side=tk.LEFT)
        self._padding=tk.IntVar(value=1)
        ttk.Spinbox(tb,textvariable=self._padding,width=3,from_=0,to=16,
                    command=lambda:self._refresh_view()).pack(side=tk.LEFT,padx=2)
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=4,pady=2)
        ttk.Label(tb,text="速度:").pack(side=tk.LEFT)
        self._speed=tk.IntVar(value=120)
        ttk.Scale(tb,from_=30,to=500,variable=self._speed,orient=tk.HORIZONTAL,length=100).pack(side=tk.LEFT,padx=2)
        ttk.Label(tb,textvariable=self._speed).pack(side=tk.LEFT)
        self._info=ttk.Label(tb,text=""); self._info.pack(side=tk.RIGHT,padx=8)

        # Canvas area
        cf=ttk.Frame(self._rp); self._rp.add(cf,weight=1)
        self._canvas=tk.Canvas(cf,bg="#1e1e1e",highlightthickness=0)
        vsb=ttk.Scrollbar(cf,orient=tk.VERTICAL,command=self._canvas.yview)
        hsb=ttk.Scrollbar(cf,orient=tk.HORIZONTAL,command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vsb.set,xscrollcommand=hsb.set)
        self._canvas.grid(row=0,column=0,sticky="nsew"); vsb.grid(row=0,column=1,sticky="ns")
        hsb.grid(row=1,column=0,sticky="ew"); cf.grid_rowconfigure(0,weight=1); cf.grid_columnconfigure(0,weight=1)
        self._canvas.bind("<Configure>",lambda e:self._refresh_view())
        self._canvas.bind("<MouseWheel>",lambda e:self._canvas.yview_scroll(-e.delta//120,"units"))

        # Detail panel at bottom
        self._detail=tk.Text(self._rp,height=4,state=tk.DISABLED,font=("Consolas",9),
                             bg="#252525",fg="#ccc",wrap=tk.NONE,padx=6,pady=4)
        self._rp.add(self._detail,weight=0)

    # ── File ops ───────────────────────────────────
    def _new(self): self.jvg=JVGFile(); self._sync_list(); self._bi=-1; self._fi=0; self._sel_fi=-1; self._refresh_view(); self.root.title("JVG编辑器 — [新建]")
    def _open_dlg(self):
        p=filedialog.askopenfilename(title="打开 JVG",filetypes=[("JVG","*.jvg *.JVG"),("All","*.*")])
        if p: self._open(p)
    def _open(self,p:str):
        try: self.jvg=load_jvg(p); self._sync_list()
        except Exception as e: messagebox.showerror("打开失败",str(e)); return
        if self.jvg.blocks: self._blist.selection_set(0); self._bi=0
        self._fi=0; self._sel_fi=-1; self._refresh_view(); self.root.title(f"JVG编辑器 — {os.path.basename(p)}")
    def _save(self):
        if not self.jvg: return
        if self.jvg.filepath: self._do_save(self.jvg.filepath)
        else: self._save_as()
    def _save_as(self):
        p=filedialog.asksaveasfilename(title="保存 JVG",defaultextension=".jvg",filetypes=[("JVG","*.jvg")])
        if p: self._do_save(p)
    def _do_save(self,p:str):
        try: save_jvg(self.jvg,p); self.jvg.filepath=p; self.root.title(f"JVG编辑器 — {os.path.basename(p)}")
        except Exception as e: messagebox.showerror("保存失败",str(e))
    def _on_close(self): self._kill_anim(); self.root.destroy()

    # ── Block mgmt ──────────────────────────────────
    def _sync_list(self):
        sel=self._blist.curselection(); prev_idx=sel[0] if sel else self._bi
        self._blist.delete(0,tk.END)
        if not self.jvg: return
        for i,b in enumerate(self.jvg.blocks): self._blist.insert(tk.END,f"[{i}] {b.name} ({b.frame_count}f)")
        if self.jvg.blocks:
            new_idx=min(prev_idx,len(self.jvg.blocks)-1)
            self._blist.selection_set(new_idx); self._bi=new_idx

    def _on_block_sel(self,ev=None):
        sel=self._blist.curselection()
        if sel: self._bi=sel[0]; self._fi=0; self._sel_fi=-1; self._kill_anim(); self._refresh_view()

    def _add_block(self):
        if not self.jvg: self.jvg=JVGFile()
        name=simpledialog.askstring("新增","分组名称:",parent=self.root) or f"block_{len(self.jvg.blocks):02d}"
        self.jvg.blocks.append(JVMBlock(name)); self._sync_list()
        self._blist.selection_clear(0,tk.END); idx=len(self.jvg.blocks)-1
        self._blist.selection_set(idx); self._bi=idx; self._refresh_view()

    def _del_block(self):
        if not self.jvg or self._bi<0: return
        if messagebox.askyesno("确认",f"删除 [{self._bi}]?"):
            del self.jvg.blocks[self._bi]; self._bi=min(self._bi,len(self.jvg.blocks)-1)
            self._sync_list(); self._refresh_view()

    # ── Frame mgmt ───────────────────────────────────
    def _add_images(self):
        if not self.jvg or self._bi<0: return messagebox.showinfo("提示","请先选择分组")
        paths=filedialog.askopenfilenames(title="选择图片",filetypes=[("图片","*.png *.bmp *.jpg *.jpeg")])
        if not paths: return
        self._info.config(text="正在导入..."); self.root.update()
        frames=import_images(list(paths))
        if frames:
            blk=self.jvg.blocks[self._bi]; blk.frames.extend(frames)
            self._sync_list(); self._refresh_view()
            self._info.config(text=f"导入 {len(frames)} 帧")

    def _del_frame(self):
        if not self.jvg or self._bi<0: return
        blk=self.jvg.blocks[self._bi]
        if self._sel_fi>=0 and self._sel_fi<blk.frame_count:
            del blk.frames[self._sel_fi]
            self._sel_fi=-1; self._sync_list(); self._kill_anim(); self._refresh_view()

    def _nav(self,d:int):
        if self._view!="single": return
        if not self.jvg or self._bi<0: return
        blk=self.jvg.blocks[self._bi]; self._fi=(self._fi+d)%max(1,blk.frame_count)
        self._sel_fi=self._fi; self._refresh_view()

    # ── Views ────────────────────────────────────────
    def _set_view(self,mode:str): self._view=mode; self._kill_anim(); self._refresh_view()

    def _get_pal(self,blk:JVMBlock,f:JVGFrame)->PaletteRGB565:
        return f._palette if f._palette else blk.palette

    def _f2tk(self,f:JVGFrame,pal:PaletteRGB565,scale:float=1.0)->Optional[ImageTk.PhotoImage]:
        w,h=f.width,f.height
        if w<=0 or h<=0: return None
        pr=pal.to_rgb888(); rgba=bytearray(w*h*4)
        for y in range(h):
            for x in range(w):
                p=y*w+x; off=p*4
                if p<len(f.alpha) and f.alpha[p]==0: continue
                idx=f.pixels[p] if p<len(f.pixels) else 0
                rgba[off]=pr[idx*3]; rgba[off+1]=pr[idx*3+1]; rgba[off+2]=pr[idx*3+2]; rgba[off+3]=255
        img=Image.frombytes('RGBA',(w,h),bytes(rgba))
        if scale!=1.0: img=img.resize((max(1,int(w*scale)),max(1,int(h*scale))),Image.NEAREST)
        return ImageTk.PhotoImage(img)

    def _show_detail(self,f:JVGFrame,blk:JVMBlock,fi:int):
        self._detail.config(state=tk.NORMAL); self._detail.delete(1.0,tk.END)
        pal=self._get_pal(blk,f); is_import=f._palette is not None
        self._detail.insert(tk.END,
            f"Frame #{fi} │ {f.width}×{f.height} │ x_off={f.x_off} y_off={f.y_off} │ "
            f"pixels={len(f.pixels)}B │ enc={len(f.encoded_data)}B │ "
            f"{'[导入]' if is_import else '[原始]'}")
        self._detail.config(state=tk.DISABLED)

    def _refresh_view(self):
        self._canvas.delete("all"); self._photos.clear()
        if not self.jvg or self._bi<0 or self._bi>=len(self.jvg.blocks): return
        blk=self.jvg.blocks[self._bi]; frames=blk.frames
        if not frames: self._canvas.create_text(200,100,text="(空)",fill="#666",font=("",14)); return

        if self._view=="tile": self._render_tile(frames,blk)
        elif self._view=="single": self._render_single(frames,blk)
        elif self._view=="anim": self._start_anim(frames,blk)

    def _render_tile(self,frames,blk):
        cols=self._tile_cols.get()
        if cols<=0:
            cw=self._canvas.winfo_width()
            # estimate: need at least 80px per frame
            cols=max(1,(cw-10)//80)
        x,y,rh=10,10,0; col=0; fw=max(32,80 if cols<=4 else 64)
        for fi,f in enumerate(frames):
            if f.width<=0: continue
            pal=self._get_pal(blk,f); scale=fw/max(f.width,f.height)
            img=self._f2tk(f,pal,scale)
            if not img: continue
            self._photos[fi]=img
            tid=self._canvas.create_image(x,y,anchor=tk.NW,image=img,tags=("frame",str(fi)))
            self._canvas.tag_bind(tid,"<Button-1>",lambda e,i=fi:self._on_frame_click(i))
            # highlight selected frame
            if fi==self._sel_fi:
                dw,dh=int(f.width*scale),int(f.height*scale)
                self._canvas.create_rectangle(x,y,x+dw,y+dh,outline="#0f0",width=2,tags=("sel",))
            # frame number
            self._canvas.create_text(x+2,y+2,text=str(fi),fill="#0f0",font=("",7),anchor=tk.NW)
            x+=fw+4; rh=max(rh,int(f.height*scale)); col+=1
            if col>=cols: x=10; y+=rh+8; rh=0; col=0
        y+=rh+20
        self._canvas.configure(scrollregion=(0,0,max(600,cols*(fw+4)+20),y))
        self._info.config(text=f"平铺 — {len(frames)}帧, 列数={cols}")

    def _render_single(self,frames,blk):
        if self._fi>=len(frames): self._fi=0
        f=frames[self._fi]; pal=self._get_pal(blk,f)
        cw=self._canvas.winfo_width(); ch=self._canvas.winfo_height()
        scale=min(1.0,(cw-80)/max(f.width,1),(ch-80)/max(f.height,1))
        img=self._f2tk(f,pal,scale)
        if img: self._photos[0]=img; self._canvas.create_image(cw//2,ch//2,anchor=tk.CENTER,image=img)
        self._canvas.create_text(40,20,text="◀",fill="#4af",font=("",14),tags=("nav",)); self._canvas.tag_bind("nav","<Button-1>",lambda e:self._nav(-1))
        self._canvas.create_text(cw-40,20,text="▶",fill="#4af",font=("",14),tags=("nav2",)); self._canvas.tag_bind("nav2","<Button-1>",lambda e:self._nav(1))
        self._canvas.configure(scrollregion=(0,0,cw,ch))
        self._sel_fi=self._fi; self._info.config(text=f"逐帧 — {self._fi+1}/{len(frames)} ({f.width}×{f.height})")
        self._show_detail(f,blk,self._fi)

    def _on_frame_click(self,fi:int):
        self._sel_fi=fi
        if not self.jvg or self._bi<0: return
        blk=self.jvg.blocks[self._bi]
        if fi<blk.frame_count:
            self._show_detail(blk.frames[fi],blk,fi)
        self._refresh_view()

    def _start_anim(self,frames,blk):
        """按游戏原始偏移量渲染动画 — 每帧按照 x_off/y_off 定位"""
        n=len(frames)
        # 计算虚拟坐标union bounding box (与gridsheet逻辑一致)
        vrs=[]
        for f in frames:
            if f.width<=0: vrs.append((0,0,0,0)); continue
            xm=_u16s(f.x_max); ym=_u16s(f.y_max)
            vrs.append((xm-f.width+1,ym-f.height+1,xm,ym))
        min_vl=min(r[0] for r in vrs); min_vt=min(r[1] for r in vrs)
        max_vr=max(r[2] for r in vrs); max_vb=max(r[3] for r in vrs)
        cell_w=max_vr-min_vl+1; cell_h=max_vb-min_vt+1
        # 缩放
        cw=self._canvas.winfo_width(); ch=self._canvas.winfo_height()
        scale=min(1.0,(cw-40)/max(cell_w,1),(ch-40)/max(cell_h,1))
        scw=int(cell_w*scale); sch=int(cell_h*scale)
        cx=(cw-scw)//2; cy=(ch-sch)//2
        # 预渲染所有帧
        self._anim_data=[]
        for fi,f in enumerate(frames):
            if f.width<=0: self._anim_data.append(None); continue
            pal=self._get_pal(blk,f); pr=pal.to_rgb888()
            ox=(_u16s(f.x_max)-f.width+1-min_vl); oy=(_u16s(f.y_max)-f.height+1-min_vt)
            rgba=bytearray(scw*sch*4)
            for py in range(f.height):
                for px in range(f.width):
                    p=py*f.width+px
                    if p<len(f.alpha) and f.alpha[p]==0: continue
                    idx=f.pixels[p] if p<len(f.pixels) else 0
                    dx=int((ox+px)*scale); dy=int((oy+py)*scale)
                    if 0<=dx<scw and 0<=dy<sch:
                        off=(dy*scw+dx)*4; rgba[off]=pr[idx*3]; rgba[off+1]=pr[idx*3+1]; rgba[off+2]=pr[idx*3+2]; rgba[off+3]=255
            pil=Image.frombytes('RGBA',(scw,sch),bytes(rgba))
            self._anim_data.append(ImageTk.PhotoImage(pil))
        self._anim_idx=0; self._anim_cx=cx; self._anim_cy=cy
        if self._anim_data: self._anim_next()

    def _anim_next(self):
        if self._view!="anim" or not hasattr(self,'_anim_data') or not self._anim_data: return
        n=len(self._anim_data); fi=self._anim_idx%n
        img=self._anim_data[fi]
        if img:
            self._photos['_a']=img
            self._canvas.delete("all")
            self._canvas.create_image(self._anim_cx,self._anim_cy,anchor=tk.NW,image=img)
            self._canvas.create_text(self._canvas.winfo_width()//2,self._canvas.winfo_height()-10,
                                     text=f"{fi+1}/{n}",fill="#888",font=("",9))
        self._anim_idx+=1
        self._anim_job=self.root.after(max(30,self._speed.get()),self._anim_next)
        self._info.config(text=f"动画 — {n}帧")

    def _kill_anim(self):
        if self._anim_job: self.root.after_cancel(self._anim_job); self._anim_job=None
        self._anim_data=[]

    # ── Export ────────────────────────────────────────
    def _export(self,mode:str):
        if not self.jvg or self._bi<0: return
        blk=self.jvg.blocks[self._bi]
        if mode=="single":
            if self._sel_fi<0 or self._sel_fi>=blk.frame_count:
                messagebox.showinfo("提示","请先在平铺视图中点击选中一帧")
                return
            p=filedialog.asksaveasfilename(title="导出帧",defaultextension=".png",filetypes=[("PNG","*.png")])
            if not p: return
            f=blk.frames[self._sel_fi]; pal=self._get_pal(blk,f)
            export_single(f,pal,p); self._info.config(text=f"已导出 {Path(p).name}")
        elif mode=="group":
            d=filedialog.askdirectory(title="选择导出目录")
            if not d: return
            export_group(blk,d)
            self._info.config(text=f"已导出 {blk.frame_count} 帧到 {d}")
        elif mode=="grid":
            d=filedialog.askdirectory(title="选择导出目录")
            if not d: return
            export_gridsheet(blk,d,padding=self._padding.get(),columns=self._tile_cols.get())
            self._info.config(text=f"已导出 gridsheet (padding={self._padding.get()}) 到 {d}")

# ── Entry ──────────────────────────────────────────
def main():
    root=tk.Tk(); fp=sys.argv[1] if len(sys.argv)>1 else None
    app=JVGEditor(root,fp); root.mainloop()

if __name__=="__main__":
    if not HAS_PIL: print("需要 Pillow: pip install Pillow"); sys.exit(1)
    main()
