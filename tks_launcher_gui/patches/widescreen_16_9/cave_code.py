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
# 调试探针区 (定位"主角不显示"用; 定位后连同 SPR_DEBUG 一起移除)
DBG_RVA = BKBUF_RVA + BKBUF_SIZE          # 0x306898
DBG_BYTES = 0x270
PAGE_MODE_RVA = DBG_RVA + 0xB0    # 1=页面态(640 逻辑宽), 0=游戏态(856)
CUR_TSTR_RVA = DBG_RVA + 0xB4     # 光标本次的目标行距
MG_MOUSE_RVA = DBG_RVA + 0xB8     # 鼠标 X - 108 (未钳制): 小游戏命中判定读点
                                  # (DBG 区内, 已在 globals_extra_windows 重定位窗口)
MG_MAP_RVA = DBG_RVA + 0xBC        # 鼠标 X 钳 [0,639]: 拾取读点 (410B77) 专用。
                                    # 拾取缓冲 word_78E276 为静态 BSS (614400B, 恰止于
                                    # 0x824276, 紧邻鼠标/TK-Edit 全局) — 不可扩容 (实测扩容
                                    # 的 -1 填充覆盖 0x8242B8 → 弹 TK-Edit 调试层且输入失效);
                                    # x>=640 读末列值(空), 实体命中由 410B74 的 bbox 兜底。
GLOBALS_EXTRA_WINDOWS = ((BKBUF_RVA - 0x260800, 1), (DBG_RVA - 0x260800, DBG_BYTES))
GLOBALS_ALLOC_SIZE = (MG_MAP_RVA - 0x260800) + 4

GXP_W_VA = 0x00A2B9A4                # gxp 头解析出的宽
GXP_H_VA = 0x00A2B9A8                # 高
MEMCPY_VA = 0x004B008C               # 原 memcpy

DD_INIT_FN = 0x44EC0C                # sub_44EC0C DD 初始化
PAGE_FUNCS = {
    'wrap_page_42131C': 0x42131C,
    'wrap_page_4240B8': 0x4240B8,
    'wrap_page_426164': 0x426164,
    # 系统菜单循环 sub_40D2D0 直接调用它 (调用点 0x40D434), 内部用 4544EC 画
    # 精灵; 不包步长会按 856 画到 640 菜单页 → 鼠标移到物品上时整片横向拉丝。
    'wrap_page_42539C': 0x42539C,
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


def _g_mouse_mg() -> bytes:
    return struct.pack('<I', 0x400000 + MG_MOUSE_RVA)


def _g_mouse_map() -> bytes:
    return struct.pack('<I', 0x400000 + MG_MAP_RVA)


def _g_page_rec_x() -> bytes:
    return struct.pack('<I', 0x400000 + PAGE_REC_X_RVA)


def _g_scratch() -> bytes:
    return struct.pack('<I', 0x400000 + SCRATCH_RVA)


def _g_bkbuf() -> bytes:
    return struct.pack('<I', 0x400000 + BKBUF_RVA)


SPR_DEBUG = False      # 运行期探针 (定位后置 False 并移除)


def _dbg(off: int = 0) -> bytes:
    return struct.pack('<I', 0x400000 + DBG_RVA + off)


def _g_pm() -> bytes:
    return struct.pack('<I', 0x400000 + PAGE_MODE_RVA)


def _cur(name: str) -> bytes:
    rva = {'w': CUR_W_RVA, 'h': CUR_H_RVA, 'xo': CUR_XO_RVA,
           'yo': CUR_YO_RVA, 'ssv': CUR_STRIDE_SV_RVA,
           'gsv': CUR_GEND_SV_RVA, 'cx0': CUR_CX0_RVA, 'cx1': CUR_CX1_RVA,
           'cy0': CUR_CY0_RVA, 'cy1': CUR_CY1_RVA,
           'px': CUR_PX_RVA, 'py': CUR_PY_RVA,
           'tstr': CUR_TSTR_RVA, 'bv': BK_VALID_RVA, 'bd': BK_DST_RVA, 'bs': BK_STRIDE_RVA,
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


def build_map_camera() -> bytes:
    """替换地图主循环 `call sub_406CE0`：按原版公式在 856 视口下重建跟随。

    原版公式（dword_4E7CC8 = 视口宽, dword_4E7CCC = 视口高）:
      viewX = clamp(actor[0x2C-4] - W/2, 0, bgW - W)
      viewY = clamp(actor[0x2C]   - 5*(H/8), 0, bgH - H)
    856x480 时即 actorX-428 / actorY-300。原函数内 `a1[1] == 当前场景` 的守卫
    在部分地图不成立会让镜头停摆；这里按同一公式直接重建镜头，
    随后仍调用原函数保留 824280/824284 与 sub_4054D8 的副作用。
    """
    code = bytearray()
    jumps: list = []

    def emit(b: bytes) -> int:
        off = len(code)
        code.extend(b)
        return off

    def j32(cond: bytes, target: str) -> None:
        jumps.append((emit(cond + b'\x00\x00\x00\x00') + 2, target))

    BGW, BGH = 0x00824290, 0x00824292
    VXL, VYL = 0x008242A8, 0x008242AC
    VXR, VYB = 0x008242B0, 0x008242B4
    Y_OFF = 5 * (480 // 8)          # 300

    emit(b'\x59')                                        # pop ecx (site+5)
    emit(b'\x89\x0D' + _g_ret())                         # mov [g_ret],ecx
    emit(b'\xB8' + struct.pack('<I', 0x406CE0))
    emit(b'\xFF\xD0')                                   # call 406CE0 (原副作用)
    emit(b'\x8B\x0C\x24')                               # mov ecx,[esp] a1
    emit(b'\x85\xC9')
    j32(b'\x0F\x84', 'done')
    emit(b'\x8B\x11')                                    # mov edx,[ecx]
    emit(b'\x85\xD2')
    j32(b'\x0F\x84', 'done')
    # ---- X ----
    emit(b'\x8B\x41\x28')                               # mov eax,[ecx+0x28]
    emit(b'\x2D' + struct.pack('<I', 428))
    emit(b'\x85\xC0')
    j32(b'\x0F\x88', 'xzero')
    emit(b'\x0F\xB7\x15' + struct.pack('<I', BGW))
    emit(b'\x81\xEA' + struct.pack('<I', W_SCREEN))
    emit(b'\x85\xD2')
    j32(b'\x0F\x88', 'xzero')
    emit(b'\x39\xD0')
    j32(b'\x0F\x8E', 'xdone')
    emit(b'\x89\xD0')
    xdone = len(code)
    emit(b'\xA3' + struct.pack('<I', VXL))
    emit(b'\x05' + struct.pack('<I', W_SCREEN))
    emit(b'\xA3' + struct.pack('<I', VXR))
    # ---- Y ----
    emit(b'\x8B\x41\x2C')                               # mov eax,[ecx+0x2C]
    emit(b'\x2D' + struct.pack('<I', Y_OFF))
    emit(b'\x85\xC0')
    j32(b'\x0F\x88', 'yzero')
    emit(b'\x0F\xB7\x15' + struct.pack('<I', BGH))
    emit(b'\x81\xEA' + struct.pack('<I', 480))
    emit(b'\x85\xD2')
    j32(b'\x0F\x88', 'yzero')
    emit(b'\x39\xD0')
    j32(b'\x0F\x8E', 'ydone')
    emit(b'\x89\xD0')
    ydone = len(code)
    emit(b'\xA3' + struct.pack('<I', VYL))
    emit(b'\x05' + struct.pack('<I', 480))
    emit(b'\xA3' + struct.pack('<I', VYB))
    jmp_done = emit(b'\xE9\x00\x00\x00\x00')
    xzero = len(code)
    emit(b'\x31\xC0')
    jmp_x = emit(b'\xE9\x00\x00\x00\x00')
    yzero = len(code)
    emit(b'\x31\xC0')
    jmp_y = emit(b'\xE9\x00\x00\x00\x00')
    done = len(code)
    emit(b'\x8B\x0D' + _g_ret())
    emit(b'\xFF\xE1')                                   # jmp ecx -> site+5
    code[jmp_done + 1:jmp_done + 5] = struct.pack('<i', done - (jmp_done + 5))
    code[jmp_x + 1:jmp_x + 5] = struct.pack('<i', xdone - (jmp_x + 5))
    code[jmp_y + 1:jmp_y + 5] = struct.pack('<i', ydone - (jmp_y + 5))
    labels = {'done': done, 'xzero': xzero, 'yzero': yzero,
              'xdone': xdone, 'ydone': ydone}
    for pos, tgt in jumps:
        code[pos:pos + 4] = struct.pack('<i', labels[tgt] - (pos + 4))
    return bytes(code)


def build_settle_shift() -> bytes:
    """结算/奖励页 (43B7FC)：把原始 640x480 画面整体右移 108，两侧补黑。

    挂在 43B7FC 主循环的 `call sub_411D18`(RVA 0x3BE13) 之前 —— 该点之后
    只剩光标绘制与 Unlock，因此：
      ① 每帧的 lm.gxp 背景 Blt、面板精灵、道具图标、文字全部已画在原 640
         坐标系内（这条路径本来就正确），本 cave 一次性平移，无需再逐个位点
         +108；
      ② 光标随后按真实窗口坐标绘制，不会被平移。

    平移 (856x480 / 1712B 行距, 16bpp):
      [0,216)      <- 黑
      [216,1496)   <- 原 [0,1280)（从右往左拷贝以避开重叠）
      [1496,1712)  <- 黑
    即内容居中于 [108,748)，左右各 108px 黑边。
    """
    code = bytearray()
    row_fix = []

    def emit(b: bytes) -> int:
        off = len(code)
        code.extend(b)
        return off

    emit(b'\x59')                                  # pop ecx (site+5)
    emit(b'\x89\x0D' + _g_ret())                   # mov [g_ret],ecx
    emit(b'\x53\x55\x56\x57')                     # push ebx;ebp;esi;edi
    emit(b'\x8B\x6C\x24\x10')                     # mov ebp,[esp+0x10] ; surface
    emit(b'\x31\xDB')                              # xor ebx,ebx ; y
    emit(b'\xFC')                                  # cld
    row = len(code)
    emit(b'\x89\xD8')                              # mov eax,ebx
    emit(b'\x69\xC0' + struct.pack('<I', 1712))    # imul eax,eax,1712
    emit(b'\x8D\x54\x05\x00')                     # lea edx,[ebp+eax]
    # move [0,1280) -> [216,1496) backwards
    emit(b'\x8B\xF2')                              # mov esi,edx
    emit(b'\x81\xC6' + struct.pack('<I', 1276))     # add esi,1276
    emit(b'\x8B\xFA')                              # mov edi,edx
    emit(b'\x81\xC7' + struct.pack('<I', 1492))     # add edi,1492
    emit(b'\xB9\x40\x01\x00\x00')                 # mov ecx,320
    emit(b'\xFD')                                  # std
    emit(b'\xF3\xA5')                              # rep movsd
    emit(b'\xFC')                                  # cld
    # left band [0,216) —— 必须在拷贝之后清, 否则会把源数据一起抹掉
    emit(b'\x8B\xFA')                              # mov edi,edx
    emit(b'\x31\xC0')                              # xor eax,eax
    emit(b'\xB9\x36\x00\x00\x00')                 # mov ecx,54
    emit(b'\xF3\xAB')                              # rep stosd
    # right band [1496,1712)
    emit(b'\x8D\xBA' + struct.pack('<I', 1496))     # lea edi,[edx+1496]
    emit(b'\x31\xC0')                              # xor eax,eax
    emit(b'\xB9\x36\x00\x00\x00')                 # mov ecx,54
    emit(b'\xF3\xAB')                              # rep stosd
    emit(b'\x43')                                  # inc ebx
    emit(b'\x81\xFB\xE0\x01\x00\x00')             # cmp ebx,480
    row_fix.append((len(code) + 2, row))
    emit(b'\x0F\x82\x00\x00\x00\x00')             # jb row
    emit(b'\x5F\x5E\x5D\x5B')                     # pop edi;esi;ebp;ebx
    emit(b'\xB8' + struct.pack('<I', 0x00411D18))   # mov eax,411D18
    emit(b'\xFF\xD0')                              # call eax (原光标绘制)
    emit(b'\x8B\x0D' + _g_ret())                   # mov ecx,[g_ret]
    emit(b'\xFF\xE1')                              # jmp ecx -> site+5
    for pos, tgt in row_fix:
        code[pos:pos + 4] = struct.pack('<i', tgt - (pos + 4))
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
    code += b'\xC7\x40' + bytes([FONT_W_OFF]) + struct.pack('<I', FONT_W_CANVAS)  # mov [eax+0x28],640
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
    code += b'\xC7\x40' + bytes([FONT_W_OFF]) + struct.pack('<I', FONT_W_SCREEN)  # mov [eax+0x28],856
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
    code += b'\xA3' + _g_mouse_mg()                  # mov [MG_MOUSE],eax (未钳制, 小游戏命中用)
    code += b'\x85\xC0'                              # test eax,eax
    code += b'\x79\x02'                              # jns +2
    code += b'\x31\xC0'                              # xor eax,eax
    code += b'\x81\xF8\x80\x02\x00\x00'              # cmp eax,640
    code += b'\x72\x05'                              # jb +5 (跳过 mov eax,639 共5B)
    code += b'\xB8\x7F\x02\x00\x00'                  # mov eax,639
    code += b'\xA3' + _g_page_x()                    # mov [PAGE_X],eax
    code += b'\xA1' + struct.pack('<I', 0x00824278)  # mov eax,[0x824278] (重载 raw)
    code += b'\x85\xC0'                              # test eax,eax
    code += b'\x79\x02'                              # jns +2
    code += b'\x31\xC0'                              # xor eax,eax
    code += b'\x3D\x80\x02\x00\x00'                  # cmp eax,640
    code += b'\x72\x05'                              # jb +5
    code += b'\xB8\x7F\x02\x00\x00'                  # mov eax,639
    code += b'\xA3' + _g_mouse_map()                 # mov [MG_MAP],eax
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
    code += b'\x89\x15' + _g_mouse_mg()              # mov [MG_MOUSE],edx (未钳制, 小游戏命中用)
    code += b'\x79\x02'                              # jns +2
    code += b'\x31\xD2'                              # xor edx,edx
    code += b'\x81\xFA\x80\x02\x00\x00'              # cmp edx,640
    code += b'\x72\x05'                              # jb +5 (跳过 mov edx,639 共5B)
    code += b'\xBA\x7F\x02\x00\x00'                  # mov edx,639
    code += b'\x89\x15' + _g_page_x()                # mov [PAGE_X],edx
    code += b'\x8B\x15' + struct.pack('<I', 0x00824278)  # mov edx,[0x824278] (重载 raw)
    code += b'\x85\xD2'                              # test edx,edx
    code += b'\x79\x02'                              # jns +2
    code += b'\x31\xD2'                              # xor edx,edx
    code += b'\x81\xFA\x80\x02\x00\x00'              # cmp edx,640
    code += b'\x72\x05'                              # jb +5
    code += b'\xBA\x7F\x02\x00\x00'                  # mov edx,639
    code += b'\x89\x15' + _g_mouse_map()             # mov [MG_MAP],edx
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
# 对象 +0x28 = 字体画布宽度 (sub_44AFF4 的 a1[10], 初值 640; sub_44E290 用它做
# 换行/裁剪判断), +0x2C = 高度。⚠ 不是"半行距"——早前误写 320/428 会让换行
# 边界与字形定位全错 (实测菜单文字错位/重复)。
FONT_W_OFF = 0x28
FONT_W_CANVAS = 640                     # 页面态: 页面画布宽 640
FONT_W_SCREEN = 856                     # 游戏态: 后备表面宽 856
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
    emit(b'\x3B\x05' + _cur('ssv'))                 # cmp eax,[实际目标行距]
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
    emit(b'\xB8' + struct.pack('<I', W_SCREEN))     # 目标后备表面物理行距恒为 856
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
    # cx1 = min(x1, stride-1, X+319)  ← 目标行距 (页面 640 / 游戏 856)
    emit(b'\x8B\x05' + _cur('ssv'))                 # mov eax,[SSV]
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
    emit(b'\xA1' + _cur('ssv'))                     # mov eax,[SSV]
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
    emit(b'\x0F\xAF\x05' + _cur('ssv'))             # imul eax,[SSV]
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
def build_fade_count() -> bytes:
    """淡变 LUT 逐像素循环的像素数: 原版硬编码 307200 (=640*480), 在 856 画布上
    只铺 307200/856≈359 行 → 上暗下亮的分界。改为运行时 g_stride*480
    (游戏 410880 / 页面 307200)。

    替换 `mov ecx,0x4B000` (0x4054B3, 5B): E8 进 cave, 设好 ecx 后 ret 回 site+5。
    """
    return (b'\xB9\xE0\x01\x00\x00'          # mov ecx,480
            + b'\x0F\xAF\x0D' + _g_stride()   # imul ecx,[g_stride]
            + b'\xC3')                        # ret


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
    """640x480 全屏 gxp 的表面按 856 宽创建 (内容靠左, 右带由 upload 清黑)。

    hook 点 RVA 0x50397 (`mov [ebp-0x90],edx`, 6B)。先补回原指令, 再按需把
    ddsd.dwWidth([ebp-0x8C]) 改成 856 并置 g_pad=1; 非 640x480 时 g_pad=0。
    `ret` 回到 site+5 (被 NOP 覆盖的 1 字节) 后继续原流程。
    作用: 让该表面与 856 后备面宽度一致 —— 否则 NULL 矩形的 Blt 会被 cnc-ddraw
    按 640->856 整幅拉伸 (实测背景美术被拉成 1.3375 倍并裁掉右侧 25%)。
    """
    code = bytearray()
    j = []

    def emit(b: bytes) -> int:
        off = len(code)
        code.extend(b)
        return off

    def j32(cond: bytes, tgt: str) -> None:
        j.append((emit(cond + b'\x00\x00\x00\x00') + 2, tgt))

    emit(b'\x89\x95\x70\xFF\xFF\xFF')                          # mov [ebp-0x90],edx
    emit(b'\x81\xBD\x74\xFF\xFF\xFF' + struct.pack('<I', 640))   # cmp dword [ebp-0x8C],640
    j32(b'\x0F\x85', 'no')
    emit(b'\x81\xFA' + struct.pack('<I', 480))                    # cmp edx,480
    j32(b'\x0F\x85', 'no')
    emit(b'\xC7\x85\x74\xFF\xFF\xFF' + struct.pack('<I', W_SCREEN))
    emit(b'\xC7\x05' + _g_pad() + struct.pack('<I', 1))
    emit(b'\xC3')
    no = len(code)
    emit(b'\xC7\x05' + _g_pad() + struct.pack('<I', 0))
    emit(b'\xC3')
    for pos, tgt in j:
        code[pos:pos + 4] = struct.pack('<i', no - (pos + 4))
    return bytes(code)


def build_gxp_upload() -> bytes:
    """按 g_pad 决定上传方式: padded 时逐行拷 1280B + 清 432B 右带。

    hook 点 RVA 0x50478 (`call memcpy`, 5B)。此刻栈上已有原代码压好的 3 个参数:
    [esp+4]=dst、[esp+8]=src、[esp+12]=size, 返回地址 [esp]=0x5047D。
    非 padded 时直接尾调用原 memcpy (参数/返回值原样透传)。
    padded 时逐行拷贝, 完成后 `ret` 回 0x5047D, 原 `add esp,0xC` 照常平衡。
    """
    code = bytearray()
    j = []

    def emit(b: bytes) -> int:
        off = len(code)
        code.extend(b)
        return off

    def j32(cond: bytes, tgt: str) -> None:
        j.append((emit(cond + b'\x00\x00\x00\x00') + 2, tgt))

    emit(b'\xA1' + _g_pad())                                  # mov eax,[g_pad]
    emit(b'\x85\xC0')                                         # test eax,eax
    j32(b'\x0F\x84', 'orig')
    emit(b'\x56\x57\x53')                                     # push esi;edi;ebx
    emit(b'\x8B\x74\x24\x14')                                 # mov esi,[esp+0x14] src
    emit(b'\x8B\x7C\x24\x10')                                 # mov edi,[esp+0x10] dst
    emit(b'\xBB\xE0\x01\x00\x00')                             # mov ebx,480
    loop = len(code)
    emit(b'\xB9\x40\x01\x00\x00')                             # mov ecx,320
    emit(b'\xF3\xA5')                                         # rep movsd
    emit(b'\x33\xC0')                                         # xor eax,eax
    emit(b'\xB9' + struct.pack('<I', BAND_DWORDS))            # mov ecx,108
    emit(b'\xF3\xAB')                                         # rep stosd
    emit(b'\x4B')                                             # dec ebx
    j32(b'\x0F\x85', 'loop')
    emit(b'\x5B\x5F\x5E')                                     # pop ebx;edi;esi
    emit(b'\xC3')
    orig = len(code)
    emit(b'\xB8' + struct.pack('<I', MEMCPY_VA))               # mov eax,memcpy
    emit(b'\xFF\xE0')                                         # jmp eax (尾调用)
    for pos, tgt in j:
        code[pos:pos + 4] = struct.pack('<i', (loop if tgt == 'loop' else orig) - (pos + 4))
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
    emit(b'\x81\xEC\x68\x00\x00\x00')          # sub esp,0x68 (fx 100B)
    emit(b'\xC7\x04\x24' + struct.pack('<I', 100))   # fx.dwSize=100
    emit(b'\xC7\x44\x24\x50' + b'\x00\x00\x00\x00')  # fx.dwFillColor=0 (fx+0x50)
    emit(b'\x8B\x94\x24\x68\x00\x00\x00')          # mov edx,[esp+0x68] (this=[A])
    emit(b'\x54')                                      # push esp (fx)
    emit(b'\x68' + struct.pack('<I', 0x1000400))      # push WAIT|COLORFILL
    emit(b'\x6A\x00')                                  # push 0 (srcRect)
    emit(b'\x6A\x00')                                  # push 0 (src)
    emit(b'\x6A\x00')                                  # push 0 (dstRect)
    emit(b'\x52')                                      # push edx (this)
    emit(b'\x8B\x12')                                  # mov edx,[edx]
    emit(b'\xFF\x52\x14')                            # call [edx+0x14] colorfill
    emit(b'\x81\xC4\x68\x00\x00\x00')          # add esp,0x68 (fx 收回)
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


# ── 3c. 小游戏背景全表面 Blt 修正 (左对齐 + 右带清黑, v2 纯 Blt) ────────
# 7 个小游戏 (40E97C 分发) 不走页面状态机: 直接往 856 后备面画, UI 坐标全部
# 按 640 硬编码 → 内容靠左、鼠标 raw 恒等映射, 自洽。每帧背景
# `Blt(画布, 0, MG_*.gxp [640x480], 0, 0, 0)` 两矩形都为 NULL → cnc-ddraw 按
# 目标行距读源 → 每行错位 216px 拖影 (与标题页同病)。本 cave 与 gxp_blt_fix
# 的差别: ① dst/src 矩形同为 {0,0,W,H} 左对齐 (无 +108, 与 UI 一致);
# ② 背景只铺左 640, 右带 [W,856) 会驻留进小游戏前的最后一帧 → W<856 时先用
#    DDBLT_COLORFILL 把整个画布填黑再 blt (44F420 同款调用: vtable+0x14,
#    flags=0x1000400, fx{dwSize=100} 全零=黑色 — 游戏自身黑幕即此调用, 实证)。
# v1 曾用 Lock/Unlock 清带, 实机白屏 (小游戏整屏不画), v2 移除一切未实证的
# DD 交互, 只保留 GetSurfaceDesc(+0x58, gxp_blt_fix 实证) 与 Blt(+0x14)。
# 单一入口: 位点 expect 延伸覆盖后续 `push 1` (3B call 形态 5B
# FF 50 14 6A 01; 5B 形态 6B 8B 10 FF 52 14 6A 01), 末尾统一
# `push 1; jmp ecx` 补回 (返回地址=site+5, 6B 位点多出的 NOP 恰在 site+5)。
# 只写 eax/ecx/edx/esp, 不碰 callee-saved, 不碰 ebp; 栈平衡: 让 Blt stdcall
# 自然消费 6 参 (esp 回到压参前), 尾部 jmp 回 site+5。
def build_gxp_blt_left() -> bytes:
    G_RECT_VA = 0x400000 + RECT_GLOBAL_RVA
    G_DST_RECT_VA = 0x400000 + DST_RECT_RVA

    code = bytearray()
    _j32: list = []

    def emit(b: bytes) -> int:
        off = len(code)
        code.extend(b)
        return off

    def j32(cond: bytes, target: str) -> None:
        _j32.append((emit(cond + b'\x00\x00\x00\x00') + 2, target))

    emit(b'\x59')                                    # pop ecx (site+5); esp=A
    emit(b'\x89\x0D' + _g_ret2())                    # mov [g_ret2],ecx
    emit(b'\x81\xEC' + struct.pack('<I', 0x80))      # sub esp,0x80 (desc); esp=A-0x80
    emit(b'\x89\x25' + _g_desc())                    # mov [g_desc],esp
    emit(b'\x8B\x84\x24' + struct.pack('<I', 0x88))  # mov eax,[esp+0x88] (src=[A+8])
    emit(b'\x85\xC0')                                # test eax,eax
    j32(b'\x0F\x84', 'skip')
    emit(b'\x54')                                    # push esp (desc)
    emit(b'\x50')                                    # push eax (this=src)
    emit(b'\x8B\x10')                                # mov edx,[eax]
    emit(b'\xFF\x52\x58')                            # call [edx+0x58] GetSurfaceDesc
    emit(b'\x8B\x15' + _g_desc())                    # mov edx,[g_desc]
    emit(b'\x8B\x4A\x08')                            # mov ecx,[edx+8]  (H)
    emit(b'\x8B\x42\x0C')                            # mov eax,[edx+0xC] (W)
    emit(b'\x8B\x25' + _g_desc())                    # mov esp,[g_desc] (=A-0x80)
    emit(b'\x85\xC0')                                # test eax,eax
    j32(b'\x0F\x84', 'skip')
    emit(b'\x85\xC9')                                # test ecx,ecx
    j32(b'\x0F\x84', 'skip')
    emit(b'\x3D' + struct.pack('<I', W_SCREEN))      # cmp eax,856
    emit(b'\x76\x05')                                # jbe +5
    emit(b'\xB8' + struct.pack('<I', W_SCREEN))      # mov eax,856
    emit(b'\x81\xF9' + struct.pack('<I', 0x1E0))     # cmp ecx,480
    emit(b'\x76\x05')                                # jbe +5
    emit(b'\xB9' + struct.pack('<I', 0x1E0))         # mov ecx,480
    # src={0,0,W,H}; dst={108,0,W+108,H} — 小游戏 UI 居中 (背景/瓷砖/文字/鼠标同步 +108)
    emit(b'\xA3' + struct.pack('<I', G_RECT_VA + 8))              # src.right=W
    emit(b'\x89\x0D' + struct.pack('<I', G_RECT_VA + 12))         # src.bottom=H
    emit(b'\x05' + struct.pack('<I', PAGE_OFF))                   # add eax,108
    emit(b'\xA3' + struct.pack('<I', G_DST_RECT_VA + 8))          # dst.right=W+108
    emit(b'\x89\x0D' + struct.pack('<I', G_DST_RECT_VA + 12))     # dst.bottom=H
    emit(b'\xC7\x05' + struct.pack('<I', G_RECT_VA) + b'\x00\x00\x00\x00')
    emit(b'\xC7\x05' + struct.pack('<I', G_RECT_VA + 4) + b'\x00\x00\x00\x00')
    emit(b'\xC7\x05' + struct.pack('<I', G_DST_RECT_VA) + struct.pack('<I', PAGE_OFF))
    emit(b'\xC7\x05' + struct.pack('<I', G_DST_RECT_VA + 4) + b'\x00\x00\x00\x00')
    # ── esp 回到 A, 指向新矩形参数 (skip 路径除外) ──
    emit(b'\x81\xC4' + struct.pack('<I', 0x80))      # add esp,0x80 → esp=A
    emit(b'\xC7\x44\x24\x04' + struct.pack('<I', G_DST_RECT_VA))  # [A+4]=dstRect
    emit(b'\xC7\x44\x24\x0C' + struct.pack('<I', G_RECT_VA))      # [A+C]=srcRect
    # ── 右带清黑: W<856 时先 colorfill 整面黑 (44F420 同款) ──
    # (eax 此时 = W+108, 故阈值 964 = 856+108 等价于 W<856)
    emit(b'\x3D' + struct.pack('<I', W_SCREEN + PAGE_OFF))  # cmp eax,964
    j32(b'\x0F\x83', 'nofill')                       # jae nofill (无带)
    emit(b'\x81\xEC\x68\x00\x00\x00')          # sub esp,0x68 (fx 100B)
    emit(b'\xC7\x04\x24' + struct.pack('<I', 100))   # fx.dwSize=100
    emit(b'\xC7\x44\x24\x50' + b'\x00\x00\x00\x00')  # fx.dwFillColor=0 (fx+0x50, 44F420 实证; 不清零=栈垃圾色)
    emit(b'\x8B\x94\x24\x68\x00\x00\x00')          # mov edx,[esp+0x68] (this=[A])
    emit(b'\x54')                                    # push esp (fx 指针)
    emit(b'\x68' + struct.pack('<I', 0x1000400))     # push DDBLT_WAIT|DDBLT_COLORFILL
    emit(b'\x6A\x00')                                # push 0 (srcRect)
    emit(b'\x6A\x00')                                # push 0 (src)
    emit(b'\x6A\x00')                                # push 0 (dstRect=整面)
    emit(b'\x52')                                    # push edx (this)
    emit(b'\x8B\x12')                                # mov edx,[edx]
    emit(b'\xFF\x52\x14')                            # call [edx+0x14] colorfill
    emit(b'\x81\xC4\x68\x00\x00\x00')          # add esp,0x68 (fx 收回)
    jmp_blt = emit(b'\xEB\x00')                      # jmp blt (rel8 回填)
    skip = len(code)
    emit(b'\x81\xC4' + struct.pack('<I', 0x98))      # add esp,0x98 → esp=P (未调 DD: 弃 desc+6 参)
    jmp_tail = emit(b'\xEB\x00')                     # jmp tail (rel8 回填)
    nofill = len(code)                               # jae 落点 (esp=A, 无带)
    blt = len(code)
    emit(b'\x8B\x14\x24')                            # mov edx,[esp] (dst 对象)
    emit(b'\x8B\x12')                                # mov edx,[edx]
    emit(b'\xFF\x52\x14')                            # call [edx+0x14] Blt → esp=P
    tail = len(code)
    emit(b'\x8B\x0D' + _g_ret2())                    # mov ecx,[g_ret2]
    emit(b'\x6A\x01')                                # push 1 (补回被 E8+NOP 覆写的 push)
    emit(b'\xFF\xE1')                                # jmp ecx → site+5
    for pos, tgt in _j32:
        val = (skip if tgt == 'skip' else nofill) - (pos + 4)
        code[pos:pos + 4] = struct.pack('<i', val)
    code[jmp_blt + 1] = (blt - (jmp_blt + 2)) & 0xFF
    code[jmp_tail + 1] = (tail - (jmp_tail + 2)) & 0xFF
    return bytes(code)


# ── 3d. 地图/战场背景 Blt 视口钳制 (窄地图信箱) ────────────────────────
# 已知局限①的落地: bgW<856 的地图/战场 (绝大多数战斗地图原为 640 宽), 相机
# 公式给出 viewX = bgW-856 < 0 或 viewX+856 > bgW → Blt 源矩形无效 → 背景失
# 败 + 相机跑到地图外。本 cave 挂在 20 个 `Blt(画布,0,背景TWM,&视口[8242A8],`
# `WAIT,0)` 调用点 (409830/4099B0/409B30/40AEF4/40B710/40C6EC/412BE8/43339C/
# 433690/433A38/434188/434D7C/4353F8/43A8D8/43BFE8/43CA64/43DE90/4434BC/
# 444BB0/445564), 每帧先把视口钳回合法区间再 blt:
#   vx = clamp(viewX, min(0,bgW-856), max(0,bgW-856))   (bgW=word[824290])
#   vy = clamp(viewY, min(0,bgH-480), max(0,bgH-480))   (bgH=word[824292])
#   回写 8242A8/B0/AC/B4 → 同帧实体绘制 (world-viewX) 与背景对齐, 且 436F60
#   的滚动累加从钳制值出发不再漂移;
#   src={max(0,vx),max(0,vy),min(bgW,vx+856),min(bgH,vy+480)},
#   dst={sx0-vx, sy0-vy, sx1-vx, sy1-vy} — 宽地图时恰等于原语义 (dst.left=0);
#   窄地图 (有黑带) 先 colorfill 整面黑 (44F420 同款) 再 blt, 消除信箱残影。
# 快路径 (bgW>=856 && bgH>=480): 参数原样直调 Blt, 零额外开销。
# 位点 5 字节 `8B xx FF 5x 14` (mov reg,[this]; call [reg+0x14]) 被 E8 覆写,
# cave 读 [esp] 取 this, 末尾 jmp site+5; 只写 eax/ecx/edx/esp, 不碰 ebp。
def build_map_bg_blt() -> bytes:
    G_RECT_VA = 0x400000 + RECT_GLOBAL_RVA
    G_DST_RECT_VA = 0x400000 + DST_RECT_RVA
    BGW, BGH = 0x00824290, 0x00824292
    VXL, VYT = 0x008242A8, 0x008242AC

    code = bytearray()
    _j32: list = []

    def emit(b: bytes) -> int:
        off = len(code)
        code.extend(b)
        return off

    def j32(cond: bytes, target: str) -> None:
        _j32.append((emit(cond + b'\x00\x00\x00\x00') + 2, target))

    # 入口 + 快慢路径分派 (快路径: 背景宽高都不小于视口 → 参数原样直调)
    emit(b'\x59')                                    # pop ecx (site+5); esp=A
    emit(b'\x89\x0D' + _g_ret2())                    # mov [g_ret2],ecx
    emit(b'\x0F\xB7\x05' + struct.pack('<I', BGW))   # movzx eax,word[824290] bgW
    emit(b'\x3D' + struct.pack('<I', W_SCREEN))      # cmp eax,856
    j32(b'\x0F\x82', 'clamp')                        # jb clamp
    emit(b'\x0F\xB7\x05' + struct.pack('<I', BGH))   # movzx eax,word[824292] bgH
    emit(b'\x3D' + struct.pack('<I', 0x1E0))         # cmp eax,480
    j32(b'\x0F\x83', 'fast')                         # jae fast
    jmp_clamp = emit(b'\xE9\x00\x00\x00\x00')        # jmp clamp (rel32 手工回填)
    fast = len(code)
    emit(b'\x8B\x14\x24')                            # mov edx,[esp] (this)
    emit(b'\x8B\x12')                                # mov edx,[edx]
    emit(b'\xFF\x52\x14')                            # call [edx+0x14] Blt -> esp=P
    emit(b'\x8B\x0D' + _g_ret2())                    # mov ecx,[g_ret2]
    emit(b'\xFF\xE1')                                # jmp ecx -> site+5
    clamp = len(code)
    # ── X: bgW>=856 → vx=clamp(viewX,0,bgW-856) 跟随;
    #    bgW<856 → vx = -((856-bgW)>>1) 恒定居中 (4:3 信箱, 左右黑边) ──
    emit(b'\x0F\xB7\x05' + struct.pack('<I', BGW))   # movzx eax,word bgW
    emit(b'\x2D' + struct.pack('<I', W_SCREEN))      # sub eax,856   (t = bgW-856)
    emit(b'\x85\xC0')                                # test eax,eax
    j32(b'\x0F\x88', 'x_narrow')                     # js x_narrow (t<0 = 窄地图)
    emit(b'\x8B\x0D' + struct.pack('<I', VXL))       # mov ecx,[8242A8] viewX
    emit(b'\x33\xD2')                                # xor edx,edx
    emit(b'\x3B\xCA')                                # cmp ecx,edx
    emit(b'\x0F\x4C\xCA')                            # cmovl ecx,edx   vx=max(viewX,0)
    emit(b'\x3B\xC8')                                # cmp ecx,eax
    emit(b'\x0F\x4F\xC8')                            # cmovg ecx,eax   vx=min(vx,t)
    jmp_xstore = emit(b'\xE9\x00\x00\x00\x00')       # jmp x_store
    x_narrow = len(code)
    emit(b'\xF7\xD8')                                # neg eax         (856-bgW > 0)
    emit(b'\xD1\xF8')                                # sar eax,1       left=(856-bgW)/2
    emit(b'\xF7\xD8')                                # neg eax         vx=-left
    emit(b'\x8B\xC8')                                # mov ecx,eax
    x_store = len(code)
    code[jmp_xstore + 1: jmp_xstore + 5] = struct.pack('<i', x_store - (jmp_xstore + 5))
    emit(b'\x89\x0D' + struct.pack('<I', VXL))       # mov [8242A8],ecx  vx 回写
    emit(b'\x81\xC1' + struct.pack('<I', W_SCREEN))  # add ecx,856
    emit(b'\x89\x0D' + struct.pack('<I', VXL + 8))   # mov [8242B0],ecx
    # ── Y: vy = clamp(viewY, L, U), L=min(0,t2), U=max(0,t2), t2 = bgH-480 ──
    emit(b'\x0F\xB7\x05' + struct.pack('<I', BGH))   # movzx eax,word bgH
    emit(b'\x2D' + struct.pack('<I', 0x1E0))         # sub eax,480   (t2)
    emit(b'\x8B\xC8')                                # mov ecx,eax
    emit(b'\x8B\xD0')                                # mov edx,eax
    emit(b'\x33\xC0')                                # xor eax,eax
    emit(b'\x85\xC9')                                # test ecx,ecx
    emit(b'\x0F\x49\xC8')                            # cmovns ecx,eax  L=(t2>=0)?0:t2
    emit(b'\x0F\x48\xD0')                            # cmovs edx,eax   U=(t2<0)?0:t2
    emit(b'\x8B\x05' + struct.pack('<I', VYT))       # mov eax,[8242AC] viewY
    emit(b'\x3B\xC1')                                # cmp eax,ecx
    emit(b'\x0F\x4C\xC1')                            # cmovl eax,ecx   vy=max(viewY,L)
    emit(b'\x3B\xC2')                                # cmp eax,edx
    emit(b'\x0F\x4F\xC2')                            # cmovg eax,edx   vy=min(vy,U)
    emit(b'\x89\x05' + struct.pack('<I', VYT))       # mov [8242AC],eax  vy 回写
    emit(b'\x05' + struct.pack('<I', 0x1E0))         # add eax,480
    emit(b'\x89\x05' + struct.pack('<I', VYT + 8))   # mov [8242B4],eax
    # ── src={max(0,vx),max(0,vy),min(bgW,vx+856),min(bgH,vy+480)} ──
    emit(b'\x8B\x15' + struct.pack('<I', VXL))       # mov edx,[8242A8] vx
    emit(b'\x85\xD2')                                # test edx,edx
    j32(b'\x0F\x89', 'sx0_done')                     # jns sx0_done
    emit(b'\x33\xD2')                                # xor edx,edx
    sx0_done = len(code)
    emit(b'\x89\x15' + struct.pack('<I', G_RECT_VA))             # src.left=sx0
    emit(b'\x2B\x15' + struct.pack('<I', VXL))       # sub edx,[8242A8] (sx0-vx)
    emit(b'\x89\x15' + struct.pack('<I', G_DST_RECT_VA))         # dst.left
    emit(b'\x8B\x15' + struct.pack('<I', VYT))       # mov edx,[8242AC] vy
    emit(b'\x85\xD2')                                # test edx,edx
    j32(b'\x0F\x89', 'sy0_done')                     # jns sy0_done
    emit(b'\x33\xD2')                                # xor edx,edx
    sy0_done = len(code)
    emit(b'\x89\x15' + struct.pack('<I', G_RECT_VA + 4))         # src.top=sy0
    emit(b'\x2B\x15' + struct.pack('<I', VYT))       # sub edx,[8242AC]
    emit(b'\x89\x15' + struct.pack('<I', G_DST_RECT_VA + 4))     # dst.top
    emit(b'\x0F\xB7\x05' + struct.pack('<I', BGW))   # movzx eax,word bgW
    emit(b'\x8B\x15' + struct.pack('<I', VXL))       # mov edx,[8242A8] vx
    emit(b'\x81\xC2' + struct.pack('<I', W_SCREEN))  # add edx,856      (vx+856)
    emit(b'\x39\xC2')                                # cmp edx,eax
    emit(b'\x0F\x4F\xD0')                            # cmovg edx,eax    sx1=min(vx+856,bgW)
    emit(b'\x89\x15' + struct.pack('<I', G_RECT_VA + 8))         # src.right=sx1
    emit(b'\x2B\x15' + struct.pack('<I', VXL))       # sub edx,[8242A8]
    emit(b'\x89\x15' + struct.pack('<I', G_DST_RECT_VA + 8))     # dst.right
    emit(b'\x0F\xB7\x05' + struct.pack('<I', BGH))   # movzx eax,word bgH
    emit(b'\x8B\x15' + struct.pack('<I', VYT))       # mov edx,[8242AC] vy
    emit(b'\x81\xC2' + struct.pack('<I', 0x1E0))     # add edx,480      (vy+480)
    emit(b'\x39\xC2')                                # cmp edx,eax
    emit(b'\x0F\x4F\xD0')                            # cmovg edx,eax    sy1=min(vy+480,bgH)
    emit(b'\x89\x15' + struct.pack('<I', G_RECT_VA + 12))        # src.bottom=sy1
    emit(b'\x2B\x15' + struct.pack('<I', VYT))       # sub edx,[8242AC]
    emit(b'\x89\x15' + struct.pack('<I', G_DST_RECT_VA + 12))    # dst.bottom
    # ── 参数槽指向新矩形 ──
    emit(b'\xC7\x44\x24\x04' + struct.pack('<I', G_DST_RECT_VA))  # [A+4]=dstRect
    emit(b'\xC7\x44\x24\x0C' + struct.pack('<I', G_RECT_VA))      # [A+C]=srcRect
    # ── colorfill 整面黑 (44F420 同款, 仅 clamp 路径 = 必有黑带) ──
    emit(b'\x81\xEC\x68\x00\x00\x00')          # sub esp,0x68 (fx 100B)
    emit(b'\xC7\x04\x24' + struct.pack('<I', 100))   # fx.dwSize=100
    emit(b'\xC7\x44\x24\x50' + b'\x00\x00\x00\x00')  # fx.dwFillColor=0 (fx+0x50, 44F420 实证; 不清零=栈垃圾色)
    emit(b'\x8B\x94\x24' + struct.pack('<I', 0x68))  # mov edx,[esp+0x68] (this=[A], esp=A-0x68)
    emit(b'\x54')                                    # push esp (fx)
    emit(b'\x68' + struct.pack('<I', 0x1000400))     # push WAIT|COLORFILL
    emit(b'\x6A\x00')                                # push 0 (srcRect)
    emit(b'\x6A\x00')                                # push 0 (src)
    emit(b'\x6A\x00')                                # push 0 (dstRect=整面)
    emit(b'\x52')                                    # push edx (this)
    emit(b'\x8B\x12')                                # mov edx,[edx]
    emit(b'\xFF\x52\x14')                            # call [edx+0x14] colorfill
    emit(b'\x81\xC4\x68\x00\x00\x00')          # add esp,0x68 (fx 收回)
    # ── Blt 背景 (esp=A → stdcall 消费 6 参 → esp=P) ──
    emit(b'\x8B\x14\x24')                            # mov edx,[esp]
    emit(b'\x8B\x12')                                # mov edx,[edx]
    emit(b'\xFF\x52\x14')                            # call [edx+0x14] Blt
    emit(b'\x8B\x0D' + _g_ret2())                    # mov ecx,[g_ret2]
    emit(b'\xFF\xE1')                                # jmp ecx -> site+5
    code[jmp_clamp + 1: jmp_clamp + 5] = struct.pack('<i', clamp - (jmp_clamp + 5))
    labels = {'clamp': clamp, 'fast': fast, 'x_narrow': x_narrow,
              'sx0_done': sx0_done, 'sy0_done': sy0_done}
    for pos, tgt in _j32:
        val = labels[tgt] - (pos + 4)
        code[pos:pos + 4] = struct.pack('<i', val)
    return bytes(code)


# ── 3d2. 相机 SetRect 视口钳制 (窄地图相机一致性) ──────────────────────
# 相机函数 (406CE0/40C8E0/43CE30/436F60/43CF78) 与两处加载初始化 (411308/
# 42FA50) 用 SetRect(&8242A8, viewX, viewY, W, H) 写视口 — 窄地图 (bgW<856)
# 时原始 viewX 超出合法区间。map_bg_blt 每帧回写钳制值, 但气泡等静态锚点在
# 注册时烘焙当时相机值 (409F4C: entry[4]=8242A8+offset), 烘焙用原始值、绘制
# 用回写值 → 静态气泡文字偏移 (相机差值, 实测 ~220px)。
# 本 cave 挂 7 个 SetRect(&8242A8,...) 调用点, 入口即钳制 l/t:
#   l = clamp(l, min(0,bgW-w), max(0,bgW-w));  t = clamp(t, min(0,bgH-h), max(0,bgH-h))
# → 相机源头恒合法。钳制后调原 SetRect (452658 绝对地址), stdcall 消费 5 参。
def build_camrect_clamp() -> bytes:
    code = bytearray()

    def emit(b: bytes) -> int:
        off = len(code)
        code.extend(b)
        return off

    emit(b'\x59')                                    # pop ecx (site+5); esp=A
    emit(b'\x89\x0D' + _g_ret2())                    # mov [g_ret2],ecx
    # ── X: l = clamp(l, min(0,bgW-w), max(0,bgW-w)) ── ([A+4]=l, [A+C]=w)
    emit(b'\x0F\xB7\x05' + struct.pack('<I', 0x00824290))  # movzx eax,word bgW
    emit(b'\x2B\x44\x24\x0C')                        # sub eax,[esp+0xC] (w)
    emit(b'\x8B\xC8')                                # mov ecx,eax
    emit(b'\x8B\xD0')                                # mov edx,eax
    emit(b'\x33\xC0')                                # xor eax,eax
    emit(b'\x85\xC9')                                # test ecx,ecx
    emit(b'\x0F\x49\xC8')                            # cmovns ecx,eax  L=min(0,t)
    emit(b'\x0F\x48\xD0')                            # cmovs edx,eax   U=max(0,t)
    emit(b'\x8B\x44\x24\x04')                        # mov eax,[esp+4] (l)
    emit(b'\x3B\xC1')                                # cmp eax,ecx
    emit(b'\x0F\x4C\xC1')                            # cmovl eax,ecx   l=max(l,L)
    emit(b'\x3B\xC2')                                # cmp eax,edx
    emit(b'\x0F\x4F\xC2')                            # cmovg eax,edx   l=min(l,U)
    emit(b'\x89\x44\x24\x04')                        # mov [esp+4],eax
    # ── Y: t = clamp(t, min(0,bgH-h), max(0,bgH-h)) ── ([A+8]=t, [A+10]=h)
    emit(b'\x0F\xB7\x05' + struct.pack('<I', 0x00824292))  # movzx eax,word bgH
    emit(b'\x2B\x44\x24\x10')                        # sub eax,[esp+0x10] (h)
    emit(b'\x8B\xC8')                                # mov ecx,eax
    emit(b'\x8B\xD0')                                # mov edx,eax
    emit(b'\x33\xC0')                                # xor eax,eax
    emit(b'\x85\xC9')                                # test ecx,ecx
    emit(b'\x0F\x49\xC8')                            # cmovns ecx,eax  L
    emit(b'\x0F\x48\xD0')                            # cmovs edx,eax   U
    emit(b'\x8B\x44\x24\x08')                        # mov eax,[esp+8] (t)
    emit(b'\x3B\xC1')                                # cmp eax,ecx
    emit(b'\x0F\x4C\xC1')                            # cmovl eax,ecx
    emit(b'\x3B\xC2')                                # cmp eax,edx
    emit(b'\x0F\x4F\xC2')                            # cmovg eax,edx
    emit(b'\x89\x44\x24\x08')                        # mov [esp+8],eax
    # ── 调原 SetRect(452658): 参数已在 [esp] (stdcall 弹 20B → esp=P) ──
    emit(b'\xB8' + struct.pack('<I', 0x452658))      # mov eax,452658
    emit(b'\xFF\xD0')                                # call eax
    emit(b'\x8B\x0D' + _g_ret2())                    # mov ecx,[g_ret2]
    emit(b'\xFF\xE1')                                # jmp ecx -> site+5
    return bytes(code)


# ── 3e. 小游戏文字位移 wrapper ─────────────────────────────────────────
# 7 个小游戏的状态/倒计时/按钮文字 44E49C 调用点 (30 个): x (arg3) += 108 与
# 背景图/瓷砖/鼠标命中 (+108) 同步居中。尾调 44E49C (栈上参数原样传递)。
def build_mg_text_shift() -> bytes:
    return (b'\xC7\x44\x24\x0C' + struct.pack('<I', PAGE_OFF)   # add dword [esp+0xC],108 (x)
            + b'\xB8' + struct.pack('<I', 0x44E49C)             # mov eax,44E49C
            + b'\xFF\xE0')                                      # jmp eax (尾调)


# ── 3e2. 结算页右对齐/格式化文字位移 wrapper (X = a2) ──────────────────
# 43B2D4/43B648 的等级/经验数字走 44E8E0 (右对齐, 逐字符从右往左画, X=a2),
# 页码 "第x/y页" 走 44E8A8 (sprintf + 44E49C, X=a2)。两者的 X 都是第 2 参
# ([esp+8]), 与 44E49C 直接调用点的 a3 ([esp+0xC]) 不同 —— 结算页面板精灵
# 八轮已 +108, 这些文字位点漏钩 → 数字/页码整体左偏 108 (结算页"割裂"观感
# 的文字成分)。尾调各自目标 (栈上参数原样传递, cdecl 由调用方平衡)。
def build_text_shift_a2(target_fn: int) -> bytes:
    return (b'\xC7\x44\x24\x08' + struct.pack('<I', PAGE_OFF)   # add dword [esp+8],108 (x=a2)
            + b'\xB8' + struct.pack('<I', target_fn)            # mov eax,target
            + b'\xFF\xE0')                                      # jmp eax (尾调)



# ── 2d. JVG 精灵两步解码 (照 TKSRemake 重写: 解码与混合分离) ────────────
# 原版绘制原语把 RLE 解码与写显存融合: 目标指针从帧右下角沿 640 宽平面
# 反向线性行走, skip/run 内嵌 640 行几何。屏幕加宽到 856 后, 只改步长常量
# 会让跨行回绕落点错 216px (地图/战斗精灵成网格碎片), 常量替换无法消除。
# TKSRemake 的权威做法 (Jvg.cpp DecodeRle + SceneRender.cpp BlitSpritePixel):
#   ① 解码只认 640 平面: row=p640/640, col=p640%640,
#      buf[(h-1-row)*w+(w-1-col)] = palette[byte]; skip 覆盖透明像素;
#   ② 贴图按真实 stride 逐像素写目标, 按 d24 用混合模式 0-5;
#      遮挡分支 (459F78/45AA8C) 逐像素查 L1 掩码 mask<depth。
# 本处理器把两步合一 (解码的同时按原坐标混合), 与目标位置无关, 因此不再
# 需要 640 平面/锚点重定位/裁剪分支。挂 18 个原语入口, 每个入口一条跳板
# (丢 fn+5、把模式号放进 edx) 跳共享 handler。
# ABI (cdecl): a1=obj[ebp+8] a2=X[ebp+0xC] a3=Y[ebp+0x10]
#              a4=frame[ebp+0x14] a5=dst[ebp+0x18]
# 普通 mode 0-5: [ebp+0x1C]=flag (mode1 时 alpha, flag 在 [ebp+0x20])
# 遮挡 mode 6/7: [ebp+0x1C]=wx [ebp+0x20]=wy [ebp+0x24]=depth [ebp+0x28]=flag
G_STRIDE = 0x400000 + STRIDE_GLOBAL_RVA

L_MODE = -0x10
L_BLK = -0x14
L_X = -0x18
L_Y = -0x1C
L_FRM = -0x20
L_DST = -0x24
L_STR = -0x28
L_CW = -0x2C
L_W = -0x34
L_H = -0x38
L_XOFF = -0x3C
L_YOFF = -0x40
L_LEFT = -0x44
L_TOP = -0x48
L_LUT = -0x4C
L_SRC = -0x50
L_RCNT = -0x54
L_ROW = -0x5C
L_COL = -0x60
L_ALPHA = -0x64
L_MB = -0x68
L_MW = -0x6C
L_WX = -0x70
L_WY = -0x74
L_DEP = -0x78
L_FX = -0x7C
L_FY = -0x80
L_S = -0x84
L_DX = -0x88
L_DY = -0x8C
L_RUN = -0x90
L_TMP = -0x94
L_D = -0x98
FRAME = 0xA0


class A:
    def __init__(self):
        self.b = bytearray(); self.lab = {}; self.fix = []

    def e(self, x): self.b += x; return self
    def L(self, n): self.lab[n] = len(self.b)
    def _rel(self, n): self.fix.append((len(self.b), n)); self.b += b'\x00\x00\x00\x00'
    def jmp(self, n): self.e(b'\xE9'); self._rel(n)
    def call(self, n): self.e(b'\xE8'); self._rel(n)

    def j(self, cc, n):
        op = {'e': 0x84, 'ne': 0x85, 'ge': 0x8D, 'l': 0x8C, 'g': 0x8F, 'le': 0x8E,
              'ae': 0x83, 'b': 0x82, 'a': 0x87, 'be': 0x86, 's': 0x88, 'ns': 0x89}[cc]
        self.e(b'\x0F' + bytes([op])); self._rel(n)

    def mr(self, reg, off):
        if -0x80 <= off <= 0x7F:
            return bytes([0x45 | (reg << 3), off & 0xFF])
        return bytes([0x85 | (reg << 3)]) + struct.pack('<i', off)

    def ld(self, r, o): self.e(bytes([0x8B]) + self.mr(r, o))
    def st(self, r, o): self.e(bytes([0x89]) + self.mr(r, o))
    def imm(self, o, v): self.e(b'\xC7' + self.mr(0, o) + struct.pack('<I', v))
    def addm(self, r, o): self.e(bytes([0x03]) + self.mr(r, o))
    def subm(self, r, o): self.e(bytes([0x2B]) + self.mr(r, o))
    def cmpm(self, r, o): self.e(bytes([0x3B]) + self.mr(r, o))
    def imulm(self, r, o): self.e(b'\x0F\xAF' + self.mr(r, o))
    def incm(self, o): self.e(b'\xFF' + self.mr(0, o))
    def decm(self, o): self.e(b'\xFF' + self.mr(1, o))
    def cmpm_imm8(self, o, v): self.e(b'\x83' + self.mr(7, o) + bytes([v & 0xFF]))

    def resolve(self):
        for pos, n in self.fix:
            self.b[pos:pos + 4] = struct.pack('<i', self.lab[n] - (pos + 4))
        return bytes(self.b)


def build_handler(entity_only=False):
    a = A()
    a.e(b'\x55\x8B\xEC\x53\x56\x57')
    a.e(b'\x81\xEC' + struct.pack('<I', FRAME))
    a.st(2, L_MODE)
    if SPR_DEBUG:
        # 每模式调用计数 + 最后一批入参 (探针)
        a.ld(0, L_MODE); a.e(b'\x25\x07\x00\x00\x00')          # and eax,7
        a.e(b'\xFF\x04\x85' + _dbg(0x00))                      # inc [DBG+eax*4]
        a.ld(0, L_MODE); a.e(b'\xA3' + _dbg(0x28))
        a.e(b'\x8B\x45\x08'); a.e(b'\xA3' + _dbg(0x2C))        # obj
        a.e(b'\x8B\x45\x14'); a.e(b'\xA3' + _dbg(0x30))        # frame
        a.e(b'\x8B\x45\x0C'); a.e(b'\xA3' + _dbg(0x34))        # X
        a.e(b'\x8B\x45\x10'); a.e(b'\xA3' + _dbg(0x38))        # Y
        a.e(b'\x8B\x45\x18'); a.e(b'\xA3' + _dbg(0x3C))        # dst
    a.e(b'\x8B\x75\x08')                       # esi = obj
    a.e(b'\x85\xF6'); a.j('e', 'done')         # obj 空 → 跳过 (防野指针)
    a.e(b'\x8B\x45\x0C'); a.st(0, L_X)
    a.e(b'\x8B\x45\x10'); a.st(0, L_Y)
    # 小游戏居中: trampoline 以 mode|0x80 标记 → X += 108 (背景/瓷砖/文字/鼠标全链同步位移)
    a.ld(0, L_MODE)                                  # mov eax,[ebp+L_MODE]
    a.e(b'\xA8\x80')                                 # test al,0x80
    a.j('e', 'no_mg_shift')
    a.e(b'\x81\x45' + bytes([L_X & 0xFF]) + struct.pack('<I', PAGE_OFF))  # add dword [ebp+L_X],108
    a.ld(0, L_MODE)
    a.e(b'\x25\x7F\x00\x00\x00')                     # and eax,0x7f
    a.st(0, L_MODE)
    a.L('no_mg_shift')
    a.e(b'\x8B\x45\x18'); a.st(0, L_DST)
    # ⚠ 帧号按 16 位有符号读: 原版 case 分支是 `mov ax,[entity+56]` 后整体 push eax
    # (高 16 位是残留的实体指针), 被调函数只读 word[ebp+0x14]。读完整 32 位会把
    # 高 16 位垃圾当帧号 → "帧号 < 总帧数" 判断失败 → 身体整路被跳过 (只剩影子)。
    a.e(b'\x0F\xBF\x45\x14'); a.st(0, L_FRM)   # movsx eax,word[ebp+0x14]
    a.e(b'\x85\xC0'); a.j('s', 'done')         # 原版 a5>=0 不成立则 return
    a.e(b'\x8B\x45\x18'); a.st(0, L_DST)
    a.e(b'\xA1' + struct.pack('<I', G_STRIDE))
    a.e(b'\x85\xC0'); a.j('e', 'done')         # g_stride 未初始化 → 跳过
    a.e(b'\x3D\x00\x10\x00\x00'); a.j('a', 'done')   # >4096 异常 → 跳过
    a.st(0, L_STR); a.st(0, L_CW)
    if SPR_DEBUG:
        a.e(b'\xA3' + _dbg(0x74))                      # 最后 g_stride
        a.e(b'\x3D' + struct.pack('<I', W_SCREEN))
        a.j('e', 'dbg_sd_ok')
        a.e(b'\xFF\x05' + _dbg(0x70))                  # g_stride != 856 计数
        a.L('dbg_sd_ok')

    # frame lookup
    a.ld(0, L_FRM)
    a.e(b'\x3B\x46\x18'); a.j('ae', 'done')
    a.e(b'\x8B\x4E\x0C\x0F\xB7\x04\x41')       # eax = sub-index
    a.e(b'\x8B\x56\x08')
    a.ld(1, L_FRM)
    a.e(b'\x0F\xB7\x0C\x4A\xC1\xE1\x06\x03\x0E')   # ecx = blk
    a.st(1, L_BLK)
    a.e(b'\x3B\x01'); a.j('ae', 'done')
    a.e(b'\x8B\x51\x28\x8B\x14\x82\x03\x51\x2C')   # edx = rec
    a.e(b'\x85\xD2'); a.j('e', 'done')

    # geometry
    a.e(b'\x0F\xBF\x02')                       # movsx eax,[edx] xMax
    a.e(b'\x0F\xB7\x4A\x04'); a.st(1, L_W)     # movzx ecx,[edx+4]
    a.e(b'\x29\xC8\x40'); a.st(0, L_XOFF)      # sub eax,ecx; inc eax
    a.e(b'\x0F\xBF\x42\x02')                   # movsx eax,[edx+2] yMax
    a.e(b'\x0F\xB7\x4A\x06'); a.st(1, L_H)
    a.e(b'\x29\xC8\x40'); a.st(0, L_YOFF)
    a.e(b'\x0F\xB7\x42\x0E'); a.st(0, L_RCNT)  # recordCount
    a.e(b'\x83\xC2\x10'); a.st(2, L_SRC)       # src = rec+16
    # 不做 w/h 合法性判断 — 原版全量分支不用 w/h, 加了会把真实帧误跳过。

    a.ld(0, L_X); a.addm(0, L_XOFF); a.st(0, L_LEFT)
    a.ld(0, L_Y); a.addm(0, L_YOFF); a.st(0, L_TOP)

    # LUT。entity_only 时 flag 恒为 -1 (406864 的实体调用点都传 -1),
    # 直接走 blk[60] 索引层, 避开按模式猜 flag 栈偏移的问题。
    a.ld(1, L_BLK)
    if not entity_only:
        a.ld(0, L_MODE)
        a.e(b'\x83\xF8\x01'); a.j('e', 'fl_a')
        a.e(b'\x83\xF8\x06'); a.j('l', 'fl_d')
        a.e(b'\x8B\x45\x28'); a.jmp('fl_g')
        a.L('fl_a'); a.e(b'\x8B\x45\x20'); a.jmp('fl_g')
        a.L('fl_d'); a.e(b'\x8B\x45\x1C')
        a.L('fl_g')
        a.e(b'\x85\xC0'); a.j('s', 'fl_i')
        a.e(b'\x8B\x54\x81\x08'); a.jmp('fl_h')
        a.L('fl_i')
    a.e(b'\x8B\x41\x3C\x8B\x54\x81\x08')
    a.L('fl_h')
    a.e(b'\x85\xD2'); a.j('ne', 'fl_s')
    a.e(b'\x8B\x51\x04')
    a.L('fl_s'); a.st(2, L_LUT)
    if SPR_DEBUG:
        # 按模式记录: DBG+0x100+mode*0x20 = {frame,h,left,top,dst,w,rcnt}
        a.ld(0, L_MODE); a.e(b'\xC1\xE0\x05')          # shl eax,5
        a.e(b'\x8B\x4D' + bytes([L_FRM & 0xFF]));   a.e(b'\x89\x0C\x05' + _dbg(0x100))
        a.e(b'\x8B\x4D' + bytes([L_H & 0xFF]));     a.e(b'\x89\x0C\x05' + _dbg(0x104))
        a.e(b'\x8B\x4D' + bytes([L_LEFT & 0xFF]));  a.e(b'\x89\x0C\x05' + _dbg(0x108))
        a.e(b'\x8B\x4D' + bytes([L_TOP & 0xFF]));   a.e(b'\x89\x0C\x05' + _dbg(0x10C))
        a.e(b'\x8B\x4D' + bytes([L_DST & 0xFF]));   a.e(b'\x89\x0C\x05' + _dbg(0x110))
        a.e(b'\x8B\x4D' + bytes([L_W & 0xFF]));     a.e(b'\x89\x0C\x05' + _dbg(0x114))
        a.e(b'\x8B\x4D' + bytes([L_RCNT & 0xFF]));  a.e(b'\x89\x0C\x05' + _dbg(0x118))
    if SPR_DEBUG:
        a.ld(0, L_LEFT); a.e(b'\xA3' + _dbg(0x40))
        a.ld(0, L_TOP); a.e(b'\xA3' + _dbg(0x44))
        a.ld(0, L_W); a.e(b'\xA3' + _dbg(0x48))
        a.ld(0, L_H); a.e(b'\xA3' + _dbg(0x4C))
        a.ld(0, L_RCNT); a.e(b'\xA3' + _dbg(0x50))
        a.ld(2, L_SRC); a.e(b'\x89\x15' + _dbg(0x54))   # rec(RLE 起点)

    # occluded args
    a.ld(0, L_MODE); a.e(b'\x83\xF8\x06'); a.j('l', 'no_occl')
    a.e(b'\x8B\x45\x1C'); a.st(0, L_WX)
    a.e(b'\x8B\x45\x20'); a.st(0, L_WY)
    # 深度按 8 位有符号读 (原版 459F78 形参是 char, 调用点也是 BYTE 字段 +88)
    a.e(b'\x0F\xBE\x45\x24'); a.st(0, L_DEP)
    if SPR_DEBUG:
        a.ld(0, L_WX); a.e(b'\xA3' + _dbg(0x58))
        a.ld(0, L_WY); a.e(b'\xA3' + _dbg(0x5C))
        a.ld(0, L_DEP); a.e(b'\xA3' + _dbg(0x60))
    a.e(b'\x8B\x46\x1C'); a.st(0, L_MB)
    a.e(b'\x8B\x46\x20'); a.st(0, L_MW)
    # 掩码基址/行宽非法 → 跳过 (等价 459EF4 的 a1[7]!=0 前置检查, 防野读崩溃)
    a.ld(0, L_MB); a.e(b'\x85\xC0'); a.j('e', 'done')
    a.ld(0, L_MW); a.e(b'\x85\xC0'); a.j('e', 'done')
    a.e(b'\x3D\x00\x00\x01\x00'); a.j('a', 'done')   # mw > 0x10000 → 跳过
    a.L('no_occl')
    # mode1 alpha
    a.ld(0, L_MODE); a.e(b'\x83\xF8\x01'); a.j('ne', 'no_alpha')
    a.e(b'\x0F\xB7\x45\x1C'); a.st(0, L_ALPHA)   # movzx eax,word[ebp+0x1C] alpha
    a.L('no_alpha')
    a.imm(L_ROW, 0); a.imm(L_COL, 0)

    # ---- record loop ----
    a.L('rec_loop')
    a.cmpm_imm8(L_RCNT, 0); a.j('e', 'done')
    a.ld(6, L_SRC)
    a.e(b'\x0F\xB7\x06')                       # skip
    a.e(b'\x0F\xB7\x4E\x02')                   # run
    a.e(b'\x83\xC6\x04'); a.st(6, L_SRC)
    a.st(1, L_RUN)
    a.e(b'\x85\xC0'); a.j('e', 'skip_done')
    a.addm(0, L_COL)
    a.L('cw')
    a.e(b'\x3D\x80\x02\x00\x00'); a.j('l', 'cwd')
    a.e(b'\x2D\x80\x02\x00\x00'); a.incm(L_ROW); a.jmp('cw')
    a.L('cwd'); a.st(0, L_COL)
    a.L('skip_done')

    # ---- pixel loop ----
    a.L('px_loop')
    a.cmpm_imm8(L_RUN, 0); a.j('e', 'rec_end')
    if SPR_DEBUG:
        a.e(b'\xFF\x05' + _dbg(0x24))                                  # 处理像素数
    # ⚠ 不判 row<h / col<w — 原版全量分支不做该判断, 它会画到 w×h 之外
    # (线性回绕), 加了会把真实帧的像素成片丢掉 (实测主角身体不显示)。
    a.ld(2, L_W); a.ld(1, L_COL); a.e(b'\x29\xCA\x4A'); a.st(2, L_FX)   # fx=W-1-col
    a.ld(1, L_H); a.ld(0, L_ROW); a.e(b'\x29\xC1\x49'); a.st(1, L_FY)   # fy=H-1-row
    a.ld(0, L_LEFT); a.addm(0, L_FX); a.st(0, L_DX)
    a.ld(0, L_TOP); a.addm(0, L_FY); a.st(0, L_DY)
    a.ld(0, L_DX); a.cmpm(0, L_CW); a.j('ae', 'adv')
    a.ld(0, L_DY); a.e(b'\x3D\xE0\x01\x00\x00'); a.j('ae', 'adv')   # dy>=480
    if SPR_DEBUG:
        a.e(b'\xFF\x05' + _dbg(0x20))                                  # 落在画布内的像素数
    # s = LUT[src[0]]
    a.ld(6, L_SRC); a.e(b'\x0F\xB6\x06')
    a.ld(7, L_LUT); a.e(b'\x0F\xB7\x3C\x47'); a.st(7, L_S)
    # occluded mask
    a.ld(0, L_MODE); a.e(b'\x83\xF8\x06'); a.j('l', 'no_mask')
    a.ld(0, L_WX); a.addm(0, L_XOFF); a.addm(0, L_FX)
    a.ld(1, L_WY); a.addm(1, L_YOFF); a.addm(1, L_FY)
    a.imulm(1, L_MW); a.e(b'\x01\xC1'); a.addm(1, L_MB)
    a.e(b'\x0F\xB6\x01'); a.cmpm(0, L_DEP); a.j('l', 'mask_ok')
    if SPR_DEBUG:
        a.e(b'\xFF\x05' + _dbg(0x68))
    a.jmp('adv')
    a.L('mask_ok')
    a.L('no_mask')
    # dst ptr
    a.ld(0, L_DY); a.imulm(0, L_STR); a.addm(0, L_DX)
    a.ld(1, L_DST); a.e(b'\x8D\x3C\x41'); a.e(b'\x0F\xB7\x07'); a.st(0, L_D)

    # dispatch
    a.ld(1, L_MODE)
    a.e(b'\x85\xC9'); a.j('e', 'm0')
    a.e(b'\x83\xF9\x01'); a.j('e', 'm1')
    a.e(b'\x83\xF9\x02'); a.j('e', 'm2')
    a.e(b'\x83\xF9\x03'); a.j('e', 'm3')
    a.e(b'\x83\xF9\x04'); a.j('e', 'm4')
    a.e(b'\x83\xF9\x05'); a.j('e', 'm5')
    a.e(b'\x83\xF9\x06'); a.j('e', 'm6')
    a.jmp('m3')                                 # m7 = subtract + mask

    a.L('m0'); a.ld(0, L_S); (a.e(b'\xFF\x05' + _dbg(0x64)) if SPR_DEBUG else None); a.e(b'\x66\x89\x07'); a.jmp('adv')
    a.L('m6'); a.ld(0, L_S); (a.e(b'\xFF\x05' + _dbg(0x64)) if SPR_DEBUG else None); a.e(b'\x66\x89\x07'); a.jmp('adv')
    a.L('store_s'); a.ld(0, L_S); (a.e(b'\xFF\x05' + _dbg(0x64)) if SPR_DEBUG else None); a.e(b'\x66\x89\x07'); a.jmp('adv')

    a.L('m1')
    a.ld(1, L_ALPHA); a.e(b'\x85\xC9'); a.j('e', 'adv')
    a.e(b'\x83\xF9\x1F'); a.j('a', 'store_s')
    a.st(1, L_ALPHA); a.jmp('weight')

    a.L('m4')
    a.ld(0, L_S); a.call('gray')
    a.e(b'\x85\xC0'); a.j('e', 'adv')
    a.e(b'\x83\xF8\x1C'); a.j('a', 'store_s')
    a.st(0, L_ALPHA); a.jmp('weight')

    a.L('m2')
    a.ld(0, L_S); a.call('gray')
    a.e(b'\x83\xF8\x1C'); a.j('a', 'store_s')
    a.jmp('add')

    a.L('m5')
    a.ld(0, L_S); a.call('gray')
    a.e(b'\x89\xC2\xC1\xE2\x06\x09\xD0')       # mov edx,eax; shl edx,6; or eax,edx
    a.e(b'\x89\xC1\xC1\xE1\x0B\x09\xC8')       # mov ecx,eax; shl ecx,11; or eax,ecx
    (a.e(b'\xFF\x05' + _dbg(0x64)) if SPR_DEBUG else None); a.e(b'\x66\x89\x07'); a.jmp('adv')

    # ---- weight blend (ecx/weight in [L_ALPHA]) ----
    a.L('weight')
    # r
    a.ld(0, L_D); a.e(b'\x89\xC2\xC1\xEA\x0B\x83\xE2\x1F')
    a.ld(1, L_S); a.e(b'\x89\xCB\xC1\xEB\x0B\x83\xE3\x1F')
    a.e(b'\xB8\x20\x00\x00\x00'); a.subm(0, L_ALPHA)
    a.e(b'\x0F\xAF\xD0')
    a.ld(1, L_ALPHA); a.e(b'\x0F\xAF\xD9')
    a.e(b'\x01\xDA\xC1\xEA\x05\xC1\xE2\x0B'); a.st(2, L_TMP)
    # g
    a.ld(0, L_D); a.e(b'\x89\xC3\xC1\xEB\x05\x83\xE3\x3F')
    a.ld(1, L_S); a.e(b'\x89\xC8\xC1\xE8\x05\x83\xE0\x3F')
    a.e(b'\xBA\x20\x00\x00\x00'); a.subm(2, L_ALPHA)
    a.e(b'\x0F\xAF\xDA')
    a.ld(1, L_ALPHA); a.e(b'\x0F\xAF\xC1')
    a.e(b'\x01\xC3\xC1\xEB\x05\xC1\xE3\x05')
    # b
    a.ld(0, L_D); a.e(b'\x83\xE0\x1F')
    a.ld(1, L_S); a.e(b'\x83\xE1\x1F')
    a.e(b'\xBA\x20\x00\x00\x00'); a.subm(2, L_ALPHA)
    a.e(b'\x0F\xAF\xC2')
    a.imulm(1, L_ALPHA)
    a.e(b'\x01\xC8\xC1\xE8\x05')
    a.e(b'\x09\xD8'); a.addm(0, L_TMP)
    (a.e(b'\xFF\x05' + _dbg(0x64)) if SPR_DEBUG else None); a.e(b'\x66\x89\x07'); a.jmp('adv')

    # ---- add (mode2) ----
    a.L('add')
    a.ld(0, L_D); a.e(b'\x89\xC2\xC1\xEA\x0B\x83\xE2\x1F')
    a.ld(1, L_S); a.e(b'\x89\xCB\xC1\xEB\x0B\x83\xE3\x1F')
    a.e(b'\x01\xDA'); a.e(b'\x83\xFA\x1F\x76\x05\xBA\x1F\x00\x00\x00')
    a.e(b'\xC1\xE2\x0B'); a.st(2, L_TMP)
    a.ld(0, L_D); a.e(b'\x89\xC3\xC1\xEB\x05\x83\xE3\x3F')
    a.ld(1, L_S); a.e(b'\x89\xC8\xC1\xE8\x05\x83\xE0\x3F')
    a.e(b'\x01\xC3'); a.e(b'\x83\xFB\x3F\x76\x05\xBB\x3F\x00\x00\x00')
    a.e(b'\xC1\xE3\x05')
    a.ld(0, L_D); a.e(b'\x83\xE0\x1F')
    a.ld(1, L_S); a.e(b'\x83\xE1\x1F')
    a.e(b'\x01\xC8'); a.e(b'\x83\xF8\x1F\x76\x05\xB8\x1F\x00\x00\x00')
    a.e(b'\x09\xD8'); a.addm(0, L_TMP)
    (a.e(b'\xFF\x05' + _dbg(0x64)) if SPR_DEBUG else None); a.e(b'\x66\x89\x07'); a.jmp('adv')

    # ---- subtract (mode3/7) ----
    a.L('m3')
    a.ld(0, L_D); a.e(b'\x89\xC2\xC1\xEA\x0B\x83\xE2\x1F')
    a.ld(1, L_S); a.e(b'\x89\xCB\xC1\xEB\x0B\x83\xE3\x1F')
    a.e(b'\x29\xDA\x79\x02\x31\xD2\xC1\xE2\x0B'); a.st(2, L_TMP)
    a.ld(0, L_D); a.e(b'\x89\xC3\xC1\xEB\x05\x83\xE3\x3F')
    a.ld(1, L_S); a.e(b'\x89\xC8\xC1\xE8\x05\x83\xE0\x3F')
    a.e(b'\x29\xC3\x79\x02\x31\xDB\xC1\xE3\x05')
    a.ld(0, L_D); a.e(b'\x83\xE0\x1F')
    a.ld(1, L_S); a.e(b'\x83\xE1\x1F')
    a.e(b'\x29\xC8\x79\x02\x31\xC0')
    a.e(b'\x09\xD8'); a.addm(0, L_TMP)
    (a.e(b'\xFF\x05' + _dbg(0x64)) if SPR_DEBUG else None); a.e(b'\x66\x89\x07'); a.jmp('adv')

    # ---- grayscale (eax=color -> eax=lum&31) ----
    a.L('gray')
    a.e(b'\x89\xC2\xC1\xEA\x0B\x83\xE2\x1F\x6B\xD2\x1E')
    a.e(b'\x89\xC3\xC1\xEB\x06\x83\xE3\x1F\x6B\xDB\x3B')
    a.e(b'\x01\xDA\x83\xE0\x1F\x6B\xC0\x0B\x01\xD0')
    a.e(b'\x33\xD2\xB9\x64\x00\x00\x00\xF7\xF1\x83\xE0\x1F\xC3')

    # ---- advance (col++, row wrap at 640, run--, src++) ----
    a.L('adv')
    a.incm(L_COL)
    a.e(b'\x81\x7D' + bytes([(L_COL) & 0xFF]) + struct.pack('<I', 640))
    a.j('b', 'adv2')
    a.imm(L_COL, 0); a.incm(L_ROW)
    a.L('adv2')
    a.decm(L_RUN); a.incm(L_SRC); a.jmp('px_loop')

    a.L('rec_end')
    a.decm(L_RCNT); a.jmp('rec_loop')

    a.L('done')
    a.e(b'\x31\xC0')                            # xor eax,eax
    a.e(b'\x81\xC4' + struct.pack('<I', FRAME))
    a.e(b'\x5F\x5E\x5B\x5D\xC3')
    return a.resolve()


def build_block(hooks, entity_only=False, pop_ret=True):
    """hooks: [(name, va, prologue_hex, mode)] -> (blob, {entry: off})

    pop_ret: 挂"函数入口"时必须为 True —— 入口处栈上是 [fn+5][调用者 ret][args],
     跳板要先 pop 掉 fn+5; 挂"调用点"时必须为 False —— 该处栈上只有一层返回
     地址, 再 pop 会把第一个参数弹掉, 整个参数表左移一位 (实测读档进图崩溃)。
    """
    a = A()
    off = {}
    jfix = []
    for name, va, pro, mode in hooks:
        off['spr_' + name] = len(a.b)
        if pop_ret:
            a.e(b'\x58')                        # pop eax (discard fn+5)
        a.e(b'\xBA' + struct.pack('<I', mode))  # mov edx, mode
        a.e(b'\xE9'); jfix.append((len(a.b), 'H'))
        a.b += b'\x00\x00\x00\x00'
    off['spr_handler'] = len(a.b)
    a.b += build_handler(entity_only=entity_only)
    for pos, _ in jfix:
        a.b[pos:pos + 4] = struct.pack('<i', off['spr_handler'] - (pos + 4))
    return bytes(a.b), off


# 实体精灵调用点 (sub_406864 内), 不是绘制原语本身。
# 只改这些 call 的目标 → 通用 640 平面解码处理器; UI/菜单/物品图标/光标仍走
# 原版绘制原语, 混合语义零改动 (上一版整体替换 18 个原语导致 UI 全失效的教训)。
# (名称, 调用点 VA, 该处原 E8 5 字节 hex, 模式)
#   mode0 不透明 / 1 alpha / 2 加法 / 3 减法 / 4 灰度alpha / 5 灰度写入
#   6 遮挡不透明 / 7 遮挡减法
_ENTITY_HOOKS = [
    ('ent_shadow_s', 0x4069B7, 'e864160500', 3),   # 简单分支影子 458020
    ('ent_m0', 0x406A10, 'e8d7da0400', 0),         # 4544EC
    ('ent_m1', 0x406A4A, 'e8d5e20400', 1),         # 454D24
    ('ent_m2', 0x406A86, 'e845ef0400', 2),         # 4559D0
    ('ent_m3', 0x406AB9, 'e862150500', 3),         # 458020
    ('ent_m4', 0x406AE7, 'e87c260500', 4),         # 459168
    ('ent_m5', 0x406B16, 'e8ed210500', 5),         # 458D08
    ('ent_occl_shadow', 0x406BA3, 'e8603e0500', 7),  # 遮挡影子 45AA08
    ('ent_occl_m', 0x406C19, 'e8d6320500', 6),     # 遮挡主体 459EF4
    ('ent_occl_m3', 0x406C76, 'e88d3d0500', 7),    # 遮挡 d24=3 主体 45AA08
]

# 战斗渲染器 sub_43339C 内的单位绘制调用点 (该函数直接调绘制原语, 不经 406864)。
# 参数/帧号语义与 406864 同构 (帧号在调用点 mov cx/ax,word[...] 后整体压栈),
# 故沿用同一处理器 (entity_only + 不 pop)。
_BATTLE_HOOKS = [
    ('bt4334CC', 0x4334CC, 'e81b100200', 0),
    ('bt433547', 0x433547, 'e8d44a0200', 3),
    ('bt433584', 0x433584, 'e8df5b0200', 4),
    ('bt4335B4', 0x4335B4, 'e8330f0200', 0),
    ('bt4337E8', 0x4337E8, 'e8ff0c0200', 0),
    ('bt433864', 0x433864, 'e8b7470200', 3),
    ('bt4338A1', 0x4338A1, 'e8c2580200', 4),
    ('bt4338D2', 0x4338D2, 'e8150c0200', 0),
    ('bt433928', 0x433928, 'e8bf0b0200', 0),
    ('bt43396F', 0x43396F, 'e8ac460200', 3),
    ('bt433B90', 0x433B90, 'e857090200', 0),
    ('bt433C0C', 0x433C0C, 'e80f440200', 3),
    ('bt433C49', 0x433C49, 'e81a550200', 4),
    ('bt433C7A', 0x433C7A, 'e86d080200', 0),
    ('bt4342EA', 0x4342EA, 'e8fd010200', 0),
    ('bt434366', 0x434366, 'e8b53c0200', 3),
    ('bt4343A2', 0x4343A2, 'e8c14d0200', 4),
    ('bt4343D3', 0x4343D3, 'e814010200', 0),
    ('bt434466', 0x434466, 'e865150200', 2),
    ('bt4344AA', 0x4344AA, 'e83d000200', 0),
    ('bt434AC7', 0x434AC7, 'e8040f0200', 2),
    ('bt434BB0', 0x434BB0, 'e81b0e0200', 2),
    ('bt434F77', 0x434F77, 'e870f50100', 0),
    ('bt434FF3', 0x434FF3, 'e828300200', 3),
    ('bt435030', 0x435030, 'e833410200', 4),
    ('bt435061', 0x435061, 'e886f40100', 0),
    ('bt4350B8', 0x4350B8, 'e813090200', 2),
    ('bt43755D', 0x43755D, 'e88acf0100', 0),
    ('bt4375AC', 0x4375AC, 'e83bcf0100', 0),
    ('bt4375E7', 0x4375E7, 'e800cf0100', 0),
    ('bt43761A', 0x43761A, 'e8cdce0100', 0),
    ('bt437659', 0x437659, 'e88ece0100', 0),
    ('bt4377B0', 0x4377B0, 'e86fd50100', 1),
    ('bt4377F7', 0x4377F7, 'e8f0cc0100', 0),
    ('bt437820', 0x437820, 'e8c7cc0100', 0),
    ('bt437853', 0x437853, 'e8c8070200', 3),
    ('bt4378C3', 0x4378C3, 'e824cc0100', 0),
    ('bt43791C', 0x43791C, 'e847180200', 4),
    ('bt437963', 0x437963, 'e884cb0100', 0),
    ('bt437990', 0x437990, 'e857cb0100', 0),
    ('bt437E67', 0x437E67, 'e880c60100', 0),
    ('bt4382F4', 0x4382F4, 'e8f3c10100', 0),
    ('bt4384D7', 0x4384D7, 'e810c00100', 0),
    ('bt43851A', 0x43851A, 'e8490c0200', 4),
    ('bt438550', 0x438550, 'e897bf0100', 0),
    ('bt43856B', 0x43856B, 'e87cbf0100', 0),
    ('bt438589', 0x438589, 'e892fa0100', 3),
    ('bt4385AF', 0x4385AF, 'e870c70100', 1),
    ('bt4385D7', 0x4385D7, 'e844fa0100', 3),
    ('bt4386A0', 0x4386A0, 'e847be0100', 0),
    ('bt4386E7', 0x4386E7, 'e87c0a0200', 4),
    ('bt438720', 0x438720, 'e8c7bd0100', 0),
    ('bt43873D', 0x43873D, 'e8aabd0100', 0),
    ('bt43875F', 0x43875F, 'e8bcf80100', 3),
    ('bt438789', 0x438789, 'e896c50100', 1),
    ('bt4387B5', 0x4387B5, 'e866f80100', 3),
    ('bt438853', 0x438853, 'e8ccc40100', 1),
    ('bt438881', 0x438881, 'e89af70100', 3),
    ('bt439446', 0x439446, 'e8d9b80100', 1),
    ('bt439475', 0x439475, 'e8a6eb0100', 3),
    ('bt4394CD', 0x4394CD, 'e852b80100', 1),
    ('bt4395F0', 0x4395F0, 'e82fb70100', 1),
    ('bt439687', 0x439687, 'e894e90100', 3),
    ('bt4396D2', 0x4396D2, 'e84db60100', 1),
    ('bt439704', 0x439704, 'e817e90100', 3),
    ('bt4397D5', 0x4397D5, 'e84ab50100', 1),
    ('bt43980B', 0x43980B, 'e810e80100', 3),
    ('bt43989B', 0x43989B, 'e884b40100', 1),
    ('bt4398CA', 0x4398CA, 'e851e70100', 3),
    ('bt439929', 0x439929, 'e8f6b30100', 1),
    ('bt4399B6', 0x4399B6, 'e831ab0100', 0),
    ('bt439B61', 0x439B61, 'e8beb10100', 1),
    ('bt439BF9', 0x439BF9, 'e822e40100', 3),
    ('bt439C4A', 0x439C4A, 'e8d5b00100', 1),
    ('bt439C7C', 0x439C7C, 'e89fe30100', 3),
    ('bt439D67', 0x439D67, 'e8b8af0100', 1),
    ('bt439E6F', 0x439E6F, 'e878a60100', 0),
    ('bt439EBF', 0x439EBF, 'e8a4f20100', 4),
    ('bt439EFE', 0x439EFE, 'e8e9a50100', 0),
    ('bt439F3B', 0x439F3B, 'e8aca50100', 0),
    ('bt43A032', 0x43A032, 'e8b5a40100', 0),
    ('bt43A10B', 0x43A10B, 'e8dca30100', 0),
    ('bt43A16F', 0x43A16F, 'e878a30100', 0),
    ('bt43A1FE', 0x43A1FE, 'e8e9a20100', 0),
    ('bt43A245', 0x43A245, 'e8a2a20100', 0),
    ('bt43A28B', 0x43A28B, 'e85ca20100', 0),
    ('bt43A2D1', 0x43A2D1, 'e816a20100', 0),
    ('bt43A317', 0x43A317, 'e8d0a10100', 0),
    ('bt43A39C', 0x43A39C, 'e84ba10100', 0),
    ('bt43A43A', 0x43A43A, 'e8ada00100', 0),
    ('bt43A47B', 0x43A47B, 'e86ca00100', 0),
    ('bt43A4EA', 0x43A4EA, 'e8fd9f0100', 0),
    ('bt43A526', 0x43A526, 'e8c19f0100', 0),
    ('bt43A5B0', 0x43A5B0, 'e8379f0100', 0),
    ('bt43A651', 0x43A651, 'e8969e0100', 0),
    ('bt43A6BD', 0x43A6BD, 'e85ed90100', 3),
    ('bt43A718', 0x43A718, 'e84bea0100', 4),
    ('bt43A768', 0x43A768, 'e87f9d0100', 0),
    ('bt43ABE7', 0x43ABE7, 'e838a10100', 1),
    ('bt43AC14', 0x43AC14, 'e807d40100', 3),
    ('bt43AC58', 0x43AC58, 'e8c7a00100', 1),
    ('bt43AC88', 0x43AC88, 'e893d30100', 3),
    ('bt43ACCA', 0x43ACCA, 'e855a00100', 1),
    ('bt43ACFB', 0x43ACFB, 'e820d30100', 3),
    ('bt43AD41', 0x43AD41, 'e8de9f0100', 1),
    ('bt43AD71', 0x43AD71, 'e8aad20100', 3),
    ('bt43AFBF', 0x43AFBF, 'e8609d0100', 1),
    ('bt43AFEC', 0x43AFEC, 'e82fd00100', 3),
    ('bt43B032', 0x43B032, 'e8ed9c0100', 1),
    ('bt43B063', 0x43B063, 'e8b8cf0100', 3),
    ('bt43B0A8', 0x43B0A8, 'e8779c0100', 1),
    ('bt43B0D8', 0x43B0D8, 'e843cf0100', 3),
    ('bt43B11E', 0x43B11E, 'e8019c0100', 1),
    ('bt43B14E', 0x43B14E, 'e8cdce0100', 3),
    ('bt43B3AC', 0x43B3AC, 'e83b910100', 128),
    ('bt43B3E6', 0x43B3E6, 'e801910100', 128),
    ('bt43B436', 0x43B436, 'e8cdd80100', 133),
    ('bt43B46D', 0x43B46D, 'e896d80100', 133),
    ('bt43B5B5', 0x43B5B5, 'e84ed70100', 133),
    ('bt43B6D4', 0x43B6D4, 'e8138e0100', 128),
    ('bt43BDE9', 0x43BDE9, 'e8fe860100', 128),
    ('bt43C14D', 0x43C14D, 'e8d28b0100', 1),
    ('bt43C176', 0x43C176, 'e8a5be0100', 3),
    ('bt43C1B8', 0x43C1B8, 'e8678b0100', 1),
    ('bt43C1E4', 0x43C1E4, 'e837be0100', 3),
    ('bt43C4FF', 0x43C4FF, 'e8e87f0100', 0),
    ('bt43C57B', 0x43C57B, 'e8a0ba0100', 3),
    ('bt43C5C2', 0x43C5C2, 'e8a1cb0100', 4),
    ('bt43C5F6', 0x43C5F6, 'e8f17e0100', 0),
    ('bt43C65C', 0x43C65C, 'e8bfb90100', 3),
    ('bt43C699', 0x43C699, 'e8caca0100', 4),
    ('bt43C6E1', 0x43C6E1, 'e83e860100', 1),
    ('bt43E10D', 0x43E10D, 'e8da630100', 0),
    ('bt43E155', 0x43E155, 'e892630100', 0),
    ('bt43E19C', 0x43E19C, 'e84b630100', 0),
    ('bt43E1E3', 0x43E1E3, 'e804630100', 0),
    ('bt43E22A', 0x43E22A, 'e8bd620100', 0),
    ('bt43E2FE', 0x43E2FE, 'e81d9d0100', 3),
    ('bt43E362', 0x43E362, 'e801ae0100', 4),
    ('bt43E39D', 0x43E39D, 'e84a610100', 0),
    ('bt43E429', 0x43E429, 'e8f29b0100', 3),
    ('bt43E484', 0x43E484, 'e8dfac0100', 4),
    ('bt43E4D4', 0x43E4D4, 'e813600100', 0),
    ('bt443B49', 0x443B49, 'e89e090100', 0),
    ('bt443BD9', 0x443BD9, 'e842440100', 3),
    ('bt443D4B', 0x443D4B, 'e89c070100', 0),
    ('bt443D7C', 0x443D7C, 'e8a30f0100', 1),
    ('bt443DAF', 0x443DAF, 'e81c1c0100', 2),
    ('bt443DD6', 0x443DD6, 'e845420100', 3),
    ('bt443DF9', 0x443DF9, 'e86a530100', 4),
    ('bt443E1C', 0x443E1C, 'e8e74e0100', 5),
    ('bt443EFF', 0x443EFF, 'e864520100', 4),
    ('bt443F33', 0x443F33, 'e8b4050100', 0),
    ('bt443FDF', 0x443FDF, 'e884510100', 4),
    ('bt444012', 0x444012, 'e80d0d0100', 1),
    ('bt444061', 0x444061, 'e8be0c0100', 1),
    ('bt4440B3', 0x4440B3, 'e818190100', 2),
    ('bt4440F5', 0x4440F5, 'e86e500100', 4),
    ('bt444129', 0x444129, 'e8be030100', 0),
    ('bt444182', 0x444182, 'e8e14f0100', 4),
    ('bt4441B5', 0x4441B5, 'e832030100', 0),
    ('bt444352', 0x444352, 'e895010100', 0),
    ('bt444383', 0x444383, 'e89c090100', 1),
    ('bt4443B6', 0x4443B6, 'e815160100', 2),
    ('bt4443DD', 0x4443DD, 'e83e3c0100', 3),
    ('bt444400', 0x444400, 'e8634d0100', 4),
    ('bt444423', 0x444423, 'e8e0480100', 5),
    ('bt444555', 0x444555, 'e892ff0000', 0),
    ('bt444586', 0x444586, 'e899070100', 1),
    ('bt4445B8', 0x4445B8, 'e813140100', 2),
    ('bt4445DF', 0x4445DF, 'e83c3a0100', 3),
    ('bt444602', 0x444602, 'e8614b0100', 4),
    ('bt444625', 0x444625, 'e8de460100', 5),
    ('bt44474A', 0x44474A, 'e89dfd0000', 0),
    ('bt44477A', 0x44477A, 'e8a5050100', 1),
    ('bt4447AD', 0x4447AD, 'e81e120100', 2),
    ('bt4447D4', 0x4447D4, 'e847380100', 3),
    ('bt4447F7', 0x4447F7, 'e86c490100', 4),
    ('bt44481A', 0x44481A, 'e8e9440100', 5),
    ('bt444E4D', 0x444E4D, 'e8ce310100', 3),
    ('bt444EAE', 0x444EAE, 'e871fe0000', 1),
    ('bt444F1F', 0x444F1F, 'e8fc300100', 3),
    ('bt444F6D', 0x444F6D, 'e87af50000', 0),
    ('bt44571B', 0x44571B, 'e800290100', 3),
    ('bt445781', 0x445781, 'e89ef50000', 1),
    ('bt4457F7', 0x4457F7, 'e824280100', 3),
    ('bt445849', 0x445849, 'e89eec0000', 0),
]

_SPRITE_HOOKS = _ENTITY_HOOKS + _BATTLE_HOOKS

# ── UI/小游戏 RLE 调用点 (游戏态 856 步长下, 640 平面 RLE 原语必然错位) ──
# 对话气泡 (40A518/40A9BC: 瓷砖 454D24=mode1, 尾巴 4544EC=mode0) 与
# 7 个小游戏 (全部 4544EC=mode0: 贴片/按钮/动画帧)。页面态函数 (41xxxx/
# 42131C/4241B0/424A2C/426164/42539C) 在 640 步长下 RLE 本就正确, 不钩。
# 战斗段 (43339C..4458B0) 已在 _BATTLE_HOOKS。
_UI_HOOKS = [
    ('ui40A65F', 0x40A65F, 'e8c0a60400', 1),
    ('ui40A707', 0x40A707, 'e818a60400', 1),
    ('ui40A780', 0x40A780, 'e89fa50400', 1),
    ('ui40A7C0', 0x40A7C0, 'e85fa50400', 1),
    ('ui40A7FD', 0x40A7FD, 'e822a50400', 1),
    ('ui40A833', 0x40A833, 'e8eca40400', 1),
    ('ui40A86C', 0x40A86C, 'e8b3a40400', 1),
    ('ui40A8AD', 0x40A8AD, 'e872a40400', 1),
    ('ui40A8E5', 0x40A8E5, 'e8029c0400', 0),
    ('ui40AB03', 0x40AB03, 'e81ca20400', 1),
    ('ui40ABAB', 0x40ABAB, 'e874a10400', 1),
    ('ui40AC24', 0x40AC24, 'e8fba00400', 1),
    ('ui40AC64', 0x40AC64, 'e8bba00400', 1),
    ('ui40ACA1', 0x40ACA1, 'e87ea00400', 1),
    ('ui40ACD7', 0x40ACD7, 'e848a00400', 1),
    ('ui40AD10', 0x40AD10, 'e80fa00400', 1),
    ('ui40AD51', 0x40AD51, 'e8ce9f0400', 1),
    ('ui40AD89', 0x40AD89, 'e85e970400', 0),
    ('ui429361', 0x429361, 'e886b10200', 128),
    ('ui4293C6', 0x4293C6, 'e821b10200', 128),
    ('ui429621', 0x429621, 'e8c6ae0200', 128),
    ('ui4296BE', 0x4296BE, 'e829ae0200', 128),
    ('ui429FD7', 0x429FD7, 'e810a50200', 128),
    ('ui429FFC', 0x429FFC, 'e8eba40200', 128),
    ('ui42A022', 0x42A022, 'e8c5a40200', 128),
    ('ui42A0EC', 0x42A0EC, 'e8fba30200', 128),
    ('ui42A161', 0x42A161, 'e886a30200', 128),
    ('ui42A2B0', 0x42A2B0, 'e837a20200', 128),
    ('ui42A2D3', 0x42A2D3, 'e814a20200', 128),
    ('ui42A2F5', 0x42A2F5, 'e8f2a10200', 128),
    ('ui42A628', 0x42A628, 'e8bf9e0200', 128),
    ('ui42A662', 0x42A662, 'e8859e0200', 128),
    ('ui42B167', 0x42B167, 'e880930200', 128),
    ('ui42B3E5', 0x42B3E5, 'e802910200', 128),
    ('ui42B421', 0x42B421, 'e8c6900200', 128),
    ('ui42D910', 0x42D910, 'e8d76b0200', 128),
    ('ui42DA32', 0x42DA32, 'e8b56a0200', 128),
    ('ui42E0A5', 0x42E0A5, 'e842640200', 128),
    ('ui42E18C', 0x42E18C, 'e85b630200', 128),
    ('ui42E78E', 0x42E78E, 'e8595d0200', 128),
    ('ui42E88C', 0x42E88C, 'e85b5c0200', 128),
    ('ui42F081', 0x42F081, 'e866540200', 128),
    ('ui42F188', 0x42F188, 'e85f530200', 128),
]

_SPRITE_HOOKS = _ENTITY_HOOKS + _BATTLE_HOOKS + _UI_HOOKS

_SPRITE_BLOB, _SPRITE_SUB = build_block(_SPRITE_HOOKS, entity_only=True,
                                        pop_ret=False)


# ── 布局与入口 ─────────────────────────────────────────────────────────
_BLOCKS = [
    ('init_stride', build_stride_init),
    ('settle_shift', build_settle_shift),
    ('map_camera', build_map_camera),
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
    ('fade_count', build_fade_count),
]
if _SPRITE_BLOB:
    _BLOCKS.append(('sprite_hooks', lambda: _SPRITE_BLOB))
_BLOCKS += [(name, (lambda f: (lambda: build_page_wrapper(f)))(fn))
     for name, fn in PAGE_FUNCS.items()]
_MG_BLOB = build_gxp_blt_left()          # 小游戏背景 Blt 左对齐+右带清黑
_BLOCKS.append(('mg_blt_left', lambda: _MG_BLOB))
_MAP_BLOB = build_map_bg_blt()           # 地图/战场背景 Blt 视口钳制 (窄地图)
_BLOCKS.append(('map_bg_blt', lambda: _MAP_BLOB))
_MGT_BLOB = build_mg_text_shift()        # 小游戏文字位移 wrapper (+108)
_BLOCKS.append(('mg_text_shift', lambda: _MGT_BLOB))
_TSR_BLOB = build_text_shift_a2(0x44E8E0)  # 结算页右对齐数字 X(a2)+108
_BLOCKS.append(('text_shift_ralign', lambda: _TSR_BLOB))
_TSW_BLOB = build_text_shift_a2(0x44E8A8)  # 结算页页码 X(a2)+108
_BLOCKS.append(('text_shift_wrap', lambda: _TSW_BLOB))
_CAM_BLOB = build_camrect_clamp()        # 相机 SetRect 视口钳制 (窄地图一致性)
_BLOCKS.append(('camrect_clamp', lambda: _CAM_BLOB))


# 诊断: 给关键 cave 块加调用计数 (定位菜单花屏时哪条路径在跑; 定位后移除)
_BLOCK_DBG = {
    'cursor_scratch': 0x80, 'grab_copy': 0x84, 'push_copy': 0x88,
    'gxp_upload': 0x8C, 'gxp_blt_fix': 0x90,
    'wrap_page_42131C': 0x94, 'wrap_page_4240B8': 0x98,
    'wrap_page_426164': 0x9C, 'wrap_page_42539C': 0xA0,
}


def _block_bytes(name: str, builder) -> bytes:
    blk = builder()
    if SPR_DEBUG and name in _BLOCK_DBG:
        blk = b'\xFF\x05' + _dbg(_BLOCK_DBG[name]) + blk   # inc dword [DBG+off]
    return blk


def cave_entries() -> dict:
    entries = {}
    off = 0
    for name, builder in _BLOCKS:
        entries[name] = off
        if name == 'sprite_hooks':
            for k, v in _SPRITE_SUB.items():
                entries[k] = off + v
        off += len(_block_bytes(name, builder))
    return entries


def build_cave_block() -> bytes:
    block = bytearray()
    for name, builder in _BLOCKS:
        block += _block_bytes(name, builder)
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
