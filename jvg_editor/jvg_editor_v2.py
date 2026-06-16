#!/usr/bin/env python3
"""
JVG 图集编辑器 v2 — PySide6 版本，支持深色/浅色主题切换
========================================================
格式依据: sub_453BD0 (JVG加载), sub_4544EC (RLE渲染)
用法: python jvg_editor_v2.py [file.jvg]
"""

from __future__ import annotations
import os, sys, struct, io, json, zlib, math
from pathlib import Path
from typing import List, Tuple, Optional
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSpinBox, QCheckBox, QFileDialog,
    QMessageBox, QInputDialog, QScrollArea, QFrame, QSplitter,
    QMenuBar, QMenu, QStatusBar, QToolBar, QGroupBox, QSizePolicy,
    QListWidget, QListWidgetItem, QAbstractItemView, QDialog,
    QDialogButtonBox, QFormLayout, QLineEdit, QTextEdit,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsRectItem
)
from PySide6.QtCore import Qt, QTimer, QSize, Signal
from PySide6.QtGui import QPixmap, QImage, QColor, QPalette, QIcon, QAction, QPainter, QFont, QMouseEvent, QPen, QBrush

HAS_PIL = False
try:
    from PIL import Image, ImageDraw
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
        self.row_count=0; self._pixels:Optional[bytes]=None; self._alpha:Optional[bytes]=None
        self.encoded_data=b""
        self._palette: Optional[PaletteRGB565] = None

    @property
    def pixels(self)->bytes:
        if self._pixels is None and self.encoded_data and self.width>0 and self.height>0:
            self._pixels,self._alpha=_decode_rle(self.encoded_data,self.width,self.height)
        return self._pixels if self._pixels is not None else b""

    @pixels.setter
    def pixels(self,val:bytes): self._pixels=val

    @property
    def alpha(self)->bytes:
        if self._alpha is None and self.encoded_data and self.width>0 and self.height>0:
            self._pixels,self._alpha=_decode_rle(self.encoded_data,self.width,self.height)
        return self._alpha if self._alpha is not None else b""

    @alpha.setter
    def alpha(self,val:bytes): self._alpha=val

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
            blk.frames.append(f)
        off+=32+(sc+1)*4+512+ds; jvg.blocks.append(blk)
    return jvg

# ── JVG 编码器 ─────────────────────────────────────────
def _encode_rle_game(pixels:bytes,alpha:bytes,w:int,h:int,screen_w:int=SCREEN_W)->Tuple[bytes,int]:
    buf=bytearray(); pair_count=0
    pending=0; first=True
    for row in range(h-1,-1,-1):
        if not first: pending+=screen_w-w
        first=False; col=w-1
        while col>=0:
            t0=col
            while col>=0 and alpha[row*w+col]==0: col-=1
            pending+=t0-col
            if col<0: break
            while pending>0xFFFF:
                buf+=struct.pack("<HH",0xFFFF,0); pair_count+=1; pending-=0xFFFF
            run=bytearray()
            while col>=0 and alpha[row*w+col]!=0 and len(run)<0xFFFF:
                run.append(pixels[row*w+col]); col-=1
            buf+=struct.pack("<HH",pending,len(run)); buf+=bytes(run)
            pair_count+=1; pending=0
    return bytes(buf),pair_count

def _count_rle_pairs(data:bytes)->int:
    if not data: return 0
    c=0; pos=0
    while pos+4<=len(data):
        _,rw=struct.unpack("<HH",data[pos:pos+4]); pos+=4+rw; c+=1
    return c

def save_jvg(jvg:JVGFile,filepath:str):
    buf=bytearray()
    total_data_size=0
    buf+=JVG_MAGIC
    buf+=struct.pack("<I",len(jvg.blocks))
    buf+=struct.pack("<I",len(jvg.blocks))
    buf+=struct.pack("<I",0)
    buf+=struct.pack("<I",jvg.total_frames)
    buf+=bytes(12)

    for blk in jvg.blocks:
        n=blk.frame_count
        buf+=JVM_MAGIC
        buf+=struct.pack("<I",n)
        buf+=struct.pack("<I",0)
        dsp=len(buf)
        buf+=struct.pack("<I",0)
        buf+=bytes(16)

        fd=bytearray(); co=[0]
        for f in blk.frames:
            meta=struct.pack("<8H",f.x_max&0xFFFF,f.y_max&0xFFFF,f.width,f.height,0,0,0,0)
            fd+=meta
            if f.encoded_data:
                enc=f.encoded_data
                rc=_count_rle_pairs(enc)
                struct.pack_into("<H",fd,len(fd)-2,rc)
            elif f.pixels and f.width>0 and f.height>0:
                alpha=f.alpha if f.alpha and len(f.alpha)==f.width*f.height else bytes([255]*(f.width*f.height))
                enc,rc=_encode_rle_game(f.pixels,alpha,f.width,f.height)
                struct.pack_into("<H",fd,len(fd)-2,rc)
            else:
                enc=b""
            fd+=enc
            co.append(co[-1]+16+len(enc))

        block_data_size=co[-1]
        total_data_size+=block_data_size

        for off in co: buf+=struct.pack("<I",off)
        for e in blk.palette.entries: buf+=struct.pack("<H",e&0xFFFF)
        buf+=fd
        struct.pack_into("<I",buf,dsp,block_data_size)

    struct.pack_into("<I",buf,12,total_data_size)
    Path(filepath).write_bytes(bytes(buf))

# ── 图像导入 (PIL量化) ───────────────────────────────
def _pil_frame(img:'Image.Image')->JVGFrame:
    if img.mode!='RGBA': img=img.convert('RGBA')
    w,h=img.size; frame=JVGFrame(); frame.width=w; frame.height=h
    a_band=img.getchannel('A')
    alpha_data=a_band.tobytes()
    frame.alpha=bytes(255 if b>=128 else 0 for b in alpha_data)
    bg=Image.new('RGB',(w,h),(0,0,0))
    rgb=Image.composite(img.convert('RGB'),bg,img.getchannel('A').point(lambda x:255 if x>=128 else 0))
    solid=sum(1 for b in alpha_data if b>=128)
    n_colors=min(255,max(1,solid)) if solid>0 else 1
    q=rgb.quantize(n_colors,method=Image.Quantize.MEDIANCUT)
    raw_pal=q.getpalette() or [0]*768
    frame._palette=PaletteRGB565()
    pal_rgb=[]
    for i in range(256):
        r,g,b=raw_pal[i*3] if i*3+2<len(raw_pal) else 0, \
              raw_pal[i*3+1] if i*3+1<len(raw_pal) else 0, \
              raw_pal[i*3+2] if i*3+2<len(raw_pal) else 0
        pal_rgb.append((r,g,b))
        frame._palette.entries[i]=((r>>3)<<11)|((g>>2)<<5)|(b>>3)
    idx_data=bytearray(q.tobytes())
    for i in range(w*h):
        if frame.alpha[i]==0: idx_data[i]=0
    frame.pixels=bytes(idx_data)
    frame.x_max=(w-1 if w-1<32768 else w-1-65536)
    frame.y_max=(h-1 if h-1<32768 else h-1-65536)
    return frame

def _remap_to_block_palette(f:JVGFrame,blk:JVMBlock):
    if not f._palette or not f.pixels: return
    used_by_original=set()
    for of in blk.frames:
        if of is f: continue
        if of.pixels:
            for b in of.pixels: used_by_original.add(b)
    f_colors=[None]*256
    for i in range(256):
        e=f._palette.entries[i]; f_colors[i]=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
    available=[i for i in range(1,256) if i not in used_by_original]
    used=set(f.pixels)
    remap=[0]*256
    for fi in sorted(used):
        if fi>=256 or f_colors[fi] is None or f._palette.entries[fi]==0: continue
        fc=f_colors[fi]; exact=None
        for bi in range(256):
            e=blk.palette.entries[bi]; bc=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
            if fc==bc and (bi not in used_by_original or bi==fi): exact=bi; break
        if exact is not None: remap[fi]=exact; continue
        if available:
            slot=available.pop(0)
            blk.palette.entries[slot]=f._palette.entries[fi]
            remap[fi]=slot
        else:
            best,best_dist=0,999999
            for bi in range(256):
                e=blk.palette.entries[bi]; bc=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
                d=abs(fc[0]-bc[0])+abs(fc[1]-bc[1])+abs(fc[2]-bc[2])
                if d<best_dist: best,best_dist=bi,d
            remap[fi]=best
    for fi in range(256):
        if fi not in used: remap[fi]=0
    px=bytearray(f.pixels)
    for i in range(len(px)):
        if px[i]<256: px[i]=remap[px[i]]
    f.pixels=bytes(px)
    if f.width>0 and f.height>0:
        alpha=f.alpha if f.alpha and len(f.alpha)==f.width*f.height else bytes([255]*(f.width*f.height))
        f.encoded_data,f.row_count=_encode_rle_game(f.pixels,alpha,f.width,f.height)
    f._palette=None

def _batch_quantize_subs_to_block(subs:List['Image.Image'],blk:'JVMBlock',
                                   keep_frame_indices:List[int])->List['JVGFrame']:
    if not subs: return []
    used_by_kept={0}
    for ki in keep_frame_indices:
        if 0<=ki<len(blk.frames):
            kf=blk.frames[ki]
            if kf.pixels:
                for b in kf.pixels: used_by_kept.add(b)
    available=[i for i in range(256) if i not in used_by_kept]
    n_avail=len(available)
    rgb_bytes=bytearray()
    for s in subs:
        if s.mode!='RGBA': s_rgba=s.convert('RGBA')
        else: s_rgba=s
        a=s_rgba.getchannel('A').tobytes()
        rgb=s_rgba.convert('RGB').tobytes()
        for i,av in enumerate(a):
            if av>=128:
                rgb_bytes+=rgb[i*3:i*3+3]
    n_px=len(rgb_bytes)//3
    MAX_PX=1_000_000
    if n_px>MAX_PX:
        step=(n_px+MAX_PX-1)//MAX_PX
        sampled=bytearray()
        for i in range(0,n_px,step):
            sampled+=rgb_bytes[i*3:i*3+3]
        rgb_bytes=sampled; n_px=len(rgb_bytes)//3
    pal_img=None; n_colors=0
    if n_px>0 and n_avail>0:
        strip=Image.frombytes('RGB',(n_px,1),bytes(rgb_bytes))
        n_colors=min(n_avail,255)
        pal_img=strip.quantize(colors=n_colors,method=Image.Quantize.MEDIANCUT)
    slot_map=[]
    if pal_img is not None:
        raw_pal=pal_img.getpalette() or [0]*768
        for pi in range(n_colors):
            r=raw_pal[pi*3] if pi*3+2<len(raw_pal) else 0
            g=raw_pal[pi*3+1] if pi*3+1<len(raw_pal) else 0
            b=raw_pal[pi*3+2] if pi*3+2<len(raw_pal) else 0
            blk_slot=available[pi]
            blk.palette.entries[blk_slot]=((r>>3)<<11)|((g>>2)<<5)|(b>>3)
            slot_map.append(blk_slot)
    results=[]
    for s in subs:
        if s.mode!='RGBA': s_rgba=s.convert('RGBA')
        else: s_rgba=s
        w,h=s_rgba.size
        a_data=s_rgba.getchannel('A').tobytes()
        alpha=bytes(255 if av>=128 else 0 for av in a_data)
        if pal_img is not None:
            rgb=s_rgba.convert('RGB')
            q=rgb.quantize(palette=pal_img,dither=0)
            idx_data=q.tobytes()
            pixels=bytearray(w*h)
            for i in range(w*h):
                if alpha[i]==0:
                    pixels[i]=0
                else:
                    pi=idx_data[i] if i<len(idx_data) else 0
                    pixels[i]=slot_map[pi] if pi<len(slot_map) else 0
        else:
            pixels=bytearray(w*h)
        frame=JVGFrame(); frame.width=w; frame.height=h
        frame.alpha=alpha; frame.pixels=bytes(pixels)
        frame.encoded_data,frame.row_count=_encode_rle_game(frame.pixels,frame.alpha,w,h)
        frame.x_max=(w-1 if w-1<32768 else w-1-65536)
        frame.y_max=(h-1 if h-1<32768 else h-1-65536)
        frame._palette=None
        results.append(frame)
    return results

def _align_anchor(new_f:JVGFrame,old_f:JVGFrame,mode:str="bottom_center")->None:
    if old_f.width<=0 or old_f.height<=0: return
    if new_f.width<=0 or new_f.height<=0: return
    old_xm=_u16s(old_f.x_max); old_ym=_u16s(old_f.y_max)
    old_x_off=old_xm-old_f.width+1; old_y_off=old_ym-old_f.height+1
    if mode=="bottom_center":
        old_cx=old_xm-(old_f.width-1)/2.0
        new_x_off=int(round(old_cx-(new_f.width-1)/2.0))
        new_f.x_max=(new_x_off+new_f.width-1)&0xFFFF
        new_f.y_max=old_ym&0xFFFF
    elif mode=="center":
        old_cx=old_xm-(old_f.width-1)/2.0; old_cy=old_ym-(old_f.height-1)/2.0
        new_x_off=int(round(old_cx-(new_f.width-1)/2.0))
        new_y_off=int(round(old_cy-(new_f.height-1)/2.0))
        new_f.x_max=(new_x_off+new_f.width-1)&0xFFFF
        new_f.y_max=(new_y_off+new_f.height-1)&0xFFFF
    else:
        new_f.x_max=(old_x_off+new_f.width-1)&0xFFFF
        new_f.y_max=(old_y_off+new_f.height-1)&0xFFFF

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

def frame_to_rgba(f:JVGFrame,pal:PaletteRGB565,greenscreen_set:Optional[set]=None)->bytearray:
    pr=pal.to_rgb888(); w,h=f.width,f.height; rgba=bytearray(w*h*4)
    for y in range(h):
        for x in range(w):
            p=y*w+x; off=p*4
            a=f.alpha[p] if p<len(f.alpha) else 0
            if a==0: continue
            idx=f.pixels[p] if p<len(f.pixels) else 0
            if greenscreen_set and idx in greenscreen_set: continue
            rgba[off]=pr[idx*3]; rgba[off+1]=pr[idx*3+1]; rgba[off+2]=pr[idx*3+2]; rgba[off+3]=255
    return rgba

def export_single(f:JVGFrame,pal:PaletteRGB565,path:str,greenscreen_set:Optional[set]=None):
    rgba=frame_to_rgba(f,pal,greenscreen_set); Path(path).write_bytes(_rgba_png(f.width,f.height,rgba))

def export_group(blk:JVMBlock,outdir:str,prefix:str="frame",greenscreen_set:Optional[set]=None):
    os.makedirs(outdir,exist_ok=True)
    for fi,f in enumerate(blk.frames):
        export_single(f,blk.palette,os.path.join(outdir,f"{prefix}_{fi:03d}.png"),greenscreen_set)

def export_gridsheet(blk:JVMBlock,outdir:str,padding:int=1,columns:int=0,greenscreen_set:Optional[set]=None):
    frames=[f for f in blk.frames if f.width>0 and f.height>0]
    if not frames: return
    n=len(frames)
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
                if greenscreen_set and idx in greenscreen_set: continue
                dx,dy=cx+ox+px,cy+oy+py
                if 0<=dx<aw and 0<=dy<ah:
                    off=(dy*aw+dx)*4; atlas[off]=pr[idx*3]; atlas[off+1]=pr[idx*3+1]; atlas[off+2]=pr[idx*3+2]; atlas[off+3]=255
    os.makedirs(outdir,exist_ok=True)
    name=f"grid_b{blk.name.replace(' ','_')}.png" if blk.name else "gridsheet.png"
    Path(os.path.join(outdir,name)).write_bytes(_rgba_png(aw,ah,atlas))
    print(f"  Gridsheet: {name} ({aw}x{ah}, {cols}x{rows}, cell {cw}x{ch})")

# ── 主题管理 ──────────────────────────────────────────
class ThemeManager:
    def __init__(self):
        self.themes_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'themes')
        self.current_theme = 'dark'
        self._dark_qss = ''
        self._light_qss = ''
        self._load_themes()

    def _load_themes(self):
        dark_path = os.path.join(self.themes_dir, 'dark.qss')
        light_path = os.path.join(self.themes_dir, 'light.qss')
        # SVG 图标的基础路径（绝对路径）
        svg_base = os.path.join(self.themes_dir, 'svg').replace('\\', '/')
        
        if os.path.exists(dark_path):
            with open(dark_path, 'r', encoding='utf-8') as f:
                qss = f.read()
                # 将相对路径替换为绝对路径
                qss = qss.replace('url(themes/svg/', f'url({svg_base}/')
                self._dark_qss = qss
        if os.path.exists(light_path):
            with open(light_path, 'r', encoding='utf-8') as f:
                qss = f.read()
                qss = qss.replace('url(themes/svg/', f'url({svg_base}/')
                self._light_qss = qss

    def get_stylesheet(self) -> str:
        return self._dark_qss if self.current_theme == 'dark' else self._light_qss

    def set_theme(self, theme: str):
        if theme in ('dark', 'light'):
            self.current_theme = theme

    def toggle_theme(self):
        self.current_theme = 'light' if self.current_theme == 'dark' else 'dark'

# ── GUI 组件 ──────────────────────────────────────────
class DockHeader(QFrame):
    """统一的面板标题头"""
    def __init__(self, title, right_layout=None):
        super().__init__()
        self.setObjectName("DockHeader")
        self.setFixedHeight(28)  # 固定高度，与 wardata_editor 一致
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("DockTitle")
        layout.addWidget(lbl, 1)
        if right_layout:
            layout.addLayout(right_layout)

class CanvasView(QGraphicsView):
    """可点击的画布视图，支持鼠标点击事件和滚轮缩放"""
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._editor = None
    
    def set_editor(self, editor):
        self._editor = editor
    
    def mousePressEvent(self, event: QMouseEvent):
        if self._editor and self._editor._view == "tile":
            # 处理平铺模式下的帧点击
            pos = self.mapToScene(event.position().toPoint())
            item = self.scene().itemAt(pos, self.transform())
            if item and isinstance(item, QGraphicsPixmapItem):
                fi = item.data(0)
                if fi is not None:
                    self._editor._on_frame_click(fi)
                    return
        super().mousePressEvent(event)
    
    def wheelEvent(self, event):
        if self._editor and event.modifiers() & Qt.ControlModifier:
            # Ctrl+滚轮缩放
            delta = event.angleDelta().y()
            if delta > 0:
                self._editor._zoom_step(0.5)
            elif delta < 0:
                self._editor._zoom_step(-0.5)
            event.accept()
        else:
            super().wheelEvent(event)

# ── GUI 编辑器 ──────────────────────────────────────────
class JVGEditor(QMainWindow):
    def __init__(self, filepath: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("JVG 图集编辑器 v2")
        self.resize(1280, 800)
        
        # 窗口居中显示
        screen = QApplication.primaryScreen()
        if screen:
            geo = self.frameGeometry()
            center = screen.availableGeometry().center()
            geo.moveCenter(center)
            self.move(geo.topLeft())
        
        # 加载图标
        ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))
        
        # 主题管理 - 参考tkt_editor_v5.py，根据系统主题自动检测
        self.theme_manager = ThemeManager()
        app_inst = QApplication.instance()
        if app_inst:
            self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark
            self.theme_manager.set_theme('dark' if self._is_dark else 'light')
        else:
            self._is_dark = True
        
        # 数据模型
        self.jvg: Optional[JVGFile] = None
        self._bi = -1
        self._fi = 0
        self._sel_fi = -1
        self._view = "tile"
        self._anim_job: Optional[QTimer] = None
        self._photos = {}
        
        # 创建UI
        self._setup_menu()
        self._setup_ui()
        
        # 应用主题
        self._apply_theme()
        
        # 打开文件
        if filepath and os.path.exists(filepath):
            self._open(filepath)
        else:
            self._new()

    def _create_dock(self, title, widget_content, header_layout=None):
        """创建统一的 dock 面板"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(DockHeader(title, header_layout))
        
        body = QWidget()
        body.setObjectName("DockBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 6, 6)
        body_layout.addWidget(widget_content)
        
        layout.addWidget(body, 1)
        return container

    def _apply_theme(self):
        stylesheet = self.theme_manager.get_stylesheet()
        self.setStyleSheet(stylesheet)
        # 更新画布背景色
        scene_bg = QColor(30, 30, 30) if self._is_dark else QColor(200, 204, 208)
        if hasattr(self, '_canvas'):
            self._canvas.setBackgroundBrush(scene_bg)

    def _setup_menu(self):
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        new_action = QAction("新建(&N)", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new)
        file_menu.addAction(new_action)
        
        open_action = QAction("打开(&O)", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_dlg)
        file_menu.addAction(open_action)
        
        save_action = QAction("保存(&S)", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("另存为(&A)...", self)
        save_as_action.triggered.connect(self._save_as)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        # 导出子菜单
        export_menu = file_menu.addMenu("导出(&E)")
        
        export_single_action = QAction("导出选中帧", self)
        export_single_action.triggered.connect(lambda: self._export("single"))
        export_menu.addAction(export_single_action)
        
        export_group_action = QAction("导出分组", self)
        export_group_action.triggered.connect(lambda: self._export("group"))
        export_menu.addAction(export_group_action)
        
        export_grid_action = QAction("导出图集", self)
        export_grid_action.triggered.connect(lambda: self._export("grid"))
        export_menu.addAction(export_grid_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")
        
        tile_action = QAction("平铺(&T)", self)
        tile_action.triggered.connect(lambda: self._set_view("tile"))
        view_menu.addAction(tile_action)
        
        single_action = QAction("逐帧(&S)", self)
        single_action.triggered.connect(lambda: self._set_view("single"))
        view_menu.addAction(single_action)
        
        anim_action = QAction("动画(&A)", self)
        anim_action.triggered.connect(lambda: self._set_view("anim"))
        view_menu.addAction(anim_action)
        
        view_menu.addSeparator()
        
        # 主题切换
        theme_menu = view_menu.addMenu("主题(&H)")
        
        dark_theme_action = QAction("深色主题", self)
        dark_theme_action.triggered.connect(lambda: self._switch_theme('dark'))
        theme_menu.addAction(dark_theme_action)
        
        light_theme_action = QAction("浅色主题", self)
        light_theme_action.triggered.connect(lambda: self._switch_theme('light'))
        theme_menu.addAction(light_theme_action)
        
        toggle_theme_action = QAction("切换主题", self)
        toggle_theme_action.setShortcut("Ctrl+T")
        toggle_theme_action.triggered.connect(self._toggle_theme)
        theme_menu.addAction(toggle_theme_action)

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # 主分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(7)
        main_layout.addWidget(splitter, 1)

        # ---------------- 左侧面板 ----------------
        left_panel = QWidget()
        left_panel.setFixedWidth(260)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 分组列表区块
        list_container = QWidget()
        lc_layout = QVBoxLayout(list_container)
        lc_layout.setContentsMargins(0, 0, 0, 0)
        list_header = QHBoxLayout()
        btn_add = QPushButton("➕")
        btn_add.setFixedWidth(36)
        btn_add.clicked.connect(self._add_block)
        btn_del = QPushButton("➖")
        btn_del.setFixedWidth(36)
        btn_del.clicked.connect(self._del_block)
        list_header.addStretch()
        list_header.addWidget(btn_add)
        list_header.addWidget(btn_del)
        
        self._blist = QListWidget()
        self._blist.currentRowChanged.connect(self._on_block_sel)
        lc_layout.addWidget(self._blist)
        left_layout.addWidget(self._create_dock("图集分组列表", list_container, header_layout=list_header), 1)
        
        # 操作与导出区域
        ops_container = QWidget()
        ops_layout = QVBoxLayout(ops_container)
        ops_layout.setContentsMargins(0, 0, 0, 0)
        
        # 帧操作组
        grp_ops = QGroupBox("帧操作")
        grp_ops_layout = QVBoxLayout(grp_ops)
        btn_add_img = QPushButton("➕ 添加图片")
        btn_add_img.clicked.connect(self._add_images)
        btn_rep_img = QPushButton("🔄 替换选中")
        btn_rep_img.clicked.connect(self._replace_frame)
        btn_bat_img = QPushButton("📦 导入图集 (切片)")
        btn_bat_img.clicked.connect(self._batch_replace_gridsheet)
        btn_del_img = QPushButton("❌ 删除选中")
        btn_del_img.clicked.connect(self._del_frame)
        grp_ops_layout.addWidget(btn_add_img)
        grp_ops_layout.addWidget(btn_rep_img)
        grp_ops_layout.addWidget(btn_bat_img)
        grp_ops_layout.addWidget(btn_del_img)
        ops_layout.addWidget(grp_ops)
        
        # 快速导出组
        grp_exp = QGroupBox("快速导出")
        grp_exp_layout = QVBoxLayout(grp_exp)
        btn_exp_single = QPushButton("📤 导出选中帧")
        btn_exp_single.clicked.connect(lambda: self._export("single"))
        btn_exp_grp = QPushButton("📁 导出当前分组")
        btn_exp_grp.clicked.connect(lambda: self._export("group"))
        btn_exp_grid = QPushButton("🗺️ 导出网格图集")
        btn_exp_grid.clicked.connect(lambda: self._export("grid"))
        grp_exp_layout.addWidget(btn_exp_single)
        grp_exp_layout.addWidget(btn_exp_grp)
        grp_exp_layout.addWidget(btn_exp_grid)
        ops_layout.addWidget(grp_exp)
        
        left_layout.addWidget(self._create_dock("工作流选项", ops_container))

        splitter.addWidget(left_panel)

        # ---------------- 右侧面板 ----------------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setHandleWidth(7)
        
        # 画布与视口工具栏
        canvas_container = QWidget()
        c_layout = QVBoxLayout(canvas_container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(4)
        
        # 工具栏放在画布上方
        tb_widget = QWidget()
        tb_layout = QHBoxLayout(tb_widget)
        tb_layout.setContentsMargins(4, 4, 4, 4)
        tb_layout.setSpacing(4)
        btn_tile = QPushButton("🖼️ 平铺")
        btn_tile.clicked.connect(lambda: self._set_view("tile"))
        btn_single = QPushButton("📷 逐帧")
        btn_single.clicked.connect(lambda: self._set_view("single"))
        btn_anim = QPushButton("🎬 动画")
        btn_anim.clicked.connect(lambda: self._set_view("anim"))
        tb_layout.addWidget(btn_tile)
        tb_layout.addWidget(btn_single)
        tb_layout.addWidget(btn_anim)
        tb_layout.addSpacing(10)
        
        tb_layout.addWidget(QLabel("列数:"))
        self._tile_cols = QSpinBox()
        self._tile_cols.setRange(0, 32)
        self._tile_cols.setValue(0)
        self._tile_cols.valueChanged.connect(lambda: self._refresh_view())
        tb_layout.addWidget(self._tile_cols)
        
        tb_layout.addWidget(QLabel("缝隙:"))
        self._padding = QSpinBox()
        self._padding.setRange(0, 16)
        self._padding.setValue(1)
        self._padding.valueChanged.connect(lambda: self._refresh_view())
        tb_layout.addWidget(self._padding)
        tb_layout.addSpacing(10)
        
        self._greenscreen_remove = QCheckBox("预览去绿幕")
        self._greenscreen_remove.setChecked(True)
        self._greenscreen_remove.stateChanged.connect(lambda: self._refresh_view())
        tb_layout.addWidget(self._greenscreen_remove)
        tb_layout.addSpacing(10)
        
        tb_layout.addWidget(QLabel("速度:"))
        self._speed = QSpinBox()
        self._speed.setRange(10, 2000)
        self._speed.setValue(120)
        self._speed.setSingleStep(10)
        tb_layout.addWidget(self._speed)
        tb_layout.addWidget(QLabel("ms"))
        tb_layout.addSpacing(10)
        
        btn_zout = QPushButton("➖")
        btn_zout.setFixedWidth(36)
        btn_zout.clicked.connect(lambda: self._zoom_step(-0.5))
        tb_layout.addWidget(btn_zout)
        
        self._zoom_label = QLabel("100%")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setFixedWidth(40)
        tb_layout.addWidget(self._zoom_label)
        
        btn_zin = QPushButton("➕")
        btn_zin.setFixedWidth(36)
        btn_zin.clicked.connect(lambda: self._zoom_step(0.5))
        tb_layout.addWidget(btn_zin)
        tb_layout.addSpacing(10)
        
        # 逐帧导航按钮
        btn_prev = QPushButton("◀ 上一帧")
        btn_prev.clicked.connect(lambda: self._nav(-1))
        btn_prev.setShortcut(Qt.Key_Left)
        tb_layout.addWidget(btn_prev)
        
        btn_next = QPushButton("下一帧 ▶")
        btn_next.clicked.connect(lambda: self._nav(1))
        btn_next.setShortcut(Qt.Key_Right)
        tb_layout.addWidget(btn_next)
        
        self._zoom = 1.0
        tb_layout.addStretch()
        
        # 切换主题按钮放在工具栏右侧
        btn_theme = QPushButton("🌗 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        tb_layout.addWidget(btn_theme)
        
        c_layout.addWidget(tb_widget)
        
        # 画布
        self._scene = QGraphicsScene()
        self._canvas = CanvasView(self._scene)
        self._canvas.set_editor(self)
        self._canvas.setBackgroundBrush(QColor(30, 30, 30))
        self._canvas.setRenderHint(QPainter.Antialiasing, False)
        self._canvas.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self._canvas.setDragMode(QGraphicsView.NoDrag)
        self._canvas.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._canvas.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        c_layout.addWidget(self._canvas, 1)

        right_splitter.addWidget(self._create_dock("2D 视口渲染器", canvas_container))

        # 详情日志区
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(100)
        self._detail.setStyleSheet("font-family: Consolas; font-size: 10pt;")
        right_splitter.addWidget(self._create_dock("图元结构校验日志", self._detail))
        
        right_layout.addWidget(right_splitter)
        splitter.addWidget(right_panel)
        
        # 设置分割器比例
        splitter.setSizes([260, 1020])
        right_splitter.setSizes([700, 150])
        
        # 信息标签
        self._info = QLabel("")
        self.statusBar().addPermanentWidget(self._info)
        self.statusBar().showMessage("引擎就绪")

    def _switch_theme(self, theme: str):
        self._is_dark = (theme == 'dark')
        self.theme_manager.set_theme(theme)
        self._apply_theme()
        self.statusBar().showMessage(f"已切换到{'深色' if theme == 'dark' else '浅色'}主题", 2000)

    def _toggle_theme(self):
        self.theme_manager.toggle_theme()
        self._is_dark = (self.theme_manager.current_theme == 'dark')
        self._apply_theme()
        theme_name = '深色' if self._is_dark else '浅色'
        self.statusBar().showMessage(f"已切换到{theme_name}主题", 2000)

    def _new(self):
        self.jvg = JVGFile()
        self._sync_list()
        self._bi = -1
        self._fi = 0
        self._sel_fi = -1
        self._refresh_view()
        self.setWindowTitle("JVG编辑器 v2 — [新建]")

    def _open_dlg(self):
        p, _ = QFileDialog.getOpenFileName(self, "打开 JVG", "", "JVG (*.jvg *.JVG);;All (*.*)")
        if p:
            self._open(p)

    def _open(self, p: str):
        try:
            self.jvg = load_jvg(p)
            self._sync_list()
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e))
            return
        if self.jvg.blocks:
            self._blist.setCurrentRow(0)
            self._bi = 0
        self._fi = 0
        self._sel_fi = -1
        self._refresh_view()
        self.setWindowTitle(f"JVG编辑器 v2 — {os.path.basename(p)}")

    def _save(self):
        if not self.jvg:
            return
        if self.jvg.filepath:
            self._do_save(self.jvg.filepath)
        else:
            self._save_as()

    def _save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "保存 JVG", "", "JVG (*.jvg)")
        if p:
            self._do_save(p)

    def _do_save(self, p: str):
        try:
            save_jvg(self.jvg, p)
            self.jvg.filepath = p
            self.setWindowTitle(f"JVG编辑器 v2 — {os.path.basename(p)}")
            self.statusBar().showMessage(f"已保存: {os.path.basename(p)}", 2000)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _sync_list(self):
        current_row = self._blist.currentRow()
        self._blist.clear()
        if not self.jvg:
            return
        for i, b in enumerate(self.jvg.blocks):
            self._blist.addItem(f"[{i}] {b.name} ({b.frame_count}f)")
        if self.jvg.blocks:
            new_idx = min(current_row, len(self.jvg.blocks) - 1) if current_row >= 0 else 0
            self._blist.setCurrentRow(new_idx)
            self._bi = new_idx

    def _on_block_sel(self, row: int):
        if row >= 0:
            self._bi = row
            self._fi = 0
            self._sel_fi = -1
            self._kill_anim()
            self._refresh_view()

    def _add_block(self):
        if not self.jvg:
            self.jvg = JVGFile()
        name = f"block_{len(self.jvg.blocks):02d}"
        self.jvg.blocks.append(JVMBlock(name))
        self._sync_list()
        idx = len(self.jvg.blocks) - 1
        self._blist.setCurrentRow(idx)
        self._bi = idx
        self._refresh_view()

    def _del_block(self):
        if not self.jvg or self._bi < 0:
            return
        reply = QMessageBox.question(self, "确认", f"删除 [{self._bi}]?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            del self.jvg.blocks[self._bi]
            self._bi = min(self._bi, len(self.jvg.blocks) - 1)
            self._sync_list()
            self._refresh_view()

    def _add_images(self):
        if not self.jvg or self._bi < 0:
            QMessageBox.information(self, "提示", "请先选择分组")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "选择图片", "", "图片 (*.png *.bmp *.jpg *.jpeg)")
        if not paths:
            return
        self._info.setText("正在导入...")
        QApplication.processEvents()
        frames = import_images(list(paths))
        if frames:
            blk = self.jvg.blocks[self._bi]
            for f in frames:
                if f._palette:
                    _remap_to_block_palette(f, blk)
            blk.frames.extend(frames)
            self._sync_list()
            self._refresh_view()
            self._info.setText(f"导入 {len(frames)} 帧")

    def _replace_frame(self):
        if not self.jvg or self._bi < 0 or self._sel_fi < 0:
            QMessageBox.information(self, "提示", "请先在平铺视图中点击选中一帧")
            return
        blk = self.jvg.blocks[self._bi]
        if self._sel_fi >= blk.frame_count:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "选择替换图片", "", "图片 (*.png *.bmp *.jpg *.jpeg)")
        if not paths:
            return
        frames = import_images([paths[0]])
        if frames:
            new_f = frames[0]
            old_f = blk.frames[self._sel_fi]
            _align_anchor(new_f, old_f, mode="bottom_center")
            if new_f._palette:
                _remap_to_block_palette(new_f, blk)
            blk.frames[self._sel_fi] = new_f
            self._sync_list()
            self._kill_anim()
            self._refresh_view()
            self._info.setText(f"已替换帧 #{self._sel_fi} (偏移已自动对齐)")

    def _del_frame(self):
        if not self.jvg or self._bi < 0:
            return
        blk = self.jvg.blocks[self._bi]
        if 0 <= self._sel_fi < blk.frame_count:
            del blk.frames[self._sel_fi]
            self._sel_fi = -1
            self._sync_list()
            self._kill_anim()
            self._refresh_view()

    def _pick_reference_block(self) -> Optional[int]:
        blocks = [(i, blk) for i, blk in enumerate(self.jvg.blocks)
                  if blk.frame_count > 0 and i != self._bi]
        if not blocks:
            QMessageBox.information(self, "无参考分组", "当前 JVG 中没有其他有帧的分组可作为参考。")
            return None

        dlg = QDialog(self)
        dlg.setWindowTitle("选择参考分组 (用于恢复offset)")
        dlg.setModal(True)
        
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("空分组导入需要参考分组的 offset。\n请选择导出该图集的源分组:"))
        
        list_widget = QListWidget()
        for bi, blk in blocks:
            list_widget.addItem(f"[{bi:3d}] {blk.name} ({blk.frame_count}f)")
        list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dlg.accept)
        button_box.rejected.connect(dlg.reject)
        layout.addWidget(button_box)
        
        if dlg.exec() == QDialog.Accepted and list_widget.currentRow() >= 0:
            return blocks[list_widget.currentRow()][0]
        return None

    def _batch_replace_gridsheet(self):
        if not self.jvg or self._bi < 0:
            QMessageBox.information(self, "提示", "请先选择分组")
            return
        blk = self.jvg.blocks[self._bi]
        valid_list = [(i, f) for i, f in enumerate(blk.frames) if f.width > 0 and f.height > 0]
        n_valid = len(valid_list)
        is_new_block = (n_valid == 0)

        path, _ = QFileDialog.getOpenFileName(self, "选择 Gridsheet 图片", "", "图片 (*.png *.bmp *.jpg *.jpeg)")
        if not path:
            return
        try:
            gs = Image.open(path).convert('RGBA')
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e))
            return

        gs_w, gs_h = gs.size
        cur_cols = self._tile_cols.value() if self._tile_cols.value() > 0 else max(1, int(math.ceil(math.sqrt(max(n_valid, 1)))))
        
        cols, ok = QInputDialog.getInt(self, "导入组图", f"columns (共 {n_valid} 帧):", cur_cols, 1, 256)
        if not ok:
            return
        
        cur_rows = max(1, int(math.ceil(max(n_valid, 1) / cols)))
        rows, ok = QInputDialog.getInt(self, "导入组图", f"rows (共 {n_valid} 帧, cols={cols}):", cur_rows, 1, 256)
        if not ok:
            return
        
        cur_pad = max(0, self._padding.value())
        pad, ok = QInputDialog.getInt(self, "导入组图", "padding / gap (像素):", cur_pad, 0, 256)
        if not ok:
            return

        if not is_new_block and cols * rows < n_valid:
            reply = QMessageBox.question(self, "容量不足",
                f"cols×rows = {cols}×{rows} = {cols * rows} < 有效帧数 {n_valid}\n"
                f"后 {n_valid - cols * rows} 帧将不会被替换。是否继续?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        cw_num = gs_w - max(0, cols - 1) * pad
        ch_num = gs_h - max(0, rows - 1) * pad
        if cw_num <= 0 or ch_num <= 0 or cw_num % cols != 0 or ch_num % rows != 0:
            QMessageBox.critical(self, "尺寸错误",
                f"图片尺寸 {gs_w}×{gs_h} 无法整除为 {cols}×{rows} 个 cell (pad={pad})\n"
                f"cw_num={cw_num}, ch_num={ch_num}\n请确认 columns / rows / padding 参数")
            return
        cw = cw_num // cols
        ch = ch_num // rows

        auto_min_vl = -((cw - 1) // 2)

        ref_frames = None
        if is_new_block:
            ref_bi = self._pick_reference_block()
            if ref_bi is not None:
                ref_blk = self.jvg.blocks[ref_bi]
                ref_valid = [(i, f) for i, f in enumerate(ref_blk.frames) if f.width > 0 and f.height > 0]
                ref_frames = ref_valid
                if len(ref_valid) > cols * rows:
                    reply = QMessageBox.question(self, "帧数不匹配",
                        f"参考分组有 {len(ref_valid)} 帧, 但 grid 只有 {cols * rows} 个 cell。\n"
                        f"多余 cell 将按自动计算 offset。是否继续?",
                        QMessageBox.Yes | QMessageBox.No)
                    if reply != QMessageBox.Yes:
                        return
        else:
            ref_frames = valid_list

        self._info.setText(f"导入组图: 裁剪 cell...")
        QApplication.processEvents()

        subs = []
        metas = []
        replace_set = set()
        max_cells = cols * rows
        skipped = 0

        if is_new_block:
            for cell_idx in range(max_cells):
                ri = cell_idx // cols
                ci = cell_idx % cols
                cx = ci * (cw + pad)
                cy = ri * (ch + pad)
                if cx + cw > gs_w or cy + ch > gs_h:
                    skipped += 1
                    continue
                cell = gs.crop((cx, cy, cx + cw, cy + ch))
                bbox = cell.getchannel('A').getbbox()
                if bbox is None:
                    skipped += 1
                    continue
                l, t, r, b = bbox
                sub = cell.crop((l, t, r, b))
                new_x_max = (auto_min_vl + r - 1) & 0xFFFF
                subs.append(sub)
                metas.append((new_x_max, 0, b))
        else:
            for cell_idx, (blk_fi, old_f) in enumerate(valid_list):
                if cell_idx >= max_cells:
                    skipped += 1
                    continue
                ri = cell_idx // cols
                ci = cell_idx % cols
                cx = ci * (cw + pad)
                cy = ri * (ch + pad)
                if cx + cw > gs_w or cy + ch > gs_h:
                    skipped += 1
                    continue
                cell = gs.crop((cx, cy, cx + cw, cy + ch))
                bbox = cell.getchannel('A').getbbox()
                if bbox is None:
                    skipped += 1
                    continue
                l, t, r, b = bbox
                sub = cell.crop((l, t, r, b))
                old_xm = _u16s(old_f.x_max)
                old_ym = _u16s(old_f.y_max)
                old_vl = old_xm - old_f.width + 1
                old_vt = old_ym - old_f.height + 1
                new_x_max = (old_vl - l + r - 1) & 0xFFFF
                new_y_max = (old_vt - t + b - 1) & 0xFFFF
                subs.append(sub)
                metas.append((blk_fi, new_x_max, new_y_max))
                replace_set.add(blk_fi)

        if is_new_block and metas:
            auto_min_vt = -max(m[2] for m in metas)
            metas = [(m[0], (auto_min_vt + m[2] - 1) & 0xFFFF) for m in metas]

        self._info.setText(f"导入组图: 统一量化 {len(subs)} 帧...")
        QApplication.processEvents()

        keep_indices = [i for i in range(len(blk.frames)) if i not in replace_set]
        new_frames = _batch_quantize_subs_to_block(subs, blk, keep_indices)

        if is_new_block:
            for (xm, ym), nf in zip(metas, new_frames):
                nf.x_max = xm
                nf.y_max = ym
                blk.frames.append(nf)
            if ref_frames:
                for cell_idx, (_, ref_f) in enumerate(ref_frames):
                    if cell_idx >= len(blk.frames):
                        break
                    _align_anchor(blk.frames[cell_idx], ref_f, mode="bottom_center")
        else:
            for (blk_fi, xm, ym), nf in zip(metas, new_frames):
                nf.x_max = xm
                nf.y_max = ym
                _align_anchor(nf, blk.frames[blk_fi], mode="bottom_center")
                blk.frames[blk_fi] = nf

        self._sync_list()
        self._kill_anim()
        self._refresh_view()
        self._info.setText(f"导入组图完成: {'新增' if is_new_block else '替换'} {len(new_frames)} 帧, 跳过 {skipped} 空cell (cell={cw}×{ch})")

    def _zoom_step(self, delta: float):
        self._zoom = max(1.0, min(3.0, self._zoom + delta))
        self._zoom_label.setText(f"{int(self._zoom * 100)}%")
        self._kill_anim()
        self._refresh_view()

    def _set_view(self, mode: str):
        self._view = mode
        self._kill_anim()
        self._refresh_view()

    def _get_pal(self, blk: JVMBlock, f: JVGFrame) -> PaletteRGB565:
        return f._palette if f._palette else blk.palette

    def _f2qpixmap(self, f: JVGFrame, pal: PaletteRGB565, scale: float = 1.0) -> Optional[QPixmap]:
        w, h = f.width, f.height
        if w <= 0 or h <= 0:
            return None
        no_green = self._greenscreen_remove.isChecked()
        if no_green:
            green_set = {i for i, e in enumerate(pal.entries) if e == 0x07E0}
        pr = pal.to_rgb888()
        
        # 生成原始尺寸的 pixmap，缩放由 QGraphicsPixmapItem.setScale 处理
        rgba = bytearray(w * h * 4)
        for y in range(h):
            for x in range(w):
                p = y * w + x
                off = p * 4
                if p < len(f.alpha) and f.alpha[p] == 0:
                    continue
                idx = f.pixels[p] if p < len(f.pixels) else 0
                if no_green and idx in green_set:
                    continue
                rgba[off] = pr[idx * 3]
                rgba[off + 1] = pr[idx * 3 + 1]
                rgba[off + 2] = pr[idx * 3 + 2]
                rgba[off + 3] = 255
        
        qimg = QImage(bytes(rgba), w, h, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg)

    def _show_detail(self, f: JVGFrame, blk: JVMBlock, fi: int):
        pal = self._get_pal(blk, f)
        is_import = f._palette is not None
        self._detail.setPlainText(
            f">> Frame [{fi}]\n"
            f"几何边界: {f.width}×{f.height} px\n"
            f"物理偏移: X={f.x_off}, Y={f.y_off} (锚定补偿)\n"
            f"数据载荷: Pixels={len(f.pixels)}B, Encoded={len(f.encoded_data)}B\n"
            f"来源状态: {'[临时外挂导入区]' if is_import else '[底层封存区]'}"
        )

    def _refresh_view(self):
        # 清除场景
        self._scene.clear()
        self._photos.clear()
        if not self.jvg or self._bi < 0 or self._bi >= len(self.jvg.blocks):
            return
        blk = self.jvg.blocks[self._bi]
        frames = blk.frames
        if not frames:
            text = self._scene.addText("(空)", QFont("Microsoft YaHei", 14))
            text.setDefaultTextColor(QColor(102, 102, 102))
            return

        if self._view == "tile":
            self._render_tile(frames, blk)
        elif self._view == "single":
            self._render_single(frames, blk)
        elif self._view == "anim":
            self._start_anim(frames, blk)

    def _render_tile(self, frames, blk):
        cols = self._tile_cols.value()
        z = self._zoom
        if cols <= 0:
            # 自动计算列数
            max_w = max((f.width for f in frames if f.width > 0), default=64)
            view_w = self._canvas.viewport().width()
            cols = max(1, int((view_w - 10) / (max_w * z + 6)))

        x, y, rh = 10, 10, 0
        col = 0
        for fi, f in enumerate(frames):
            if f.width <= 0:
                continue
            pal = self._get_pal(blk, f)
            # 缓存原始尺寸的 pixmap
            pixmap = self._f2qpixmap(f, pal, 1.0)
            if not pixmap:
                continue
            self._photos[fi] = pixmap
            dw, dh = int(f.width * z), int(f.height * z)
            
            # 添加图像到场景，使用 setScale 进行缩放
            item = QGraphicsPixmapItem(pixmap)
            item.setPos(x, y)
            item.setScale(z)
            item.setData(0, fi)  # 存储帧索引
            self._scene.addItem(item)
            
            # 添加帧号文字
            text = self._scene.addText(str(fi), QFont("Consolas", 7))
            text.setPos(x + 2, y + 2)
            text.setDefaultTextColor(QColor(0, 255, 0))
            
            # 选中框
            if fi == self._sel_fi:
                pen = QColor(0, 255, 0)
                rect = self._scene.addRect(x, y, dw, dh, pen)
            
            x += dw + 4
            rh = max(rh, dh)
            col += 1
            if col >= cols:
                x = 10
                y += rh + 8
                rh = 0
                col = 0

        # 设置场景范围
        self._scene.setSceneRect(0, 0, max(600, x + 20), y + rh + 20)
        self._canvas.centerOn(0, 0)  # 滚动到左上角
        self._info.setText(f"平铺 — {len(frames)}帧, 列数={cols}, {int(z * 100)}%")

    def _render_single(self, frames, blk):
        if self._fi >= len(frames):
            self._fi = 0
        f = frames[self._fi]
        pal = self._get_pal(blk, f)
        
        view_w = self._canvas.viewport().width()
        view_h = self._canvas.viewport().height()
        
        # 计算自适应缩放（与原版一致）
        fit_scale = min(1.0, (view_w - 80) / max(f.width, 1), (view_h - 80) / max(f.height, 1))
        # 获取原始尺寸的 pixmap
        pixmap = self._f2qpixmap(f, pal, 1.0)
        
        if pixmap:
            self._photos[0] = pixmap
            total_scale = fit_scale * self._zoom
            pw = f.width * total_scale
            ph = f.height * total_scale
            # 居中显示（与原版 anchor=tk.CENTER 一致）
            x = (view_w - pw) / 2
            y = (view_h - ph) / 2
            item = QGraphicsPixmapItem(pixmap)
            item.setPos(x, y)
            item.setScale(total_scale)
            self._scene.addItem(item)
        
        self._sel_fi = self._fi
        self._scene.setSceneRect(0, 0, view_w, view_h)
        self._info.setText(f"逐帧 — {self._fi + 1}/{len(frames)} ({f.width}×{f.height})")
        self._show_detail(f, blk, self._fi)

    def _on_frame_click(self, fi: int):
        self._sel_fi = fi
        if not self.jvg or self._bi < 0:
            return
        blk = self.jvg.blocks[self._bi]
        if fi < blk.frame_count:
            self._show_detail(blk.frames[fi], blk, fi)
        self._refresh_view()

    def _nav(self, d: int):
        """逐帧导航"""
        if self._view != "single":
            return
        if not self.jvg or self._bi < 0:
            return
        blk = self.jvg.blocks[self._bi]
        self._fi = (self._fi + d) % max(1, blk.frame_count)
        self._sel_fi = self._fi
        self._refresh_view()

    def _start_anim(self, frames, blk):
        n = len(frames)
        vrs = []
        for f in frames:
            if f.width <= 0:
                vrs.append((0, 0, 0, 0))
                continue
            xm = _u16s(f.x_max)
            ym = _u16s(f.y_max)
            vrs.append((xm - f.width + 1, ym - f.height + 1, xm, ym))
        
        min_vl = min(r[0] for r in vrs)
        min_vt = min(r[1] for r in vrs)
        max_vr = max(r[2] for r in vrs)
        max_vb = max(r[3] for r in vrs)
        cell_w = max_vr - min_vl + 1
        cell_h = max_vb - min_vt + 1
        
        view_w = self._canvas.viewport().width()
        view_h = self._canvas.viewport().height()
        base_scale = min(1.0, (view_w - 40) / max(cell_w, 1), (view_h - 40) / max(cell_h, 1))
        scale = base_scale * self._zoom  # 应用用户缩放
        scw = int(cell_w * scale)
        sch = int(cell_h * scale)
        cx = (view_w - scw) // 2
        cy = (view_h - sch) // 2
        
        self._anim_data = []
        self._anim_cx = cx
        self._anim_cy = cy
        no_green = self._greenscreen_remove.isChecked()
        
        for fi, f in enumerate(frames):
            if f.width <= 0:
                self._anim_data.append(None)
                continue
            pal = self._get_pal(blk, f)
            pr = pal.to_rgb888()
            if no_green:
                green_set = {i for i, e in enumerate(pal.entries) if e == 0x07E0}
            ox = _u16s(f.x_max) - f.width + 1 - min_vl
            oy = _u16s(f.y_max) - f.height + 1 - min_vt
            rgba = bytearray(scw * sch * 4)
            
            # 对每个目标像素，找到对应的原图像素（最近邻插值）
            for dy in range(sch):
                for dx in range(scw):
                    # 计算原图坐标
                    px = int(dx / scale) - ox
                    py = int(dy / scale) - oy
                    if px < 0 or px >= f.width or py < 0 or py >= f.height:
                        continue
                    p = py * f.width + px
                    if p < len(f.alpha) and f.alpha[p] == 0:
                        continue
                    idx = f.pixels[p] if p < len(f.pixels) else 0
                    if no_green and idx in green_set:
                        continue
                    off = (dy * scw + dx) * 4
                    rgba[off] = pr[idx * 3]
                    rgba[off + 1] = pr[idx * 3 + 1]
                    rgba[off + 2] = pr[idx * 3 + 2]
                    rgba[off + 3] = 255
            
            qimg = QImage(bytes(rgba), scw, sch, QImage.Format_RGBA8888)
            self._anim_data.append(QPixmap.fromImage(qimg))
        
        self._anim_idx = 0
        if self._anim_data:
            self._anim_next()

    def _anim_next(self):
        if self._view != "anim" or not hasattr(self, '_anim_data') or not self._anim_data:
            return
        n = len(self._anim_data)
        fi = self._anim_idx % n
        pixmap = self._anim_data[fi]
        if pixmap:
            self._photos['_a'] = pixmap
            # 清除场景并添加当前帧
            self._scene.clear()
            item = QGraphicsPixmapItem(pixmap)
            item.setPos(self._anim_cx, self._anim_cy)
            self._scene.addItem(item)
            
            # 添加帧计数文字
            text = self._scene.addText(f"{fi + 1}/{n}", QFont("Microsoft YaHei", 9))
            text.setPos(self._canvas.viewport().width() // 2 - 20, self._canvas.viewport().height() - 20)
            text.setDefaultTextColor(QColor(136, 136, 136))
        
        self._anim_idx += 1
        if not self._anim_job:
            self._anim_job = QTimer()
            self._anim_job.timeout.connect(self._anim_next)
        self._anim_job.start(max(30, self._speed.value()))
        self._info.setText(f"动画 — {n}帧")

    def _kill_anim(self):
        if self._anim_job:
            self._anim_job.stop()
            self._anim_job = None
        self._anim_data = []

    def _export(self, mode: str):
        if not self.jvg or self._bi < 0:
            return
        blk = self.jvg.blocks[self._bi]
        gs = None
        if self._greenscreen_remove.isChecked():
            gs = {i for i, e in enumerate(blk.palette.entries) if e == 0x07E0}
        
        if mode == "single":
            if self._sel_fi < 0 or self._sel_fi >= blk.frame_count:
                QMessageBox.information(self, "提示", "请先在平铺视图中点击选中一帧")
                return
            p, _ = QFileDialog.getSaveFileName(self, "导出帧", "", "PNG (*.png)")
            if not p:
                return
            f = blk.frames[self._sel_fi]
            pal = self._get_pal(blk, f)
            export_single(f, pal, p, gs)
            self._info.setText(f"已导出 {Path(p).name}")
        elif mode == "group":
            d = QFileDialog.getExistingDirectory(self, "选择导出目录")
            if not d:
                return
            export_group(blk, d, greenscreen_set=gs)
            self._info.setText(f"已导出 {blk.frame_count} 帧到 {d}")
        elif mode == "grid":
            d = QFileDialog.getExistingDirectory(self, "选择导出目录")
            if not d:
                return
            export_gridsheet(blk, d, padding=self._padding.value(), 
                           columns=self._tile_cols.value(), greenscreen_set=gs)
            self._info.setText(f"已导出 gridsheet (padding={self._padding.value()}) 到 {d}")

# ── Entry ──────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序图标
    ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'TKS.ico')
    if os.path.exists(ico_path):
        app.setWindowIcon(QIcon(ico_path))
    
    fp = sys.argv[1] if len(sys.argv) > 1 else None
    editor = JVGEditor(fp)
    editor.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    if not HAS_PIL:
        print("需要 Pillow: pip install Pillow")
        sys.exit(1)
    main()
