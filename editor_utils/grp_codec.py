"""
grp_codec — GRP 区段编解码 + 图层差分公共模块
=================================================
为 GRP 编辑器与启动器提供统一、字节一致的 GRP 区段编解码能力，以及
"图层差分" (grp_layer_diff) MOD 的差分/合并原语。

只依赖 struct / base64 / editor_utils.lzss (stream 变体)，不引入任何 GUI 依赖，
因此可被 tks_launcher_gui 的合并流程直接复用。

GRP 图像区段布局 (与 grp_editor_v2.py 一致):
  [12B 头: <HHII> = width, height, comp_a, comp_b]
  [FrameA: <I 原始长度> + LZSS(stream) 主图, RGB565 每像素 2 字节]
  [FrameB: <I 声明长度> + RLE字节对(L1[+L2]) 或 LZSS 回退]
其中 L1 = 前景遮挡层 (W*H 字节), L2 = 碰撞层 (W*H 字节)。

图层差分平面:
  A  = 主图        (W*H*2 字节, 2 字节整像素对齐)
  L1 = 前景层      (W*H 字节)
  L2 = 碰撞层      (W*H 字节)
跨度 span = [起始字节下标, [新值, ...]]，只记录发生变化的连续像素。
"""
import base64
import struct

from editor_utils.lzss import lzss_compress_stream, lzss_decompress_stream

GRP_LAYER_DIFF = "grp_layer_diff"


# ═══════════════════════════════════════════════════════════════
# RLE 字节对 (GRP FrameB 专用)
# ═══════════════════════════════════════════════════════════════

def rle_bp_decompress(data: bytes, target_size: int) -> bytes:
    out = bytearray()
    pos = 0
    while pos + 1 < len(data) and len(out) < target_size:
        count, value = data[pos], data[pos + 1]
        pos += 2
        out.extend(bytes([value] * count))
    return bytes(out[:target_size])


def rle_bp_probe(data: bytes, expected_size: int) -> bool:
    total, pos = 0, 0
    while pos + 1 < len(data):
        total += data[pos]
        pos += 2
    return total == expected_size


def rle_bp_compress(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        v = data[i]
        c = 1
        while i + c < n and data[i + c] == v and c < 255:
            c += 1
        out.append(c)
        out.append(v)
        i += c
    return bytes(out)


# ═══════════════════════════════════════════════════════════════
# 区段解码 / 编码
# ═══════════════════════════════════════════════════════════════

def decode_section(section_bytes: bytes, need_a: bool = True):
    """将单个 GRP 图像区段的原始字节解码为平面。

    need_a=False 时跳过主图 LZSS 解压 (A=None), 用于“仅改图层”合并时
    避免一次无意义的大图解压; 此时 fa_bytes 仍可用于原样复用。

    Returns:
        dict(width,height,comp_a,comp_b,fa_bytes,fb_bytes,A,L1,L2,has_layer2,
             total_px,uncomp_a) 或 None (非有效图像区段)。
        fa_bytes/fb_bytes 为原始压缩块，供未变平面原样复用。
    """
    if section_bytes is None or len(section_bytes) < 12:
        return None
    w, h, comp_a, comp_b = struct.unpack_from("<HHII", section_bytes, 0)
    if not (1 <= w <= 4096 and 1 <= h <= 4096):
        return None
    if comp_a <= 0 or comp_b <= 0 or 12 + comp_a + comp_b != len(section_bytes):
        return None

    total_px = w * h
    uncomp_a = total_px * 2
    fa_bytes = section_bytes[12:12 + comp_a]
    fb_bytes = section_bytes[12 + comp_a:12 + comp_a + comp_b]

    if len(fa_bytes) < 4:
        return None

    # ── FrameA (主图) ── 仅在需要时解压 (避免图层-only 合并时浪费一次大图 LZSS 解压)
    if need_a:
        uncomp_sz = struct.unpack_from("<I", fa_bytes, 0)[0]
        a_stream = fa_bytes[4:]
        A = lzss_decompress_stream(a_stream, min(uncomp_sz, uncomp_a))
        if len(A) < uncomp_a:
            A = A + b'\x00' * (uncomp_a - len(A))
        else:
            A = A[:uncomp_a]
    else:
        A = None

    # ── FrameB (图层) ──
    L1 = None
    L2 = None
    has_layer2 = False
    if len(fb_bytes) >= 4:
        declared = struct.unpack_from("<I", fb_bytes, 0)[0]
        comp_data = fb_bytes[4:]
        if rle_bp_probe(comp_data, declared):
            raw = rle_bp_decompress(comp_data, declared)
            L1 = raw[:total_px]
            if len(L1) < total_px:
                L1 = L1 + b'\x00' * (total_px - len(L1))
            if declared == total_px * 2 and len(raw) >= total_px * 2:
                L2 = raw[total_px:total_px * 2]
                has_layer2 = True
        else:
            raw = lzss_decompress_stream(comp_data, uncomp_a)
            L1 = bytes(raw[i] for i in range(0, min(len(raw), total_px * 2), 2))
            if len(L1) < total_px:
                L1 = L1 + b'\x00' * (total_px - len(L1))
    if L1 is None:
        L1 = b'\x00' * total_px

    return {
        'width': w, 'height': h, 'comp_a': comp_a, 'comp_b': comp_b,
        'fa_bytes': fa_bytes, 'fb_bytes': fb_bytes,
        'A': A, 'L1': L1, 'L2': L2, 'has_layer2': has_layer2,
        'total_px': total_px, 'uncomp_a': uncomp_a,
    }


def encode_section(width: int, height: int, A, L1, L2, has_layer2: bool,
                   reuse_fa=None, reuse_fb=None) -> bytes:
    """将平面重新编码为 GRP 图像区段字节 (对齐 grp_editor_v2.save_grp)。

    只重压缩发生变化的平面组：
      - reuse_fa 提供 → 主图未变，原样复用 FrameA 压缩块；否则 LZSS(A)。
      - reuse_fb 提供 → 图层未变，原样复用 FrameB 压缩块；否则 RLE(L1[+L2])。
    """
    total_px = width * height
    uncomp_a = total_px * 2

    # ── FrameA ──
    if reuse_fa is not None:
        fa_data = bytes(reuse_fa)
    else:
        body = bytes(A)[:uncomp_a].ljust(uncomp_a, b'\x00')
        fa_body = lzss_compress_stream(body)
        fa_data = struct.pack("<I", uncomp_a) + fa_body
    comp_a = len(fa_data)

    # ── FrameB ──
    if reuse_fb is not None:
        fb_data = bytes(reuse_fb)
    else:
        if has_layer2 and L2 is not None:
            fb_raw = (bytes(L1) + bytes(L2))[:uncomp_a]
        elif L1 is not None:
            fb_raw = bytes(L1)[:total_px]
        else:
            fb_raw = b""
        fb_body = rle_bp_compress(fb_raw)
        fb_data = struct.pack("<I", len(fb_raw)) + fb_body
    comp_b = len(fb_data)

    return struct.pack("<HHII", width, height, comp_a, comp_b) + fa_data + fb_data


# ═══════════════════════════════════════════════════════════════
# 平面差分 / 应用
# ═══════════════════════════════════════════════════════════════

def _diff_spans(orig: bytes, cur: bytes, align: int = 1) -> list:
    """逐字节比较，输出连续变化区间的跨度列表 [[start,[vals...]], ...]。

    align>1 时按 align 字节对齐 (A 平面用 2, 保证整像素)。
    """
    lo, lc = len(orig), len(cur)
    n = max(lo, lc)
    spans = []
    k = 0
    while k < n:
        ob = orig[k] if k < lo else 0
        cb = cur[k] if k < lc else 0
        if ob == cb:
            k += 1
            continue
        start = k
        while k < n:
            o2 = orig[k] if k < lo else 0
            c2 = cur[k] if k < lc else 0
            if o2 == c2:
                break
            k += 1
        end = k
        if align > 1:
            start -= start % align
            r = end % align
            if r:
                end += (align - r)
            if end > n:
                end = n
        vals = [(cur[i] if i < lc else 0) for i in range(start, end)]
        spans.append([start, vals])
        k = end
    return spans


def diff_planes(ref_dec: dict, cur_dec: dict) -> dict:
    """比较两个已解码区段的平面，返回 {plane: spans}（只含变化平面）。"""
    planes = {}
    if ref_dec['A'] != cur_dec['A']:
        s = _diff_spans(ref_dec['A'], cur_dec['A'], align=2)
        if s:
            planes['A'] = s
    if ref_dec['L1'] != cur_dec['L1']:
        s = _diff_spans(ref_dec['L1'], cur_dec['L1'], align=1)
        if s:
            planes['L1'] = s
    rl2 = ref_dec['L2'] or b''
    cl2 = cur_dec['L2'] or b''
    if rl2 != cl2:
        s = _diff_spans(rl2, cl2, align=1)
        if s:
            planes['L2'] = s
    return planes


def apply_spans(buf: bytearray, spans: list) -> bytearray:
    """将跨度差分就地应用到平面 bytearray。"""
    n = len(buf)
    for start, vals in spans:
        for j, v in enumerate(vals):
            idx = start + j
            if 0 <= idx < n:
                buf[idx] = v & 0xFF
    return buf


def span_pixel_count(spans: list, elem: int = 1) -> int:
    """跨度覆盖的像素数 (A 平面 elem=2)。"""
    total = sum(len(vals) for _s, vals in spans)
    return total // elem if elem > 1 else total


# ═══════════════════════════════════════════════════════════════
# 区段级差分条目 / 整文件差分
# ═══════════════════════════════════════════════════════════════

def diff_section_entry(ref_bytes: bytes, cur_bytes: bytes):
    """比较单个区段，返回差分条目：
       - None                              两者内容等价 (无需导出)
       - {'width','height','planes':{...}} 图像段的图层差分
       - {'data_b64': ...}                 非图像段/尺寸变化 → 整段替换回退
    """
    if ref_bytes == cur_bytes:
        return None
    ro = decode_section(ref_bytes)
    co = decode_section(cur_bytes)
    if ro and co and ro['width'] == co['width'] and ro['height'] == co['height']:
        planes = diff_planes(ro, co)
        if planes:
            return {'width': co['width'], 'height': co['height'], 'planes': planes}
        # 解码后平面一致 (仅压缩形态不同) → 视为无变化
        return None
    return {'data_b64': base64.b64encode(bytes(cur_bytes)).decode('ascii')}


def build_layer_diff(ref_sections: list, cur_sections: list, target: str = "section"):
    """对比参考与当前区段列表，生成图层差分。

    新增区段(新地图)以**原始二进制**形式单独返回(blobs), 由调用方写入
    .tksmod 的 ZIP 二进制成员; appended 条目仅引用成员名(bin)。
    这比 base64-in-JSON 体积更小(base64 会破坏 DEFLATE 的 LZ77 匹配)。

    Returns:
        (modified: {str(idx): entry}, appended: [{index,bin}],
         deleted_indices: [idx,...], stats: [(idx, {plane: pixels}), ...],
         blobs: {member_name: raw_bytes})
    """
    modified = {}
    appended = []
    deleted = []
    stats = []
    blobs = {}

    n = min(len(ref_sections), len(cur_sections))
    for i in range(n):
        entry = diff_section_entry(ref_sections[i], cur_sections[i])
        if entry is None:
            continue
        modified[str(i)] = entry
        if 'planes' in entry:
            pc = {p: span_pixel_count(entry['planes'][p], 2 if p == 'A' else 1)
                  for p in entry['planes']}
            stats.append((i, pc))
        else:
            stats.append((i, {'full': 1}))

    for i in range(len(ref_sections), len(cur_sections)):
        name = f"blobs/{target}.{i}.bin"
        appended.append({'index': i, 'bin': name})
        blobs[name] = bytes(cur_sections[i])

    for i in range(len(cur_sections), len(ref_sections)):
        deleted.append(i)

    return modified, appended, deleted, stats, blobs


def build_layer_diff_json(target: str, original_count: int, original_crc32: str,
                          modified: dict, appended: list, deleted: list) -> dict:
    """组装 grp_layer_diff 的数据差异 JSON。"""
    return {
        "target": target,
        "patch_type": GRP_LAYER_DIFF,
        "original_crc32": original_crc32,
        "original_count": original_count,
        "modified": modified,
        "appended": appended,
        "deleted_indices": deleted,
    }


def apply_layer_diff_to_sections(base_sections: list, diff_data: dict,
                                 blobs: dict | None = None) -> list:
    """将单个 grp_layer_diff 应用到基准区段列表, 返回完整区段列表。

    供编辑器导入预览使用 (单 MOD, 不做跨 MOD 冲突检测)。
    兼容 modified 为 dict (图层差分) 或 list (旧 block_diff)。
    blobs: {member_name: raw_bytes} — appended 区段的二进制成员 (新格式);
           旧格式的 appended 仍可用 data_b64。
    """
    sections = list(base_sections)
    blobs = blobs or {}
    modified = diff_data.get("modified", {})

    if isinstance(modified, dict):
        for sidx_str, entry in modified.items():
            try:
                sidx = int(sidx_str)
            except (ValueError, TypeError):
                continue
            if 'planes' in entry:
                if not (0 <= sidx < len(base_sections)):
                    continue
                need_a = 'A' in entry['planes']
                dec = decode_section(base_sections[sidx], need_a=need_a)
                if dec is None:
                    continue
                A = bytearray(dec['A']) if dec['A'] is not None else None
                L1 = bytearray(dec['L1'])
                L2 = bytearray(dec['L2']) if dec['L2'] is not None else None
                has2 = dec['has_layer2']
                touched = set()
                for plane, spans in entry['planes'].items():
                    if plane == 'L2' and L2 is None:
                        L2 = bytearray(dec['total_px'])
                        has2 = True
                    buf = A if plane == 'A' else (L1 if plane == 'L1' else L2)
                    if buf is None:
                        continue
                    apply_spans(buf, spans)
                    touched.add('A' if plane == 'A' else 'B')
                reuse_fa = None if 'A' in touched else dec['fa_bytes']
                reuse_fb = None if 'B' in touched else dec['fb_bytes']
                sections[sidx] = encode_section(
                    dec['width'], dec['height'],
                    bytes(A) if A is not None else None, bytes(L1),
                    bytes(L2) if L2 is not None else None,
                    has2, reuse_fa=reuse_fa, reuse_fb=reuse_fb)
            elif 'data_b64' in entry:
                if 0 <= sidx < len(sections):
                    sections[sidx] = base64.b64decode(entry['data_b64'])
    elif isinstance(modified, list):
        for e in modified:
            idx = e.get('index', -1)
            b = e.get('data_b64', '')
            if 0 <= idx < len(sections) and b:
                sections[idx] = base64.b64decode(b)

    for e in diff_data.get("appended", []):
        idx = e.get('index', -1)
        raw = None
        if e.get('bin') and blobs:
            raw = blobs.get(e['bin'])
        elif e.get('data_b64'):
            raw = base64.b64decode(e['data_b64'])
        if raw is not None and idx >= 0:
            while len(sections) <= idx:
                sections.append(b'')
            sections[idx] = raw
    for idx in sorted(diff_data.get("deleted_indices", []), reverse=True):
        if 0 <= idx < len(sections):
            sections[idx] = b''

    return sections


def read_blob_members(source, prefix: str = "blobs/") -> dict:
    """从 .tksmod (文件路径或 ZIP 字节) 读取指定前缀的二进制成员。

    返回 {member_name: raw_bytes}。仅用标准库, 无 GUI 依赖, 可被启动器复用。
    """
    import io
    import zipfile
    try:
        if isinstance(source, (bytes, bytearray)):
            zf = zipfile.ZipFile(io.BytesIO(source))
        else:
            zf = zipfile.ZipFile(source)
        with zf:
            return {n: zf.read(n) for n in zf.namelist()
                    if n.startswith(prefix) and not n.endswith('/')}
    except Exception:
        return {}


def merge_layer_diff_into_sections(base_sections: list, diff_data: dict,
                                   blobs: dict | None = None):
    """将一个 grp_layer_diff 累加合并进 base_sections (编辑器"合并进当前GRP")。

    与 apply_layer_diff_to_sections 的区别: appended 区段不再按声明索引放置,
    而是 内容去重 + 顺延到空位, 用于把多个新地图 MOD 叠加成一份。

      - modified(planes):   叠加到对应区段(就地);
      - modified(data_b64): 覆盖该区段;
      - appended:           与现有区段字节相同则去重复用, 否则追加到末尾新索引;
      - deleted_indices:    合并模式下忽略 (不删现有内容)。

    Returns:
        (sections, remap) — remap: [{'declared': i, 'actual': j, 'action': '追加|去重复用|覆盖修改'}]
    """
    blobs = blobs or {}
    sections = list(base_sections)
    remap = []

    modified = diff_data.get("modified", {})
    if isinstance(modified, dict):
        for sidx_str, entry in modified.items():
            try:
                sidx = int(sidx_str)
            except (ValueError, TypeError):
                continue
            if not (0 <= sidx < len(sections)):
                continue
            if 'planes' in entry:
                dec = decode_section(sections[sidx], need_a=('A' in entry['planes']))
                if dec is None:
                    continue
                A = bytearray(dec['A']) if dec['A'] is not None else None
                L1 = bytearray(dec['L1'])
                L2 = bytearray(dec['L2']) if dec['L2'] is not None else None
                has2 = dec['has_layer2']
                touched = set()
                for plane, spans in entry['planes'].items():
                    if plane == 'L2' and L2 is None:
                        L2 = bytearray(dec['total_px'])
                        has2 = True
                    buf = A if plane == 'A' else (L1 if plane == 'L1' else L2)
                    if buf is None:
                        continue
                    apply_spans(buf, spans)
                    touched.add('A' if plane == 'A' else 'B')
                reuse_fa = None if 'A' in touched else dec['fa_bytes']
                reuse_fb = None if 'B' in touched else dec['fb_bytes']
                sections[sidx] = encode_section(
                    dec['width'], dec['height'],
                    bytes(A) if A is not None else None, bytes(L1),
                    bytes(L2) if L2 is not None else None,
                    has2, reuse_fa=reuse_fa, reuse_fb=reuse_fb)
                remap.append({'declared': sidx, 'actual': sidx, 'action': '覆盖修改'})
            elif 'data_b64' in entry:
                sections[sidx] = base64.b64decode(entry['data_b64'])
                remap.append({'declared': sidx, 'actual': sidx, 'action': '覆盖修改'})

    for e in diff_data.get("appended", []):
        declared = e.get("index", -1)
        raw = None
        if e.get('bin') and blobs:
            raw = blobs.get(e['bin'])
        elif e.get('data_b64'):
            raw = base64.b64decode(e['data_b64'])
        if raw is None:
            continue
        # 内容去重: 与现有区段字节完全相同则复用 (快速, 安全无损)
        dup = None
        for k, s in enumerate(sections):
            if s == raw:
                dup = k
                break
        if dup is not None:
            remap.append({'declared': declared, 'actual': dup, 'action': '去重复用'})
        else:
            sections.append(raw)
            remap.append({'declared': declared, 'actual': len(sections) - 1, 'action': '追加'})

    return sections, remap
