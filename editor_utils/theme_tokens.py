"""主题 token 表 —— 全套件主题颜色的单一事实来源（阶段 1 产物）。

结构（2026-09-03 模板统一后为单一模板）：
  * 全套件唯一 QSS 结构模板：editor_themes/templates/base.qss.tpl
  * 每主题槽位值：本文件 SLOTS（槽位名 -> 4 元组，顺序为
    (gpt-dark, gpt-light, classic-dark, classic-light)）
  * QPalette / 画布底色 / 标题栏配色：本文件 PALETTE / CANVAS_BG / TITLEBAR
  theme_manager 加载时把槽位注入模板生成最终 QSS。
  维护规则：改结构改模板；改颜色改本文件；禁止再散落硬编码色值。

命名约定（P1 去重合并后：同值槽位已合并为单一槽位，485 -> 223）：
  语义名  高频组已语义化: accent / text_primary / text_base / text_muted /
          text_success / bd_regular / bd_inset / bd_hover / bd_accent2 /
          bg_root / bg_window / bg_surface / bg_hover / accent_soft / hairline
          —— 改一个语义槽位即全项目生效（如 accent 原 40 处重复值已归一）
  编号名  低频组暂保留首个成员的提取名，渐进语义化，改名需同步模板:
    bg_*  background 系背景色          fg_*   文字/前景色
    bd_*  border 系边框色              selbg_*  选中态背景
    altbg_* 隔行底色                   sel_*  其他 selection 系
    gridline_color_* 表格网格线        其他前缀取自属性名
  {{?name}} 可选行：某主题值为空串时该行不渲染
  —— 用于属性在 4 主题间存在性不同的行，值含完整属性行文本

查找技巧：按值（如 #212121）搜索定位槽位；再到 templates/base.qss.tpl
中搜同名槽位查看其 QSS 上下文（选择器/属性）。
"""
from __future__ import annotations


THEMES = ("gpt-dark", "gpt-light", "classic-dark", "classic-light")


def tokens_for(theme_id: str) -> dict[str, str]:
    """返回指定主题的 槽位名 -> 字面值 映射。"""
    return {name: pair[THEMES.index(theme_id)]
            for name, pair in SLOTS.items()}


SLOTS: dict[str, tuple[str, str, str, str]] = {
    'bg_root': ('#212121', '#ffffff', '#202531', '#e0e4e8'),
    'text_base': ('#ececec', '#2d2d2d', '#dcdcdc', '#222222'),
    'bg_window': ('#212121', '#ffffff', '#1d212d', '#e0e4e8'),
    'bg_04': ('#2f2f2f', '#2d2d2d', '#292f3c', '#2d2d2d'),
    'fg_02': ('#ececec', '#ffffff', '#e0e4eb', '#e0e4e8'),
    'bd_01': ('1px solid #444444', '1px solid #9a9aa6', '1px solid #3b445c', '1px solid #9a9b9d'),
    'bg_05': ('#2f2f2f', '#ffffff', '#292f3c', '#ffffff'),
    'text_primary': ('#ececec', '#2d2d2d', '#e0e4eb', '#2d2d2d'),
    'sel_01': ('rgba(16, 163, 127, 0.24)', 'rgba(16, 163, 127, 0.14)', 'rgba(71, 140, 191, 0.24)', 'rgba(71, 140, 191, 0.14)'),
    'bg_surface': ('#2f2f2f', '#ffffff', '#1a1e27', '#ffffff'),
    'bd_regular': ('1px solid #444444', '1px solid #d9d9e3', '1px solid #14171f', '1px solid #b0b5bd'),
    'gridline_color_01': ('#3a3a3a', '#ececf1', '#323a4f', '#e9edf1'),
    'sel_02': ('rgba(16, 163, 127, 0.24)', 'rgba(16, 163, 127, 0.14)', '#478cbf', '#478cbf'),
    'fg_06': ('#ececec', '#2d2d2d', '#ffffff', '#fff'),
    'altbg_01': ('#292929', '#f7f7f8', '#242934', '#f6f7f8'),
    'bg_hover': ('#3a3a3a', '#f1f1f1', '#323a4f', '#eff1f4'),
    'bg_09': ('#212121', '#f7f7f8', '#1d212d', '#f6f7f8'),
    'bg_10': ('#212121', '#f7f7f8', '#202531', '#d1d6dc'),
    'fg_10': ('#b4b4b4', '#6e6e80', '#aab4cd', '#222'),
    'bg_11': ('#2f2f2f', '#f1f1f1', '#292f3c', '#eff1f4'),
    'accent_soft': ('rgba(16, 163, 127, 0.22)', 'rgba(16, 163, 127, 0.14)', 'rgba(71, 140, 191, 0.22)', 'rgba(71, 140, 191, 0.14)'),
    'fg_12': ('#ececec', '#087f63', '#e0e4eb', '#366a91'),
    'bd_inset': ('1px solid #444444', '1px solid #d9d9e3', '1px solid #3b445c', '1px solid #d6dadf'),
    'accent': ('#10a37f', '#10a37f', '#478cbf', '#478cbf'),
    'bd_hover': ('#5a5a5a', '#b6b6c4', '#505a74', '#b6b6c4'),
    'bg_15': ('#262626', '#f7f7f8', '#212632', '#f6f7f8'),
    'fg_14': ('#777777', '#9a9aa6', '#6c7793', '#9a9b9d'),
    'bd_08': ('#333333', '#ececf1', '#2d3344', '#e9edf1'),
    'bg_16': ('#343434', '#ffffff', '#2e3548', '#cdd3d9'),
    'fg_15': ('#ececec', '#2d2d2d', '#dcdcdc', '#111'),
    'bd_09': ('1px solid #444444', '1px solid #d9d9e3', '1px solid #14171f', '1px solid #a6abb2'),
    'bg_17': ('#3a3a3a', '#f1f1f1', '#3b445c', '#b8c0c7'),
    'bg_18': ('#424242', '#e7e7e7', '#478cbf', '#8da4b8'),
    'bg_20': ('#2a2a2a', '#f7f7f8', '#252a35', '#d5d9dd'),
    'fg_17': ('#777777', '#9a9aa6', '#555', '#999'),
    'fg_18': ('#b4b4b4', '#6e6e80', '#aab4cd', '#6e6e80'),
    'hairline': ('#444444', '#d9d9e3', '#3b445c', '#d6dadf'),
    'bd_17': ('1px solid #444444', '1px solid #d9d9e3', '1px solid #3b445c', '1px solid #b0b5bd'),
    'bg_26': ('rgba(255, 255, 255, 0.04)', 'rgba(0, 0, 0, 0.03)', 'rgba(255, 255, 255, 0.04)', 'rgba(0, 0, 0, 0.03)'),
    'image_01': ('url(svg/down-arrow.svg)', 'url(svg/down-arrow-light.svg)', 'url(svg/down-arrow.svg)', 'url(svg/down-arrow-light.svg)'),
    'bg_27': ('#2f2f2f', '#ffffff', '#202531', '#ffffff'),
    'fg_22': ('#ececec', '#2d2d2d', '#dcdcdc', '#222'),
    'bg_30': ('#343434', '#f7f7f8', '#2d3446', '#f6f7f8'),
    'image_02': ('url(svg/up-arrow.svg)', 'url(svg/up-arrow-light.svg)', 'url(svg/up-arrow.svg)', 'url(svg/up-arrow-light.svg)'),
    'bg_32': ('#424242', '#ececf1', '#39425a', '#e9edf1'),
    'bd_26': ('1px solid #5a5a5a', '1px solid #b6b6c4', '1px solid #14171f', '1px solid #b0b5bd'),
    'bd_28': ('#10a37f', '#10a37f', '#3b445c', '#8da4b8'),
    'bg_37': ('#262626', '#f7f7f8', '#202531', '#e0e4e8'),
    'fg_26': ('#b4b4b4', '#6e6e80', '#a5b0cb', '#111'),
    'bg_38': ('#2f2f2f', '#ffffff', '#292f3c', '#e0e4e8'),
    'bd_30': ('1px solid #5a5a5a', '1px solid #b6b6c4', '1px solid #505a74', '1px solid #b6b6c4'),
    'bd_33': ('1px solid #3a3a3a', '1px solid #ececf1', '1px solid #14171f', '1px solid #b0b5bd'),
    'bg_40': ('transparent', 'transparent', '#1a1e27', '#f2f5f7'),
    'bg_41': ('#555555', '#c4c4cc', '#3b445c', '#b8c0c7'),
    'fg_29': ('#b4b4b4', '#6e6e80', '#dcdcdc', '#222222'),
    'bd_36': ('1px solid #333333', '1px solid #ececf1', '1px solid #14171f', '1px solid #b0b5bd'),
    'bg_47': ('#2f2f2f', '#f1f1f1', '#3b445c', '#b8c0c7'),
    'bg_48': ('rgba(16, 163, 127, 0.24)', 'rgba(16, 163, 127, 0.14)', '#478cbf', '#8da4b8'),
    'fg_31': ('#ececec', '#087f63', '#ffffff', '#111'),
    'bg_50': ('#3a3a3a', '#f1f1f1', '#478cbf', '#478cbf'),
    'fg_33': ('#ececec', '#2d2d2d', '#ffffff', '#ffffff'),
    'bg_51': ('#444444', '#ececf1', '#14171f', '#b0b5bd'),
    'fg_38': ('#6a6a6a', '#a0a0a0', '#5c6680', '#b6b6c4'),
    'bg_59': ('transparent', 'transparent', '#202531', '#e0e4e8'),
    'fg_39': ('#a0a0a0', '#8e8ea0', '#95a0bd', '#222'),
    'bd_41': ('1px solid transparent', '1px solid transparent', '1px solid #14171f', '1px solid #b0b5bd'),
    'bg_60': ('#2f2f2f', '#f7f7f8', '#1a1e27', '#ffffff'),
    'fg_40': ('#10a37f', '#087f63', '#478cbf', '#478cbf'),
    'bd_accent2': ('2px solid #10a37f', '2px solid #10a37f', '2px solid #478cbf', '2px solid #478cbf'),
    'fg_42': ('#666666', '#b6b6c4', '#5c6680', '#b6b6c4'),
    'bg_62': ('#2f2f2f', '#f7f7f8', '#292f3c', '#f6f7f8'),
    'text_muted': ('#a0a0a0', '#6e6e80', '#95a0bd', '#6e6e80'),
    'bg_65': ('#2a2a2a', '#f1f1f1', '#252a35', '#eff1f4'),
    'bd_51': ('1px solid #212121', '1px solid #ffffff', '1px solid #1d212d', '1px solid #e0e4e8'),
    'fg_46': ('#666666', '#9a9aa6', '#5c6680', '#9a9b9d'),
    'bg_68': ('#171717', '#f7f7f8', '#14171f', '#b0b5bd'),
    'fg_47': ('#d6d6d6', '#3f3f4d', '#a5b0cb', '#111'),
    'bg_71': ('#1f1f1f', '#f7f7f8', '#1a1e27', '#ffffff'),
    'bd_57': ('1px solid #3a3a3a', '1px solid #ececf1', 'none', 'none'),
    'bg_73': ('#2f2f2f', '#ececf1', '#1a1e27', '#ffffff'),
    'bg_74': ('#777777', '#9a9aa6', '#3b445c', '#b8c0c7'),
    'fg_49': ('#8e8e8e', '#8e8ea0', '#888', '#666'),
    'fg_51': ('#b4b4b4', '#6e6e80', '#a5b0cb', '#333333'),
    'fg_52': ('#555555', '#c4c4cc', '#3b445c', '#a0a8b4'),
    'fg_53': ('#a0a0a0', '#8e8ea0', '#8a96b3', '#555555'),
    'fg_54': ('#858585', '#9a9aa6', '#6a7590', '#777777'),
    'fg_55': ('#8e8e8e', '#8e8ea0', '#888888', '#888888'),
    'fg_56': ('#c5c5c5', '#2d2d2d', '#a5b0cb', '#111'),
    'fg_57': ('#a0a0a0', '#444', '#8a96b3', '#444'),
    'bg_79': ('#262626', '#f7f7f8', 'transparent', 'transparent'),
    'bd_62': ('1px solid #444444', '1px solid #d9d9e3', 'none', 'none'),
    'bd_63': ('2px solid #10a37f', '2px solid #10a37f', '2px solid #2b4f70', '2px solid #8caec7'),
    'fg_58': ('#e0e4eb', '#2d2d2d', '#e0e4eb', '#111111'),
    'fg_59': ('#a0a0a0', '#8e8ea0', '#8a96b3', '#666666'),
    'bd_64': ('1px solid #343434', '1px solid #ececf1', '1px solid #2e3548', '1px solid #d8dce3'),
    'text_success': ('#45c49a', '#178a39', '#55b572', '#178a39'),
    'fg_61': ('#f0a27e', '#c93b16', '#e27d60', '#c93b16'),
    'bg_80': ('#262626', '#ffffff', '#161923', '#f7f9fa'),
    'bd_65': ('1px solid #444444', '1px solid #d9d9e3', '1px solid #0b0c12', '1px solid #c2c7ce'),
    'bg_81': ('#2b2b2b', '#ffffff', '#1a1e29', '#ffffff'),
    'bd_66': ('1px solid #10a37f', '1px solid #10a37f', '1px solid #478cbf', '1px solid #478cbf'),
    'fg_62': ('#e0e4eb', '#2d2d2d', '#e0e4eb', '#222222'),
    'fg_63': ('', '    selection-color: #ffffff;', '', '    selection-color: #ffffff;'),
    'bd_67': ('1px solid #212121', '1px solid #ececf1', '1px solid #202531', '1px solid #d8dce3'),
    'fg_64': ('#a0a0a0', '#9a9aa6', '#8a96b3', '#555555'),
    'bg_82': ('#343434', '#ececf1', '#2e3548', '#e5e9f0'),
    'fg_65': ('#ffffff', '#2d2d2d', '#ffffff', '#111111'),
    'bg_83': ('#343434', '#ececf1', '#2d3446', '#e9edf1'),
    'fg_66': ('#ffffff', '#2d2d2d', '#ffffff', '#2d2d2d'),
    'bg_84': ('#212121', '#ececf1', '#202531', '#d8dce3'),
    'fg_69': ('#a0a0a0', '#8e8ea0', '#8a96b3', '#666'),
    'fg_70': ('#ef4444', '#cc3333', '#CC3333', '#cc3333'),
    'bd_69': ('1px solid #0d8c6d', '1px solid #0d8c6d', '1px solid #366a91', '1px solid #366a91'),
    'bg_86': ('#1aaf89', '#1aaf89', '#5aa1d5', '#5aa1d5'),
    'bg_87': ('#0d8c6d', '#0d8c6d', '#366a91', '#366a91'),
    'bg_88': ('transparent', 'transparent', '#1a1e27', '#d1d6dc'),
    'bg_90': ('#1c1c1c', '#ffffff', '#171A21', '#ffffff'),
    'bg_91': ('#2a2a2a', '#f7f7f8', '#252a35', '#e8ecf0'),
    'bd_72': ('#2f2f2f', '#f7f7f8', '#1a1e27', '#d1d6dc'),
    'bg_92': ('#265c50', '#8CB8D9', '#2D4A5E', '#8CB8D9'),
    'bg_93': ('#10a37f', '#6e6e80', '#478cbf', '#8da4b8'),
    'fg_73': ('#4ade80', '#2E7D32', '#55b572', '#178a39'),
    'fg_74': ('#f87171', '#C62828', '#e27d60', '#c93b16'),
    'fg_75': ('#c5c5c5', '#2d2d2d', '#a5b0cb', '#222222'),
    'fg_76': ('    color: #ececec;', '', '    color: #dcdcdc;', ''),
    'bg_98': ('#1aaf89', '#1aaf89', '#5a9ccc', '#5a9ccc'),
    'bg_99': ('#0f5f4c', '#10a37f', '#2b4f70', '#478cbf'),
    'fg_77': ('#e6fff7', '#ffffff', '#e1ebf4', '#ffffff'),
    'bd_74': ('1px solid #0b4c3d', '1px solid #0d8c6d', '1px solid #1e3448', '1px solid #366a91'),
    'bg_100': ('#126e59', '#1aaf89', '#366a91', '#5a9ccc'),
    'bg_101': ('#0b4c3d', '#0d8c6d', '#1e3448', '#366a91'),
    'bg_102': ('#1d3d33', '#b7e2d6', '#313b46', '#c2d0dd'),
    'fg_78': ('#5f8a7c', '#6b9687', '#757f88', '#7b8996'),
    'bd_75': ('#27554a', '#a3d5c5', '#3e4d5a', '#b0c2d2'),
    'fg_80': ('#8e8e8e', '#8e8ea0', '#888', '#777'),
    'bg_104': ('#343434', '#d0e8ff', '#2e3548', '#d0e8ff'),
    'fg_82': ('#55d6b2', '#087f63', '#5aa1d5', '#366a91'),
    'bg_108': ('#212121', '#ffffff', '#202531', '#f5f5f5'),
    'gridline_color_02': ('#4a4a4a', '#f7f7f8', '#2a303d', '#d1d6dc'),
    'fg_86': ('#f59e0b', '#b85c00', '#cc6600', '#b85c00'),
    'bd_80': ('1px solid #858585', '1px solid #9a9aa6', '1px solid #666', '1px solid #999'),
    'bd_81': ('1px solid #858585', '1px solid #9a9aa6', '1px solid #777', '1px solid #999'),
    'bd_84': ('2px solid #ffffff', '2px solid #ffffff', '2px solid #ffffff', '2px solid #e0e4e8'),
    'bd_85': ('1px solid #858585', '1px solid #9a9aa6', '1px solid #555', '1px solid #999'),
    'bg_112': ('#343434', '#f1f1f1', '#2d3446', '#eff1f4'),
    'bd_89': ('#4a4a4a', '#d9d9e3', '#414a63', '#d6dadf'),
    'fg_89': ('#8e8e8e', '#8e8ea0', '#838eab', '#8e8ea0'),
    'fg_91': ('#45c49a', '#178a39', '#5a9ccc', '#178a39'),
    'bd_93': ('1px solid #3a3a3a', '1px solid #ececf1', '1px solid #323a4f', '1px solid #e9edf1'),
    'fg_94': ('#8e8e8e', '#8e8ea0', '#888', '#888'),
    'fg_96': ('#ff6b6b', '#ff6b6b', '#e27d60', '#c93b16'),
    'fg_97': ('#f0a27e', '#c93b16', '#f0a27e', '#c93b16'),
    'fg_99': ('#45c49a', '#2E7D32', '#55b572', '#2E7D32'),
    'fg_100': ('#CC6600', '#B85C00', '#CC6600', '#B85C00'),
    'fg_101': ('#ef4444', '#C62828', '#CC3333', '#C62828'),
    'fg_102': ('#AAAAAA', '#6e6e80', '#AAAAAA', '#999'),
    'fg_105': ('#737373', '#aaa', '#555', '#aaa'),
    'bg_119': ('#1a1d24', '#313c52', '#191d26', '#313c52'),
    'bg_121': ('rgba(255, 193, 7, 0.12)', 'rgba(255, 193, 7, 0.18)', 'rgba(255, 193, 7, 0.12)', 'rgba(255, 193, 7, 0.18)'),
    'fg_108': ('#f59e0b', '#B8860B', '#FFA000', '#B8860B'),
    'bg_122': ('rgba(16, 163, 127, 0.28)', 'rgba(16, 163, 127, 0.18)', 'rgba(71, 140, 191, 0.28)', 'rgba(71, 140, 191, 0.18)'),
    'bg_126': ('rgba(255, 255, 0, 0.08)', 'rgba(255, 255, 0, 0.12)', 'rgba(255, 255, 0, 0.08)', 'rgba(255, 255, 0, 0.12)'),
    'fg_116': ('#f59e0b', '#CC6600', '#e8a040', '#B85C00'),
    'bg_128': ('#303b52', '#eef2ff', '#303b52', '#eef2ff'),
    'fg_117': ('#e5edff', '#4f5bb5', '#e5edff', '#4f5bb5'),
    'bd_103': ('1px solid #7aa2f7', '1px solid #7c83fd', '1px solid #7aa2f7', '1px solid #7c83fd'),
    'bg_129': ('#384967', '#e3e8ff', '#384967', '#e3e8ff'),
    'bg_130': ('#26344a', '#d8dfff', '#26344a', '#d8dfff'),
    'fg_118': ('#ffffff', '#ffffff', '#ffffff', '#e0e4e8'),
    'bg_131': ('#2a3148', '#e3e6f5', '#2a3148', '#e3e6f5'),
    'fg_119': ('#8a99c2', '#7c83fd', '#8a99c2', '#7c83fd'),
    'bd_104': ('#7aa2f7', '#7c83fd', '#7aa2f7', '#7c83fd'),
    'fg_126': ('#10a37f', '#0d8c6d', '#478cbf', '#366a91'),
    'fg_127': ('#91b2ff', '#4f5bb5', '#91b2ff', '#4f5bb5'),
    'bg_140': ('#262626', '#ffffff', '#212632', '#e0e4e8'),
    'bd_109': ('2px dashed #424242', '2px dashed #8e8ea0', '2px dashed #39425a', '2px dashed #8e8ea0'),
    'fg_129': ('#8e8e8e', '#6e6e80', '#838eab', '#6e6e80'),
    'bd_110': ('1px solid #343434', '1px solid #8e8ea0', '1px solid #2d3446', '1px solid #8e8ea0'),
    'fg_134': ('#1a1a1a', '#1a1a1a', '#171a21', '#222222'),
    'bd_111': ('1px solid #4a4a4a', '1px solid #d9d9e3', '1px solid #414a63', '1px solid #d6dadf'),
    'fg_135': ('#e59ac6', '#b0308a', '#e59ac6', '#b0308a'),
    'bg_144': ('rgba(229,154,198,0.16)', 'rgba(176,48,138,0.10)', 'rgba(229,154,198,0.16)', 'rgba(176,48,138,0.10)'),
    'fg_136': ('#e8a26a', '#b05a1a', '#e8a26a', '#b05a1a'),
    'bg_145': ('rgba(232,162,106,0.16)', 'rgba(176,90,26,0.10)', 'rgba(232,162,106,0.16)', 'rgba(176,90,26,0.10)'),
    'fg_137': ('#8fd48f', '#2e7d32', '#8fd48f', '#2e7d32'),
    'bg_146': ('rgba(143,212,143,0.16)', 'rgba(46,125,50,0.10)', 'rgba(143,212,143,0.16)', 'rgba(46,125,50,0.10)'),
    'fg_138': ('#7ecbd4', '#00796b', '#7ecbd4', '#00796b'),
    'bg_147': ('rgba(126,203,212,0.16)', 'rgba(0,121,107,0.10)', 'rgba(126,203,212,0.16)', 'rgba(0,121,107,0.10)'),
    'fg_139': ('#7fb3f2', '#1565c0', '#7fb3f2', '#1565c0'),
    'bg_148': ('rgba(127,179,242,0.16)', 'rgba(21,101,192,0.10)', 'rgba(127,179,242,0.16)', 'rgba(21,101,192,0.10)'),
    'fg_140': ('#d4b06e', '#8d6e00', '#d4b06e', '#8d6e00'),
    'bg_149': ('rgba(212,176,110,0.16)', 'rgba(141,110,0,0.12)', 'rgba(212,176,110,0.16)', 'rgba(141,110,0,0.12)'),
    'fg_141': ('#e58f8f', '#c62828', '#e58f8f', '#c62828'),
    'bg_150': ('rgba(229,143,143,0.16)', 'rgba(198,40,40,0.10)', 'rgba(229,143,143,0.16)', 'rgba(198,40,40,0.10)'),
    'fg_142': ('#a8b3c7', '#455a64', '#a8b3c7', '#455a64'),
    'bg_151': ('rgba(168,179,199,0.16)', 'rgba(69,90,100,0.10)', 'rgba(168,179,199,0.16)', 'rgba(69,90,100,0.10)'),
    'fg_143': ('#b79ae0', '#6a3ab2', '#b79ae0', '#6a3ab2'),
    'bg_152': ('rgba(183,154,224,0.16)', 'rgba(106,58,178,0.10)', 'rgba(183,154,224,0.16)', 'rgba(106,58,178,0.10)'),
    'fg_144': ('#9aa3b5', '#606878', '#9aa3b5', '#606878'),
    'bg_153': ('rgba(154,163,181,0.14)', 'rgba(96,104,120,0.12)', 'rgba(154,163,181,0.14)', 'rgba(96,104,120,0.12)'),
    'fg_145': ('#d7b9a5', '#5d4037', '#d7b9a5', '#5d4037'),
    'bg_154': ('rgba(215,185,165,0.16)', 'rgba(93,64,55,0.10)', 'rgba(215,185,165,0.16)', 'rgba(93,64,55,0.10)'),
    'fg_146': ('#9fa8da', '#3949ab', '#9fa8da', '#3949ab'),
    'bg_155': ('rgba(159,168,218,0.16)', 'rgba(57,73,171,0.10)', 'rgba(159,168,218,0.16)', 'rgba(57,73,171,0.10)'),
    'fg_147': ('#c5e1a5', '#558b2f', '#c5e1a5', '#558b2f'),
    'bg_156': ('rgba(197,225,165,0.16)', 'rgba(85,139,47,0.10)', 'rgba(197,225,165,0.16)', 'rgba(85,139,47,0.10)'),
    'fg_148': ('#6699cc', '#3366cc', '#6699cc', '#3366cc'),
    'fg_150': ('#ef7777', '#cc3333', '#ef7777', '#cc3333'),
    'fg_151': ('#b58fd9', '#7b4fa0', '#b58fd9', '#7b4fa0'),
    'fg_152': ('#d4a855', '#a07820', '#d4a855', '#a07820'),
    'fg_153': ('#7ab8d4', '#2a6f8c', '#7ab8d4', '#2a6f8c'),
    'bg_158': ('#171717', '#f7f7f8', '#14171f', '#f6f7f8'),
    'bd_112': ('1px solid #333333', '1px solid #ececf1', '1px solid #2d3344', '1px solid #e9edf1'),
    'bg_162': ('#424242', '#e7e7e7', '#39425a', '#e3e7ed'),
    'bg_165': ('#1c1c1c', '#f1f1f1', '#191c24', '#eff1f4'),
    'bd_116': ('1px solid #3a3a3a', '1px solid #d9d9e3', '1px solid #323a4f', '1px solid #d6dadf'),
    'bg_167': ('#262626', '#ffffff', '#212632', '#ffffff'),
    'gridline_color_03': ('#393939', '#e3e3e8', '#32394e', '#e0e4e8'),
    'fg_161': ('#45c49a', '#087f63', '#5a9ccc', '#366a91'),
    'bg_171': ('rgba(16, 163, 127, 0.16)', 'rgba(16, 163, 127, 0.12)', 'rgba(71, 140, 191, 0.16)', 'rgba(71, 140, 191, 0.12)'),
    'bg_172': ('rgba(122, 162, 247, 0.16)', 'rgba(124, 131, 253, 0.14)', 'rgba(122, 162, 247, 0.16)', 'rgba(124, 131, 253, 0.14)'),
    'fg_166': ('#a0a0a0', '#8e8ea0', '#95a0bd', '#8e8ea0'),
    'bd_error': ('2px solid #ef4444', '2px solid #c62828', '2px solid #ef4444', '2px solid #c62828'),
    # ── 排版槽位首批 (P1-6): 颜色槽位之外的排版令牌起步 ──
    # fs_body 正文字号 (正文/预览描述/成员名等); radius_md 主圆角 (按钮/输入框/卡片)
    'fs_body': ('13px', '13px', '13px', '13px'),
    'radius_md': ('8px', '8px', '8px', '8px'),
}

# ── 业务自绘控件语义色板 ──────────────────────────────────────────────
# 每张表 = 一个业务控件族的颜色键集；值顺序与 THEMES 一致:
# (gpt-dark, gpt-light, classic-dark, classic-light)。
# 业务代码经 theme_manager.business_colors(table, theme_id) 按主题取值。

# 启动模式卡片 (mode_card.py, 自绘 QAbstractButton)。
# base/base_hover 为 (背景, 边框, 标题文字RGBA)；badge_* 为 (背景, 文字, 边框)。
# 语义: 标准=主操作 (现代族绿 / 经典族 Godot 蓝 #478cbf 系)、兼容=靛蓝辅助。
MODE_CARD: dict[str, tuple] = {
    "base": (("#2f2f2f", "#444444", (236, 236, 236, 220)),
             ("#f7f7f8", "#d9d9e3", (45, 45, 45, 220)),
             ("#1a1e27", "#14171f", (220, 220, 220, 220)),
             ("#ffffff", "#b0b5bd", (34, 34, 34, 220))),
    "base_hover": (("#383838", "#5a5a5a", (236, 236, 236, 235)),
                   ("#f1f1f1", "#b6b6c4", (45, 45, 45, 235)),
                   ("#252a35", "#2a303d", (220, 220, 220, 235)),
                   ("#f2f5f7", "#a6abb2", (34, 34, 34, 235))),
    "std": (("#0f5f4c", "#10a37f", (230, 255, 247, 255)),
            ("#e8f7f2", "#10a37f", (8, 127, 99, 255)),
            ("#2b4f70", "#478cbf", (225, 235, 244, 255)),
            ("#e8f1f8", "#478cbf", (54, 106, 145, 255))),
    "std_hover": (("#126e59", "#1aaf89", (240, 255, 250, 255)),
                  ("#d9f1e9", "#0d8c6d", (8, 111, 88, 255)),
                  ("#366a91", "#5a9ccc", (235, 243, 250, 255)),
                  ("#d9eaf6", "#366a91", (44, 90, 124, 255))),
    "compat": (("#303b52", "#7aa2f7", (229, 237, 255, 255)),
               ("#eef2ff", "#7c83fd", (63, 74, 154, 255)),
               ("#303b52", "#7aa2f7", (229, 237, 255, 255)),
               ("#eef2ff", "#7c83fd", (63, 74, 154, 255))),
    "compat_hover": (("#384967", "#91b2ff", (240, 245, 255, 255)),
                     ("#e3e8ff", "#6570d9", (52, 63, 138, 255)),
                     ("#384967", "#91b2ff", (240, 245, 255, 255)),
                     ("#e3e8ff", "#6570d9", (52, 63, 138, 255))),
    "disabled": (("#2a2a2a", "#333333", (236, 236, 236, 75)),
                 ("#f7f7f8", "#ececf1", (45, 45, 45, 80)),
                 ("#252a35", "#14171f", (220, 220, 220, 75)),
                 ("#ffffff", "#b0b5bd", (34, 34, 34, 80))),
    "checked_disabled": (("#2a2f2e", "#3d5c56", (236, 236, 236, 90)),
                         ("#edf5f2", "#9acfc0", (45, 45, 45, 105)),
                         ("#2a303d", "#3d5a74", (220, 220, 220, 90)),
                         ("#e9f1f7", "#9ac3dc", (34, 34, 34, 105))),
    "std_glow": ("#10a37f", "#10a37f", "#5a9ccc", "#478cbf"),
    "compat_glow": ("#7aa2f7", "#7c83fd", "#7aa2f7", "#7c83fd"),
    "badge_std": (("#D9FFF1", "#075C47", "#76E9C1"),
                  ("#087F63", "#FFFFFF", "#087F63"),
                  ("#dfe9f2", "#1f3f5c", "#76a1c6"),
                  ("#366a91", "#FFFFFF", "#366a91")),
    "badge_compat": (("#DDE8FF", "#1E3977", "#9DBDFF"),
                     ("#4F5BB5", "#FFFFFF", "#4F5BB5"),
                     ("#DDE8FF", "#1E3977", "#9DBDFF"),
                     ("#4F5BB5", "#FFFFFF", "#4F5BB5")),
}

# 日志控制台 (log_console.py, QSyntaxHighlighter 级别/段级着色)。
# 级别色只区分深浅，经典族沿用现代族取值（与迁移前行为一致）。
LOG_CONSOLE: dict[str, tuple[str, str, str, str]] = {
    "error": ("#F87171", "#C62828", "#F87171", "#C62828"),
    "warn": ("#F6C56B", "#9A6A00", "#F6C56B", "#9A6A00"),
    "ok": ("#4ADE80", "#2E7D32", "#4ADE80", "#2E7D32"),
    "info": ("#7AA2F7", "#4F6FD6", "#7AA2F7", "#4F6FD6"),
    "default_fg": ("#ececec", "#2d2d2d", "#ececec", "#2d2d2d"),
    "id_color": ("#82AAFF", "#1D4ED8", "#82AAFF", "#1D4ED8"),
    "hex_color": ("#2DD4BF", "#0D9488", "#2DD4BF", "#0D9488"),
}

# 精灵表编辑器 (spritesheet_editor.py) 画布视口底色 —— 图像编辑器惯例,
# 恒为深色系 (不随主题明暗变化, 仅深浅两档微调; classic 沿用 modern 取值)。
SPRITESHEET: dict[str, tuple[str, str, str, str]] = {
    "canvas_bg": ("#1a1d24", "#313c52", "#1a1d24", "#313c52"),
}

# 技能图谱 (skill_editor.py: SkillGraphView / SkillTreeDialog / 详情面板)。
# type_* 为技能类型色板 dict ({0=指令 1=主动 2=被动 3=移动, "_"=未知兜底})。
SKILL_GRAPH: dict[str, tuple] = {
    "canvas_bg": ("#12151d", "#f4f6fa", "#12151d", "#f4f6fa"),
    "grid_dot": ("#28303f", "#dde3ee", "#28303f", "#dde3ee"),
    "type_graph": (
        {0: "#4d90d0", 1: "#e8815f", 2: "#5cbf82", 3: "#b98adb", "_": "#9aa4b8"},
        {0: "#2f74b0", 1: "#cf6a49", 2: "#2f9457", 3: "#8a5bb8", "_": "#5a6472"},
        {0: "#4d90d0", 1: "#e8815f", 2: "#5cbf82", 3: "#b98adb", "_": "#9aa4b8"},
        {0: "#2f74b0", 1: "#cf6a49", 2: "#2f9457", 3: "#8a5bb8", "_": "#5a6472"},
    ),
    "type_detail": (
        {0: "#478cbf", 1: "#e27d60", 2: "#55b572", 3: "#b988db", "_": "#dcdcdc"},
        {0: "#28638f", 1: "#bd5739", 2: "#2d8046", 3: "#8a5bb8", "_": "#222222"},
        {0: "#478cbf", 1: "#e27d60", 2: "#55b572", 3: "#b988db", "_": "#dcdcdc"},
        {0: "#28638f", 1: "#bd5739", 2: "#2d8046", 3: "#8a5bb8", "_": "#222222"},
    ),
    "edge_regroup": ("#c58af0", "#8e44ad", "#c58af0", "#8e44ad"),
    "edge_focus": ("#ffc85a", "#e0930f", "#ffc85a", "#e0930f"),
    "edge_normal": ("#586274", "#a9b2c2", "#586274", "#a9b2c2"),
    "edge_label_regroup": (("#e6d2ff", "#392c4e"), ("#6a3d99", "#efe4fb"),
                           ("#e6d2ff", "#392c4e"), ("#6a3d99", "#efe4fb")),
    "edge_label_self": (("#bff0cd", "#25402f"), ("#1f6b3a", "#e2f5e8"),
                        ("#bff0cd", "#25402f"), ("#1f6b3a", "#e2f5e8")),
    "edge_label_plus": (("#f0d9a8", "#322f28"), ("#8a5a00", "#f2ecdf"),
                        ("#f0d9a8", "#322f28"), ("#8a5a00", "#f2ecdf")),
    "node_fill": ("#282f3e", "#ffffff", "#282f3e", "#ffffff"),
    "node_fill_focus": ("#312b1b", "#fff7e3", "#312b1b", "#fff7e3"),
    "node_border": ("#3b4453", "#d9dfe8", "#3b4453", "#d9dfe8"),
    "node_name": ("#eef1f6", "#1f2633", "#eef1f6", "#1f2633"),
    "node_sub": ("#8b93a7", "#6b7385", "#8b93a7", "#6b7385"),
    "node_shadow": ((0, 0, 0, 90), (70, 84, 110, 40),
                    (0, 0, 0, 90), (70, 84, 110, 40)),
    "focus_border": ("#ffc85a", "#e0930f", "#ffc85a", "#e0930f"),
    "focus_glow": ((255, 200, 90, 130), (224, 147, 15, 95),
                   (255, 200, 90, 130), (224, 147, 15, 95)),
}

# 剧本编辑器 (mat_editor.py / mat_widgets.py)。
# entity_type_colors: 实体类型色板 dict; syntax: 预览语法色板 dict;
# editor_syntax: 脚本编辑器高亮色板 dict (原 _PALETTE 深浅对)。
MAT: dict[str, tuple] = {
    "entity_type_colors": (
        {0: "#AAAAAA", 5: "#2196F3", 10: "#4CAF50", 15: "#FF9800",
                  16: "#795548", 20: "#9C27B0", 110: "#E91E63", 200: "#F44336"},
        {0: "#777777", 5: "#1565C0", 10: "#2E7D32", 15: "#E65100",
                  16: "#5D4037", 20: "#6A1B9A", 110: "#AD1457", 200: "#C62828"},
        {0: "#AAAAAA", 5: "#2196F3", 10: "#4CAF50", 15: "#FF9800",
                  16: "#795548", 20: "#9C27B0", 110: "#E91E63", 200: "#F44336"},
        {0: "#777777", 5: "#1565C0", 10: "#2E7D32", 15: "#E65100",
                  16: "#5D4037", 20: "#6A1B9A", 110: "#AD1457", 200: "#C62828"},
    ),
    "syntax": (
        {"cmd": "#dcdcdc", "talk": "#b884ff", "flow": "#5b8aff",
                 "branch": "#e0a040", "getitem": "#ff7b7b", "scene": "#6ab04c",
                 "comment": "#6a7590", "block": "#7a86a8", "raw": "#5a6480"},
        {"cmd": "#333333", "talk": "#7B30D0", "flow": "#0066CC",
                 "branch": "#CC6600", "getitem": "#CC0000", "scene": "#008800",
                 "comment": "#AAA", "block": "#BBB", "raw": "#999"},
        {"cmd": "#dcdcdc", "talk": "#b884ff", "flow": "#5b8aff",
                 "branch": "#e0a040", "getitem": "#ff7b7b", "scene": "#6ab04c",
                 "comment": "#6a7590", "block": "#7a86a8", "raw": "#5a6480"},
        {"cmd": "#333333", "talk": "#7B30D0", "flow": "#0066CC",
                 "branch": "#CC6600", "getitem": "#CC0000", "scene": "#008800",
                 "comment": "#AAA", "block": "#BBB", "raw": "#999"},
    ),
    "editor_syntax": (
        {"keyword": "#ff7085", "comment": "#6a737d", "number": "#a1ffe0",
                "command": "#a1bfff", "block": "#ffce7b"},
        {"keyword": "#d63547", "comment": "#6a737d", "number": "#2e9c6e",
                "command": "#6b89ff", "block": "#c75000"},
        {"keyword": "#ff7085", "comment": "#6a737d", "number": "#a1ffe0",
                "command": "#a1bfff", "block": "#ffce7b"},
        {"keyword": "#d63547", "comment": "#6a737d", "number": "#2e9c6e",
                "command": "#6b89ff", "block": "#c75000"},
    ),
    "pv_step_bg": ("#5a5520", "#FFEE88", "#5a5520", "#FFEE88"),
    "tkt_fallback": ("#c8c8c8", "#333333", "#c8c8c8", "#333333"),
}

# 动画编辑器 (act_editor.py) 时间轴/网格 —— 主题感知部分。
ACT: dict[str, tuple[str, str, str, str]] = {
    "timeline_bg": ("#1a1e27", "#f5f5f5", "#1a1e27", "#f5f5f5"),
    "grid_major": ("#2e3548", "#ddd", "#2e3548", "#ddd"),
    "grid_minor": ("#3b445c", "#ccc", "#3b445c", "#ccc"),
    "stmt_muted": ("#888888", "#AAAAAA", "#888888", "#AAAAAA"),
}

# 成长率面板 (picker_dialogs.GrowthTableDialog — warpc 编辑器 / tks_book 查看器共用)。
GROWTH: dict[str, tuple[str, str, str, str]] = {
    "delta": ("#55b572", "#2d7a2d", "#55b572", "#2d7a2d"),  # Δ增量
    "grp": ("#e8a040", "#cc7a20", "#e8a040", "#cc7a20"),   # grp 最终属性
}

# 启动器杂项语义色 (P3-6 收编: mod_list / 音乐弹窗 / 图片占位文案)。
# 现值主题无关 (4 元组同值), 集中于此后改色只动本处; 后续可按主题分化。
LAUNCHER: dict[str, tuple[str, str, str, str]] = {
    "dup_id": ("#dc3232", "#dc3232", "#dc3232", "#dc3232"),          # 重复 ID 警示红
    "music_modified": ("#2f80ed", "#2f80ed", "#2f80ed", "#2f80ed"),  # 音乐已修改
    "music_unmodified": ("#888888", "#888888", "#888888", "#888888"),  # 音乐未修改
    "placeholder_gray": ("#888888", "#888888", "#888888", "#888888"),  # "未选择图片"占位
}

# 路径状态色 (ui_helpers.update_path_labels): (深色主题值, 浅色主题值)。
STATUS: dict[str, tuple[str, str]] = {
    "loaded": ("#55b572", "#178a39"),
    "missing": ("#e27d60", "#c93b16"),
}

_BUSINESS: dict[str, dict[str, tuple]] = {
    "mode_card": MODE_CARD,
    "log_console": LOG_CONSOLE,
    "spritesheet": SPRITESHEET,
    "skill_graph": SKILL_GRAPH,
    "mat": MAT,
    "act": ACT,
    "growth": GROWTH,
    "launcher": LAUNCHER,
}


def business_colors(table: str, theme_id: str) -> dict:
    """返回业务控件族语义色板按主题取值后的字典。表名见 _BUSINESS。"""
    idx = THEMES.index(theme_id)
    return {key: values[idx] for key, values in _BUSINESS[table].items()}


# 各主题画布（QGraphicsView）背景色 —— 与模板中 QGraphicsView 的
# background-color 槽位语义对应（冒烟测试有一致性断言兜底）。
CANVAS_BG: dict[str, str] = {
    "gpt-dark": "#1f1f1f",
    "gpt-light": "#f7f7f8",
    "classic-dark": "#1a1e27",
    "classic-light": "#ffffff",
}


# Qt 原生控件（QSS 不覆盖的弹窗、滚动区域等）的调色板。
# 键名与 QPalette 角色的映射见 theme_manager._PALETTE_ROLE_MAP。
PALETTE: dict[str, dict[str, str]] = {
    "gpt-dark": {
        "window": "#212121", "window_text": "#ECECEC",
        "base": "#2F2F2F", "alternate_base": "#262626",
        "text": "#ECECEC", "button": "#343434", "button_text": "#ECECEC",
        "highlight": "#10A37F", "highlighted_text": "#FFFFFF",
        "placeholder_text": "#8E8E8E",
        "tooltip_base": "#2F2F2F", "tooltip_text": "#ECECEC",
    },
    "gpt-light": {
        "window": "#FFFFFF", "window_text": "#2D2D2D",
        "base": "#FFFFFF", "alternate_base": "#F7F7F8",
        "text": "#2D2D2D", "button": "#FFFFFF", "button_text": "#2D2D2D",
        "highlight": "#10A37F", "highlighted_text": "#FFFFFF",
        "placeholder_text": "#8E8EA0",
        "tooltip_base": "#2D2D2D", "tooltip_text": "#FFFFFF",
    },
    "classic-dark": {
        "window": "#202531", "window_text": "#DCDCDC",
        "base": "#1A1E27", "alternate_base": "#252A35",
        "text": "#DCDCDC", "button": "#2E3548", "button_text": "#DCDCDC",
        "highlight": "#478CBF", "highlighted_text": "#FFFFFF",
        "placeholder_text": "#8A96B3",
        "tooltip_base": "#1A1E27", "tooltip_text": "#DCDCDC",
    },
    "classic-light": {
        "window": "#E0E4E8", "window_text": "#222222",
        "base": "#FFFFFF", "alternate_base": "#F2F5F7",
        "text": "#222222", "button": "#CDD3D9", "button_text": "#111111",
        "highlight": "#478CBF", "highlighted_text": "#FFFFFF",
        "placeholder_text": "#888888",
        "tooltip_base": "#222222", "tooltip_text": "#FFFFFF",
    },
}


# Windows 原生标题栏配色（window_theme 消费，转换为 BGR 后设置 DWM 属性）。
TITLEBAR: dict[str, dict[str, str | int]] = {
    "gpt-dark": {"caption": "#212121", "border": "#444444",
                 "text": "#ECECEC", "dark_mode": 1},
    "gpt-light": {"caption": "#FFFFFF", "border": "#D9D9E3",
                  "text": "#2D2D2D", "dark_mode": 0},
    "classic-dark": {"caption": "#202531", "border": "#14171F",
                     "text": "#DCDCDC", "dark_mode": 1},
    "classic-light": {"caption": "#E0E4E8", "border": "#B0B5BD",
                      "text": "#222222", "dark_mode": 0},
}
