# -*- coding: utf-8 -*-
"""游戏状态界面 1:1 复刻视图 — mb.gxp 背景 + Mu.JVG 精灵 + 反编译坐标

布局与绘制顺序复刻自反编译代码:
  sub_41762C — 左侧队伍列表 (79px 行高) + 顶部页签 (x=209+72j, y=6)
  sub_417F84 — 状态页: 面板装饰 / 4装备槽 / 6技能槽 / 属性文字 (x=220)
  sub_4188D4 — 异常状态图标 (帧 241+)
  sub_454D90 — 半透明混合公式 dst*(32-a)/32 + src*a/32 (alpha 10/13/15)
资源: mb.gxp (JGXP 头 + LZSS + RGB565 全屏 640×480), Mu.JVG (帧偏移 x_off/y_off),
      PFace.jvg (主角自定义头像, f[1]==0 时替代 Mu 帧)。
头像帧规则 (含 tks_launcher 补丁): f[261] 非零 → 帧 f[261]; 否则 f[1]+211。
"""
import struct

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from editor_utils.lzss import lzss_decompress_stream
from editor_utils.rgb565 import rgb565_to_rgba
from editor_utils.jvg_data import load_jvg

from book_loader import tkt_first_line, pil_to_qpixmap

GAME_W, GAME_H = 640, 480

# 游戏调色板颜色索引 (sub_44B028) — 颜色值取自游戏截图采样
GAME_COLORS = {
    16: QColor(255, 255, 240),   # 白 (数值/未选中行)
    18: QColor(228, 56, 44),     # 红 (HP/MP < 一半)
    19: QColor(252, 248, 37),    # 黄 (选中行名字 / HP/MP ≥ 一半)
    20: QColor(51, 218, 50),     # 绿 (生命标签 / 八属性标签)
    21: QColor(0, 244, 213),     # 青 (内力标签 / 核心标签)
}

# 状态页左列 (sub_417F84 L61-91): (标签, y, 颜色)
CORE_ROWS = [("等级:", 60), ("生命:", 83), ("内力:", 106), ("经验:", 129), ("升级:", 152)]
STAT_ROWS = [  # (标签, y, 当前值字段)
    ("攻击:", 244, 12), ("防御:", 267, 14), ("命中:", 290, 16), ("闪避:", 313, 18),
    ("速度:", 336, 20), ("幸运:", 359, 22), ("悟性:", 382, 26), ("移动:", 405, 24),
]
EQUIP_REC_IDX = [69, 70, 71, 72]         # 装备 TKItem 记录号 (-1=空)
SKILL_SLOT_IDX = [82, 83, 84, 85, 86, 87]  # 4主动+2被动 技能索引 (-1=空)


def _load_gxp_pil(path):
    """解码 GXP 全屏背景 → PIL RGBA (格式同 gxp_editor: JGXP 头 48B + LZSS + RGB565)"""
    from PIL import Image
    data = open(path, 'rb').read()
    if len(data) < 52 or data[:4] != b"JGXP":
        return None
    w = ~struct.unpack_from("<i", data, 4)[0]
    h = ~struct.unpack_from("<i", data, 8)[0]
    csize = struct.unpack_from("<I", data, 12)[0]
    usize = struct.unpack_from("<I", data, 48)[0]
    raw = lzss_decompress_stream(data[52:48 + csize], usize)
    return Image.frombytes("RGBA", (w, h), bytes(rgb565_to_rgba(raw, w, h)))


def _jvg_frame_pil(blk, frame):
    """JVGFrame → PIL RGBA (调色板 + RLE alpha)"""
    from PIL import Image
    if frame.width <= 0 or frame.height <= 0:
        return None
    img = Image.frombytes('P', (frame.width, frame.height), frame.pixels)
    img.putpalette(blk.palette.to_rgb888())
    rgba = img.convert('RGBA')
    rgba.putalpha(Image.frombytes('L', (frame.width, frame.height), frame.alpha))
    return rgba


def _status_cache(data):
    """帧/背景/静态底图缓存挂在 GameData 上, 跨视图重建复用"""
    c = getattr(data, '_status_view_cache', None)
    if c is None:
        c = {'mu': None, 'mu_tried': False, 'pface': None, 'pface_tried': False,
             'bg': None, 'bg_tried': False, 'mu_pix': {}, 'pface_pix': {}, 'base': None}
        data._status_view_cache = c
    return c


class GameStatusView(QWidget):
    """640×480 游戏状态界面复刻控件。左侧列表行可点击切换角色。"""

    charClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(GAME_W, GAME_H)
        self.data = None
        self._roster = []        # [warpc_idx, ...] (与人物列表同序)
        self._rec_by_idx = {}
        self._current = -1
        self._window = []        # 左侧列表当前显示的 warpc_idx 窗口 (≤6)
        self._image = None       # 渲染结果 QPixmap
        self._font = QFont("SimSun")
        self._font.setPixelSize(20)
        self._fm = QFontMetrics(self._font)
        self.setCursor(Qt.PointingHandCursor)

    # ── 数据 ──

    def set_data(self, data):
        self.data = data
        self._rec_by_idx = {r['index']: r for r in data.warpc_recs}
        self._image = None

    def set_roster(self, roster):
        self._roster = list(roster)

    def available(self):
        """mb.gxp 与 Mu.JVG 均存在时才可用"""
        return (self.data is not None
                and self.data.paths.get("mb.gxp")
                and self.data.paths.get("Mu.JVG"))

    def show_char(self, warpc_idx):
        self._current = warpc_idx
        # 左列表窗口: 当前角色居中 (游戏内是队伍 6 人, 图鉴用花名册邻居)
        pos = self._roster.index(warpc_idx) if warpc_idx in self._roster else 0
        start = min(max(0, pos - 2), max(0, len(self._roster) - 6))
        self._window = self._roster[start:start + 6]
        self._rebuild()
        self.update()

    # ── 资源 ──

    def _cache(self):
        return _status_cache(self.data)

    def _mu_frames(self):
        c = self._cache()
        if not c['mu_tried']:
            c['mu_tried'] = True
            p = self.data.paths.get("Mu.JVG")
            if p:
                try:
                    jvg = load_jvg(p)
                    c['mu'] = [(b, f) for b in jvg.blocks for f in b.frames]
                except Exception:
                    c['mu'] = None
        return c['mu']

    def _pface_frames(self):
        c = self._cache()
        if not c['pface_tried']:
            c['pface_tried'] = True
            p = self.data.paths.get("PFace.jvg")
            if p:
                try:
                    jvg = load_jvg(p)
                    c['pface'] = [(b, f) for b in jvg.blocks for f in b.frames]
                except Exception:
                    c['pface'] = None
        return c['pface']

    def _frame_pix(self, frames, pix_cache, idx):
        """帧 → (QPixmap, x_off, y_off); 无效帧返回 None"""
        if not frames or idx < 0 or idx >= len(frames):
            return None
        if idx in pix_cache:
            return pix_cache[idx]
        blk, f = frames[idx]
        entry = None
        try:
            pil = _jvg_frame_pil(blk, f)
            pix = pil_to_qpixmap(pil) if pil else None
            if pix:
                entry = (pix, f.x_off, f.y_off)
        except Exception:
            entry = None
        pix_cache[idx] = entry
        return entry

    def _mu_pix(self, idx):
        return self._frame_pix(self._mu_frames(), self._cache()['mu_pix'], idx)

    def _pface_pix(self, idx):
        return self._frame_pix(self._pface_frames(), self._cache()['pface_pix'], idx)

    def _background(self):
        c = self._cache()
        if not c['bg_tried']:
            c['bg_tried'] = True
            p = self.data.paths.get("mb.gxp")
            if p:
                try:
                    c['bg'] = pil_to_qpixmap(_load_gxp_pil(p))
                except Exception:
                    c['bg'] = None
        return c['bg']

    # ── 绘制原语 ──

    def _blit(self, p, entry, x, y, alpha32=None):
        """按帧偏移绘制; alpha32 复刻 sub_454D90 混合 (a/32)"""
        if entry is None:
            return
        pix, xo, yo = entry
        if alpha32 is not None:
            p.setOpacity(alpha32 / 32.0)
        p.drawPixmap(x + xo, y + yo, pix)
        p.setOpacity(1.0)

    def _text(self, p, x, y, text, color_idx=16):
        """复刻游戏定宽字模: 全角 20px / 半角 10px, 黑色描边"""
        col = GAME_COLORS.get(color_idx, GAME_COLORS[16])
        p.setFont(self._font)
        baseline = y + self._fm.ascent() - 2
        cx = x
        for ch in text:
            adv = 20 if ord(ch) > 0xFF else 10
            if not ch.isspace():
                p.setPen(QColor(20, 16, 12))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    p.drawText(cx + dx, baseline + dy, ch)
                p.setPen(col)
                p.drawText(cx, baseline, ch)
            cx += adv

    @staticmethod
    def _hpmp_color(cur, mx):
        """sub_41762C HP/MP 颜色规则: 满=16白, ≥一半=19黄, <一半=18红"""
        if cur == mx:
            return 16
        return 19 if cur >= mx / 2 else 18

    def _portrait_pix(self, f):
        """头像帧: f[261] 非零 → Mu 帧 f[261]; f[1] 非零 → Mu 帧 f[1]+211;
        否则 PFace 帧 0 (存在时), 兜底 Mu 帧 211"""
        if len(f) > 261 and f[261] > 0:
            return self._mu_pix(f[261])
        if f[1]:
            return self._mu_pix(f[1] + 211)
        entry = self._pface_pix(0)
        return entry if entry else self._mu_pix(211)

    # ── 静态底图 (跨角色复用): 背景 + 面板 + 页签 + 槽标签 + 属性标签 ──

    def _static_base(self):
        c = self._cache()
        if c['base'] is not None:
            return c['base']
        bg = self._background()
        base = QPixmap(GAME_W, GAME_H)
        base.fill(QColor(0, 0, 0))
        p = QPainter(base)
        if bg:
            p.drawPixmap(0, 0, bg)
        # 面板装饰 (417F84 L21-24): 帧 10/8/9 半透明, 帧 7 不透明
        self._blit(p, self._mu_pix(10), 460, 61, 15)
        self._blit(p, self._mu_pix(8), 209, 45, 10)
        self._blit(p, self._mu_pix(9), 214, 55, 13)
        self._blit(p, self._mu_pix(7), 210, 50)
        # 顶部页签 (41762C L120-126): 状态页选中 → 帧 74, 其余 68+j
        for j in range(6):
            self._blit(p, self._mu_pix((74 if j == 0 else 68) + j), 209 + 72 * j, 6)
        # 装备槽标签 (417F84 L32): 帧 62武/64防/66饰/66饰
        for i, fr in enumerate((62, 64, 66, 66)):
            self._blit(p, self._mu_pix(fr), 450, 80 + 35 * i)
        # 技能槽标签 (417F84 L50): 帧 58,58,59,59,60,61
        for i, fr in enumerate((58, 58, 59, 59, 60, 61)):
            self._blit(p, self._mu_pix(fr), 450, 240 + 36 * i)
        # 属性标签 (417F84 L61-76): 核心色21青, 八属性+技能点数色20绿
        for label, y in CORE_ROWS:
            self._text(p, 220, y, label, 21)
        for label, y, _fi in STAT_ROWS:
            self._text(p, 220, y, label, 20)
        self._text(p, 220, 428, "技能点数:", 20)
        p.end()
        c['base'] = base
        return base

    # ── 整帧渲染 ──

    def _rebuild(self):
        if not self.available():
            self._image = None
            return
        rec = self._rec_by_idx.get(self._current)
        if rec is None:
            self._image = None
            return
        f = rec['fields']
        img = QPixmap(self._static_base())
        p = QPainter(img)

        # 左侧列表 (41762C): 行高 79px, 选中行帧0边框+黄名字, 未选中行暗化
        for row, widx in enumerate(self._window):
            r = self._rec_by_idx.get(widx)
            if r is None:
                continue
            rf = r['fields']
            name = self.data.char_name(r) or f"#{widx}"
            hp_c = self._hpmp_color(rf[5], rf[8])
            mp_c = self._hpmp_color(rf[6], rf[10])
            if widx == self._current:
                self._blit(p, self._mu_pix(0), 7, 79 * row + 3)
                self._blit(p, self._mu_pix(row + 1), 208, 42)   # 选中行→面板连接条
                self._text(p, 80, 79 * row + 4, name, 19)
                self._text(p, 80, 79 * row + 27, "生命:", 20)
                self._text(p, 80, 79 * row + 50, "内力:", 21)
                self._text(p, 80, 79 * row + 27, f"     {rf[5]}", hp_c)
                self._text(p, 80, 79 * row + 50, f"     {rf[6]}", mp_c)
                self._blit(p, self._portrait_pix(rf), 7, 79 * row + 4)
            else:
                self._text(p, 76, 79 * row + 8, name, 16)
                self._text(p, 80, 79 * row + 27, "生命:", 16)
                self._text(p, 80, 79 * row + 50, "内力:", 16)
                self._text(p, 80, 79 * row + 27, f"     {rf[5]}", hp_c)
                self._text(p, 80, 79 * row + 50, f"     {rf[6]}", mp_c)
                self._blit(p, self._mu_pix(0), 3, 79 * row + 7, 10)
                self._blit(p, self._portrait_pix(rf), 3, 79 * row + 8, 15)

        # 装备槽名字 (417F84 L33-37): f[69..72] = TKItem 记录号
        for i, fi in enumerate(EQUIP_REC_IDX):
            ri = f[fi]
            if 0 <= ri < len(self.data.item_recs):
                nm = tkt_first_line(self.data.tkt, self.data.item_recs[ri]['vals'][2])
                if nm:
                    self._text(p, 480, 80 + 35 * i, nm, 16)

        # 技能槽名字 (417F84 L50-55): f[82..87] (空槽判定与 tab_char 一致: >0)
        for i, fi in enumerate(SKILL_SLOT_IDX):
            sid = f[fi]
            if sid > 0:
                nm = self.data.skill_name(sid)
                if nm:
                    self._text(p, 490, 36 * i + 247, nm, 16)

        # 状态页数值 (417F84 L77-91, 色16白, "%5d" 缩进 5 半角)
        self._text(p, 220, 60, f"     {f[2]}")
        self._text(p, 220, 83, f"     {f[5]}/{f[8]}")
        self._text(p, 220, 106, f"     {f[6]}/{f[10]}")
        self._text(p, 220, 129, f"     {max(f[3], 0)}")  # 静态数据 [3]=-1(我方标志), 运行时才是经验
        self._text(p, 220, 152, f"     {f[4]}")
        for _label, y, fi in STAT_ROWS:
            self._text(p, 220, y, f"     {f[fi]}")
        self._text(p, 220, 428, f"         {f[31]}")

        # 异常状态图标 (4188D4): f[43..50] 字节对 (图标id, 标志), 帧 id+241
        shown = 0
        for k in range(8):
            v = f[43 + k] & 0xFFFF
            lo, hi = v & 0xFF, (v >> 8) & 0xFF
            if lo and hi:
                if shown >= 4:
                    self._blit(p, self._mu_pix(lo + 241), 40 * shown + 120, 210)
                else:
                    self._blit(p, self._mu_pix(lo + 241), 40 * shown + 280, 175)
                shown += 1
        p.end()
        self._image = img

    # ── 事件 ──

    def paintEvent(self, event):
        p = QPainter(self)
        if self._image is not None:
            p.drawPixmap(0, 0, self._image)
        else:
            p.fillRect(self.rect(), QColor(24, 24, 28))
            p.setPen(QColor(160, 160, 160))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "缺少 mb.gxp / Mu.JVG, 无法渲染游戏界面")

    def mousePressEvent(self, event):
        # 左侧列表行命中 (行区域同帧0边框: x 3..205, 高 74)
        pos = event.position().toPoint()
        if pos.x() <= 205:
            row = (pos.y() - 3) // 79
            if 0 <= row < len(self._window):
                widx = self._window[row]
                if widx != self._current:
                    self.charClicked.emit(widx)
                    return
        super().mousePressEvent(event)
