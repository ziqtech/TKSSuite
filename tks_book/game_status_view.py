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
  sub_419B54 — 装备页: 面板38/34/35 + 4装备槽(帧62/64/66,39px步进) + 分类高亮(帧29-31)
  sub_419A24 — 装备列表: 12行/页, 行高31, 图标(字段4+130)@225, 名字@265, 选中条帧82
  sub_419D9C — 换装属性预览: 8属性差值@(486,240+28i) + 升降箭头(帧36/37)@610
  sub_422268 — 换装差值计算: 悬停物品加成(字段11-18) - 当前槽装备加成
  sub_419850 — 装备列表构建: 按槽分类(字段1=2/3/4)+职业掩码(字段5), 每页 12 项
  sub_41A080 — 队伍页: 4子页签(帧50-53, 60px步进) + 团队(5成员/战绩统计)
               + 记事/功绩(每页3条, TKT=11201+序号) + 历史(TKT 9050+序号)
  sub_41A7A8 — 记事/功绩列表构建 (1000项标志数组, 1=记事 2=功绩, 页数=⌈n/3⌉)
  sub_422A5C — 团队聚合属性: Σ队员智慧/仁德/勇气/医术 (前三钳≥0, 医术封顶100)
  sub_41A940 — 系统页: 标题帧84 + 5系统选项行(帧85/87/94-98) + 音效/BGM 开关(帧99/100)
               + 滑块旋钮(帧vol+88) + 开关旋钮(帧86); 状态 word_755C74/76/78/7A
  sub_41FAAC — 系统页交互 case 5: "离开"(x=240-305, y=359-393) → word_4E8058=1 → 标题界面
  sub_425EAC — 加载 TitleMenu.gxp (标题界面背景, 按钮文字内嵌于位图, 无文字绘制)
  sub_425F3C — 标题界面 hover 检测: X∈[200,460], Y∈[44*(i-1)+290, 44*(i-1)+333]
  sub_426164 — 标题界面调度: hover 高亮 = Cur.JVG 帧 116/117/118 @ (200, 44*i+246)
  sub_426004 — 标题界面点击: 选项1新游戏→回主菜单 / 选项2继续→存档页读档 / 选项3离开→退出
  sub_417F0C — 翻页箭头: 帧21(x,y) / 帧22(x+20,y+5)
  sub_454D90 — 半透明混合公式 dst*(32-a)/32 + src*a/32 (alpha 10/13/15)
资源: mb.gxp (JGXP 头 + LZSS + RGB565 全屏 640×480), Mu.JVG (帧偏移 x_off/y_off),
      PFace.jvg (主角自定义头像, 受全局 USE_PFACE 开关控制, 默认不使用),
      TitleMenu.gxp (标题界面背景), Cur.JVG (标题按钮高亮帧 116-118)。
头像帧规则 (含 tks_launcher 补丁): f[261] 非零 → 帧 f[261]; 否则 f[1]+211;
      f[1]==0 时: USE_PFACE=True → PFace 帧 0, 默认(False) → Mu 帧 211。
      左侧列表头像受 USE_TABCHAR_PORTRAIT 全局开关控制 (默认 True):
      True → tab_char 逻辑取值 Fa.JVG 帧 f[1]*2 (70×70, 保持尺寸); False → 原游戏逻辑。
      存档/读档界面头像受 USE_SAVE_PORTRAIT 全局开关控制 (默认 True):
      True → 按队伍头像逻辑取值 _portrait_pix (受 USE_TABCHAR_PORTRAIT 控制);
      False → 原游戏逻辑 Mu 帧 cid+211 (cid 为存档 team_ids 中的 warpc 索引)。
"""
import struct
import time

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from editor_utils.lzss import lzss_decompress_stream
from editor_utils.rgb565 import rgb565_to_rgba
from editor_utils.jvg_data import load_jvg

from book_loader import (
    SKILL_LEARN_BASE, SKILL_LEARN_COUNT, get_packed_byte,
    tkt_first_line, tkt_full_text, pil_to_qpixmap,
)
from game_font import load_game_font
from game_audio import GameAudio
from jinc2_shader import resize_jinc2_sharp

GAME_W, GAME_H = 640, 480

# 全局设置: 是否使用 PFace.jvg 作为主角自定义头像 (f[1]==0 时)
#   默认 False (不使用): f[1]==0 → Mu 帧 211
#   True: f[1]==0 → PFace 帧 0 (存在时), 兜底 Mu 帧 211 (游戏原版行为)
# 可用 set_use_pface() 运行时切换
USE_PFACE = False


def set_use_pface(flag):
    """运行时切换 PFace 使用开关 (True=使用 PFace 帧0, False=用 Mu 帧211)"""
    global USE_PFACE
    USE_PFACE = bool(flag)


# 全局设置: 游戏界面复刻左侧队伍列表头像是否按 tab_char 人物表格逻辑取值
#   默认 True: Fa.JVG 帧 f[1]*2 (70×70 大头像, 保持原头像尺寸)
#   False: 原游戏逻辑 (f[261] 非零 → Mu 帧 f[261]; f[1] → Mu 帧 f[1]+211;
#           f[1]==0 → PFace 帧0 / Mu 帧211)
# 可用 set_use_tabchar_portrait() 运行时切换
USE_TABCHAR_PORTRAIT = True


def set_use_tabchar_portrait(flag):
    """运行时切换左侧列表头像取值逻辑 (True=tab_char 逻辑 Fa.JVG f[1]*2,
    False=原游戏逻辑 Mu 帧)"""
    global USE_TABCHAR_PORTRAIT
    USE_TABCHAR_PORTRAIT = bool(flag)


# 全局设置: 存档/读档界面人物头像是否按队伍头像逻辑取值
#   默认 True: 按 _portrait_pix 取值 (受 USE_TABCHAR_PORTRAIT 控制,
#       True→Fa.JVG 帧 f[1]*2; False→原游戏逻辑 Mu 帧)
#   False: 原存档页逻辑 — Mu 帧 cid+211 (cid 为存档 team_ids 中的 warpc 索引)
# 可用 set_use_save_portrait() 运行时切换
USE_SAVE_PORTRAIT = True


def set_use_save_portrait(flag):
    """运行时切换存档/读档界面头像取值逻辑 (True=队伍头像逻辑 _portrait_pix,
    False=原游戏逻辑 Mu 帧 cid+211)"""
    global USE_SAVE_PORTRAIT
    USE_SAVE_PORTRAIT = bool(flag)

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

# 装备页 (sub_419B54/sub_419A24/sub_419D9C/sub_422268)
EQUIP_LIST_VISIBLE = 12   # 每页可见行数 (sub_419850 v7<11 → 12 项)
EQUIP_SLOT_CAT = (2, 3, 4, 4)  # 4 槽 → TKItem 分类 field[1] (武器/防具/饰品/饰品)
EQUIP_ATTR_LABELS = ["攻擊:", "防禦:", "命中:", "閃避:", "速度:", "幸運:", "悟性:", "移動:"]  # 换装差值 (字段11-18)

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
             'cur': None, 'cur_tried': False,
             'bg': None, 'bg_tried': False, 'mu_pix': {}, 'pface_pix': {},
             'cur_pix': {}, 'title_bg': None, 'title_bg_tried': False}
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
        self._roster_start = 0   # 左列表窗口起始索引 (滚轮翻动)
        self._rec_by_idx = {}
        self._skill_by_idx = {}
        self._current = -1
        self._window = []        # 左侧列表当前显示的 warpc_idx 窗口 (≤6)
        self._image = None       # 渲染结果 QPixmap
        # 技能页状态 (对应游戏 a1[614866]=焦点 0-3分类/4-9槽, a1[614891]=列表选中行)
        self._page = 0           # 0=状态, 1=技能, 2=物品, 3=装备, 4=队伍, 5=系统
        self._skill_cat = 1      # 当前分类 0-3 (默认主动技能)
        self._skill_focus = 1    # 焦点: 0-3=分类页签, 4-9=右侧槽
        self._skill_sel = 0
        self._skill_scroll = 0
        self._skill_rows = []    # [(skill_idx, learn_state), ...] 当前分类
        # 物品页状态 (对应游戏 a1[614867]=分类, a1[614891]=页内选中行)
        self._item_cat = 0
        self._item_sel = -1      # 选中跟随鼠标 (-1=鼠标不在物品行上, 不选中)
        self._item_scroll = 0
        # 物品说明弹窗: 右键按住即时显示 (游戏内 hold 右键立即弹出说明, 松开消失, 无延时)
        self._tooltip_item = -1   # 当前显示说明的物品全局索引 (-1=不显示)
        # 装备页状态 (对应游戏 a1[614868]=选中槽 0-3, a1[614891]=页内悬停行)
        self._equip_slot = 0     # 选中装备槽 → 决定列表分类
        self._equip_sel = -1     # 悬停物品 (-1=不悬停, 差值预览显示0)
        self._equip_scroll = 0
        # 队伍页状态 (对应游戏 a1[614869]=子页签 0团队/1记事/2功绩/3历史, a1[614900]=页码)
        self._team_tab = 0
        self._journal_page = 0
        # 团队子页选中成员行 (对应游戏 a1[614891], sub_42131C L86-92 画帧45 高亮;
        # hover 区域 sub_420730 case 4: x∈[562,618], y∈[271+35i, 299+35i])
        self._team_sel = -1
        # 系统页状态 (对应游戏 word_755C74/76/78/7A; 初值取自 sub_411624 初始化)
        #   word_755C78 = SE 开关 / word_755C7A = SE 音量(1-5)
        #   word_755C74 = BGM 开关 / word_755C76 = BGM 音量(1-5)
        self._se_on = True
        self._se_vol = 2
        self._bgm_on = True
        self._bgm_vol = 3
        # 存档页状态 (对应游戏 arglist[614953]=操作模式 / arglist[614900]=页码)
        #   进入存档页: save_mode=1(存档)/2(读档); 0=未激活 (主菜单)
        #   3 页 × 3 行 = 9 存档槽 (sub_41AB94)
        #   save_hover: 0=未选中, 2*row+1=存档按钮, 2*row+2=读档/取消按钮 (sub_41DC5C)
        self._save_mode = 0
        self._save_page = 0
        self._save_hover = 0
        # 标题界面状态 (sub_425EAC/sub_425F3C/sub_426004/sub_426164):
        #   系统页点"离开"(x=240-305,y=359-393) → word_4E8058=1 → 标题界面
        #   背景 TitleMenu.gxp (按钮文字内嵌位图); 3 按钮 X∈[200,460], Y∈[44*(i-1)+290, 44*(i-1)+333]
        #   hover 高亮 = Cur.JVG 帧 116/117/118 @ (200, 44*i+246); 点击: 1新游戏/2继续/3离开
        self._title_mode = False
        self._title_hover = 0      # 悬停选项 0=无, 1-3 (sub_425F3C)
        self._txt_queue = []     # 文字绘制队列 (精灵画完后统一按 FONT9696 像素混合)
        self._font = QFont("SimSun")
        self._font.setPixelSize(24)
        self._scale = 1.0        # 显示缩放 (1.0=640×480 原始尺寸)
        self._scaled_pixmap = None   # 缓存的 jinc2-sharp 缩放结果 QPixmap
        self._scaled_dirty = True    # 缩放缓存失效标志
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)   # 物品页选中跟随鼠标 (mouseMoveEvent 无需按键)

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
        self._roster_start = min(max(0, pos - 2), max(0, len(self._roster) - 6))
        self._rebuild_window()
        self._skill_sel = 0
        self._skill_scroll = 0
        # 音频状态同步 + BGM 启动 (游戏: 菜单期间 BGM 持续, sub_412BE8 播放 0000.mp3)
        self._sync_audio()
        self._refresh()

    def _rebuild_window(self):
        """根据 _roster_start 重建左列表窗口 (≤6 行)"""
        self._window = self._roster[self._roster_start:self._roster_start + 6]

    def _scroll_roster(self, delta, sfx=False):
        """滚轮翻动左列表花名册窗口 (delta=±1)"""
        n = len(self._roster)
        new = max(0, min(self._roster_start + delta, max(0, n - 6)))
        if new != self._roster_start:
            if sfx:
                self._sfx(3)
            self._roster_start = new
            self._rebuild_window()
            self._refresh()

    # ── 缩放 ──

    def set_scale(self, scale):
        """设置显示缩放 (1.0=原始 640×480)"""
        scale = max(0.1, scale)
        if abs(self._scale - scale) < 0.001:
            return
        self._scale = scale
        self._scaled_dirty = True   # 必须在 setFixedSize 之前置位 (setFixedSize 可能触发立即重绘)
        self._scaled_pixmap = None  # 清除旧缓存, 避免重绘时使用过期尺寸的 pixmap
        self.setFixedSize(int(GAME_W * scale), int(GAME_H * scale))
        self.update()

    def scale_factor(self):
        return self._scale

    def _game_pos(self, pos):
        """控件坐标 → 游戏坐标 (640×480 空间, 供鼠标事件用)"""
        s = self._scale
        if s == 1.0:
            return pos
        return QPoint(int(pos.x() / s), int(pos.y() / s))

    # ── 音频 (sub_451C38 音效 / sub_412BE8 BGM) ──

    def _audio(self):
        """GameAudio 实例 (挂 GameData 缓存, 跨角色视图重建复用)"""
        c = self._cache()
        if 'audio' not in c:
            a = GameAudio()
            a.load(self.data.game_dir)
            c['audio'] = a
        return c['audio']

    def _sfx(self, sfx_id=3):
        """播放点击音效 (sub_451C38, SSF.GRP 音轨, 受第二行开关控制)。

        音效 ID 为机器码 edx 实证 (Borland fastcall, 反编译 sub_451C38(0) 有误):
        3=翻页/头像行, 4=页签/系统页/切页, 6=列表行/存档按钮, 7=分类/槽/焦点/队伍,
        8=标题界面, 1=系统页离开。
        """
        self._audio().play_sfx(sfx_id)

    def _sync_audio(self):
        """视图音频状态 → 音频模块 (系统页两行: 第一行=BGM mp3, 第二行=音效 WAV)

        游戏: 第一行 word_755C78/7A → sub_44AC90/44ACE8/44AD18 (BGM, 图鉴 _se_*)
              第二行 word_755C74/76 → dword_A2C228/sub_451DF8 (音效, 图鉴 _bgm_*)
        BGM 仅在标题界面播放 (游戏 sub_412BE8: 标题循环里 sub_44AC50+44AC90
        播 0000.mp3; 主菜单/存档页不启动 BGM)。
        """
        a = self._audio()
        a.set_bgm_enabled(self._se_on)
        a.set_bgm_volume(self._se_vol)
        a.set_sfx_enabled(self._bgm_on)
        a.set_sfx_volume(self._bgm_vol)
        if self._title_mode:
            a.start_bgm()

    def view_state(self):
        """页面/子页签状态快照 (角色切换重建视图时由 CharTab 保持)"""
        return {'page': self._page, 'skill_cat': self._skill_cat,
                'skill_focus': self._skill_focus, 'team_tab': self._team_tab,
                'journal_page': self._journal_page, 'item_cat': self._item_cat,
                'item_sel': self._item_sel, 'item_scroll': self._item_scroll,
                'equip_slot': self._equip_slot, 'equip_scroll': self._equip_scroll,
                'se_on': self._se_on, 'se_vol': self._se_vol,
                'bgm_on': self._bgm_on, 'bgm_vol': self._bgm_vol,
                'save_mode': self._save_mode, 'save_page': self._save_page,
                'save_hover': self._save_hover,
                'title_mode': self._title_mode, 'title_hover': self._title_hover}

    def restore_state(self, state):
        if not state:
            return
        self._page = state.get('page', 0)
        self._skill_cat = state.get('skill_cat', 1)
        self._skill_focus = state.get('skill_focus', 1)
        self._team_tab = state.get('team_tab', 0)
        self._journal_page = state.get('journal_page', 0)
        self._team_sel = -1   # hover 状态瞬时, 重建后由鼠标位置重新决定
        self._item_cat = state.get('item_cat', 0)
        self._item_sel = state.get('item_sel', -1)
        self._item_scroll = state.get('item_scroll', 0)
        self._equip_slot = state.get('equip_slot', 0)
        self._equip_scroll = state.get('equip_scroll', 0)
        self._equip_sel = -1
        self._se_on = state.get('se_on', True)
        self._se_vol = state.get('se_vol', 2)
        self._bgm_on = state.get('bgm_on', True)
        self._bgm_vol = state.get('bgm_vol', 3)
        self._save_mode = state.get('save_mode', 0)
        self._save_page = state.get('save_page', 0)
        self._save_hover = state.get('save_hover', 0)
        self._title_mode = state.get('title_mode', False)
        self._title_hover = state.get('title_hover', 0)
        if self._title_mode:
            # 标题界面重建后无鼠标移动事件, 悬停高亮由下一次 mouseMove 重新计算
            self._title_hover = 0

    def _refresh(self):
        self._rebuild()
        self._scaled_dirty = True   # 源图变更 → 缩放缓存失效
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

    def _save_background(self):
        """存档页背景 save.gxp (sub_41FAAC case 5: sub_450264 加载 aSaveGxp)"""
        c = self._cache()
        if not c.get('save_bg_tried'):
            c['save_bg_tried'] = True
            p = self.data.paths.get("save.gxp")
            if p:
                try:
                    c['save_bg'] = pil_to_qpixmap(_load_gxp_pil(p))
                except Exception:
                    c['save_bg'] = None
        return c['save_bg']

    def _cur_frames(self):
        """Cur.JVG 帧列表 (标题界面按钮高亮池, sub_411624 加载为 dword_755AF8)"""
        c = self._cache()
        if not c['cur_tried']:
            c['cur_tried'] = True
            p = self.data.paths.get("Cur.JVG")
            if p:
                try:
                    jvg = load_jvg(p)
                    c['cur'] = [(b, f) for b in jvg.blocks for f in b.frames]
                except Exception:
                    c['cur'] = None
        return c['cur']

    def _cur_pix(self, idx):
        return self._frame_pix(self._cur_frames(), self._cache()['cur_pix'], idx)

    def _title_background(self):
        """标题界面背景 TitleMenu.gxp (sub_425EAC: sub_450264 加载 aTitlemenuGxp)"""
        c = self._cache()
        if not c.get('title_bg_tried'):
            c['title_bg_tried'] = True
            p = self.data.paths.get("TitleMenu.gxp")
            if p:
                try:
                    c['title_bg'] = pil_to_qpixmap(_load_gxp_pil(p))
                except Exception:
                    c['title_bg'] = None
        return c['title_bg']

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

    def _draw_item_name(self, x, y, tid, color_idx):
        """物品名富文本渲染 (菜单字号 FTYPE2): TKT 名称可含 FCOLOR 颜色宏,
        与右键说明同源走 draw_rich, 纯文本名不受影响。"""
        raw = self._expand_macros(self.data.tkt_raw_bytes(tid).split(b'\x1e')[0])
        self._rich(x, y, raw, color_idx, px=24, ftype=2)

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

    def _fa_pix(self, idx):
        """Fa.JVG 帧 → (QPixmap, 0, 0) (tab_char 人物表格头像逻辑, 帧偏移均为 0)"""
        c = self._cache()
        if 'fa_pix' not in c:
            c['fa_pix'] = {}
        if idx not in c['fa_pix']:
            sprites = getattr(self.data, 'fa_sprites', []) or []
            entry = None
            if 0 <= idx < len(sprites) and sprites[idx] is not None:
                pix = pil_to_qpixmap(sprites[idx])
                if pix:
                    entry = (pix, 0, 0)
            c['fa_pix'][idx] = entry
        return c['fa_pix'].get(idx)

    def _portrait_pix(self, f):
        """左侧队伍列表头像帧。

        USE_TABCHAR_PORTRAIT=True (默认): 按 tab_char 人物表格逻辑取值,
            但保持原头像尺寸 — Fa.JVG 帧 f[1]*2 (70×70 大头像, 与 Mu 帧尺寸一致)。
        False: 原游戏逻辑 — f[261] 非零 → Mu 帧 f[261];
            f[1] 非零 → Mu 帧 f[1]+211; f[1]==0 → (USE_PFACE 时 PFace 帧 0) / Mu 帧 211。
        """
        if USE_TABCHAR_PORTRAIT:
            entry = self._fa_pix(f[1] * 2)
            if entry:
                return entry
            # Fa.JVG 缺失/越界时兜底原游戏逻辑
        if len(f) > 261 and f[261] > 0:
            return self._mu_pix(f[261])
        if f[1]:
            return self._mu_pix(f[1] + 211)
        if USE_PFACE:
            entry = self._pface_pix(0)
            if entry:
                return entry
        return self._mu_pix(211)

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
            # 金钱 (419704 L15-17: 色19黄, "      %-d"; 图鉴按游戏金钱上限 30000 显示)
            self._text(p, 450, 440, "      30000", 19)
        elif page == 3:
            # 装备页 (419B54 L17-19): 右面板38(a15) + 列表面板34(不透明) + 属性预览面板35(a12)
            self._blit(p, self._mu_pix(38), 465, 64, 15)
            self._blit(p, self._mu_pix(34), 215, 48)
            # frame35 分两段渲染: 上方面板(装备槽区) + 下方面板(属性预览区), 中间留间隙
            # frame35 帧顶有13px透明区, 上方面板上移使透明区移出可见区(消除顶部间隙)
            # 下方面板下移使透明区落入上下面板之间的间隙
            # 上方面板: 实心内容从 y=54 开始, 裁剪到 y=54-216
            p.save()
            p.setClipRect(0, 54, 640, 163)
            self._blit(p, self._mu_pix(35), 478, 42, 12)
            p.restore()
            # 下方面板: 实心内容从 y=234 开始, 裁剪到 y=234-470
            p.save()
            p.setClipRect(0, 234, 640, 236)
            self._blit(p, self._mu_pix(35), 478, 222, 12)
            p.restore()
        # page 4 (队伍) / page 5 (系统): 面板/元素全部在 _draw_team_page / _draw_system_page 动态绘制
        #   (系统页渲染顺序关键: sub_41A940 先画旋钮/按钮, 最后画半透明选项行叠加其上,
        #    若放入 _static_base 缓存会导致顺序错误 → 按钮全亮, 与原版不符)
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
        # 存档页 (sub_41AB94): save.gxp 全屏背景 + 存档列表 (不画队伍列表/页签)
        if self._save_mode > 0:
            img = QPixmap(GAME_W, GAME_H)
            img.fill(QColor(0, 0, 0))
            p = QPainter(img)
            bg = self._save_background()
            if bg:
                p.drawPixmap(0, 0, bg)
            self._draw_save_page(p)
            p.end()
            self._image = self._flush_texts(img)
            return
        # 标题界面 (sub_425EAC/sub_426164): TitleMenu.gxp 全屏背景 + hover 高亮
        #   (不画队伍列表/页签; 按钮文字内嵌于背景位图, 无 FONT9696 文字)
        if self._title_mode:
            img = QPixmap(GAME_W, GAME_H)
            img.fill(QColor(0, 0, 0))
            p = QPainter(img)
            self._draw_title_page(p)
            p.end()
            self._image = self._flush_texts(img)
            return
        img = QPixmap(self._static_base(self._page))
        p = QPainter(img)
        self._draw_roster(p)
        if self._page == 0:
            self._draw_status_page(p, f)
        elif self._page == 1:
            self._draw_skill_page(p, f)
        elif self._page == 2:
            self._draw_item_page(p, f)
        elif self._page == 3:
            self._draw_equip_page(p, f)
        elif self._page == 4:
            self._draw_team_page(p, f)
        elif self._page == 5:
            self._draw_system_page(p, f)
        p.end()
        self._image = self._flush_texts(img)
        if self._page in (2, 3):
            # 物品/装备说明弹窗作为最顶层覆盖 (在列表文字之上, 避免被物品名压住)
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
                    self._draw_item_name(480, 80 + 35 * i,
                                         self.data.item_recs[ri]['vals'][2], 16)

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
            # 高亮无条件 (sub_418C90 L26-30): 选中行 a1[614891]==v7 即高亮,
            # 不依赖焦点 — 焦点在右侧槽时鼠标悬停列表行同样高亮
            selected = (gi == self._skill_sel)
            if selected:
                self._blit(p, self._mu_pix(80), 228, 31 * row + 143, 15)
            col = 1 if state >= 20 else (2 if selected else 16)
            nm = self.data.skill_name(si) or f"技能#{si}"
            rec = self._skill_by_idx.get(si)
            # 名字 = TKT 原始字节 (含前导 ASCII 空格, 292/350 条), 与游戏
            # sub_4067E8 → wvsprintfA 同一数据源; 图鉴 skill_name 的 strip 会丢前导空格
            raw = self.data.tkt_raw_bytes(rec['vals'][0]) if rec else b""
            if not raw:
                raw = nm.encode('big5', errors='replace')
            if self._skill_focus < 4:
                cost = rec['vals'][3] * (250 - f[26]) // 200 if rec else 0
                # 游戏 sub_418C90 L44: wvsprintfA("%-10.10s%4d") → 字节流 → sub_44E49C
                # 名字≤10B 硬截断, 补 ASCII 空格到 10 字节, 再接 %4d;
                # 空格半宽步进 12px (sub_421B64 设菜单字体 66=1), 数字位置随名字字节数浮动
                self._rich(240, 31 * row + 145,
                           self._skill_row_bytes(raw, cost), col, px=24, ftype=2)
            else:
                # 焦点在右侧槽 (sub_418C90 L31-37): 只画名字, 无格式串
                self._rich(240, 31 * row + 145, raw, col, px=24, ftype=2)

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
        # 选中跟随鼠标, 允许 -1 (鼠标不在任何物品行上时不选中); ≥0 时钳到有效范围
        if self._item_sel >= 0:
            self._item_sel = min(self._item_sel, n - 1) if n else -1

        # 列表 (419458): 行高31, 图标@235 名字@285, 选中条帧81@281 (色2选中/色16默认)
        vis = rows[self._item_scroll:self._item_scroll + ITEM_LIST_VISIBLE]
        for r, (ridx, vals) in enumerate(vis):
            gi = self._item_scroll + r
            selected = (gi == self._item_sel)
            if selected:
                self._blit(p, self._mu_pix(81), 281, 31 * r + 103, 15)
            self._blit(p, self._mu_pix(vals[4] + 130), 235, 31 * r + 105)
            self._draw_item_name(285, 31 * r + 105, vals[2],
                                 2 if selected else 16)

        # 翻页箭头 (417F0C @ 598,48): 帧21 上 / 帧22 下 (+20,+5)
        if self._item_scroll > 0:
            self._blit(p, self._mu_pix(21), 598, 48)
        if self._item_scroll + ITEM_LIST_VISIBLE < n:
            self._blit(p, self._mu_pix(22), 618, 53)
        # 说明弹窗不在此绘制: 由 _overlay_item_tooltip 在文字 flush 之后作为最顶层覆盖

    def _overlay_item_tooltip(self, pixmap):
        """物品/装备说明弹窗最顶层覆盖 (4195C4): 右键长按时显示, 层级高于列表文字。

        帧158 提示框 + 说明文本(字段3)。位置随长按物品的可见行: v5=Y+31, 靠底(>360)则 Y-139。
        物品页列表行基线 31r+103; 装备页 31r+83。
        """
        if self._tooltip_item < 0:
            return pixmap
        if self._page == 2:
            rows = self._build_item_rows(self._item_cat)
            scroll, visible, base_y = self._item_scroll, ITEM_LIST_VISIBLE, 103
        elif self._page == 3:
            rows = self._build_equip_rows(self._equip_slot)
            scroll, visible, base_y = self._equip_scroll, EQUIP_LIST_VISIBLE, 83
        else:
            return pixmap
        if not (0 <= self._tooltip_item < len(rows)):
            return pixmap
        sel_row = self._tooltip_item - scroll
        if not (0 <= sel_row < visible):
            return pixmap   # 物品已滚出可见区
        yy = 31 * sel_row + base_y
        v5 = yy + 31 if yy + 31 <= 360 else yy - 139
        p = QPainter(pixmap)
        self._blit(p, self._mu_pix(158), 252, v5)
        p.end()
        raw = self._expand_macros(self.data.tkt_raw_bytes(rows[self._tooltip_item][1][3]))
        self._rich(262, v5 + 8, raw, 16, px=16, ftype=0, max_y=v5 + 113)
        return self._flush_texts(pixmap)

    # ── 装备页 (sub_419B54 / sub_419A24 / sub_419D9C / sub_422268) ──

    def _build_equip_rows(self, slot):
        """选中槽可装备物品 [(rec_index, vals), ...]: 按槽分类 field[1] 过滤 + 职业掩码 field[5]"""
        c = self._cache()
        char = self._rec_by_idx.get(self._current)
        cat = EQUIP_SLOT_CAT[slot]
        # 职业掩码: 角色字段 [77+分类] (79/80/81); 缺角色时不限制
        cmask = (char['fields'][77 + cat] & 0xFFFF) if char else 0xFFFF
        key = ('equip', self._current, slot)
        if key not in c:
            rows = []
            for rec in self.data.item_recs:
                vals = rec['vals']
                if vals[0] in (0, 1) or vals[2] <= 0 or vals[1] != cat:
                    continue
                imask = vals[5] & 0xFFFF   # 职业限制掩码 (sub_419850: (imask & cmask)==imask)
                if (imask & cmask) != imask:
                    continue
                if not tkt_first_line(self.data.tkt, vals[2]):
                    continue
                rows.append((rec['index'], vals))
            c[key] = rows
        return c[key]

    def _draw_equip_page(self, p, f):
        """装备页动态内容 (419B54 槽/分类 + 419A24 列表 + 419D9C/422268 换装差值预览)"""
        slot = self._equip_slot
        v8 = slot if slot != 3 else 2
        # 4 装备槽 (419B54 L22-44): 图标 2*v7+62 @ (483,39v+60), 选中槽高亮帧83
        for v6 in range(4):
            v7 = v6 if v6 != 3 else 2
            if slot == v6:
                self._blit(p, self._mu_pix(83), 480, 39 * v6 + 58, 15)
            self._blit(p, self._mu_pix(2 * v7 + 62), 483, 39 * v6 + 60)
            ri = f[69 + v6]   # 该槽装备 TKItem 记录号
            if 0 <= ri < len(self.data.item_recs):
                nm = tkt_first_line(self.data.tkt, self.data.item_recs[ri]['vals'][2])
                if nm:
                    self._draw_item_name(512, 39 * v6 + 60,
                                         self.data.item_recs[ri]['vals'][2], 16)
        # 分类高亮 (419B54 L49): 帧 v8+29 @ (61*v8+230, 52)
        self._blit(p, self._mu_pix(v8 + 29), 61 * v8 + 230, 52)

        # 列表 (419A24): 行高31, 图标@225 名字@265, 选中条帧82@261
        rows = self._build_equip_rows(slot)
        n = len(rows)
        self._equip_scroll = max(0, min(self._equip_scroll, max(0, n - EQUIP_LIST_VISIBLE)))
        if self._equip_sel >= 0:
            self._equip_sel = min(self._equip_sel, n - 1) if n else -1
        vis = rows[self._equip_scroll:self._equip_scroll + EQUIP_LIST_VISIBLE]
        for r, (ridx, vals) in enumerate(vis):
            gi = self._equip_scroll + r
            selected = (gi == self._equip_sel)
            if selected:
                self._blit(p, self._mu_pix(82), 261, 31 * r + 83, 15)
            self._blit(p, self._mu_pix(vals[4] + 130), 225, 31 * r + 85)
            self._draw_item_name(265, 31 * r + 85, vals[2],
                                 2 if selected else 16)

        # 翻页箭头 (417F0C @ 426,42): 帧21 上 / 帧22 下 (+20,+5)
        if self._equip_scroll > 0:
            self._blit(p, self._mu_pix(21), 426, 42)
        if self._equip_scroll + EQUIP_LIST_VISIBLE < n:
            self._blit(p, self._mu_pix(22), 446, 47)

        # 换装属性差值预览 (419D9C L21-46 + 422268): 8属性 @ (486,240+28i), 升降箭头 @ (610,28i+246)
        equipped = None
        eri = f[69 + slot]
        if 0 <= eri < len(self.data.item_recs):
            equipped = self.data.item_recs[eri]['vals']
        hovered = rows[self._equip_sel][1] if 0 <= self._equip_sel < n else None
        for i, label in enumerate(EQUIP_ATTR_LABELS):
            if hovered is None:
                delta = 0
            elif equipped is None:
                delta = hovered[11 + i]                    # 空槽 → 悬停物品全额加成
            else:
                delta = hovered[11 + i] - equipped[11 + i]  # 有装备 → 差值
            self._text(p, 486, 240 + 28 * i, f"{label}{delta}", 16)
            if delta > 0:
                self._blit(p, self._mu_pix(36), 610, 28 * i + 246)   # 升箭头
            elif delta < 0:
                self._blit(p, self._mu_pix(37), 610, 28 * i + 246)   # 降箭头

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
                # 成员行右侧按钮 (解散): 帧44 底(a15) + 帧54 图案(不透明);
                # 选中行先画帧45 亮黄高亮 (sub_42131C L86-92: 45→44→54 顺序)
                if i == self._team_sel:
                    self._blit(p, self._mu_pix(45), 560, 35 * i + 270)
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

    # ── 系统页 (sub_41A940) ──

    def _draw_system_page(self, p, f):
        """系统页全部内容 (sub_41A940 L14-35) — 严格按反编译渲染顺序绘制。

        渲染顺序关键: 先画旋钮/按钮(不透明/半透明), 最后画半透明选项行叠加其上。
        若顺序反了 → 按钮全亮(不被选项行半透明面板覆盖), 与原版不符。
        """
        # ── 第 1-8 步: 音效/BGM 旋钮 + 开关按钮 (sub_41A940 L14-27) ──
        # 音效滑块旋钮 (不透明): 帧 vol+88 @ (340,95)
        self._blit(p, self._mu_pix(self._se_vol + 88), 340, 95)
        # 音效开关旋钮 (半透明 a10): 帧86 @ (440 若开 / 540 若关, 103)
        self._blit(p, self._mu_pix(86), 440 if self._se_on else 540, 103, 10)
        # 音效 开/关 按钮 (不透明): 帧99 @ (440,100) / 帧100 @ (540,100)
        self._blit(p, self._mu_pix(99), 440, 100)
        self._blit(p, self._mu_pix(100), 540, 100)
        # BGM 滑块旋钮 (不透明): 帧 vol+88 @ (340,160)
        self._blit(p, self._mu_pix(self._bgm_vol + 88), 340, 160)
        # BGM 开关旋钮 (半透明 a10): 帧86 @ (440 若开 / 540 若关, 168)
        self._blit(p, self._mu_pix(86), 440 if self._bgm_on else 540, 168, 10)
        # BGM 开/关 按钮 (不透明): 帧99 @ (440,165) / 帧100 @ (540,165)
        self._blit(p, self._mu_pix(99), 440, 165)
        self._blit(p, self._mu_pix(100), 540, 165)

        # ── 第 9 步: 装饰 (sub_41A940 L28): 帧42 @ (550,200) 不透明 ──
        self._blit(p, self._mu_pix(42), 550, 200)

        # ── 第 10 步: 标题面板 (sub_41A940 L29): 帧84 @ (215,57) a10 ──
        self._blit(p, self._mu_pix(84), 215, 57, 10)

        # ── 第 11 步: 5 系统选项行 (sub_41A940 L30-35) — 最后绘制, 半透明叠加在按钮之上 ──
        for i in range(5):
            y = 65 * i + 100
            self._blit(p, self._mu_pix(85), 240, y, 10)       # 背景 a10
            self._blit(p, self._mu_pix(87), 240, y, 15)       # 叠加 a15
            self._blit(p, self._mu_pix(i + 94), 240, y)        # 图标 不透明

    # ── 存档页 (sub_41AB94 + sub_41B08C) ──
    # 进入: 系统页点 存档/读档 按钮 → arglist[614953]=1/2, arglist[461]=6, 加载 save.gxp
    # 取消: 点 "取消" → arglist[614953]=0, arglist[461]=8 → 10 → 1 (回主菜单)
    # 布局: 3页 × 3行 = 9 存档槽; 行高 150px; 每槽 6 角色头像 + 金钱 + 日期/时间 + 地点
    # 存档文件: Save\<N>.sav (28字节索引, N=1-9); file_idx = 3*page + row + 1

    def _save_slot(self, row):
        """存档槽元数据 (sub_41B1A8): row=0..2 → save_slots[3*page + row]"""
        slots = getattr(self.data, 'save_slots', [])
        idx = 3 * self._save_page + row
        if 0 <= idx < len(slots):
            return slots[idx]
        return None

    def _draw_save_page(self, p):
        """存档页渲染 (sub_41AB94 L20-70 + sub_41B08C hover/箭头)"""
        # 字体 FTYPE2 @ 24px, 色16 (sub_44AF7C(2,24,1,0,1,0) + sub_44B028(16))
        # 页码 "第%d頁 共3頁" @ (450, 10) (byte_4E9944, 参数 page+1)
        self._text(p, 450, 10, f"第{self._save_page + 1}頁 共3頁", 16)
        # 3 行存档槽 (sub_41AB94 L23-69)
        for i in range(3):
            yb = 150 * i
            # 行背景 frame 273 @ (9, yb+40) 半透明 a10 (sub_41AB94 L25)
            self._blit(p, self._mu_pix(273), 9, yb + 40, 10)
            # 存档数据 (sub_41B1A8: file_idx = 3*page + row + 1)
            slot = self._save_slot(i)
            if slot is None:
                # 空槽: 仅显示金钱"0"和按钮文字 (sub_41AB94 SLOBYTE==-1 分支)
                self._blit(p, self._mu_pix(206), 300, yb + 125)
                self._text(p, 390, yb + 135, "0", 16)
            else:
                # 非空槽: 画头像/等级/日期/时间/地点/金钱 (sub_41AB94 L29-67)
                team_ids = slot['team_ids']
                team_levels = slot['team_levels']
                # 角色头像 v7=0..5 (sub_41AB94 L29-50): 空位 SLOBYTE==-1 → break
                for v in range(6):
                    cid = team_ids[v]
                    if cid < 0:
                        break  # 空位, 停止绘制后续头像
                    # USE_SAVE_PORTRAIT=True (默认): 按队伍头像逻辑取值
                    #   (_portrait_pix, 受 USE_TABCHAR_PORTRAIT 控制:
                    #    True→Fa.JVG 帧 f[1]*2; False→原游戏逻辑 Mu 帧)
                    # USE_SAVE_PORTRAIT=False: 原存档页逻辑 Mu 帧 cid+211
                    if USE_SAVE_PORTRAIT:
                        rec = self._rec_by_idx.get(cid)
                        entry = self._portrait_pix(rec['fields']) if rec else None
                        if entry is None:
                            entry = self._mu_pix(cid + 211)
                    else:
                        # 帧号 = charID + 211 (sub_41AB94 L35)
                        entry = self._mu_pix(cid + 211)
                    self._blit(p, entry, 71 * v + 16, yb + 46)
                    # 等级 "Lv %2d" @ (71*v+16, yb+110) 色20 (sub_41AB94 L43-45)
                    self._text(p, 71 * v + 16, yb + 110, f"Lv {team_levels[v]:2d}", 20)
                # 日期/时间 (sub_41AB94 L58-63): localtime → strftime
                ts = slot['timestamp']
                if ts > 0:
                    tm = time.localtime(ts)
                    self._text(p, 450, yb + 50,
                               f"{tm.tm_year % 100:02d}年{tm.tm_mon:02d}月{tm.tm_mday:02d}日", 16)
                    self._text(p, 450, yb + 80,
                               f"{tm.tm_hour:02d}:{tm.tm_min:02d}:{tm.tm_sec:02d}", 16)
                # 地点名称 @ (20, yb+135) 色16 (sub_41AB94 L65-66: sub_4067E8(sceneID+300))
                self._text(p, 20, yb + 135, self.data.scene_name(slot['scene_id']), 16)
                # 金钱图标 frame 206 @ (300, yb+125) (sub_41AB94 L51)
                self._blit(p, self._mu_pix(206), 300, yb + 125)
                # 金钱数值 "%d" @ (390, yb+135) (sub_41AB94 L52)
                self._text(p, 390, yb + 135, str(slot['gold']), 16)
            # 存档/读档按钮 (sub_41AB94 L53-56): byte_4E995B "存檔" / byte_4E9960 "讀檔"
            if self._save_mode == 1:
                self._text(p, 460, yb + 130, "存檔", 16)
            else:
                self._text(p, 460, yb + 130, "讀檔", 16)
            # 取消按钮 (sub_41AB94 L57): byte_4E9965 "取消"
            self._text(p, 528, yb + 130, "取消", 16)
        # hover 高亮 (sub_41B08C L13-19): frame86 alpha=10
        if self._save_hover > 0:
            for i in range(3):
                if self._save_hover == 2 * i + 1:
                    # 存档按钮 hover @ (451, 150*i+128)
                    self._blit(p, self._mu_pix(86), 451, 150 * i + 128, 10)
                elif self._save_hover == 2 * i + 2:
                    # 读档/取消按钮 hover @ (519, 150*i+128)
                    self._blit(p, self._mu_pix(86), 519, 150 * i + 128, 10)
        # 翻页箭头 (sub_41B08C L23-24): frame21 上 @ (613,190) / frame22 下 @ (613,240)
        self._blit(p, self._mu_pix(21), 613, 190)
        self._blit(p, self._mu_pix(22), 613, 240)

    # ── 标题界面 (sub_425EAC + sub_425F3C + sub_426004 + sub_426164) ──
    # 进入: 系统页点"离开"(x=240-305, y=359-393) → word_4E8058=1 → 主循环重载标题
    # 背景: TitleMenu.gxp 全屏 (按钮文字内嵌位图, 无 FONT9696 文字绘制)
    # 3 按钮区域: X∈[200,460], Y∈[44*(i-1)+290, 44*(i-1)+333] (i=1..3)
    # hover 高亮: Cur.JVG 帧 116/117/118 (sub_45408C(Cur,21)=116) @ (200, 44*i+246) 不透明
    # 点击 (sub_426004): 1=新的游戏→回主菜单 / 2=继续游戏→存档页(读档) / 3=离开游戏→退出
    TITLE_HOVER_BASE = 116      # Cur.JVG 帧号基址 (dword_824444, sub_45408C(Cur,21))

    def _title_hit(self, x, y):
        """按钮命中检测 (sub_425F3C/sub_426004): X∈[200,460], Y∈[44*(i-1)+290, 44*(i-1)+333]"""
        if not (200 <= x <= 460):
            return 0
        for i in (1, 2, 3):
            if 44 * (i - 1) + 290 <= y <= 44 * (i - 1) + 333:
                return i
        return 0

    def _draw_title_page(self, p):
        """标题界面渲染 (sub_426164 L27-32): 全屏背景 + hover 高亮帧 (不透明)"""
        bg = self._title_background()
        if bg:
            p.drawPixmap(0, 0, bg)
        if self._title_hover > 0:
            self._blit(p, self._cur_pix(self.TITLE_HOVER_BASE + self._title_hover - 1),
                       200, 44 * self._title_hover + 246)

    @staticmethod
    def _skill_row_bytes(raw_name, cost):
        """复刻 wvsprintfA "%-10.10s%4d" 字节语义 (sub_418C90 L44)。

        名字 = TKT 原始字节 (含前导 ASCII 空格, 图鉴 skill_name 的 strip 会丢失);
        %.10s 最多 10 字节硬截断 (名字≤10B 时不截断, 本样本全部 ≤10B);
        不足补 ASCII 空格到 10 字节 (空格在 FONT9696 中半宽 12px 占位);
        再接 %4d 右对齐 4 位消耗。已用系统真实 wvsprintfA 实测验证一致
        (_test_wvsprintf.py)。
        """
        name = raw_name[:10]
        return name + b' ' * (10 - len(name)) + f'{cost:4d}'.encode('ascii')

    # ── 事件 ──

    def paintEvent(self, event):
        p = QPainter(self)
        # 先填充背景, 清除旧内容 (防止缩放/尺寸变更时残留上一帧)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        if self._image is None:
            p.fillRect(self.rect(), QColor(24, 24, 28))
            p.setPen(QColor(160, 160, 160))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "缺少 mb.gxp / Mu.JVG, 无法渲染游戏界面")
            return

        # scale=1.0: 直接绘制原始 640×480 图 (无需缩放)
        if self._scale == 1.0:
            p.drawPixmap(0, 0, self._image)
            return

        # scale≠1.0: 使用 jinc2-sharp 缩放 (缓存)
        if self._scaled_dirty:
            self._rebuild_scaled_pixmap()
        if self._scaled_pixmap is not None:
            p.drawPixmap(0, 0, self._scaled_pixmap)
        else:
            # 缩放失败回退: QPainter 平滑缩放
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.scale(self._scale, self._scale)
            p.drawPixmap(0, 0, self._image)

    def _rebuild_scaled_pixmap(self):
        """将 _image (640×480) 用 jinc2-sharp 缩放到当前 _scale 尺寸"""
        self._scaled_dirty = False
        if self._image is None:
            self._scaled_pixmap = None
            return
        out_w = int(GAME_W * self._scale)
        out_h = int(GAME_H * self._scale)
        try:
            from PIL import Image as PILImage
            # QPixmap → PIL Image (注意 stride 可能 ≠ w*4)
            qimg = self._image.toImage().convertToFormat(QImage.Format_RGBA8888)
            w, h = qimg.width(), qimg.height()
            stride = qimg.bytesPerLine()
            raw = bytes(qimg.bits()[:qimg.sizeInBytes()])
            if stride == w * 4:
                pil_img = PILImage.frombytes('RGBA', (w, h), raw)
            else:
                # 去除 stride 填充字节
                rows = [raw[i * stride:(i * stride) + w * 4] for i in range(h)]
                pil_img = PILImage.frombytes('RGBA', (w, h), b''.join(rows))
            pil_img = pil_img.convert('RGB')
            # jinc2-sharp 缩放
            pil_scaled = resize_jinc2_sharp(pil_img, out_w, out_h)
            # PIL Image → QPixmap
            pil_rgba = pil_scaled.convert('RGBA')
            data = pil_rgba.tobytes('raw', 'RGBA')
            qimg2 = QImage(data, out_w, out_h, QImage.Format_RGBA8888)
            self._scaled_pixmap = QPixmap.fromImage(qimg2.copy())
        except Exception:
            self._scaled_pixmap = None

    def mousePressEvent(self, event):
        pos = self._game_pos(event.position().toPoint())
        x, y = pos.x(), pos.y()

        # 右键: 物品/装备页按住即时显示说明弹窗 (游戏内 hold 右键立即弹出, 松开消失, 无延时)
        # 音效: 游戏 case 3 (sub_420844 机器码 0x420A59/0x420AA9) 物品/装备页行上右键
        # → sub_451C38 音效 6 + a1[8]=1 (说明浮框显示标志, sub_4195C4 检查 a1[4])
        if event.button() == Qt.RightButton:
            if self._page in (2, 3):
                gi = self._item_at(pos)
                if gi >= 0 and gi != self._tooltip_item:
                    self._sfx(6)   # 游戏 case 3: 右键显示说明音效
                    self._tooltip_item = gi
                    self._refresh()
            return

        # 存档页 (sub_41CE10): 全屏 save.gxp 背景, 不响应左侧列表/页签/系统页
        if self._save_mode > 0:
            self._save_mouse(x, y)
            return

        # 标题界面 (sub_426004): 全屏 TitleMenu.gxp, 3 按钮点击 (1新游戏/2继续/3离开)
        if self._title_mode:
            self._title_mouse(x, y)
            return

        # 左侧列表行 (行区域同帧0边框: x 3..205, 高 79)
        if x <= 205:
            row = (y - 3) // 79
            if 0 <= row < len(self._window):
                widx = self._window[row]
                if widx != self._current:
                    self._sfx(3)      # 游戏 sub_41F9D0
                    self.charClicked.emit(widx)
            return

        # 顶部页签 (209+72j, 6, 68x32): 状态/技能/物品/装备/队伍/系统可切换
        if 6 <= y <= 40 and x >= 209:
            j = (x - 209) // 72
            if j in (0, 1, 2, 3, 4, 5) and j != self._page:
                self._sfx(4)      # 游戏 sub_41FA40
                self._page = j
                self._refresh()
            return

        if self._page == 4:
            self._team_mouse(x, y)
            return

        if self._page == 5:
            self._system_mouse(x, y)
            return

        if self._page == 2:
            self._item_mouse(x, y)
            return

        if self._page == 3:
            self._equip_mouse(x, y)
            return

        if self._page != 1:
            return

        # 技能页: 分类页签 (220+42i, 99, 39x38)
        if 99 <= y <= 137 and 219 <= x < 219 + 42 * 4:
            i = (x - 219) // 42
            if 0 <= i <= 3 and (self._skill_focus != i or self._skill_cat != i):
                self._sfx(7)      # 游戏 sub_41FAAC case1 → sub_421F20
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
                self._sfx(7)      # 游戏 sub_421F20
                self._skill_focus = i + 4
                self._refresh()
            return

        # 技能页: 翻页箭头 (390,98,20x30 上 / 410,103,20x30 下)
        if 390 <= x < 410 and 98 <= y < 128:
            self._sfx(3)          # 游戏 sub_421FBC (翻上页)
            self._scroll_skill(-SKILL_LIST_VISIBLE)
            return
        if 410 <= x < 430 and 103 <= y < 133:
            self._sfx(3)          # 游戏 sub_42200C (翻下页)
            self._scroll_skill(SKILL_LIST_VISIBLE)
            return

        # 技能页: 列表行 (sub_42061C: x=228-417, y=142+31r..172+31r, 行高31)
        # 游戏点击行 = sub_41F318 学习/装备动作; 图鉴只读仅确认选中 (hover 已选中),
        # 不切焦点 (游戏 sub_41F318 不改 a1[614866])
        if 228 <= x <= 417 and y >= 142:
            row = (y - 142) // 31
            if 0 <= row < SKILL_LIST_VISIBLE:
                gi = self._skill_scroll + row
                if gi < len(self._skill_rows):
                    self._sfx(6)  # 游戏 sub_41F318
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

    def mouseMoveEvent(self, event):
        # 存档页 hover (sub_41DC5C): X∈[452,583], 分两子区域, 间隙[516,518]不触发
        if self._save_mode > 0:
            pos = self._game_pos(event.position().toPoint())
            x, y = pos.x(), pos.y()
            new_hover = 0
            if 452 <= x <= 583:
                for v in range(3):
                    if 150 * v + 127 <= y <= 150 * v + 155:
                        if 452 <= x <= 515:
                            new_hover = 2 * v + 1      # 存档按钮 (sub_41DC5C L24-26)
                        elif 519 <= x <= 583:
                            new_hover = 2 * v + 2      # 读档/取消按钮 (sub_41DC5C L28-30)
                        # 间隙 [516,518] → new_hover=0 (原游戏瑕疵, 1:1 保留)
                        break
            if new_hover != self._save_hover:
                self._save_hover = new_hover
                self._refresh()
            return
        # 标题界面 hover (sub_425F3C): 移到选项上高亮, 移出清除
        if self._title_mode:
            pos = self._game_pos(event.position().toPoint())
            new_hover = self._title_hit(pos.x(), pos.y())
            if new_hover != self._title_hover:
                self._title_hover = new_hover
                self._refresh()
            return
        # 技能页 hover (sub_4212E0 → sub_420730 case 1 → sub_422218):
        #   X∈[228,417], Y∈[142+31r, 172+31r] → 选中行 = scroll+r
        #   sub_422218 仅更新选中行 a1[614891], 不切焦点; 移出列表区保持选中
        #   (游戏 sub_420730 返回 -1 时不更新, 高亮停留)
        if self._page == 1:
            pos = self._game_pos(event.position().toPoint())
            gi = self._skill_hover_row(pos.x(), pos.y())
            if gi >= 0 and gi != self._skill_sel:
                self._skill_sel = gi
                self._refresh()
            return
        # 队伍页团队子页 hover (sub_420730 case 4): X∈[562,618], Y∈[271+35i, 299+35i]
        # → 选中成员行 → 帧45 高亮 (sub_42131C L86-92); 移出区域保持 (游戏 -1 不更新)
        if self._page == 4 and self._team_tab == 0:
            pos = self._game_pos(event.position().toPoint())
            x, y = pos.x(), pos.y()
            new_sel = -1
            if 562 <= x <= 618:
                for r in range(len(self._team_members())):
                    if 271 + 35 * r <= y <= 299 + 35 * r:
                        new_sel = r
                        break
            if new_sel >= 0 and new_sel != self._team_sel:
                self._team_sel = new_sel
                self._refresh()
            return
        # 物品/装备页: 选中跟随鼠标 — 悬停到哪行选哪行; 移出列表区保持选中
        # (游戏 sub_4212E0: sub_420730 返回 -1 时不更新, 与技能页一致)
        if self._page == 2:
            gi = self._item_at(self._game_pos(event.position().toPoint()))
            if gi >= 0 and gi != self._item_sel:
                self._item_sel = gi
                self._refresh()
        elif self._page == 3:
            gi = self._item_at(self._game_pos(event.position().toPoint()))
            if gi >= 0 and gi != self._equip_sel:
                self._equip_sel = gi   # 悬停驱动换装差值预览
                self._refresh()
        super().mouseMoveEvent(event)

    def _skill_hover_row(self, x, y):
        """技能列表 hover 行检测 (sub_420730 case 1): X∈[228,417], Y∈[142+31r, 172+31r],
        行高 31; 返回全局行号 (scroll+屏幕行), 不在区域/无行返回 -1"""
        if 228 <= x <= 417:
            for r in range(SKILL_LIST_VISIBLE):
                if 142 + 31 * r <= y <= 172 + 31 * r:
                    gi = self._skill_scroll + r
                    return gi if gi < len(self._skill_rows) else -1
        return -1

    def _item_at(self, pos):
        """物品/装备列表行命中 → 全局索引 (无则 -1)"""
        x, y = pos.x(), pos.y()
        if self._page == 2:
            # 物品: 235..632, y=105+31r, 10 行
            if 235 <= x <= 632 and y >= 105:
                row = (y - 105) // 31
                if 0 <= row < ITEM_LIST_VISIBLE:
                    gi = self._item_scroll + row
                    if gi < len(self._build_item_rows(self._item_cat)):
                        return gi
        elif self._page == 3:
            # 装备: 225..464, y=85+31r, 12 行 (右侧 465+ 为槽/属性区, 不算列表)
            if 225 <= x <= 464 and y >= 85:
                row = (y - 85) // 31
                if 0 <= row < EQUIP_LIST_VISIBLE:
                    gi = self._equip_scroll + row
                    if gi < len(self._build_equip_rows(self._equip_slot)):
                        return gi
        return -1

    def wheelEvent(self, event):
        # 存档页翻页 (sub_41CE10 case 11/12/13: 页码变化才响, 边界不响)
        if self._save_mode > 0:
            if event.angleDelta().y() > 0:
                if self._save_page > 0:
                    self._sfx(3)
                    self._save_page -= 1
                    self._refresh()
            else:
                if self._save_page < 2:
                    self._sfx(3)
                    self._save_page += 1
                    self._refresh()
            event.accept()
            return
        # 标题界面: 无翻页逻辑 (sub_426164 不处理滚轮), 直接忽略
        if self._title_mode:
            event.accept()
            return
        # 左侧队伍列表: 鼠标在列表区 (x≤205) 时滚轮翻动花名册窗口
        gx = self._game_pos(event.position().toPoint()).x()
        if gx <= 205:
            self._scroll_roster(-1 if event.angleDelta().y() > 0 else 1, sfx=True)
            event.accept()
            return
        if self._page == 1:
            self._scroll_skill(-3 if event.angleDelta().y() > 0 else 3, sfx=True)
            event.accept()
            return
        if self._page == 2:
            self._scroll_item(-3 if event.angleDelta().y() > 0 else 3, sfx=True)
            event.accept()
            return
        if self._page == 3:
            self._scroll_equip(-3 if event.angleDelta().y() > 0 else 3, sfx=True)
            event.accept()
            return
        if self._page == 4 and self._team_tab in (1, 2):
            self._flip_journal(-1 if event.angleDelta().y() > 0 else 1, sfx=True)
            event.accept()
            return
        super().wheelEvent(event)

    def _scroll_skill(self, delta, sfx=False):
        n = len(self._skill_rows)
        new = max(0, min(self._skill_scroll + delta, max(0, n - SKILL_LIST_VISIBLE)))
        if new != self._skill_scroll:
            if sfx:
                self._sfx(3)      # 游戏 sub_420844 case 12/13 → 翻页
            self._skill_scroll = new
            self._refresh()

    # ── 物品页交互 ──

    def _item_mouse(self, x, y):
        # 分类栏 (61*cat+229, 54, 56x24): 6 分类
        if 48 <= y <= 78 and 229 <= x < 229 + 61 * ITEM_CATEGORIES:
            i = (x - 229) // 61
            if 0 <= i < ITEM_CATEGORIES and i != self._item_cat:
                self._sfx(7)      # 游戏 sub_422064
                self._item_cat = i
                self._item_sel = -1   # 切换分类后重置选中 (由鼠标悬停重新决定)
                self._item_scroll = 0
                self._refresh()
            return
        # 翻页箭头 (598,48,20x30 上一页 / 618,53,20x30 下一页)
        if 598 <= x < 618 and 48 <= y < 78:
            self._sfx(3)          # 游戏 sub_421FBC (翻上页)
            self._scroll_item(-ITEM_LIST_VISIBLE)
            return
        if 618 <= x < 638 and 53 <= y < 83:
            self._sfx(3)          # 游戏 sub_42200C (翻下页)
            self._scroll_item(ITEM_LIST_VISIBLE)
            return
        # 列表行选中由 mouseMoveEvent (悬停跟随) 处理, 此处无需响应左键点击

    def _scroll_item(self, delta, sfx=False):
        n = len(self._build_item_rows(self._item_cat))
        new = max(0, min(self._item_scroll + delta, max(0, n - ITEM_LIST_VISIBLE)))
        if new != self._item_scroll:
            if sfx:
                self._sfx(3)      # 游戏 sub_420844 case 12/13 → 翻页
            self._item_scroll = new
            self._refresh()

    # ── 装备页交互 ──

    def _equip_mouse(self, x, y):
        # 分类按钮 (61*cat+230, 52, 56x24): 武器/防具/饰品 → 切换槽 (与右侧槽相通)
        if 48 <= y <= 78 and 230 <= x < 230 + 61 * 3:
            cat = (x - 230) // 61
            if 0 <= cat <= 2 and cat != self._equip_slot:
                self._sfx(7)      # 游戏 sub_4220D8
                self._equip_slot = cat
                self._equip_sel = -1
                self._equip_scroll = 0
                self._refresh()
            return
        # 装备槽 (480.., 39v+58, 高39, 右侧含名字): 点选槽 → 切换列表分类
        if x >= 480 and 58 <= y < 58 + 39 * 4:
            v6 = (y - 58) // 39
            if 0 <= v6 < 4 and v6 != self._equip_slot:
                self._sfx(7)      # 游戏 sub_4220D8
                self._equip_slot = v6
                self._equip_sel = -1
                self._equip_scroll = 0
                self._refresh()
            return
        # 翻页箭头 (426,42,20x30 上一页 / 446,47,20x30 下一页)
        if 426 <= x < 446 and 42 <= y < 72:
            self._sfx(3)          # 游戏 sub_421FBC (翻上页)
            self._scroll_equip(-EQUIP_LIST_VISIBLE)
            return
        if 446 <= x < 466 and 47 <= y < 77:
            self._sfx(3)          # 游戏 sub_42200C (翻下页)
            self._scroll_equip(EQUIP_LIST_VISIBLE)
            return
        # 列表行悬停选中由 mouseMoveEvent 处理 (驱动换装差值预览)

    def _scroll_equip(self, delta, sfx=False):
        n = len(self._build_equip_rows(self._equip_slot))
        new = max(0, min(self._equip_scroll + delta, max(0, n - EQUIP_LIST_VISIBLE)))
        if new != self._equip_scroll:
            if sfx:
                self._sfx(3)      # 游戏 sub_420844 case 12/13 → 翻页
            self._equip_scroll = new
            self._refresh()

    # ── 队伍页交互 ──

    def _team_mouse(self, x, y):
        # 子页签 (215+60i, 56, 62x30): 团队/记事/功绩/历史
        if 56 <= y <= 86 and 215 <= x < 215 + 60 * 4:
            i = (x - 215) // 60
            if 0 <= i <= 3 and self._team_tab != i:
                self._sfx(7)      # 游戏 sub_422158
                self._team_tab = i
                self._journal_page = 0
                self._refresh()
            return
        # 记事/功绩: 翻页箭头 (460,50,20x30 上一页 / 480,55,20x30 下一页)
        if self._team_tab in (1, 2):
            if 460 <= x < 480 and 50 <= y < 80:
                self._sfx(3)      # 游戏 sub_421FBC
                self._flip_journal(-1)
                return
            if 480 <= x < 500 and 55 <= y < 85:
                self._sfx(3)      # 游戏 sub_42200C
                self._flip_journal(1)
                return
        # 团队: 队员行 (420.., 270+35i, 高35) → 切换选中角色
        if self._team_tab == 0 and x >= 420 and 270 <= y < 270 + 35 * 5:
            members = self._team_members()
            i = (y - 270) // 35
            if i < len(members) and members[i] != self._current:
                self._sfx(7)      # 游戏 sub_42359C
                self.charClicked.emit(members[i])
            return

    def _flip_journal(self, delta, sfx=False):
        entries = self._journal_entries(self._team_tab) if self._team_tab in (1, 2) else []
        pages = max(1, (len(entries) + JOURNAL_PER_PAGE - 1) // JOURNAL_PER_PAGE)
        new = max(0, min(self._journal_page + delta, pages - 1))
        if new != self._journal_page:
            if sfx:
                self._sfx(3)      # 游戏 sub_420844 case 12/13 → 翻页
            self._journal_page = new
            self._refresh()

    # ── 系统页交互 (sub_41FAAC case 5) ──
    # 音效行 y=97-129 / BGM 行 y=164-198: 开关旋钮 + 5 档音量滑块
    # 系统选项行 y=229-263 / 294-328 / 359-393: 存档/读档/离开 (图鉴只读, 仅视觉)

    def _system_mouse(self, x, y):
        # 音效行 (word_755C78 开关 / word_755C7A 音量)
        if 97 <= y <= 129:
            self._audio_click(x, 'se')
            return
        # BGM 行 (word_755C74 开关 / word_755C76 音量)
        if 164 <= y <= 198:
            self._audio_click(x, 'bgm')
            return
        # 系统选项 3 (存档, sub_41FAAC case 5 L273-287): y=229-263, x=240-305
        # → arglist[614953]=1, arglist[461]=6, 加载 save.gxp
        if 229 <= y <= 263 and 240 <= x <= 305:
            self._sfx(4)          # 游戏 sub_41FAAC: 存档点击
            self._save_mode = 1
            self._save_page = 0
            self._save_hover = 0
            self._refresh()
            return
        # 系统选项 4 (读档, sub_41FAAC case 5 L253-271): y=294-328, x=240-305
        # → arglist[614953]=2, arglist[461]=6, 加载 save.gxp
        if 294 <= y <= 328 and 240 <= x <= 305:
            self._sfx(4)          # 游戏 sub_41FAAC: 读档点击
            self._save_mode = 2
            self._save_page = 0
            self._save_hover = 0
            self._refresh()
            return
        # 系统选项 5 (离开, sub_41FAAC case 5 L241-251): y=359-393, x=240-305
        # → sub_451C38(0) + word_4E8058=1 → 主循环重载资源进入标题界面 (sub_425EAC)
        if 359 <= y <= 393 and 240 <= x <= 305:
            # 标题界面资源缺失时保持只读 (不跳转)
            if not (self.data.paths.get("TitleMenu.gxp")
                    and self.data.paths.get("Cur.JVG")):
                return
            self._sfx(1)          # 游戏 sub_41FAAC: 离开点击
            self._title_mode = True
            self._title_hover = 0
            # 进入标题界面 → 播放 BGM (游戏 sub_412BE8: sub_44AC50+44AC90 播 0000.mp3)
            self._audio().start_bgm()
            self._refresh()
            return

    # ── 标题界面交互 (sub_426004) ──
    # 左键点击: X∈[200,460], Y∈[44*(i-1)+290, 44*(i-1)+334] (sub_426004 L16-23)
    #   1=新的游戏 → sub_426164 返回 100 → 主循环退出标题, 进入主菜单
    #   2=继续游戏 → 加载 save.gxp, arglist[614953]=2, arglist[461]=6 → 存档页(读档)
    #   3=离开游戏 → sub_44ACE8 + SendMessageA(hWnd, WM_CLOSE) → 退出程序

    def _title_mouse(self, x, y):
        if not (200 <= x <= 460):
            return
        for i in (1, 2, 3):
            if 44 * (i - 1) + 290 <= y <= 44 * (i - 1) + 334:
                self._sfx(8)      # 游戏 sub_426004: 标题三按钮点击
                if i == 1:
                    # 新的游戏 → 回主菜单 (游戏: sub_412688 进入游戏主流程)
                    # 离开标题界面 → 停止 BGM (主菜单不播, 对齐用户需求)
                    self._audio().stop_bgm()
                    self._title_mode = False
                    self._title_hover = 0
                    self._refresh()
                elif i == 2:
                    # 继续游戏 → 存档页 (读档模式, sub_426004 L33-42)
                    # 离开标题界面 → 停止 BGM (存档页不播)
                    self._audio().stop_bgm()
                    self._save_mode = 2
                    self._save_page = 0
                    self._save_hover = 0
                    self._refresh()
                else:
                    # 离开游戏 → 退出图鉴程序 (游戏: SendMessageA(hWnd, WM_CLOSE))
                    app = QApplication.instance()
                    if app is not None:
                        app.quit()
                return

    def _audio_click(self, x, kind):
        """系统页两行点击 (sub_41FAAC case 5 L289-372):
        - x=441-504 且当前关 → 开启; x=541-604 且当前开 → 关闭
        - x=13v+332..13v+344 (v=1..5) 且当前开 → 设置音量 v
        游戏语义: 第一行(图鉴 _se_*)=BGM(mp3, word_755C78/7A), 第二行(图鉴 _bgm_*)=音效
        (WAV, word_755C74/76); 每个生效分支都有 sub_451C38(0) 点击音。
        """
        if kind == 'se':
            on, vol = self._se_on, self._se_vol
        else:
            on, vol = self._bgm_on, self._bgm_vol
        a = self._audio()
        # 开关旋钮: 开位 441-504 / 关位 541-604
        if 441 <= x <= 504 and not on:
            self._sfx(4)          # 游戏: 开启点击音
            if kind == 'se':
                self._se_on = True
                a.set_bgm_enabled(True)      # 第一行 = BGM (word_755C78)
            else:
                self._bgm_on = True
                a.set_sfx_enabled(True)      # 第二行 = 音效 (word_755C74)
            self._refresh()
            return
        if 541 <= x <= 604 and on:
            self._sfx(4)          # 游戏: 关闭点击音
            if kind == 'se':
                self._se_on = False
                a.set_bgm_enabled(False)     # 第一行 = BGM
            else:
                self._bgm_on = False
                a.set_sfx_enabled(False)     # 第二行 = 音效
            self._refresh()
            return
        # 音量滑块 (5 档, 仅开启时生效): v=1..5 → x=13v+332..13v+344
        if on:
            for v in range(1, 6):
                if 13 * v + 332 <= x <= 13 * v + 344:
                    if v != vol:
                        self._sfx(4)  # 游戏: 音量点击音
                        if kind == 'se':
                            self._se_vol = v
                            a.set_bgm_volume(v)   # 第一行 = BGM 音量 (word_755C7A)
                        else:
                            self._bgm_vol = v
                            a.set_sfx_volume(v)   # 第二行 = 音效音量 (word_755C76)
                        self._refresh()
                    return

    # ── 存档页交互 (sub_41CE10 case 1/7) ──
    # 按钮区 x=452-583, 行 y=150*v+127~155 (v=0,1,2):
    #   取消 x=516-583 → arglist[614953]=0, arglist[461]=8 → 回主菜单
    #   存档/读档 x=452-515 → 图鉴只读, 无实际效果
    # 翻页箭头 x=613-632: 上 y=191-216 / 下 y=242-266

    def _save_mouse(self, x, y):
        # 按钮区域 (sub_41CE10 L42-172): x=452-583
        if 452 <= x <= 583:
            for v in range(3):
                if 150 * v + 127 <= y <= 150 * v + 155:
                    if 516 <= x <= 583:
                        # 取消 (sub_41CE10 L49-65): arglist[614953]=0, arglist[461]=8
                        # → 10 → 1: 从标题界面进入则回标题界面, 否则回主菜单 (系统页)
                        self._sfx(6)  # 游戏 sub_41CE10: 取消音效
                        self._save_mode = 0
                        self._save_page = 0
                        self._save_hover = 0
                        self._title_hover = 0
                        # 回标题界面 → 恢复 BGM (标题界面专属播放)
                        if self._title_mode:
                            self._audio().start_bgm()
                        self._refresh()
                    else:
                        # 存档/读档按钮 x=452-515: 图鉴只读无实际效果,
                        # 但游戏 sub_41CE10 L69/L157 仍播放音效
                        self._sfx(6)
                    return
            return
        # 翻页箭头 (sub_41CE10 L174-198): x=613-632 (成功翻页才响, 边界不响)
        if 613 <= x <= 632:
            if 191 <= y <= 216 and self._save_page > 0:
                self._sfx(3)
                self._save_page -= 1
                self._save_hover = 0
                self._refresh()
            elif 242 <= y <= 266 and self._save_page < 2:
                self._sfx(3)
                self._save_page += 1
                self._save_hover = 0
                self._refresh()
