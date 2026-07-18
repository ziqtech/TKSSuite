#!/usr/bin/env python3
"""
JVG 图集编辑器 — PySide6 版本，支持深色/浅色主题切换
========================================================
格式依据: sub_453BD0 (JVG加载), sub_4544EC (RLE渲染)
用法: python jvg_editor_v2.py [file.jvg]
"""

from __future__ import annotations

import base64
import copy
import json
import math
import os
import struct
import sys
import tempfile
import zlib
from functools import partial
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction, QActionGroup, QCloseEvent, QColor, QFont, QIcon, QImage,
    QMouseEvent, QPainter, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QCheckBox, QFileDialog,
    QMessageBox, QInputDialog, QScrollArea, QFrame, QSplitter,
    QMenuBar, QMenu, QStatusBar, QToolBar, QGroupBox, QSizePolicy,
    QListWidget, QListWidgetItem, QAbstractItemView, QDialog,
    QDialogButtonBox, QFormLayout, QLineEdit, QTextEdit,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsRectItem,
    QToolButton,
)

HAS_PIL = False
try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.dock_components import DockHeader, create_dock
from editor_utils.mod_exporter import (
    compute_crc32, generate_mod_json, pack_tksmod, ModMetadataDialog,
    diff_binary_blocks, build_block_diff_json,
    load_jvg_raw_blocks,
    get_tksmod_info, import_tksmod_blocks, ModImportPreviewDialog, ModExportPreviewDialog,
    safe_mod_filename,
)
from editor_utils.theme_manager import ThemeManager
from editor_utils.version import format_title, format_about_header
from editor_utils.window_theme import apply_godot_theme

JVG_MAGIC = b"@JVG"
JVM_MAGIC = b"@JVM"
SCREEN_W = 640
HEADER_SIZE = 32

# ── JVG 数据模型 ──────────────────────────────────────────
class PaletteRGB565:
    def __init__(self):
        self.entries: List[int] = [0] * 256

    def to_rgb888(self) -> bytes:
        r = bytearray(768)
        for i, e in enumerate(self.entries):
            r5, g6, b5 = (e>>11)&0x1F, (e>>5)&0x3F, e&0x1F
            r[i*3]=(r5<<3)|(r5>>2)
            r[i*3+1]=(g6<<2)|(g6>>4)
            r[i*3+2]=(b5<<3)|(b5>>2)
        return bytes(r)

class JVGFrame:
    def __init__(self):
        self.x_max=0
        self.y_max=0
        self.width=0
        self.height=0
        self.row_count=0
        self._pixels:Optional[bytes]=None
        self._alpha:Optional[bytes]=None
        self.encoded_data=b""
        self._palette: Optional[PaletteRGB565] = None
        # 帧头 8 个 uint16 中未被编辑器使用的保留字段，必须原样保存以免 MOD diff 误判
        self._hdr_unk4=0
        self._hdr_unk5=0
        self._hdr_unk6=0

    @property
    def pixels(self)->bytes:
        if self._pixels is None and self.encoded_data and self.width>0 and self.height>0:
            self._pixels,self._alpha=_decode_rle(self.encoded_data,self.width,self.height)
        return self._pixels if self._pixels is not None else b""

    @pixels.setter
    def pixels(self,val:bytes):
        self._pixels=val

    @property
    def alpha(self)->bytes:
        if self._alpha is None and self.encoded_data and self.width>0 and self.height>0:
            self._pixels,self._alpha=_decode_rle(self.encoded_data,self.width,self.height)
        return self._alpha if self._alpha is not None else b""

    @alpha.setter
    def alpha(self,val:bytes):
        self._alpha=val

    @property
    def x_off(self)->int:
        v=self.x_max
        return (v-65536 if v>=32768 else v)-self.width+1

    @property
    def y_off(self)->int:
        v=self.y_max
        return (v-65536 if v>=32768 else v)-self.height+1

class JVMBlock:
    def __init__(self, name:str=""):
        self.name=name
        self.frames:List[JVGFrame]=[]
        self.palette=PaletteRGB565()
        self._header_reserved=bytes(16)  # block头 [16:32] 保留字节，原样保存
        self._payload_size:Optional[int]=None  # block头 [8:12] 原值，原样保存以免 MOD diff 误判

    @property
    def frame_count(self)->int:
        return len(self.frames)

class JVGFile:
    def __init__(self):
        self.blocks:List[JVMBlock]=[]
        self.filepath:Optional[str]=None

    @property
    def total_frames(self)->int:
        return sum(b.frame_count for b in self.blocks)

    @property
    def block_count(self)->int:
        return len(self.blocks)

# ── JVG 解码器 ─────────────────────────────────────────
def _u16s(v:int)->int:
    return v-65536 if v>=32768 else v

def _decode_rle(data:bytes, w:int, h:int)->Tuple[bytes,bytes]:
    total=w*h
    out=bytearray(total)
    alpha=bytearray(total)
    recs=[]
    pos=0
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
        gap=max(SCREEN_W-w,0)
        bp=total-1
        pg=0
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
    jvg=JVGFile()
    jvg.filepath=filepath
    bc=struct.unpack("<I",data[8:12])[0]
    off=HEADER_SIZE
    for bi in range(bc):
        if off+32>len(data) or data[off:off+4]!=JVM_MAGIC: break
        sc=struct.unpack("<I",data[off+4:off+8])[0]
        ds=struct.unpack("<I",data[off+12:off+16])[0]
        s1=off+32
        co=[struct.unpack("<I",data[s1+j*4:s1+j*4+4])[0] for j in range(sc+1)]
        po=s1+(sc+1)*4
        blk=JVMBlock(f"block_{bi:02d}")
        for j in range(256): blk.palette.entries[j]=struct.unpack("<H",data[po+j*2:po+j*2+2])[0]
        dr=po+512
        for si in range(sc):
            mo=dr+co[si]
            ws=struct.unpack("<8H",data[mo:mo+16])
            f=JVGFrame()
            f.x_max=ws[0]
            f.y_max=ws[1]
            f.width=ws[2]
            f.height=ws[3]
            f.row_count=ws[7]
            f._hdr_unk4=ws[4]
            f._hdr_unk5=ws[5]
            f._hdr_unk6=ws[6]
            eo=mo+16
            f.encoded_data=data[eo:eo+co[si+1]-co[si]-16]
            blk.frames.append(f)
        blk._header_reserved=data[off+16:off+32]
        blk._payload_size=struct.unpack("<I",data[off+8:off+12])[0]
        off+=32+(sc+1)*4+512+ds
        jvg.blocks.append(blk)
    return jvg

# ── JVG 编码器 ─────────────────────────────────────────
def _encode_rle_game(pixels:bytes,alpha:bytes,w:int,h:int,screen_w:int=SCREEN_W)->Tuple[bytes,int]:
    buf=bytearray()
    pair_count=0
    pending=0
    first=True
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
    c=0
    pos=0
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
        psp=len(buf)               # [8:12] 块负载大小，待帧数据大小确定后回填
        buf+=struct.pack("<I",0)
        dsp=len(buf)
        buf+=struct.pack("<I",0)
        buf+=blk._header_reserved if len(blk._header_reserved)==16 else bytes(16)

        fd=bytearray()
        co=[0]
        for f in blk.frames:
            meta=struct.pack("<8H",f.x_max&0xFFFF,f.y_max&0xFFFF,f.width,f.height,
                f._hdr_unk4&0xFFFF,f._hdr_unk5&0xFFFF,f._hdr_unk6&0xFFFF,0)
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
        # [8:12] 各文件约定不一：部分文件全部写 0，部分文件写负载大小；游戏加载时并不使用它
        # （加载按 [12:16] data_size 定位下一块）。为保证与原始文件逐块比对时字节一致、
        # 避免 MOD 导出把未改动的块误判为"已修改"，这里原样回写读取到的原值；新建块无原值时回退为计算值。
        payload_val=blk._payload_size if getattr(blk,'_payload_size',None) is not None \
            else (n+1)*4+512+block_data_size
        struct.pack_into("<I",buf,psp,payload_val&0xFFFFFFFF)

    struct.pack_into("<I",buf,12,total_data_size)
    Path(filepath).write_bytes(bytes(buf))

# ── 图像导入 (PIL量化) ───────────────────────────────
def _pil_frame(img:'Image.Image')->JVGFrame:
    if img.mode!='RGBA': img=img.convert('RGBA')
    w,h=img.size
    frame=JVGFrame()
    frame.width=w
    frame.height=h
    a_band=img.getchannel('A')
    alpha_data=a_band.tobytes()
    frame.alpha=bytes(255 if b>=128 else 0 for b in alpha_data)
    bg=Image.new('RGB',(w,h),(0,0,0))
    rgb=Image.composite(img.convert('RGB'),bg,img.getchannel('A').point(lambda x:255 if x>=128 else 0))
    solid=sum(1 for b in alpha_data if b>=128)
    n_colors=min(255,max(1,solid)) if solid>0 else 1
    q=rgb.quantize(n_colors,method=Image.Quantize.MEDIANCUT,dither=0)
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
        e=f._palette.entries[i]
        f_colors[i]=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
    available=[i for i in range(1,256) if i not in used_by_original]
    used=set(f.pixels)
    remap=[0]*256
    for fi in sorted(used):
        if fi>=256 or f_colors[fi] is None or fi==0: continue
        fc=f_colors[fi]
        exact=None
        for bi in range(256):
            e=blk.palette.entries[bi]
            bc=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
            if fc==bc and (bi not in used_by_original or bi==fi):
                exact=bi
                break
        if exact is not None:
            remap[fi]=exact
            continue
        if available:
            slot=available.pop(0)
            blk.palette.entries[slot]=f._palette.entries[fi]
            remap[fi]=slot
        else:
            best,best_dist=0,999999
            for bi in range(256):
                e=blk.palette.entries[bi]
                bc=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
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
        rgb_bytes=sampled
        n_px=len(rgb_bytes)//3
    pal_img=None
    n_colors=0
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
        frame=JVGFrame()
        frame.width=w
        frame.height=h
        frame.alpha=alpha
        frame.pixels=bytes(pixels)
        frame.encoded_data,frame.row_count=_encode_rle_game(frame.pixels,frame.alpha,w,h)
        frame.x_max=(w-1 if w-1<32768 else w-1-65536)
        frame.y_max=(h-1 if h-1<32768 else h-1-65536)
        frame._palette=None
        results.append(frame)
    return results

def _align_anchor(new_f:JVGFrame,old_f:JVGFrame,mode:str="bottom_center")->None:
    if old_f.width<=0 or old_f.height<=0: return
    if new_f.width<=0 or new_f.height<=0: return
    old_xm=_u16s(old_f.x_max)
    old_ym=_u16s(old_f.y_max)
    old_x_off=old_xm-old_f.width+1
    old_y_off=old_ym-old_f.height+1
    if mode=="bottom_center":
        old_cx=old_xm-(old_f.width-1)/2.0
        new_x_off=int(round(old_cx-(new_f.width-1)/2.0))
        new_f.x_max=(new_x_off+new_f.width-1)&0xFFFF
        new_f.y_max=old_ym&0xFFFF
    elif mode=="center":
        old_cx=old_xm-(old_f.width-1)/2.0
        old_cy=old_ym-(old_f.height-1)/2.0
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
            img=Image.open(p)
            frames.append(_pil_frame(img))
        except Exception as e:
            print(f"  skip {Path(p).name}: {e}")
    return frames

# ── 导出 ──────────────────────────────────────────────
def _rgba_png(w:int,h:int,rgba:bytearray)->bytes:
    def ch(ct,d):
        c=ct+d
        return struct.pack(">I",len(d))+c+struct.pack(">I",zlib.crc32(c)&0xFFFFFFFF)
    png=b"\x89PNG\r\n\x1a\n"
    png+=ch(b"IHDR",struct.pack(">IIBBBBB",w,h,8,6,0,0,0))
    raw=bytearray()
    for row in range(h):
        raw.append(0)
        raw.extend(rgba[row*w*4:(row+1)*w*4])
    png+=ch(b"IDAT",zlib.compress(bytes(raw),9))
    png+=ch(b"IEND",b"")
    return png

def frame_to_rgba(f:JVGFrame,pal:PaletteRGB565,greenscreen_set:Optional[set]=None)->bytearray:
    pr=pal.to_rgb888()
    w,h=f.width,f.height
    rgba=bytearray(w*h*4)
    for y in range(h):
        for x in range(w):
            p=y*w+x
            off=p*4
            a=f.alpha[p] if p<len(f.alpha) else 0
            if a==0: continue
            idx=f.pixels[p] if p<len(f.pixels) else 0
            if greenscreen_set and idx in greenscreen_set: continue
            rgba[off]=pr[idx*3]
            rgba[off+1]=pr[idx*3+1]
            rgba[off+2]=pr[idx*3+2]
            rgba[off+3]=255
    return rgba

def export_single(f:JVGFrame,pal:PaletteRGB565,path:str,greenscreen_set:Optional[set]=None):
    rgba=frame_to_rgba(f,pal,greenscreen_set)
    Path(path).write_bytes(_rgba_png(f.width,f.height,rgba))

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
        xm=_u16s(f.x_max)
        ym=_u16s(f.y_max)
        vl=xm-f.width+1
        vt=ym-f.height+1
        vrs.append((vl,vt,xm,ym))
    min_vl=min(r[0] for r in vrs)
    max_vr=max(r[2] for r in vrs)
    min_vt=min(r[1] for r in vrs)
    max_vb=max(r[3] for r in vrs)
    cw=max_vr-min_vl+1
    ch=max_vb-min_vt+1
    cols=columns if columns>0 else max(1,int(math.ceil(math.sqrt(n))))
    rows=math.ceil(n/cols)
    aw=cols*cw+(cols-1)*padding
    ah=rows*ch+(rows-1)*padding
    atlas=bytearray(aw*ah*4)
    for fi,f in enumerate(frames):
        ri=fi//cols
        ci=fi%cols
        cx=ci*(cw+padding)
        cy=ri*(ch+padding)
        vl,vt,_,_=vrs[fi]
        ox=vl-min_vl
        oy=vt-min_vt
        pr=blk.palette.to_rgb888()
        for py in range(f.height):
            for px in range(f.width):
                p=py*f.width+px
                if p<len(f.alpha) and f.alpha[p]==0: continue
                idx=f.pixels[p] if p<len(f.pixels) else 0
                if greenscreen_set and idx in greenscreen_set: continue
                dx,dy=cx+ox+px,cy+oy+py
                if 0<=dx<aw and 0<=dy<ah:
                    off=(dy*aw+dx)*4
                    atlas[off]=pr[idx*3]
                    atlas[off+1]=pr[idx*3+1]
                    atlas[off+2]=pr[idx*3+2]
                    atlas[off+3]=255
    os.makedirs(outdir,exist_ok=True)
    name=f"grid_b{blk.name.replace(' ','_')}.png" if blk.name else "gridsheet.png"
    Path(os.path.join(outdir,name)).write_bytes(_rgba_png(aw,ah,atlas))
    print(f"  Gridsheet: {name} ({aw}x{ah}, {cols}x{rows}, cell {cw}x{ch})")

# ── GUI 组件 ──────────────────────────────────────────
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
        self.setWindowTitle(format_title("jvg_editor"))
        self.resize(1400, 900)

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

        apply_godot_theme(self, self._is_dark)

        # 数据模型
        self.jvg: Optional[JVGFile] = None
        self._bi = -1
        self._fi = 0
        self._sel_fi = -1
        self._view = "tile"
        self._anim_job: Optional[QTimer] = None
        self._photos = {}
        self._act_export_avatars = None
        self._act_import_avatars = None
        self._dirty = False

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
        """创建统一的 dock 面板 — 委托给 editor_utils.dock_components"""
        return create_dock(title, widget_content, header_layout)

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
        export_single_action.triggered.connect(partial(self._export, "single"))
        export_menu.addAction(export_single_action)

        export_group_action = QAction("导出分组", self)
        export_group_action.triggered.connect(partial(self._export, "group"))
        export_menu.addAction(export_group_action)

        export_grid_action = QAction("导出图集", self)
        export_grid_action.triggered.connect(partial(self._export, "grid"))
        export_menu.addAction(export_grid_action)

        export_menu.addSeparator()

        self._act_export_avatars = QAction("导出全部头像 (Fa.JVG)", self)
        self._act_export_avatars.triggered.connect(self._export_all_avatars)
        export_menu.addAction(self._act_export_avatars)

        self._act_export_avatars_split = QAction("导出每帧头像 (Fa.JVG)", self)
        self._act_export_avatars_split.triggered.connect(self._export_all_avatars_split)
        export_menu.addAction(self._act_export_avatars_split)

        self._act_import_avatars = QAction("导入全部头像 (Fa.JVG)", self)
        self._act_import_avatars.triggered.connect(self._import_all_avatars)
        export_menu.addAction(self._act_import_avatars)

        file_menu.addSeparator()

        export_mod_action = QAction("导出为 MOD (.tksmod)…", self)
        export_mod_action.triggered.connect(self._export_tksmod)
        file_menu.addAction(export_mod_action)

        export_block_mod_action = QAction("导出当前分组为 MOD (.tksmod)…", self)
        export_block_mod_action.triggered.connect(self._export_block_as_mod)
        file_menu.addAction(export_block_mod_action)

        export_frame_mod_action = QAction("导出选中帧为 MOD (.tksmod)…", self)
        export_frame_mod_action.triggered.connect(self._export_frame_as_mod)
        file_menu.addAction(export_frame_mod_action)

        import_mod_action = QAction("导入 MOD (.tksmod)…", self)
        import_mod_action.triggered.connect(self._import_tksmod)
        file_menu.addAction(import_mod_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 视图菜单 — 可切换的 checkable 动作
        view_menu = menubar.addMenu("视图(&V)")
        view_group = QActionGroup(self)
        view_group.setExclusive(True)

        self._act_tile = QAction("平铺(&T)", self, checkable=True)
        self._act_tile.setShortcut("1")
        self._act_tile.triggered.connect(partial(self._set_view, "tile"))
        view_group.addAction(self._act_tile)
        view_menu.addAction(self._act_tile)

        self._act_single = QAction("逐帧(&S)", self, checkable=True)
        self._act_single.setShortcut("2")
        self._act_single.triggered.connect(partial(self._set_view, "single"))
        view_group.addAction(self._act_single)
        view_menu.addAction(self._act_single)

        self._act_anim = QAction("动画(&A)", self, checkable=True)
        self._act_anim.setShortcut("3")
        self._act_anim.triggered.connect(partial(self._set_view, "anim"))
        view_group.addAction(self._act_anim)
        view_menu.addAction(self._act_anim)
        self._act_tile.setChecked(True)

        view_menu.addSeparator()

        # 主题切换
        theme_menu = view_menu.addMenu("主题(&H)")

        dark_theme_action = QAction("深色主题", self)
        dark_theme_action.triggered.connect(partial(self._switch_theme, 'dark'))
        theme_menu.addAction(dark_theme_action)

        light_theme_action = QAction("浅色主题", self)
        light_theme_action.triggered.connect(partial(self._switch_theme, 'light'))
        theme_menu.addAction(light_theme_action)

        toggle_theme_action = QAction("切换主题", self)
        toggle_theme_action.setShortcut("Ctrl+T")
        toggle_theme_action.triggered.connect(self._toggle_theme)
        theme_menu.addAction(toggle_theme_action)

        # 帮助菜单
        hm = menubar.addMenu("帮助(&H)")
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("关于编辑器", self._show_about)

    def _show_help(self):
        QMessageBox.information(self, "帮助说明",
            "功能: 浏览和编辑《三国群侠传》JVG 图像帧资源\n\n"
            "特性:\n"
            "  · 三种视图模式: 平铺 / 逐帧 / 动画播放\n"
            "  · 导出单帧、分组或完整图集为 PNG\n"
            "  · 头像资源批量导入/导出 (Fa.JVG)\n"
            "  · 支持 MOD 格式导入导出 (.tksmod)\n"
            "  · 深色/浅色主题切换\n\n"
            "快捷键:\n"
            "  1 = 平铺视图   2 = 逐帧视图   3 = 动画视图\n"
            "  Ctrl+T = 切换主题")

    def _show_about(self):
        QMessageBox.information(self, "关于编辑器",
            format_about_header('jvg_editor'))

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # 主水平分割器：左-中-右三栏布局
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(7)
        main_layout.addWidget(splitter, 1)

        # ================ 左侧：图集分组列表 ================
        left_panel = QWidget()
        left_panel.setMinimumWidth(180)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        list_container = QWidget()
        lc_layout = QVBoxLayout(list_container)
        lc_layout.setContentsMargins(0, 0, 0, 0)
        list_header = QHBoxLayout()
        btn_add = QToolButton()
        btn_add.setText("➕")
        btn_add.setAutoRaise(True)
        btn_add.setObjectName("dockToolButton")
        btn_add.clicked.connect(self._add_block)
        btn_del = QToolButton()
        btn_del.setText("➖")
        btn_del.setAutoRaise(True)
        btn_del.setObjectName("dockToolButton")
        btn_del.clicked.connect(self._del_block)
        list_header.addStretch()
        list_header.addWidget(btn_add)
        list_header.addWidget(btn_del)

        self._blist = QListWidget()
        self._blist.currentRowChanged.connect(self._on_block_sel)
        lc_layout.addWidget(self._blist)
        left_layout.addWidget(self._create_dock("图集分组列表", list_container, header_layout=list_header))
        splitter.addWidget(left_panel)

        # ================ 中间：2D 视口渲染器 ================
        canvas_container = QWidget()
        c_layout = QVBoxLayout(canvas_container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(4)

        # 工具栏放在画布上方
        tb_widget = QWidget()
        tb_layout = QHBoxLayout(tb_widget)
        tb_layout.setContentsMargins(4, 4, 4, 4)
        tb_layout.setSpacing(4)
        self._btn_tile = QPushButton("🖼️ 平铺")
        self._btn_tile.clicked.connect(partial(self._set_view, "tile"))
        self._btn_single = QPushButton("📷 逐帧")
        self._btn_single.clicked.connect(partial(self._set_view, "single"))
        self._btn_anim = QPushButton("🎬 动画")
        self._btn_anim.clicked.connect(partial(self._set_view, "anim"))
        tb_layout.addWidget(self._btn_tile)
        tb_layout.addWidget(self._btn_single)
        tb_layout.addWidget(self._btn_anim)
        tb_layout.addSpacing(10)
        self._greenscreen_remove = QCheckBox("预览去绿幕")
        self._greenscreen_remove.setChecked(True)
        self._greenscreen_remove.stateChanged.connect(self._refresh_view)
        tb_layout.addWidget(self._greenscreen_remove)
        tb_layout.addSpacing(10)
        tb_layout.addWidget(QLabel("速度:"))
        self._speed = QSpinBox()
        self._speed.setRange(10, 2000)
        self._speed.setValue(120)
        self._speed.setSingleStep(10)
        self._speed.setFixedWidth(56)
        tb_layout.addWidget(self._speed)
        tb_layout.addWidget(QLabel("ms"))
        tb_layout.addSpacing(10)
        btn_prev = QPushButton("◀ 上一帧")
        btn_prev.clicked.connect(partial(self._nav, -1))
        btn_prev.setShortcut(Qt.Key_Left)
        tb_layout.addWidget(btn_prev)
        btn_next = QPushButton("下一帧 ▶")
        btn_next.clicked.connect(partial(self._nav, 1))
        btn_next.setShortcut(Qt.Key_Right)
        tb_layout.addWidget(btn_next)
        self._zoom = 1.0
        tb_layout.addStretch()
        btn_zout = QPushButton("➖")
        btn_zout.setFixedWidth(36)
        btn_zout.clicked.connect(partial(self._zoom_step, -0.5))
        tb_layout.addWidget(btn_zout)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setFixedWidth(40)
        tb_layout.addWidget(self._zoom_label)
        btn_zin = QPushButton("➕")
        btn_zin.setFixedWidth(36)
        btn_zin.clicked.connect(partial(self._zoom_step, 0.5))
        tb_layout.addWidget(btn_zin)

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

        splitter.addWidget(self._create_dock("2D 视口渲染器", canvas_container))

        # ================ 右侧：工作流选项 + 图元结构校验日志 ================
        right_panel = QWidget()
        right_panel.setMinimumWidth(180)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # 顶部 dock 容器
        top_docks = QWidget()
        top_docks.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        top_docks_layout = QVBoxLayout(top_docks)
        top_docks_layout.setContentsMargins(0, 0, 0, 0)
        top_docks_layout.setSpacing(4)

        # 视图与布局
        layout_widget = QWidget()
        layout_form = QFormLayout(layout_widget)
        layout_form.setContentsMargins(4, 4, 4, 4)
        layout_form.setSpacing(4)
        self._tile_cols = QSpinBox()
        self._tile_cols.setRange(0, 32)
        self._tile_cols.setValue(0)
        self._tile_cols.valueChanged.connect(self._refresh_view)
        layout_form.addRow("平铺列数:", self._tile_cols)
        self._padding = QSpinBox()
        self._padding.setRange(0, 16)
        self._padding.setValue(1)
        self._padding.valueChanged.connect(self._refresh_view)
        layout_form.addRow("导出间距:", self._padding)
        btn_theme = QPushButton("🌗 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        layout_form.addRow(btn_theme)
        top_docks_layout.addWidget(self._create_dock("视图与布局", layout_widget))

        # 帧导入与替换
        frame_ops_widget = QWidget()
        frame_ops_layout = QVBoxLayout(frame_ops_widget)
        frame_ops_layout.setContentsMargins(4, 4, 4, 4)
        frame_ops_layout.setSpacing(2)
        btn_add_img = QPushButton("➕ 添加图片")
        btn_add_img.clicked.connect(self._add_images)
        btn_rep_img = QPushButton("🔄 替换选中")
        btn_rep_img.clicked.connect(self._replace_frame)
        btn_bat_img = QPushButton("📦 导入图集")
        btn_bat_img.clicked.connect(self._batch_replace_gridsheet)
        btn_del_img = QPushButton("❌ 删除选中")
        btn_del_img.clicked.connect(self._del_frame)
        frame_ops_layout.addWidget(btn_add_img)
        frame_ops_layout.addWidget(btn_rep_img)
        frame_ops_layout.addWidget(btn_bat_img)
        frame_ops_layout.addWidget(btn_del_img)
        top_docks_layout.addWidget(self._create_dock("帧导入与替换", frame_ops_widget))

        # 导出
        exp_widget = QWidget()
        exp_layout = QVBoxLayout(exp_widget)
        exp_layout.setContentsMargins(4, 4, 4, 4)
        exp_layout.setSpacing(2)
        btn_exp_single = QPushButton("📤 导出选中帧")
        btn_exp_single.clicked.connect(partial(self._export, "single"))
        btn_exp_grp = QPushButton("📁 导出当前分组")
        btn_exp_grp.clicked.connect(partial(self._export, "group"))
        btn_exp_grid = QPushButton("🗺️ 导出网格图集")
        btn_exp_grid.clicked.connect(partial(self._export, "grid"))
        exp_layout.addWidget(btn_exp_single)
        exp_layout.addWidget(btn_exp_grp)
        exp_layout.addWidget(btn_exp_grid)
        top_docks_layout.addWidget(self._create_dock("导出", exp_widget))

        # 头像操作
        avatar_widget = QWidget()
        avatar_layout = QVBoxLayout(avatar_widget)
        avatar_layout.setContentsMargins(4, 4, 4, 4)
        avatar_layout.setSpacing(2)
        self._btn_export_avatars = QPushButton("📤 导出全部头像")
        self._btn_export_avatars.clicked.connect(self._export_all_avatars)
        self._btn_export_avatars_split = QPushButton("📤 导出每帧头像")
        self._btn_export_avatars_split.clicked.connect(self._export_all_avatars_split)
        self._btn_import_avatars = QPushButton("📥 导入全部头像")
        self._btn_import_avatars.clicked.connect(self._import_all_avatars)
        avatar_layout.addWidget(self._btn_export_avatars)
        avatar_layout.addWidget(self._btn_export_avatars_split)
        avatar_layout.addWidget(self._btn_import_avatars)
        self._grp_avatar = self._create_dock("头像操作", avatar_widget)
        self._grp_avatar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        right_layout.addWidget(top_docks)
        right_layout.addWidget(self._grp_avatar)

        # 图元结构校验日志
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMinimumHeight(60)
        self._detail.setProperty("class", "MonoText")
        right_layout.addWidget(self._create_dock("图元结构校验日志", self._detail))

        right_layout.addStretch()

        # 将右侧面板移到图集分组列表左边
        splitter.addWidget(right_panel)
        w_canvas = splitter.widget(1)
        w_left = splitter.widget(0)
        splitter.addWidget(w_left)
        splitter.addWidget(w_canvas)

        # 三栏比例：左右固定，中间自适应
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([250, 250, 780])

        # 信息标签
        self._info = QLabel("")
        self.statusBar().addPermanentWidget(self._info)
        self.statusBar().showMessage("引擎就绪")

        # 初始化视图按钮状态
        self._set_view(self._view)

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
        apply_godot_theme(self, self._is_dark)

    # ── 未保存确认 ──────────────────────────────────────

    def closeEvent(self, event: QCloseEvent):
        if self._dirty:
            reply = QMessageBox.question(
                self, "未保存的修改",
                "当前文件有未保存的修改，是否保存？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if reply == QMessageBox.Save:
                self._save()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            super().closeEvent(event)

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self, "未保存的修改",
            "当前文件有未保存的修改，是否继续？\n\n"
            "点击“保存”先保存再继续，\n点击“丢弃”放弃修改，\n点击“取消”返回。",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if reply == QMessageBox.Save:
            self._save()
            return not self._dirty
        elif reply == QMessageBox.Discard:
            self._dirty = False
            return True
        return False

    def _new(self):
        if not self._confirm_discard():
            return
        self.jvg = JVGFile()
        self._sync_list()
        self._bi = -1
        self._fi = 0
        self._sel_fi = -1
        self._refresh_view()
        self._update_avatar_actions()
        self._dirty = False
        self.setWindowTitle(format_title("jvg_editor", "[新建]"))

    def _open_dlg(self):
        if not self._confirm_discard():
            return
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
        self._update_avatar_actions()
        self._dirty = False
        self.setWindowTitle(format_title("jvg_editor", os.path.basename(p)))

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
            self._dirty = False
            self.setWindowTitle(format_title("jvg_editor", os.path.basename(p)))
            self.statusBar().showMessage(f"已保存: {os.path.basename(p)}", 2000)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _export_tksmod(self):
        """导出 JVG 为 .tksmod — 块级增量（仅导出修改过的精灵块）"""
        if not self.jvg or not self.jvg.filepath:
            QMessageBox.information(self, "提示", "请先打开 JVG 文件")
            return

        target_name = os.path.basename(self.jvg.filepath)

        # 获取当前块数据
        tmp_path = tempfile.mktemp(suffix='.jvg')
        try:
            save_jvg(self.jvg, tmp_path)
            cur_blocks = load_jvg_raw_blocks(tmp_path)
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)
        if cur_blocks is None:
            QMessageBox.warning(self, "错误", "无法序列化当前 JVG 数据")
            return

        def _compute_stats(ref_dir):
            ref_path = os.path.join(ref_dir, target_name)
            if not os.path.isfile(ref_path):
                return {"valid": False, "error": f"目录中未找到 {target_name}"}
            ref_blocks = load_jvg_raw_blocks(ref_path)
            if ref_blocks is None:
                return {"valid": False, "error": f"{target_name} 不是有效的 JVG 文件"}
            diff = diff_binary_blocks(ref_blocks, cur_blocks)
            targets = []
            if diff['modified'] or diff['appended'] or diff['deleted_indices']:
                targets.append({"name": target_name,
                    "modified": len(diff['modified']),
                    "appended": len(diff['appended']),
                    "deleted": len(diff['deleted_indices'])})
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=os.path.dirname(self.jvg.filepath) if self.jvg and self.jvg.filepath else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        ref_path = os.path.join(ref_dir, target_name)
        if not os.path.isfile(ref_path):
            QMessageBox.warning(self, "参考文件不存在", f"在 {ref_dir} 中未找到 {target_name}")
            return

        # 加载参考文件的原始块
        ref_blocks = load_jvg_raw_blocks(ref_path)
        if ref_blocks is None:
            QMessageBox.warning(self, "参考文件无效", f"{target_name} 不是有效的 JVG 文件")
            return

        # 先保存当前编辑到临时文件获取当前块数据

        tmp_path = tempfile.mktemp(suffix='.jvg')
        try:
            save_jvg(self.jvg, tmp_path)
            cur_blocks = load_jvg_raw_blocks(tmp_path)
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)

        if cur_blocks is None:
            QMessageBox.warning(self, "错误", "无法序列化当前 JVG 数据")
            return

        # 计算块级差异
        diff_result = diff_binary_blocks(ref_blocks, cur_blocks)
        if not diff_result['modified'] and not diff_result['appended'] and not diff_result['deleted_indices']:
            QMessageBox.information(self, "无差异", "当前 JVG 与参考文件相同，无需导出。")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # 构建数据文件
        crc = compute_crc32(ref_path)
        data_json = build_block_diff_json(target=target_name, block_type="jvm_block",
            original_count=len(ref_blocks), original_crc32=crc, diff_result=diff_result)
        internal_path = f"data/{target_name}.json"
        components = [{"file": internal_path, "target": target_name}]
        mod_json = generate_mod_json(metadata, components)

        safe_name = safe_mod_filename(metadata['name'], metadata['id'])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_name}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {internal_path: data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.statusBar().showMessage(f"已导出 MOD: {os.path.basename(fp)} (修改{n_mod}块, 新增{n_app}块)", 5000)
            QMessageBox.information(self, "导出成功",
                f"已导出 (块级增量):\n{fp}\n\n参考: {ref_path}\n修改: {n_mod} 个精灵块\n新增: {n_app} 个精灵块")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_block_as_mod(self):
        """导出当前分组为 .tksmod — 块级增量模式，launcher 可正确合并到目标文件"""
        if not self.jvg or self._bi < 0 or self._bi >= len(self.jvg.blocks):
            QMessageBox.information(self, "提示", "请先选中一个分组")
            return

        if not self.jvg.filepath:
            QMessageBox.information(self, "提示",
                "请先打开一个 JVG 文件（需要原始文件名作为 MOD 合并目标）")
            return

        blk = self.jvg.blocks[self._bi]

        # 步骤1: 序列化当前分组 → 临时 JVG → 提取原始 block 字节
        tmp_jvg = JVGFile()
        new_blk = JVMBlock(blk.name)
        new_blk.frames = copy.deepcopy(blk.frames)
        new_blk.palette.entries = list(blk.palette.entries)
        new_blk._header_reserved = blk._header_reserved
        new_blk._payload_size = blk._payload_size
        tmp_jvg.blocks.append(new_blk)

        tmp_path = tempfile.mktemp(suffix='.jvg')
        try:
            save_jvg(tmp_jvg, tmp_path)
            cur_blocks = load_jvg_raw_blocks(tmp_path)
            if not cur_blocks:
                QMessageBox.warning(self, "错误", "无法序列化当前分组")
                return
            block_bytes = cur_blocks[0]

            # 步骤2: 构建 block_diff — launcher 会加载游戏原文件并替换指定索引的块
            target_name = os.path.basename(self.jvg.filepath)
            diff_result = {
                "modified": [{"index": self._bi,
                              "data_b64": base64.b64encode(block_bytes).decode('ascii')}],
                "appended": [],
                "deleted_indices": [],
            }

            crc = compute_crc32(self.jvg.filepath)
            data_json = build_block_diff_json(
                target=target_name, block_type="jvm_block",
                original_count=len(self.jvg.blocks), original_crc32=crc,
                diff_result=diff_result)

            # 步骤3: MOD 元数据
            dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
            if dlg.exec() != QDialog.Accepted: return
            metadata = dlg.get_metadata()
            self._last_mod_metadata = metadata

            internal_path = f"data/{target_name}.json"
            mod_json = generate_mod_json(metadata,
                [{"file": internal_path, "target": target_name}])

            safe_name = safe_mod_filename(metadata['name'], metadata['id'])
            fp, _ = QFileDialog.getSaveFileName(self, "导出当前分组为 MOD",
                f"{safe_name}.tksmod", "TKS MOD (*.tksmod)")
            if not fp: return

            pack_tksmod(fp, mod_json, {internal_path: data_json})

            self.statusBar().showMessage(
                f"已导出 MOD: {os.path.basename(fp)} (分组 [{self._bi}] {blk.name}, {blk.frame_count}帧)", 5000)
            QMessageBox.information(self, "导出成功",
                f"已导出当前分组为 MOD (块级合并):\n{fp}\n\n"
                f"目标文件: {target_name}\n分组: [{self._bi}] {blk.name}\n帧数: {blk.frame_count}\n\n"
                f"Launcher 加载时将替换 {target_name} 的第 {self._bi} 个精灵块。")
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)

    def _export_frame_as_mod(self):
        """导出选中帧为 .tksmod — 资源替换模式（独立 JVG 文件，用于分享/存档）"""
        if not self.jvg or self._bi < 0 or self._bi >= len(self.jvg.blocks):
            QMessageBox.information(self, "提示", "请先选中一个分组")
            return

        blk = self.jvg.blocks[self._bi]
        if self._sel_fi < 0 or self._sel_fi >= blk.frame_count:
            QMessageBox.information(self, "提示", "请先在平铺视图中点击选中一帧")
            return

        frame = blk.frames[self._sel_fi]

        # 创建临时 JVGFile，包含一个分组和选中的帧
        tmp_jvg = JVGFile()
        new_blk = JVMBlock(f"{blk.name}_f{self._sel_fi}")
        new_blk.frames = [copy.deepcopy(frame)]
        new_blk.palette.entries = list(blk.palette.entries)
        tmp_jvg.blocks.append(new_blk)


        tmp_path = tempfile.mktemp(suffix='.jvg')
        try:
            save_jvg(tmp_jvg, tmp_path)

            # MOD 元数据
            dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
            if dlg.exec() != QDialog.Accepted: return
            metadata = dlg.get_metadata()
            self._last_mod_metadata = metadata

            # 生成独立资源文件名（不会覆盖游戏文件）
            src_name = os.path.basename(self.jvg.filepath) if self.jvg.filepath else "unknown.jvg"
            base = os.path.splitext(src_name)[0]
            target_name = f"{base}_{blk.name}_f{self._sel_fi:03d}.jvg"

            mod_json = generate_mod_json(metadata, [],
                resources=[{"file": f"resources/{target_name}", "target": target_name}])

            safe_name = safe_mod_filename(metadata['name'], metadata['id'])
            fp, _ = QFileDialog.getSaveFileName(self, "导出选中帧为 MOD",
                f"{safe_name}.tksmod", "TKS MOD (*.tksmod)")
            if not fp: return

            pack_tksmod(fp, mod_json, {}, resource_files={f"resources/{target_name}": tmp_path})

            self.statusBar().showMessage(
                f"已导出 MOD: {os.path.basename(fp)} (帧 #{self._sel_fi})", 5000)
            QMessageBox.information(self, "导出成功",
                f"已导出选中帧为 MOD:\n{fp}\n\n"
                f"分组: [{self._bi}] {blk.name}\n"
                f"帧: #{self._sel_fi} ({frame.width}×{frame.height})\n\n"
                f"注意: 帧导出为独立资源文件，不会自动合并到游戏 JVG。\n"
                f"如需修改游戏中的精灵块，请使用「导出当前分组为 MOD」。")
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到 JVG 编辑器"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        # 查找 JVG 类型的 target
        jvg_targets = [t for t in info.get("targets", []) if t.upper().endswith(".JVG")]
        if not jvg_targets:
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 JVG 文件的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}")
            return

        target_name = jvg_targets[0]  # 取第一个 JVG target

        dlg = ModImportPreviewDialog(self, info, default_dir=os.path.dirname(self.jvg.filepath) if self.jvg and self.jvg.filepath else "")
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        mod_json, blocks = import_tksmod_blocks(
            fp, ref_dir, target_name, block_type="jvm_block")
        if blocks is None:
            QMessageBox.warning(self, "导入失败",
                f"无法导入 MOD 数据。\n请确认参考目录中包含有效的 {target_name}")
            return

        # 将块数据重建为临时 JVG 文件，然后重新加载

        tmp_path = tempfile.mktemp(suffix='.jvg')
        try:
            # 重建 JVG 二进制
            total_frames = 0
            total_data_size = 0
            for blk_data in blocks:
                if len(blk_data) >= 32 and blk_data[:4] == b'@JVM':
                    sc = struct.unpack_from('<I', blk_data, 4)[0]
                    ds = struct.unpack_from('<I', blk_data, 12)[0]
                    total_frames += sc
                    total_data_size += ds

            buf = bytearray()
            buf += b'@JVG'
            buf += struct.pack('<I', len(blocks))
            buf += struct.pack('<I', len(blocks))
            buf += struct.pack('<I', total_data_size)
            buf += struct.pack('<I', total_frames)
            buf += bytes(12)
            for blk_data in blocks:
                buf += blk_data

            Path(tmp_path).write_bytes(bytes(buf))
            self.jvg = load_jvg(tmp_path)
            self.jvg.filepath = None  # 清除临时路径
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"重建 JVG 数据失败: {e}")
            return
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)

        # 记住 MOD 元数据
        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        self._sync_list()
        self._bi = 0
        self._fi = 0
        self._refresh_view()
        self._dirty = True
        self.statusBar().showMessage(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{target_name}: {len(blocks)} 个精灵块", 5000)
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"目标: {target_name}\n"
            f"精灵块: {len(blocks)} 个\n\n"
            f"您现在可以继续编辑并重新导出。")

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
        self._dirty = True

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
            self._dirty = True

    def _add_images(self):
        if not self.jvg or self._bi < 0:
            QMessageBox.information(self, "提示", "请先选择分组")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "选择图片", "", "图片 (*.png *.bmp *.jpg *.jpeg)")
        if not paths:
            return
        self._info.setText("正在导入...")
        QApplication.processEvents()
        # 统一量化到分组调色板：一次性量化所有图片，避免空分组逐帧 remap
        # 时第 0 色丢失变黑、以及多帧相互覆盖调色板槽位导致色板错乱的问题。
        subs = []
        for p in sorted(paths, key=lambda pp: Path(pp).name.lower()):
            try:
                subs.append(Image.open(p).convert('RGBA'))
            except Exception as e:
                print(f"  skip {Path(p).name}: {e}")
        if subs:
            blk = self.jvg.blocks[self._bi]
            # 保护分组内已有有效帧的颜色，新帧颜色写入剩余槽位
            keep_indices = [i for i, f in enumerate(blk.frames) if f.width > 0 and f.height > 0]
            new_frames = _batch_quantize_subs_to_block(subs, blk, keep_indices)
            blk.frames.extend(new_frames)
            self._sync_list()
            self._kill_anim()
            self._refresh_view()
            self._dirty = True
            self._info.setText(f"导入 {len(new_frames)} 帧")

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
        try:
            img = Image.open(paths[0]).convert('RGBA')
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e))
            return
        old_f = blk.frames[self._sel_fi]
        # 统一量化：保护分组内其他有效帧的颜色，新帧量化到剩余槽位。
        # 相比“逐帧量化到 255 色再 remap 合并”（两次近似），批量量化一次性取新图
        # 全局最优色，避免可用槽位不足时最近色匹配导致的颜色丢失。
        keep_indices = [i for i, f in enumerate(blk.frames)
                        if i != self._sel_fi and f.width > 0 and f.height > 0]
        new_frames = _batch_quantize_subs_to_block([img], blk, keep_indices)
        if new_frames:
            new_f = new_frames[0]
            _align_anchor(new_f, old_f, mode="bottom_center")
            blk.frames[self._sel_fi] = new_f
            self._sync_list()
            self._kill_anim()
            self._refresh_view()
            self._dirty = True
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
            self._dirty = True

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

        # 导入模式选择 (仅替换分支需要)
        use_bbox_mode = True  # 默认 bbox 模式
        if not is_new_block:
            mode_items = ["自适应 Bbox (外部图集)", "精确匹配 (本编辑器导出的图集)"]
            mode_choice, ok = QInputDialog.getItem(self, "导入模式",
                "选择导入模式:\n"
                "· 自适应 Bbox — 用 alpha 通道自动检测精灵边界，适合外部图集\n"
                "· 精确匹配 — 按旧帧 offset 精确提取，适合本编辑器导出的图集",
                mode_items, 0, False)
            if not ok:
                return
            use_bbox_mode = (mode_choice == mode_items[0])

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
            # 预计算全局视口原点 (与 export_gridsheet 一致)
            _vrs = []
            for _, vf in valid_list:
                _xm = _u16s(vf.x_max)
                _ym = _u16s(vf.y_max)
                _vl = _xm - vf.width + 1
                _vt = _ym - vf.height + 1
                _vrs.append((_vl, _vt, _xm, _ym))
            _min_vl = min(r[0] for r in _vrs)
            _min_vt = min(r[1] for r in _vrs)

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
                if use_bbox_mode:
                    # Bbox 自适应模式：用 alpha 通道检测精灵边界
                    l, t, r, b = bbox
                    sub = cell.crop((l, t, r, b))
                    # 用全局视口原点计算游戏世界坐标 (所有 cell 统一基准)
                    new_x_max = (_min_vl + r - 1) & 0xFFFF
                    new_y_max = (_min_vt + b - 1) & 0xFFFF
                else:
                    # 精确匹配模式：按旧帧 offset 提取，尺寸不变
                    old_xm = _u16s(old_f.x_max)
                    old_ym = _u16s(old_f.y_max)
                    old_vl = old_xm - old_f.width + 1
                    old_vt = old_ym - old_f.height + 1
                    ox = old_vl - _min_vl
                    oy = old_vt - _min_vt
                    sub = cell.crop((ox, oy, ox + old_f.width, oy + old_f.height))
                    new_x_max = old_f.x_max
                    new_y_max = old_f.y_max
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
        else:
            for (blk_fi, xm, ym), nf in zip(metas, new_frames):
                nf.x_max = xm
                nf.y_max = ym
                if not use_bbox_mode:
                    # 精确匹配模式：用 _align_anchor 重新对齐
                    _align_anchor(nf, blk.frames[blk_fi], mode="bottom_center")
                # bbox 模式：直接使用公式计算的 offset，不做锚点对齐
                blk.frames[blk_fi] = nf

        self._sync_list()
        self._kill_anim()
        self._refresh_view()
        self._dirty = True
        _mode_label = "Bbox" if (is_new_block or use_bbox_mode) else "精确匹配"
        self._info.setText(f"导入组图完成: {'新增' if is_new_block else '替换'} {len(new_frames)} 帧, 跳过 {skipped} 空cell (cell={cw}×{ch}, {_mode_label})")

    def _zoom_step(self, delta: float):
        self._zoom = max(1.0, min(3.0, self._zoom + delta))
        self._zoom_label.setText(f"{int(self._zoom * 100)}%")
        self._kill_anim()
        self._refresh_view()

    def _set_view(self, mode: str):
        self._view = mode
        if hasattr(self, '_act_tile'):
            self._act_tile.setChecked(mode == "tile")
            self._act_single.setChecked(mode == "single")
            self._act_anim.setChecked(mode == "anim")
        if hasattr(self, '_btn_tile'):
            names = {"tile": "平铺", "single": "逐帧", "anim": "动画"}
            for btn, key in [(self._btn_tile, "tile"), (self._btn_single, "single"), (self._btn_anim, "anim")]:
                btn.setText(f"🟢 {names[key]}" if mode == key else f"⚪ {names[key]}")
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
        # 计算选中帧在整个图集中的全局序号（累加当前分组之前所有分组的帧数 + 分组内序号）
        base = sum(b.frame_count for b in self.jvg.blocks[:self._bi]) if (self.jvg and self._bi >= 0) else 0
        global_fi = base + fi
        total = self.jvg.total_frames if self.jvg else 0
        self._detail.setPlainText(
            f">> Frame [{fi}]\n"
            f"选中帧序: 全局第 {global_fi}/{total} 帧 (分组内 #{fi})\n"
            f"几何边界: {f.width}×{f.height} px\n"
            f"物理偏移: X={f.x_off}, Y={f.y_off} (锚定补偿)\n"
            f"数据载荷: Pixels={len(f.pixels)}B, Encoded={len(f.encoded_data)}B\n"
            f"来源状态: {'[临时外挂导入区]' if is_import else '[底层封存区]'}"
        )

    def _refresh_view(self, *_):
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
            item.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
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

        # 计算所有帧的边界框（与动画模式一致）
        vrs = []
        for frame in frames:
            if frame.width <= 0:
                vrs.append((0, 0, 0, 0))
                continue
            xm = _u16s(frame.x_max)
            ym = _u16s(frame.y_max)
            vrs.append((xm - frame.width + 1, ym - frame.height + 1, xm, ym))

        min_vl = min(r[0] for r in vrs)
        min_vt = min(r[1] for r in vrs)
        max_vr = max(r[2] for r in vrs)
        max_vb = max(r[3] for r in vrs)
        cell_w = max_vr - min_vl + 1
        cell_h = max_vb - min_vt + 1

        # 计算自适应缩放
        base_scale = min(1.0, (view_w - 40) / max(cell_w, 1), (view_h - 40) / max(cell_h, 1))
        scale = base_scale * self._zoom

        # 获取原始尺寸的 pixmap
        pixmap = self._f2qpixmap(f, pal, 1.0)

        if pixmap:
            self._photos[0] = pixmap
            # 计算当前帧在 cell 中的偏移量
            ox = _u16s(f.x_max) - f.width + 1 - min_vl
            oy = _u16s(f.y_max) - f.height + 1 - min_vt

            # 计算 cell 在视口中的居中位置
            cell_pixel_w = cell_w * scale
            cell_pixel_h = cell_h * scale
            cx = (view_w - cell_pixel_w) / 2
            cy = (view_h - cell_pixel_h) / 2

            # 帧在 cell 中的位置
            x = cx + ox * scale
            y = cy + oy * scale

            item = QGraphicsPixmapItem(pixmap)
            item.setPos(x, y)
            item.setScale(scale)
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

    # ── Fa.JVG 头像批量操作 ─────────────────────────────────
    def _is_fa_jvg(self) -> bool:
        """检查当前加载文件是否为 Fa.JVG"""
        if not self.jvg or not self.jvg.filepath:
            return False
        return os.path.basename(self.jvg.filepath).upper() == "FA.JVG"

    def _update_avatar_actions(self):
        """根据当前文件类型启用/禁用头像相关操作"""
        is_fa = self._is_fa_jvg()
        if self._act_export_avatars:
            self._act_export_avatars.setEnabled(is_fa)
        if self._act_export_avatars_split:
            self._act_export_avatars_split.setEnabled(is_fa)
        if self._act_import_avatars:
            self._act_import_avatars.setEnabled(is_fa)
        if hasattr(self, '_btn_export_avatars'):
            self._btn_export_avatars.setEnabled(is_fa)
        if hasattr(self, '_btn_export_avatars_split'):
            self._btn_export_avatars_split.setEnabled(is_fa)
        if hasattr(self, '_btn_import_avatars'):
            self._btn_import_avatars.setEnabled(is_fa)

    def _export_all_avatars(self):
        """导出全部头像：取所有偶数block的frame0(70×70)，以padding=1排列成近正方形图集"""
        if not self.jvg or not self._is_fa_jvg():
            QMessageBox.information(self, "提示", "此功能仅适用于 Fa.JVG 头像资源文件")
            return

        # 收集所有70×70头像 (偶数block的frame 0)
        avatars = []  # [(block_index, frame, block), ...]
        for bi in range(0, len(self.jvg.blocks), 2):
            blk = self.jvg.blocks[bi]
            if blk.frame_count > 0:
                f = blk.frames[0]
                if f.width > 0 and f.height > 0:
                    avatars.append((bi, f, blk))

        if not avatars:
            QMessageBox.information(self, "提示", "没有找到有效的头像数据")
            return

        n = len(avatars)
        cols = int(math.ceil(math.sqrt(n)))
        rows = int(math.ceil(n / cols))

        cell_size = 70
        padding = self._padding.value()
        aw = cols * cell_size + (cols - 1) * padding
        ah = rows * cell_size + (rows - 1) * padding

        no_green = self._greenscreen_remove.isChecked()
        atlas = bytearray(aw * ah * 4)

        for ai, (bi, f, blk) in enumerate(avatars):
            ri = ai // cols
            ci = ai % cols
            cx = ci * (cell_size + padding)
            cy = ri * (cell_size + padding)

            pal = self._get_pal(blk, f)
            if no_green:
                gs = {i for i, e in enumerate(pal.entries) if e == 0x07E0}
            else:
                gs = None
            pr = pal.to_rgb888()

            for py in range(f.height):
                for px in range(f.width):
                    p = py * f.width + px
                    if p < len(f.alpha) and f.alpha[p] == 0:
                        continue
                    idx = f.pixels[p] if p < len(f.pixels) else 0
                    if gs and idx in gs:
                        continue
                    dx, dy = cx + px, cy + py
                    if 0 <= dx < aw and 0 <= dy < ah:
                        off = (dy * aw + dx) * 4
                        atlas[off] = pr[idx * 3]
                        atlas[off + 1] = pr[idx * 3 + 1]
                        atlas[off + 2] = pr[idx * 3 + 2]
                        atlas[off + 3] = 255

        default_name = "Fa_avatars.png"
        fp, _ = QFileDialog.getSaveFileName(self, "导出全部头像", default_name, "PNG (*.png)")
        if not fp:
            return

        Path(fp).write_bytes(_rgba_png(aw, ah, atlas))
        self._info.setText(f"已导出 {n} 个头像到 {Path(fp).name} ({aw}×{ah}, {cols}×{rows})")
        self.statusBar().showMessage(f"已导出全部头像: {n}个角色 ({cols}×{rows})", 3000)

    def _export_all_avatars_split(self):
        """导出每帧头像：将每个角色的70×70和35×35头像导出为独立PNG"""
        if not self.jvg or not self._is_fa_jvg():
            QMessageBox.information(self, "提示", "此功能仅适用于 Fa.JVG 头像资源文件")
            return

        outdir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not outdir:
            return

        no_green = self._greenscreen_remove.isChecked()
        exported = 0

        for bi, blk in enumerate(self.jvg.blocks):
            if blk.frame_count == 0:
                continue
            f = blk.frames[0]
            if f.width <= 0 or f.height <= 0:
                continue

            pal = self._get_pal(blk, f)
            if no_green:
                gs = {i for i, e in enumerate(pal.entries) if e == 0x07E0}
            else:
                gs = None

            char_idx = bi // 2
            size_label = "70x70" if bi % 2 == 0 else "35x35"
            name = f"avatar_{char_idx:03d}_{size_label}.png"
            export_single(f, pal, os.path.join(outdir, name), gs)
            exported += 1

        self._info.setText(f"已导出 {exported} 帧到 {outdir}")
        self.statusBar().showMessage(f"已导出每帧头像: {exported} 帧", 3000)

    def _import_all_avatars(self):
        """导入全部头像：从图集按编辑器间距拆分70×70头像，自动生成35×35版本"""
        if not self.jvg or not self._is_fa_jvg():
            QMessageBox.information(self, "提示", "此功能仅适用于 Fa.JVG 头像资源文件")
            return

        # 用已有偶数block数量确定网格（与导出逻辑一致，不受padding变化影响）
        avatar_count = sum(1 for bi in range(0, len(self.jvg.blocks), 2)
                          if self.jvg.blocks[bi].frame_count > 0
                          and self.jvg.blocks[bi].frames[0].width > 0)
        if avatar_count == 0:
            QMessageBox.information(self, "提示", "没有找到已有头像数据，无法确定网格尺寸")
            return
        cols = int(math.ceil(math.sqrt(avatar_count)))
        rows = int(math.ceil(avatar_count / cols))

        fp, _ = QFileDialog.getOpenFileName(self, "选择头像图集", "", "PNG (*.png)")
        if not fp:
            return

        try:
            img = Image.open(fp).convert('RGBA')
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e))
            return

        cell_size = 70
        padding = self._padding.value()
        stride = cell_size + padding
        total_cells = cols * rows

        self._info.setText(f"导入全部头像: 解析 {cols}×{rows} 图集...")
        QApplication.processEvents()

        imported = 0
        for cell_idx in range(total_cells):
            ri = cell_idx // cols
            ci = cell_idx % cols
            cx = ci * stride
            cy = ri * stride

            # 裁剪 70×70 区域
            cell_70 = img.crop((cx, cy, cx + cell_size, cy + cell_size))

            # 跳过全透明 cell
            bbox = cell_70.getchannel('A').getbbox()
            if bbox is None:
                continue

            # 缩放生成 35×35
            cell_35 = cell_70.resize((35, 35), Image.LANCZOS)

            even_bi = cell_idx * 2       # 70×70 头像 block
            odd_bi = cell_idx * 2 + 1    # 35×35 头像 block

            # 确保 block 存在
            while even_bi >= len(self.jvg.blocks):
                self.jvg.blocks.append(JVMBlock(f"block_{len(self.jvg.blocks):02d}"))
            while odd_bi >= len(self.jvg.blocks):
                self.jvg.blocks.append(JVMBlock(f"block_{len(self.jvg.blocks):02d}"))

            blk_even = self.jvg.blocks[even_bi]
            blk_odd = self.jvg.blocks[odd_bi]

            # --- 导入 70×70 头像 ---
            frame_70 = _pil_frame(cell_70)
            if frame_70._palette:
                blk_even.palette.entries = list(frame_70._palette.entries)
                frame_70._palette = None
            frame_70.x_max = (cell_size - 1) & 0xFFFF
            frame_70.y_max = (cell_size - 1) & 0xFFFF
            blk_even.frames = [frame_70]

            # --- 导入 35×35 头像 ---
            frame_35 = _pil_frame(cell_35)
            if frame_35._palette:
                blk_odd.palette.entries = list(frame_35._palette.entries)
                frame_35._palette = None
            frame_35.x_max = (35 - 1) & 0xFFFF
            frame_35.y_max = (35 - 1) & 0xFFFF
            blk_odd.frames = [frame_35]

            imported += 1

        self._sync_list()
        self._kill_anim()
        self._refresh_view()
        self._dirty = True
        self._info.setText(f"导入全部头像完成: {imported} 个角色 ({cols}×{rows} 图集)")
        self.statusBar().showMessage(f"已导入全部头像: {imported} 个角色", 3000)

# ── Entry ──────────────────────────────────────────
def main():
    from editor_utils.app_init import install_translator, setup_app_icon
    from editor_utils.ui_helpers import install_dialog_theme_filter
    app = QApplication(sys.argv)
    install_dialog_theme_filter(app)
    app.setStyle("Fusion")  # 使用 Fusion 样式，避免 Windows 原生样式覆盖 QSS
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(os.path.abspath(__file__)))

    fp = sys.argv[1] if len(sys.argv) > 1 else None
    editor = JVGEditor(fp)
    editor.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    if not HAS_PIL:
        print("需要 Pillow: pip install Pillow")
        sys.exit(1)
    main()

