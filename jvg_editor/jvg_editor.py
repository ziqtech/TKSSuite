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
        self.row_count=0; self._pixels:Optional[bytes]=None; self._alpha:Optional[bytes]=None
        self.encoded_data=b""
        self._palette: Optional[PaletteRGB565] = None  # per-frame palette for imports

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
    """按游戏 sub_4544EC 渲染逻辑生成 RLE 数据

    游戏渲染循环 (sub_4544EC.c L134-150):
        dest = screen + 2*(y_max*640 + x_max)   # 起点 = 右下角
        while (rle_pairs--):
            dest -= 2*skip                       # 向左跳过 skip 像素
            while (run--):
                *dest = palette[*src++]          # 写像素
                dest -= 2                        # 向左移
    关键点:
      1) dest 内存线性递减, 跨行必须 skip = screen_w - w 补偿屏幕行距;
      2) 透明像素(alpha==0)通过累积 skip 跳过, 不写 run data;
      3) skip 必须在行间累积 (若上一行最后不透明段左侧还有透明像素, 这些
         偏移量要并入下一行的跳跃距离), 否则累积 1px 偏差会形成斜纹。
    """
    buf=bytearray(); pair_count=0
    pending=0  # 跨行累积 skip
    first=True
    for row in range(h-1,-1,-1):
        # 行切换: 从上一行左外一格跳到本行右外一格, 需要 (screen_w-w) 个像素的回跳
        if not first: pending+=screen_w-w
        first=False
        col=w-1
        while col>=0:
            # 累计连续透明像素
            t0=col
            while col>=0 and alpha[row*w+col]==0: col-=1
            pending+=t0-col
            if col<0: break
            # 如 pending 溢出 uint16, 拆成若干空对 (0xFFFF,0) 先消耗
            while pending>0xFFFF:
                buf+=struct.pack("<HH",0xFFFF,0); pair_count+=1; pending-=0xFFFF
            # 收集连续不透明段 (从右到左, 匹配 dest 向左移动)
            run=bytearray()
            while col>=0 and alpha[row*w+col]!=0 and len(run)<0xFFFF:
                run.append(pixels[row*w+col]); col-=1
            buf+=struct.pack("<HH",pending,len(run)); buf+=bytes(run)
            pair_count+=1; pending=0
    return bytes(buf),pair_count

def _count_rle_pairs(data:bytes)->int:
    """统计 RLE (skip,run) 对数 — sub_4544EC.c L46: word_A5AECA"""
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
                # 为导入帧按游戏渲染格式生成 RLE (含跨行 skip 与 alpha 透明处理)
                alpha=f.alpha if f.alpha and len(f.alpha)==f.width*f.height else bytes([255]*(f.width*f.height))
                enc,rc=_encode_rle_game(f.pixels,alpha,f.width,f.height)
                struct.pack_into("<H",fd,len(fd)-2,rc)
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

def _remap_to_block_palette(f:JVGFrame,blk:JVMBlock):
    """将导入帧重映射到块调色板: 扫描块中所有帧已使用的索引, 仅使用空位,
    保证原始帧不受影响。同时更新 encoded_data。"""
    if not f._palette or not f.pixels: return
    # 1. 扫描块中所有原始帧已使用的调色板索引 (仅检查有 encoded_data 的帧)
    used_by_original=set()
    for of in blk.frames:
        if of is f: continue  # 跳过自身
        if of.pixels:
            for b in of.pixels: used_by_original.add(b)
    # 2. 构建可用索引: blk.palette 中值为0 且不被原始帧使用的空位
    f_colors=[None]*256
    for i in range(256):
        e=f._palette.entries[i]; f_colors[i]=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
    available=[i for i in range(1,256) if i not in used_by_original]
    # 3. 对导入帧中实际使用的颜色, 分配空位并写入调色板
    used=set(f.pixels)
    remap=[0]*256
    for fi in sorted(used):
        if fi>=256 or f_colors[fi] is None or f._palette.entries[fi]==0: continue
        # 尝试精确匹配已有颜色
        fc=f_colors[fi]; exact=None
        for bi in range(256):
            e=blk.palette.entries[bi]; bc=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
            if fc==bc and (bi not in used_by_original or bi==fi): exact=bi; break
        if exact is not None: remap[fi]=exact; continue
        # 分配新空位
        if available:
            slot=available.pop(0)
            blk.palette.entries[slot]=f._palette.entries[fi]
            remap[fi]=slot
        else:
            # 无空位时找最近颜色
            best,best_dist=0,999999
            for bi in range(256):
                e=blk.palette.entries[bi]; bc=(((e>>11)&0x1F)<<3,((e>>5)&0x3F)<<2,(e&0x1F)<<3)
                d=abs(fc[0]-bc[0])+abs(fc[1]-bc[1])+abs(fc[2]-bc[2])
                if d<best_dist: best,best_dist=bi,d
            remap[fi]=best
    # 4. 未使用的颜色映射到0
    for fi in range(256):
        if fi not in used: remap[fi]=0
    # 5. 重映射像素
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
    """批量统一量化: 把多张 RGBA sub 图一次性量化为共享调色板, 写入 block.palette 的空位。

    避免逐帧独立量化导致的调色板槽位争抢 → 颜色退化(掉色)。

    Args:
        subs: 每个将要替换的帧对应的 RGBA 子图 (已裁剪到 bbox 大小)
        blk: 目标 block (其 palette 会被更新)
        keep_frame_indices: 不会被替换的帧索引列表, 其调色板槽位必须保留

    Returns:
        与 subs 一一对应的 JVGFrame 列表, 已填充 width/height/alpha/pixels/encoded_data。
        x_max/y_max 设为默认值, 调用者应自行覆盖。
    """
    if not subs: return []
    # 1. 收集"保留帧"已使用的槽位 (含索引 0 = 透明)
    used_by_kept={0}
    for ki in keep_frame_indices:
        if 0<=ki<len(blk.frames):
            kf=blk.frames[ki]
            if kf.pixels:
                for b in kf.pixels: used_by_kept.add(b)
    available=[i for i in range(256) if i not in used_by_kept]
    n_avail=len(available)
    # 2. 收集所有 sub 的非透明像素, 合并为采样条
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
    # 采样压缩避免量化过慢 (100w 像素足够保留颜色分布)
    MAX_PX=1_000_000
    if n_px>MAX_PX:
        step=(n_px+MAX_PX-1)//MAX_PX
        sampled=bytearray()
        for i in range(0,n_px,step):
            sampled+=rgb_bytes[i*3:i*3+3]
        rgb_bytes=sampled; n_px=len(rgb_bytes)//3
    # 3. 生成共享 palette 图
    pal_img=None; n_colors=0
    if n_px>0 and n_avail>0:
        strip=Image.frombytes('RGB',(n_px,1),bytes(rgb_bytes))
        n_colors=min(n_avail,255)
        pal_img=strip.quantize(colors=n_colors,method=Image.Quantize.MEDIANCUT)
    # 4. 写入 block.palette 的空位, 记录 pal_idx -> block_slot
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
    # 5. 对每个 sub 用共享 palette 做量化 (dither=0 避免抖动破坏纯色块)
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
            pixels=bytearray(w*h)  # 全透明
        frame=JVGFrame(); frame.width=w; frame.height=h
        frame.alpha=alpha; frame.pixels=bytes(pixels)
        frame.encoded_data,frame.row_count=_encode_rle_game(frame.pixels,frame.alpha,w,h)
        frame.x_max=(w-1 if w-1<32768 else w-1-65536)
        frame.y_max=(h-1 if h-1<32768 else h-1-65536)
        frame._palette=None
        results.append(frame)
    return results

def _align_anchor(new_f:JVGFrame,old_f:JVGFrame,mode:str="bottom_center")->None:
    """将新帧的偏移 (x_max, y_max) 对齐到旧帧锚点, 保持其在游戏中的视觉位置。

    游戏引擎中 x_max/y_max 为精灵右下角相对实体锚点的偏移 (signed int16)。
    当替换图尺寸与原图不同时, 需要重新计算使视觉锚点保持一致。
    模式:
      - bottom_center: 底边中心对齐 (适合角色精灵, 锚点在脚底)
      - center:        bbox 中心对齐 (适合物体/特效)
      - topleft:       左上角对齐 (保持 x_off, y_off 不变)
    """
    if old_f.width<=0 or old_f.height<=0: return
    if new_f.width<=0 or new_f.height<=0: return
    old_xm=_u16s(old_f.x_max); old_ym=_u16s(old_f.y_max)
    old_x_off=old_xm-old_f.width+1; old_y_off=old_ym-old_f.height+1
    if mode=="bottom_center":
        old_cx=old_xm-(old_f.width-1)/2.0
        new_x_off=int(round(old_cx-(new_f.width-1)/2.0))
        new_f.x_max=(new_x_off+new_f.width-1)&0xFFFF
        new_f.y_max=old_ym&0xFFFF  # 底边保持
    elif mode=="center":
        old_cx=old_xm-(old_f.width-1)/2.0; old_cy=old_ym-(old_f.height-1)/2.0
        new_x_off=int(round(old_cx-(new_f.width-1)/2.0))
        new_y_off=int(round(old_cy-(new_f.height-1)/2.0))
        new_f.x_max=(new_x_off+new_f.width-1)&0xFFFF
        new_f.y_max=(new_y_off+new_f.height-1)&0xFFFF
    else:  # topleft
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
                if greenscreen_set and idx in greenscreen_set: continue
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
        self.root=root; self.root.title("JVG 图集编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico): self.root.iconbitmap(default=ico)
        self.root.geometry("1280x800")
        self.jvg:Optional[JVGFile]=None; self._bi=-1; self._fi=0; self._sel_fi=-1
        self._view="tile"; self._tile_cols=tk.IntVar(value=0); self._anim_job=None
        self._greenscreen_remove=tk.BooleanVar(value=True)
        self._photos={}; self._detail_imgs={}
        self._setup_menu(); self._setup_ui()
        if filepath and os.path.exists(filepath): self._open(filepath)
        else: self._new()
        self.root.protocol("WM_DELETE_WINDOW",self._on_close)
        sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
        x = (sw - 1280) // 2; y = (sh - 800) // 2
        self.root.geometry(f'1280x800+{x}+{y}')

    def _setup_menu(self):
        mb=tk.Menu(self.root)
        fm=tk.Menu(mb,tearoff=0)
        fm.add_command(label="新建 Ctrl+N",command=self._new)
        fm.add_command(label="打开 Ctrl+O",command=self._open_dlg)
        fm.add_command(label="保存 Ctrl+S",command=self._save)
        fm.add_command(label="另存为...",command=self._save_as)
        fm.add_separator()
        em=tk.Menu(fm,tearoff=0)
        em.add_command(label="导出选中",command=lambda:self._export("single"))
        em.add_command(label="导出分组",command=lambda:self._export("group"))
        em.add_command(label="导出图集",command=lambda:self._export("grid"))
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

        bf=ttk.LabelFrame(lf,text="操作",padding=4); bf.pack(fill=tk.X,padx=4,pady=4)
        ttk.Button(bf,text="添加图片",command=self._add_images).pack(fill=tk.X,pady=2)
        ttk.Button(bf,text="替换选中",command=self._replace_frame).pack(fill=tk.X,pady=2)
        ttk.Button(bf,text="导入图集",command=self._batch_replace_gridsheet).pack(fill=tk.X,pady=2)
        ttk.Button(bf,text="删除选中",command=self._del_frame).pack(fill=tk.X,pady=2)

        ef=ttk.LabelFrame(lf,text="导出",padding=4); ef.pack(fill=tk.X,padx=4,pady=4)
        ttk.Button(ef,text="导出选中",command=lambda:self._export("single")).pack(fill=tk.X,pady=1)
        ttk.Button(ef,text="导出分组",command=lambda:self._export("group")).pack(fill=tk.X,pady=1)
        ttk.Button(ef,text="导出图集",command=lambda:self._export("grid")).pack(fill=tk.X,pady=1)

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
        ttk.Checkbutton(tb,text="去绿幕",variable=self._greenscreen_remove,
                        command=lambda:self._refresh_view()).pack(side=tk.LEFT,padx=4)
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=4,pady=2)
        ttk.Label(tb,text="速度:").pack(side=tk.LEFT)
        def _validate_speed(P):
            if P=="": return True
            try: v=int(P); return 10<=v<=2000
            except: return False
        vcmd=(self.root.register(_validate_speed),'%P')
        self._speed=tk.IntVar(value=120)
        ttk.Spinbox(tb,textvariable=self._speed,width=5,from_=10,to=2000,increment=10,
                    validate='key',validatecommand=vcmd).pack(side=tk.LEFT,padx=2)
        ttk.Label(tb,text="ms").pack(side=tk.LEFT)
        ttk.Separator(tb,orient=tk.VERTICAL).pack(side=tk.LEFT,fill=tk.Y,padx=4,pady=2)
        self._zoom=tk.DoubleVar(value=1.0)
        self._zoom_label=ttk.Label(tb,text="100%",width=5)
        self._zoom_label.pack(side=tk.RIGHT)
        ttk.Button(tb,text="+",width=2,command=lambda:self._zoom_step(0.5)).pack(side=tk.RIGHT,padx=1)
        ttk.Button(tb,text="−",width=2,command=lambda:self._zoom_step(-0.5)).pack(side=tk.RIGHT,padx=1)
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
        self._canvas.bind("<MouseWheel>",self._on_mousewheel)
        # Pan via click-drag
        self._pan_x=0; self._pan_y=0; self._pan_start=None
        self._canvas.bind("<ButtonPress-2>",self._pan_start_fn)
        self._canvas.bind("<B2-Motion>",self._pan_move_fn)
        self._canvas.bind("<ButtonRelease-2>",self._pan_end_fn)
        # Ctrl+Left drag also pans
        self._canvas.bind("<Control-ButtonPress-1>",self._pan_start_fn)
        self._canvas.bind("<Control-B1-Motion>",self._pan_move_fn)

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
            self._blist.see(new_idx)

    def _on_block_sel(self,ev=None):
        sel=self._blist.curselection()
        if sel: self._bi=sel[0]; self._fi=0; self._sel_fi=-1; self._kill_anim(); self._refresh_view()

    def _add_block(self):
        if not self.jvg: self.jvg=JVGFile()
        name = f"block_{len(self.jvg.blocks):02d}"
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
            blk=self.jvg.blocks[self._bi]
            for f in frames:
                if f._palette: _remap_to_block_palette(f,blk)
            blk.frames.extend(frames)
            self._sync_list(); self._refresh_view()
            self._info.config(text=f"导入 {len(frames)} 帧")

    def _replace_frame(self):
        if not self.jvg or self._bi<0 or self._sel_fi<0: return messagebox.showinfo("提示","请先在平铺视图中点击选中一帧")
        blk=self.jvg.blocks[self._bi]
        if self._sel_fi>=blk.frame_count: return
        paths=filedialog.askopenfilenames(title="选择替换图片",filetypes=[("图片","*.png *.bmp *.jpg *.jpeg")])
        if not paths: return
        frames=import_images([paths[0]])  # only first file
        if frames:
            new_f=frames[0]
            old_f=blk.frames[self._sel_fi]
            _align_anchor(new_f,old_f,mode="bottom_center")  # 保持原帧视觉锚点
            if new_f._palette: _remap_to_block_palette(new_f,blk)
            blk.frames[self._sel_fi]=new_f
            self._sync_list(); self._kill_anim(); self._refresh_view()
            self._info.config(text=f"已替换帧 #{self._sel_fi} (偏移已自动对齐)")

    def _del_frame(self):
        if not self.jvg or self._bi<0: return
        blk=self.jvg.blocks[self._bi]
        if self._sel_fi>=0 and self._sel_fi<blk.frame_count:
            del blk.frames[self._sel_fi]
            self._sel_fi=-1; self._sync_list(); self._kill_anim(); self._refresh_view()

    def _batch_replace_gridsheet(self):
        """导入组图: 选择一张已导出的 Gridsheet 图片, 按用户输入的 cols/rows/gap 拆分。

        有有效帧时替换对应帧; 空分组时新增帧。
        """
        if not self.jvg or self._bi<0: return messagebox.showinfo("提示","请先选择分组")
        blk=self.jvg.blocks[self._bi]
        valid_list=[(i,f) for i,f in enumerate(blk.frames) if f.width>0 and f.height>0]
        n_valid=len(valid_list)
        is_new_block = (n_valid == 0)
        path=filedialog.askopenfilename(title="选择 Gridsheet 图片",
                                        filetypes=[("图片","*.png *.bmp *.jpg *.jpeg")])
        if not path: return
        try: gs=Image.open(path).convert('RGBA')
        except Exception as e: return messagebox.showerror("打开失败",str(e))
        gs_w,gs_h=gs.size
        # 参数输入: columns / rows / padding
        cur_cols=self._tile_cols.get() if self._tile_cols.get()>0 else max(1,int(math.ceil(math.sqrt(max(n_valid,1)))))
        cols=simpledialog.askinteger("导入组图",f"columns (共 {n_valid} 帧):",parent=self.root,
                                     initialvalue=cur_cols,minvalue=1,maxvalue=256)
        if cols is None: return
        cur_rows=max(1,int(math.ceil(max(n_valid,1)/cols)))
        rows=simpledialog.askinteger("导入组图",f"rows (共 {n_valid} 帧, cols={cols}):",parent=self.root,
                                     initialvalue=cur_rows,minvalue=1,maxvalue=256)
        if rows is None: return
        cur_pad=max(0,self._padding.get())
        pad=simpledialog.askinteger("导入组图","padding / gap (像素):",parent=self.root,
                                    initialvalue=cur_pad,minvalue=0,maxvalue=256)
        if pad is None: return
        # 容量校验
        if not is_new_block and cols*rows<n_valid:
            if not messagebox.askyesno("容量不足",
                f"cols×rows = {cols}×{rows} = {cols*rows} < 有效帧数 {n_valid}\n"
                f"后 {n_valid-cols*rows} 帧将不会被替换。是否继续?"):
                return
        # 按用户输入直接计算 cell 尺寸
        cw_num=gs_w-max(0,cols-1)*pad
        ch_num=gs_h-max(0,rows-1)*pad
        if cw_num<=0 or ch_num<=0 or cw_num%cols!=0 or ch_num%rows!=0:
            return messagebox.showerror("尺寸错误",
                f"图片尺寸 {gs_w}×{gs_h} 无法整除为 {cols}×{rows} 个 cell (pad={pad})\n"
                f"cw_num={cw_num}, ch_num={ch_num}\n请确认 columns / rows / padding 参数")
        cw=cw_num//cols; ch=ch_num//rows
        # 虚拟坐标原点 (与 export_gridsheet 一致)
        if is_new_block:
            min_vl=0; min_vt=0
        else:
            vrs=[(_u16s(f.x_max)-f.width+1,_u16s(f.y_max)-f.height+1) for _,f in valid_list]
            min_vl=min(r[0] for r in vrs); min_vt=min(r[1] for r in vrs)
        # 第一遍: 裁剪每个非空 cell 的 sub 图
        self._info.config(text=f"导入组图: 裁剪 cell..."); self.root.update()
        subs=[]; metas=[]; replace_set=set()
        max_cells=cols*rows
        skipped=0
        if is_new_block:
            # 空分组: 遍历所有 cell, 非空的作为新帧添加
            for cell_idx in range(max_cells):
                ri=cell_idx//cols; ci=cell_idx%cols
                cx=ci*(cw+pad); cy=ri*(ch+pad)
                if cx+cw>gs_w or cy+ch>gs_h:
                    skipped+=1; continue
                cell=gs.crop((cx,cy,cx+cw,cy+ch))
                bbox=cell.getchannel('A').getbbox()
                if bbox is None:
                    skipped+=1; continue
                l,t,r,b=bbox
                sub=cell.crop((l,t,r,b))
                new_x_max=(min_vl+r-1)&0xFFFF
                new_y_max=(min_vt+b-1)&0xFFFF
                subs.append(sub)
                metas.append((new_x_max,new_y_max))
        else:
            for cell_idx,(blk_fi,_old_f) in enumerate(valid_list):
                if cell_idx>=max_cells:
                    skipped+=1; continue
                ri=cell_idx//cols; ci=cell_idx%cols
                cx=ci*(cw+pad); cy=ri*(ch+pad)
                if cx+cw>gs_w or cy+ch>gs_h:
                    skipped+=1; continue
                cell=gs.crop((cx,cy,cx+cw,cy+ch))
                bbox=cell.getchannel('A').getbbox()
                if bbox is None:
                    skipped+=1; continue
                l,t,r,b=bbox
                sub=cell.crop((l,t,r,b))
                new_x_max=(min_vl+r-1)&0xFFFF
                new_y_max=(min_vt+b-1)&0xFFFF
                subs.append(sub); metas.append((blk_fi,new_x_max,new_y_max))
                replace_set.add(blk_fi)
        # 第二遍: 统一量化 (共享调色板, 避免掉色)
        self._info.config(text=f"导入组图: 统一量化 {len(subs)} 帧..."); self.root.update()
        keep_indices=[i for i in range(len(blk.frames)) if i not in replace_set]
        new_frames=_batch_quantize_subs_to_block(subs,blk,keep_indices)
        # 第三遍: 写回 block
        if is_new_block:
            for (xm,ym),nf in zip(metas,new_frames):
                nf.x_max=xm; nf.y_max=ym
                blk.frames.append(nf)
        else:
            for (blk_fi,xm,ym),nf in zip(metas,new_frames):
                nf.x_max=xm; nf.y_max=ym
                blk.frames[blk_fi]=nf
        self._sync_list(); self._kill_anim(); self._refresh_view()
        self._info.config(text=f"导入组图完成: {'新增' if is_new_block else '替换'} {len(new_frames)} 帧, 跳过 {skipped} 空cell (cell={cw}×{ch})")

    def _nav(self,d:int):
        if self._view!="single": return
        if not self.jvg or self._bi<0: return
        blk=self.jvg.blocks[self._bi]; self._fi=(self._fi+d)%max(1,blk.frame_count)
        self._sel_fi=self._fi; self._refresh_view()

    # ── Zoom & Pan ──────────────────────────────────
    def _zoom_step(self,delta:float):
        z=max(0.5,min(5.0,self._zoom.get()+delta)); self._zoom.set(z)
        self._zoom_label.config(text=f"{int(z*100)}%")
        self._kill_anim(); self._refresh_view()
    def _on_mousewheel(self,ev):
        if ev.state&0x4:  # Ctrl+Wheel → zoom
            delta=0.5 if ev.delta>0 else -0.5; self._zoom_step(delta)
        elif ev.state&0x1:  # Shift+Wheel → horizontal scroll
            self._canvas.xview_scroll(-ev.delta//120,"units")
        else:  # default → vertical scroll
            self._canvas.yview_scroll(-ev.delta//120,"units")
    def _pan_start_fn(self,ev): self._pan_start=(ev.x,ev.y)
    def _pan_move_fn(self,ev):
        if self._pan_start:
            dx=ev.x-self._pan_start[0]; dy=ev.y-self._pan_start[1]
            self._canvas.xview_scroll(-dx,"units"); self._canvas.yview_scroll(-dy,"units")
            self._pan_start=(ev.x,ev.y)
    def _pan_end_fn(self,ev): self._pan_start=None

    # ── Views ────────────────────────────────────────
    def _set_view(self,mode:str): self._view=mode; self._kill_anim(); self._refresh_view()

    def _get_pal(self,blk:JVMBlock,f:JVGFrame)->PaletteRGB565:
        return f._palette if f._palette else blk.palette

    def _f2tk(self,f:JVGFrame,pal:PaletteRGB565,scale:float=1.0)->Optional[ImageTk.PhotoImage]:
        scale*=self._zoom.get()
        w,h=f.width,f.height
        if w<=0 or h<=0: return None
        no_green=self._greenscreen_remove.get()
        if no_green:
            green_set={i for i,e in enumerate(pal.entries) if e==0x07E0}
        pr=pal.to_rgb888(); rgba=bytearray(w*h*4)
        for y in range(h):
            for x in range(w):
                p=y*w+x; off=p*4
                if p<len(f.alpha) and f.alpha[p]==0: continue
                idx=f.pixels[p] if p<len(f.pixels) else 0
                if no_green and idx in green_set: continue
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
        z=self._zoom.get()
        # Default: show at original size. Auto-calc columns from canvas width.
        if cols<=0:
            cw=self._canvas.winfo_width()
            # estimate max frame width at current zoom
            max_w=max((f.width for f in frames if f.width>0),default=64)
            cols=max(1,int((cw-10)/(max_w*z+6)))
        x,y,rh=10,10,0; col=0
        for fi,f in enumerate(frames):
            if f.width<=0: continue
            pal=self._get_pal(blk,f)
            img=self._f2tk(f,pal,1.0)  # _f2tk already applies zoom internally
            if not img: continue
            self._photos[fi]=img
            dw,dh=int(f.width*z),int(f.height*z)
            tid=self._canvas.create_image(x,y,anchor=tk.NW,image=img,tags=("frame",str(fi)))
            self._canvas.tag_bind(tid,"<Button-1>",lambda e,i=fi:self._on_frame_click(i))
            if fi==self._sel_fi:
                self._canvas.create_rectangle(x,y,x+dw,y+dh,outline="#0f0",width=2,tags=("sel",))
            self._canvas.create_text(x+2,y+2,text=str(fi),fill="#0f0",font=("",7),anchor=tk.NW)
            x+=dw+4; rh=max(rh,dh); col+=1
            if col>=cols: x=10; y+=rh+8; rh=0; col=0
        y+=rh+20
        self._canvas.configure(scrollregion=(0,0,max(600,cols*(int(max((f.width for f in frames if f.width>0),default=64)*z)+4)+20),y))
        self._info.config(text=f"平铺 — {len(frames)}帧, 列数={cols}, {int(z*100)}%")

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
        no_green=self._greenscreen_remove.get()
        for fi,f in enumerate(frames):
            if f.width<=0: self._anim_data.append(None); continue
            pal=self._get_pal(blk,f); pr=pal.to_rgb888()
            if no_green:
                green_set={i for i,e in enumerate(pal.entries) if e==0x07E0}
            ox=(_u16s(f.x_max)-f.width+1-min_vl); oy=(_u16s(f.y_max)-f.height+1-min_vt)
            rgba=bytearray(scw*sch*4)
            for py in range(f.height):
                for px in range(f.width):
                    p=py*f.width+px
                    if p<len(f.alpha) and f.alpha[p]==0: continue
                    idx=f.pixels[p] if p<len(f.pixels) else 0
                    if no_green and idx in green_set: continue
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
        gs=None
        if self._greenscreen_remove.get():
            gs={i for i,e in enumerate(blk.palette.entries) if e==0x07E0}
        if mode=="single":
            if self._sel_fi<0 or self._sel_fi>=blk.frame_count:
                messagebox.showinfo("提示","请先在平铺视图中点击选中一帧")
                return
            p=filedialog.asksaveasfilename(title="导出帧",defaultextension=".png",filetypes=[("PNG","*.png")])
            if not p: return
            f=blk.frames[self._sel_fi]; pal=self._get_pal(blk,f)
            export_single(f,pal,p,gs); self._info.config(text=f"已导出 {Path(p).name}")
        elif mode=="group":
            d=filedialog.askdirectory(title="选择导出目录")
            if not d: return
            export_group(blk,d,greenscreen_set=gs)
            self._info.config(text=f"已导出 {blk.frame_count} 帧到 {d}")
        elif mode=="grid":
            d=filedialog.askdirectory(title="选择导出目录")
            if not d: return
            export_gridsheet(blk,d,padding=self._padding.get(),columns=self._tile_cols.get(),greenscreen_set=gs)
            self._info.config(text=f"已导出 gridsheet (padding={self._padding.get()}) 到 {d}")

# ── Entry ──────────────────────────────────────────
def main():
    root=tk.Tk(); fp=sys.argv[1] if len(sys.argv)>1 else None
    app=JVGEditor(root,fp); root.mainloop()

if __name__=="__main__":
    if not HAS_PIL: print("需要 Pillow: pip install Pillow"); sys.exit(1)
    main()
