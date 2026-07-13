"""
ttf_converter.py — TTF/OTF → FONT9696 字体转换器
====================================================
功能:
  - 加载任意 TTF/OTF 字体
  - 枚举所有 BIG5 码点, 渲染 96×96 1bpp 位图
  - RLE 压缩并构建完整 FONT9696 文件字节流

简繁体支持:
  - 简体模式: BIG5 → 简体 Unicode (先 big5 解码再 繁→简 转换)
  - 繁体模式: BIG5 → 繁体 Unicode (直接 big5 解码)

注: FONT9696 文件本身使用 BIG5 编码索引, 但字形内容可以是简体或繁体。
    这与 tkt_editor/控制标签体系.md 中 "字形是简体的, 用 Big5 编码索引" 一致。
"""
from __future__ import annotations

import io
import os
import struct
from typing import Callable, Optional

from font9696_codec import Font9696


# ── BIG5 → Unicode 映射 ──

# 预构建 BIG5 码点 → Unicode 字符映射表 (14758 项)
# 直接使用 Python codecs 的 big5 解码
def _build_big5_to_unicode_table() -> dict[int, str]:
    """构建 BIG5 双字节码 → Unicode 字符映射表。"""
    table = {}
    for high in range(0xA1, 0xFF):
        for low in list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF)):
            code = (high << 8) | low
            try:
                ch = bytes([high, low]).decode('big5')
                if ch:
                    table[code] = ch
            except (UnicodeDecodeError, LookupError):
                continue
    return table


_BIG5_TO_UNICODE = _build_big5_to_unicode_table()


# ── 简繁体转换 (内置 OpenCC 风格最小映射) ──
# 实际简繁转换使用 OpenCC 库 (若已安装), 否则回退到内置映射表
_T2S_TABLE: Optional[dict[str, str]] = None
_OPENCC_T2S = None


def _init_opencc() -> bool:
    """初始化 OpenCC 简繁转换器。返回是否可用。"""
    global _OPENCC_T2S, _T2S_TABLE
    if _T2S_TABLE is not None:
        return True
    try:
        import opencc  # type: ignore
        _OPENCC_T2S = opencc.OpenCC('t2s')   # 繁体→简体
        return True
    except Exception:
        # OpenCC 不可用, 使用内置最小映射表 (常见汉字)
        _T2S_TABLE = _build_builtin_t2s_table()
        return False


def _build_builtin_t2s_table() -> dict[str, str]:
    """构建内置简繁映射表 (覆盖常见字符)。

    注: 此表仅覆盖最常用字符, 强烈建议安装 opencc-python-reimplemented。
    """
    # 常见繁→简映射 (示例, 实际使用应安装 OpenCC)
    mapping = {
        '關': '关', '開': '开', '來': '来', '國': '国', '東': '东',
        '書': '书', '學': '学', '會': '会', '時': '时', '過': '过',
        '們': '们', '這': '这', '個': '个', '後': '后', '從': '从',
        '為': '为', '應': '应', '對': '对', '與': '与', '業': '业',
        '機': '机', '動': '动', '經': '经', '長': '长', '點': '点',
        '問': '问', '題': '题', '話': '话', '說': '说', '請': '请',
        '謝': '谢', '謝': '谢', '還': '还', '現': '现', '見': '见',
        '觀': '观', '讀': '读', '講': '讲', '讓': '让', '識': '识',
        '選': '选', '鄉': '乡', '頭': '头', '點': '点', '龍': '龙',
        '聖': '圣', '戰': '战', '劍': '剑', '傳': '传', '師': '师',
        '帥': '帅', '將': '将', '軍': '军', '馬': '马', '車': '车',
        '網': '网', '線': '线', '節': '节', '類': '类', '樣': '样',
        '樣': '样', '實': '实', '寫': '写', '導': '导', '專': '专',
        '屬': '属', '廠': '厂', '廣': '广', '莊': '庄', '庫': '库',
        '應': '应', '營': '营', '藝': '艺', '術': '术', '藥': '药',
        '處': '处', '號': '号', '虜': '虏', '雖': '虽', '難': '难',
        '靈': '灵', '雲': '云', '電': '电', '陽': '阳', '陰': '阴',
        '陳': '陈', '陸': '陆', '雜': '杂', '霍': '霍', '青': '青',
        '非': '非', '面': '面', '革': '革', '韓': '韩', '音': '音',
        '頂': '顶', '頓': '顿', '頗': '颇', '領': '领', '頭': '头',
        '誇': '夸', '誌': '志', '識': '识', '護': '护', '議': '议',
        '讀': '读', '變': '变', '讓': '让', '讚': '赞', '豁': '豁',
        '豹': '豹', '趙': '赵', '趣': '趣', '趨': '趋', '蹤': '踪',
        '車': '车', '軌': '轨', '軍': '军', '軒': '轩', '載': '载',
        '較': '较', '輕': '轻', '輝': '辉', '輪': '轮', '輯': '辑',
        '輸': '输', '辦': '办', '辭': '辞', '邊': '边', '還': '还',
        '進': '进', '過': '过', '適': '适', '遠': '远', '遲': '迟',
        '運': '运', '道': '道', '達': '达', '適': '适', '遵': '遵',
        '避': '避', '還': '还', '邊': '边', '醞': '酝', '醫': '医',
        '釋': '释', '鋒': '锋', '鋪': '铺', '錄': '录', '錢': '钱',
        '錦': '锦', '鍵': '键', '鍾': '钟', '鎖': '锁', '鏡': '镜',
        '鐵': '铁', '鑑': '鉴', '長': '长', '門': '门', '閉': '闭',
        '開': '开', '間': '间', '閑': '闲', '閣': '阁', '閱': '阅',
        '闆': '板', '闊': '阔', '闕': '阙', '關': '关', '闘': '斗',
        '陘': '陉', '陣': '阵', '陰': '阴', '陳': '陈', '陽': '阳',
        '階': '阶', '陞': '升', '陛': '陛', '陝': '陕', '陋': '陋',
        '陷': '陷', '陪': '陪', '陬': '陬', '陲': '陲', '陳': '陈',
        '陷': '陷', '陽': '阳', '陰': '阴', '陳': '陈', '陸': '陆',
    }
    return mapping


def _convert_t2s(ch: str) -> str:
    """繁体字符 → 简体字符。"""
    if _OPENCC_T2S is not None:
        try:
            return _OPENCC_T2S.convert(ch)
        except Exception:
            pass
    if _T2S_TABLE is not None:
        return _T2S_TABLE.get(ch, ch)
    return ch


# ── 字形渲染 ──

def _render_glyph_pillow(char: str, font, canvas_size: int = 96) -> Optional[bytes]:
    """用 PIL 渲染单字为 96×96 1bpp 笔画位图 (bit=1=笔画)。

    Args:
        char: Unicode 字符
        font: PIL.ImageFont.FreeTypeFont 实例
        canvas_size: 画布尺寸 (默认 96)

    Returns:
        1152 字节位图 (bit=1 为笔画), 或 None (无法渲染)
    """
    from PIL import Image, ImageDraw

    img = Image.new('L', (canvas_size, canvas_size), 0)
    draw = ImageDraw.Draw(img)

    # 测量字符包围盒
    try:
        bbox = draw.textbbox((0, 0), char, font=font)
    except Exception:
        return None
    if bbox is None:
        return None
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    if text_w <= 0 or text_h <= 0:
        return None

    # 居中绘制
    # 注意: bbox[0]/bbox[1] 是字符的左侧/顶部偏移 (可能为负, 因字体度量)
    px = (canvas_size - text_w) // 2 - bbox[0]
    py = (canvas_size - text_h) // 2 - bbox[1]
    draw.text((px, py), char, fill=255, font=font)

    # 二值化 → 1bpp 位图
    px_data = img.load()
    bitmap = bytearray(Font9696.GLYPH_BUF_SIZE)
    for y in range(canvas_size):
        for x in range(canvas_size):
            if px_data[x, y] >= 128:   # 笔画
                byte_idx = y * (canvas_size // 8) + (x // 8)
                bitmap[byte_idx] |= (1 << (7 - (x % 8)))

    return bytes(bitmap)


def _render_glyph_qt(char: str, font_family: str, font_pixel_size: int,
                     canvas_size: int = 96) -> Optional[bytes]:
    """用 Qt 渲染单字 (PIL 不可用时的回退方案)。

    Args:
        char: Unicode 字符
        font_family: Qt 字体族名
        font_pixel_size: 字体像素大小
        canvas_size: 画布尺寸

    Returns:
        1152 字节位图 (bit=1 为笔画), 或 None
    """
    from PySide6.QtGui import QImage, QPainter, QColor, QFont
    from PySide6.QtCore import Qt, QRect

    image = QImage(canvas_size, canvas_size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setPen(QColor(255, 255, 255, 255))
    font = QFont(font_family)
    font.setPixelSize(font_pixel_size)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, canvas_size, canvas_size), Qt.AlignCenter, char)
    painter.end()

    # 二值化 → 1bpp
    bitmap = bytearray(Font9696.GLYPH_BUF_SIZE)
    img_ptr = image.constBits()
    img_ptr.setsize(image.sizeInBytes())
    pixel_data = bytes(img_ptr)
    bytes_per_line = image.bytesPerLine()

    for y in range(canvas_size):
        line_start = y * bytes_per_line
        for x in range(canvas_size):
            # ARGB32: 每像素 4 字节 (B, G, R, A) — Qt 默认字节序
            alpha = pixel_data[line_start + x * 4 + 3]
            if alpha >= 128:
                byte_idx = y * (canvas_size // 8) + (x // 8)
                bitmap[byte_idx] |= (1 << (7 - (x % 8)))

    return bytes(bitmap)


# ── 主转换函数 ──

def generate_font9696_from_ttf(
    ttf_path: str,
    output_path: str,
    ftype_indices: list[int],
    simplified: bool = True,
    pixel_size: int = 80,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> tuple[bool, str]:
    """从 TTF 生成 FONT9696 文件。

    Args:
        ttf_path: 源 TTF/OTF 字体文件路径
        output_path: 输出 FONT9696 文件路径
        ftype_indices: 要生成的 FTYPE 区段索引列表 (0-7)
                       未列出的区段将填充空字形
        simplified: True=简体字形, False=繁体字形
        pixel_size: TTF 渲染像素大小 (建议 70-85, 留边距)
        progress_callback: (current, total, message) 进度回调

    Returns:
        (success, message)
    """
    if not os.path.isfile(ttf_path):
        return False, f"TTF 文件不存在: {ttf_path}"

    # 初始化简繁转换
    if simplified:
        _init_opencc()

    # 加载 PIL 字体 (优先)
    pil_font = None
    try:
        from PIL import ImageFont
        pil_font = ImageFont.truetype(ttf_path, pixel_size)
    except ImportError:
        pass
    except Exception as e:
        return False, f"加载 TTF 失败: {e}"

    # 枚举所有 BIG5 码点 (单区段, 14758 项)
    all_codes = Font9696.iter_all_big5_codes()   # [(big5, idx_in_section)]
    total = len(all_codes) * len(ftype_indices)
    current = 0

    glyphs: dict[int, bytes] = {}   # {glyph_global_index: rle_data}

    for ftype in ftype_indices:
        if not (0 <= ftype < Font9696.SECTIONS):
            if progress_callback:
                progress_callback(current, total, f"跳过无效 FTYPE: {ftype}")
            continue

        for big5_code, idx_in_section in all_codes:
            global_idx = idx_in_section + Font9696.GLYPHS_PER_SECTION * ftype

            # BIG5 → Unicode 字符
            ch = _BIG5_TO_UNICODE.get(big5_code)
            if ch is None:
                # 该码点 BIG5 未分配, 用空字形
                empty_bitmap = b'\x00' * Font9696.GLYPH_BUF_SIZE
                rle = Font9696.encode_rle(empty_bitmap)
                glyphs[global_idx] = rle
                current += 1
                continue

            # 简繁体转换
            if simplified:
                ch = _convert_t2s(ch)

            # 渲染字形
            stroke_bitmap = None
            if pil_font is not None:
                stroke_bitmap = _render_glyph_pillow(ch, pil_font)
            # Qt 回退渲染未实现 (依赖 QApplication, 不适合后台转换)

            if stroke_bitmap is None:
                # 渲染失败, 用空字形
                stroke_bitmap = b'\x00' * Font9696.GLYPH_BUF_SIZE

            # FONT9696 文件中 bit=1 为背景, bit=0 为笔画
            # 当前 stroke_bitmap 中 bit=1 为笔画, 需反转
            file_bitmap = Font9696.invert_polarity(stroke_bitmap)

            # RLE 压缩
            rle = Font9696.encode_rle(file_bitmap)
            glyphs[global_idx] = rle

            current += 1
            if progress_callback and current % 500 == 0:
                progress_callback(current, total,
                                  f"FTYPE {ftype}: {current}/{total} ({ch})")

    if progress_callback:
        progress_callback(total, total, "正在构建文件...")

    # 构建完整 FONT9696 字节流
    file_bytes = Font9696.build_font9696(glyphs)

    # 原子写入 (.tmp + os.replace)
    tmp_path = output_path + '.tmp'
    with open(tmp_path, 'wb') as f:
        f.write(file_bytes)
    os.replace(tmp_path, output_path)

    if progress_callback:
        progress_callback(total, total, f"完成: {output_path}")

    return True, f"成功生成 {len(glyphs)} 个字形 → {output_path}"


def generate_font9696_multi_ttf(
    ttf_paths: list[str],
    output_path: str,
    ftype_assignments: dict[int, str],
    simplified: bool = True,
    pixel_size: int = 80,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> tuple[bool, str]:
    """从多个 TTF 生成 FONT9696 文件 (不同 FTYPE 区段使用不同 TTF)。

    Args:
        ttf_paths: 所有 TTF 文件路径列表 (用于验证)
        output_path: 输出 FONT9696 文件路径
        ftype_assignments: {ftype: ttf_path} 区段→TTF 映射
                          未列出的 FTYPE 区段填充空字形
        simplified: True=简体, False=繁体
        pixel_size: TTF 渲染像素大小
        progress_callback: (current, total, message) 进度回调

    Returns:
        (success, message)
    """
    # 验证 TTF 文件
    for ttf in set(ftype_assignments.values()):
        if not os.path.isfile(ttf):
            return False, f"TTF 文件不存在: {ttf}"

    if simplified:
        _init_opencc()

    # 加载所有需要的 PIL 字体
    pil_fonts: dict[str, object] = {}
    try:
        from PIL import ImageFont
        for ttf in set(ftype_assignments.values()):
            try:
                pil_fonts[ttf] = ImageFont.truetype(ttf, pixel_size)
            except Exception as e:
                return False, f"加载 TTF 失败 ({ttf}): {e}"
    except ImportError:
        return False, "Pillow 库未安装, 无法渲染 TTF"

    all_codes = Font9696.iter_all_big5_codes()
    total = len(all_codes) * len(ftype_assignments)
    current = 0

    glyphs: dict[int, bytes] = {}

    for ftype, ttf_path in ftype_assignments.items():
        if not (0 <= ftype < Font9696.SECTIONS):
            continue
        pil_font = pil_fonts.get(ttf_path)
        if pil_font is None:
            continue

        for big5_code, idx_in_section in all_codes:
            global_idx = idx_in_section + Font9696.GLYPHS_PER_SECTION * ftype

            ch = _BIG5_TO_UNICODE.get(big5_code)
            if ch is None:
                empty_bitmap = b'\x00' * Font9696.GLYPH_BUF_SIZE
                glyphs[global_idx] = Font9696.encode_rle(empty_bitmap)
                current += 1
                continue

            if simplified:
                ch = _convert_t2s(ch)

            stroke_bitmap = _render_glyph_pillow(ch, pil_font)
            if stroke_bitmap is None:
                stroke_bitmap = b'\x00' * Font9696.GLYPH_BUF_SIZE

            file_bitmap = Font9696.invert_polarity(stroke_bitmap)
            glyphs[global_idx] = Font9696.encode_rle(file_bitmap)

            current += 1
            if progress_callback and current % 500 == 0:
                progress_callback(current, total,
                                  f"FTYPE {ftype}: {current}/{total} ({ch})")

    if progress_callback:
        progress_callback(total, total, "正在构建文件...")

    file_bytes = Font9696.build_font9696(glyphs)

    tmp_path = output_path + '.tmp'
    with open(tmp_path, 'wb') as f:
        f.write(file_bytes)
    os.replace(tmp_path, output_path)

    if progress_callback:
        progress_callback(total, total, f"完成: {output_path}")

    return True, f"成功生成 {len(glyphs)} 个字形 → {output_path}"
