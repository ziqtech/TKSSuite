# -*- coding: utf-8 -*-
"""widescreen_16_9 的 cave 代码 (patch_sites 型补丁)。

三类 cave:

1. 页面画布行拷贝 (grab_copy / push_copy): 页面对象内嵌画布仍是 640x480
   (行距 1280B), 与视频内存 (行距 lPitch) 之间的整块 memcpy 会行错位, 改为
   按 size 逐行拷贝。⚠ 必须遵循 size 参数: 存在 size=0 的调用 (src=NULL),
   原版 memcpy 直接返回, 忽略 size 会从 NULL 读 480 行 -> 访问违例。

2. 绘制步长 wrapper (init_stride / wrap_page_*): 绘制原语步长是运行时全局
   STRIDE_GLOBAL (屏幕 856 / 页面 640)。⚠ wrapper 不能用 `call page_fn`
   (多压返回地址使被调函数参数整体错位 4 字节 -> Access violation), 必须用
   "尾调用 + 替换自身返回地址为桩"。

3. GXP 加载器适配 (gxp_pad_decide / gxp_upload): 全屏 640x480 的 gxp 背景
   表面按 856 宽创建 (内容靠左 + 右带黑), 上传改为逐行拷贝 — 否则
   `Blt(后备 856 <- 背景 640, NULL, NULL)` 尺寸不匹配会产生行错位拖影。

4. 鼠标双空间映射 (mouse_clamp / mouse_map_down / rec_map): 游戏主循环是
   独立线程, VCL 鼠标事件在主线程异步写入, 写入时刻页面 wrapper 几乎必然
   未激活 —— 按运行时步长换算永远得到 raw 值。[0x824278] 恒存 raw 窗口坐标
   (光标绘制/战斗/边缘卷屏消费), 另同步 PAGE_X = clamp(raw-108,0,639) 与
   点击记录副本 PAGE_REC_X, 供三个页面状态机内的读点改读 (与 TKSRemake
   `InputState::SetLogicalWidth` 的按当前逻辑画布取鼠标等价)。

5. 软件光标两步绘制 (cursor_scratch): JVG RLE 流按"640 宽屏幕反向线性扫描"
   编码 (TKSRemake DecodeRle 权威结论), skip/run 内嵌 640 行几何, 在 856 面
   上直接解码必行漂 216px (实测整屏拉丝)。光标改道: 先以步长 640 解码进
   640x480 虚拟屏幕, 再把帧矩形按真实步长 blit 到后备表面 (哨兵色透明)。

通用约定: 保存/恢复 ebx/esi/edi/ebp; rep movs/stos 前 cld; 用 cdecl 语义。
"""

import struct

BAND_DWORDS = (856 - 640) * 2 // 4   # 右带清零 dwords (856 -> 108)
W_SCREEN = 856
W_PAGE = 640
SCREEN_PITCH = W_SCREEN * 2          # 1712 (16 字节对齐, 无填充)

STRIDE_GLOBAL_RVA = 0x260800         # .data BSS 空闲槽: 绘制步长
RET_GLOBAL_RVA = 0x260804            # 同上: 暂存调用者返回地址
PAD_GLOBAL_RVA = 0x260808            # 同上: 全屏 gxp 已按 856 建面的标志
EAX_SAVE_RVA = 0x26080C              # 同上: Blt cave 暂存 eax (dst 对象)
RET2_SAVE_RVA = 0x260810             # 同上: Blt cave 暂存返回地址 (跨 DD 调用)
RECT_GLOBAL_RVA = 0x260814           # 同上: Blt cave 的源 RECT {0,0,W,H} (16B)
DESC_PTR_RVA = 0x260824              # 同上: Blt cave 的 DDSURFACEDESC 缓冲指针
OFF_GLOBAL_RVA = 0x260828            # 同上: 页面居中偏移 (px): 页面 = (856-640)/2, 游戏 = 0
DST_RECT_RVA = 0x26082C              # 同上: Blt cave 的目标 RECT (含居中偏移, 16B, 至 0x26083B)
END_GLOBAL_RVA = 0x26083C            # 同上: 表面末行指针偏移 479*行距 (页面 0x95B00/游戏 0xC82D0)
# ⚠ END 不能放在 0x260830 — 那在 DST_RECT (0x26082C..0x26083B) 内部, 互相覆盖。
PAGE_X_RVA = 0x260840                # 鼠标 X 的页面逻辑坐标 = clamp(raw-108, 0, 639)
PAGE_REC_X_RVA = 0x260844            # 点击记录 78E25E 的页面逻辑坐标副本
SCRATCH_SIZE = 0x96000               # 640*480*2
CUR_W_RVA = 0x26084C                 # 以下 10 槽为 cursor_scratch 的瞬时变量 (仅游戏线程)
CUR_H_RVA = 0x260850
CUR_XO_RVA = 0x260854
CUR_YO_RVA = 0x260858
CUR_STRIDE_SV_RVA = 0x26085C
CUR_GEND_SV_RVA = 0x260860
CUR_CX0_RVA = 0x260864
CUR_CX1_RVA = 0x260868
CUR_CY0_RVA = 0x26086C
CUR_CY1_RVA = 0x260870
CUR_PX_RVA = 0x260874                # 光标自擦除: 上一帧绘制点 X (raw)
CUR_PY_RVA = 0x260878                # 同上: Y
BK_VALID_RVA = 0x26087C              # 同上: backing store 有效标志
BK_DST_RVA = 0x260880                # 同上: 上一帧绘制目标表面
BK_STRIDE_RVA = 0x260884             # 同上: 上一帧行距
BK_X0_RVA = 0x260888                 # 同上: 上一帧矩形 x0
BK_Y0_RVA = 0x26088C                 # 同上: y0
BK_W_RVA = 0x260890                  # 同上: 宽 (px)
BK_H_RVA = 0x260894                  # 同上: 高 (px)
# ⚠ scratch 必须放在所有槽位之后 (否则 rep stosd 清屏会把槽位一起清掉)
SCRATCH_RVA = 0x260898               # 640x480 虚拟屏幕 (RLE 解码用)
# 光标背景快照 (256x128px, 覆盖 Cur.JVG 最大帧 227x108): 下一帧恢复用
BKBUF_SIZE = 256 * 128 * 2           # 0x10000
BKBUF_RVA = SCRATCH_RVA + SCRATCH_SIZE   # 0x2F6898 .. 0x306897
PAGE_OFF = (856 - 640) // 2          # 108: 640 画布在 856 窗口内居中, 两侧各 108 黑边
BK_MAX_W, BK_MAX_H = 256, 128        # 超出则该帧不做自擦除 (只画不擦)

# ── globals 重定位 (运行时搬离 .data) ──────────────────────────────────
# ⚠ 实测 (2026-09-11): 0x660878 起的 0x96000 "BSS 空闲区" 并不空闲 — 启动
# 阶段锚点带 (行 238..277) 已有 3334 个非零游戏像素 (游戏经计算指针使用该区,
# .text 无 disp32 引用 ≠ 无人使用)。cave 每帧 rep stosd 填充 0x96000 字节会
# 持续覆盖游戏数据, 反之游戏也可能踩坏槽位 (g_stride 等)。
# 方案: 引擎按 patch.json 的 globals_* 声明把整块 (槽位 + scratch + 光标
# backing) VirtualAllocEx 到独立内存, 并把 cave 字节与位点 repl 中落在
# 重定位窗口内的 4 字节绝对地址统一 +delta — 与 warpc 占位符替换同一思路。
# 窗口 = 槽位区 [base, base+span) (含 scratch 基址) + 精确单值窗口 (BKBUF
# 基址, span=1)。⚠ 窗口必须窄 — 宽窗口会对指令流里恰好同值的随机 4 字节
# 序列产生假阳性。
GLOBALS_PH_BASE = 0x400000 + 0x260800       # 占位基址 (= 槽位 0x660800)
GLOBALS_REBASE_SPAN = 0x99                  # 槽位窗口: 0x660800..0x660898 (含 scratch 基址)
GLOBALS_EXTRA_WINDOWS = ((BKBUF_RVA - 0x260800, 1),)   # BKBUF 基址精确窗口
GLOBALS_ALLOC_SIZE = (BKBUF_RVA - 0x260800) + BKBUF_SIZE   # 0x306898 → 页对齐

GXP_W_VA = 0x00A2B9A4                # gxp 头解析出的宽
GXP_H_VA = 0x00A2B9A8                # 高
MEMCPY_VA = 0x004B008C               # 原 memcpy

DD_INIT_FN = 0x44EC0C                # sub_44EC0C DD 初始化
PAGE_FUNCS = {
    'wrap_page_42131C': 0x42131C,
    'wrap_page_4240B8': 0x4240B8,
    'wrap_page_426164': 0x426164,
}


def _g_stride() -> bytes:
    return struct.pack('<I', 0x400000 + STRIDE_GLOBAL_RVA)


def _g_ret() -> bytes:
    return struct.pack('<I', 0x400000 + RET_GLOBAL_RVA)


def _g_pad() -> bytes:
    return struct.pack('<I', 0x400000 + PAD_GLOBAL_RVA)


def _g_eax() -> bytes:
    return struct.pack('<I', 0x400000 + EAX_SAVE_RVA)


def _g_ret2() -> bytes:
    return struct.pack('<I', 0x400000 + RET2_SAVE_RVA)


def _g_desc() -> bytes:
    return struct.pack('<I', 0x400000 + DESC_PTR_RVA)


def _g_off() -> bytes:
    return struct.pack('<I', 0x400000 + OFF_GLOBAL_RVA)


def _g_dst_rect() -> bytes:
    return struct.pack('<I', 0x400000 + DST_RECT_RVA)


def _g_end() -> bytes:
    return struct.pack('<I', 0x400000 + END_GLOBAL_RVA)


def _g_page_x() -> bytes:
    return struct.pack('<I', 0x400000 + PAGE_X_RVA)


def _g_page_rec_x() -> bytes:
    return struct.pack('<I', 0x400000 + PAGE_REC_X_RVA)


def _g_scratch() -> bytes:
    return struct.pack('<I', 0x400000 + SCRATCH_RVA)


def _g_bkbuf() -> bytes:
    return struct.pack('<I', 0x400000 + BKBUF_RVA)


def _cur(name: str) -> bytes:
    rva = {'w': CUR_W_RVA, 'h': CUR_H_RVA, 'xo': CUR_XO_RVA,
           'yo': CUR_YO_RVA, 'ssv': CUR_STRIDE_SV_RVA,
           'gsv': CUR_GEND_SV_RVA, 'cx0': CUR_CX0_RVA, 'cx1': CUR_CX1_RVA,
           'cy0': CUR_CY0_RVA, 'cy1': CUR_CY1_RVA,
           'px': CUR_PX_RVA, 'py': CUR_PY_RVA,
           'bv': BK_VALID_RVA, 'bd': BK_DST_RVA, 'bs': BK_STRIDE_RVA,
           'bx': BK_X0_RVA, 'by': BK_Y0_RVA, 'bw': BK_W_RVA,
           'bh': BK_H_RVA}[name]
    return struct.pack('<I', 0x400000 + rva)


def _end_of(rows: int, width: int) -> int:
    return rows * width * 2


# ── 1. 页面画布行拷贝 (居中: 左右各 108px 黑边) ─────────────────────────
def _copy_prologue() -> bytes:
    code = bytearray()
    code += b'\x55'                                  # push ebp
    code += b'\x8B\xEC'                              # mov ebp, esp
    code += b'\x56\x57\x53'                          # push esi;push edi;push ebx
    code += b'\xFC'                                  # cld
    return bytes(code)


_COPY_EPILOGUE = b'\x8B\x45\x08' + b'\x5B\x5F\x5E\x5D\xC3'   # mov eax,[ebp+8]; pop ebx,edi,esi,ebp; ret


def build_push_copy() -> bytes:
    """页画布(640x480,1280) -> 屏幕(856x480,lPitch), 居中放置并清两侧黑带。

    cdecl: [ebp+8]=dst(屏幕基址), [ebp+0xC]=src(画布基址), [ebp+0x10]=size(字节)。
    TKSRemake 语义: 640 逻辑画布在宽窗口内居中, 两侧对称黑边。
    """
    code = bytearray(_copy_prologue())
    code += b'\x8B\x5D\x08'                          # mov ebx,[ebp+8]   ; 屏幕行首
    code += b'\x8B\x55\x0C'                          # mov edx,[ebp+0xC] ; 画布行首
    code += b'\x8B\x75\x10'                          # mov esi,[ebp+0x10] ; 剩余字节
    code += b'\x81\xFE' + (1280).to_bytes(4, 'little')   # cmp esi,1280
    jl_done = len(code); code += b'\x7C\x00'
    l_loop = len(code)
    code += b'\x33\xC0'                              # xor eax,eax
    code += b'\x8B\xFB'                              # mov edi,ebx
    code += b'\xB9' + (PAGE_OFF * 2 // 4).to_bytes(4, 'little')   # mov ecx,54 ; 左黑带
    code += b'\xF3\xAB'                              # rep stosd
    code += b'\x56'                                  # push esi
    code += b'\x8B\xF2'                              # mov esi,edx
    code += b'\x8D\xBB' + (PAGE_OFF * 2).to_bytes(4, 'little')    # lea edi,[ebx+216]
    code += b'\xB9' + (320).to_bytes(4, 'little')    # mov ecx,320 ; 640px
    code += b'\xF3\xA5'                              # rep movsd
    code += b'\xB9' + (PAGE_OFF * 2 // 4).to_bytes(4, 'little')   # mov ecx,54 ; 右黑带
    code += b'\xF3\xAB'                              # rep stosd
    code += b'\x5E'                                  # pop esi
    code += b'\x03\x1D' + struct.pack('<I', 0xA2ACD8)            # add ebx,[lPitch]
    code += b'\x81\xC2' + (1280).to_bytes(4, 'little')           # add edx,1280
    code += b'\x81\xEE' + (1280).to_bytes(4, 'little')           # sub esi,1280
    code += b'\x81\xFE' + (1280).to_bytes(4, 'little')           # cmp esi,1280
    jae_loop = len(code); code += b'\x7D\x00'
    done = len(code)
    code += _COPY_EPILOGUE
    code[jl_done + 1] = (done - (jl_done + 2)) & 0xFF
    code[jae_loop + 1] = (l_loop - (jae_loop + 2)) & 0xFF
    return bytes(code)


def build_grab_copy() -> bytes:
    """屏幕(856x480,lPitch) -> 页画布(640x480,1280), 只抓取居中区域。

    cdecl: [ebp+8]=dst(画布基址), [ebp+0xC]=src(屏幕基址), [ebp+0x10]=size(字节)。
    与 push 方向互为逆: 跳过左侧 108px 黑带, 逐行取 640px。
    入口先执行 grab 时刻的光标擦除 (烤前清除, 见 grab_erase.py)。
    """
    code = bytearray(_copy_prologue())
    if not DISABLE_GRAB_ERASE:
        code += _build_grab_erase()
    code += b'\x8B\x5D\x08'                          # mov ebx,[ebp+8]   ; 画布行首
    code += b'\x8B\x55\x0C'                          # mov edx,[ebp+0xC] ; 屏幕行首
    code += b'\x81\xC2' + (PAGE_OFF * 2).to_bytes(4, 'little')    # add edx,216 ; 跳过左黑带
    code += b'\x8B\x75\x10'                          # mov esi,[ebp+0x10]
    code += b'\x81\xFE' + (1280).to_bytes(4, 'little')            # cmp esi,1280
    jl_done = len(code); code += b'\x7C\x00'
    l_loop = len(code)
    code += b'\x8B\xFB'                              # mov edi,ebx
    code += b'\x56'                                  # push esi
    code += b'\x8B\xF2'                              # mov esi,edx
    code += b'\xB9' + (320).to_bytes(4, 'little')    # mov ecx,320
    code += b'\xF3\xA5'                              # rep movsd
    code += b'\x5E'                                  # pop esi
    code += b'\x81\xC3' + (1280).to_bytes(4, 'little')            # add ebx,1280
    code += b'\x03\x15' + struct.pack('<I', 0xA2ACD8)            # add edx,[lPitch]
    code += b'\x81\xEE' + (1280).to_bytes(4, 'little')            # sub esi,1280
    code += b'\x81\xFE' + (1280).to_bytes(4, 'little')            # cmp esi,1280
    jae_loop = len(code); code += b'\x7D\x00'
    done = len(code)
    code += _COPY_EPILOGUE
    code[jl_done + 1] = (done - (jl_done + 2)) & 0xFF
    code[jae_loop + 1] = (l_loop - (jae_loop + 2)) & 0xFF
    return bytes(code)



# ── 2. 绘制步长 wrapper ────────────────────────────────────────────────
def build_stride_init() -> bytes:
    """尾调用 DD 初始化, 期间把步长全局置为屏幕宽 (不改变其参数布局)。"""
    code = bytearray()
    code += b'\xC7\x05' + _g_stride() + struct.pack('<I', W_SCREEN)
    code += b'\xC7\x05' + _g_off() + struct.pack('<I', 0)      # 游戏态: 无居中偏移
    code += b'\xC7\x05' + _g_end() + struct.pack('<I', _end_of(479, W_SCREEN))
    code += b'\xB8' + struct.pack('<I', DD_INIT_FN)
    code += b'\xFF\xE0'                              # jmp eax (尾调用)
    return bytes(code)


def build_page_wrapper(page_fn: int) -> bytes:
    """页面状态机: 设 640/居中 108 -> 尾调用 -> 桩恢复 856/0 -> 回到调用者。

    与 TKSRemake `InputState::SetLogicalWidth(FrameCanvasWidth())` 等价:
    页面期间逻辑宽 640 且居中偏移 108, 游戏期间逻辑宽 856、无偏移。
    ⚠ 桩不得破坏 EAX — 标题循环 `dword_4E8064 = sub_426164(...)` 取返回值,
    旧桩 `mov eax,[g_ret]; jmp eax` 把返回值覆盖成返回地址 (0x412D9A), 循环
    首帧即 break, 菜单永不交互 (实测 4E8064 恒为 0x412D9A 实锤)。改用
    `push [g_ret] ... ret` 恢复返回地址, 全程不触碰 EAX。
    """
    code = bytearray()
    code += b'\xC7\x05' + _g_stride() + struct.pack('<I', W_PAGE)
    code += b'\xC7\x05' + _g_off() + struct.pack('<I', PAGE_OFF)
    code += b'\xC7\x05' + _g_end() + struct.pack('<I', _end_of(479, W_PAGE))
    code += b'\xA1' + struct.pack('<I', FONT_OBJ_PTR_VA)          # mov eax,[fontobj]
    code += b'\xC7\x40' + bytes([FONT_PITCH_OFF]) + struct.pack('<I', FONT_PITCH_CANVAS)  # mov [eax+0x28],320
    code += b'\x8B\x04\x24'                          # mov eax,[esp]
    code += b'\xA3' + _g_ret()                       # mov [g_ret],eax
    call_off = len(code)
    code += b'\xE8\x00\x00\x00\x00'                  # call $+5
    code += b'\x58'                                  # pop eax
    add_imm_off = len(code) + 1
    code += b'\x05\x00\x00\x00\x00'                  # add eax,<stub-(call_off+5)>
    code += b'\x89\x04\x24'                          # mov [esp],eax
    code += b'\xB8' + struct.pack('<I', page_fn)
    code += b'\xFF\xE0'                              # jmp eax
    stub_off = len(code)
    code += b'\xFF\x35' + _g_ret()                   # push dword [g_ret]
    code += b'\x50'                                  # push eax ; ⚠ 保存页面函数返回值
    code += b'\xC7\x05' + _g_stride() + struct.pack('<I', W_SCREEN)
    code += b'\xC7\x05' + _g_off() + struct.pack('<I', 0)
    code += b'\xC7\x05' + _g_end() + struct.pack('<I', _end_of(479, W_SCREEN))
    code += b'\xA1' + struct.pack('<I', FONT_OBJ_PTR_VA)          # mov eax,[fontobj]
    code += b'\xC7\x40' + bytes([FONT_PITCH_OFF]) + struct.pack('<I', FONT_PITCH_SCREEN)  # mov [eax+0x28],428
    code += b'\x58'                                  # pop eax ; ⚠ 恢复返回值 (否则标题循环首帧 break)
    code += b'\xC3'                                  # ret (→ 调用者, EAX=页面返回值)
    code[add_imm_off:add_imm_off + 4] = ((stub_off - (call_off + 5)) & 0xFFFFFFFF).to_bytes(4, 'little')
    return bytes(code)


# ── 2b. 鼠标坐标双空间映射 ─────────────────────────────────────────────
# 游戏主循环跑在独立线程 (sub_412BE8 是线程入口), VCL 鼠标事件在主线程异步
# 写 [0x824278]/[0x82427C] —— 写入时刻 wrapper 几乎必然未激活 (步长=856/偏移
# =0), 所以按 g_stride/g_off 在写入时换算永远得到 raw 值, 页面态读到的坐标
# 会整体偏 108px。改为双空间: [0x824278] 恒存 raw 窗口坐标 (光标绘制/战斗
# 逻辑/边缘卷屏全部消费 raw), 另设 PAGE_X = clamp(raw-108, 0, 639) 供三个
# 被页面 wrapper 包住的状态机 (42131C/4240B8/426164 及其子函数, 24 个读点)
# 与点击记录副本 PAGE_REC_X 消费 —— 与 TKSRemake
# `InputState::SetLogicalWidth(FrameCanvasWidth())` 的"事件即按当前逻辑画布
# 钳制"语义等价, 只是二进制里按读方空间拆成两个全局。
def build_mouse_clamp() -> bytes:
    """替换 FormMouseMove `mov [0x824278],eax`: 存 raw 并同步 PAGE_X。

    语义: [0x824278] = raw (原版行为); PAGE_X = clamp(raw-108, 0, 639)。
    仅用 eax/ecx; edx 必须保留 (下一条 `mov [0x82427c],edx` 要用)。
    """
    code = bytearray()
    code += b'\xA3' + struct.pack('<I', 0x00824278)  # mov [0x824278],eax (原指令)
    code += b'\x59'                                  # pop ecx  ; 返回地址 (全程保留!)
    code += b'\x8D\x40' + struct.pack('<b', -PAGE_OFF)  # lea eax,[eax-108]
    code += b'\x85\xC0'                              # test eax,eax
    code += b'\x79\x02'                              # jns +2
    code += b'\x31\xC0'                              # xor eax,eax
    code += b'\x81\xF8\x80\x02\x00\x00'              # cmp eax,640
    code += b'\x72\x05'                              # jb +5 (跳过 mov eax,639 共5B)
    code += b'\xB8\x7F\x02\x00\x00'                  # mov eax,639
    code += b'\xA3' + _g_page_x()                    # mov [PAGE_X],eax
    code += b'\xFF\xE1'                              # jmp ecx
    return bytes(code)


def build_mouse_map_down() -> bytes:
    """替换 FormMouseDown `mov [0x824278],ecx` (6B): 存 raw 并同步 PAGE_X。

    入口 ecx=X, eax=Y (eax 必须保留, 下一条 `mov [0x82427c],eax` 要用);
    ecx/edx 此后立即被调用方重载, 可用。位点 6B = E8 rel32 + 1 NOP。
    """
    code = bytearray()
    code += b'\x89\x0D' + struct.pack('<I', 0x00824278)  # mov [0x824278],ecx (原指令)
    code += b'\x89\xCA'                              # mov edx,ecx
    code += b'\x59'                                  # pop ecx  ; 返回地址
    code += b'\x81\xEA' + struct.pack('<I', PAGE_OFF)   # sub edx,108
    code += b'\x79\x02'                              # jns +2
    code += b'\x31\xD2'                              # xor edx,edx
    code += b'\x81\xFA\x80\x02\x00\x00'              # cmp edx,640
    code += b'\x72\x05'                              # jb +5 (跳过 mov edx,639 共5B)
    code += b'\xBA\x7F\x02\x00\x00'                  # mov edx,639
    code += b'\x89\x15' + _g_page_x()                # mov [PAGE_X],edx
    code += b'\x41'                                  # inc ecx (跳过位点尾 NOP)
    code += b'\xFF\xE1'                              # jmp ecx
    return bytes(code)


def build_rec_map() -> bytes:
    """替换 sub_411C1C `mov [0x78E25E],eax`: 点击记录存 raw 并同步 PAGE_REC_X。

    点击记录 78E25E 的消费方分两族: 三个页面状态机内的 18 个读点要页面逻辑
    坐标 (改读 PAGE_REC_X), 名字输入页 (4258F0/425DB0, 直接画后备表面) 仍读
    raw。eax 保留非必需但顺手; edx/ecx 调用方随后重载。
    """
    code = bytearray()
    code += b'\xA3' + struct.pack('<I', 0x0078E25E)  # mov [0x78E25E],eax (原指令)
    code += b'\x59'                                  # pop ecx
    code += b'\x8D\x50' + struct.pack('<b', -PAGE_OFF)  # lea edx,[eax-108]
    code += b'\x85\xD2'                              # test edx,edx
    code += b'\x79\x02'                              # jns +2
    code += b'\x31\xD2'                              # xor edx,edx
    code += b'\x81\xFA\x80\x02\x00\x00'              # cmp edx,640
    code += b'\x72\x05'                              # jb +5 (跳过 mov edx,639 共5B)
    code += b'\xBA\x7F\x02\x00\x00'                  # mov edx,639
    code += b'\x89\x15' + _g_page_rec_x()            # mov [PAGE_REC_X],edx
    code += b'\xFF\xE1'                              # jmp ecx
    return bytes(code)


# ── 2c'. 软件光标: 640 虚拟屏幕解码 + blit ─────────────────────────────
# JVG 精灵 RLE 流按 TKSRemake DecodeRle 的权威结论是"沿 640 宽屏幕的反向线
# 性扫描流": skip/run 计数内嵌 640 平面的行几何, 跨行依赖连续显存隐式回绕。
# 目标面加宽到 856 后每跨一行漂 216px (实测表现为随光标移动的整屏拉丝),
# 常量替换无法消除 (数据里编码的是 640 平面几何)。等价 TKSRemake 的两步
# 方案 (先解码进 640 平面帧缓冲再单独 blit): 在 sub_411D18 调 sub_4544EC
# 的唯一位点改道 —— 先以步长 640 把光标帧解码进 640x480 虚拟屏幕 (右下角
# 锚点), 再把帧矩形按真实步长 blit 到后备表面 (哨兵色跳过透明)。
# 光标即可在任何鼠标位置 (含页面黑边) 正确显示。
DISABLE_GRAB_ERASE = False               # 二分开关: grab 前光标擦除
DISABLE_CURSOR_ERASE = False             # 光标自擦除 (Phase A) 已启用
DISABLE_CURSOR_SNAPSHOT = False          # 光标快照 (Phase B) 已启用
FONT_OBJ_PTR_VA = 0x00755B08            # 字体对象指针变量 dword_755B08
FONT_PITCH_OFF = 0x28                   # 对象内半行距字段偏移 (行距 = 2*该值)
FONT_PITCH_CANVAS = 320                 # 页面态: 640 画布行距的一半 (渲染器内 ×2)
FONT_PITCH_SCREEN = 428                 # 游戏态: 856 后备表面行距的一半
CURSOR_SENTINEL = 0xFE1F                # RGB565 品红系, 调色板色几乎不可能命中
CURSOR_PRIM_VA = 0x004544EC             # sub_4544EC


def build_cursor_scratch() -> bytes:
    """替换 sub_411D18 内 `call sub_4544EC` (0x411D4A): 640 虚拟屏幕解码+blit。

    入口栈 (cdecl 6 参, [esp]=返回地址): obj, X, Y, frame(word), dst, -1。
    帧几何 (对照 sub_4544EC 读法):
      w = u16 [[obj+0xC] + frame*2]      h = u16 [[obj+8] + frame*2]
      inner = [obj] + h*64               fd = [inner+0x2C] + [inner+0x28][frame]
      xOff = s16 [fd]                    yOff = s16 [fd+2]

    blit 矩形: 解码锚点取虚拟屏幕中心 (320,240), 与目标锚点 (X,Y) 对应:
      sx = x - X + 320, sy = y - Y + 240
      cx0 = max(x0, 0, X-320), cx1 = min(x1, stride-1, X+319)  (y 轴同理 ±240/479)
      (锚点居中使正/负 xOff/yOff 的帧都完整落在虚拟屏幕内)
    透明判定: 解码前把虚拟屏幕填哨兵色, blit 时跳过哨兵。
    寄存器: 栈帧 +X/edi +Y/ebx +行号/ebp, esi/edx/eax/ecx 为内层工作寄存器;
    全部 callee-saved 寄存器 (ebx/esi/edi/ebp) 入口保存出口恢复。
    """
    code = bytearray()

    def emit(b: bytes) -> None:
        code.extend(b)

    def j32(cond: str) -> int:
        op = {'jo': 0x80, 'jno': 0x81, 'jb': 0x82, 'jae': 0x83, 'je': 0x84,
              'jne': 0x85, 'jbe': 0x86, 'ja': 0x87, 'js': 0x88, 'jns': 0x89,
              'jp': 0x8A, 'jnp': 0x8B, 'jl': 0x8C, 'jge': 0x8D, 'jle': 0x8E,
              'jg': 0x8F}[cond]
        pos = len(code)
        emit(b'\x0F' + bytes([op]) + b'\x00\x00\x00\x00')
        return pos

    def jmp32() -> int:
        """E9 rel32 (5B), 回填方式与 j32 不同 (rel 在 pos+1)。"""
        pos = len(code)
        emit(b'\xE9\x00\x00\x00\x00')
        return pos

    def fix32(pos: int) -> None:
        code[pos + 2:pos + 6] = struct.pack('<i', len(code) - (pos + 6))

    emit(b'\x53\x56\x57\x55')                        # push ebx;esi;edi;ebp
    # [esp+0x10]=ret [0x14]=obj [0x18]=X [0x1C]=Y [0x20]=frame [0x24]=dst

    # ── Phase A: 上一帧光标自擦除 (逐像素归属恢复) ──
    # 不做整矩形校验: 游戏每帧只局部重绘 (动画/悬停高亮) 时, 整矩形校验会因
    # 局部变化而整体放弃恢复 → 未被覆盖的光标像素永久残留 (实测: 鼠标快速移动
    # 成串拖影)。改为逐像素归属判定: 仅当该像素仍精确等于本帧我们写入的值
    # (scratch 非哨兵 且 dst == scratch) 才恢复 BKBUF 背景; 被游戏其它绘制碰过
    # 的像素一律不动。scratch 此刻仍保有上一帧解码结果 (Phase B 才 refill)。
    emit(b'\xA1' + _cur('bv'))                       # mov eax,[BK_VALID]
    emit(b'\x85\xC0')                                # test eax,eax
    pa0 = j32('je')                                  # jz A_DONE (无效, 跳过)
    if DISABLE_CURSOR_ERASE:
        pa0 = jmp32()                                # 二分开关: 永远跳过擦除
    emit(b'\xA1' + _cur('bs'))                       # mov eax,[BK_STRIDE]
    emit(b'\x3B\x05' + _g_stride())                  # cmp eax,[g_stride]
    pa1 = j32('jne')                                 # jne A_DONE (表面/步长变了)
    emit(b'\x8B\x44\x24\x24')                        # mov eax,[esp+0x24] ; dst
    emit(b'\x3B\x05' + _cur('bd'))                   # cmp eax,[BK_DST]
    pa2 = j32('jne')                                 # jne A_DONE
    emit(b'\xA1' + _cur('bw'))                       # mov eax,[BK_W]
    emit(b'\x85\xC0')                                # test eax,eax
    pa3 = j32('je')                                  # jz A_DONE
    emit(b'\x3D' + struct.pack('<I', BK_MAX_W))      # cmp eax,256
    pa4 = j32('ja')                                  # ja A_DONE
    emit(b'\x8B\x0D' + _cur('bh'))                   # mov ecx,[BK_H]
    emit(b'\x85\xC9')                                # test ecx,ecx
    pa5 = j32('je')                                  # jz A_DONE
    emit(b'\x81\xF9' + struct.pack('<I', BK_MAX_H))  # cmp ecx,128
    pa6 = j32('ja')                                  # ja A_DONE
    emit(b'\xFC')                                    # cld
    emit(b'\x33\xED')                                # xor ebp,ebp ; y=0
    a_rrow = len(code)
    # dst 行指针 edi = dst + ((by+y)*stride + bx)*2
    emit(b'\x8B\xC5')                                # mov eax,ebp
    emit(b'\x03\x05' + _cur('by'))                   # add eax,[BK_Y0]
    emit(b'\x0F\xAF\x05' + _cur('bs'))               # imul eax,[BK_STRIDE]
    emit(b'\x03\x05' + _cur('bx'))                   # add eax,[BK_X0]
    emit(b'\x8D\x3C\x00')                            # lea edi,[eax+eax]
    emit(b'\x03\x7C\x24\x24')                        # add edi,[esp+0x24]
    # BK 行指针 esi = BKBUF + y*512 (256px)
    emit(b'\x8B\xF5')                                # mov esi,ebp
    emit(b'\xC1\xE6\x09')                            # shl esi,9
    emit(b'\x81\xC6' + _g_bkbuf())                   # add esi,BKBUF
    # scratch 行基址 ebx = SCRATCH + ((by+y - PY + 240)*640 + (bx - PX + 320))*2
    emit(b'\x8B\xC5')                                # mov eax,ebp
    emit(b'\x03\x05' + _cur('by'))                   # add eax,[BK_Y0]
    emit(b'\x2B\x05' + _cur('py'))                   # sub eax,[CUR_PY]
    emit(b'\x05\xF0\x00\x00\x00')                    # add eax,240
    emit(b'\x69\xC0\x80\x02\x00\x00')                # imul eax,eax,640
    emit(b'\x8B\x15' + _cur('bx'))                   # mov edx,[BK_X0]
    emit(b'\x2B\x15' + _cur('px'))                   # sub edx,[CUR_PX]
    emit(b'\x81\xC2\x40\x01\x00\x00')                # add edx,320
    emit(b'\x03\xC2')                                # add eax,edx
    emit(b'\x8D\x04\x00')                            # lea eax,[eax+eax] ; 像素索引→字节偏移(×2)
    emit(b'\x05' + _g_scratch())                     # add eax,SCRATCH
    emit(b'\x8B\xD8')                                # mov ebx,eax
    emit(b'\x8B\x0D' + _cur('bw'))                   # mov ecx,[BK_W] ; 列计数
    a_px = len(code)
    emit(b'\x66\x8B\x03')                            # mov ax,[ebx] ; 上帧解码值
    emit(b'\x66\x3D' + struct.pack('<H', CURSOR_SENTINEL))  # cmp ax,SENTINEL
    pa7 = j32('je')                                  # je A_NEXT (透明位: 未写过)
    emit(b'\x66\x3B\x07')                            # cmp ax,[edi] ; 仍是我们的值?
    pa8 = j32('jne')                                 # jne A_NEXT (被游戏改过, 不动)
    emit(b'\x66\x8B\x06')                            # mov ax,[esi] ; 快照背景
    emit(b'\x66\x89\x07')                            # mov [edi],ax ; 恢复
    # A_NEXT:
    code[pa7 + 2:pa7 + 6] = struct.pack('<i', len(code) - (pa7 + 6))
    code[pa8 + 2:pa8 + 6] = struct.pack('<i', len(code) - (pa8 + 6))
    emit(b'\x83\xC7\x02')                            # add edi,2
    emit(b'\x83\xC6\x02')                            # add esi,2
    emit(b'\x83\xC3\x02')                            # add ebx,2
    emit(b'\x49')                                    # dec ecx
    pa11 = j32('jne')                                # jne A_PX
    code[pa11 + 2:pa11 + 6] = struct.pack('<i', a_px - (pa11 + 6))
    emit(b'\x45')                                    # inc ebp
    emit(b'\x3B\x2D' + _cur('bh'))                   # cmp ebp,[BK_H]
    pa12 = j32('jb')                                 # jb A_ROW
    code[pa12 + 2:pa12 + 6] = struct.pack('<i', a_rrow - (pa12 + 6))
    # A_DONE = Phase A 结束处 (原流程入口):
    a_end = len(code)
    if DISABLE_CURSOR_ERASE:
        code[pa0 + 1:pa0 + 5] = struct.pack('<i', a_end - (pa0 + 5))
    else:
        code[pa0 + 2:pa0 + 6] = struct.pack('<i', a_end - (pa0 + 6))
    for pp in (pa1, pa2, pa3, pa4, pa5, pa6):
        code[pp + 2:pp + 6] = struct.pack('<i', a_end - (pp + 6))

    # ── 原始流程: 帧几何 ──
    emit(b'\x8B\x74\x24\x14')                        # mov esi,[esp+0x14] ; obj
    emit(b'\x85\xF6')                                # test esi,esi
    p = j32('je')                                    # jz DONE
    emit(b'\x8B\x7C\x24\x18')                        # mov edi,[esp+0x18] ; X
    emit(b'\x8B\x5C\x24\x1C')                        # mov ebx,[esp+0x1C] ; Y
    emit(b'\x0F\xB7\x44\x24\x20')                    # movzx eax,word [esp+0x20]
    emit(b'\x3B\x46\x18')                            # cmp eax,[esi+0x18]
    q = j32('jae')                                   # jae DONE
    emit(b'\x89\xC5')                                # mov ebp,eax ; frame
    # 对照 sub_4544EC 0x45450C..0x454571:
    #   V1    = u16 [[obj+0xC] + frame*2]     (块/sprite id)
    #   inner = [obj] + u16 [[obj+8] + frame*2] * 64
    #   bounds: V1 < u32 [inner]
    #   fd    = [inner+0x2C] + [inner+0x28][V1*4]
    #   xOff  = s16 [fd]   yOff = s16 [fd+2]
    #   w     = u16 [fd+4] h   = u16 [fd+6]   (帧头自带, 对应 TKSRemake
    #   Jvg.cpp: width=ReadU16(+4), xOff=xMax-width+1)
    emit(b'\x8B\x4E\x0C')                            # mov ecx,[esi+0xC]
    emit(b'\x0F\xB7\x04\x69')                        # movzx eax,word [ecx+ebp*2] ; V1
    emit(b'\x8B\x4E\x08')                            # mov ecx,[esi+8]
    emit(b'\x0F\xB7\x0C\x69')                        # movzx ecx,word [ecx+ebp*2]
    emit(b'\xC1\xE1\x06')                            # shl ecx,6
    emit(b'\x03\x0E')                                # add ecx,[esi] ; inner
    emit(b'\x3B\x01')                                # cmp eax,[ecx]
    q2 = j32('jae')                                  # V1 >= [inner] -> DONE
    emit(b'\x8B\x51\x28')                            # mov edx,[ecx+0x28]
    emit(b'\x8B\x14\x82')                            # mov edx,[edx+eax*4]
    emit(b'\x03\x51\x2C')                            # add edx,[ecx+0x2C] ; fd
    emit(b'\x0F\xBF\x02')                            # movsx eax,word [edx] ; xOff
    emit(b'\xA3' + _cur('xo'))                       # mov [XO],eax
    emit(b'\x0F\xBF\x42\x02')                        # movsx eax,word [edx+2] ; yOff
    emit(b'\xA3' + _cur('yo'))                       # mov [YO],eax
    emit(b'\x0F\xB7\x42\x04')                        # movzx eax,word [edx+4] ; w
    emit(b'\xA3' + _cur('w'))                        # mov [W],eax
    emit(b'\x85\xC0')                                # test eax,eax
    r = j32('je')                                    # jz DONE
    emit(b'\x0F\xB7\x42\x06')                        # movzx eax,word [edx+6] ; h
    emit(b'\xA3' + _cur('h'))                        # mov [H],eax
    # 步长/末行切 640 语义, 解码完还原
    emit(b'\xA1' + _g_stride())                      # mov eax,[STRIDE]
    emit(b'\xA3' + _cur('ssv'))                      # mov [SSV],eax
    emit(b'\xA1' + _g_end())                         # mov eax,[GEND]
    emit(b'\xA3' + _cur('gsv'))                      # mov [GSV],eax
    emit(b'\xC7\x05' + _g_stride() + struct.pack('<I', W_PAGE))
    emit(b'\xC7\x05' + _g_end() + struct.pack('<I', _end_of(479, W_PAGE)))
    emit(b'\xFC')                                    # cld
    emit(b'\xBF' + _g_scratch())                     # mov edi,SCRATCH
    emit(b'\xB9' + struct.pack('<I', SCRATCH_SIZE // 4))
    # ⚠ rep stosd 写 32 位双字 = 两个相邻 16 位像素, 哨兵必须在 EAX 高低半字
    # 各放一份 (0xFE1FFE1F)。只放 0x0000FE1F 会得到 FE1F,0000 交替棋盘格,
    # blit 时 0x0000 ≠ 哨兵被当不透明黑色逐列写入 → 光标变黑块 (实测确认)。
    emit(b'\xB8' + struct.pack('<I',
                               CURSOR_SENTINEL | (CURSOR_SENTINEL << 16)))
    emit(b'\xF3\xAB')                                # rep stosd
    # cdecl 参数自右向左压栈: (obj, X, Y, frame, dst, -1) → 先压 -1/dst/frame,
    # 再压 Y、X, 最后压 obj。⚠ frame 必须先于 Y/X 压栈 — 旧版把 Y/X 压在了
    # frame 之前, sub_4544EC 收到 a5(帧号)=240 ≥ 帧总数 119, 入口即返回,
    # 解码从不写入 → 光标区域只剩哨兵/黑棋盘 (实测 A5AExx 全零确认)。
    emit(b'\x6A\xFF')                                # push -1          (a7)
    emit(b'\x68' + _g_scratch())                     # push SCRATCH     (a6 = dst)
    emit(b'\x55')                                    # push ebp         (a5 = frame)
    emit(b'\x68\xF0\x00\x00\x00')                    # push 240         (a4 = Y)
    emit(b'\x68\x40\x01\x00\x00')                    # push 320         (a3 = X)
    emit(b'\x56')                                    # push esi         (a2 = obj)
    emit(b'\xB8' + struct.pack('<I', CURSOR_PRIM_VA))
    emit(b'\xFF\xD0')                                # call eax
    emit(b'\x83\xC4\x18')                            # add esp,0x18
    emit(b'\x8B\x05' + _cur('ssv'))                  # mov eax,[SSV]
    emit(b'\xA3' + _g_stride())                      # mov [STRIDE],eax
    emit(b'\x8B\x05' + _cur('gsv'))                  # mov eax,[GSV]
    emit(b'\xA3' + _g_end())                         # mov [GEND],eax
    # ── 计算裁剪矩形 (锚点 320,240) ──
    # edi/ebx 已被 primitive 破坏, 从栈上重取
    emit(b'\x8B\x7C\x24\x18')                        # mov edi,[esp+0x18] ; X
    emit(b'\x8B\x5C\x24\x1C')                        # mov ebx,[esp+0x1C] ; Y
    # x1 = X + XO (ecx); cx0 = max(x1-w+1, 0, X-320)
    emit(b'\x8B\x05' + _cur('xo'))                   # mov eax,[XO]
    emit(b'\x8D\x0C\x07')                            # lea ecx,[edi+eax] ; x1
    emit(b'\x89\xCA')                                # mov edx,ecx
    emit(b'\x2B\x15' + _cur('w'))                    # sub edx,[W]
    emit(b'\x42')                                    # inc edx ; x0
    emit(b'\x85\xD2')                                # test edx,edx
    p1 = j32('jns')
    emit(b'\x31\xD2')                                # xor edx,edx
    fix32(p1)
    emit(b'\x8D\x87' + struct.pack('<i', -320))      # lea eax,[edi-320]
    emit(b'\x3B\xD0')                                # cmp edx,eax
    p2 = j32('jge')
    emit(b'\x89\xC2')                                # mov edx,eax
    fix32(p2)
    emit(b'\x89\x15' + _cur('cx0'))                  # mov [CX0],edx
    # cx1 = min(x1, stride-1, X+319)
    emit(b'\x8B\x05' + _cur('ssv'))                  # mov eax,[SSV]
    emit(b'\x48')                                    # dec eax
    emit(b'\x39\xC1')                                # cmp ecx,eax
    p3 = j32('jle')
    emit(b'\x89\xC1')                                # mov ecx,eax
    fix32(p3)
    emit(b'\x8D\x87' + struct.pack('<i', 319))       # lea eax,[edi+319]
    emit(b'\x39\xC1')                                # cmp ecx,eax
    p4 = j32('jle')
    emit(b'\x89\xC1')                                # mov ecx,eax
    fix32(p4)
    emit(b'\x89\x0D' + _cur('cx1'))                  # mov [CX1],ecx
    # y1 = Y + YO; cy0 = max(y1-h+1, 0, Y-240); cy1 = min(y1, 479, Y+239)
    emit(b'\x8B\x05' + _cur('yo'))                   # mov eax,[YO]
    emit(b'\x8D\x0C\x03')                            # lea ecx,[ebx+eax] ; y1
    emit(b'\x89\xCA')                                # mov edx,ecx
    emit(b'\x2B\x15' + _cur('h'))                    # sub edx,[H]
    emit(b'\x42')                                    # inc edx
    emit(b'\x85\xD2')                                # test edx,edx
    p5 = j32('jns')
    emit(b'\x31\xD2')                                # xor edx,edx
    fix32(p5)
    emit(b'\x8D\x83' + struct.pack('<i', -240))      # lea eax,[ebx-240]
    emit(b'\x3B\xD0')                                # cmp edx,eax
    p6 = j32('jge')
    emit(b'\x89\xC2')                                # mov edx,eax
    fix32(p6)
    emit(b'\x89\x15' + _cur('cy0'))                  # mov [CY0],edx
    emit(b'\xB8\xDF\x01\x00\x00')                    # mov eax,479
    emit(b'\x39\xC1')                                # cmp ecx,eax
    p7 = j32('jle')
    emit(b'\x89\xC1')                                # mov ecx,eax
    fix32(p7)
    emit(b'\x8D\x83' + struct.pack('<i', 239))       # lea eax,[ebx+239]
    emit(b'\x39\xC1')                                # cmp ecx,eax
    p8 = j32('jle')
    emit(b'\x89\xC1')                                # mov ecx,eax
    fix32(p8)
    emit(b'\x89\x0D' + _cur('cy1'))                  # mov [CY1],ecx
    # 空矩形 → DONE
    emit(b'\xA1' + _cur('cx0'))                      # mov eax,[CX0]
    emit(b'\x3B\x05' + _cur('cx1'))                  # cmp eax,[CX1]
    p9 = j32('jg')                                   # jg DONE
    emit(b'\xA1' + _cur('cy0'))                      # mov eax,[CY0]
    emit(b'\x3B\x05' + _cur('cy1'))                  # cmp eax,[CY1]
    p10 = j32('jg')                                  # jg DONE
    # ── Phase B: 绘制前快照目标矩形进 BKBUF (下一帧恢复用) ──
    if DISABLE_CURSOR_SNAPSHOT:
        pb_skip = jmp32()                            # 二分开关: 跳过快照
    emit(b'\x8B\x44\x24\x24')                        # mov eax,[esp+0x24] ; dst
    emit(b'\xA3' + _cur('bd'))                       # mov [BK_DST],eax
    emit(b'\xA1' + _cur('ssv'))                      # mov eax,[SSV]
    emit(b'\xA3' + _cur('bs'))                       # mov [BK_STRIDE],eax
    emit(b'\xA1' + _cur('cx0'))
    emit(b'\xA3' + _cur('bx'))                       # mov [BK_X0],eax
    emit(b'\xA1' + _cur('cy0'))
    emit(b'\xA3' + _cur('by'))                       # mov [BK_Y0],eax
    emit(b'\xA1' + _cur('cx1'))
    emit(b'\x2B\x05' + _cur('cx0'))                  # sub eax,[CX0]
    emit(b'\x40')                                    # inc eax
    emit(b'\xA3' + _cur('bw'))                       # mov [BK_W],eax
    emit(b'\xA1' + _cur('cy1'))
    emit(b'\x2B\x05' + _cur('cy0'))                  # sub eax,[CY0]
    emit(b'\x40')                                    # inc eax
    emit(b'\xA3' + _cur('bh'))                       # mov [BK_H],eax
    emit(b'\x8B\x44\x24\x18')                        # mov eax,[esp+0x18] ; X
    emit(b'\xA3' + _cur('px'))                       # mov [CUR_PX],eax
    emit(b'\x8B\x44\x24\x1C')                        # mov eax,[esp+0x1C] ; Y
    emit(b'\xA3' + _cur('py'))                       # mov [CUR_PY],eax
    emit(b'\xC7\x05' + _cur('bv') + struct.pack('<I', 1))   # BK_VALID=1
    # ⚠ 快照循环破坏 edi/ebp —— 之后的绘制行循环依赖 edi(X)/ebx(Y) 计算 scratch
    # 源索引, 必须保护 edi (ebp 行循环会重载; ebx 本段不碰, 顺手保护)
    emit(b'\x53\x57')                                # push ebx; push edi
    emit(b'\xFC')                                    # cld
    emit(b'\x33\xED')                                # xor ebp,ebp
    b_srow = len(code)
    emit(b'\x8B\xC5')                                # mov eax,ebp
    emit(b'\x03\x05' + _cur('by'))                   # add eax,[BK_Y0]
    emit(b'\x0F\xAF\x05' + _cur('bs'))               # imul eax,[BK_STRIDE]
    emit(b'\x03\x05' + _cur('bx'))                   # add eax,[BK_X0]
    emit(b'\x8D\x34\x00')                            # lea esi,[eax+eax]
    emit(b'\x03\x74\x24\x2C')                        # add esi,[esp+0x2C] ; dst (+8 栈深)
    emit(b'\x8B\xFD')                                # mov edi,ebp
    emit(b'\xC1\xE7\x09')                            # shl edi,9
    emit(b'\x81\xC7' + _g_bkbuf())                   # add edi,BKBUF
    emit(b'\x8B\x0D' + _cur('bw'))                   # mov ecx,[BK_W] ; 词数
    emit(b'\xF3\x66\xA5')                            # rep movsw
    emit(b'\x45')                                    # inc ebp
    emit(b'\x3B\x2D' + _cur('bh'))                   # cmp ebp,[BK_H]
    pb0 = j32('jb')                                  # jb B_SAVE_ROW
    code[pb0 + 2:pb0 + 6] = struct.pack('<i', b_srow - (pb0 + 6))
    emit(b'\x5F\x5B')                                # pop edi; pop ebx
    # ── 逐行 blit (ebp = y) ──
    if DISABLE_CURSOR_SNAPSHOT:
        code[pb_skip + 1:pb_skip + 5] = struct.pack('<i', len(code) - (pb_skip + 5))
    emit(b'\x8B\x2D' + _cur('cy0'))                  # mov ebp,[CY0]
    row_pos = len(code)
    # esi = SCRATCH + ((ebp-Y+240)*640 + (cx0-X+320))*2
    emit(b'\x89\xE8')                                # mov eax,ebp
    emit(b'\x29\xD8')                                # sub eax,ebx
    emit(b'\x05\xF0\x00\x00\x00')                    # add eax,240
    emit(b'\x69\xC0\x80\x02\x00\x00')                # imul eax,eax,640
    emit(b'\x8B\x15' + _cur('cx0'))                  # mov edx,[CX0]
    emit(b'\x81\xC2\x40\x01\x00\x00')                # add edx,320
    emit(b'\x29\xFA')                                # sub edx,edi
    emit(b'\x03\xC2')                                # add eax,edx
    emit(b'\x8D\x34\x00')                            # lea esi,[eax+eax]
    emit(b'\x81\xC6' + _g_scratch())                 # add esi,SCRATCH
    # edx = dst + (ebp*stride + cx0)*2
    emit(b'\x89\xE8')                                # mov eax,ebp
    emit(b'\x0F\xAF\x05' + _cur('ssv'))              # imul eax,[SSV]
    emit(b'\x03\x05' + _cur('cx0'))                  # add eax,[CX0]
    emit(b'\x8D\x14\x00')                            # lea edx,[eax+eax]
    emit(b'\x03\x54\x24\x24')                        # add edx,[esp+0x24] ; dst
    # ecx = 像素数
    emit(b'\x8B\x0D' + _cur('cx1'))                  # mov ecx,[CX1]
    emit(b'\x2B\x0D' + _cur('cx0'))                  # sub ecx,[CX0]
    emit(b'\x41')                                    # inc ecx
    px_pos = len(code)
    # 内层: 非哨兵像素写入
    emit(b'\x66\x8B\x06')                            # mov ax,[esi]
    emit(b'\x66\x3D' + struct.pack('<H', CURSOR_SENTINEL))  # cmp ax,SENTINEL
    sk = j32('je')                                   # je skip
    emit(b'\x66\x89\x02')                            # mov [edx],ax
    fix32(sk)
    emit(b'\x83\xC6\x02')                            # add esi,2
    emit(b'\x83\xC2\x02')                            # add edx,2
    emit(b'\x49')                                    # dec ecx
    jnz_pos = len(code)
    emit(b'\x75\x00')                                # jnz PXLOOP (回填)
    emit(b'\x45')                                    # inc ebp
    emit(b'\x3B\x2D' + _cur('cy1'))                  # cmp ebp,[CY1]
    jle_pos = len(code)
    emit(b'\x7E\x00')                                # jle ROWLOOP (回填)
    # DONE
    done_pos = len(code)
    emit(b'\x5D\x5F\x5E\x5B\xC3')                    # pop ebp;edi;esi;ebx; ret
    code[jnz_pos + 1] = (px_pos - (jnz_pos + 2)) & 0xFF
    code[jle_pos + 1] = (row_pos - (jle_pos + 2)) & 0xFF
    for pr in (p, q, q2, r, p9, p10):
        code[pr + 2:pr + 6] = struct.pack('<i', done_pos - (pr + 6))
    return bytes(code)


# ── 2c. 字形/光标绘制器的裁剪与换行宽度 (640 -> 动态逻辑宽度) ───────────
# 这批绘制器 (0x4544EC..0x45B20C, 共 18 个格式变体) 的地址计算已改为读
# g_stride, 但内部仍以硬编码 640 做 x 裁剪与"x+=640 换行":
#     cmp r32, 0x280 / add [ebp+0xc],0x280 / sub [0x4ed840],0x280
# 于是把本该 856 宽的屏幕当 640 宽处理 —— 精灵每行错位 (856-640)=216px 并
# 反复回卷, 表现为鼠标移动时整屏拉丝花屏 (实测: 移动 2px, y±15 行内跨全宽
# 散点)。TKSRemake 的等价语义是"当前逻辑宽度"统一参与裁剪 (SetLogicalWidth),
# 故此处改为与 g_stride 同步的动态宽度 (页面=640, 游戏=856)。
def build_blit_cmp_eax_w() -> bytes:
    """5B 位点 `cmp eax,640` -> `cmp eax,[g_stride]` (标志位供后续 jcc)。"""
    return b'\x59' + b'\x3B\x05' + _g_stride() + b'\xFF\xE1'


def build_blit_end_eax() -> bytes:
    """5B 位点 `add eax,479*1280` -> `add eax,[g_end]` (保留 ecx/edx 与标志)。"""
    SCRATCH = 0x004ED83C                             # 原版光标临时量区
    code = bytearray()
    code += bytes([0x89, 0x0D]) + struct.pack('<I', SCRATCH)   # mov [scratch],ecx
    code += bytes([0x59])                                      # pop ecx
    code += bytes([0x03, 0x05]) + _g_end()                     # add eax,[g_end]
    code += bytes([0x8B, 0x0D]) + struct.pack('<I', SCRATCH)   # mov ecx,[scratch]
    code += bytes([0xFF, 0xE1])                                # jmp ecx
    return bytes(code)


def build_blit_wrap_add() -> bytes:
    """7B 位点 `add dword [ebp+0xc],640` -> 加当前逻辑宽度 (保留 eax 与标志)。"""
    code = bytearray()
    code += b'\x59'                                  # pop ecx  ; 返回地址
    code += b'\x50'                                  # push eax
    code += b'\x8B\x45\x0C'                          # mov eax,[ebp+0xc]
    code += b'\x03\x05' + _g_stride()                # add eax,[g_stride]
    code += b'\x89\x45\x0C'                          # mov [ebp+0xc],eax
    code += b'\x58'                                  # pop eax  ; 不影响标志
    code += b'\xFF\xE1'                              # jmp ecx
    return bytes(code)


def build_blit_wrap_sub() -> bytes:
    """10B 位点 `sub dword [0x4ed840],640` -> 减当前逻辑宽度 (保留 eax 与标志)。"""
    code = bytearray()
    code += b'\x59'                                  # pop ecx
    code += b'\x50'                                  # push eax
    code += b'\xA1' + struct.pack('<I', 0x004ED840)   # mov eax,[0x4ed840]
    code += b'\x2B\x05' + _g_stride()                # sub eax,[g_stride]
    code += b'\xA3' + struct.pack('<I', 0x004ED840)   # mov [0x4ed840],eax
    code += b'\x58'                                  # pop eax
    code += b'\xFF\xE1'                              # jmp ecx
    return bytes(code)


# ── 3. GXP 加载器适配 ──────────────────────────────────────────────────
def build_gxp_pad_decide() -> bytes:
    """640x480 全屏 gxp -> ddsd 宽改 856 (右带留黑); 其余尺寸原样。"""
    code = bytearray()
    code += b'\xA1' + struct.pack('<I', GXP_W_VA)     # mov eax,[W]
    code += b'\x8B\x15' + struct.pack('<I', GXP_H_VA)  # mov edx,[H]
    code += b'\x89\x85\x74\xFF\xFF\xFF'               # mov [ebp-0x8C],eax (ddsd.W)
    code += b'\x89\x95\x70\xFF\xFF\xFF'               # mov [ebp-0x90],edx (ddsd.H)
    code += b'\xC7\x05' + _g_pad() + struct.pack('<I', 0)
    code += b'\x3D\x80\x02\x00\x00'                   # cmp eax,640
    j1 = len(code); code += b'\x75\x00'
    code += b'\x81\xFA\xE0\x01\x00\x00'               # cmp edx,480
    j2 = len(code); code += b'\x75\x00'
    code += b'\xB8' + struct.pack('<I', W_SCREEN)     # mov eax,856
    code += b'\x89\x85\x74\xFF\xFF\xFF'               # mov [ebp-0x8C],eax
    code += b'\xC7\x05' + _g_pad() + struct.pack('<I', 1)
    out = len(code)
    code += b'\xC3'
    code[j1 + 1] = (out - (j1 + 2)) & 0xFF
    code[j2 + 1] = (out - (j2 + 2)) & 0xFF
    return bytes(code)


def build_gxp_upload() -> bytes:
    """上传: padded 时逐行拷 1280B + 清 432B 右带, 否则原 memcpy。

    自身压 3 个参数, 使 hook 后原 `add esp,0xC` 平衡。
    src 步进 1280 (640 宽), dst 步进 1712 (856x2); rep movsd + rep stosd 后
    edi 恰落下一行行首。
    """
    code = bytearray()
    code += b'\x8B\x0D' + struct.pack('<I', GXP_W_VA)     # mov ecx,[W]
    code += b'\x0F\xAF\x0D' + struct.pack('<I', GXP_H_VA)  # imul ecx,[H]
    code += b'\x03\xC9'                                   # add ecx,ecx
    code += b'\x51'                                       # push size
    code += b'\x8B\x45\xEC'                               # mov eax,[ebp-0x14] (src)
    code += b'\x50'                                       # push src
    code += b'\x8B\x55\x8C'                               # mov edx,[ebp-0x74] (dst)
    code += b'\x52'                                       # push dst
    code += b'\xA1' + _g_pad()                            # mov eax,[g_pad]
    code += b'\x85\xC0'                                   # test eax,eax
    jz_orig = len(code); code += b'\x74\x00'
    code += b'\x56\x57\x53'                               # push esi;push edi;push ebx
    code += b'\x8B\x75\xEC'                               # mov esi,[ebp-0x14]
    code += b'\x8B\x7D\x8C'                               # mov edi,[ebp-0x74]
    code += b'\xBB\xE0\x01\x00\x00'                       # mov ebx,480
    l_loop = len(code)
    code += b'\xB9\x40\x01\x00\x00'                       # mov ecx,320
    code += b'\xF3\xA5'                                   # rep movsd
    code += b'\x33\xC0'                                   # xor eax,eax
    code += b'\xB9' + BAND_DWORDS.to_bytes(4, 'little')   # mov ecx,108
    code += b'\xF3\xAB'                                   # rep stosd
    code += b'\x4B'                                       # dec ebx
    jnz_loop = len(code); code += b'\x75\x00'
    code += b'\x5B\x5F\x5E'                               # pop ebx;pop edi;pop esi
    code += b'\xC3'
    orig = len(code)
    code += b'\xB8' + struct.pack('<I', MEMCPY_VA)
    code += b'\xFF\xD0'                                   # call eax
    code += b'\xC3'
    code[jz_orig + 1] = (orig - (jz_orig + 2)) & 0xFF
    code[jnz_loop + 1] = (l_loop - (jnz_loop + 2)) & 0xFF
    return bytes(code)


# ── 3b. 页面背景全表面 Blt 修正 ────────────────────────────────────────
def build_gxp_blt_fix() -> bytes:
    """把 `Blt(后备, 0, 背景, 0, f, 0)` 的两个 NULL 矩形改成"源表面实际尺寸"。

    dst/src 矩形同时为 NULL 时按"整个表面"处理, 后备已拓宽到 856 而 6 个位点的
    源表面尺寸不一 (640x480 页面背景, 以及 AVI 逐帧的其它尺寸), 尺寸不匹配时
    cnc-ddraw 以 dst 行距读源 → 每行错位 216px 拖影; 若硬编码 640x480 又会因
    源小于该矩形而失败 (实测: 黑屏停摆)。故运行时问源表面要尺寸:

      GetSurfaceDesc(src, &ddsd)  →  RECT {0,0,W,H} 同时作 dst/src 矩形

    源尺寸取不到 (调用失败/为 0) 时不动矩形, 退回原语义 (宁可拖影不可卡死)。

    ⚠ 位点用 E8 进入 cave 会多压一个返回地址 (ESP=S0-4), 若直接 `call
    [edx+0x14]`, DirectDraw 读到的 6 个参数整体错位 4 字节, 且 stdcall 弹参
    后 ESP 失衡 → 返回即跳到野地址 (实测: 黑屏卡死, 无异常框)。故 cave 先
    `pop ecx` 复位 ESP 到 S0, 末尾 `jmp` 回 site+5。
    ⚠ eax (dst 对象) 与 ecx (返回地址) 都要跨 DD 调用保存 —— 后者会被 DD
    方法破坏, 前者位点所在函数之后还会用 (实测 0x40D441 `push eax`), 故分别
    存 .data 槽; eax 置矩形指针、ecx 存返回地址都会破坏原值。
    """
    SUB = 0x100                      # DDSURFACEDESC2=124B, 留足余量 (不与参数槽重叠)
    G_RECT_VA = 0x400000 + RECT_GLOBAL_RVA
    G_DST_RECT_VA = 0x400000 + DST_RECT_RVA

    code = bytearray()
    jz_fix, jbe_fix = [], []

    def emit(b: bytes) -> int:
        off = len(code)
        code.extend(b)
        return off

    emit(b'\x59')                                        # pop ecx  ; ESP 复位 S0
    emit(b'\xA3' + _g_eax())                             # mov [g_eax],eax   ; dst 对象
    emit(b'\x89\x0D' + _g_ret2())                        # mov [g_ret2],ecx  ; 返回地址
    emit(b'\x81\xEC' + struct.pack('<I', SUB))           # sub esp,SUB
    emit(b'\x89\x25' + _g_desc())                        # mov [g_desc],esp  ; 记 desc 首址
    emit(b'\xC7\x04\x24' + struct.pack('<I', 124))       # mov dword [esp],124  ; dwSize
    emit(b'\xC7\x44\x24\x08\x00\x00\x00\x00')            # mov dword [esp+8],0  ; dwHeight
    emit(b'\xC7\x44\x24\x0C\x00\x00\x00\x00')            # mov dword [esp+0xC],0; dwWidth
    src_off = SUB + 8                                    # 原 [S0+8]=src
    emit(b'\x8B\x84\x24' + struct.pack('<I', src_off))   # mov eax,[esp+src_off] ; src 表面
    emit(b'\x54')                                        # push esp            ; lpDDSurfaceDesc
    emit(b'\x50')                                        # push eax            ; this=src
    emit(b'\x8B\x10')                                    # mov edx,[eax]
    emit(b'\xFF\x52\x58')                                # call [edx+0x58]     ; GetSurfaceDesc
    # 经 g_desc 读回尺寸 / 恢复 ESP: 不依赖被调方是否弹参 (stdcall/cdecl 皆可)
    emit(b'\x8B\x15' + _g_desc())                        # mov edx,[g_desc]
    emit(b'\x8B\x52\x08')                                # mov edx,[edx+8]     ; dwHeight
    emit(b'\x8B\x05' + _g_desc())                        # mov eax,[g_desc]
    emit(b'\x8B\x40\x0C')                                # mov eax,[eax+0xC]   ; dwWidth
    emit(b'\x8B\x25' + _g_desc())                        # mov esp,[g_desc]    ; ESP=S0-SUB
    emit(b'\x81\xC4' + struct.pack('<I', SUB))           # add esp,SUB         ; ESP=S0
    emit(b'\x85\xC0')                                    # test eax,eax
    jz_fix.append(len(code) + 1); emit(b'\x74\x00')      # jz skip
    emit(b'\x85\xD2')                                    # test edx,edx
    jz_fix.append(len(code) + 1); emit(b'\x74\x00')      # jz skip
    # ⚠ 宽度必须钳到 748 (= 856-108): padded gxp 源宽 856, 若 W 取 856 则
    # dst.right = W+108 = 964 超出后备表面 → Blt 返回 DDERR_INVALIDRECT 每帧
    # 失败 → 后备永不重涂, 上一帧光标残留 → 鼠标事件的 grab 把它烤进画布,
    # push 每帧重放 (实测: 标题屏光标残影成串)。钳 748 后 src={0,0,748,H}
    # (640 内容 + 108 黑带) → dst={108,0,856,H} 恰好铺满画布区+右带。
    emit(b'\x3D' + struct.pack('<I', W_SCREEN - PAGE_OFF))   # cmp eax,748
    jbe_fix.append(len(code) + 1); emit(b'\x76\x00')     # jbe ok (不超可 blit 宽)
    emit(b'\xB8' + struct.pack('<I', W_SCREEN - PAGE_OFF))   # mov eax,748
    ok_off = len(code)
    emit(b'\xC7\x05' + struct.pack('<I', G_RECT_VA) + b'\x00\x00\x00\x00')          # src left=0
    emit(b'\xC7\x05' + struct.pack('<I', G_RECT_VA + 4) + b'\x00\x00\x00\x00')      # src top=0
    emit(b'\xA3' + struct.pack('<I', G_RECT_VA + 8))                                # src right=W
    emit(b'\x89\x15' + struct.pack('<I', G_RECT_VA + 12))                           # src bottom=H
    # 目标矩形 = 画布在屏幕内的位置: 居中偏移 PAGE_OFF (108)
    emit(b'\xC7\x05' + struct.pack('<I', G_DST_RECT_VA) + struct.pack('<I', PAGE_OFF))   # dst left=108
    emit(b'\xC7\x05' + struct.pack('<I', G_DST_RECT_VA + 4) + b'\x00\x00\x00\x00')       # dst top=0
    emit(b'\x8D\x88' + struct.pack('<I', PAGE_OFF))                                 # lea ecx,[eax+108]
    emit(b'\x89\x0D' + struct.pack('<I', G_DST_RECT_VA + 8))                        # dst right=W+108
    emit(b'\x89\x15' + struct.pack('<I', G_DST_RECT_VA + 12))                       # dst bottom=H
    emit(b'\xC7\x44\x24\x04' + struct.pack('<I', G_DST_RECT_VA))  # mov [esp+4],dstRect
    emit(b'\xC7\x44\x24\x0C' + struct.pack('<I', G_RECT_VA))      # mov [esp+0xC],srcRect
    skip_off = len(code)
    emit(b'\x8B\x14\x24')                                # mov edx,[esp]       ; dst 对象
    emit(b'\x8B\x12')                                    # mov edx,[edx]
    emit(b'\xFF\x52\x14')                                # call [edx+0x14]     ; Blt
    emit(b'\x8B\x0D' + _g_ret2())                        # mov ecx,[g_ret2]
    emit(b'\xFF\xE1')                                    # jmp ecx             ; 回 site+5
    for p in jz_fix:
        code[p] = (skip_off - (p + 1)) & 0xFF
    for p in jbe_fix:
        code[p] = (ok_off - (p + 1)) & 0xFF
    return bytes(code)


# ── 布局与入口 ─────────────────────────────────────────────────────────
_BLOCKS = [
    ('init_stride', build_stride_init),
    ('grab_copy', build_grab_copy),
    ('push_copy', build_push_copy),
    ('gxp_pad_decide', build_gxp_pad_decide),
    ('gxp_upload', build_gxp_upload),
    ('gxp_blt_fix', build_gxp_blt_fix),
    ('mouse_clamp', build_mouse_clamp),
    ('mouse_map_down', build_mouse_map_down),
    ('rec_map', build_rec_map),
    ('cursor_scratch', build_cursor_scratch),
    ('blit_cmp_eax_w', build_blit_cmp_eax_w),
    ('blit_end_eax', build_blit_end_eax),
    ('blit_wrap_add', build_blit_wrap_add),
    ('blit_wrap_sub', build_blit_wrap_sub),
] + [(name, (lambda f: (lambda: build_page_wrapper(f)))(fn))
     for name, fn in PAGE_FUNCS.items()]


def cave_entries() -> dict:
    entries = {}
    off = 0
    for name, builder in _BLOCKS:
        entries[name] = off
        off += len(builder())
    return entries


def build_cave_block() -> bytes:
    block = bytearray()
    for name, builder in _BLOCKS:
        block += builder()
    return bytes(block)


def _load_grab_erase_builder():
    """按路径加载 grab_erase.py (与 本文件 同目录), 返回 build_grab_erase。"""
    import importlib.util
    import os
    _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'grab_erase.py')
    _spec = importlib.util.spec_from_file_location('_ws_grab_erase', _p)
    _m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_m)
    return _m.build_grab_erase


_build_grab_erase = _load_grab_erase_builder()


CAVE_ENTRIES = cave_entries()
