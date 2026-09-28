# -*- coding: utf-8 -*-
"""TKT 颜色宏显示辅助 — 供物品编辑器/物品选择器渲染物品名称的 FCOLOR 颜色。

只支持颜色语义: FCOLOR 设色 + FRESET 颜色还原 (FSIZE/FTYPE 等其它控制码
不处理、原样保留)。文本来自 load_tkt_simple: 控制码以原始控制字节形式存在
(0x02=FCOLOR, 0x01=FRESET, 后跟 1 字节参数); 同时兼容字面 <FCOLOR,n> 标签。
颜色表与 tkt_editor 同源: game_defs.GAME_COLORS (色号 1-32)。
"""
import html
import re

from editor_utils.game_defs import GAME_COLORS

# 与 tkt_editor.DEFAULT_FCOLOR 一致 (游戏默认色号 32 = 白)
DEFAULT_FCOLOR = 32

_FCOLOR_BYTE = 0x02
_FRESET_BYTE = 0x01
_LITERAL_FCOLOR_RE = re.compile(r'<FCOLOR,(\d+)>')

# 全部 TKT 控制码: 控制字节 → 参数字节数 (与 tkt_loader._CONTROL_TAGS 对应)
_CONTROL_BYTE_LEN = {
    0x01: 1, 0x02: 1, 0x04: 1, 0x05: 1, 0x1D: 1,
    0x14: 2, 0x15: 2, 0x16: 2,
}
_LITERAL_TAG_RE = re.compile(
    r'<(?:FRESET|FCOLOR|FCOLORD|FSIZE|FTYPE|TEXT|VARNUM|VARTXT|NAME),\d+(?:,\d+)*>')


def parse_color_segments(text):
    """将 TKT 文本解析为 [(片段文本, 颜色hex或None), ...]。

    颜色 None = 未配置颜色码 (调用方保持界面默认色, 不覆盖主题)。
    色号 1-32 有效; 越界/不完整的控制字节按原文保留 (与改动前显示一致)。
    FRESET 语义与 tkt_editor 相同: 1/3 → 默认色, 2 → 还原上一个颜色。
    """
    segs = []
    buf = []
    cur = None   # 当前颜色 (None=未配置颜色码)
    prev = None  # 上一个颜色 (FRESET,2 还原用)

    def flush():
        if buf:
            segs.append((''.join(buf), cur))
            buf.clear()

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        code = ord(ch)
        nxt = ord(text[i + 1]) if i + 1 < n else None
        # FCOLOR/FRESET 控制字节无条件消费:
        # 参数字节可能本身是空白字符 (色号 9-13、28-32), 无效时仅剥离不设色,
        # 避免残留控制字节显示为方框
        if code in (_FCOLOR_BYTE, _FRESET_BYTE):
            if nxt is None:
                i += 1
                continue
            if code == _FCOLOR_BYTE and 1 <= nxt <= 32:
                flush()
                prev, cur = cur, GAME_COLORS[nxt]
                i += 2
                continue
            if code == _FRESET_BYTE and nxt in (1, 2, 3):
                flush()
                cur = prev if nxt == 2 else None
                i += 2
                continue
            # 无效参数: 参数位是控制/空白字符 (上游 split/strip 破坏所致) 一并
            # 消费; 参数位是普通文字则仅剥离控制字节本身
            i += 2 if nxt < 0x21 else 1
            continue
        if ch == '<':
            m = _LITERAL_FCOLOR_RE.match(text, i)
            if m:
                val = int(m.group(1))
                if 1 <= val <= 32:
                    flush()
                    prev, cur = cur, GAME_COLORS[val]
                    i = m.end()
                    continue
        buf.append(ch)
        i += 1
    flush()
    return segs


def strip_tkt_macros(text):
    """剥离全部 TKT 宏代码, 返回纯显示文本 (不做任何颜色渲染)。

    用于字段下方预览文本等只求干净文本的位置: 剥掉控制码字节序列
    (FCOLOR/FRESET/FSIZE/FTYPE/NAME/TEXT/VARNUM/VARTXT) 与字面 <TAG,n>
    标签及杂散控制字符, 避免它们显示为方框; 换行保留。
    """
    if not text:
        return text or ""
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        code = ord(ch)
        dlen = _CONTROL_BYTE_LEN.get(code)
        if dlen is not None:
            i += 1 + min(dlen, n - i - 1)
            continue
        if ch == '<':
            m = _LITERAL_TAG_RE.match(text, i)
            if m:
                i = m.end()
                continue
        if code < 0x20 and ch not in '\n\t':
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def color_segments_single_line(text):
    """解析为颜色分段并单行化 (相邻同色合并), 供表格单元格分段着色绘制。

    先解析后单行化: 色号 9-13/28-32 的参数字节本身是空白字符,
    反过来单行化会破坏颜色宏。跨段边界原有的换行/空白保留为单个空格。
    """
    segs = parse_color_segments(text or "")
    flat = []
    prev_tail_ws = False
    for t, c in segs:
        t2 = ' '.join(t.split())
        if not t2:
            prev_tail_ws = prev_tail_ws or bool(t and t[-1:].isspace())
            continue
        lead = ' ' if (flat and (prev_tail_ws or t[:1].isspace())) else ''
        if flat and flat[-1][1] == c:
            flat[-1][0] += lead + t2
        else:
            flat.append([lead + t2, c])
        prev_tail_ws = bool(t and t[-1:].isspace())
    return [(t, c) for t, c in flat]


def item_name_color_text(text):
    """列表单元格用: 返回 (去除颜色宏后的纯文本, 首个显示文本的颜色或 None)。

    单元格只能整格一色, 取第一段实际显示文本所用的颜色
    (连续 FCOLOR 紧邻时与游戏渲染一致, 后设者生效)。
    """
    segs = parse_color_segments(text or "")
    if not segs:
        return text or "", None
    plain = ''.join(t for t, _ in segs)
    color = next((c for t, c in segs if t and c), None)
    return plain, color


def color_tags_html(text):
    """QLabel 富文本用: 按颜色分段转 HTML (换行转 <br>)。

    无任何颜色码时返回 None, 调用方维持原 setText 纯文本路径,
    避免把含 '<' 的普通文本误走富文本渲染。
    """
    segs = parse_color_segments(text or "")
    if not any(c for _, c in segs):
        return None
    merged = []
    for t, c in segs:
        if merged and merged[-1][1] == c:
            merged[-1][0] += t
        else:
            merged.append([t, c])
    parts = []
    for t, c in merged:
        esc = html.escape(t).replace('\n', '<br>')
        parts.append(f'<font color="{c}">{esc}</font>' if c else esc)
    return ''.join(parts)
