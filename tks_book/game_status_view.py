# -*- coding: utf-8 -*-
"""游戏状态/技能/队伍界面 1:1 复刻视图 — mb.gxp 背景 + Mu.JVG 精灵 + 反编译坐标

布局与绘制顺序复刻自反编译代码:
  sub_41762C — 左侧队伍列表 (79px 行高) + 顶部页签 (x=209+72j, y=6)
  sub_417F84 — 状态页: 面板装饰 / 4装备槽 / 6技能槽 / 属性文字 (x=220)
  sub_4188D4 — 异常状态图标 (帧 241+)
  sub_418EE8 — 技能页: 面板(16/11/12/13/14) / 4分类页签(42px步进) / 右侧6槽(35px步进)
  sub_418C90 — 技能列表: 31px 行高, 选中条帧80, 学习消耗 = jp_cost×(250-悟性)/200
  sub_418E5C — 技能说明: 字号16, 坐标(453,305)
  sub_419704 — 物品页: 分类栏帧25 + 6分类高亮(帧27-32,61px步进) + 列表面板帧33 + 金钱帧206
  sub_419458 — 物品列表: 10行/页, 行高31, 图标(字段4+130)@235, 名字@285, 选中条帧81
  sub_4195C4 — 物品说明: 浮动提示框帧158, 行 Y+31 (靠底则 Y-139), 说明文本=字段3
               (游戏内右键长按物品显示, 松开消失; 弹窗为最顶层, 覆盖列表文字)
  sub_41928C — 物品列表构建: 按字段1(分类)过滤, 每页 10 项
  sub_41A080 — 队伍页: 4子页签(帧50-53, 60px步进) + 团队(5成员/战绩统计)
               + 记事/功绩(每页3条, TKT=11201+序号) + 历史(TKT 9050+序号)
  sub_41A7A8 — 记事/功绩列表构建 (1000项标志数组, 1=记事 2=功绩, 页数=⌈n/3⌉)
  sub_422A5C — 团队聚合属性: Σ队员智慧/仁德/勇气/医术 (前三钳≥0, 医术封顶100)
  sub_417F0C — 翻页箭头: 帧21(x,y) / 帧22(x+20,y+5)
  sub_454D90 — 半透明混合公式 dst*(32-a)/32 + src*a/32 (alpha 10/13/15)
资源: mb.gxp (JGXP 头 + LZSS + RGB565 全屏 640×480), Mu.JVG (帧偏移 x_off/y_off),
      PFace.jvg (主角自定义头像, f[1]==0 时替代 Mu 帧)。
头像帧规则 (含 tks_launcher 补丁): f[261] 非零 → 帧 f[261]; 否则 f[1]+211。
"""
import struct

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from editor_utils.lzss import lzss_decompress_stream
from editor_utils.rgb565 import rgb565_to_rgba
from editor_utils.jvg_data import load_jvg

from book_loader import (
    SKILL_LEARN_BASE, SKILL_LEARN_COUNT, get_packed_byte,
    tkt_first_line, tkt_full_text, pil_to_qpixmap,
)
from game_font import load_game_font

GAME_W, GAME_H = 640, 480

# 游戏文字调色板 (sub_451FA0 权威定义, 32 色; sub_451F08 存储为 RGB565 → 显示时量化)
def _c565(r, g, b):
    """按游戏 RGB565 存储量化 (与实际屏幕输出一致)"""
    r5, g6, b5 = r >> 3, g >> 2, b >> 3
    return QColor((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


GAME_COLORS = {
    0: _c565(0, 0, 0),        1: _c565(128, 128, 128),  2: _c565(128, 0, 0),
    3: _c565(128, 128, 0),    4: _c565(0, 128, 0),      5: _c565(0, 128, 128),
    6: _c565(0, 0, 128),      7: _c565(128, 0, 128),    8: _c565(128, 64, 0),
    9: _c565(128, 0, 64),     10: _c565(64, 128, 0),    11: _c565(0, 128, 64),
    12: _c565(64, 0, 128),    13: _c565(0, 64, 128),    14: _c565(0, 0, 0),
    15: _c565(0, 0, 0),       16: _c565(244, 242, 220), 17: _c565(192, 192, 192),
    18: _c565(255, 0, 0),     19: _c565(255, 255, 0),   20: _c565(0, 255, 0),
    21: _c565(0, 255, 255),   22: _c565(0, 0, 255),     23: _c565(255, 0, 255),
    24: _c565(255, 128, 64),  25: _c565(255, 64, 128),  26: _c565(128, 255, 64),
    27: _c565(64, 255, 128),  28: _c565(128, 64, 255),  29: _c565(64, 128, 255),
    30: _c565(52, 62, 84),    31: _c565(255, 255, 255),
}

# 状态页左列 (sub_417F84 L61-91): (标签, y) — 繁体原文取自 exe 数据段 (Big5, FONT9696 可查)
CORE_ROWS = [("等級:", 60), ("生命:", 83), ("內力:", 106), ("經驗:", 129), ("升級:", 152)]
STAT_ROWS = [  # (标签, y, 当前值字段)
    ("攻擊:", 244, 12), ("防禦:", 267, 14), ("命中:", 290, 16), ("閃避:", 313, 18),
    ("速度:", 336, 20), ("幸運:", 359, 22), ("悟性:", 382, 26), ("移動:", 405, 24),
]
EQUIP_REC_IDX = [69, 70, 71, 72]         # 装备 TKItem 记录号 (-1=空)
SKILL_SLOT_IDX = [82, 83, 84, 85, 86, 87]  # 4主动+2被动 技能索引 (-1=空)
SLOT_CAT_FRAMES = (58, 58, 59, 59, 60, 61)  # 右侧6槽分类图标帧 (指令/主动/被动/移动)

SKILL_LIST_VISIBLE = 10   # 技能列表面板 (帧12 高319, 行高31) 可见行数

# 物品页 (sub_419704/sub_419458/sub_4195C4)
ITEM_LIST_VISIBLE = 10    # 每页可见行数 (sub_41928C v8<9 → 10 项)
ITEM_CATEGORIES = 6       # 分类数 0-5 (药品/道具/武器/防具/饰品/特殊, 高亮帧 27-32)

# 队伍页 (sub_41A080): 团队统计标签 (繁体原文取自 exe 数据段, 值为存档数据 → 静态显示 0)
TEAM_STAT_LEFT = [  # (标签, y) @ x=230, 值 %5d
    ("勝場數  ", 100), ("敗場數  ", 130), ("殺敵數  ", 160),
]
TEAM_TASK_ROWS = [  # (标签, y, 后缀) @ x=230
    ("完成任務", 250, "%"), ("特殊物品", 280, "%"),
    ("收納靈魂", 400, ""), ("收納獸元", 430, ""),
]
TEAM_ATTR_RIGHT = [  # (标签, y, 字段) @ x=440, 团队聚合 (sub_422A5C)
    ("智慧    ", 110, 27), ("仁德    ", 145, 28), ("勇氣    ", 180, 29), ("醫術    ", 215, 30),
]
JOURNAL_TKT_BASE = 11201   # 记事/功绩文本池 (sub_41A080 L78: 序号+11201)
JOURNAL_TKT_SPAN = 200     # 记事 11201-11400, 功绩 11401-11600 (TKT 数据实证分段)
JOURNAL_PER_PAGE = 3       # 每页3条 (41A080 L76-95: y=108/225/339, 分隔条帧57)


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
             'bg': None, 'bg_tried': False, 'mu_pix': {}, 'pface_pix': {}}
        data._status_view_cache = c
    return c


class GameStatusView(QWidget):
    """640×480 游戏菜单界面复刻控件 (状态/技能页)。

    可交互: 左侧头像行切换角色; 顶部页签切换 状态↔技能;
    技能页内: 分类页签 / 列表行 / 右侧槽点击, 滚轮或箭头翻页。
    """

    charClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(GAME_W, GAME_H)
        self.data = None
        self._roster = []        # [warpc_idx, ...] (与人物列表同序)
        self._rec_by_idx = {}
        self._skill_by_idx = {}
        self._current = -1
        self._window = []        # 左侧列表当前显示的 warpc_idx 窗口 (≤6)
        self._image = None       # 渲染结果 QPixmap
        # 技能页状态 (对应游戏 a1[614866]=焦点 0-3分类/4-9槽, a1[614891]=列表选中行)
        self._page = 0           # 0=状态, 1=技能, 2=物品, 4=队伍
        self._skill_cat = 1      # 当前分类 0-3 (默认主动技能)
        self._skill_focus = 1    # 焦点: 0-3=分类页签, 4-9=右侧槽
        self._skill_sel = 0
        self._skill_scroll = 0
        self._skill_rows = []    # [(skill_idx, learn_state), ...] 当前分类
        # 物品页状态 (对应游戏 a1[614867]=分类, a1[614891]=页内选中行)
        self._item_cat = 0
        self._item_sel = 0
        self._item_scroll = 0
        # 物品说明弹窗: 右键按住即时显示 (游戏内 hold 右键立即弹出说明, 松开消失, 无延时)
        self._tooltip_item = -1   # 当前显示说明的物品全局索引 (-1=不显示)
        # 队伍页状态 (对应游戏 a1[614869]=子页签 0团队/1记事/2功绩/3历史, a1[614900]=页码)
        self._team_tab = 0
        self._journal_page = 0
        self._txt_queue = []     # 文字绘制队列 (精灵画完后统一按 FONT9696 像素混合)
        self._font = QFont("SimSun")
        self._font.setPixelSize(24)
        self.setCursor(Qt.PointingHandCursor)

    # ── 数据 ──

    def set_data(self, data):
        self.data = data
        self._rec_by_idx = {r['index']: r for r in data.warpc_recs}
        self._skill_by_idx = {r['index']: r for r in data.skill_recs}
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
        self._skill_sel = 0
        self._skill_scroll = 0
        self._refresh()

    def view_state(self):
        """页面/子页签状态快照 (角色切换重建视图时由 CharTab 保持)"""
        return {'page': self._page, 'skill_cat': self._skill_cat,
                'skill_focus': self._skill_focus, 'team_tab': self._team_tab,
                'journal_page': self._journal_page, 'item_cat': self._item_cat,
                'item_sel': self._item_sel, 'item_scroll': self._item_scroll}

    def restore_state(self, state):
        if not state:
            return
        self._page = state.get('page', 0)
        self._skill_cat = state.get('skill_cat', 1)
        self._skill_focus = state.get('skill_focus', 1)
        self._team_tab = state.get('team_tab', 0)
        self._journal_page = state.get('journal_page', 0)
        self._item_cat = state.get('item_cat', 0)
        self._item_sel = state.get('item_sel', 0)
        self._item_scroll = state.get('item_scroll', 0)

    def _refresh(self):
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

    def _text(self, p, x, y, text, color_idx=16, px=24, shadow=False):
        """文字入队 (精灵绘制完毕后由 _flush_texts 统一按 FONT9696 管线渲染)。

        px 对应 sub_44B04C 字号 (菜单 FTYPE2@24 / 说明 FTYPE0@16); 全角 +px, ASCII 半宽 +px/2。
        shadow 复刻 sub_44AF7C a7 (选中行文字阴影, sub_44C6A4 右下膨胀)。
        """
        self._txt_queue.append(('t', x, y, text, color_idx, px, shadow))

    def _rich(self, x, y, raw, color_idx=16, px=16, ftype=0, max_y=None):
        """TKT 原始字节流入队 (0x1E 换行 + FCOLOR/FSIZE/FTYPE/FRESET 控制码, 空格占位)"""
        if raw:
            self._txt_queue.append(('r', x, y, raw, color_idx, px, ftype, max_y))

    def _expand_macros(self, raw, depth=0):
        """复刻 sub_409C60 宏展开: 0x14 TEXT引用 / 0x15,0x16 变量 / 0x1D NAME 玩家名。
        控制码 0x01/0x02/0x04/0x05 与 0x1E 原样保留 (交给 draw_rich)。"""
        out = bytearray()
        i, n = 0, len(raw)
        while i < n:
            b = raw[i]
            if b == 0x14 and i + 2 < n:            # TEXT: 2字节 TKT id → 递归展开
                tid = raw[i + 1] | (raw[i + 2] << 8)
                if depth < 2:
                    out += self._expand_macros(self.data.tkt_raw_bytes(tid), depth + 1)
                i += 3
                continue
            if b in (0x15, 0x16) and i + 1 < n:    # VARNUM/VARTXT: 运行时变量, 静态置空
                i += 2
                continue
            if b == 0x1D and i + 1 < n:            # NAME: 玩家名两段 (755B6C/755B64), 静态用默认名
                if raw[i + 1] == 1:
                    out += "主角".encode('big5')   # NAME,2 为姓名第二段, 避免重复置空
                i += 2
                continue
            if b in (0x01, 0x02, 0x05) and i + 1 < n:
                out += raw[i:i + 2]
                i += 2
                continue
            if b == 0x04 and i + 1 < n:
                out += raw[i:i + 2]
                i += 2
                continue
            if b == 0x03 and i + 3 < n:
                out += raw[i:i + 4]
                i += 4
                continue
            if b >= 0x80 and i + 1 < n:
                out += raw[i:i + 2]
                i += 2
                continue
            out.append(b)
            i += 1
        return bytes(out)

    @staticmethod
    def _strip_controls(raw):
        """剥控制码 → 纯文本 (SimSun 兜底渲染用)"""
        out = bytearray()
        i, n = 0, len(raw)
        while i < n:
            b = raw[i]
            if b in (0x01, 0x02, 0x04, 0x05):
                i += 2
            elif b == 0x03:
                i += 4
            elif b == 0x1E:
                out.append(0x0A)
                i += 1
            elif b < 0x20:
                i += 1
            elif b >= 0x80 and i + 1 < n:
                out += raw[i:i + 2]
                i += 2
            else:
                out.append(b)
                i += 1
        try:
            return out.replace(b'\x0a', b'\n').decode('big5', errors='replace')
        except Exception:
            return ""

    def _game_font(self):
        """FONT9696 渲染器 (懒加载, 挂 GameData 缓存; 缺失返回 None → SimSun 兜底)"""
        c = self._cache()
        if 'gf' not in c:
            c['gf'] = load_game_font(self.data.paths.get("FONT9696")
                                     or self.data.game_dir)
        return c['gf']

    def _flush_texts(self, pixmap):
        """将排队文字渲染到 pixmap: FONT9696 像素混合; 字库缺失时 SimSun 描边兜底"""
        if not self._txt_queue:
            return pixmap
        queue, self._txt_queue = self._txt_queue, []
        gf = self._game_font()
        if gf is None:
            painter = QPainter(pixmap)
            for op in queue:
                if op[0] == 't':
                    _k, x, y, text, color_idx, px, _shadow = op
                    self._text_fallback(painter, x, y, text, color_idx, px)
                else:
                    _k, x, y, raw, color_idx, px, _ft, _my = op
                    for li, line in enumerate(self._strip_controls(raw).split('\n')):
                        self._text_fallback(painter, x, y + px * li, line, color_idx, px)
            painter.end()
            return pixmap
        img = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        pal = {i: (c.red(), c.green(), c.blue()) for i, c in GAME_COLORS.items()}
        for op in queue:
            if op[0] == 't':
                _k, x, y, text, color_idx, px, shadow = op
                col = GAME_COLORS.get(color_idx, GAME_COLORS[16])
                ftype = 0 if px == 16 else 2   # 说明文字 FTYPE0, 菜单 FTYPE2 (sub_44AF7C 调用点)
                gf.draw_text(img, x, y, text, (col.red(), col.green(), col.blue()),
                             size=px, ftype=ftype, shadow=shadow)
            else:
                _k, x, y, raw, color_idx, px, ftype, max_y = op
                gf.draw_rich(img, x, y, raw, pal, color_idx=color_idx,
                             size=px, ftype=ftype, max_y=max_y)
        return QPixmap.fromImage(img)

    def _text_fallback(self, p, x, y, text, color_idx=16, px=24):
        """SimSun 描边兜底 (FONT9696 缺失时): 全角 px / 半角 px/2"""
        col = GAME_COLORS.get(color_idx, GAME_COLORS[16])
        font = self._font
        if px != 24:
            font = QFont("SimSun")
            font.setPixelSize(px)
        p.setFont(font)
        fm = QFontMetrics(font)
        baseline = y + fm.ascent() - 2
        cx = x
        for ch in text:
            adv = px if ord(ch) > 0xFF else px // 2
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

    # ── 静态底图 (跨角色复用): 背景 + 页签 + 面板 + 固定标签 ──

    def _static_base(self, page):
        c = self._cache()
        key = ('base', page)
        if key in c:
            return c[key]
        bg = self._background()
        base = QPixmap(GAME_W, GAME_H)
        base.fill(QColor(0, 0, 0))
        p = QPainter(base)
        if bg:
            p.drawPixmap(0, 0, bg)
        # 顶部页签 (41762C L120-126): 选中页 → 帧 74+j, 其余 68+j
        for j in range(6):
            self._blit(p, self._mu_pix((74 + j) if j == page else (68 + j)), 209 + 72 * j, 6)
        if page == 0:
            # 状态页面板 (417F84 L21-24): 帧 10/8/9 半透明, 帧 7 不透明
            self._blit(p, self._mu_pix(10), 460, 61, 15)
            self._blit(p, self._mu_pix(8), 209, 45, 10)
            self._blit(p, self._mu_pix(9), 214, 55, 13)
            self._blit(p, self._mu_pix(7), 210, 50)
            # 装备槽标签 (417F84 L32): 帧 62武/64防/66饰/66饰
            for i, fr in enumerate((62, 64, 66, 66)):
                self._blit(p, self._mu_pix(fr), 450, 80 + 35 * i)
            # 技能槽标签 (417F84 L50): 帧 58,58,59,59,60,61
            for i, fr in enumerate(SLOT_CAT_FRAMES):
                self._blit(p, self._mu_pix(fr), 450, 240 + 36 * i)
            # 属性标签 (417F84 L61-76): 核心色21青, 八属性+技能点数色20绿
            for label, y in CORE_ROWS:
                self._text(p, 220, y, label, 21)
            for label, y, _fi in STAT_ROWS:
                self._text(p, 220, y, label, 20)
            self._text(p, 220, 428, "技能點數:", 20)
        elif page == 1:
            # 技能页面板 (418EE8 L17-23): 16/8/11/12/13/14 半透明, 帧 7 不透明
            self._blit(p, self._mu_pix(16), 247, 67, 15)
            self._blit(p, self._mu_pix(8), 209, 45, 10)
            self._blit(p, self._mu_pix(7), 210, 50)
            self._blit(p, self._mu_pix(11), 214, 55, 13)
            self._blit(p, self._mu_pix(12), 220, 139, 15)
            self._blit(p, self._mu_pix(13), 452, 303, 15)
            self._blit(p, self._mu_pix(14), 335, 59, 15)
            # 右侧6槽 分类图标 + 名字底条 (418EE8 L33-34)
            for i, fr in enumerate(SLOT_CAT_FRAMES):
                self._blit(p, self._mu_pix(fr), 445, 35 * i + 65)
                self._blit(p, self._mu_pix(15), 485, 35 * i + 69, 10)
        elif page == 2:
            # 物品页 (419704): 分类栏帧25 + 列表面板帧33 (均不透明) + 底栏帧26(a10) + 金钱帧206
            self._blit(p, self._mu_pix(25), 221, 48)
            self._blit(p, self._mu_pix(33), 216, 85)
            self._blit(p, self._mu_pix(26), 246, 428, 10)
            self._blit(p, self._mu_pix(206), 450, 430)
            # 金钱 (419704 L15-17: 色19黄, "      %-d"; 运行时数据 → 静态查看显示 0)
            self._text(p, 450, 440, "      0", 19)
        # page 4 (队伍): 面板随子页签变化, 全部在 _draw_team_page 动态绘制
        p.end()
        base = self._flush_texts(base)
        c[key] = base
        return base

    # ── 技能页数据 (对应游戏进入分类时构建的 a1[614873..] 列表) ──

    def _build_skill_rows(self, f):
        """当前分类的可学习技能行: [(skill_idx, learn_state>0), ...] 按索引升序"""
        cat = self._skill_cat
        rows = []
        limit = min(SKILL_LEARN_COUNT, len(self.data.skill_recs) or SKILL_LEARN_COUNT)
        for si in range(limit):
            v = get_packed_byte(f, SKILL_LEARN_BASE, si)
            if v <= 0:
                continue
            rec = self._skill_by_idx.get(si)
            if rec is None:
                continue
            if cat is not None and rec['vals'][2] != cat:
                continue
            rows.append((si, v))
        return rows

    def _desc_skill_idx(self, f):
        """说明面板显示的技能: 焦点在右侧槽 → 槽技能; 否则列表选中行"""
        if self._skill_focus >= 4:
            sid = f[SKILL_SLOT_IDX[self._skill_focus - 4]]
            return sid if sid > 0 else -1
        if 0 <= self._skill_sel < len(self._skill_rows):
            return self._skill_rows[self._skill_sel][0]
        return -1

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
        img = QPixmap(self._static_base(self._page))
        p = QPainter(img)
        self._draw_roster(p)
        if self._page == 0:
            self._draw_status_page(p, f)
        elif self._page == 1:
            self._draw_skill_page(p, f)
        elif self._page == 2:
            self._draw_item_page(p, f)
        elif self._page == 4:
            self._draw_team_page(p, f)
        p.end()
        self._image = self._flush_texts(img)
        if self._page == 2:
            # 物品说明弹窗作为最顶层覆盖 (在列表文字之上, 避免被物品名压住)
            self._image = self._overlay_item_tooltip(self._image)

    def _draw_roster(self, p):
        """左侧列表 (41762C): 行高 79px, 选中行帧0边框+黄名字, 未选中行暗化"""
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
                # 选中行文字带阴影 (41762C L30: sub_44AF7C(...,1,1))
                self._text(p, 80, 79 * row + 4, name, 19, shadow=True)
                self._text(p, 80, 79 * row + 27, "生命:", 20, shadow=True)
                self._text(p, 80, 79 * row + 50, "內力:", 21, shadow=True)
                self._text(p, 80, 79 * row + 27, f"     {rf[5]}", hp_c, shadow=True)
                self._text(p, 80, 79 * row + 50, f"     {rf[6]}", mp_c, shadow=True)
                self._blit(p, self._portrait_pix(rf), 7, 79 * row + 4)
            else:
                self._text(p, 76, 79 * row + 8, name, 16)
                self._text(p, 80, 79 * row + 27, "生命:", 16)
                self._text(p, 80, 79 * row + 50, "內力:", 16)
                self._text(p, 80, 79 * row + 27, f"     {rf[5]}", hp_c)
                self._text(p, 80, 79 * row + 50, f"     {rf[6]}", mp_c)
                self._blit(p, self._mu_pix(0), 3, 79 * row + 7, 10)
                self._blit(p, self._portrait_pix(rf), 3, 79 * row + 8, 15)

    def _draw_status_page(self, p, f):
        """状态页动态内容 (sub_417F84 + sub_4188D4)"""
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

    def _draw_skill_page(self, p, f):
        """技能页动态内容 (sub_418EE8 + sub_418C90 + sub_418E5C)"""
        self._skill_rows = self._build_skill_rows(f)
        n = len(self._skill_rows)
        self._skill_scroll = max(0, min(self._skill_scroll, max(0, n - SKILL_LIST_VISIBLE)))
        self._skill_sel = max(0, min(self._skill_sel, n - 1)) if n else -1

        # 右侧6槽: 光标 (418EE8 L31-33, 帧20静态, 先画光标再补画图标 → 光标为高亮底)
        for i, fi in enumerate(SKILL_SLOT_IDX):
            if self._skill_focus == i + 4:
                self._blit(p, self._mu_pix(20), 443, 35 * i + 65)
                self._blit(p, self._mu_pix(SLOT_CAT_FRAMES[i]), 445, 35 * i + 65)
            sid = f[fi]
            if sid > 0:
                nm = self.data.skill_name(sid)
                if nm:
                    self._text(p, 486, 35 * i + 70, nm, 16)

        # 4 分类页签 (418EE8 L44-56): 选中 → 光标帧20; 未选中 → 帧17 暗化叠加
        for i in range(4):
            if self._skill_focus == i:
                self._blit(p, self._mu_pix(20), 42 * i + 219, 98)
                self._blit(p, self._mu_pix(58 + i), 42 * i + 220, 99)
            else:
                self._blit(p, self._mu_pix(58 + i), 42 * i + 220, 99)
                self._blit(p, self._mu_pix(17), 42 * i + 220, 99, 15)

        # 技能点数 (418EE8 L57: "技能點數%6d" @ 235,60)
        self._text(p, 235, 60, f"技能點數{f[31]:6d}")

        # 技能列表 (418C90): 选中条帧80, 学习消耗 = jp_cost×(250-悟性)/200
        vis = self._skill_rows[self._skill_scroll:self._skill_scroll + SKILL_LIST_VISIBLE]
        for row, (si, state) in enumerate(vis):
            gi = self._skill_scroll + row
            selected = (gi == self._skill_sel and self._skill_focus < 4)
            if selected:
                self._blit(p, self._mu_pix(80), 228, 31 * row + 143, 15)
            col = 1 if state >= 20 else (2 if selected else 16)
            nm = self.data.skill_name(si) or f"技能#{si}"
            if self._skill_focus < 4:
                rec = self._skill_by_idx.get(si)
                cost = rec['vals'][3] * (250 - f[26]) // 200 if rec else 0
                # "%-10.10s%4d" 单流排版: 名字按字节截断/补空格到 10 字节,
                # 空格半宽步进 → 消耗位置随名字全/半角构成浮动 (同 wvsprintfA)
                self._text(p, 240, 31 * row + 145, f"{self._pad10(nm)}{cost:4d}", col)
            else:
                self._text(p, 240, 31 * row + 145, nm, col)

        # 翻页箭头 (417F0C @ 390,98): 帧21 上 / 帧22 下 (+20,+5)
        if self._skill_scroll > 0:
            self._blit(p, self._mu_pix(21), 390, 98)
        if self._skill_scroll + SKILL_LIST_VISIBLE < n:
            self._blit(p, self._mu_pix(22), 410, 103)

        # 技能说明 (418E5C: 字号16 FTYPE0 @ 453,305; 原始字节流含 0x1E 分行/FCOLOR 控制码)
        sid = self._desc_skill_idx(f)
        rec = self._skill_by_idx.get(sid) if sid >= 0 else None
        if rec:
            raw = self._expand_macros(self.data.tkt_raw_bytes(rec['vals'][1]))
            self._rich(453, 305, raw, 16, px=16, ftype=0, max_y=452)

    # ── 物品页 (sub_419704 / sub_419458 / sub_4195C4) ──

    def _build_item_rows(self, cat):
        """当前分类的全部物品 [(rec_index, vals), ...] (过滤 field[1]==cat, 空槽同 tab_item)"""
        c = self._cache()
        key = ('items', cat)
        if key not in c:
            rows = []
            for rec in self.data.item_recs:
                vals = rec['vals']
                if vals[0] in (0, 1) or vals[2] <= 0 or vals[1] != cat:
                    continue
                if not tkt_first_line(self.data.tkt, vals[2]):
                    continue
                rows.append((rec['index'], vals))
            c[key] = rows
        return c[key]

    def _draw_item_page(self, p, f):
        """物品页动态内容 (sub_419704 分类高亮 + sub_419458 列表 + sub_4195C4 说明框)"""
        cat = self._item_cat
        # 分类高亮 (419704 L14): 帧 cat+27 @ (61*cat+229, 54)
        self._blit(p, self._mu_pix(cat + 27), 61 * cat + 229, 54)

        rows = self._build_item_rows(cat)
        n = len(rows)
        # 滚动与选中相互独立 (同技能页): 仅做边界钳制, 不因选中强制回拉滚动位置
        self._item_scroll = max(0, min(self._item_scroll, max(0, n - ITEM_LIST_VISIBLE)))
        self._item_sel = max(0, min(self._item_sel, n - 1)) if n else -1

        # 列表 (419458): 行高31, 图标@235 名字@285, 选中条帧81@281 (色2选中/色16默认)
        vis = rows[self._item_scroll:self._item_scroll + ITEM_LIST_VISIBLE]
        for r, (ridx, vals) in enumerate(vis):
            gi = self._item_scroll + r
            selected = (gi == self._item_sel)
            if selected:
                self._blit(p, self._mu_pix(81), 281, 31 * r + 103, 15)
            self._blit(p, self._mu_pix(vals[4] + 130), 235, 31 * r + 105)
            nm = tkt_first_line(self.data.tkt, vals[2]) or f"#{ridx}"
            self._text(p, 285, 31 * r + 105, nm, 2 if selected else 16)

        # 翻页箭头 (417F0C @ 598,48): 帧21 上 / 帧22 下 (+20,+5)
        if self._item_scroll > 0:
            self._blit(p, self._mu_pix(21), 598, 48)
        if self._item_scroll + ITEM_LIST_VISIBLE < n:
            self._blit(p, self._mu_pix(22), 618, 53)
        # 说明弹窗不在此绘制: 由 _overlay_item_tooltip 在文字 flush 之后作为最顶层覆盖

    def _overlay_item_tooltip(self, pixmap):
        """物品说明弹窗最顶层覆盖 (4195C4): 右键长按时显示, 层级高于列表文字。

        帧158 提示框 + 说明文本(字段3)。位置随长按物品的可见行: v5=Y+31, 靠底(>360)则 Y-139。
        """
        if self._page != 2 or self._tooltip_item < 0:
            return pixmap
        rows = self._build_item_rows(self._item_cat)
        if not (0 <= self._tooltip_item < len(rows)):
            return pixmap
        sel_row = self._tooltip_item - self._item_scroll
        if not (0 <= sel_row < ITEM_LIST_VISIBLE):
            return pixmap   # 物品已滚出可见区
        yy = 31 * sel_row + 103
        v5 = yy + 31 if yy + 31 <= 360 else yy - 139
        p = QPainter(pixmap)
        self._blit(p, self._mu_pix(158), 252, v5)
        p.end()
        raw = self._expand_macros(self.data.tkt_raw_bytes(rows[self._tooltip_item][1][3]))
        self._rich(262, v5 + 8, raw, 16, px=16, ftype=0, max_y=v5 + 113)
        return self._flush_texts(pixmap)

    # ── 队伍页 (sub_41A080) ──

    def _team_members(self):
        """团队构成: 当前选中人物 + 上方2人 + 下方2人 (花名册邻居, 边缘截断≤5)"""
        if self._current not in self._roster:
            return [self._current]
        pos = self._roster.index(self._current)
        return self._roster[max(0, pos - 2):pos + 3]

    def _journal_entries(self, kind):
        """记事(1)/功绩(2) 全部有值条目 [(tkt_id, 宏展开原始字节), ...] (静态按 TKT 分段)"""
        c = self._cache()
        key = ('journal', kind)
        if key not in c:
            lo = JOURNAL_TKT_BASE + (kind - 1) * JOURNAL_TKT_SPAN
            hi = lo + JOURNAL_TKT_SPAN - 1
            entries = []
            for tid in range(lo, hi + 1):
                txt = tkt_full_text(self.data.tkt, tid)
                if txt and txt.strip():
                    entries.append((tid, self._expand_macros(self.data.tkt_raw_bytes(tid))))
            c[key] = entries
        return c[key]

    def _draw_team_page(self, p, f):
        """队伍页 (41A080): 子页签 0团队 / 1记事 / 2功绩 / 3历史"""
        tab = self._team_tab
        if tab == 0:
            # 团队面板 (L38-42): 42/39/40/41 半透明 + 页签高亮49
            self._blit(p, self._mu_pix(42), 365, 210, 15)
            self._blit(p, self._mu_pix(39), 210, 55, 15)
            self._blit(p, self._mu_pix(40), 220, 94, 15)
            self._blit(p, self._mu_pix(41), 430, 97, 15)
            self._blit(p, self._mu_pix(49), 215, 56, 10)
            members = self._team_members()
            for i in range(5):
                if i < 4:
                    self._blit(p, self._mu_pix(50 + i), 60 * i + 215, 56)
                self._blit(p, self._mu_pix(43), 420, 35 * i + 270, 15)
                if i < len(members):
                    r = self._rec_by_idx.get(members[i])
                    if r is not None:
                        nm = self.data.char_name(r) or f"#{members[i]}"
                        self._text(p, 425, 35 * i + 273, nm, 16)
                        self._text(p, 518, 35 * i + 273, f"{r['fields'][2]:3d}", 16)
                self._blit(p, self._mu_pix(44), 560, 35 * i + 270, 15)
                self._blit(p, self._mu_pix(54), 560, 35 * i + 270)
            # 战绩统计 (L61-67, 存档运行时数据, 静态查看显示 0)
            for label, y in TEAM_STAT_LEFT:
                self._text(p, 230, y, f"{label}{0:5d}", 16)
            for label, y, suffix in TEAM_TASK_ROWS:
                self._text(p, 230, y, f"{label}{0:5d}{suffix}", 16)
            # 团队聚合属性 (L68-71 + 422A5C): Σ队员属性, 前三钳≥0, 医术封顶100
            for label, y, fi in TEAM_ATTR_RIGHT:
                total = sum(self._rec_by_idx[m]['fields'][fi]
                            for m in members if m in self._rec_by_idx)
                total = min(total, 100) if fi == 30 else max(total, 0)
                self._text(p, 440, y, f"{label}{total:5d}", 16)
            return

        # 记事/功绩/历史 共用面板 (L26-28): 55/39/56 半透明 + 4子页签
        self._blit(p, self._mu_pix(55), 290, 140, 15)
        self._blit(p, self._mu_pix(39), 210, 55, 15)
        self._blit(p, self._mu_pix(56), 217, 92, 15)
        for i in range(4):
            if tab == i:
                self._blit(p, self._mu_pix(49), 60 * i + 215, 56, 10)
            self._blit(p, self._mu_pix(50 + i), 60 * i + 215, 56)

        if tab in (1, 2):
            # 记事/功绩列表 (L73-99): 每页3条 @ y=108/225/339, 分隔条帧57, 页码 %3d/%3d
            # 条目 = 宏展开后的原始字节流 (44E49C 富文本: 0x1E 分行/FCOLOR/空格占位)
            entries = self._journal_entries(tab)
            pages = max(1, (len(entries) + JOURNAL_PER_PAGE - 1) // JOURNAL_PER_PAGE)
            self._journal_page = max(0, min(self._journal_page, pages - 1))
            start = self._journal_page * JOURNAL_PER_PAGE
            page_entries = entries[start:start + JOURNAL_PER_PAGE]
            slot_max_y = (210, 325, 452)   # 裁剪到下一分隔条/面板底
            for slot, y in enumerate((108, 225, 339)):
                if slot < len(page_entries):
                    self._rich(237, y, page_entries[slot][1], 16, px=16,
                               ftype=0, max_y=slot_max_y[slot])
            self._blit(p, self._mu_pix(57), 250, 210)
            self._blit(p, self._mu_pix(57), 250, 325)
            # 翻页箭头 (417F0C @ 460,50) + 页码
            if self._journal_page > 0:
                self._blit(p, self._mu_pix(21), 460, 50)
            if self._journal_page < pages - 1:
                self._blit(p, self._mu_pix(22), 480, 55)
            if entries:
                self._text(p, 525, 60, f"{self._journal_page + 1:3d}/{pages:3d}", 16)
        else:
            # 历史 (L101-108): 当前选中人物历史原始字节流 (TKT 9050+序号 / 补丁字段[262])
            rec = self._rec_by_idx.get(self._current)
            if rec is not None:
                hid = rec['fields'][262]           # 补丁字段 [262] 覆盖历史文本ID
                if hid == 0:
                    hid = 9050 + rec['index']
                raw = self._expand_macros(self.data.tkt_raw_bytes(hid))
                self._rich(237, 108, raw, 16, px=16, ftype=0, max_y=452)

    @staticmethod
    def _pad10(name):
        """复刻 C "%-10.10s" 字节语义: Big5 全角 2 字节, 截断/补 ASCII 空格到 10 字节"""
        w, out = 0, ""
        for ch in name:
            cw = 2 if ord(ch) > 0xFF else 1
            if w + cw > 10:
                break
            out += ch
            w += cw
        return out + " " * (10 - w)

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
        pos = event.position().toPoint()
        x, y = pos.x(), pos.y()

        # 右键: 物品页按住即时显示说明弹窗 (游戏内 hold 右键立即弹出, 松开消失, 无延时)
        if event.button() == Qt.RightButton:
            if self._page == 2:
                gi = self._item_at(pos)
                if gi >= 0 and gi != self._tooltip_item:
                    self._tooltip_item = gi
                    self._refresh()
            return

        # 左侧列表行 (行区域同帧0边框: x 3..205, 高 79)
        if x <= 205:
            row = (y - 3) // 79
            if 0 <= row < len(self._window):
                widx = self._window[row]
                if widx != self._current:
                    self.charClicked.emit(widx)
            return

        # 顶部页签 (209+72j, 6, 68x32): 状态/技能/物品/队伍可切换
        if 6 <= y <= 40 and x >= 209:
            j = (x - 209) // 72
            if j in (0, 1, 2, 4) and j != self._page:
                self._page = j
                self._refresh()
            return

        if self._page == 4:
            self._team_mouse(x, y)
            return

        if self._page == 2:
            self._item_mouse(x, y)
            return

        if self._page != 1:
            return

        # 技能页: 分类页签 (220+42i, 99, 39x38)
        if 99 <= y <= 137 and 219 <= x < 219 + 42 * 4:
            i = (x - 219) // 42
            if 0 <= i <= 3 and (self._skill_focus != i or self._skill_cat != i):
                self._skill_cat = i
                self._skill_focus = i
                self._skill_sel = 0
                self._skill_scroll = 0
                self._refresh()
            return

        # 技能页: 右侧6槽 (443.., 65+35i, 高35)
        if x >= 443 and 65 <= y < 65 + 35 * 6:
            i = (y - 65) // 35
            if self._skill_focus != i + 4:
                self._skill_focus = i + 4
                self._refresh()
            return

        # 技能页: 翻页箭头 (390,98,20x30 上 / 410,103,20x30 下)
        if 390 <= x < 410 and 98 <= y < 128:
            self._scroll_skill(-SKILL_LIST_VISIBLE)
            return
        if 410 <= x < 430 and 103 <= y < 133:
            self._scroll_skill(SKILL_LIST_VISIBLE)
            return

        # 技能页: 列表行 (228..426, 143+31r, 行高31)
        if 228 <= x <= 426 and y >= 143:
            row = (y - 143) // 31
            if 0 <= row < SKILL_LIST_VISIBLE:
                gi = self._skill_scroll + row
                if gi < len(self._skill_rows):
                    self._skill_focus = self._skill_cat  # 焦点回到列表所属分类
                    self._skill_sel = gi
                    self._refresh()
            return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # 右键松开: 隐藏物品说明弹窗
        if event.button() == Qt.RightButton:
            if self._tooltip_item >= 0:
                self._tooltip_item = -1
                self._refresh()
            return
        super().mouseReleaseEvent(event)

    def _item_at(self, pos):
        """物品列表行命中 → 全局物品索引 (无则 -1); 行区域 235..632, y=105+31r, 10 行"""
        x, y = pos.x(), pos.y()
        if 235 <= x <= 632 and y >= 105:
            row = (y - 105) // 31
            if 0 <= row < ITEM_LIST_VISIBLE:
                gi = self._item_scroll + row
                if gi < len(self._build_item_rows(self._item_cat)):
                    return gi
        return -1

    def wheelEvent(self, event):
        if self._page == 1:
            self._scroll_skill(-3 if event.angleDelta().y() > 0 else 3)
            event.accept()
            return
        if self._page == 2:
            self._scroll_item(-3 if event.angleDelta().y() > 0 else 3)
            event.accept()
            return
        if self._page == 4 and self._team_tab in (1, 2):
            self._flip_journal(-1 if event.angleDelta().y() > 0 else 1)
            event.accept()
            return
        super().wheelEvent(event)

    def _scroll_skill(self, delta):
        n = len(self._skill_rows)
        new = max(0, min(self._skill_scroll + delta, max(0, n - SKILL_LIST_VISIBLE)))
        if new != self._skill_scroll:
            self._skill_scroll = new
            self._refresh()

    # ── 物品页交互 ──

    def _item_mouse(self, x, y):
        # 分类栏 (61*cat+229, 54, 56x24): 6 分类
        if 48 <= y <= 78 and 229 <= x < 229 + 61 * ITEM_CATEGORIES:
            i = (x - 229) // 61
            if 0 <= i < ITEM_CATEGORIES and i != self._item_cat:
                self._item_cat = i
                self._item_sel = 0
                self._item_scroll = 0
                self._refresh()
            return
        # 翻页箭头 (598,48,20x30 上一页 / 618,53,20x30 下一页)
        if 598 <= x < 618 and 48 <= y < 78:
            self._scroll_item(-ITEM_LIST_VISIBLE)
            return
        if 618 <= x < 638 and 53 <= y < 83:
            self._scroll_item(ITEM_LIST_VISIBLE)
            return
        # 列表行 (235..632, 105+31r, 行高31, 10 行)
        if 235 <= x <= 632 and y >= 105:
            row = (y - 105) // 31
            if 0 <= row < ITEM_LIST_VISIBLE:
                gi = self._item_scroll + row
                if gi < len(self._build_item_rows(self._item_cat)) and gi != self._item_sel:
                    self._item_sel = gi
                    self._refresh()
            return

    def _scroll_item(self, delta):
        n = len(self._build_item_rows(self._item_cat))
        new = max(0, min(self._item_scroll + delta, max(0, n - ITEM_LIST_VISIBLE)))
        if new != self._item_scroll:
            self._item_scroll = new
            self._refresh()

    # ── 队伍页交互 ──

    def _team_mouse(self, x, y):
        # 子页签 (215+60i, 56, 62x30): 团队/记事/功绩/历史
        if 56 <= y <= 86 and 215 <= x < 215 + 60 * 4:
            i = (x - 215) // 60
            if 0 <= i <= 3 and self._team_tab != i:
                self._team_tab = i
                self._journal_page = 0
                self._refresh()
            return
        # 记事/功绩: 翻页箭头 (460,50,20x30 上一页 / 480,55,20x30 下一页)
        if self._team_tab in (1, 2):
            if 460 <= x < 480 and 50 <= y < 80:
                self._flip_journal(-1)
                return
            if 480 <= x < 500 and 55 <= y < 85:
                self._flip_journal(1)
                return
        # 团队: 队员行 (420.., 270+35i, 高35) → 切换选中角色
        if self._team_tab == 0 and x >= 420 and 270 <= y < 270 + 35 * 5:
            members = self._team_members()
            i = (y - 270) // 35
            if i < len(members) and members[i] != self._current:
                self.charClicked.emit(members[i])
            return

    def _flip_journal(self, delta):
        entries = self._journal_entries(self._team_tab) if self._team_tab in (1, 2) else []
        pages = max(1, (len(entries) + JOURNAL_PER_PAGE - 1) // JOURNAL_PER_PAGE)
        new = max(0, min(self._journal_page + delta, pages - 1))
        if new != self._journal_page:
            self._journal_page = new
            self._refresh()
