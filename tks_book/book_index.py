# -*- coding: utf-8 -*-
"""tks_book 反向索引层 — 物品获得途径 / 人物入队条件。

数据链路 (逆向依据见 docs/mat_editor、docs/shop_editor、docs/warpc_editor):
  TKD.dat     XOR 0xFF + Big5 → DEFINE 块; DEFINE ID = (实体ID<<16)|块号
  TKMat.Dat   实体: d0=类型 d1=场景; type110 宝箱 d53-d64 三组物品;
              type16 战斗区 d52-d54 三组战斗ID
  TKShop.dat  8B×240: area_id/item_ref(TKItem下标)/condition
  WarData.dat 498B×219: 战斗名/地图/敌人编队(WarPC索引)/战场宝物
  脚本命令:   GetItem(物品ID,数量) TeamMember(角色ID,1=加入)
              BuyMenu(编号,分类,…) War(战斗ID) Check*(前置条件)
"""
import os
import re
import struct
from collections import defaultdict

from editor_utils.lzss import lzss_decompress_dat

# ── TKMat 常量 (同 mat_constants) ──
MAT_REC_SIZE = 384
MAT_REC_COUNT = 6000

# ── WarData 常量 (同 wardata_editor) ──
WAR_REC_SIZE = 498

SHOP_AREA_NAMES = {0: "药店", 1: "道具店", 2: "武器防具店", 3: "杂货店", 4: "饰品店"}

# 比较符 (同 mat_script_desc._CMP_OPS, 逆向 sub_40E40C 系列)
CMP_OPS = {'0': "=", '1': "≥", '-1': "≤", '-2': "<", '2': ">", '3': "≠"}

MINIGAME_NAMES = {'1': "华容道", '2': "八阵图", '3': "骰子", '4': "串珠",
                  '5': "四四同数", '6': "拼图", '7': "龙蛇百变"}

# CheckTeam 类别语义 (同 mat_script_desc._CAT_NAMES, 逆向 sub_40E65C)
# 2/3/4/6 读取队伍累计四维 word_756884/886/888/88A
CHECKTEAM_CATS = {2: "智慧", 3: "仁德", 4: "勇气", 6: "医术",
                  10: "事件完成度", 11: "特殊物品收集度"}

# 旗标注释 (摘自 docs/mat_editor/TKD脚本Flag汇总.md 中带注释的条目)
FLAG_NOTES = {
    7: "關羽", 8: "張飛", 9: "黃忠", 10: "馬超", 11: "趙雲", 12: "馬良",
    13: "有找到人時", 23: "找回三人", 107: "魯肅事件", 108: "孫未回來",
    120: "已告知曹操位置", 121: "曹操未回來", 122: "開啟夏侯惇",
    124: "孔明暫時加入", 125: "孔明", 126: "周瑜暫時加入",
    128: "司馬懿暫時加入", 129: "司馬懿", 131: "劉備回來",
    133: "江夏還沒開啟", 140: "陸遜事件", 141: "給張飛的信",
    146: "找到七個以上的鼎", 147: "孫尚香", 148: "未開啟孫權對話",
    150: "未遇孫尚香之前", 151: "孫尚香出走", 152: "找回張飛後問話",
    301: "華佗", 302: "第一次遇華佗", 311: "許家村", 313: "買家具",
    315: "賣古董", 322: "1000兩", 323: "開啟貂嬋第三選項",
    325: "呂布離開洛陽", 326: "張遼離開虎牢關", 328: "完成呂布事件",
    329: "完成張角事件", 330: "赤兔馬給呂布", 336: "換龍鱗鳳羽",
    337: "換赤血青鋒", 338: "換玄鐵白玉", 339: "換千鍛百鍊",
    340: "換烈火金塵", 341: "見過貂嬋", 352: "九鼎七齊事件結束",
    353: "貂嬋", 357: "長安道士", 360: "孫尚香隱藏劇情加入",
    427: "完成救麒麟事件", 500: "完成麻沸散", 501: "沒有人的時候",
    502: "夏侯惇", 503: "完成張遼事件", 504: "典韋", 505: "賈詡",
    506: "荀彧", 507: "許褚", 999: "長安", 1001: "陸遜", 1002: "甘寧",
    1003: "太史慈", 1004: "魯肅", 1005: "呂蒙", 1006: "黃蓋",
    1007: "完成孫權事件", 1012: "周瑜", 1015: "完成張飛事件", 1019: "孟獲",
}

_XOR_TABLE = bytes([i ^ 0xFF for i in range(256)])
# 脚本命令行: 命令名(参数, 参数, ...) — 行首可有缩进/花括号, 注释行 // 不匹配
_CMD_RE = re.compile(r'^[\s{]*([A-Za-z_]\w*)\(([^)]*)\)')
_COND_CMDS = {'CheckFlag', 'CheckItem', 'CheckTeam', 'CheckResult',
              'CheckMember', 'MiniGame', 'War'}
# 无信息量的 DEFINE 注释 (如 "1 #Define"、"1 #Define end") 不作为事件说明展示
_NOISE_COMMENT_RE = re.compile(r'^\d*\s*#?Define(\s+end)?$', re.IGNORECASE)


def _clean_comment(comment):
    c = (comment or "").strip()
    return "" if not c or _NOISE_COMMENT_RE.match(c) else c


# ═══════════════════════════════════════════════════════════════
# 底层加载 (轻量版, 只取所需字段)
# ═══════════════════════════════════════════════════════════════

def load_tkd_defines(fp):
    """TKD.dat → DEFINE 块列表 (同 mat_text_codec.load_tkd + parse_defines)"""
    with open(fp, 'rb') as f:
        data = f.read()
    decoded = data.translate(_XOR_TABLE)
    try:
        text = decoded.decode('big5', errors='replace')
    except Exception:
        text = decoded.decode('gbk', errors='replace')
    defines = []
    current = None
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('DEFINE') and not stripped.startswith('//'):
            parts = stripped.split(None, 1)
            did = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            current = {'define_id': did, 'comment': '', 'body': []}
        elif stripped.startswith('};') and current is not None:
            current['comment'] = stripped[2:].replace(' end', '').strip()
            defines.append(current)
            current = None
        elif current is not None:
            current['body'].append(line)
    return defines


def load_mat_lite(fp):
    """TKMat.Dat → {实体ID: {'type','scene','flags','x','y','box','ext'}}
    (flags=d2 初始标志 bit0=启用; x/y=d10/d11 坐标(sub_407070);
     box=(d18,d19,d20,d21) 碰撞盒左上角+宽高 (type15 触发区有效范围);
     ext=d52..d64 仅 type110/16)"""
    with open(fp, 'rb') as f:
        raw = f.read()
    entities = {}
    count = min(MAT_REC_COUNT, len(raw) // MAT_REC_SIZE)
    for i in range(count):
        off = i * MAT_REC_SIZE
        d = struct.unpack_from('<22i', raw, off)
        d0, d1, d2 = d[0], d[1], d[2]
        if d0 == 0:
            continue
        ent = {'type': d0, 'scene': d1, 'flags': d2,
               'x': d[10], 'y': d[11],
               'box': (d[18], d[19], d[20], d[21]),
               'ext': None}
        if d0 in (110, 16):
            # d52..d64 (字节偏移 208..256) — type110 物品组 / type16 战斗组
            ent['ext'] = struct.unpack_from('<13i', raw, off + 208)
        entities[i] = ent
    return entities


def load_shops(fp):
    """TKShop.dat → [{'area_id','item_ref','condition'}] (同 shop_editor)"""
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress_dat(raw)
    if len(raw) % 8 == 0 and (len(dec) == 0 or len(dec) % 8 != 0):
        dec = raw
    recs = []
    for i in range(min(240, len(dec) // 8)):
        area_id, item_ref, condition = struct.unpack_from('<hhh', dec, i * 8)
        recs.append({'area_id': area_id, 'item_ref': item_ref,
                     'condition': condition})
    return recs


def load_wardata_lite(fp):
    """WarData.dat → 战斗列表 (名称/地图/敌人编队/战场宝物, 同 wardata_editor)"""
    with open(fp, 'rb') as f:
        raw = f.read()
    recs = []
    for i in range(len(raw) // WAR_REC_SIZE):
        off = i * WAR_REC_SIZE
        recs.append({
            'index': i,
            'name_id': struct.unpack_from('<H', raw, off + 30)[0],
            'map_id': struct.unpack_from('<H', raw, off + 32)[0],
            'enemy_ids': struct.unpack_from('<18H', raw, off + 34),
            'trea_sub': struct.unpack_from('<10H', raw, off + 326),
            'trea_quant': struct.unpack_from('<20H', raw, off + 346),
        })
    return recs


# ═══════════════════════════════════════════════════════════════
# 条件描述
# ═══════════════════════════════════════════════════════════════

def _int(s, default=0):
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return default


def describe_condition(cmd, args, data):
    """Check* 命令 → 人类可读的入队/事件前置条件; 无法解读返回 None"""
    op = CMP_OPS.get(args[2].strip(), args[2].strip()) if len(args) >= 3 else "="
    if cmd == 'CheckFlag' and len(args) >= 2:
        fid = _int(args[0])
        note = FLAG_NOTES.get(fid)
        label = f"剧情旗标#{fid}" + (f"「{note}」" if note else "")
        return f"{label} {op} {args[1].strip()}"
    if cmd == 'CheckItem' and len(args) >= 2:
        iid = _int(args[0])
        if iid == 10000:
            return f"金钱 {op} {args[1].strip()}"
        name = data.item_name_by_id(iid) or f"物品#{iid}"
        return f"持有「{name}」{op} {args[1].strip()}"
    if cmd == 'CheckTeam' and len(args) >= 2:
        cat = _int(args[0])
        if cat == 1:
            name = data.char_name_by_index(_int(args[1]))
            return f"队伍中有「{name}」" if op in ("=", "≥", ">") else f"队伍中没有「{name}」"
        if cat == 5:
            return f"队伍人数 {op} {args[1].strip()}"
        label = CHECKTEAM_CATS.get(cat, f"全局计数器{cat}")
        return f"{label} {op} {args[1].strip()}"
    if cmd == 'CheckResult' and len(args) >= 2:
        return f"对话中选择第 {_int(args[1]) + 1} 个选项"
    if cmd == 'CheckMember' and len(args) >= 4:
        name = data.char_name_by_index(_int(args[0]))
        attr = "等级" if args[1].strip() == '0' else f"属性{args[1].strip()}"
        o = CMP_OPS.get(args[3].strip(), args[3].strip())
        return f"「{name}」{attr} {o} {args[2].strip()}"
    if cmd == 'MiniGame' and args:
        return f"小游戏「{MINIGAME_NAMES.get(args[0].strip(), '类型' + args[0])}」过关"
    if cmd == 'War' and args:
        return f"战斗#{args[0].strip()} 胜利"
    return None


# ═══════════════════════════════════════════════════════════════
# 反向索引构建
# ═══════════════════════════════════════════════════════════════

def build_indexes(data):
    """构建 物品→获得途径 / 角色→入队事件 反向索引。

    写入 data 的属性:
      item_sources: {item_id: [(途径, 描述), ...]}
      char_joins:   {warpc_idx: [{'scene','conds','comment'}, ...]}
      battles:      {battle_id: {'name','map_id','enemy_ids'}}
      battle_scenes:{battle_id: set(场景ID)}  (War命令 + type16 战斗区)
    """
    data.item_sources = defaultdict(list)
    data.char_joins = defaultdict(list)
    data.battles = {}
    data.battle_scenes = defaultdict(set)
    data.special_items = []

    d = data.game_dir
    mat_p = None
    for cand in ("TKMat.Dat", "TKMat.dat", "TKMAT.DAT"):
        fp = os.path.join(d, cand)
        if os.path.exists(fp):
            mat_p = fp
            break
    entities = {}
    if mat_p:
        try:
            entities = load_mat_lite(mat_p)
        except Exception:
            entities = {}
    data.mat_entities = entities   # 全量轻量实体表 (地图页标注用)

    def ent_scene(eid):
        ent = entities.get(eid)
        return ent['scene'] if ent else None

    def scene_text(sid):
        if sid is None:
            return "未知场景"
        if sid == -1:
            return "全局"
        return data.scene_name(sid)

    # ── 1. TKD 脚本扫描: GetItem / TeamMember / BuyMenu / War ──
    buy_scenes = defaultdict(set)   # area_id → {场景ID}
    special_items = []              # Attribute(-1,11,N) 特殊物品收集度来源
    tkd_p = os.path.join(d, "TKD.dat")
    defines = []
    if os.path.exists(tkd_p):
        try:
            defines = load_tkd_defines(tkd_p)
        except Exception:
            defines = []

    for block in defines:
        eid = block['define_id'] >> 16
        scene = ent_scene(eid)
        comment = _clean_comment(block['comment'])
        attr_deltas = []   # Attribute(-1,11,N) 增量收集 (特殊物品收集度)
        script_getitems = []  # 同块 GetItem(物品ID,数量) — 排除金钱10000
        # 花括号嵌套感知的条件栈:
        #   Check*/MiniGame/War 命令后紧跟 "{" 时开启条件作用域, "}" 关闭;
        #   TeamMember 的入队条件 = 当前包住它的所有条件作用域 (旁路分支不计入)
        depth = 0
        cond_stack = []     # [(开启时的depth, 条件描述或None), ...]
        pending_cond = None  # 刚解析到的条件命令, 等待下一个 "{" 绑定

        def _scan_braces(text):
            nonlocal depth, pending_cond
            # ";" / "//" 之后为注释, 花括号计数须截断 (保留 "};" 的 "}")
            for stop in (';', '//'):
                p = text.find(stop)
                if p >= 0:
                    text = text[:p]
            for ch in text:
                if ch == '{':
                    cond_stack.append((depth, pending_cond))
                    pending_cond = None
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    while cond_stack and cond_stack[-1][0] >= depth:
                        cond_stack.pop()

        for line in block['body']:
            m = _CMD_RE.match(line)
            cmd = m.group(1) if m else None
            args = (m.group(2).split(',') if m.group(2).strip() else []) if m else []
            # 命令前的花括号 (如整行 "{"、块首 "{;注释"、行内 "{Cmd(...)")
            _scan_braces(line[:m.start(1)] if m else line)
            if not m:
                continue
            if cmd in _COND_CMDS:
                pending_cond = describe_condition(cmd, args, data)
                if cmd == 'War' and args:
                    bid = _int(args[0], -1)
                    if bid >= 0 and scene is not None:
                        data.battle_scenes[bid].add(scene)
            elif cmd == 'Attribute' and len(args) >= 3:
                # Attribute(目标,属性,变化值): 目标-1 + 属性11 = 特殊物品收集度
                if _int(args[0], 0) == -1 and _int(args[1], 0) == 11:
                    attr_deltas.append(_int(args[2], 0))
            elif cmd == 'GetItem' and len(args) >= 1:
                iid = _int(args[0])
                qty = _int(args[1], 1) if len(args) >= 2 else 1
                if iid != 10000 and qty > 0 and iid in data.item_by_id:
                    script_getitems.append((iid, qty))
                    txt = scene_text(scene)
                    if comment:
                        txt += f" — {comment}"
                    if qty > 1:
                        txt += f" ×{qty}"
                    data.item_sources[iid].append(("剧情事件", txt))
            elif cmd == 'TeamMember' and len(args) >= 2 and args[1].strip() == '1':
                cid = _int(args[0], -1)
                if cid >= 0:
                    # 入队条件 = 花括号作用域包住本命令的全部条件 (由内到外去重)
                    conds = [c for _, c in cond_stack if c]
                    data.char_joins[cid].append({
                        'scene': scene, 'scene_text': scene_text(scene),
                        'conds': conds, 'comment': comment,
                    })
            elif cmd == 'BuyMenu' and len(args) >= 2:
                area = _int(args[1], -1)
                if 0 <= area <= 4 and scene is not None and scene >= 0:
                    buy_scenes[area].add(scene)
            # 命令之后的花括号 (如 "CheckResult(8,0) {" 同行开块写法)
            _scan_braces(line[m.end():])

        # ── 特殊物品收集度来源登记 (Attribute(-1,11,N), 逆向 sub_40E11C case11) ──
        # 物品本体双轨制 (docs/mat_editor/Attribute与GetItem双轨物品系统分析.md):
        #   type110 机关 → TKMat d53-d64 三组物品 (sub_408B30 掉落)
        #   其它实体     → 同块脚本 GetItem 命令 (sub_40CE30)
        # Attribute 本身只累加 word_757F00 收集度, 不入物品栏
        if attr_deltas:
            ent = entities.get(eid)
            etype = ent['type'] if ent else None
            items_found = []
            if ent and etype == 110 and ent['ext'] is not None:
                ext = ent['ext']     # d52..d64
                for base in (1, 5, 9):   # d53/d57/d61 三组物品
                    id_min, id_max, q_min, q_max = ext[base:base + 4]
                    if id_min <= 0:
                        continue
                    if id_max < id_min:
                        id_max = id_min
                    items_found.append((id_min, id_max,
                                        max(q_min, 0), max(q_max, q_min),
                                        'TKMat机关'))
            for iid, qty in script_getitems:
                items_found.append((iid, iid, qty, qty, '脚本GetItem'))
            special_items.append({
                'entity_id': eid,
                'block_no': block['define_id'] & 0xFFFF,
                'type': etype,
                'scene': scene,
                'scene_text': scene_text(scene),
                'comment': comment,
                'delta': sum(attr_deltas),
                'items': items_found,
                # d2 bit0=启用 (未启用实体初始不可交互, 脚本不会触发)
                'enabled': bool(ent['flags'] & 1) if ent else True,
            })
    data.special_items = sorted(
        special_items,
        key=lambda e: (e['scene'] if e['scene'] is not None else 1 << 30,
                       e['entity_id']))

    # ── 2. TKMat type110 宝箱/机关 三组物品; type16 随机战斗区 ──
    for eid, ent in entities.items():
        if ent['ext'] is None:
            continue
        ext = ent['ext']            # d52..d64
        if ent['type'] == 110:
            sname = scene_text(ent['scene'])
            for g, base in enumerate((1, 5, 9)):   # d53/d57/d61 → ext[1]/[5]/[9]
                id_min, id_max, q_min, q_max = ext[base:base + 4]
                if id_min <= 0:
                    continue
                if id_max < id_min:
                    id_max = id_min
                qty_txt = ""
                if q_max > q_min > 0:
                    qty_txt = f" ×{q_min}~{q_max}"
                elif q_min > 1:
                    qty_txt = f" ×{q_min}"
                if id_min == id_max:
                    if id_min in data.item_by_id:
                        data.item_sources[id_min].append(
                            ("地图拾取", f"{sname} — 宝箱/机关{qty_txt}"))
                elif id_max - id_min <= 50:
                    for iid in range(id_min, id_max + 1):
                        if iid in data.item_by_id:
                            data.item_sources[iid].append(
                                ("地图拾取", f"{sname} — 宝箱/机关 (随机其一){qty_txt}"))
        elif ent['type'] == 16:
            # d52/d53/d54 = 三组战斗ID (ext[0]/[1]/[2])
            for bid in ext[0:3]:
                if bid > 0 and ent['scene'] is not None:
                    data.battle_scenes[bid].add(ent['scene'])

    # ── 3. WarData 战斗表 (敌人编队 + 战场宝物) ──
    war_p = os.path.join(d, "WarData.dat")
    war_recs = []
    if os.path.exists(war_p):
        try:
            war_recs = load_wardata_lite(war_p)
        except Exception:
            war_recs = []
    enemy_battles = defaultdict(list)   # WarPC索引 → [battle_id]
    for w in war_recs:
        bid = w['index']
        data.battles[bid] = w
        for en in set(w['enemy_ids']):
            if 0 < en < 60000:
                enemy_battles[en].append(bid)
        for gi in range(10):
            iid = w['trea_sub'][gi]
            if iid > 0 and iid in data.item_by_id:
                q_min, q_max = w['trea_quant'][gi * 2], w['trea_quant'][gi * 2 + 1]
                qty_txt = f" ×{q_min}~{q_max}" if q_max > q_min > 0 else (
                    f" ×{q_min}" if q_min > 1 else "")
                data.item_sources[iid].append(
                    ("战场宝物", f"{data.battle_name(bid)}{qty_txt}"))
    data.enemy_battles = enemy_battles

    # ── 4. 敌人掉落 (WarPC drop 槽 270/271/272, 概率 100/20/5 硬编码) ──
    slot_labels = ["必掉 100%", "高概率 20%", "低概率 5%"]
    for rec in data.warpc_recs:
        f = rec['fields']
        cname = data.char_name(rec)
        if not cname:
            continue
        for slot, fi in enumerate((270, 271, 272)):
            iid = f[fi]
            if iid <= 0 or iid not in data.item_by_id:
                continue
            bids = enemy_battles.get(rec['index'], [])
            where = ""
            if bids:
                names = [data.battle_name(b) for b in bids[:3]]
                where = " — 出现于: " + "、".join(names)
                if len(bids) > 3:
                    where += f" 等{len(bids)}场"
            data.item_sources[iid].append(
                ("敌人掉落", f"{cname} ({slot_labels[slot]}){where}"))

    # ── 5. 商店 (TKShop + BuyMenu 场景锚定) ──
    shop_p = os.path.join(d, "TKShop.dat")
    shops = []
    if os.path.exists(shop_p):
        try:
            shops = load_shops(shop_p)
        except Exception:
            shops = []
    for s in shops:
        area = s['area_id']
        if area not in SHOP_AREA_NAMES:
            continue
        ref = s['item_ref']
        if not (0 <= ref < len(data.item_recs)):
            continue
        iid = data.item_recs[ref]['vals'][0]
        if iid not in data.item_by_id:
            continue
        cond = s['condition']
        if cond == 1:
            cond_txt = "随机上架 (同屏最多5件)"
        elif cond > 1:
            cond_txt = f"幸运门槛 {cond} (概率=最高幸运-{cond})"
        else:
            cond_txt = "始终有售"
        scenes = sorted(buy_scenes.get(area, ()))
        loc = ""
        if scenes:
            names = [data.scene_name(x) for x in scenes[:4]]
            loc = " @ " + "、".join(names)
            if len(scenes) > 4:
                loc += f" 等{len(scenes)}处"
        data.item_sources[iid].append(
            ("商店购买", f"{SHOP_AREA_NAMES[area]}{loc} — {cond_txt}"))

    # 去重 + 排序: 相同途径合并计数, 按途径类型固定顺序展示
    order = {"商店购买": 0, "地图拾取": 1, "剧情事件": 2, "敌人掉落": 3, "战场宝物": 4}
    for iid, srcs in data.item_sources.items():
        counted = {}
        for kv in srcs:
            counted[kv] = counted.get(kv, 0) + 1
        merged = []
        for (kind, desc), n in counted.items():
            merged.append((kind, f"{desc} (×{n}处)" if n > 1 else desc))
        merged.sort(key=lambda kv: order.get(kv[0], 9))
        data.item_sources[iid] = merged
