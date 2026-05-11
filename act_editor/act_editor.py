#!/usr/bin/env python3
"""
TKAct.dat 多图层 2D 精灵动画编辑器 v2.4.4
=============================================================
修订依据:
  - v2.0/v2.1: 逆向工作区/TKS_AI分析act_editor记录.md
  - v2.2    : 逆向工作区/TKS_AI修正TKAct.dat实际JVG绑定.md
  - v2.3    : 尾部 64B 逆向确认为"音效触发表"
              (sub_4434BC L111-119 预加载 + L627-636 触发)
  - v2.4    : layer_type 语义精细化 + 预览图像混合模式生效
              (sub_4434BC L305/L414/L460/L518 四段位置分流)
  - v2.4.1  : 修复预览 sprite 周围显示黑色底色的问题
              (Windows Tk Canvas 对 RGBA PhotoImage 的 alpha 合成
               在多 sprite 叠加场景下不稳定, 改由 PIL 自合成后
               一次性以 RGB 贴图)
  - v2.4.2  : [已被 v2.4.3 覆写] 错误地将 mode=2 标注为 50% 半透.
  - v2.4.3  : mode=2 是加法饱和混合 (additive), 非 alpha 半透.
              查表 word_A3AD30[i+j]=min(i+j,31) (sub_453554 L43-52)
              param=0/>31 → full additive; 0<p<=31 → scaled additive.
  - v2.4.4  : ★ mode=3/4 修正 (之前实现完全错误, 依据 sub_45871C / sub_459854):
              mode=3 (sub_45871C L118-134): per-channel 减法钳 0
                    dst.RGB = max(dst - src, 0)          # 非 RGB/3 阴影!
                    黑色 src 不改变 dst, 亮色 src 压暗 dst → "挖洞变暗".
              mode=4 (sub_459854 L109-124): 按 src 亮度 alpha-blend
                    α = word_A3AEB0[src] & 0x1F          # NTSC 灰度 5-bit
                    α==0 跳过; α>28 覆盖;
                    其他 dst = dst*(32-α)/32 + src*α/32  # 非 RGB 取反!
                    亮色强覆盖、暗色弱显现 → 烟雾/光雾/软粒子风格.
              PIL 实现: ImageChops.subtract / Image.composite + luma mask.

  v2.4 新增:
    · layer_type 语义按实测重新标注 (与 sub_4434BC 反编译完全一致):
        t=1  角色攻击动作    (Aa.jvg, 攻击者位置, L305 <3 分支)
        t=2  技能攻击特效    (Af.jvg, 攻击者位置, L305 <3 分支)
        t=3  受击特效        (Af.jvg, 受击方位置, L414 ==3 延迟段)
        t=4  命中锚点坐标    (sub_42F9C8 计算屏幕位置, 不渲染)
        t=5  全屏特效        (屏幕中心 320,300, L518 ==5 分支)
    · 预览引入 6 种图像混合模式 (对应 sub_4434BC L320-339 switch):
        0 正常      sub_4544EC  直接 blit
        1 闪烁/染色 sub_454D24  按 blend_param 偏色 (param 0 或 >31 不变)
        2 加法/发光 sub_4559D0  additive 饱和混合:
                                  = 0/>31    dst = min(dst+src, 31/63)
                                  0<p<=31    dst = min(dst+src*p/32, 31/63)
        3 减法/压暗 sub_458020→45871C: dst = max(dst-src, 0) 每通道
        4 亮度融合  sub_459168→459854: α=Y(src), dst = dst*(32-α)/32+src*α/32
        5 水平翻转  sub_458D08  X 轴镜像

  v2.0 修正要点:
    1. 前 32 字节 = 4 方向 × 8 字节 的图层绘制顺序 (z-order)
    2. 8 个槽位即 8 个图层 (layer), 按语义分组编辑
    3. 字段按语义命名并按功能分组 (来源/帧范围/时序/渲染/位移/…)
    4. 尾部 64B 按 16 对 (value, count) 显示
    5. 预览节拍遵循 tick_interval / start_delay / [first,last] 语义

  v2.2 关键修正 (sub_4434BC + sub_42FEE0 反编译证据):
    · layer_type == 1 → Aa.jvg  (dword_951924, 主角动作库)
    · layer_type != 1 → Af.jvg  (dword_951930, 特效/物件库)
    · Cha.jvg 走 sub_458020(dword_755AF0, ...) 直接绘制角色基础行走图,
      不经 ACT 图层系统, 故不再作为编辑器资源加载.
    · Ani.jvg 未被 sub_4434BC 引用, 移出 ACT 编辑器视野.

  v2.3 新增 (sub_451780 + sub_451C38 反编译证据):
    · 尾部 16 对 = 音效触发表: (sound_id, trigger_tick)
      · sub_4434BC L111-119  执行前预加载 16 个音效  (sub_451780(1))
      · sub_4434BC L627-636  每 tick 检查 v5[1] == word_9D03A0 → 播放
    · 音效实际来源 = SWS.GRP (sub_451780 L48-61):
      · A2C22C == 1 → sub_4B22A8(..., *(+16)+4*v19, 0)  从 GRP 按 sid 取
      · A2C22C == 0 → sub_4B2ECC(..., "sound\\%04d.wav", v19)  文件 fallback
      · 实测 Sound/ 目录不完整 (仅 29 文件, 但 sid 最高达 95+),
        必须从 SWS.GRP 读取; Sound/ 仅作历史兜底.
    · SWS.GRP 结构 (SWS.IDX 索引, 每段 = RIFF WAV):
      · IDX = 连续 <I 偏移表, 末尾 = 文件大小
      · 506 段 (SWS.IDX 507 偏移), 每段可直接作为 WAV 字节流播放
    · 预览画面:
      · 不再每帧重算 bbox, 改为条目级固定 bbox (切条目时算一次)
      · 原点 (0,0) 固定在画布中央偏下 (模拟角色脚底锚点)
      · 切换方向/播放不会造成画面跳动
    · 预览 tick 推进时自动按 trigger_tick 触发 SWS.GRP 音效播放

文件结构 (784 字节/条, 共 650 条 = 509,600 字节):
  [0-31]    方向表: 4 方向 × 8 字节, 每字节为 1-based 图层号 (0=空)
  [32-79]   条目级参数区 (24 int16, 多数预留/未知)
  [80-719]  图层 × 8 (各 80 字节 = 40 int16)
  [720-783] 尾部 = 音效触发表 16 对 × (sound_id, trigger_tick) × int16

逆向关键函数:
  sub_411624: sub_452544(aTkactDat, &unk_9539CA, 509600)  初始化载入
  sub_452544: 原始 I/O 读取 (非 LZSS)
  sub_4434BC: 动画运行时处理 (本编辑器语义的主要证据来源)
  sub_45408C: 帧基址计算
  sub_45410C: param_key 查表
  sub_451780: 加载 sound\\%04d.wav → DirectSound 缓冲 (a2 = sound_id)
  sub_451C38: 播放已加载音效缓冲 (eax = 资源表, edx = sound_id)
"""

class LRUCache:
    """固定容量的 LRU 缓存, 兼容 dict 的 get/set/clear 接口."""
    def __init__(self, capacity=500):
        self.cache = collections.OrderedDict()
        self.capacity = capacity

    def get(self, key):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def __setitem__(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def clear(self):
        self.cache.clear()


import os, sys, struct, copy, time, collections, tkinter as tk
from tkinter import ttk, messagebox, filedialog

HAS_PIL = False
try:
    from PIL import Image, ImageTk, ImageChops
    HAS_PIL = True
except ImportError:
    pass


# ============================================================
# 音效播放 (Windows MCI + SWS.GRP 资源包)
#   sub_451780 关键逻辑 (L48-61):
#     if dword_A2C22C == 1:
#         sub_4B22A8(*(+28), *(+16)+4*v19, 0)   # 从 GRP 资源包按 sid 取
#     elif dword_A2C22C == 0:
#         sub_4B2ECC(..., "sound\\%04d.wav", v19)  # 文件路径 fallback
#   说明: 实际游戏运行时走 A2C22C=1 分支, 从 SWS.GRP 读 WAV;
#         Sound/ 目录仅作历史 fallback, 不完整 (只有 29 个音效,
#         而 TKAct 里 sid 最高出现 95+, 必须走 SWS.GRP).
#   SWS.GRP 结构 (grp_editor.py 验证):
#     - SWS.IDX = 连续 <I 偏移表, 最后一个 = 文件大小
#     - num_sections = len(idx) - 1
#     - 每 section 直接就是一个 RIFF WAV 字节流
# ============================================================
_mci_alias_counter = [0]
_sws_tempfiles = []  # 进程退出时清理


class _SWSGrp:
    """SWS.GRP 音效资源包最小读取器 (按需流式读取, 不一次性载入).
    get_wav(sid) → 返回原始 WAV 字节或 None.
    extract_to_temp(sid) → 写到临时 .wav 文件供 MCI 播放, 返回路径或 None.
    """

    def __init__(self, grp_path, idx_path):
        self.grp_path = grp_path
        self.idx_path = idx_path
        self.offsets = []
        self._wav_cache = {}
        self._temp_cache = {}

    def load_index(self):
        with open(self.idx_path, 'rb') as f:
            data = f.read()
        if len(data) < 8 or len(data) % 4:
            return 0
        self.offsets = [struct.unpack_from('<I', data, i)[0]
                        for i in range(0, len(data), 4)]
        # 合法性校验: 末尾必须 = grp 文件大小
        try:
            grp_sz = os.path.getsize(self.grp_path)
        except OSError:
            return 0
        if not self.offsets or self.offsets[-1] != grp_sz:
            self.offsets = []
            return 0
        return self.section_count

    @property
    def section_count(self):
        return max(0, len(self.offsets) - 1)

    def get_wav(self, sid):
        if sid < 0 or sid >= self.section_count:
            return None
        cached = self._wav_cache.get(sid)
        if cached is not None:
            return cached
        start = self.offsets[sid]
        end = self.offsets[sid + 1]
        if end <= start:
            return None
        try:
            with open(self.grp_path, 'rb') as f:
                f.seek(start)
                data = f.read(end - start)
        except OSError:
            return None
        # 校验 RIFF/WAVE 头
        if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
            return None
        # 最多缓存 32 条 (防内存膨胀)
        if len(self._wav_cache) < 32:
            self._wav_cache[sid] = data
        return data

    def extract_to_temp(self, sid):
        """把 sid 对应的 WAV 写到临时文件, 返回路径 (MCI 需要文件路径)."""
        if sid in self._temp_cache and os.path.exists(self._temp_cache[sid]):
            return self._temp_cache[sid]
        data = self.get_wav(sid)
        if not data:
            return None
        import tempfile
        fd, path = tempfile.mkstemp(prefix=f'tkact_sws_{sid:04d}_',
                                    suffix='.wav')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
        except OSError:
            return None
        self._temp_cache[sid] = path
        _sws_tempfiles.append(path)
        return path

    def wav_info(self, sid):
        """返回简要信息 (ch, sr, bits, duration_s) 或 None."""
        data = self.get_wav(sid)
        if not data:
            return None
        try:
            import io as _io
            import wave as _wave
            with _wave.open(_io.BytesIO(data), 'rb') as wf:
                nf = wf.getnframes()
                sr = wf.getframerate()
                return (wf.getnchannels(), sr, wf.getsampwidth() * 8,
                        nf / sr if sr > 0 else 0.0)
        except Exception:
            return None


def _mci_send(cmd):
    """winmm.dll mciSendStringW 包装; 失败返回 (errno, err_msg)"""
    if sys.platform != 'win32':
        return (-1, 'not-windows')
    try:
        import ctypes
        winmm = ctypes.windll.winmm
        rc = winmm.mciSendStringW(ctypes.c_wchar_p(cmd), None, 0, None)
        if rc != 0:
            buf = ctypes.create_unicode_buffer(256)
            winmm.mciGetErrorStringW(rc, buf, 256)
            return (rc, buf.value)
        return (0, '')
    except Exception as e:
        return (-1, str(e))


def _mci_play_async(path):
    """异步播放 wav 文件, 返回 alias; 失败返回 None"""
    if not path or not os.path.exists(path):
        return None
    _mci_alias_counter[0] += 1
    alias = f"tkact_snd_{_mci_alias_counter[0]}"
    _mci_send(f'close {alias}')
    rc, msg = _mci_send(f'open "{path}" type waveaudio alias {alias}')
    if rc != 0:
        rc, msg = _mci_send(f'open "{path}" alias {alias}')
        if rc != 0:
            return None
    rc, msg = _mci_send(f'play {alias}')
    if rc != 0:
        _mci_send(f'close {alias}')
        return None
    return alias


def _mci_close(alias):
    if alias:
        _mci_send(f'stop {alias}')
        _mci_send(f'close {alias}')


def _cleanup_sws_tempfiles():
    for p in list(_sws_tempfiles):
        try:
            if os.path.exists(p):
                os.unlink(p)
        except OSError:
            pass
    _sws_tempfiles.clear()


# ------------------------------------------------------------
# JVG 按需加载器 (只解码当前条目引用的块, 不加载全量 40MB+347MB)
# ------------------------------------------------------------

class _LazyJvgReader:
    """JVG 文件按需读取: 首次扫描仅解析头部 (块偏移+帧数), 不解码像素.
    get_block(idx) 时才 RLE 解码该块的帧, 并缓存."""

    def __init__(self, path):
        self.path = path
        self._offsets = []    # 每块的起始偏移
        self._sub_counts = [] # 每块的帧数
        self._cache = {}      # {idx: JVMBlock}
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except Exception:
            self._valid = False
            return
        if len(data) < 32 or data[0:4] != b'@JVG':
            self._valid = False
            return
        self._data = data
        self._valid = True
        bc = struct.unpack('<I', data[8:12])[0]
        off = 32
        for _ in range(bc):
            if off + 32 > len(data) or data[off:off+4] != b'@JVM':
                break
            sc = struct.unpack('<I', data[off+4:off+8])[0]
            ds = struct.unpack('<I', data[off+12:off+16])[0]
            self._sub_counts.append(sc)
            self._offsets.append(off)
            off += 32 + (sc + 1) * 4 + 512 + ds

    @property
    def valid(self):
        return self._valid

    @property
    def block_count(self):
        return len(self._offsets)

    @property
    def frame_counts(self):
        return list(self._sub_counts)

    def get_block(self, idx):
        if idx < 0 or idx >= len(self._offsets):
            return None
        if idx in self._cache:
            return self._cache[idx]
        jvg_mod = _get_jvg_loader()
        if not jvg_mod:
            return None
        off = self._offsets[idx]
        end = (self._offsets[idx+1] if idx+1 < len(self._offsets)
               else len(self._data))
        raw = self._data[off:end]
        sc = self._sub_counts[idx]
        # 解析 JVM 块 (直接复制 jvg_editor 的 load_jvg 内联逻辑)
        s1 = 32
        co = [struct.unpack('<I', raw[s1+j*4:s1+j*4+4])[0] for j in range(sc+1)]
        po = s1 + (sc+1)*4
        blk = jvg_mod.JVMBlock(f"blk_{idx:03d}")
        for j in range(256):
            blk.palette.entries[j] = struct.unpack('<H', raw[po+j*2:po+j*2+2])[0]
        dr = po + 512
        for si in range(sc):
            mo = dr + co[si]
            ws = struct.unpack('<8H', raw[mo:mo+16])
            f = jvg_mod.JVGFrame()
            f.x_max = ws[0]; f.y_max = ws[1]
            f.width = ws[2]; f.height = ws[3]
            f.row_count = ws[7]
            eo = mo + 16
            f.encoded_data = raw[eo:eo+co[si+1]-co[si]-16]
            if f.width > 0 and f.height > 0:
                f.pixels, f.alpha = jvg_mod._decode_rle(
                    f.encoded_data, f.width, f.height)
            blk.frames.append(f)
        self._cache[idx] = blk
        return blk


_jvg_loader = None


def _get_jvg_loader():
    global _jvg_loader
    if _jvg_loader is None:
        jvg_dir = os.path.join(os.path.dirname(__file__), '..', 'jvg_editor')
        if jvg_dir not in sys.path:
            sys.path.insert(0, jvg_dir)
        try:
            import jvg_editor as _jvg_editor
            _jvg_loader = _jvg_editor
        except ImportError:
            _jvg_loader = False
    return _jvg_loader if _jvg_loader is not False else None


# ============================================================
# 常量
# ============================================================

ACT_ENTRY_SIZE = 784
ACT_ENTRY_COUNT = 650
ACT_LAYER_SIZE = 80            # 每图层 80 字节 = 40 int16
ACT_MAX_LAYER = 8              # 方向表字节值域 1..8
PREVIEW_ENEMY_X = 160          # 预览: 假想敌 X 偏移 (t=3 受击图层渲染位置)
ACT_HEADER_SIZE = 80
ACT_PARAM_OFFSET = 32          # 条目级参数区起点
ACT_TAIL_OFFSET = 720
ACT_TAIL_SIZE = 64
ACT_DECOMPRESSED = 509600

# 方向顺序 — sub_4434BC 以字节下标 v33 ∈ [0,3] 索引方向组;
# 实测 entry #0 的 4 组 z-order 呈 "前/后朝向反转" 模式,
# 下/右使用 [3,4,1,2], 上/左使用 [1,2,3,4], 故与常见 RPG 四方向一致:
DIRECTION_LABELS = ["方向0 (右上)", "方向1 (右下)", "方向2 (左下)", "方向3 (左上)"]
DIRECTION_SHORT = ["右上", "右下", "左下", "左上"]

# 图层类型 (sub_4434BC: *(_WORD*)dword_9D0690)
#   引擎按 "==1 vs !=1" 切换贴图源 (sub_42FEE0 验证):
#     type == 1 : v32 = dword_951924  →  Aa.jvg  (主角动作库)
#     type != 1 : v32 = dword_951930  →  Af.jvg  (特效/物件库)
#   渲染位置分流 (按 layer_type 4 段互斥):
#     type <  3 : L305 主段渲染, 坐标 = 攻击者位置 + 图层 offset
#                 → type=1 角色攻击动作; type=2 技能攻击特效 (从角色发出)
#     type == 3 : L414 延迟段, 遍历地图格子, 仅在命中目标格再绘制
#                 → 受击特效 (以受击方位置为锚点)
#     type == 4 : L149 v29=1 触发 sub_42F9C8 计算屏幕锚点; L460 在锚点位置绘制
#                 → "命中闪光" 坐标同步锚, 真实绘制另走 sub_42F9C8 的屏幕映射
#     type == 5 : L156 v28=1; L518 固定屏幕中心 (320, 300) 绘制
#                 → 全屏特效 (如 boss 大招闪白、屏幕变色等)
# ⚠ 历史纠错: v2.1 曾把贴图源误标为 Cha.jvg / Ani.jvg;
#   实测 sub_42FEE0 显示 dword_951924 = Aa.jvg, dword_951930 = Af.jvg.
#   Cha.jvg 由 sub_458020(dword_755AF0, ...) 直接绘制, 不经 ACT 图层.
LAYER_TYPE_LABELS = {
    0: "0 空",
    1: "1 角色攻击动作 (Aa.jvg, 攻击者位置)",
    2: "2 技能攻击特效 (Af.jvg, 攻击者位置)",
    3: "3 受击特效     (Af.jvg, 受击方位置)",
    4: "4 命中锚点坐标 (sub_42F9C8, 不渲染)",
    5: "5 全屏特效     (屏幕中心 320,300)",
}

# 混合模式 (sub_4434BC: switch(+22) → 6 个渲染函数)
#   每个函数的近似语义 (逆向结论, 预览按此模拟):
#     0 sub_4544EC  直接 blit, 透明色 key (alpha=0 跳过), 无任何像素变换
#     1 sub_454D24  带参数 a6=+24 的染色 blit; 0 或 >31 时视觉无变化
#     2 sub_4559D0  加法饱和混合 (additive); 查表 word_A3AD30[i+j]=min(i+j,31)
#                  (sub_453554 L43-52 初始化, 非 (a+b)/2 半透!)
#                    · a6=0        → sub_455B98/_456150   full additive: dst=min(dst+src,31/63)
#                    · 0<a6<=31    → sub_4573A0/_4579D0   scaled additive: dst=min(dst+src*a6/32,31)
#                    · a6>31       → 递归 (0,0) 退化 full additive (实测 48 次 a6=80)
#     3 sub_458020  减法饱和混合 (a6=a7=0 走 sub_45871C L118-134):
#                    dst.RGB = max(dst - src, 0) per-channel (非 RGB/3!)
#     4 sub_459168  按 src 亮度的 alpha blend (走 sub_459854 L109-124):
#                    α = Y(src)                      # NTSC 灰度 5-bit
#                    α==0 跳过; α>28 覆盖;
#                    其他 dst = dst*(32-α)/32 + src*α/32  (非 RGB 取反!)
#     5 sub_458D08  水平翻转 (证据: L111/L136 目标指针 dword_A5AEB4 -=2 逆写)
BLEND_MODE_LABELS = {
    0: "0 正常",
    1: "1 闪烁/染色",
    2: "2 加法/发光",
    3: "3 减法/压暗",
    4: "4 亮度融合",
    5: "5 水平翻转",
}

# 方向感知 (sub_4434BC L308: if(+4==4) v34=v33 else v34=0)
DIRECTION_MODE_LABELS = {
    0: "0 固定方向0",
    4: "4 随朝向变",
}

# 循环行为 (sub_4434BC L593-610: 当前帧到达 last_frame 后, 依 +38 处理)
LOOP_BEHAVIOR_LABELS = {
    -1: "-1 (0xFFFF) 循环到起始帧",
    -2: "-2 (0xFFFE) 停止本图层",
}

# 移动模式 (sub_4434BC +50 == 1/2)
MOVE_MODE_LABELS = {
    0: "0 无",
    1: "1 跟随移动",
    2: "2 四方来回",
}

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_B = ('Microsoft YaHei UI', 9, 'bold')
W_INPUT = 10
W_INPUT_S = 6

# ============================================================
# JVG 轻量帧数探针  (不解码像素, 仅读 @JVG header + 各 @JVM sub_count)
# ============================================================

# 常见 "总帧数 → (方向数, 每方向帧数)" 推断优先级表
# (基于 Aa.jvg/Af.jvg 实测分布: Aa 全是 4 的倍数; Af 多为单向)
_JVG_LAYOUT_HINTS = [
    (28, 4, 7),   # ★ Aa 最常见: 4 向 × 7 帧
    (32, 4, 8),   # Aa 次常见: 4 向 × 8 帧
    (36, 4, 9),   # Aa: 4 向 × 9 帧
    (48, 4, 12),  # Aa: 4 向 × 12 帧
    (40, 4, 10),  # Aa: 4 向 × 10 帧
    (44, 4, 11),  # Aa: 4 向 × 11 帧
    (24, 4, 6),   # Aa: 4 向 × 6 帧
    (20, 4, 5),   # Af/Aa: 4 向 × 5 帧
    (4,  4, 1),   # 4 向纯静态
]


def infer_jvg_layout(n_frames):
    """根据总帧数推断 (方向数, 每方向帧数, 是否确定模式)."""
    if n_frames <= 0:
        return (0, 0, False)
    for total, dirs, per in _JVG_LAYOUT_HINTS:
        if n_frames == total:
            return (dirs, per, True)
    for d in (4, 2, 1):
        if n_frames % d == 0:
            return (d, n_frames // d, False)
    return (1, n_frames, False)


# ============================================================
# Aa.jvg / Af.jvg 块结构约定 (实测分布, 非 sub_4434BC 自身规定)
# ============================================================
# Aa.jvg (dword_951924, 158 blocks, 40 MB):
#   主角/角色 "ACT 扩展动作库" —— 下蹲/出剑/抬手/治疗/倒地/
#   起身/蓄力/挥拳 等相对于 Cha.jvg 基础行走的附加姿势.
#   帧数分布 (占比前几位):
#     ┌──────┬────────┬────────────────────────────┐
#     │ 总帧 │ 次数   │ 典型语义 (4 方向)          │
#     │  28  │  25    │ 4 向 × 7 帧 ★              │
#     │  32  │  21    │ 4 向 × 8 帧                │
#     │  36  │  17    │ 4 向 × 9 帧                │
#     │  48  │  14    │ 4 向 × 12 帧               │
#     │  40  │  12    │ 4 向 × 10 帧               │
#     │  44  │   9    │ 4 向 × 11 帧               │
#     │  24  │   8    │ 4 向 × 6 帧                │
#     └──────┴────────┴────────────────────────────┘
#   所有 block 帧数均为 4 的倍数 → 主角动作均为 4 方向结构.
#
# Af.jvg (dword_951930, 367 blocks, 347 MB):
#   特效/物件/刀光/箭矢/爆点/飞行物 等通用动画池.
#   帧数分布 (前几位): 20/24/17/19/28/15/16/18/7 ... 
#   大量非 4 倍数块 → 多数特效/物件为单方向动画,
#   ACT 数据里对应 direction_mode == 0 (固定方向 0).
#
# ⚠ Cha.jvg (dword_755AF0, 178 blocks) 的 "block 0=阴影, block 1=72帧
#   主角行走, block 2..=28帧 NPC 行走" 约定属于"地图角色基础渲染"系统,
#   由 sub_458020 按角色 base block 直接绘制, 与 TKAct 图层系统无关.
#   (编辑器不加载 Cha/Ani, 它们不是 ACT 消费资源)
#
# ⚠ ACT 引擎 sub_4434BC 方向表循环步长是 8 字节/方向, 前 32 字节仅容
#   纳 4 方向的绘制顺序, 故 v33 ∈ {0,1,2,3}. 哪怕 Aa 某块帧数=72 (不存在)
#   或 Af 某块为 8 方向结构, ACT 也只能驱动前 4 方向.
#
# ACT 侧的"帧片段"由三个字段组合决定, 与 JVG 块真实帧数解耦:
#   dir_frame_offset  方向间帧步长   (该块每方向帧数, 典型 7/8/5/9/1)
#   first_frame       方向内起始帧   (通常=0)
#   last_frame        方向内终止帧   (通常=dfo-1)
#
# 帧片段读取示例 (dirmode=4 随朝向变):
#   dfo=7 first=0 last=6  ⇒ 4 向×7 帧 (28 帧 Aa 块全取)
#   dfo=8 first=0 last=7  ⇒ 4 向×8 帧 (32 帧 Aa 块全取)
#   dfo=9 first=0 last=8  ⇒ 4 向×9 帧 (36 帧 Aa 块全取)
#   dfo=1 first=0 last=0  ⇒ 4 向×1 帧 (4 帧纯静态块全取)
# ============================================================

# ============================================================
# 图层字段定义 — 按"语义分组"组织, 每字段 = (key, int16_idx, 标签, 宽度, 描述)
# ★ 标记表示 v1.0 中错标的字段已纠正
# ============================================================

# 单字段元组结构: (key, int16_idx, label, width, tooltip)
FIELD_GROUPS = [
    ("来源", [
        ("layer_type",       0,  "类型",       W_INPUT,
         "sub_4434BC: *(_WORD*)(+0)\n"
         "  ==1 → Aa.jvg (dword_951924, 主角动作库)\n"
         "  !=1 → Af.jvg (dword_951930, 特效/物件库)\n"
         "  渲染阶段: <3 主段 / ==3 延迟段 / ==4 锚点 / ==5 结束"),
        ("jvg_block_index",  1,  "JVG 块号",    W_INPUT,
         "sub_4434BC: *(_WORD*)(+2) → sub_45410C 查表\n"
         "Aa.jvg (158块) 主角动作库, 帧数多为 4 倍数:\n"
         "  28(4×7,★) 32(4×8) 36(4×9) 48(4×12) 40(4×10) 44(4×11) 24(4×6)\n"
         "Af.jvg (367块) 特效/物件库, 多为单向动画:\n"
         "  常见 20/24/17/19/28/15/16/18/7 帧 (大量非 4 倍数)"),
    ]),
    ("帧范围", [
        ("first_frame",      17, "起始帧",     W_INPUT,
         "sub_4434BC L595: *(_WORD*)(+34)  动画起始帧号\n"
         "★ 此为'方向内相对帧号', 引擎按 dir_frame_offset × direction 再叠加\n"
         "  标准行走约定: =0 (即该方向静止姿)"),
        ("last_frame",       18, "终止帧",     W_INPUT,
         "sub_4434BC L593: *(_WORD*)(+36)  到达即触发循环/停止\n"
         "★ 方向内相对帧号; 典型值:\n"
         "  =0  纯静止  =dfo-1  跑满该方向全部帧 (如 28帧Aa块时=6, 32帧=7)"),
        ("loop_behavior",    19, "循环行为",   W_INPUT,
         "sub_4434BC L603: *(_WORD*)(+38)  -1 循环/-2 停止/≥0 跳帧"),
    ]),
    ("时序 ★", [
        ("tick_interval",    21, "帧停留 tick ★", W_INPUT,
         "sub_4434BC L574: if(counter>=+42) 翻下一帧  ← 数据字段, 可编辑"),
        ("start_delay",      22, "启动延迟 ★",    W_INPUT,
         "sub_4434BC L248/L566: !*(+44) 才递增, --*(+44)  ← 数据字段, 可编辑"),
    ]),
    ("渲染", [
        ("blend_mode",       11, "混合模式",   W_INPUT,
         "sub_4434BC L320-339: switch(+22) → 6 种渲染"),
        ("blend_param",      12, "混合参数",   W_INPUT,
         "sub_4434BC: *(_WORD*)(+24)  颜色/alpha/随机种等"),
        ("blend_param_step", 13, "混合参数步进", W_INPUT,
         "sub_4434BC L613: *(+24) += *(+26)  每翻帧的累加量"),
    ]),
    ("位移 (方向 0~3)", [
        ("x_off_d0",         3,  "X₀", W_INPUT_S, "sub_4434BC: +6  方向0 的 X 偏移"),
        ("x_off_d1",         4,  "X₁", W_INPUT_S, "sub_4434BC: +8  方向1 的 X 偏移"),
        ("x_off_d2",         5,  "X₂", W_INPUT_S, "sub_4434BC: +10 方向2 的 X 偏移"),
        ("x_off_d3",         6,  "X₃", W_INPUT_S, "sub_4434BC: +12 方向3 的 X 偏移"),
        ("y_off_d0",         7,  "Y₀", W_INPUT_S, "sub_4434BC: +14 方向0 的 Y 偏移"),
        ("y_off_d1",         8,  "Y₁", W_INPUT_S, "sub_4434BC: +16 方向1 的 Y 偏移"),
        ("y_off_d2",         9,  "Y₂", W_INPUT_S, "sub_4434BC: +18 方向2 的 Y 偏移"),
        ("y_off_d3",         10, "Y₃", W_INPUT_S, "sub_4434BC: +20 方向3 的 Y 偏移"),
    ]),
    ("方向感知", [
        ("direction_mode",   2,  "方向模式",   W_INPUT,
         "sub_4434BC L308: if(+4==4) 随朝向变 else 固定方向0"),
        ("dir_frame_offset", 16, "方向帧偏移", W_INPUT,
         "sub_4434BC L309: v35 += +32 × v33 (方向模式=4 时按朝向偏移帧号)\n"
         "★ 等于'该方向帧段长度'(即每方向帧数); 常见值:\n"
         "  =7 (28帧Aa块, 4向×7)  =8 (32帧Aa块, 4向×8)\n"
         "  =9 (36帧Aa块, 4向×9)  =12 (48帧Aa块, 4向×12)\n"
         "  =1 (4帧纯静态块)       =0 (固定方向 0, 无朝向步进)"),
    ]),
    ("自动移动", [
        ("move_mode",        25, "移动模式",   W_INPUT,
         "sub_4434BC L577-591: +50 == 1 跟随 / == 2 四方往返"),
        ("step_value",       26, "步进值",     W_INPUT_S,
         "sub_4434BC: *(_WORD*)(+52)"),
        ("step_delta",       27, "步进增量",   W_INPUT_S,
         "sub_4434BC: *(_WORD*)(+54)"),
    ]),
    ("运行时 (只读, 文件=0)", [
        ("_rt_frame_base",   14, "帧基址",     W_INPUT_S,
         "sub_4434BC: +28 = sub_45408C(...)"),
        ("_rt_cur_frame",    15, "当前帧",     W_INPUT_S,
         "sub_4434BC: +30 = base+init"),
        ("_rt_20",           20, "RT20",       W_INPUT_S, "运行时"),
        ("_rt_counter",      23, "RT 计数",    W_INPUT_S,
         "sub_4434BC: *(+46)"),
        ("_rt_dir_sign",     24, "RT 方向符",  W_INPUT_S,
         "sub_4434BC: +48 ∈ {0,1,-1}"),
    ]),
    ("保留 / 未知", [
        (f"_res_{i}", i, f"[{i}]", W_INPUT_S, f"int16[{i}] 未在 sub_4434BC 中引用")
        for i in range(28, 40)
    ]),
]

# 平铺全部字段 (供加载/保存使用)
ALL_FIELDS = [f for _, grp in FIELD_GROUPS for f in grp]

# 运行时 / 保留字段 (UI 上以只读灰显呈现)
READONLY_KEYS = {f[0] for f in ALL_FIELDS
                 if f[0].startswith('_rt') or f[0].startswith('_res')}


# ============================================================
# 数据加载 / 保存
# ============================================================

def load_act(fp):
    """加载 TKAct.dat (原始文件, 非 LZSS)"""
    with open(fp, 'rb') as f:
        raw = f.read()
    if len(raw) != ACT_DECOMPRESSED:
        raise ValueError(
            f"文件大小 {len(raw)} 不等于预期 {ACT_DECOMPRESSED} (650×784)")
    entries = []
    for i in range(ACT_ENTRY_COUNT):
        off = i * ACT_ENTRY_SIZE
        data = raw[off:off + ACT_ENTRY_SIZE]

        # 方向表: 4 方向 × 8 字节
        dirs = []
        for d in range(4):
            dirs.append(list(data[d * 8: d * 8 + 8]))

        # 条目级参数区 int16[16..39] (bytes 32..79)
        param16 = list(struct.unpack_from('<24h', data, ACT_PARAM_OFFSET))

        # 8 个图层
        layers = []
        for s in range(1, ACT_MAX_LAYER + 1):
            lo = s * ACT_LAYER_SIZE
            layers.append(list(struct.unpack_from('<40h', data, lo)))

        # 尾部 32 int16 → 16 对 (value, count)
        tail = list(struct.unpack_from('<32h', data, ACT_TAIL_OFFSET))

        entries.append({
            'index':   i,
            'dirs':    dirs,
            'param16': param16,
            'layers':  layers,
            'tail':    tail,
        })
    return entries


def save_act(fp, entries):
    """保存 TKAct.dat (原始文件, 非 LZSS)"""
    buf = bytearray(ACT_ENTRY_COUNT * ACT_ENTRY_SIZE)
    for entry in entries:
        i = entry['index']
        off = i * ACT_ENTRY_SIZE

        # 方向表
        for d in range(4):
            b = entry['dirs'][d]
            buf[off + d * 8: off + d * 8 + 8] = bytes(
                v & 0xFF for v in b)

        # 条目级参数
        struct.pack_into('<24h', buf, off + ACT_PARAM_OFFSET,
                         *entry['param16'])

        # 图层
        for s in range(ACT_MAX_LAYER):
            lo = off + (s + 1) * ACT_LAYER_SIZE
            struct.pack_into('<40h', buf, lo, *entry['layers'][s])

        # 尾部
        struct.pack_into('<32h', buf, off + ACT_TAIL_OFFSET, *entry['tail'])

    if len(buf) != ACT_DECOMPRESSED:
        raise RuntimeError(f"回写缓冲区大小异常: {len(buf)}")

    with open(fp, 'wb') as f:
        f.write(buf)
    return True


def entry_is_empty(entry):
    for d in range(4):
        if any(entry['dirs'][d]):
            return False
    if any(entry['param16']):
        return False
    for s in range(ACT_MAX_LAYER):
        if any(v != 0 for v in entry['layers'][s]):
            return False
    if any(entry['tail']):
        return False
    return True


def entry_active_layers(entry):
    """返回 type ≠ 0 的图层号集合 (1-based)"""
    used = set()
    for s in range(ACT_MAX_LAYER):
        if entry['layers'][s][0] != 0:
            used.add(s + 1)
    return used


def entry_referenced_layers(entry):
    """返回方向表引用过的图层号集合 (1-based)"""
    used = set()
    for d in range(4):
        for v in entry['dirs'][d]:
            if v:
                used.add(v)
    return used


def entry_summary(entry):
    refd = entry_referenced_layers(entry)
    act = entry_active_layers(entry)
    shown = sorted(refd | act)
    if not shown:
        return "(空)"
    parts = []
    for s in shown[:6]:
        t = entry['layers'][s - 1][0] if 1 <= s <= ACT_MAX_LAYER else 0
        parts.append(f"#{s}({t})")
    if len(shown) > 6:
        parts.append("…")
    return " ".join(parts)


# ============================================================
# GUI
# ============================================================

class ActEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKAct.dat 多图层 2D 精灵动画编辑器 v2.2")
        ico = os.path.join(os.path.dirname(__file__), '..', 'kon_editor',
                           'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1320x860")
        self.root.minsize(1080, 680)
        self.root.state('zoomed')  # 默认全屏

        self.act_path = None
        self.aa_path = None      # Aa.jvg (layer_type==1 的贴图源)
        self.af_path = None      # Af.jvg (layer_type!=1 的贴图源)
        self.sws_grp = None      # _SWSGrp 实例 (sub_451780 A2C22C=1 分支)
        self.entries = []
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = None

        # JVG 数据 (预览用, 完整解码)
        self._aa_data = None
        self._af_data = None
        self._jvg_cache = LRUCache(capacity=500)
        self._pil_cache = LRUCache(capacity=500)

        # JVG 轻量探针 (block 帧数列表)
        self._aa_counts = []
        self._af_counts = []

        # 预览状态
        self._preview_job = None
        self._preview_tick_idx = 0
        self._is_playing = False
        self._last_time = 0.0
        self._tick_accumulator = 0.0
        # 固定包围盒 (切换条目时算一次, 避免随方向/tick 抖动)
        self._preview_bbox = None
        # 预览音效: 已触发 tick 集合 (防止同一 tick 反复播放)
        self._preview_played_ticks = set()
        # MCI 别名池: [(alias, ...)] —— 由 _preview_stop 清理
        self._preview_sfx_aliases = []
        # Scrubbing 节流 job ID
        self._scrub_job = None

        self._build_ui()
        self._set_edit_enabled(False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1320) // 2
        y = (sh - 860) // 2
        self.root.geometry(f'1320x860+{x}+{y}')

    # ----------- UI 构建 -----------

    def _build_ui(self):
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir,
                       accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="导出 CSV…", command=self._export_csv)
        fm.add_separator()
        fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="复制当前条目到空位", command=self._copy_entry)
        em.add_command(label="清空当前条目", command=self._clear_entry)
        mb.add_cascade(label="编辑", menu=em)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段参考 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Toolbar
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.sv, width=22)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(
            side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(
            side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)
        self.show_empty = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="显示空条目", variable=self.show_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(
            side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(
            side=tk.RIGHT, padx=10)

        # Main PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.main_paned = paned

        # Left: TreeView (缩小宽度, 给编辑区留空间)
        lf = ttk.Frame(paned)
        paned.add(lf, weight=1)
        lf.configure(width=345)
        cols = ('index', 'summary', 'n_layer')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings',
                                 selectmode='browse')
        cc = [
            ('index', '动画#', 55),
            ('summary', '图层组成 (#图层(type))', 220),
            ('n_layer', '图层数', 60),
        ]
        for cid, cn, cw in cc:
            self.tree.heading(cid, text=cn,
                              command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center'
                             if cid != 'summary' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.tag_configure('active', foreground='#228B22')
        self.tree.tag_configure('empty', foreground='#AAAAAA')

        # Right: Edit panel (更大权重, 给编辑区更多空间)
        rf = ttk.Frame(paned)
        paned.add(rf, weight=4)
        self.edit_frame = rf

        top_bar = ttk.Frame(rf)
        top_bar.pack(fill=tk.X)
        self.lbl_entry = ttk.Label(top_bar, text="未选中",
                                   font=('', 11, 'bold'))
        self.lbl_entry.pack(side=tk.LEFT, padx=4, pady=(0, 4))
        ttk.Button(top_bar, text="应用修改", command=self._apply_edit,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(top_bar, text="重置", command=self._reset_edit,
                   width=6).pack(side=tk.RIGHT, padx=1)

        # Notebook for tabs
        self.nb = ttk.Notebook(rf)
        self.nb.pack(fill=tk.BOTH, expand=True)

        # Tab 1: 方向与绘制顺序 (z-order)
        self.dir_frame = ttk.Frame(self.nb)
        self.nb.add(self.dir_frame, text="方向与绘制顺序")

        # Tab 2: 时间轴与预览 (统一视图: 预览 + 时间轴 + 音效标记)
        self.unified_frame = ttk.Frame(self.nb)
        self.nb.add(self.unified_frame, text="时间轴与预览")
        self._layer_vars = []   # [{key: StringVar, '_type_combo': Combobox, ...}] × 8
        self._tl_selected_layers = set()
        self._marquee_start = None
        self._tl_track_h = 28
        self._tl_zoom = 40
        self._tl_playhead = 0
        self._tl_last_layers_info = []
        self._edit_snapshot = None
        self._tl_edit_enabled = False

        # Tab 3: 条目级参数
        self.param_frame = ttk.Frame(self.nb)
        self.nb.add(self.param_frame, text="条目级参数")

        # Tab 4: 尾部数据 (16 对)
        self.tail_frame = ttk.Frame(self.nb)
        self.nb.add(self.tail_frame, text="尾部数据")

        # Bottom path bar
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_path = ttk.Label(pf, text="", foreground="gray")
        self.lbl_path.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_jvg = ttk.Label(pf, text="", foreground="gray")
        self.lbl_jvg.pack(side=tk.LEFT, padx=10, pady=2)

        self._build_direction_ui()
        self._build_unified_ui()
        self._build_param_ui()
        self._build_tail_ui()

        # 默认选中时间轴与预览 Tab
        self.nb.select(self.unified_frame)
        # 左侧列表最小宽度 (延迟确保窗口已渲染)
        self.root.after(345, lambda: self.main_paned.sashpos(0, 345))

    # -------- Tab: 方向与绘制顺序 --------

    def _build_direction_ui(self):
        """4 × 8 表格: 行=方向, 列=z-order 位次, 单元格=图层号 (0/1..8)
        sub_4434BC: v22[8*v33 + i] 按字节序依次渲染 → 后绘制在上层
        """
        main = ttk.Frame(self.dir_frame, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="方向表 (bytes 0-31): 每行 8 个槽 = 该方向的绘制顺序 "
                 "(从左到右: 底层 → 顶层)。单元格值 0=空, 1~8=图层号。",
            font=FONT_S, foreground='#666', wraplength=900, justify='left'
        ).pack(anchor=tk.W, pady=(0, 6))

        tbl = ttk.Frame(main)
        tbl.pack(anchor=tk.W)

        # 表头
        ttk.Label(tbl, text="", width=14).grid(row=0, column=0)
        ttk.Label(tbl, text="底层", font=FONT_S,
                  foreground='#888').grid(row=0, column=1, sticky='w')
        ttk.Label(tbl, text="→ 顶层", font=FONT_S,
                  foreground='#888').grid(row=0, column=8, sticky='e')
        for s in range(8):
            ttk.Label(tbl, text=f"z{s}", font=FONT_S,
                      foreground='#999').grid(row=1, column=1 + s, padx=2)

        # 4 行 × 8 列
        self._dir_vars = [[tk.StringVar() for _ in range(8)] for _ in range(4)]
        for d in range(4):
            ttk.Label(tbl, text=DIRECTION_LABELS[d], font=FONT_B).grid(
                row=2 + d, column=0, sticky='w', padx=(0, 6), pady=2)
            for i in range(8):
                ent = ttk.Entry(tbl, textvariable=self._dir_vars[d][i],
                                width=4, font=FONT, justify='center')
                ent.grid(row=2 + d, column=1 + i, padx=1, pady=1)
                self._bind_tooltip(
                    ent,
                    f"{DIRECTION_LABELS[d]} z-order[{i}] (byte {d*8+i})\n"
                    f"值 0=空, 1-8=图层号\n"
                    f"sub_4434BC 按此顺序依次渲染, 后画的覆盖前画的")

        ttk.Label(
            main,
            text="说明: 朝向不同时顺序常反转 (如下/右 = [3,4,1,2], 上/左 = [1,2,3,4]), "
                 "这就是 2.5D 身前/身后遮挡关系的数据源。",
            font=FONT_S, foreground='#888', wraplength=900, justify='left'
        ).pack(anchor=tk.W, pady=(10, 0))

    # -------- Tab: 图层编辑 --------

    # -------- Tab: 时间轴编辑 (替代旧8子Tab) --------

    def _build_unified_ui(self):
        """构建统一面板: 预览 + 时间轴 + 音效标记 + 缩略图"""
        main = ttk.Frame(self.unified_frame, padding=5)
        main.pack(fill=tk.BOTH, expand=True)

        # ====== 控制栏 (合并) ======
        ctrl = ttk.Frame(main)
        ctrl.pack(fill=tk.X, pady=(0, 3))

        # 步进 + 播放控制
        ttk.Button(ctrl, text="◀◀", width=3,
                   command=self._tl_goto_first).pack(side=tk.LEFT, padx=1)
        ttk.Button(ctrl, text="◀", width=3,
                   command=self._tl_step_prev).pack(side=tk.LEFT, padx=1)
        ttk.Button(ctrl, text="▶", command=self._preview_play,
                   width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(ctrl, text="⏸", command=self._preview_stop,
                   width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(ctrl, text="▶▶", width=3,
                   command=self._tl_goto_last).pack(side=tk.LEFT, padx=1)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)

        # 方向选择
        ttk.Label(ctrl, text="方向:", font=FONT_S).pack(side=tk.LEFT)
        self._preview_dir_var = tk.IntVar(value=0)
        for d in range(4):
            ttk.Radiobutton(ctrl, text=DIRECTION_SHORT[d],
                            variable=self._preview_dir_var, value=d,
                            command=self._preview_redraw,
                            width=5).pack(side=tk.LEFT)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)

        ttk.Label(ctrl, text="周期(ms):", font=FONT_S).pack(side=tk.LEFT)
        self._preview_speed = tk.IntVar(value=120)
        ttk.Spinbox(ctrl, textvariable=self._preview_speed,
                    from_=10, to=500, increment=10, width=5,
                    font=FONT).pack(side=tk.LEFT, padx=2)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)

        # 时间轴缩放
        ttk.Label(ctrl, text="缩放:", font=FONT_S).pack(side=tk.LEFT)
        ttk.Button(ctrl, text="−", width=2,
                   command=self._tl_zoom_out).pack(side=tk.LEFT, padx=1)
        ttk.Button(ctrl, text="+", width=2,
                   command=self._tl_zoom_in).pack(side=tk.LEFT, padx=1)
        self._tl_zoom_lbl = ttk.Label(ctrl, text="40px/t",
                                      font=('', 7))

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)

        ttk.Button(ctrl, text="归零", width=4,
                   command=self._tl_reset_playhead).pack(side=tk.LEFT, padx=1)
        self._tl_tick_lbl = ttk.Label(ctrl, text="tick:0", font=FONT_S, width=7)
        self._tl_tick_lbl.pack(side=tk.LEFT, padx=2)

        # 图层可见性 (第二行)
        vis_row = ttk.Frame(main)
        vis_row.pack(fill=tk.X, pady=(0, 3))
        ttk.Label(vis_row, text="图层可见:", font=FONT_S).pack(side=tk.LEFT)
        self._preview_vis_frame = ttk.Frame(vis_row)
        self._preview_vis_frame.pack(side=tk.LEFT, fill=tk.X)
        self._preview_vis_vars = {}
        self._tl_zoom_lbl.pack(side=tk.LEFT, padx=2)

        # 编辑模式开关
        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)
        self._edit_mode_var = tk.BooleanVar(value=False)
        self._edit_mode_btn = ttk.Checkbutton(
            ctrl, text="编辑模式", variable=self._edit_mode_var,
            command=self._toggle_edit_mode)
        self._edit_mode_btn.pack(side=tk.LEFT, padx=4)

        # 图层面板开关
        self._layer_panel_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl, text="☰ 图层", variable=self._layer_panel_visible,
                        command=self._toggle_layer_panel).pack(
                            side=tk.LEFT, padx=4)

        # ====== 垂直分割: 预览区 + 时间轴区 (可拖动调整) ======
        main_vpw = ttk.PanedWindow(main, orient=tk.VERTICAL)
        main_vpw.pack(fill=tk.BOTH, expand=True)

        # 上部: PanedWindow (左预览画布 + 右图层卡片)
        upper_pw = ttk.PanedWindow(main_vpw, orient=tk.HORIZONTAL)
        main_vpw.add(upper_pw, weight=3)

        # 左: 预览画布 (主区域)
        preview_outer = ttk.Frame(upper_pw)
        upper_pw.add(preview_outer, weight=1)

        # 右: 图层卡片列表 (默认隐藏, 点击 ☰ 图层 展开)
        right_outer = ttk.Frame(upper_pw, width=240)
        upper_pw.add(right_outer, weight=0)
        upper_pw.forget(right_outer)  # 默认隐藏
        self._tl_layer_panel = right_outer
        self._tl_layer_pw = upper_pw

        right_canvas = tk.Canvas(right_outer, width=240, highlightthickness=0)
        right_sb = ttk.Scrollbar(right_outer, orient=tk.VERTICAL,
                                 command=right_canvas.yview)
        right_inner = ttk.Frame(right_canvas)
        right_inner.bind('<Configure>',
                         lambda e, c=right_canvas: c.configure(
                             scrollregion=c.bbox('all')))
        right_canvas.create_window((0, 0), window=right_inner, anchor='nw')
        right_canvas.configure(yscrollcommand=right_sb.set)
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_sb.pack(side=tk.RIGHT, fill=tk.Y)

        def _rmw(e, c=right_canvas):
            c.yview_scroll(int(-1 * (e.delta / 120)), "units")

        right_canvas.bind("<Enter>",
                          lambda e, c=right_canvas: c.bind_all(
                              "<MouseWheel>", _rmw))
        right_canvas.bind("<Leave>",
                          lambda e, c=right_canvas: c.unbind_all(
                              "<MouseWheel>"))

        self._preview_canvas = tk.Canvas(preview_outer, bg='#1a1a2e',
                                         highlightthickness=0)
        self._preview_canvas.pack(fill=tk.BOTH, expand=True)
        self._preview_canvas.bind('<Configure>', lambda e: self._preview_redraw())
        self._preview_canvas.bind('<Left>', lambda e: self._preview_step_back())
        self._preview_canvas.bind('<Right>', lambda e: self._preview_step_next())
        self._preview_canvas.bind('<Button-1>', self._pv_on_press, add='+')
        self._preview_canvas.bind('<B1-Motion>', self._pv_on_drag, add='+')
        self._preview_canvas.bind('<ButtonRelease-1>', self._pv_on_release, add='+')
        self._preview_canvas.bind('<Motion>', self._pv_on_motion, add='+')
        self._pv_drag_state = None
        self._preview_sprite_boxes = []

        if not HAS_PIL:
            self._preview_canvas.create_text(
                200, 100, text="需要 Pillow 库:\npip install Pillow",
                fill="#888", font=("", 11))

        # ====== 下部: 时间轴画布 (可上下滚动) ======
        tl_frame = ttk.Frame(main_vpw)
        main_vpw.add(tl_frame, weight=2)

        self._tl_canvas = tk.Canvas(tl_frame, bg='#f5f5f5',
                                    highlightthickness=0)
        tl_hsb = ttk.Scrollbar(tl_frame, orient=tk.HORIZONTAL,
                               command=self._tl_canvas.xview)
        tl_vsb = ttk.Scrollbar(tl_frame, orient=tk.VERTICAL,
                               command=self._tl_canvas.yview)
        self._tl_canvas.configure(xscrollcommand=tl_hsb.set,
                                  yscrollcommand=tl_vsb.set)
        self._tl_canvas.grid(row=0, column=0, sticky='nsew')
        tl_vsb.grid(row=0, column=1, sticky='ns')
        tl_hsb.grid(row=1, column=0, sticky='ew')
        tl_frame.grid_rowconfigure(0, weight=1)
        tl_frame.grid_columnconfigure(0, weight=1)

        self._tl_canvas.bind("<MouseWheel>", self._tl_on_mousewheel)
        self._tl_canvas.bind("<Button-1>", self._tl_on_click)
        self._tl_canvas.bind("<B1-Motion>", self._tl_on_drag)
        self._tl_canvas.bind("<ButtonRelease-1>", self._tl_on_release)
        self._tl_canvas.bind("<Motion>", self._tl_on_motion)
        self._tl_drag_state = None

        # 时间轴: 鼠标中键拖拽平移
        self._tl_canvas.bind("<Button-2>", self._tl_pan_start)
        self._tl_canvas.bind("<B2-Motion>", self._tl_pan_move)

        # NLE 快捷键 (J/K/L + 空格, 全局绑定)
        self.root.bind('<KeyPress-j>', self._nle_play_reverse)
        self.root.bind('<KeyPress-k>', lambda e: self._preview_stop())
        self.root.bind('<KeyPress-l>', self._nle_play_forward)
        self.root.bind('<space>', self._nle_toggle_playback)
        # 上下方向键: 轨道穿梭
        self.root.bind('<Up>', self._nle_track_up)
        self.root.bind('<Down>', self._nle_track_down)

        # 时间轴右键菜单 + Shift+滚轮轨道高度
        self._tl_canvas.bind("<Button-3>", self._tl_on_right_click)
        self._tl_canvas.bind("<Shift-MouseWheel>", self._tl_on_shift_mousewheel)

        # ====== 底部: 帧缩略图选择器 ======
        self._thumb_frame = ttk.Frame(main, height=56)
        self._thumb_frame.pack(fill=tk.X, pady=(3, 0))
        self._thumb_canvas = tk.Canvas(self._thumb_frame, height=56,
                                       bg='#e8e8e8', highlightthickness=0)
        self._thumb_canvas.pack(fill=tk.X)
        self._thumb_canvas.create_text(140, 28,
                                       text="(选择图层查看帧缩略图)",
                                       fill='#999', font=FONT_S)
        self._thumb_images = []

        # ====== 构建图层卡片 ======
        self._tl_track_colors = ['#e74c3c', '#3498db', '#f39c12', '#2ecc71',
                                 '#9b59b6', '#1abc9c', '#e67e22', '#95a5a6']
        self._tl_cards = []
        for s in range(ACT_MAX_LAYER):
            card = self._build_timeline_card(right_inner, s)
            self._tl_cards.append(card)

        self._tl_right_canvas = right_canvas
        self._tl_right_inner = right_inner

        # 默认编辑模式关闭: 禁用手动编辑交互
        self._set_timeline_interactive(False)

    def _toggle_edit_mode(self):
        """切换编辑模式"""
        en = self._edit_mode_var.get()
        self._set_timeline_interactive(en)
        self.status_var.set("编辑模式: 开启" if en else "编辑模式: 关闭 (预览优先)")

    def _toggle_layer_panel(self):
        """显示/隐藏图层面板"""
        if self._layer_panel_visible.get():
            self._tl_layer_pw.add(self._tl_layer_panel, weight=0)
        else:
            self._tl_layer_pw.forget(self._tl_layer_panel)

    def _set_timeline_interactive(self, en):
        """启用/禁用时间轴编辑交互 (不影响预览)"""
        # 轨道边缘拖拽和图层选择仅在编辑模式下可用
        self._tl_edit_enabled = en
        if not en:
            self._tl_selected_layers.clear()
            self._tl_refresh_thumbnails()

    def _build_timeline_card(self, parent, layer_idx):
        """构建紧凑图层卡片: 头部 + 详细区域(可折叠)"""
        s = layer_idx + 1
        vars_row = {}
        self._layer_vars.append(vars_row)

        # 卡片容器
        card = ttk.Frame(parent, relief='ridge', borderwidth=1)
        card.pack(fill=tk.X, padx=2, pady=2)

        # ---- 头部 ----
        head = ttk.Frame(card)
        head.pack(fill=tk.X, padx=4, pady=(4, 2))

        lbl = ttk.Label(head, text=f"#{s}", font=('', 10, 'bold'), width=3)
        lbl.pack(side=tk.LEFT)
        vars_row['_card_label'] = lbl

        type_var = tk.StringVar()
        vars_row['layer_type'] = type_var
        type_combo = ttk.Combobox(head, textvariable=type_var,
                                  values=list(LAYER_TYPE_LABELS.values()),
                                  width=22, state='readonly', font=FONT_S)
        type_combo.pack(side=tk.LEFT, padx=2)
        vars_row['_type_combo'] = type_combo

        def _select_card(e, idx=layer_idx):
            self._tl_select_layer(idx)

        for w in (card, head, lbl, type_combo):
            w.bind('<Button-1>', _select_card)

        # ---- 紧凑属性行 ----
        row1 = ttk.Frame(card)
        row1.pack(fill=tk.X, padx=4, pady=1)

        # blend_mode
        bv = tk.StringVar()
        vars_row['blend_mode'] = bv
        blend_combo = ttk.Combobox(row1, textvariable=bv,
                                   values=list(BLEND_MODE_LABELS.values()),
                                   width=14, font=FONT_S, state='readonly')
        blend_combo.pack(side=tk.LEFT, padx=(0, 2))
        vars_row['_blend_mode_combo'] = blend_combo

        # loop_behavior
        lv = tk.StringVar()
        vars_row['loop_behavior'] = lv
        loop_combo = ttk.Combobox(row1, textvariable=lv,
                                  values=list(LOOP_BEHAVIOR_LABELS.values()),
                                  width=20, font=FONT_S, state='readonly')
        loop_combo.pack(side=tk.LEFT, padx=2)
        vars_row['_loop_behavior_combo'] = loop_combo

        # 帧范围标签 (点击后可在缩略图区调整)
        frame_lbl = ttk.Label(row1, text="[0..0]", font=FONT_S, width=10,
                              anchor='center')
        frame_lbl.pack(side=tk.LEFT, padx=2)
        vars_row['_frame_lbl'] = frame_lbl
        frame_lbl.bind('<Button-1>', _select_card)

        # start_delay
        ttk.Label(row1, text="延迟:", font=FONT_S).pack(side=tk.LEFT,
                                                        padx=(8, 0))
        sdv = tk.StringVar(value="0")
        vars_row['start_delay'] = sdv
        sd_entry = ttk.Entry(row1, textvariable=sdv, width=4, font=FONT_S)
        sd_entry.pack(side=tk.LEFT, padx=1)

        # tick_interval
        ttk.Label(row1, text="间隔:", font=FONT_S).pack(side=tk.LEFT, padx=(4, 0))
        tiv = tk.StringVar(value="0")
        vars_row['tick_interval'] = tiv
        ti_entry = ttk.Entry(row1, textvariable=tiv, width=4, font=FONT_S)
        ti_entry.pack(side=tk.LEFT, padx=1)

        # ---- 详细区域 (默认折叠) ----
        detail_frame = ttk.Frame(card)
        vars_row['_detail_frame'] = detail_frame
        vars_row['_detail_expanded'] = False

        # Toggle按钮
        toggle_btn = ttk.Button(card, text="▼ 展开详情", width=12,
                                command=lambda idx=layer_idx: self._tl_toggle_detail(idx))
        toggle_btn.pack(anchor=tk.W, padx=4, pady=(0, 2))
        vars_row['_toggle_btn'] = toggle_btn

        # 详细字段 (从 FIELD_GROUPS 构建, 排除已在紧凑行显示的)
        COMPACT_FIELDS = {'layer_type', 'blend_mode', 'loop_behavior',
                          'start_delay', 'tick_interval'}
        for grp_name, fields in FIELD_GROUPS:
            # 筛掉已显示的
            remaining = [(fn, idx, label, w, c) for (fn, idx, label, w, c) in fields
                         if fn not in COMPACT_FIELDS]
            if not remaining:
                continue
            lf_grp = ttk.LabelFrame(detail_frame, text=grp_name, padding=3)
            lf_grp.pack(fill=tk.X, padx=2, pady=1, anchor=tk.W)
            self._render_field_group(lf_grp, remaining, vars_row)

        # JVG 探针
        probe_lbl = ttk.Label(detail_frame, text="", font=FONT_S,
                              foreground='#556', justify='left')
        probe_lbl.pack(fill=tk.X, padx=4, pady=(2, 0), anchor=tk.W)
        vars_row['_probe_lbl'] = probe_lbl

        # 字段变化时刷新探针; jvg_block_index 变化时自动填充帧参数
        for fn in ('jvg_block_index', 'dir_frame_offset',
                   'first_frame', 'last_frame', 'direction_mode'):
            if fn in vars_row:
                vars_row[fn].trace_add(
                    'write',
                    lambda *_a, idx=layer_idx, f=fn:
                        self._on_layer_field_change(idx, f))
        type_combo.bind('<<ComboboxSelected>>',
                        lambda _e, idx=layer_idx: self._update_layer_probe(idx),
                        add='+')

        return card

    def _tl_toggle_detail(self, layer_idx):
        """展开/折叠图层卡片的详细属性"""
        vr = self._layer_vars[layer_idx]
        df = vr['_detail_frame']
        btn = vr['_toggle_btn']
        if vr['_detail_expanded']:
            df.pack_forget()
            btn.config(text="▼ 展开详情")
            vr['_detail_expanded'] = False
        else:
            df.pack(fill=tk.X, padx=2, pady=(0, 4), after=btn)
            btn.config(text="▲ 收起详情")
            vr['_detail_expanded'] = True

    def _tl_select_layer(self, layer_idx):
        """选中图层: 高亮卡片, 联动缩略图区和时间轴"""
        self._tl_selected_layers.clear()
        self._tl_selected_layers.add(layer_idx)
        self._tl_refresh_thumbnails()
        self._tl_redraw()

    # ---- 时间轴绘制 ----

    def _tl_redraw(self):
        """重绘时间轴画布"""
        c = self._tl_canvas
        c.delete("all")
        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]
        zoom = self._tl_zoom
        margin = 30
        track_h = getattr(self, '_tl_track_h', 28)
        track_gap = 4
        ruler_h = 22

        # 计算总 tick 数
        max_tick = 0
        layers_info = []
        for s in range(ACT_MAX_LAYER):
            L = entry['layers'][s]
            if L[0] == 0:
                continue
            delay = L[22]
            interval = max(1, L[21])
            first = L[17]
            last = L[18]
            span = max(1, last - first + 1)
            dur = delay + span * interval
            if dur > max_tick:
                max_tick = dur
            layers_info.append((s, L[0], delay, span * interval, L[19], L[21]))

        self._tl_last_layers_info = layers_info
        max_tick = max(max_tick, 10)
        total_w = margin * 2 + int(max_tick * zoom) + 200

        # 画布可滚动区域 (含音效标记行)
        content_h = ruler_h + len(layers_info) * (track_h + track_gap) + 40
        c.configure(scrollregion=(0, 0, total_w, content_h))

        # 刻度尺
        tick_step = max(1, int(20 / zoom))  # 约每20px一个刻度标
        for t in range(0, max_tick + tick_step, tick_step):
            x = margin + int(t * zoom)
            c.create_line(x, ruler_h - 4, x, ruler_h, fill='#999')
            if t % max(1, tick_step * 5) == 0 or t == 0:
                c.create_text(x, ruler_h - 8, text=str(t), font=FONT_S,
                              fill='#666', anchor='s')

        # 轨道条
        for i, (s, ltype, delay, play_ticks, loop, interval) in enumerate(layers_info):
            y = ruler_h + i * (track_h + track_gap) + 4
            color = self._tl_track_colors[s % 8]
            is_selected = (s in getattr(self, '_tl_selected_layers', set()))

            # 可见性切换 (左侧, 可点击)
            vis_var = self._preview_vis_vars.get(s + 1)
            vis_on = vis_var.get() if vis_var else True
            vis_x = 18
            vis_tag = f'vis_{s}'
            eye_char = '●' if vis_on else '○'
            eye_color = color if vis_on else '#bbb'
            c.create_text(vis_x, y + track_h // 2, text=eye_char,
                          font=('', 10), fill=eye_color, anchor='center',
                          tags=(vis_tag,))
            # 透明点击区域 (扩大命中范围)
            c.create_rectangle(0, y, 30, y + track_h,
                               fill='', outline='', tags=(vis_tag,))

            # 图层标签
            c.create_text(34, y + track_h // 2, text=f"#{s+1}",
                          font=('', 9, 'bold'), fill=color, anchor='w')

            # 延迟区 (灰色)
            if delay > 0:
                dx = margin
                dw = int(delay * zoom)
                c.create_rectangle(dx, y, dx + dw, y + track_h,
                                   fill='#ddd', outline='#ccc')

            # 播放区 (彩色)
            px = margin + int(delay * zoom)
            pw = max(4, int(play_ticks * zoom))
            c.create_rectangle(px, y, px + pw, y + track_h,
                               fill=color,
                               outline=('#fff' if is_selected else color),
                               width=(3 if is_selected else 1))

            # 帧范围文字
            L = entry['layers'][s]
            c.create_text(px + 4, y + track_h // 2,
                          text=f"[{L[17]}..{L[18]}] loop={L[19]}",
                          font=FONT_S, fill='#fff', anchor='w')

            # loop标记
            loop_mark = ""
            if L[19] == -1:
                loop_mark = "↻"
            elif L[19] == -2:
                loop_mark = "■"
            elif L[19] >= 0:
                loop_mark = f"↷{L[19]}"
            if loop_mark:
                c.create_text(px + pw + 4, y + track_h // 2, text=loop_mark,
                              font=FONT_S, fill=color, anchor='w')

            # 存储轨道bbox用于点击检测
            vars_row = self._layer_vars[s]
            vars_row['_track_bbox'] = (px, y, px + pw, y + track_h)
            vars_row['_delay_bbox'] = (margin, y, px, y + track_h)
            vars_row['_track_layer'] = s

        # 播放头 (用 tag 标记, 支持增量更新)
        ph_x = margin + int(self._tl_playhead * zoom)
        ph_bottom = ruler_h + len(layers_info) * (track_h + track_gap) + 10
        c.create_line(ph_x, 0, ph_x, ph_bottom,
                      fill='red', width=2, tags='playhead')
        c.create_polygon(ph_x - 5, 0, ph_x + 5, 0, ph_x, 8,
                         fill='red', outline='red', tags='playhead')
        self._tl_ph_bottom = ph_bottom

        # ---- 音效标记 (从 tail 数据) ----
        sfx_y = ruler_h + len(layers_info) * (track_h + track_gap) + 14
        tail = entry.get('tail') or []
        sfx_colors = ['#e91e63', '#9c27b0', '#3f51b5', '#009688',
                      '#ff9800', '#795548', '#607d8b', '#4caf50']
        sfx_markers = []
        for i in range(16):
            sid = tail[i * 2] if i * 2 < len(tail) else 0
            trig = tail[i * 2 + 1] if i * 2 + 1 < len(tail) else 0
            if sid == 0 or trig < 0:
                continue
            sx = margin + int(trig * zoom)
            color = sfx_colors[i % len(sfx_colors)]
            # 音符图标
            c.create_text(sx, sfx_y, text="♪", fill=color,
                          font=("", 10, "bold"), tags=('sfx',))
            # 标签
            c.create_text(sx, sfx_y + 12, text=f"sid={sid}",
                          font=("", 6), fill=color, anchor='n', tags=('sfx',))
            # 竖线连接到轨道
            c.create_line(sx, sfx_y - 10, sx, sfx_y - 4, fill=color,
                          width=1, dash=(2, 2), tags=('sfx',))
            sfx_markers.append((sx, sfx_y, sid, trig, i))

        # 存储音效标记用于点击检测
        self._tl_sfx_markers = sfx_markers

    def _tl_update_playhead(self):
        """增量更新播放头位置 (不重绘轨道, 用于播放时跟随)"""
        c = self._tl_canvas
        zoom = self._tl_zoom
        margin = 30
        ph_x = margin + int(self._tl_playhead * zoom)
        ph_bottom = getattr(self, '_tl_ph_bottom', 100)
        # 移动现有播放头元素
        for item in c.find_withtag('playhead'):
            coords = c.coords(item)
            if len(coords) == 4:  # line: x1,y1,x2,y2
                c.coords(item, ph_x, coords[1], ph_x, coords[3])
            elif len(coords) == 6:  # polygon triangle
                c.coords(item, ph_x - 5, 0, ph_x + 5, 0, ph_x, 8)
        # 更新滚动区域
        c.configure(scrollregion=c.bbox('all'))

    def _tl_calc_duration(self, entry):
        """计算动画总tick时长"""
        max_tick = 0
        for s in range(ACT_MAX_LAYER):
            L = entry['layers'][s]
            if L[0] == 0:
                continue
            delay = L[22]
            interval = max(1, L[21])
            first = L[17]
            last = L[18]
            span = max(1, last - first + 1)
            dur = delay + span * interval
            if dur > max_tick:
                max_tick = dur
        return max_tick

    def _tl_snap_tick(self, raw_tick, exclude_layer, threshold):
        """磁吸: 将 raw_tick 吸附到最近的 snap 点 (playhead / 其他图层边缘).
        exclude_layer: 当前拖拽的图层索引, 排除自身避免吸附到自己.
        返回吸附后的 tick (或原始值, 如果无近点)."""
        if self._editing_idx is None:
            return raw_tick
        entry = self.entries[self._editing_idx]
        points = [self._tl_playhead]  # 播放头
        for s in range(8):
            if s == exclude_layer:
                continue
            L = entry['layers'][s]
            if L[0] == 0:
                continue
            # 左边缘 = start_delay
            points.append(L[22])
            # 右边缘 = start_delay + span * interval
            first = L[17]
            last = L[18]
            interval = max(1, L[21])
            span = max(1, last - first + 1)
            points.append(L[22] + span * interval)
        best = min(points, key=lambda p: abs(p - raw_tick))
        return best if abs(best - raw_tick) <= threshold else raw_tick

    # ---- 时间轴交互 ----

    def _tl_hit_test(self, canvas_x, canvas_y):
        """检测鼠标位置命中的轨道元素.
        返回 (layer_idx, 'playhead'|'left_edge'|'right_edge'|'body'|None, tick)"""
        c = self._tl_canvas
        x = c.canvasx(canvas_x)
        y = c.canvasy(canvas_y)
        zoom = self._tl_zoom
        margin = 30
        edge_margin = 6
        ruler_h = 22
        track_h = getattr(self, '_tl_track_h', 28)
        track_gap = 4

        tick = max(0, int((x - margin) / zoom + 0.5))

        # 严格: 只有刻度尺区才返回 playhead
        if y < ruler_h:
            return None, 'playhead', tick

        for s in range(ACT_MAX_LAYER):
            vr = self._layer_vars[s]
            bb = vr.get('_track_bbox')
            db = vr.get('_delay_bbox')
            if bb is None or db is None:
                continue

            # 轨道 Y 范围
            ty = bb[1]
            by = bb[3]
            if not (ty <= y <= by):
                continue

            # 左边缘 (延迟区右边界 = 播放区左边界)
            left_x = bb[0]
            if db[2] > db[0] and abs(x - left_x) <= edge_margin:
                return s, 'left_edge', tick

            # 右边缘 (播放区右边界)
            right_x = bb[2]
            if abs(x - right_x) <= edge_margin:
                return s, 'right_edge', tick

            # 轨道体内
            if db[0] <= x <= bb[2]:
                return s, 'body', tick

        # 检测音效标记
        for (sx, sy, sid, trig, i) in getattr(self, '_tl_sfx_markers', []):
            if abs(x - sx) < 10 and abs(y - sy) < 12:
                return i, 'sfx', trig

        return None, 'empty', tick

    def _tl_on_click(self, event):
        """点击时间轴: 移动播放头 / 选中图层 / 开始拖拽 / 试听音效 / 切换可见性
        Shift+点击空白→框选; Shift+点击片段→追加选择; 点击标尺→移动播放头"""
        self._tl_drag_state = None
        self._marquee_start = None

        # 检测可见性点击 (左侧 vis 区域)
        c = self._tl_canvas
        x = c.canvasx(event.x)
        y = c.canvasy(event.y)
        margin = 30
        ruler_h = 22
        track_h = getattr(self, '_tl_track_h', 28)
        track_gap = 4

        # 检查是否在轨道区域点击了可见性开关
        if 0 <= x < 30:
            for i, (s, ltype, delay, play_ticks, loop, interval) in enumerate(
                getattr(self, '_tl_last_layers_info', [])):
                ty = ruler_h + i * (track_h + track_gap) + 4
                if ty <= y <= ty + track_h:
                    vis_var = self._preview_vis_vars.get(s + 1)
                    if vis_var is not None:
                        vis_var.set(not vis_var.get())
                        self._preview_redraw()
                        self._tl_redraw()
                    return

        layer_idx, hit_type, tick = self._tl_hit_test(event.x, event.y)
        edit_ok = getattr(self, '_tl_edit_enabled', False)

        if hit_type == 'sfx':
            if edit_ok:
                self._tl_drag_state = ('sfx', layer_idx)
                return
            entry = self.entries[self._editing_idx] if self._editing_idx is not None else None
            if entry:
                tail = entry.get('tail') or []
                sid = tail[layer_idx * 2] if layer_idx * 2 < len(tail) else 0
                if sid and self.sws_grp:
                    self._play_sound_preview(sid)
        elif hit_type in ('left_edge', 'right_edge') and edit_ok:
            self._tl_drag_state = (layer_idx, hit_type)
        elif hit_type == 'body':
            if edit_ok:
                # 多选: 未按 Shift 且点击不在集合 → 清空后单选
                if not (event.state & 0x0001):
                    if layer_idx not in self._tl_selected_layers:
                        self._tl_selected_layers.clear()
                        self._tl_selected_layers.add(layer_idx)
                else:
                    self._tl_selected_layers.add(layer_idx)
                self._tl_refresh_thumbnails()
                # 记录编组拖拽起点: 所有选中图层的原始 start_delay
                entry = self.entries[self._editing_idx]
                orig_delays = {}
                for sel_idx in self._tl_selected_layers:
                    L = entry['layers'][sel_idx]
                    orig_delays[sel_idx] = L[22]
                self._tl_drag_state = ('batch_move', tick, orig_delays)
                self._tl_redraw()
            else:
                self._tl_select_layer(layer_idx)
        elif hit_type == 'empty':
            if edit_ok:
                # 记录框选起点, Shift 追加否则清空
                self._marquee_start = (x, y)
                if not (event.state & 0x0001):
                    self._tl_selected_layers.clear()
                self._tl_redraw()
            # 非编辑模式点空白无操作
        elif hit_type == 'playhead':
            self._tl_playhead = tick
            self._tl_tick_lbl.config(text=f"tick: {tick}")
            self._tl_redraw()
            self._tl_sync_preview(tick)

    def _play_sound_preview(self, sid):
        """试听指定 sound_id"""
        if self.sws_grp is None:
            return
        try:
            p = self._resolve_sound_path(sid)
            if p:
                alias = _mci_play_async(p)
                self.status_var.set(f"试听 sid={sid}")
            else:
                self.status_var.set(f"未找到音效 sid={sid}")
        except Exception:
            self.status_var.set(f"播放失败 sid={sid}")

    def _tl_on_drag(self, event):
        """拖拽: 播放头 / 轨道边缘 / 音效标记 / 框选 / 编组移动
        Shift 按下时启用磁吸 (吸附到 playhead 和其他图层边缘)."""
        c = self._tl_canvas
        x = c.canvasx(event.x)
        y = c.canvasy(event.y)

        # 框选绘制: 画虚线矩形
        if getattr(self, '_marquee_start', None) is not None:
            x0, y0 = self._marquee_start
            c.delete('marquee')
            c.create_rectangle(x0, y0, x, y,
                               outline='#3498db', width=1, dash=(4, 4),
                               tags='marquee')
            return

        layer_idx, hit_type, tick = self._tl_hit_test(event.x, event.y)
        SNAP_THRESHOLD = 2

        if self._tl_drag_state is not None:
            ds = self._tl_drag_state

            # 音效标记拖拽
            if ds[0] == 'sfx':
                sfx_idx = ds[1]
                if self._editing_idx is not None:
                    entry = self.entries[self._editing_idx]
                    tail = entry.get('tail') or []
                    if sfx_idx * 2 + 1 < len(tail):
                        tail[sfx_idx * 2 + 1] = max(0, tick)
                        self._dirty = True
                        self._tl_redraw()
                return

            # 轨道体平移拖拽
            if ds[0] == 'track_move':
                _, dlayer_idx, start_tick, start_delay = ds
                if self._editing_idx is not None:
                    entry = self.entries[self._editing_idx]
                    L = entry['layers'][dlayer_idx]
                    raw_delay = start_delay + (tick - start_tick)
                    if event.state & 0x0001:  # Shift → 磁吸
                        new_delay = max(0, self._tl_snap_tick(
                            max(0, raw_delay), dlayer_idx, SNAP_THRESHOLD))
                    else:
                        new_delay = max(0, raw_delay)
                    L[22] = new_delay
                    self._dirty = True
                    vr = self._layer_vars[dlayer_idx]
                    sdv = vr.get('start_delay')
                    if sdv is not None:
                        sdv.set(str(new_delay))
                    self._tl_redraw()
                return

            # 编组拖拽: 批量移动所有选中图层
            if ds[0] == 'batch_move':
                start_tick, orig_delays = ds[1], ds[2]
                if self._editing_idx is not None:
                    delta_tick = tick - start_tick

                    # 边界钳制: 最左的图层不能拖到 0 以下
                    min_orig = min(orig_delays.values())
                    if min_orig + delta_tick < 0:
                        delta_tick = -min_orig

                    # Shift 磁吸: 以鼠标所在图层为锚点
                    if event.state & 0x0001 and layer_idx is not None:
                        anchor_orig = orig_delays.get(layer_idx)
                        if anchor_orig is not None:
                            anchor_raw = anchor_orig + delta_tick
                            snapped = max(0, self._tl_snap_tick(
                                anchor_raw, -1, SNAP_THRESHOLD))
                            delta_tick = snapped - anchor_orig

                    entry = self.entries[self._editing_idx]
                    for sel_idx, orig_delay in orig_delays.items():
                        L = entry['layers'][sel_idx]
                        L[22] = orig_delay + delta_tick
                        vr = self._layer_vars[sel_idx]
                        sdv = vr.get('start_delay')
                        if sdv is not None:
                            sdv.set(str(L[22]))

                    self._dirty = True
                    self._tl_redraw()
                return

            # 轨道边缘拖拽
            dlayer_idx, dhit_type = ds
            if self._editing_idx is not None:
                entry = self.entries[self._editing_idx]
                L = entry['layers'][dlayer_idx]

                if dhit_type == 'right_edge':
                    delay = L[22]
                    interval = max(1, L[21])
                    first = L[17]
                    play_ticks = max(0, tick - delay)
                    new_span = max(1, play_ticks // interval)
                    new_end = max(first, first + new_span - 1)
                    if event.state & 0x0001:  # Shift → 磁吸右边缘
                        new_end = self._tl_snap_tick(
                            new_end, dlayer_idx, SNAP_THRESHOLD)
                        new_end = max(first, new_end)
                    L[18] = new_end

                elif dhit_type == 'left_edge':
                    t = tick
                    if event.state & 0x0001:  # Shift → 磁吸左边缘
                        t = self._tl_snap_tick(t, dlayer_idx, SNAP_THRESHOLD)
                    L[22] = max(0, t)

                self._dirty = True
                vr = self._layer_vars[dlayer_idx]
                fl = vr.get('_frame_lbl')
                if fl is not None:
                    fl.config(text=f"[{L[17]}..{L[18]}]")
                sdv = vr.get('start_delay')
                if sdv is not None:
                    sdv.set(str(L[22]))
                self._tl_redraw()
            return

        # 拖拽播放头 (Scrubbing: 节流渲染, 最多 30ms 一次)
        self._tl_playhead = tick
        self._tl_tick_lbl.config(text=f"tick: {tick}")
        self._tl_redraw()
        if self._scrub_job is not None:
            self.root.after_cancel(self._scrub_job)
        self._scrub_job = self.root.after(
            30, lambda: self._tl_sync_preview(self._tl_playhead))

    def _tl_on_release(self, event):
        """释放鼠标: 结算框选 / 同步预览 / 应用修改"""
        c = self._tl_canvas

        # 结算框选: AABB 碰撞检测, 框中的图层加入选中集合
        if getattr(self, '_marquee_start', None) is not None:
            x0, y0 = self._marquee_start
            x1 = c.canvasx(event.x)
            y1 = c.canvasy(event.y)
            min_x, max_x = min(x0, x1), max(x0, x1)
            min_y, max_y = min(y0, y1), max(y0, y1)

            for s in range(ACT_MAX_LAYER):
                bb = self._layer_vars[s].get('_track_bbox')
                if bb is not None:
                    # AABB 相交测试
                    hit = not (max_x < bb[0] or min_x > bb[2]
                               or max_y < bb[1] or min_y > bb[3])
                    if hit:
                        self._tl_selected_layers.add(s)

            self._marquee_start = None
            c.delete('marquee')
            self._tl_refresh_thumbnails()
            self._tl_redraw()

        if self._scrub_job is not None:
            self.root.after_cancel(self._scrub_job)
            self._scrub_job = None
        was_sfx = (self._tl_drag_state is not None
                   and self._tl_drag_state[0] == 'sfx')
        self._tl_drag_state = None
        if self._editing_idx is not None:
            entry = self.entries[self._editing_idx]
            if was_sfx:
                tail = entry.get('tail') or []
                for k in range(32):
                    self._tail_vars[k].set(str(tail[k]))
            self._populate_edit(entry)
        self._tl_sync_preview(self._tl_playhead)

    def _tl_on_motion(self, event):
        """鼠标移动: 改变光标样式"""
        layer_idx, hit_type, _ = self._tl_hit_test(event.x, event.y)
        edit_ok = getattr(self, '_tl_edit_enabled', False)
        if hit_type == 'sfx' and edit_ok:
            self._tl_canvas.configure(cursor='hand2')
        elif hit_type in ('left_edge', 'right_edge') and edit_ok:
            self._tl_canvas.configure(cursor='sb_h_double_arrow')
        else:
            self._tl_canvas.configure(cursor='')

    def _tl_sync_preview(self, tick):
        """将预览同步到指定tick: 停止播放, 渲染指定tick帧"""
        self._preview_stop()
        self._preview_tick_idx = tick
        self._preview_redraw()

    def _tl_on_mousewheel(self, event):
        """鼠标滚轮: 上下滚动 / Ctrl+滚轮 或 Alt+滚轮 缩放 (以鼠标位置为中心)"""
        if event.state & 0x4 or event.state & 0x20000:  # Ctrl 或 Alt
            # 记录缩放前鼠标对应的 tick
            old_zoom = self._tl_zoom
            old_cx = self._tl_canvas.canvasx(event.x)
            old_tick = old_cx / max(1, old_zoom)

            delta = 1 if event.delta > 0 else -1
            self._tl_zoom = max(2, min(40, self._tl_zoom + delta * 2))
            self._tl_zoom_lbl.config(text=f"{self._tl_zoom}px/t")
            self._tl_redraw()

            # 缩放后滚动使 old_tick 保持在鼠标位置
            new_cx = old_tick * self._tl_zoom
            dx = new_cx - old_cx
            self._tl_canvas.xview_scroll(int(dx), "units")
        else:
            self._tl_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _tl_zoom_in(self):
        self._tl_zoom = min(40, self._tl_zoom + 2)
        self._tl_zoom_lbl.config(text=f"{self._tl_zoom}px/tick")
        self._tl_redraw()

    def _tl_zoom_out(self):
        self._tl_zoom = max(2, self._tl_zoom - 2)
        self._tl_zoom_lbl.config(text=f"{self._tl_zoom}px/tick")
        self._tl_redraw()

    def _tl_reset_playhead(self):
        self._tl_playhead = 0
        self._tl_tick_lbl.config(text="tick: 0")
        self._tl_redraw()
        self._tl_sync_preview(0)

    def _tl_step_next(self):
        self._tl_playhead += 1
        self._tl_tick_lbl.config(text=f"tick: {self._tl_playhead}")
        self._tl_redraw()
        self._tl_sync_preview(self._tl_playhead)

    def _tl_step_prev(self):
        self._tl_playhead = max(0, self._tl_playhead - 1)
        self._tl_tick_lbl.config(text=f"tick: {self._tl_playhead}")
        self._tl_redraw()
        self._tl_sync_preview(self._tl_playhead)

    def _tl_goto_first(self):
        self._tl_playhead = 0
        self._tl_tick_lbl.config(text="tick: 0")
        self._tl_redraw()
        self._tl_sync_preview(0)

    def _tl_goto_last(self):
        if self._editing_idx is not None:
            entry = self.entries[self._editing_idx]
            self._tl_playhead = self._tl_calc_duration(entry)
        else:
            self._tl_playhead = 0
        self._tl_tick_lbl.config(text=f"tick: {self._tl_playhead}")
        self._tl_redraw()
        self._tl_sync_preview(self._tl_playhead)

    # ---- NLE 快捷键处理 ----

    def _nle_play_forward(self, event=None):
        """L 键: 播放 (多次按可实现倍速, 当前简化实现为播放/继续)."""
        if not getattr(self, '_is_playing', False):
            self._preview_play()

    def _nle_play_reverse(self, event=None):
        """J 键: 倒放/后退一帧."""
        self._preview_stop()
        self._preview_step_back()

    def _nle_toggle_playback(self, event=None):
        """空格键: 播放/暂停切换. 焦点在输入框时忽略."""
        w = self.root.focus_get()
        if isinstance(w, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            return
        if getattr(self, '_is_playing', False):
            self._preview_stop()
        else:
            self._preview_play()

    # ---- 时间轴画布导航 ----

    def _tl_pan_start(self, event):
        self._tl_canvas.scan_mark(event.x, event.y)

    def _tl_pan_move(self, event):
        self._tl_canvas.scan_dragto(event.x, event.y, gain=1)

    # ---- 轨道高度 (Shift+滚轮) ----

    def _tl_on_shift_mousewheel(self, event):
        """Shift+滚轮: 调整轨道高度 20~80px"""
        delta = 1 if event.delta > 0 else -1
        self._tl_track_h = max(20, min(80, self._tl_track_h + delta * 4))
        self._tl_redraw()

    # ---- 轨道键盘导航 (Up/Down) ----

    def _nle_track_up(self, event=None):
        """上方向键: 选中上一个非空图层"""
        if not getattr(self, '_tl_edit_enabled', False) or self._editing_idx is None:
            return
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Spinbox)):
            return
        entry = self.entries[self._editing_idx]
        current = min(self._tl_selected_layers) if self._tl_selected_layers else ACT_MAX_LAYER
        for s in range(current - 1, -1, -1):
            if entry['layers'][s][0] != 0:
                self._tl_select_layer(s)
                return

    def _nle_track_down(self, event=None):
        """下方向键: 选中下一个非空图层"""
        if not getattr(self, '_tl_edit_enabled', False) or self._editing_idx is None:
            return
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Spinbox)):
            return
        entry = self.entries[self._editing_idx]
        current = max(self._tl_selected_layers) if self._tl_selected_layers else -1
        for s in range(current + 1, ACT_MAX_LAYER):
            if entry['layers'][s][0] != 0:
                self._tl_select_layer(s)
                return

    # ---- 右键上下文菜单 ----

    def _tl_on_right_click(self, event):
        """右键轨道: 弹出快捷操作菜单"""
        if not getattr(self, '_tl_edit_enabled', False):
            return
        layer_idx, hit_type, _ = self._tl_hit_test(event.x, event.y)
        if layer_idx is None:
            return
        if hit_type not in ('body', 'left_edge', 'right_edge'):
            return
        if self._editing_idx is None:
            return

        self._tl_select_layer(layer_idx)
        L = self.entries[self._editing_idx]['layers'][layer_idx]
        menu = tk.Menu(self.root, tearoff=0)

        vis_var = self._preview_vis_vars.get(layer_idx + 1)
        is_vis = vis_var.get() if vis_var else True
        menu.add_command(
            label="隐藏图层" if is_vis else "显示图层",
            command=lambda: self._quick_toggle_vis(layer_idx))

        menu.add_separator()

        blend_menu = tk.Menu(menu, tearoff=0)
        for val, label in BLEND_MODE_LABELS.items():
            blend_menu.add_command(
                label=label,
                command=lambda v=val: self._quick_set_blend(layer_idx, v))
        menu.add_cascade(label="混合模式", menu=blend_menu)

        menu.add_separator()
        menu.add_command(label="清空该图层数据",
                         command=lambda: self._quick_clear_layer(layer_idx))

        menu.tk_popup(event.x_root, event.y_root)

    def _quick_toggle_vis(self, layer_idx):
        vis_var = self._preview_vis_vars.get(layer_idx + 1)
        if vis_var:
            vis_var.set(not vis_var.get())
            self._preview_redraw()
            self._tl_redraw()

    def _quick_set_blend(self, layer_idx, mode_val):
        if self._editing_idx is not None:
            L = self.entries[self._editing_idx]['layers'][layer_idx]
            L[11] = mode_val
            self._dirty = True
            self._populate_layer(layer_idx, L)
            self._preview_redraw()

    def _quick_clear_layer(self, layer_idx):
        """清空图层: 把该层除 layer_type=0 外的关键字段归零"""
        if self._editing_idx is None:
            return
        if not messagebox.askyesno("确认", f"确定清空图层 #{layer_idx + 1} 的所有数据?"):
            return
        L = self.entries[self._editing_idx]['layers'][layer_idx]
        for i in range(len(L)):
            L[i] = 0
        L[0] = 0
        self._dirty = True
        self._tl_selected_layers.discard(layer_idx)
        self._tl_refresh_thumbnails()
        self._tl_redraw()
        self._preview_redraw()
        self._populate_layer(layer_idx, L)
        self.status_var.set(f"图层 #{layer_idx + 1} 已清空")

    # ---- 缩略图 ----

    def _tl_refresh_thumbnails(self):
        """刷新帧缩略图条: 解码选中图层JVG块的所有帧, 显示为缩略图"""
        c = self._thumb_canvas
        c.delete("all")
        self._thumb_images = []

        if not self._tl_selected_layers:
            c.create_text(140, 28, text="(选择图层查看帧缩略图)",
                          fill='#999', font=FONT_S)
            return
        if self._editing_idx is None:
            return
        if not self._preview_load_jvg():
            c.create_text(140, 28, text="(未加载 JVG)",
                          fill='#999', font=FONT_S)
            return

        # 多选时取最小索引图层作为缩略图代表
        display_layer = min(self._tl_selected_layers)
        entry = self.entries[self._editing_idx]
        L = entry['layers'][display_layer]
        ltype = L[0]
        block_idx = L[1]
        if ltype == 0 or block_idx <= 0:
            c.create_text(140, 28, text="(该图层未关联 JVG 块)",
                          fill='#999', font=FONT_S)
            return

        # 确定 JVG 来源
        src = 'aa' if ltype == 1 else 'af'
        jvg = self._aa_data if src == 'aa' else self._af_data
        if jvg is None or block_idx >= jvg.block_count:
            c.create_text(140, 28, text="(JVG 块不存在)",
                          fill='#999', font=FONT_S)
            return

        blk = jvg.get_block(block_idx)
        total_frames = blk.frame_count
        if total_frames == 0:
            return

        first = L[17]
        last = L[18]
        dfo = L[16]

        # 缩略图参数
        thumb_h = 40
        thumb_spacing = 4
        margin = 4
        c.configure(height=thumb_h + 20)

        # 解码并缩放所有帧
        for fi in range(total_frames):
            pil_img = self._preview_get_pil(src, block_idx, fi)
            if pil_img is None:
                continue
            w, h = pil_img.size
            if h <= 0:
                continue
            ratio = thumb_h / h
            tw = max(1, int(w * ratio))
            thumb = pil_img.resize((tw, thumb_h), Image.NEAREST)
            tk_img = ImageTk.PhotoImage(thumb)
            self._thumb_images.append(tk_img)

            x = margin + fi * (thumb_h + thumb_spacing)
            c.create_image(x, 8, image=tk_img, anchor='nw',
                           tags=('thumb', f'frame_{fi}'))

        if not self._thumb_images:
            return

        # 总宽度
        total_w = margin + total_frames * (thumb_h + thumb_spacing)
        c.configure(scrollregion=(0, 0, total_w, thumb_h + 20))

        # 方向帧偏移标记
        if dfo > 0:
            for di in range(0, total_frames, dfo):
                x = margin + di * (thumb_h + thumb_spacing)
                c.create_line(x, thumb_h + 8, x, thumb_h + 16,
                              fill='#3498db', width=1, tags='dfo')
                c.create_text(x, thumb_h + 18, text=str(di),
                              font=('', 6), fill='#3498db', anchor='n', tags='dfo')

        # 高亮选中范围 [first..last]
        fx = margin + first * (thumb_h + thumb_spacing) - 1
        lx = margin + last * (thumb_h + thumb_spacing) + thumb_h + 1
        c.create_rectangle(fx, 6, lx, thumb_h + 10,
                           outline='#e74c3c', width=2, tags='selection')
        c.create_text(fx + 2, 8, text=f"first={first}",
                      font=('', 7, 'bold'), fill='#e74c3c', anchor='nw',
                      tags='selection')
        c.create_text(lx - 2, 8, text=f"last={last}",
                      font=('', 7, 'bold'), fill='#e74c3c', anchor='ne',
                      tags='selection')

        # 点击缩略图选择帧范围
        _thumb_state = {'anchor': None}  # 闭包内保存 Shift+点击锚点

        def _on_thumb_click(e):
            fi = int((c.canvasx(e.x) - margin) / (thumb_h + thumb_spacing) + 0.5)
            fi = max(0, min(total_frames - 1, fi))

            if e.state & 0x1:  # Shift+点击 → 扩展范围
                if _thumb_state['anchor'] is not None:
                    L[17] = min(_thumb_state['anchor'], fi)
                    L[18] = max(_thumb_state['anchor'], fi)
            else:
                # 普通点击 → 设置锚点并定位到该帧
                _thumb_state['anchor'] = fi
                L[17] = fi
                L[18] = fi

            self._dirty = True
            self._populate_layer(display_layer, L)
            self._tl_redraw()
            self._preview_stop()
            self._preview_tick_idx = 0
            self._preview_redraw()
            # 刷新缩略图高亮(不重建绑定)
            self._tl_draw_thumb_selection(L[17], L[18], total_frames, dfo)

        c.bind("<Button-1>", _on_thumb_click)

    def _tl_draw_thumb_selection(self, first, last, total_frames, dfo=0):
        """轻量刷新: 仅更新缩略图选中框 (不解码帧, 不重建绑定)"""
        c = self._thumb_canvas
        c.delete('selection')
        thumb_h = 40
        thumb_spacing = 4
        margin = 4
        fx = margin + first * (thumb_h + thumb_spacing) - 1
        lx = margin + last * (thumb_h + thumb_spacing) + thumb_h + 1
        c.create_rectangle(fx, 6, lx, thumb_h + 10,
                           outline='#e74c3c', width=2, tags='selection')
        c.create_text(fx + 2, 8, text=f"first={first}",
                      font=('', 7, 'bold'), fill='#e74c3c', anchor='nw',
                      tags='selection')
        c.create_text(lx - 2, 8, text=f"last={last}",
                      font=('', 7, 'bold'), fill='#e74c3c', anchor='ne',
                      tags='selection')

    def _render_field_group(self, parent, fields, vars_row):
        """在 parent 内以每行 4 列网格渲染字段"""
        row = 0
        col = 0
        per_row = 4
        for (fn, idx, label, width, comment) in fields:
            if fn == 'layer_type':
                # 已在 head 单独渲染
                continue
            cell = ttk.Frame(parent)
            cell.grid(row=row, column=col, sticky='w', padx=4, pady=1)
            is_ro = fn in READONLY_KEYS

            lbl = ttk.Label(cell, text=f"{label}  [{idx}]", font=FONT_S,
                            foreground=('#AAA' if is_ro else '#444'))
            lbl.pack(anchor=tk.W)
            self._bind_tooltip(lbl, comment)

            sv = tk.StringVar()
            vars_row[fn] = sv

            # 下拉候选 (枚举字段)
            if fn == 'blend_mode':
                combo = ttk.Combobox(cell, textvariable=sv,
                                     values=list(BLEND_MODE_LABELS.values()),
                                     width=22, font=FONT)
                combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                vars_row[f'_{fn}_combo'] = combo
            elif fn == 'direction_mode':
                combo = ttk.Combobox(cell, textvariable=sv,
                                     values=list(DIRECTION_MODE_LABELS.values()),
                                     width=14, font=FONT)
                combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                vars_row[f'_{fn}_combo'] = combo
            elif fn == 'loop_behavior':
                combo = ttk.Combobox(cell, textvariable=sv,
                                     values=list(LOOP_BEHAVIOR_LABELS.values()),
                                     width=22, font=FONT)
                combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                vars_row[f'_{fn}_combo'] = combo
            elif fn == 'move_mode':
                combo = ttk.Combobox(cell, textvariable=sv,
                                     values=list(MOVE_MODE_LABELS.values()),
                                     width=14, font=FONT)
                combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                vars_row[f'_{fn}_combo'] = combo
            else:
                ent = ttk.Entry(cell, textvariable=sv, width=width, font=FONT)
                if is_ro:
                    ent.configure(state='readonly', foreground='#AAA')
                ent.pack(side=tk.LEFT, fill=tk.X, expand=True)

            col += 1
            if col >= per_row:
                col = 0
                row += 1

    # -------- Tab: 条目级参数 --------

    def _build_param_ui(self):
        """条目级参数区 (bytes 32-79, int16[16..39], 共 24 项)"""
        main = ttk.Frame(self.param_frame, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="条目级参数区 (bytes 32-79, int16[16..39], 共 24 项)。\n"
                 "★ [18] 疑似总 tick;  [20/22/24/…] 疑似每激活图层的 tick 配额;  其余多为 0。",
            font=FONT_S, foreground='#666', justify='left'
        ).pack(anchor=tk.W, pady=(0, 6))

        grid = ttk.Frame(main)
        grid.pack(anchor=tk.W)

        self._param_vars = []
        for k, idx in enumerate(range(16, 40)):
            row = k // 6
            col = k % 6
            cell = ttk.Frame(grid)
            cell.grid(row=row, column=col, sticky='w', padx=3, pady=2)

            hint = ""
            if idx == 18:
                hint = " 总tick?"
            elif idx in (20, 22, 24, 26, 28):
                hint = " 图层tick?"
            ttk.Label(cell, text=f"[{idx:2d}]{hint}", font=FONT_S,
                      foreground='#888').pack(anchor=tk.W)
            sv = tk.StringVar()
            self._param_vars.append(sv)
            ent = ttk.Entry(cell, textvariable=sv, width=8, font=FONT)
            ent.pack(side=tk.LEFT)
            self._bind_tooltip(
                ent, f"int16[{idx}] = bytes {idx*2}..{idx*2+1}")

    # -------- Tab: 尾部 (16 对) = 音效触发表 --------

    def _build_tail_ui(self):
        main = ttk.Frame(self.tail_frame, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="尾部 (bytes 720-783) = 音效触发表  16 对 × (sound_id, trigger_tick)\n"
                 "逆向证据: sub_4434BC L111-119 对 &unk_9D064A 逐对 sub_451780(1) 预加载;\n"
                 "          L627-636 每 tick 检查 v5[1] == word_9D03A0 时 sub_451C38(0) 播放.\n"
                 "音效路径: sound\\%04d.wav (sub_451780 L56); 实测目录为 .mp3 时编辑器自动兼容.\n"
                 "sound_id = 0 表示该对空位 (不触发).",
            font=FONT_S, foreground='#666', justify='left'
        ).pack(anchor=tk.W, pady=(0, 6))

        canvas = tk.Canvas(main, highlightthickness=0)
        sb = ttk.Scrollbar(main, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>',
                   lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(inner, text="#", font=FONT_B, width=3).grid(
            row=0, column=0, padx=2)
        ttk.Label(inner, text="sound_id", font=FONT_B, width=9).grid(
            row=0, column=1, padx=2)
        ttk.Label(inner, text="trigger_tick", font=FONT_B, width=11).grid(
            row=0, column=2, padx=2)
        ttk.Label(inner, text="", font=FONT_B, width=3).grid(
            row=0, column=3, padx=2)
        ttk.Label(inner, text="文件", font=FONT_B, width=20).grid(
            row=0, column=4, padx=4, sticky='w')
        ttk.Label(inner, text="原 int16", font=FONT_S,
                  foreground='#999').grid(row=0, column=5, padx=8, sticky='w')

        self._tail_vars = []      # 平铺 32 个 StringVar
        self._tail_file_lbls = []  # 每对的文件状态标签 (sound_id 变化时刷新)
        for pair in range(16):
            r = pair + 1
            ttk.Label(inner, text=f"{pair:02d}", font=FONT_S,
                      foreground='#666').grid(row=r, column=0, padx=2)
            v_var = tk.StringVar()
            c_var = tk.StringVar()
            self._tail_vars.append(v_var)   # 偶数: sound_id
            self._tail_vars.append(c_var)   # 奇数: trigger_tick
            id_ent = ttk.Entry(inner, textvariable=v_var, width=8,
                               font=FONT)
            id_ent.grid(row=r, column=1, padx=2)
            tick_ent = ttk.Entry(inner, textvariable=c_var, width=10,
                                 font=FONT)
            tick_ent.grid(row=r, column=2, padx=2)
            # 试听按钮
            btn = ttk.Button(inner, text="▶",
                             width=2,
                             command=lambda idx=pair: self._on_tail_preview(idx))
            btn.grid(row=r, column=3, padx=1)
            self._bind_tooltip(btn, "试听此 sound_id 对应的音效文件")
            # 文件状态标签
            fl = ttk.Label(inner, text="", font=FONT_S, foreground='#999',
                           anchor='w', width=24)
            fl.grid(row=r, column=4, padx=4, sticky='w')
            self._tail_file_lbls.append(fl)
            ttk.Label(inner, text=f"[{pair*2}], [{pair*2+1}]",
                      font=FONT_S, foreground='#AAA').grid(
                row=r, column=5, padx=8, sticky='w')
            # sound_id 变化时刷新文件标签
            v_var.trace_add('write',
                            lambda *a, idx=pair: self._refresh_tail_file_lbl(idx))

    def _refresh_tail_file_lbl(self, pair_idx):
        """根据 sound_id 刷新该对的文件标签 (SWS.GRP)"""
        if pair_idx >= len(self._tail_file_lbls):
            return
        lbl = self._tail_file_lbls[pair_idx]
        try:
            sid = int(self._tail_vars[pair_idx * 2].get() or 0)
        except ValueError:
            sid = 0
        if sid <= 0:
            lbl.config(text="(空位)", foreground='#AAA')
            return
        if self.sws_grp is None:
            lbl.config(text=f"SWS#{sid:04d}  (未加载 TKS 目录)",
                       foreground='#C60')
            return
        info = self.sws_grp.wav_info(sid)
        if info is not None:
            ch, sr, bits, dur = info
            lbl.config(
                text=(f"SWS#{sid:03d}  {ch}ch {sr}Hz {bits}bit "
                      f"{dur:.2f}s"),
                foreground='#093')
            return
        if sid >= self.sws_grp.section_count:
            lbl.config(
                text=f"SWS#{sid}  X 超出段数({self.sws_grp.section_count})",
                foreground='#C33')
            return
        lbl.config(text=f"SWS#{sid:03d}  (非 WAV 段)", foreground='#C60')

    def _resolve_sound_path(self, sid):
        """解析 sound_id -> 可播放的 .wav 本地路径 (SWS.GRP)."""
        if sid <= 0 or self.sws_grp is None:
            return None
        return self.sws_grp.extract_to_temp(sid)

    def _on_tail_preview(self, pair_idx):
        """试听按钮: 播放该对 sound_id 指向的音效 (SWS.GRP)"""
        try:
            sid = int(self._tail_vars[pair_idx * 2].get() or 0)
        except ValueError:
            sid = 0
        if sid <= 0:
            self.status_var.set(f"尾部 #{pair_idx:02d}: sound_id=0 空位, 无音效")
            return
        if self.sws_grp is None:
            messagebox.showinfo(
                "未加载音效源",
                "请先通过 文件 -> 加载 TKS 目录 来定位 SWS.GRP")
            return
        p = self._resolve_sound_path(sid)
        if not p:
            self.status_var.set(f"未找到音效 sid={sid} (SWS.GRP)")
            return
        alias = _mci_play_async(p)
        if alias is None:
            self.status_var.set(f"播放失败: sid={sid}")
        else:
            self.status_var.set(f"> sid={sid} (SWS)")


    # -------- 通用辅助 --------

    def _bind_tooltip(self, widget, text):
        tip = {'win': None}

        def _enter(e):
            if tip['win']:
                return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid',
                      borderwidth=1, font=FONT_S, wraplength=480,
                      padding=3).pack()
            tip['win'] = w

        def _leave(e):
            if tip['win']:
                tip['win'].destroy()
                tip['win'] = None

        widget.bind('<Enter>', _enter)
        widget.bind('<Leave>', _leave)

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children():
            self._set_ws(c, en)
        for tab_id in self.nb.tabs():
            tab = self.nb.nametowidget(tab_id)
            for c in tab.winfo_children():
                self._set_ws(c, en)

    def _set_ws(self, w, en):
        try:
            if isinstance(w, (ttk.Entry, ttk.Spinbox)):
                w.configure(state='normal' if en else 'disabled')
            elif isinstance(w, ttk.Combobox):
                w.configure(state='readonly' if en else 'disabled')
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton,
                                ttk.Button)):
                w.state(['!disabled'] if en else ['disabled'])
        except Exception:
            pass
        for c in w.winfo_children():
            self._set_ws(c, en)

    @staticmethod
    def _enum_to_label(value, label_map):
        return label_map.get(value, f"{value} (未知)")

    @staticmethod
    def _label_to_enum(label, label_map):
        for k, v in label_map.items():
            if v == label:
                return k
        try:
            return int((label or '0').strip().split()[0])
        except Exception:
            return 0

    # ----------- 数据加载 -----------

    def _load_tks_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d:
            return
        act = os.path.join(d, "TKAct.dat")
        # Aa.jvg / Af.jvg 才是 ACT 图层的实际贴图源
        # 先尝试常见大小写组合 (Windows 文件系统不区分, 但用 exists() 更安全)
        def _pick(*names):
            for n in names:
                p = os.path.join(d, n)
                if os.path.exists(p):
                    return p
            return None
        aa = _pick("Aa.jvg", "Aa.JVG", "aa.jvg")
        af = _pick("Af.jvg", "Af.JVG", "af.jvg")
        # SWS.GRP + SWS.IDX = 实际运行时音效源 (sub_451780 A2C22C=1 分支)
        sws_path = _pick("SWS.GRP", "SWS.grp", "sws.grp")
        swi_path = _pick("SWS.IDX", "SWS.idx", "sws.idx")
        sws = None
        if sws_path and swi_path:
            tmp = _SWSGrp(sws_path, swi_path)
            if tmp.load_index() > 0:
                sws = tmp
        if not os.path.exists(act):
            messagebox.showwarning("文件缺失", "未找到 TKAct.dat")
            return
        self.act_path = act
        self.aa_path = aa
        self.af_path = af
        self.sws_grp = sws
        self._reload()

    def _reload(self):
        if not self.act_path:
            return
        self._preview_stop()
        self._aa_data = None
        self._af_data = None
        self._jvg_cache.clear()
        self._pil_cache.clear()
        self.status_var.set("加载中…")
        self.root.update()
        try:
            self.entries = load_act(self.act_path)
            self._dirty = False
            nonempty = sum(1 for e in self.entries if not entry_is_empty(e))
            self.status_var.set(
                f"{len(self.entries)} 条 (784 字节/条) | 非空 {nonempty}")
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            self.entries = []
        self._set_edit_enabled(True)
        self._update_path()
        self._apply_filter()

    def _update_path(self):
        g, r = "#228B22", "#CC3333"
        if not self.act_path:
            self.lbl_path.config(text="TKAct: (未加载)", foreground=r)
        else:
            self.lbl_path.config(text=f"TKAct: {self.act_path}", foreground=g)
        # 探针: _LazyJvgReader 扫描 JVG 头部获取 block 帧数 (不解码像素)
        if self.aa_path and not self._aa_counts:
            r = _LazyJvgReader(self.aa_path)
            if r.valid:
                self._aa_counts = r.frame_counts
        if self.af_path and not self._af_counts:
            r = _LazyJvgReader(self.af_path)
            if r.valid:
                self._af_counts = r.frame_counts
        aa_note = (f"{len(self._aa_counts)} blocks"
                   if self._aa_counts else "✗")
        af_note = (f"{len(self._af_counts)} blocks"
                   if self._af_counts else "✗")
        # SWS.GRP 状态 (主音效源)
        if self.sws_grp is not None:
            sws_note = f"{self.sws_grp.section_count} 段"
        else:
            sws_note = "✗"
        self.lbl_jvg.config(
            text=(f"Aa.jvg (主角动作): {aa_note}   |   "
                  f"Af.jvg (特效/物件): {af_note}   |   "
                  f"SWS.GRP: {sws_note}"),
            foreground=g if (self._aa_counts or self._af_counts) else r)

    # ----------- 筛选/列表 -----------

    def _apply_filter(self):
        q = self.sv.get().strip().lower()
        self.filtered_indices = []
        for entry in self.entries:
            if not self.show_empty.get() and entry_is_empty(entry):
                continue
            if q:
                text = f"{entry['index']} {entry_summary(entry)}".lower()
                if q not in text:
                    continue
            self.filtered_indices.append(entry['index'])
        self._refresh_table()
        nonempty = sum(1 for e in self.entries if not entry_is_empty(e))
        msg = (f"显示 {len(self.filtered_indices)}/{ACT_ENTRY_COUNT} "
               f"(非空 {nonempty}) | Ctrl+S 保存")
        if self._dirty:
            msg += " [已修改]"
        self.status_var.set(msg)

    def _clear_filter(self):
        self.sv.set("")
        self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
        for idx in self.filtered_indices:
            entry = self.entries[idx]
            n_layer = len(entry_active_layers(entry))
            has_data = not entry_is_empty(entry)
            tags = ['active'] if has_data else ['empty']
            self.tree.insert('', 'end',
                             values=(entry['index'],
                                     entry_summary(entry), n_layer),
                             tags=tags)

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 'summary':
            self.filtered_indices.sort(
                key=lambda i: entry_summary(self.entries[i]).lower(),
                reverse=rev)
        elif col == 'n_layer':
            self.filtered_indices.sort(
                key=lambda i: len(entry_active_layers(self.entries[i])),
                reverse=rev)
        else:
            self.filtered_indices.sort(reverse=rev)
        self._sort_reverse = not rev
        self._refresh_table()

    # ----------- 编辑 -----------

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(self.tree.item(sel[0])['values'][0])
        # 保存编辑前快照 (用于重置)
        entry = self.entries[idx]
        self._edit_snapshot = {
            'dirs': [list(d) for d in entry['dirs']],
            'param16': list(entry['param16']),
            'layers': [list(L) for L in entry['layers']],
            'tail': list(entry['tail']),
        }
        self._populate_edit(entry)

    def _populate_edit(self, entry):
        self._editing_idx = entry['index']
        active = sorted(entry_active_layers(entry))
        refd = sorted(entry_referenced_layers(entry))
        self.lbl_entry.config(
            text=(f"动画 #{entry['index']}   "
                  f"活跃图层 {active if active else '(空)'}   "
                  f"方向表引用 {refd if refd else '(无)'}"))

        for d in range(4):
            for i in range(8):
                self._dir_vars[d][i].set(str(entry['dirs'][d][i]))

        for s in range(ACT_MAX_LAYER):
            self._populate_layer(s, entry['layers'][s])

        for k in range(24):
            self._param_vars[k].set(str(entry['param16'][k]))

        for k in range(32):
            self._tail_vars[k].set(str(entry['tail'][k]))

        for s in range(ACT_MAX_LAYER):
            t = entry['layers'][s][0]
            lbl = self._layer_vars[s].get('_card_label')
            if lbl is not None:
                if t == 0:
                    lbl.config(text=f"#{s+1} (空)", foreground='#888')
                else:
                    full = LAYER_TYPE_LABELS.get(t, str(t))
                    parts = full.split(' ', 1)
                    lab = (parts[1].split('(')[0].strip()
                           if len(parts) > 1 else full)
                    lbl.config(text=f"#{s+1} {lab}", foreground='#000')

        self._preview_reload()
        self._tl_redraw()

    def _populate_layer(self, layer_idx, vals):
        self._auto_fill_enabled = False  # 加载数据时禁止自动填充
        vars_row = self._layer_vars[layer_idx]
        t = vals[0]
        combo = vars_row.get('_type_combo')
        if combo is not None:
            combo.set(self._enum_to_label(t, LAYER_TYPE_LABELS))
        vars_row['layer_type'].set(str(t))

        for (fn, idx, _, _, _) in ALL_FIELDS:
            if fn == 'layer_type' or fn not in vars_row:
                continue
            v = vals[idx]
            if fn == 'blend_mode':
                vars_row[fn].set(self._enum_to_label(v, BLEND_MODE_LABELS))
            elif fn == 'direction_mode':
                vars_row[fn].set(self._enum_to_label(v, DIRECTION_MODE_LABELS))
            elif fn == 'loop_behavior':
                vars_row[fn].set(self._enum_to_label(v, LOOP_BEHAVIOR_LABELS))
            elif fn == 'move_mode':
                vars_row[fn].set(self._enum_to_label(v, MOVE_MODE_LABELS))
            else:
                vars_row[fn].set(str(v))

        self._auto_fill_enabled = True
        self._update_layer_probe(layer_idx)
        # 更新紧凑卡片帧范围标签
        fl = vars_row.get('_frame_lbl')
        if fl is not None:
            fl.config(text=f"[{vals[17]}..{vals[18]}]")

    # ----------- JVG 帧数探针 -----------

    def _update_layer_probe(self, layer_idx):
        """刷新指定图层的探针标签: 显示 JVG 实际帧数、推断布局、ACT 切片比例"""
        vars_row = self._layer_vars[layer_idx]
        lbl = vars_row.get('_probe_lbl')
        if lbl is None:
            return

        def _iv(key, default=0):
            try:
                raw = vars_row[key].get() if key in vars_row else ''
                # 枚举字段 (如 direction_mode) 取前缀数字
                raw = raw.split(' ', 1)[0] if raw else ''
                return int(raw) if raw.lstrip('-').isdigit() else default
            except Exception:
                return default

        # layer_type 直接从 combo 取
        combo = vars_row.get('_type_combo')
        type_lbl = combo.get() if combo else ''
        try:
            ltype = int(type_lbl.split(' ', 1)[0]) if type_lbl else 0
        except Exception:
            ltype = 0

        blk = _iv('jvg_block_index', -1)
        dfo = _iv('dir_frame_offset', 0)
        first = _iv('first_frame', 0)
        last = _iv('last_frame', 0)
        dmode = _iv('direction_mode', 0)

        # 空图层
        if ltype == 0:
            lbl.config(text="— (空图层)", foreground='#AAA')
            return

        # 非渲染图层
        if ltype >= 4:
            name = {4: '坐标锚点', 5: '结束标记'}.get(ltype, '非渲染')
            lbl.config(text=f"— {name} (无 JVG 引用)", foreground='#AAA')
            return

        # 选择 JVG 源 (sub_4434BC: type==1 用 dword_951924=Aa.jvg, 否则 dword_951930=Af.jvg)
        if ltype == 1:
            src_name, counts = 'Aa.jvg', self._aa_counts
        else:
            src_name, counts = 'Af.jvg', self._af_counts

        if not counts:
            lbl.config(
                text=f"{src_name}[{blk}]  (未加载 JVG, 无法探测实际帧数)",
                foreground='#C60')
            return
        if blk < 0 or blk >= len(counts):
            lbl.config(
                text=f"{src_name}[{blk}]  ✗ 块号越界 (共 {len(counts)} 块)",
                foreground='#C33')
            return

        n_frames = counts[blk]
        dirs, per, is_std = infer_jvg_layout(n_frames)

        # ACT 切片窗口 (方向内帧范围)
        per_dir_act = (last - first + 1) if last >= first else 0
        # 全部方向下读取到的帧号范围 (dmode=4 时跨 4 向, 否则仅方向 0)
        if dmode == 4:
            read_max = last + dfo * 3
            span_desc = f"方向 0: {first}..{last}  方向 3: {first+dfo*3}..{read_max}"
            used = per_dir_act * 4
        else:
            read_max = last
            span_desc = f"方向 0 (固定): {first}..{last}"
            used = per_dir_act

        pct = (used * 100 // n_frames) if n_frames > 0 else 0
        tag = '✓' if is_std else '·'
        layout_desc = f"{tag} 推断 {dirs}向×{per}帧"

        # 告警: 只标识"一定是错的"情况 (方向 0 单向就越界)
        warn = ''
        if last >= n_frames or first < 0:
            warn = f"  ⚠ 方向 0 切片 {first}..{last} 越出池 0..{n_frames-1}"

        # 信息提示 (不标红): dfo 与推断不符
        info = ''
        if is_std and dfo > 0 and dfo != per and dmode == 4:
            info = f"  (dfo={dfo} ≠ 推断 {per}, 非标准切片)"

        if warn:
            color = '#C33'
        elif is_std and not info:
            color = '#093'
        else:
            color = '#456'

        lbl.config(
            text=(f"{src_name}[{blk}]  实际 {n_frames} 帧   {layout_desc}{info}\n"
                  f"    {span_desc}   切片量 {used}/{n_frames} ({pct}%){warn}"),
            foreground=color)

    def _on_layer_field_change(self, layer_idx, field_name):
        """图层字段变更回调: 刷新探针; jvg_block_index 变更时自动填充帧参数."""
        self._update_layer_probe(layer_idx)
        if (field_name == 'jvg_block_index'
                and getattr(self, '_auto_fill_enabled', True)):
            self._auto_fill_jvg_params(layer_idx)

    def _auto_fill_jvg_params(self, layer_idx):
        """根据 jvg_block_index 自动填充方向/帧参数 (默认 4 方向布局).
        例如 block #116 共 48 帧 → 48/4=12 → first=0, last=11, dfo=12,
        direction_mode=4."""
        vr = self._layer_vars[layer_idx]

        # 读取当前 jvg_block_index
        try:
            blk = int((vr.get('jvg_block_index', tk.StringVar()).get() or '0'))
        except (ValueError, AttributeError):
            return
        if blk <= 0:
            return

        # 从 layer_type 确定 JVG 来源
        combo = vr.get('_type_combo')
        type_str = combo.get() if combo else ''
        try:
            ltype = int(type_str.split(' ', 1)[0]) if type_str else 0
        except ValueError:
            ltype = 0
        if ltype == 1:
            counts = self._aa_counts
        elif ltype in (2, 3):
            counts = self._af_counts
        else:
            return

        if not counts or blk >= len(counts):
            return
        n_frames = counts[blk]
        if n_frames <= 0:
            return

        # 推断布局: 优先 4 方向, 否则 2 方向, 否则 1 方向
        dirs, per, _ = infer_jvg_layout(n_frames)
        if dirs < 1:
            return

        # 自动填充 (loop 默认为 last_frame, 即播完后停在末帧)
        if 'direction_mode' in vr:
            vr['direction_mode'].set(f'{dirs} {"四向感知" if dirs == 4 else "双向感知" if dirs == 2 else f"{dirs}向"}')
        if 'first_frame' in vr:
            vr['first_frame'].set('0')
        if 'last_frame' in vr:
            vr['last_frame'].set(str(per - 1))
        if 'dir_frame_offset' in vr:
            vr['dir_frame_offset'].set(str(per))
        if 'loop_behavior' in vr:
            vr['loop_behavior'].set(str(per - 1))

        self._update_layer_probe(layer_idx)

    def _apply_edit(self):
        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]

        for d in range(4):
            for i in range(8):
                try:
                    v = int(self._dir_vars[d][i].get() or 0)
                except ValueError:
                    v = 0
                entry['dirs'][d][i] = max(0, min(255, v))

        for s in range(ACT_MAX_LAYER):
            vals = entry['layers'][s]
            vars_row = self._layer_vars[s]
            combo = vars_row.get('_type_combo')
            if combo is not None:
                vals[0] = self._label_to_enum(combo.get(), LAYER_TYPE_LABELS)

            for (fn, idx, _, _, _) in ALL_FIELDS:
                if fn == 'layer_type' or fn not in vars_row:
                    continue
                raw = vars_row[fn].get()
                if fn == 'blend_mode':
                    v = self._label_to_enum(raw, BLEND_MODE_LABELS)
                elif fn == 'direction_mode':
                    v = self._label_to_enum(raw, DIRECTION_MODE_LABELS)
                elif fn == 'loop_behavior':
                    v = self._label_to_enum(raw, LOOP_BEHAVIOR_LABELS)
                elif fn == 'move_mode':
                    v = self._label_to_enum(raw, MOVE_MODE_LABELS)
                else:
                    try:
                        v = int((raw or '0').strip())
                    except ValueError:
                        v = 0
                vals[idx] = max(-32768, min(32767, v))

        for k in range(24):
            try:
                v = int(self._param_vars[k].get() or 0)
            except ValueError:
                v = 0
            entry['param16'][k] = max(-32768, min(32767, v))

        for k in range(32):
            try:
                v = int(self._tail_vars[k].get() or 0)
            except ValueError:
                v = 0
            entry['tail'][k] = max(-32768, min(32767, v))

        self._dirty = True
        self._apply_filter()
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == entry['index']:
                self.tree.selection_set(child)
                self.tree.see(child)
                break
        self._populate_edit(entry)
        self.status_var.set(f"动画 #{entry['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        """恢复到编辑前的快照状态 (含图层可见性)"""
        if self._editing_idx is not None and self._edit_snapshot is not None:
            snap = self._edit_snapshot
            entry = self.entries[self._editing_idx]
            entry['dirs'] = [list(d) for d in snap['dirs']]
            entry['param16'] = list(snap['param16'])
            entry['layers'] = [list(L) for L in snap['layers']]
            entry['tail'] = list(snap['tail'])
            self._dirty = False
            self._preview_vis_vars.clear()  # 重置可见性
            self._populate_edit(entry)
            self.status_var.set("已重置为编辑前的状态")

    def _copy_entry(self):
        if self._editing_idx is None:
            return
        src = self.entries[self._editing_idx]
        if entry_is_empty(src):
            messagebox.showinfo("提示", "当前条目为空, 无需复制")
            return
        for entry in self.entries:
            if entry_is_empty(entry):
                idx_bak = entry['index']
                entry['dirs'] = [list(d) for d in src['dirs']]
                entry['param16'] = list(src['param16'])
                entry['layers'] = [list(L) for L in src['layers']]
                entry['tail'] = list(src['tail'])
                entry['index'] = idx_bak
                self._dirty = True
                self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == idx_bak:
                        self.tree.selection_set(child)
                        self.tree.see(child)
                        break
                self._populate_edit(entry)
                self.status_var.set(
                    f"已复制 #{src['index']} → #{idx_bak}")
                return
        messagebox.showwarning("槽位已满",
                               f"所有 {ACT_ENTRY_COUNT} 个条目均已占用")

    def _clear_entry(self):
        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]
        if entry_is_empty(entry):
            messagebox.showinfo("提示", "当前条目已经为空")
            return
        if not messagebox.askyesno("确认清空",
                                   f"确定清空动画 #{entry['index']}?"):
            return
        idx_save = entry['index']
        self.entries[idx_save] = {
            'index': idx_save,
            'dirs': [[0] * 8 for _ in range(4)],
            'param16': [0] * 24,
            'layers': [[0] * 40 for _ in range(ACT_MAX_LAYER)],
            'tail': [0] * 32,
        }
        self._dirty = True
        self._apply_filter()
        self._populate_edit(self.entries[idx_save])
        self.status_var.set(f"已清空动画 #{idx_save}")

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.act_path or not self.entries:
            messagebox.showinfo("提示", "请先加载数据")
            return
        if not messagebox.askyesno(
                "确认保存",
                f"保存 {len(self.entries)} 条到:\n{self.act_path}\n\n"
                f"原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.act_path, 'rb') as s:
                with open(self.act_path + ".bak", 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass
        try:
            self.status_var.set("正在保存…")
            self.root.update()
            save_act(self.act_path, self.entries)
            self._dirty = False
            self.status_var.set(f"已保存 → {self.act_path}")
            messagebox.showinfo("保存成功",
                                f"已保存\n备份: {self.act_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.entries:
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p:
            return
        with open(p, 'w', encoding='utf-8-sig') as f:
            cols = ['动画#', '图层组成']
            for s in range(1, ACT_MAX_LAYER + 1):
                for (fn, _, _, _, _) in ALL_FIELDS:
                    cols.append(f"L{s}_{fn}")
            f.write(','.join(cols) + '\n')
            for entry in self.entries:
                if entry_is_empty(entry):
                    continue
                row = [str(entry['index']), entry_summary(entry)]
                for s in range(ACT_MAX_LAYER):
                    L = entry['layers'][s]
                    for (_, idx, _, _, _) in ALL_FIELDS:
                        row.append(str(L[idx]))
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ============================================================
    # 动画预览 (遵循 sub_4434BC 语义)
    # ============================================================

    def _preview_active_layers(self, direction):
        """按方向表的 z-order 返回 (slot, eff_dir, layer_vals): 底层→顶层"""
        entry = self.entries[self._editing_idx]
        order = [v for v in entry['dirs'][direction % 4] if v]
        if not order:
            order = sorted(entry_active_layers(entry))
        out = []
        for slot in order:
            if slot < 1 or slot > ACT_MAX_LAYER:
                continue
            L = entry['layers'][slot - 1]
            if L[0] == 0:
                continue
            eff_dir = direction if (L[2] == 4 or L[0] < 3) else 0
            out.append((slot, eff_dir, L))
        return out

    def _preview_load_jvg(self):
        """按需加载 JVG 索引 (只扫描头部, 不解码像素)"""
        if not HAS_PIL:
            return False
        if _get_jvg_loader() is None:
            return False
        try:
            if self.aa_path and not self._aa_data:
                r = _LazyJvgReader(self.aa_path)
                if r.valid:
                    self._aa_data = r
                    self._aa_counts = r.frame_counts
            if self.af_path and not self._af_data:
                r = _LazyJvgReader(self.af_path)
                if r.valid:
                    self._af_data = r
                    self._af_counts = r.frame_counts
        except Exception:
            pass
        return (self._aa_data is not None) or (self._af_data is not None)

    def _preview_get_frame(self, src, block_idx, frame_idx):
        key = (src, block_idx, frame_idx)
        cached = self._jvg_cache.get(key)
        if cached is not None:
            return cached
        jvg = self._aa_data if src == 'aa' else self._af_data
        if jvg is None or block_idx < 0 or block_idx >= jvg.block_count:
            return None
        blk = jvg.get_block(block_idx)
        if frame_idx < 0 or frame_idx >= blk.frame_count:
            return None
        f = blk.frames[frame_idx]
        if f.width <= 0 or f.height <= 0:
            return None
        pal_rgb = blk.palette.to_rgb888()
        rgba = bytearray(f.width * f.height * 4)
        for py in range(f.height):
            base = py * f.width
            for px in range(f.width):
                p = base + px
                if p < len(f.alpha) and f.alpha[p] == 0:
                    continue
                idx = f.pixels[p] if p < len(f.pixels) else 0
                o = p * 4
                rgba[o] = pal_rgb[idx * 3]
                rgba[o + 1] = pal_rgb[idx * 3 + 1]
                rgba[o + 2] = pal_rgb[idx * 3 + 2]
                rgba[o + 3] = 255
        try:
            img = Image.frombytes('RGBA', (f.width, f.height), bytes(rgba))
            tk_img = ImageTk.PhotoImage(img)
            res = (tk_img, f, blk)
            self._jvg_cache[key] = res
            return res
        except Exception:
            return None

    def _preview_get_pil(self, src, block_idx, frame_idx):
        """返回原始 PIL RGBA Image (未经混合/缩放), 供 _preview_redraw 作为
        混合/缩放的输入. (src, block, frame) 为缓存键."""
        key = (src, block_idx, frame_idx)
        cached = self._pil_cache.get(key)
        if cached is not None:
            return cached
        jvg = self._aa_data if src == 'aa' else self._af_data
        if jvg is None or block_idx < 0 or block_idx >= jvg.block_count:
            return None
        blk = jvg.get_block(block_idx)
        if frame_idx < 0 or frame_idx >= blk.frame_count:
            return None
        f = blk.frames[frame_idx]
        if f.width <= 0 or f.height <= 0:
            return None
        pal_rgb = blk.palette.to_rgb888()
        rgba = bytearray(f.width * f.height * 4)
        for py in range(f.height):
            base = py * f.width
            for px in range(f.width):
                p = base + px
                if p < len(f.alpha) and f.alpha[p] == 0:
                    continue
                idx = f.pixels[p] if p < len(f.pixels) else 0
                o = p * 4
                rgba[o] = pal_rgb[idx * 3]
                rgba[o + 1] = pal_rgb[idx * 3 + 1]
                rgba[o + 2] = pal_rgb[idx * 3 + 2]
                rgba[o + 3] = 255
        try:
            img = Image.frombytes('RGBA', (f.width, f.height), bytes(rgba))
            self._pil_cache[key] = img
            return img
        except Exception:
            return None

    def _apply_blend(self, pil_img, mode, param):
        """对 PIL RGBA 图像应用混合模式近似变换 (sub_4434BC +22 switch).

        各 case 在 sub_4434BC 的原始调用 (a6=+24=blend_param, a7=0 除 case1):
          case 0: sub_4544EC(..., -1)                        无 param
          case 1: sub_454D24(..., param, -1)                 a6=param
          case 2: sub_4559D0(..., param, 0, -1)              a6=param, a7=0
          case 3: sub_458020(..., 0, 0, -1)                  ★ a6=a7=0 写死
          case 4: sub_459168(..., -1)                        无 param
          case 5: sub_458D08(..., -1)                        无 param

        ★ v2.4.3 修正: mode=2 是 additive (加法饱和混合, 非 alpha 半透).
        ★ v2.4.4 修正: mode=3/4 之前实现错误, 依据反编译修正:
          mode=3 (sub_45871C L118-134):  per-channel 减法钳 0
              dst.RGB = max(dst.RGB - src.RGB, 0)
              黑色 src 不改变 dst, 亮色 src 压暗 dst → "挖洞变暗"效果
          mode=4 (sub_459854 L109-124):  按 src 亮度的 alpha-blend
              α = word_A3AEB0[src] & 0x1F  # NTSC 灰度 Y=(11R+59G+30B)/100, 取 5-bit
              if α == 0:     dst 不变 (src 黑色跳过)
              elif α > 28:   dst = src (不透明覆盖)
              else:          dst = dst*(32-α)/32 + src*α/32  (α 级 alpha blend)
              亮色强覆盖、暗色弱显现 → 烟雾/光雾/软粒子风格

          mode=2/3/4 都需要访问 dst (背景), 故此处 _apply_blend 仅直通,
          实际混合由 _preview_redraw 合成阶段对应的 _composite_* 方法实现.

        mode=3/4/5 在 ACT 调用点 param 被忽略 (case3 a6=a7=0 固定走阴影分支,
        case4/5 不传 param), 故此处也忽略 param.
        """
        if pil_img is None:
            return None
        if mode == 0 or mode not in (1, 2, 3, 4, 5):
            return pil_img
        # mode=2/3/4 的混合必须访问 dst, 由合成阶段处理; 此处原样返回
        if mode in (2, 3, 4):
            return pil_img

        if mode == 5:
            # 5 水平翻转: sub_458D08 证据为目标指针 -=2 逆写像素
            try:
                return pil_img.transpose(Image.FLIP_LEFT_RIGHT)
            except Exception:
                return pil_img

        # 其余模式均需逐像素操作
        try:
            src = pil_img.tobytes()
        except Exception:
            return pil_img
        buf = bytearray(src)
        n = len(buf) // 4

        if mode == 1:
            # 1 染色: 把 param 视作 tint 色调索引, 无效值 (0 或 >31) 不变色
            p = int(param) & 0xFFFF
            if p == 0 or p > 31:
                return pil_img
            p &= 0x1F
            # 近似色轮: 红 / 黄 / 绿 / 蓝 四段
            if p < 8:
                tr, tg, tb = 255, 0, 0
            elif p < 16:
                tr, tg, tb = 255, 255, 0
            elif p < 24:
                tr, tg, tb = 0, 255, 0
            else:
                tr, tg, tb = 0, 0, 255
            for i in range(n):
                o = i * 4
                if buf[o + 3] == 0:
                    continue
                buf[o]     = (buf[o]     + tr) >> 1
                buf[o + 1] = (buf[o + 1] + tg) >> 1
                buf[o + 2] = (buf[o + 2] + tb) >> 1

        try:
            return Image.frombytes('RGBA', pil_img.size, bytes(buf))
        except Exception:
            return pil_img

    def _composite_additive(self, composite, rgba_src, dx, dy, param):
        """对 composite (RGB) 在 (dx, dy) 处应用 additive 饱和加法, src 透明区域不贡献.

        对应游戏反编译:
          sub_455B98 / sub_456150  (param = 0, 或 > 31 递归到 0):
              dst.RGB = word_A3AD30[dst.RGB + src.RGB]    # = min(dst+src, 31)
          sub_4573A0 / sub_4579D0  (0 < param <= 31):
              src' = word_A39D30[64*param + src.RGB]      # = param*src/32
              dst.RGB = word_A3AD30[dst.RGB + src'.RGB]   # = min(dst+src', 31)

        PIL 实现 (RGB24 空间等价):
          1. 按 sprite 的 alpha 通道生成 "src 贡献图" (alpha=0 位置 RGB→0)
          2. 若 0 < param <= 31: 对贡献图所有通道乘 param/32
          3. 用 ImageChops.add(dst_region, contrib) 做饱和加法
        """
        if composite is None or rgba_src is None:
            return
        sw, sh = rgba_src.size
        cw, ch = composite.size
        # 交集裁剪: sprite 在画布上的可见矩形
        l = max(0, dx)
        t = max(0, dy)
        r = min(cw, dx + sw)
        b = min(ch, dy + sh)
        if r <= l or b <= t:
            return
        # src 内部对应的可见子区域
        sl, st = l - dx, t - dy
        sr, sb = r - dx, b - dy
        try:
            sub = rgba_src.crop((sl, st, sr, sb))
            if sub.mode != 'RGBA':
                sub = sub.convert('RGBA')
            # 用 alpha 作掩膜: alpha=0 位置 RGB 填 0, 其他位置保留原 RGB
            alpha = sub.split()[3]
            src_rgb = sub.convert('RGB')
            zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
            masked = Image.composite(src_rgb, zero_bg, alpha)
            # 可变 alpha 预乘 (对应 sub_4579D0 L117-119 查 A39D30 预乘表)
            try:
                p = int(param)
            except Exception:
                p = 0
            if 0 < p <= 31:
                factor = p / 32.0
                masked = masked.point(lambda v, f=factor: int(v * f))
            # 对 composite 对应矩形做饱和加法 (ImageChops.add = min(a+b, 255))
            dst_crop = composite.crop((l, t, r, b))
            blended = ImageChops.add(dst_crop, masked)
            composite.paste(blended, (l, t))
        except Exception:
            # 加法失败时退化为 alpha 合成, 保证预览不中断
            try:
                composite.paste(rgba_src, (dx, dy), rgba_src)
            except Exception:
                pass

    def _composite_subtract(self, composite, rgba_src, dx, dy):
        """对 composite 在 (dx, dy) 处应用 "减法饱和混合" (sub_45871C).

        游戏反编译 L118-134 per-channel:
            if src.R >= dst.R: v13 = 0       else: v13 = dst.R - src.R
            if src.G >= dst.G: v11 = 0       else: v11 = dst.G - src.G
            if src.B >= dst.B: v9  = 0       else: v9  = dst.B - src.B
            dst = v9 | (32*v11) | (v13<<10)
        等价于: dst.RGB = max(dst - src, 0)  每通道独立  → ImageChops.subtract.

        sprite 透明区 (alpha=0) 的 RGB 必须置 0 (减 0 不改变 dst).
        """
        if composite is None or rgba_src is None:
            return
        sw, sh = rgba_src.size
        cw, ch = composite.size
        l = max(0, dx); t = max(0, dy)
        r = min(cw, dx + sw); b = min(ch, dy + sh)
        if r <= l or b <= t:
            return
        sl, st = l - dx, t - dy
        sr, sb = r - dx, b - dy
        try:
            sub = rgba_src.crop((sl, st, sr, sb))
            if sub.mode != 'RGBA':
                sub = sub.convert('RGBA')
            alpha = sub.split()[3]
            src_rgb = sub.convert('RGB')
            zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
            masked = Image.composite(src_rgb, zero_bg, alpha)
            dst_crop = composite.crop((l, t, r, b))
            blended = ImageChops.subtract(dst_crop, masked)
            composite.paste(blended, (l, t))
        except Exception:
            try:
                composite.paste(rgba_src, (dx, dy), rgba_src)
            except Exception:
                pass

    def _composite_luma_alpha(self, composite, rgba_src, dx, dy):
        """对 composite 在 (dx, dy) 处应用 "按 src 亮度做 alpha blend" (sub_459854).

        游戏反编译 L109-124:
            α = word_A3AEB0[src] & 0x1F      # NTSC 灰度 5-bit (0..31)
            if α == 0:     dst 不变            (src 黑色 → 跳过)
            elif α > 28:   dst = src          (不透明覆盖)
            else:          dst = dst*(32-α)/32 + src*α/32   (α 级 alpha blend)

        word_A3AEB0 在 sub_453554 L63-102 初始化为 Y = (11R+59G+30B)/100.
        此处把 5-bit α 等价映射到 8-bit mask ∈ [0,255] 用 Image.composite 实现:
            mask = 0                   when α_8 == 0 or sprite 透明
            mask = 255                 when α_5 > 28  (即 α_8 > 224)
            mask = α_8                 otherwise      (线性 alpha)
        """
        if composite is None or rgba_src is None:
            return
        sw, sh = rgba_src.size
        cw, ch = composite.size
        l = max(0, dx); t = max(0, dy)
        r = min(cw, dx + sw); b = min(ch, dy + sh)
        if r <= l or b <= t:
            return
        sl, st = l - dx, t - dy
        sr, sb = r - dx, b - dy
        try:
            sub = rgba_src.crop((sl, st, sr, sb))
            if sub.mode != 'RGBA':
                sub = sub.convert('RGBA')
            alpha = sub.split()[3]
            src_rgb = sub.convert('RGB')
            # PIL convert('L') 使用 ITU-R 601-2 luma (0.299R+0.587G+0.114B),
            # 与游戏 (0.30, 0.59, 0.11) 几乎一致 (差 <0.2%), 直接复用.
            luma = src_rgb.convert('L')
            # 构造 mask: 0 → 0, >224 → 255, 其余 → luma 本身
            mask_luma = luma.point(
                lambda v: 0 if v == 0 else (255 if v > 224 else v))
            # 再与 sprite alpha 做"与" (alpha=0 处 mask=0)
            alpha_bin = alpha.point(lambda v: 255 if v > 0 else 0)
            mask = ImageChops.multiply(mask_luma, alpha_bin)
            dst_crop = composite.crop((l, t, r, b))
            # Image.composite(src, dst, mask): out = src*mask/255 + dst*(1-mask/255)
            blended = Image.composite(src_rgb, dst_crop, mask)
            composite.paste(blended, (l, t))
        except Exception:
            try:
                composite.paste(rgba_src, (dx, dy), rgba_src)
            except Exception:
                pass

    def _preview_reload(self):
        self._preview_stop()
        if self._editing_idx is None:
            return
        if not self._aa_data and not self._af_data:
            self._preview_load_jvg()
        self._preview_tick_idx = 0
        self._preview_played_ticks = set()
        # 条目级固定 bbox: 遍历全部方向/全部帧/全部图层算一次外接矩形
        self._preview_bbox = self._compute_entry_bbox(
            self.entries[self._editing_idx])
        self._preview_update_vis()
        self._preview_redraw()

    def _compute_entry_bbox(self, entry):
        """计算条目级固定包围盒 (遍历全部帧取最大外接矩形).
        仅访问 JVG header 字段 (width/height/x_off/y_off), 不触发 RLE 解码,
        故即使逐帧遍历也很快.
        同时纳入原点 (0,0) 和假想敌位置 (PREVIEW_ENEMY_X, 0)."""
        if self._aa_data is None and self._af_data is None:
            return None
        xs = [0, PREVIEW_ENEMY_X]
        ys = [0]
        for direction in range(4):
            order = [v for v in entry['dirs'][direction] if v]
            if not order:
                order = sorted(entry_active_layers(entry))
            for slot in order:
                if slot < 1 or slot > ACT_MAX_LAYER:
                    continue
                L = entry['layers'][slot - 1]
                if L[0] == 0:
                    continue
                src = 'aa' if L[0] == 1 else 'af'
                jvg = self._aa_data if src == 'aa' else self._af_data
                pk = L[1]
                if jvg is None or pk < 0 or pk >= jvg.block_count:
                    continue
                blk = jvg.get_block(pk)
                n = blk.frame_count
                if n <= 0:
                    continue
                eff_dir = direction if (L[2] == 4 or L[0] < 3) else 0
                ox = L[3 + eff_dir]
                oy = L[7 + eff_dir]
                # t=3/t=4 偏移到假想敌 (t=4 游戏中锚点=鼠标格坐标, 预览放敌方)
                base_x = PREVIEW_ENEMY_X if L[0] in (3, 4) else 0
                # 取全部帧的最大外接矩形 (仅 header, 无 RLE)
                for fi in range(n):
                    f = blk.frames[fi]
                    if f.width <= 0 or f.height <= 0:
                        continue
                    l = f.x_off + ox + base_x
                    t = f.y_off + oy
                    r = l + f.width - 1
                    b = t + f.height - 1
                    xs.extend([l, r])
                    ys.extend([t, b])
        if len(xs) < 2 or len(ys) < 2:
            return None
        # 四周加 10px 余量防止边缘裁切
        return (min(xs) - 10, min(ys) - 10, max(xs) + 10, max(ys) + 10)

    def _preview_update_vis(self):
        # 保存现有可见性状态
        saved_vis = {slot: v.get() for slot, v in self._preview_vis_vars.items()}
        for w in self._preview_vis_frame.winfo_children():
            w.destroy()
        self._preview_vis_vars.clear()
        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]
        slots = entry_referenced_layers(entry) | entry_active_layers(entry)
        if not slots:
            return
        for slot in sorted(slots):
            t = entry['layers'][slot - 1][0]
            # 优先恢复之前保存的状态, 否则默认可见
            default_vis = saved_vis.get(slot, True)
            var = tk.BooleanVar(value=default_vis)
            cb = ttk.Checkbutton(self._preview_vis_frame,
                                 text=f"#{slot}(t={t})",
                                 variable=var,
                                 command=self._preview_redraw)
            cb.pack(side=tk.LEFT, padx=1)
            self._preview_vis_vars[slot] = var

    def _preview_play(self):
        if self._editing_idx is None:
            return
        if not self._aa_data and not self._af_data:
            if not self._preview_load_jvg():
                return
        self._preview_stop()
        self._preview_tick_idx = 0
        self._preview_played_ticks = set()
        self._last_time = time.perf_counter()
        self._tick_accumulator = 0.0
        self._is_playing = True
        self._preview_tick_loop()

    def _preview_stop(self):
        self._is_playing = False
        if self._preview_job:
            self.root.after_cancel(self._preview_job)
            self._preview_job = None
        if self._preview_sfx_aliases:
            for a in list(self._preview_sfx_aliases):
                _mci_close(a)
            self._preview_sfx_aliases = []

    def _preview_tick_loop(self):
        """Delta Time 播放循环: 用 perf_counter 精确计时, 必要时跳帧补偿."""
        if not getattr(self, '_is_playing', False):
            return

        cur = time.perf_counter()
        dt = cur - self._last_time
        self._last_time = cur

        tick_duration = max(10, self._preview_speed.get()) / 1000.0
        self._tick_accumulator += dt

        ticks_to_advance = 0
        while self._tick_accumulator >= tick_duration:
            ticks_to_advance += 1
            self._tick_accumulator -= tick_duration

        if ticks_to_advance > 0:
            old_tick = self._preview_tick_idx
            self._preview_tick_idx += ticks_to_advance

            # 补齐跳帧期间错过的所有音效触发
            for missed_tick in range(old_tick + 1, self._preview_tick_idx + 1):
                self._preview_sync_sfx_for_tick(missed_tick)

            all_stopped = self._preview_redraw()
            self._tl_playhead = self._preview_tick_idx
            self._tl_tick_lbl.config(text=f"tick: {self._tl_playhead}")
            self._tl_update_playhead()

            if all_stopped:
                self._is_playing = False
                return

        self._preview_job = self.root.after(5, self._preview_tick_loop)

    def _preview_step_first(self):
        self._preview_stop()
        self._preview_tick_idx = 0
        self._tl_tick_lbl.config(text="0")
        self._tl_playhead = 0
        self._tl_tick_lbl.config(text="tick: 0")
        self._tl_redraw()
        self._preview_redraw()

    def _preview_step_back(self):
        self._preview_stop()
        self._preview_tick_idx = max(0, self._preview_tick_idx - 1)
        self._tl_tick_lbl.config(text=str(self._preview_tick_idx))
        self._tl_playhead = self._preview_tick_idx
        self._tl_tick_lbl.config(text=f"tick: {self._tl_playhead}")
        self._tl_redraw()
        self._preview_redraw()

    def _preview_step_next(self):
        self._preview_stop()
        self._preview_tick_idx += 1
        self._tl_tick_lbl.config(text=str(self._preview_tick_idx))
        self._tl_playhead = self._preview_tick_idx
        self._tl_tick_lbl.config(text=f"tick: {self._tl_playhead}")
        self._tl_redraw()
        self._preview_redraw()

    def _preview_step_last(self):
        self._preview_stop()
        if self._editing_idx is not None:
            entry = self.entries[self._editing_idx]
            self._preview_tick_idx = self._tl_calc_duration(entry)
        else:
            self._preview_tick_idx = 0
        self._tl_tick_lbl.config(text=str(self._preview_tick_idx))
        self._tl_playhead = self._preview_tick_idx
        self._tl_tick_lbl.config(text=f"tick: {self._tl_playhead}")
        self._tl_redraw()
        self._preview_redraw()

    def _preview_sync_sfx(self):
        """兼容旧接口: 为当前 tick 触发音效."""
        self._preview_sync_sfx_for_tick(self._preview_tick_idx)

    def _preview_sync_sfx_for_tick(self, tick):
        """为指定 tick 触发音效 (供 Delta Time 跳帧补偿使用).
        音效源: SWS.GRP (sub_451780 A2C22C=1 分支)."""
        if self._editing_idx is None:
            return
        if self.sws_grp is None:
            return
        entry = self.entries[self._editing_idx]
        tail = entry.get('tail') or []
        for i in range(16):
            sid = tail[i * 2] if i * 2 < len(tail) else 0
            trig = tail[i * 2 + 1] if i * 2 + 1 < len(tail) else 0
            if sid == 0:
                continue
            if trig != tick:
                continue
            key = (i, tick)
            if key in self._preview_played_ticks:
                continue
            self._preview_played_ticks.add(key)
            path = self._resolve_sound_path(sid)
            if not path:
                continue
            alias = _mci_play_async(path)
            if alias:
                self._preview_sfx_aliases.append(alias)

    def _compute_layer_frame(self, L, tick):
        """按 sub_4434BC 语义计算当前帧号:
          start_delay (+44): 先倒数; 期间不播放
          tick_interval (+42): 每积累此值 tick 翻帧 (0 视作 1)
          first..last (+34..+36): 播放区间
          loop_behavior (+38): -1 无限循环, -2 播完停止,
                               ≥0 首轮播完后跳至该帧并循环
        返回 (cur_frame, stopped): stopped 表示首轮播放完成
        (loop=-1 永不为 True; loop=-2/>=0 在 frame_adv>=span 时为 True)"""
        start_delay = L[22]
        tick_interval = L[21]
        first = L[17]
        last = L[18]
        loop = L[19]

        if start_delay > 0:
            if tick < start_delay:
                return first, False
            tick -= start_delay

        step = max(1, tick_interval)
        frame_adv = tick // step
        span = max(1, last - first + 1)

        if loop == -1:
            return first + (frame_adv % span), False
        if loop == -2:
            if frame_adv >= span:
                return last, True
            return first + frame_adv, False
        if loop >= 0:
            if frame_adv < span:
                return first + frame_adv, False
            rem = frame_adv - span
            tail = max(1, last - loop + 1)
            return loop + (rem % tail), True
        return first + (frame_adv % span), False

    def _preview_redraw(self):
        c = self._preview_canvas
        c.delete("all")
        self._preview_sprite_boxes = []  # 精灵画布边界 (用于拖拽定位)

        if self._editing_idx is None:
            return
        if not self._aa_data and not self._af_data:
            c.create_text(200, 100,
                          text="未加载 JVG\n请先 文件 → 加载 TKS 目录",
                          fill="#888", font=("", 11))
            return

        direction = self._preview_dir_var.get()
        layers = self._preview_active_layers(direction)
        if not layers:
            c.create_text(200, 100, text=f"方向 {direction}: 无活跃图层",
                          fill="#888", font=("", 11))
            return

        tick = self._preview_tick_idx
        sprites = []
        dyn_x, dyn_y = [], []
        n_stoppable = 0   # loop=-2 的图层数 (会停止的)
        n_stopped = 0     # 已停止的图层数
        _layer_diag = []  # 诊断: 每层状态
        for slot, eff_dir, L in layers:
            v = self._preview_vis_vars.get(slot)
            if v is not None and not v.get():
                _layer_diag.append(f"#{slot} 隐藏")
                continue
            src = 'aa' if L[0] == 1 else 'af'
            pk = L[1]
            jvg = self._aa_data if src == 'aa' else self._af_data
            if jvg is None or pk < 0 or pk >= jvg.block_count:
                _layer_diag.append(f"#{slot} JVG缺失")
                continue
            blk = jvg.get_block(pk)
            n_frames = blk.frame_count
            if n_frames <= 0:
                _layer_diag.append(f"#{slot} 0帧")
                continue

            cur_abs, stopped = self._compute_layer_frame(L, tick)
            span = max(1, L[18] - L[17] + 1)
            delay = L[22]
            interval = max(1, L[21])
            eff_tick = max(0, tick - delay)
            frame_adv = eff_tick // interval

            # start_delay 期间: 图层不渲染, 不计入停止判断
            if tick < delay:
                _layer_diag.append(
                    f"#{slot} L={L[19]} 延迟中(delay={delay})")
                continue

            _layer_diag.append(
                f"#{slot} L={L[19]} fadv={frame_adv}/{span}"
                f"{' STOP' if stopped else ''}")
            # 游戏停止逻辑: loop=-1 无限循环不参与; 其余所有值首轮播完后停止
            if L[19] != -1:
                n_stoppable += 1
                if stopped:
                    n_stopped += 1
                    if L[19] == -2:
                        continue  # loop=-2 停止后不渲染
                    # loop>=0: 计入停止但继续渲染 (tail loop 阶段)
            if L[2] == 4:
                cur_abs += L[16] * eff_dir
            cur_abs = cur_abs % n_frames if n_frames > 0 else 0
            frame = blk.frames[cur_abs]

            ox = L[3 + eff_dir]
            oy = L[7 + eff_dir]
            # t=3 受击图层偏移到假想敌位置
            # t=4 也偏移到敌方 (游戏中 t=4 锚点 = 鼠标点击的地图格子坐标,
            #   sub_4429C8 转换后存入 word_9D6F80/82, 不属于攻击方/受击方;
            #   预览无战场格子输入, 暂放敌方侧)
            enemy_x = PREVIEW_ENEMY_X if L[0] in (3, 4) else 0
            spr_l = frame.x_off + ox + enemy_x
            spr_t = frame.y_off + oy
            spr_r = spr_l + frame.width - 1
            spr_b = spr_t + frame.height - 1
            dyn_x.extend([spr_l, spr_r, -ox - enemy_x])
            dyn_y.extend([spr_t, spr_b, -oy])
            sprites.append((slot, eff_dir, L, src, blk, cur_abs, frame,
                            ox, oy, spr_l, spr_t, spr_r, spr_b, False))

        if not sprites:
            c.create_text(200, 100,
                          text=f"方向 {direction}: 无可渲染帧\n(检查图层可见性)",
                          fill="#888", font=("", 11))
            return

        # 使用条目级固定 bbox, 保证切方向/逐帧时画面不晃; 缺失时回退到动态计算
        if self._preview_bbox is not None:
            bbox_l, bbox_t, bbox_r, bbox_b = self._preview_bbox
        else:
            bbox_l, bbox_r = min(dyn_x), max(dyn_x)
            bbox_t, bbox_b = min(dyn_y), max(dyn_y)
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw < 10 or ch < 10:
            return
        margin = 40
        bw = max(bbox_r - bbox_l, 1)
        bh = max(bbox_b - bbox_t, 1)
        sx = (cw - margin * 2) / bw
        sy = (ch - margin * 2) / bh
        scale = min(sx, sy, 3.0)
        # 锚点 (0,0) 居中显示在画布: bbox 中心对齐画布中心
        draw_w = bw * scale
        draw_h = bh * scale
        off_x = (cw - draw_w) / 2 - bbox_l * scale
        off_y = (ch - draw_h) / 2 - bbox_t * scale

        def to_cv(gx, gy):
            return (off_x + gx * scale, off_y + gy * scale)

        # 角色原点 (绿色)
        ox_c, oy_c = to_cv(0, 0)
        c.create_line(ox_c - 16, oy_c, ox_c + 16, oy_c,
                      fill='#00ff00', width=2)
        c.create_line(ox_c, oy_c - 16, ox_c, oy_c + 16,
                      fill='#00ff00', width=2)
        c.create_text(ox_c + 18, oy_c + 4, text="攻击方", fill='#0f0',
                      font=("Consolas", 7), anchor=tk.NW)

        # 假想敌位置 (红色)
        ex_c, ey_c = to_cv(PREVIEW_ENEMY_X, 0)
        c.create_line(ex_c - 16, ey_c, ex_c + 16, ey_c,
                      fill='#ff4444', width=2)
        c.create_line(ex_c, ey_c - 16, ex_c, ey_c + 16,
                      fill='#ff4444', width=2)
        c.create_text(ex_c + 18, ey_c + 4, text="受击方", fill='#f44',
                      font=("Consolas", 7), anchor=tk.NW)
        # 假想敌人形占位
        c.create_rectangle(ex_c - 15, ey_c - 40, ex_c + 15, ey_c,
                           fill='#442222', outline='#884444', width=1)
        c.create_text(ex_c, ey_c - 20, text="敌", fill='#f44',
                      font=("Consolas", 9))

        scaled_cache = []
        slot_colors = ['#4488ff', '#ff8844', '#44ff88', '#ff44ff',
                       '#ffff44', '#44ffff', '#ff8888', '#88ff88']
        info = [f"方向{direction} | 可见{len(sprites)}图层 | Tick:{tick}"]

        # ============================================================
        # ★ v2.4.1 修复: 在 PIL 层合成所有 sprite 再一次性贴到 Tk canvas,
        # 绕开 Windows Tk Canvas 对 RGBA PhotoImage alpha 合成的局限
        # (alpha=0 像素会显示成黑色 "底色" 的历史问题根源)
        # ★ v2.4.3 修正: mode=2 走加法饱和混合 (additive) 而非 alpha 半透,
        #               依据 sub_453554 L43-52 查表 word_A3AD30[i+j]=min(i+j,31)
        # 合成画布尺寸 = bbox * scale, 初始底色 = canvas bg (#1a1a2e)
        # ============================================================
        comp_w = max(1, int(bw * scale))
        comp_h = max(1, int(bh * scale))
        CANVAS_BG_RGB = (0x1a, 0x1a, 0x2e)
        try:
            composite = Image.new('RGB', (comp_w, comp_h), CANVAS_BG_RGB)
        except Exception:
            composite = None
        # composite 贴到 canvas 的左上角: 对应游戏坐标 (bbox_l, bbox_t)
        comp_ox, comp_oy = to_cv(bbox_l, bbox_t)

        for sp in sprites:
            (slot, eff_dir, L, src, blk, cur_abs, frame,
             ox, oy, spr_l, spr_t, spr_r, spr_b, stopped) = sp

            pk = L[1]
            blend_mode = L[11]
            blend_param = L[12]
            # 可读 blend 标签 (用于 info 行显示)
            _bm_label = {
                0: '正常', 1: '染色', 2: '加法',
                3: '减法', 4: '亮度融合', 5: '翻转',
            }.get(blend_mode, f'?{blend_mode}')
            _effective = True
            if blend_mode == 0:
                _effective = False
            elif blend_mode == 2:
                # mode=2 任何 param 都有效 (加法混合, p 只影响 src 预乘强度)
                _effective = True
            elif blend_mode == 1:
                _effective = 0 < blend_param <= 31
            _eff_tag = '' if _effective or blend_mode in (3, 4, 5) else '~'

            # 1) 取原始 PIL RGBA (无缩放无混合)
            pil = self._preview_get_pil(src, pk, cur_abs)
            if pil is None:
                continue

            # 2) 应用像素级变换 (mode=1/3/4/5); mode=2 原样返回由合成阶段处理
            pil_blended = self._apply_blend(pil, blend_mode, blend_param)
            if pil_blended is None:
                continue

            cx, cy = to_cv(spr_l, spr_t)
            nw = max(1, int(frame.width * scale))
            nh = max(1, int(frame.height * scale))
            color = slot_colors[(slot - 1) % len(slot_colors)]

            # 3) 缩放 → 按 blend_mode 合成到 composite 画布上
            try:
                if nw == frame.width and nh == frame.height:
                    final_img = pil_blended
                else:
                    final_img = pil_blended.resize((nw, nh), Image.NEAREST)
                if composite is not None:
                    # 目标位置 = sprite 在合成图上的左上角像素坐标
                    dx = int(round((spr_l - bbox_l) * scale))
                    dy = int(round((spr_t - bbox_t) * scale))
                    if blend_mode == 2:
                        # ★ additive 加法饱和混合 (sub_4559D0 全分支):
                        #   param == 0  或  > 31  → full additive (scale=1.0)
                        #   0 < param <= 31       → src 先乘 param/32 再加
                        #   公式 (每通道): dst = min(dst + src * α, 255)
                        #   黑色 (0,0,0) 贡献为 0, 不改变 dst → "黑色被过滤"
                        self._composite_additive(
                            composite, final_img, dx, dy, blend_param)
                    elif blend_mode == 3:
                        # ★ 减法饱和混合 (sub_45871C L118-134):
                        #   dst.RGB = max(dst - src, 0) 每通道独立
                        self._composite_subtract(
                            composite, final_img, dx, dy)
                    elif blend_mode == 4:
                        # ★ 按 src 亮度的 alpha blend (sub_459854 L109-124):
                        #   α = NTSC 灰度 Y(src)  → 按 α 值线性融合 src 与 dst
                        self._composite_luma_alpha(
                            composite, final_img, dx, dy)
                    else:
                        # 其余 mode: 标准 alpha 合成 (paste with mask)
                        composite.paste(final_img, (dx, dy), final_img)
            except Exception:
                continue

            # sprite 外边框 + 序号标签 (直接画到 canvas, 不走 PIL)
            rx, ry = to_cv(spr_r, spr_b)
            c.create_rectangle(cx, cy, rx + 1, ry + 1,
                               outline=color, width=1)
            c.create_text(cx + 2, cy + 2, text=f"#{slot}",
                          fill=color, font=("Consolas", 6), anchor=tk.NW)

            # 记录精灵画布边界 (用于画布拖拽定位)
            self._preview_sprite_boxes.append(
                (slot, eff_dir, cx, cy, max(cx, rx), max(cy, ry), ox, oy))

            info.append(
                f"  #{slot} src={src} blk={pk} t={L[0]} dir={eff_dir} "
                f"f={cur_abs+1}/{blk.frame_count} "
                f"off=({ox:+d},{oy:+d}) "
                f"blend={blend_mode}/{_bm_label}{_eff_tag}(p={blend_param}) "
                f"int={L[21]} delay={L[22]} "
                f"[{L[17]}..{L[18]}] loop={L[19]}"
                f"{' [STOP]' if stopped else ''}")

        # 4) 合成图一次性贴到 canvas (RGB 模式, 不触及 tk alpha)
        if composite is not None:
            try:
                comp_tk = ImageTk.PhotoImage(composite)
                scaled_cache.append(comp_tk)
                # ★ z-order: 合成图要在 sprite 边框/文字之下
                # 但前面已 create_rectangle/text, 所以此处加 tag 后 lower
                img_id = c.create_image(comp_ox, comp_oy,
                                        image=comp_tk, anchor=tk.NW)
                c.tag_lower(img_id)
                # 原点十字也需要在合成图之上 -> 重绘
                c.create_line(ox_c - 16, oy_c, ox_c + 16, oy_c,
                              fill='#00ff00', width=2)
                c.create_line(ox_c, oy_c - 16, ox_c, oy_c + 16,
                              fill='#00ff00', width=2)
                c.create_text(ox_c + 18, oy_c + 4, text="原点", fill='#0f0',
                              font=("Consolas", 7), anchor=tk.NW)
            except Exception:
                pass

        # 所有 loop!=-1 的图层首轮播完后停止 (loop=-1 无限循环不参与判断)
        all_stopped = n_stoppable > 0 and n_stopped >= n_stoppable
        if all_stopped:
            c.create_text(cw // 2, ch - 16,
                          text=f"■ 播放完毕 (tick {tick})",
                          fill='#ff0', font=("Consolas", 10))

        self._preview_scaled_cache = scaled_cache
        info.append(f"loop=-2: {n_stopped}/{n_stoppable}")
        # 诊断: 每层推进状态
        for diag in _layer_diag:
            info.append(diag)
        for li, line in enumerate(info[:20]):
            c.create_text(8, 8 + li * 14, text=line, fill="#0f0",
                          font=("Consolas", 8), anchor=tk.NW)

        return all_stopped

    # ---- 画布拖拽定位 ----

    def _pv_hit_test(self, cx, cy):
        """检测画布坐标命中的精灵. 返回 (slot, eff_dir) 或 None"""
        for (slot, eff_dir, sx, sy, ex, ey, ox, oy) in self._preview_sprite_boxes:
            if sx <= cx <= ex and sy <= cy <= ey:
                return (slot, eff_dir, ox, oy, sx, sy)
        return None

    def _pv_on_press(self, event):
        hit = self._pv_hit_test(event.x, event.y)
        if hit:
            slot, eff_dir, ox, oy, sx, sy = hit
            self._pv_drag_state = (slot, eff_dir, ox, oy, event.x, event.y, sx, sy)
            self._preview_stop()
            self._preview_canvas.configure(cursor='fleur')
        else:
            self._pv_drag_state = None

    def _pv_on_drag(self, event):
        if self._pv_drag_state is None:
            return
        slot, eff_dir, ox, oy, px, py, sx, sy = self._pv_drag_state
        dx = event.x - px
        dy = event.y - py

        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]
        L = entry['layers'][slot - 1]

        # 计算缩放因子 (近似, 从最近的 bbox)
        cw = self._preview_canvas.winfo_width()
        ch = self._preview_canvas.winfo_height()
        if self._preview_bbox is not None:
            bbox_l, bbox_t, bbox_r, bbox_b = self._preview_bbox
        else:
            return
        margin = 40
        bw = max(bbox_r - bbox_l, 1)
        bh = max(bbox_b - bbox_t, 1)
        scale = min((cw - margin * 2) / bw, (ch - margin * 2) / bh, 3.0)

        # 画布像素 → 游戏坐标
        gdx = int(dx / scale)
        gdy = int(dy / scale)

        new_ox = L[3 + eff_dir] + gdx
        new_oy = L[7 + eff_dir] + gdy

        L[3 + eff_dir] = max(-32768, min(32767, new_ox))
        L[7 + eff_dir] = max(-32768, min(32767, new_oy))

        self._dirty = True
        self._pv_drag_state = (slot, eff_dir, L[3 + eff_dir], L[7 + eff_dir],
                               event.x, event.y, sx + gdx, sy + gdy)
        self._populate_layer(slot - 1, L)
        self._preview_redraw()

    def _pv_on_release(self, event):
        if self._pv_drag_state is not None and self._editing_idx is not None:
            entry = self.entries[self._editing_idx]
            self._populate_edit(entry)
        self._pv_drag_state = None
        self._preview_canvas.configure(cursor='')

    def _pv_on_motion(self, event):
        hit = self._pv_hit_test(event.x, event.y)
        if hit:
            self._preview_canvas.configure(cursor='hand2')
        else:
            self._preview_canvas.configure(cursor='')

    def _on_close(self):
        self._preview_stop()
        if self._dirty:
            if not messagebox.askyesno("未保存", "有未保存的修改, 确定退出?"):
                return
        _cleanup_sws_tempfiles()
        self.root.destroy()

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        lines = [
            "TKAct.dat 字段语义 v2.0 (基于 sub_4434BC 反编译)",
            "",
            f"【文件结构】{ACT_ENTRY_COUNT} 条 × {ACT_ENTRY_SIZE} 字节 "
            f"= {ACT_DECOMPRESSED} 字节",
            "  每条 = 方向表[32B] + 条目级参数[48B] + 8图层×80B + 尾部[64B]",
            "",
            "【方向表 (bytes 0-31)】",
            "  4 方向 × 8 字节, 每字节 = 1-based 图层号 (0=空)",
            "  sub_4434BC: v22[8*v33+i] 依次渲染, 后画的在上层 (z-order)",
            "  约束: v33 ∈ [0,3], 否则 +2*v34+6 会越界侵入 Y 数组",
            "",
            "【图层 × 8 (各 80 字节, 40 int16)】",
        ]
        for grp_name, fields in FIELD_GROUPS:
            lines.append(f"  — {grp_name} —")
            for (fn, idx, label, _, comment) in fields:
                lines.append(f"    [{idx:2d}] {fn:<18s} {label}")
                lines.append(f"         {comment}")
            lines.append("")
        lines.append("【尾部 (bytes 720-783)】")
        lines.append("  16 对 (value, count), 疑似关键帧/触发表")
        lines.append("  未在 sub_4434BC 中引用, 用途未完全验证")

        dlg = tk.Toplevel(self.root)
        dlg.title("字段参考 (反编译来源)")
        dlg.geometry("760x640")
        dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='word')
        sb = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        tx.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines))
        tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "TKAct.dat 多图层 2D 精灵动画编辑器 v2.4.4\n\n"
            "修订依据:\n"
            "  · 逆向工作区/TKS_AI分析act_editor记录.md (v2.0/v2.1)\n"
            "  · 逆向工作区/TKS_AI修正TKAct.dat实际JVG绑定.md (v2.2)\n"
            "  · sub_4434BC / sub_451780 / sub_458D08 反编译 (v2.3/v2.4)\n\n"
            "650 条 × 784 字节 = 509,600 字节\n\n"
            "v2.4.4 重大修正 (mode=3/4 之前实现完全错误):\n"
            "  · mode=3 实为\"减法钳 0\" (sub_45871C L118-134):\n"
            "    dst.RGB = max(dst - src, 0) 每通道 → \"挖洞变暗\"\n"
            "  · mode=4 实为\"按亮度 alpha-blend\" (sub_459854 L109-124):\n"
            "    α=Y(src); α==0 跳过; α>28 覆盖; 其他 α 级线性融合\n\n"
            "v2.4.3 修正:\n"
            "  · mode=2 是加法饱和混合 (additive), 非 alpha 半透\n"
            "    查表 word_A3AD30[i+j]=min(i+j,31) (sub_453554 L43-52)\n\n"
            "v2.4.1 修复:\n"
            "  · 预览 sprite 周围黑底 (Tk Canvas RGBA alpha 合成)\n"
            "    → 改由 PIL 自合成, 一次性以 RGB 贴图\n\n"
            "v2.4 关键修正:\n"
            "  · layer_type 语义按实测精细化 (与 sub_4434BC L305/414/460/518 分流一致):\n"
            "    t=1 角色攻击动作 (Aa.jvg, 攻击者位置)\n"
            "    t=2 技能攻击特效 (Af.jvg, 攻击者位置)\n"
            "    t=3 受击特效 (Af.jvg, 受击方位置, 延迟段)\n"
            "    t=4 命中锚点 (sub_42F9C8 计算, 不渲染)\n"
            "    t=5 全屏特效 (屏幕中心 320,300)\n"
            "  · 预览应用 6 种图像混合模式 (blend_mode +22):\n"
            "    0 正常 / 1 染色 / 2 加法 / 3 减法 / 4 亮度融合 / 5 水平翻转\n\n"
            "v2.3: 尾部 64B = 音效触发表 + SWS.GRP 实时播放\n"
            "v2.2: 贴图源 = Aa.jvg / Af.jvg (非 Cha / Ani)\n"
            "逆向来源: sub_4434BC / sub_42FEE0 / sub_451780 / sub_458D08")


def main():
    root = tk.Tk()
    ActEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
