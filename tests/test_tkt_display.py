"""tkt_display 颜色宏解析回归测试 — 物品名称/说明的 FCOLOR 渲染。"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from editor_utils.game_defs import GAME_COLORS  # noqa: E402
from editor_utils.tkt_display import (  # noqa: E402
    color_tags_html, item_name_color_text, parse_color_segments, strip_tkt_macros,
)


def _fcolor(n):
    """FCOLOR 控制字节序列 (0x02 + 色号), 与 TKT.dat 内编码一致"""
    return chr(0x02) + chr(n)


def _freset(n):
    return chr(0x01) + chr(n)


class TestParseColorSegments(unittest.TestCase):
    def test_control_byte_prefix(self):
        segs = parse_color_segments(f"{_fcolor(14)}神兵利器")
        self.assertEqual(segs, [("神兵利器", GAME_COLORS[14])])

    def test_mid_text_color(self):
        segs = parse_color_segments(f"前{_fcolor(20)}后")
        self.assertEqual(segs, [("前", None), ("后", GAME_COLORS[20])])

    def test_no_color_keeps_default(self):
        self.assertEqual(parse_color_segments("普通物品"), [("普通物品", None)])
        self.assertEqual(parse_color_segments(""), [])

    def test_literal_tag(self):
        segs = parse_color_segments("<FCOLOR,3>紅顏知己")
        self.assertEqual(segs, [("紅顏知己", GAME_COLORS[3])])

    def test_strip_mat_editor_literal_form(self):
        # mat_editor 的 TktLazyDict 解码出字面 <FCOLOR,n>/<FRESET,n> 形态,
        # 剥离后为干净名称 (保持默认色, 不渲染颜色)
        self.assertEqual(strip_tkt_macros("<FCOLOR,14>金烏劍<FRESET,2>"), "金烏劍")

    def test_freset_semantics(self):
        # FRESET,1/3 → 默认色; FRESET,2 → 还原上一个颜色 (与 tkt_editor 一致)
        segs = parse_color_segments(f"{_fcolor(20)}甲{_freset(1)}乙")
        self.assertEqual(segs, [("甲", GAME_COLORS[20]), ("乙", None)])
        segs = parse_color_segments(f"{_fcolor(20)}甲{_fcolor(3)}乙{_freset(2)}丙")
        self.assertEqual(segs, [("甲", GAME_COLORS[20]), ("乙", GAME_COLORS[3]),
                                ("丙", GAME_COLORS[20])])

    def test_whitespace_color_values(self):
        # 色号 9-13/28-32 的参数字节本身是空白字符 (如 FCOLOR,10 = \x02\x0a),
        # 不得被当作换行/空白破坏
        raw = f"{_fcolor(10)}绿色说明{_freset(1)}"
        self.assertEqual(parse_color_segments(raw),
                         [("绿色说明", GAME_COLORS[10])])
        txt, color = item_name_color_text(raw)
        self.assertEqual((txt, color), ("绿色说明", GAME_COLORS[10]))
        # 单行化放在剥离之后, 文本不受空白参数字节影响
        self.assertEqual(' '.join(txt.split()), "绿色说明")

    def test_invalid_color_stripped_not_rendered(self):
        # 无效色号/悬空控制字节: 不设色但必须剥离, 避免显示为方框;
        # 控制字节后的普通文字不被误当参数吞掉
        raw = f"甲{_fcolor(0)}乙{_fcolor(33)}丙{chr(0x02)}丁"
        self.assertEqual(parse_color_segments(raw), [("甲乙!丙丁", None)])
        txt, color = item_name_color_text(raw)
        self.assertEqual((txt, color), ("甲乙!丙丁", None))
        # 上游 split 破坏产生的 "\x02 空格" 残留也一并净化
        txt2, _ = item_name_color_text(f"{chr(0x02)} 绿色说明")
        self.assertEqual(txt2, "绿色说明")

    def test_color_range_boundaries(self):
        self.assertEqual(parse_color_segments(f"{_fcolor(1)}甲"),
                         [("甲", GAME_COLORS[1])])
        self.assertEqual(parse_color_segments(f"{_fcolor(32)}甲"),
                         [("甲", GAME_COLORS[32])])


class TestItemNameColorText(unittest.TestCase):
    def test_color_and_stripped_text(self):
        txt, color = item_name_color_text(f"{_fcolor(14)}神兵利器")
        self.assertEqual(txt, "神兵利器")
        self.assertEqual(color, GAME_COLORS[14])

    def test_mid_text_stripped_first_color_wins(self):
        txt, color = item_name_color_text(f"前{_fcolor(20)}{_fcolor(3)}后")
        self.assertEqual(txt, "前后")
        # 单元格整格一色: 取首段实际显示文本的生效颜色 (与游戏渲染一致)
        self.assertEqual(color, GAME_COLORS[3])

    def test_no_color_unchanged(self):
        txt, color = item_name_color_text("普通物品")
        self.assertEqual((txt, color), ("普通物品", None))
        self.assertEqual(item_name_color_text(""), ("", None))
        self.assertEqual(item_name_color_text(None), ("", None))


class TestColorTagsHtml(unittest.TestCase):
    def test_no_color_returns_none(self):
        self.assertIsNone(color_tags_html("普通说明"))
        self.assertIsNone(color_tags_html(""))
        # 仅其它控制码 (如 FSIZE) 不触发富文本
        self.assertIsNone(color_tags_html(f"甲{chr(0x04)}{chr(24)}乙"))

    def test_html_segments(self):
        out = color_tags_html(f"{_fcolor(14)}神兵\n利器")
        self.assertEqual(out, f'<font color="{GAME_COLORS[14]}">神兵<br>利器</font>')

    def test_html_escapes_and_merges(self):
        out = color_tags_html(f"{_fcolor(20)}<甲&>{_fcolor(20)}乙")
        self.assertEqual(out, f'<font color="{GAME_COLORS[20]}">&lt;甲&amp;&gt;乙</font>')

    def test_mixed_default_and_color(self):
        out = color_tags_html(f"前{_fcolor(3)}后")
        self.assertEqual(out, f'前<font color="{GAME_COLORS[3]}">后</font>')


class TestStripTktMacros(unittest.TestCase):
    def test_strip_color_macros(self):
        # 前后颜色宏 (截图中的前后方框) 全部剥掉
        raw = f"{_fcolor(14)}金烏劍{_freset(1)}"
        self.assertEqual(strip_tkt_macros(raw), "金烏劍")

    def test_strip_all_control_tags(self):
        # 1 字节参数 (FSIZE/FTYPE) 与 2 字节参数 (TEXT/VARNUM) 控制码
        raw = (f"{chr(0x04)}{chr(24)}甲{chr(0x05)}{chr(3)}乙"
               f"{chr(0x14)}{chr(1)}{chr(0)}丙")
        self.assertEqual(strip_tkt_macros(raw), "甲乙丙")

    def test_strip_literal_tags_and_stray_control_chars(self):
        self.assertEqual(strip_tkt_macros("<FCOLOR,3>甲<FRESET,2>乙"), "甲乙")
        raw = f"甲{chr(0x03)}乙\n丙"
        self.assertEqual(strip_tkt_macros(raw), "甲乙\n丙")

    def test_plain_text_unchanged(self):
        self.assertEqual(strip_tkt_macros("普通物品名稱"), "普通物品名稱")
        self.assertEqual(strip_tkt_macros(""), "")
        self.assertEqual(strip_tkt_macros(None), "")

    def test_dangling_control_byte_stripped(self):
        # 截断可能产生悬空控制字节 (方框来源)
        self.assertEqual(strip_tkt_macros(f"甲{chr(0x02)}"), "甲")


class TestItemPickerDescColumn(unittest.TestCase):
    """物品选择器「物品说明」列的宏渲染回归 (单元格着色 + tooltip 净化)。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_desc_cell_colored_and_tooltip_clean(self):
        from PySide6.QtCore import Qt
        from editor_utils.picker_dialogs import ColorSegmentsDelegate, ItemPickerDialog
        # 色号 20 (常规) 与色号 10 (参数字节 \x0a 是空白字符, 易被单行化破坏)
        items = [
            {'index': 0, 'item_id': 10, 'tab_code': 0, 'name': '金烏劍',
             'desc': f"{_fcolor(20)}紅字說明{_freset(1)}\n第二行",
             'equip_type': 0, 'icon': 0, 'price': 100},
            {'index': 1, 'item_id': 11, 'tab_code': 0, 'name': '玄鐵重劍',
             'desc': f"{_fcolor(10)}綠字說明",
             'equip_type': 0, 'icon': 0, 'price': 100},
            {'index': 2, 'item_id': 12, 'tab_code': 0, 'name': '普通物',
             'desc': '說明文字無宏代碼',
             'equip_type': 0, 'icon': 0, 'price': 100},
        ]
        dlg = ItemPickerDialog(None, items, title='测试')
        try:
            # 含宏说明: 段数据按颜色码分段 (UserRole, 供委托分段绘制),
            # 仅带颜色的词语着色, 其余文字保持默认色
            desc_item = dlg._table.item(0, 7)
            self.assertEqual(desc_item.text(), '紅字說明 第二行')
            self.assertEqual(desc_item.data(Qt.ItemDataRole.UserRole),
                             [('紅字說明', GAME_COLORS[20]), (' 第二行', None)])
            self.assertIsNone(desc_item.data(Qt.ItemDataRole.ForegroundRole))
            # tooltip 保留换行但无控制字节 (方框来源)
            tip = desc_item.toolTip()
            self.assertEqual(tip, '紅字說明\n第二行')
            self.assertTrue(all(ord(c) >= 0x20 or c in '\n\t' for c in tip))

            # 空白参数字节色号: 单元格无控制字节残留, 段颜色正确
            desc_item2 = dlg._table.item(1, 7)
            self.assertEqual(desc_item2.text(), '綠字說明')
            self.assertEqual(desc_item2.data(Qt.ItemDataRole.UserRole),
                             [('綠字說明', GAME_COLORS[10])])

            # 无宏说明: 不走分段绘制 (无段数据)
            self.assertIsNone(dlg._table.item(2, 7).data(Qt.ItemDataRole.UserRole))

            # 委托绘制 smoke: 真实控件抓取渲染 (含说明列分段绘制路径) 不异常
            delegate = dlg._table.itemDelegateForColumn(7)
            self.assertIsInstance(delegate, ColorSegmentsDelegate)
            dlg.resize(900, 300)
            dlg.show()
            self.app.processEvents()
            dlg._table.selectRow(0)
            self.app.processEvents()
            pix = dlg._table.viewport().grab()  # noqa: F841 渲染不崩即通过
            dlg.hide()
        finally:
            dlg.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
