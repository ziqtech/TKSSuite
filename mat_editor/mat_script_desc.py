# -*- coding: utf-8 -*-
"""mat_editor_v2 脚本命令描述系统 — 命令列表/描述模板与人类可读描述辅助函数。
从 mat_editor_v2.py 原样迁出, 无 UI 逻辑 (§工程化拆分)。"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.lzss import lzss_decompress_dat as lzss_decompress


# 脚本命令完整列表 — 基于 DEFCMD.LST 权威操作码表 + TKD_decoded.txt 实际用法
# DEFCMD.LST 操作码映射 (格式: 操作码=命令名(参数数)):
#   [Normal]
#   0=End(1), 1=TalkB(4), 2=SetTalkB(4), 3=DoTalkB(0), 4=SetNowDef(3),
#   5=SysTalk(6), 6=SetHint(3), 7=MenuTalk(2), 8=SetScene(2), 9=SetWalk(3),
#   10=WaitWalk(2), 11=StopWalk(2), 12=SetEnabled(2), 13=SetVisible(2),
#   14=SetWait(3), 15=Nop(0), 16=SetCursor(3), 17=FadeOut(4), 18=FadeIn(4),
#   19=ChangeScene(4), 20=SetAni(7), 21=SetTick(2), 22=SetShadow(2),
#   23=SetPos(4), 24=Disable(1), 25=Enable(1), 26=Redraw(1), 27=SetPlayer(1),
#   28=SetCamera(1), 29=SetView(2), 30=SlideTo(3), 31=PlayerAct(1),
#   32=SetFlag(2), 33=AddFlag(2), 34=TalkA(5), 35=Switch(2), 36=SetVar(2),
#   37=Random(3), 38=SetFlagVar(2), 39=AddFlagVar(2), 40=GetItem(2),
#   41=BlackTalk(4), 42=SetChaPic(2), 43=SetWeather(2), 44=ShowMenu(2),
#   45=TeamMember(2), 46=Note(2), 47=SetBlock(2), 48=Attribute(3),
#   49=SetSwitch(2), 50=BuyMenu(3), 51=PlaySound(2), 52=StopSound(1),
#   53=PlayMusic(2), 54=SetMusic(2), 55=TheEnd(1), 56=Fix(1)
#   [Special]
#   60=CheckResult(2), 61=CheckFlag(3), 62=CheckItem(3), 63=CheckTeam(3),
#   64=MiniGame(3), 65=CheckMember(4), 66=War(1)
#   [NoArg]
#   82=Else
SCRIPT_COMMANDS = [
    # [Normal] — 按 DEFCMD.LST 操作码顺序排列
    'End', 'TalkB', 'SetTalkB', 'DoTalkB', 'SetNowDef', 'SysTalk', 'SetHint',
    'MenuTalk', 'SetScene', 'SetWalk', 'WaitWalk', 'StopWalk', 'SetEnabled',
    'SetVisible', 'SetWait', 'Nop', 'SetCursor', 'FadeOut', 'FadeIn',
    'ChangeScene', 'SetAni', 'SetTick', 'SetShadow', 'SetPos', 'Disable',
    'Enable', 'Redraw', 'SetPlayer', 'SetCamera', 'SetView', 'SlideTo',
    'PlayerAct', 'SetFlag', 'AddFlag', 'TalkA', 'Switch', 'SetVar', 'Random',
    'SetFlagVar', 'AddFlagVar', 'GetItem', 'BlackTalk', 'SetChaPic',
    'SetWeather', 'ShowMenu', 'TeamMember', 'Note', 'SetBlock', 'Attribute',
    'SetSwitch', 'BuyMenu', 'PlaySound', 'StopSound', 'PlayMusic', 'SetMusic',
    'TheEnd', 'Fix',
    # [Special]
    'CheckResult', 'CheckFlag', 'CheckItem', 'CheckTeam', 'MiniGame',
    'CheckMember', 'War',
    # [NoArg]
    'Else',
    # TKD 文本层额外命令 (非 DEFCMD.LST 标准但实际出现)
    'Yield', 'Jump', 'ShowText', 'MenuChoice', 'SetPosFade', 'SceneFade',
    'SceneBGM', 'Camera', 'WaitInput', 'SetGlobal', 'SetWord', 'WaitTimer',
    'Music',
]

# 脚本命令描述模板 — 用于预览窗口的人类可读描述
# 键为命令名, 值为 lambda, 接收 (args, tkt) 返回描述字符串
# tkt 为 TKT 全文查找表 (id→text)
def _tkt_text(tkt, id_str, max_len=60):
    """从 TKT 获取文本, id_str 为字符串形式的 ID, 返回截断文本或空串"""
    try:
        tid = int(id_str)
        txt = tkt.get(tid, '')
        return txt[:max_len] + ('...' if len(txt) > max_len else '') if txt else ''
    except (ValueError, TypeError):
        return ''

def _tkt_scene(tkt, scene_id_str, max_len=20):
    """从 TKT 获取场景名称, scene_id_str 为字符串形式的场景ID
    场景名称存储在 TKT_ID = scene_id + 300"""
    try:
        sid = int(scene_id_str)
        tkt_id = sid + 300  # SCENE_NAME_TKT_BASE = 300
        txt = tkt.get(tkt_id, '')
        if txt:
            # 只取第一行作为场景名
            name = txt.split('\n')[0].strip()
            return name[:max_len] + ('...' if len(name) > max_len else '') if name else ''
        return ''
    except (ValueError, TypeError):
        return ''

def _item_name(item_names, id_str):
    """从 item_names 获取物品名称, id_str 为字符串形式的物品ID"""
    try:
        if not item_names: return ''
        tid = int(id_str)
        return item_names.get(tid, '')
    except (ValueError, TypeError):
        return ''

def _sign_qty(qty_str):
    """格式化数量: 正数加+号, 负数保持-号"""
    try:
        v = int(qty_str)
        return f"+{v}" if v >= 0 else str(v)
    except ValueError:
        return qty_str

# CheckTeam 角色名缓存 (由 MatEditor._reload 从 WarPC.dat + TKT.dat 动态填充)
_char_name_cache = {}

def _load_char_names(tks_dir, tkt_lookup):
    """从 WarPC.dat 加载角色名映射 index→name.
    类似 warpc_editor 的做法: 读 WarPC 每条记录的 [0] name_id, 查 TKT 得到名称."""
    global _char_name_cache
    wp = os.path.join(tks_dir, 'WarPC.dat')
    if not os.path.exists(wp):
        return
    try:
        with open(wp, 'rb') as f:
            raw = f.read()
        dec = lzss_decompress(raw)
        REC = 1054  # 527 int16
        # 兜底: 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
        if len(raw) % REC == 0 and (len(dec) == 0 or len(dec) % REC != 0):
            dec = raw
        # 加载全部记录: WarPC 原版含 143 个角色(远超旧的 min(50) 上限, 导致 index≥50 显示"角色#N"),
        # 用文件实际记录数, 同时兼容 MOD 扩容后的更大花名册
        cnt = len(dec) // REC
        for i in range(1, cnt):   # 记录#0 是主角, 单独处理; 从 1 开始解析其余角色
            off = i * REC
            name_id = struct.unpack_from('<h', dec, off)[0]
            if name_id > 0 and name_id in tkt_lookup:
                name = tkt_lookup[name_id].split('\n')[0].strip()
                if name:
                    _char_name_cache[i] = name
        # WarPC 记录#0 恒为主角: 其名字为玩家自定义(TKT 中是 NAME 占位符), 统一显示"主角"
        _char_name_cache[0] = "主角"
    except Exception:
        pass

def _dir_name(dir_str, entity=""):
    """朝向值->方向名。entity=0主角(八向), 其他NPC(四向)"""
    _D8 = {1:"上",2:"右上",3:"右",4:"右下",5:"下",6:"左下",7:"左",8:"左上"}
    _D4 = {1:"右上",2:"右上",3:"右下",4:"右下",5:"左下",6:"左下",7:"左上",8:"左上"}
    try:
        v = int(dir_str)
        return _D8.get(v, dir_str) if entity == "0" else _D4.get(v, dir_str)
    except:
        return dir_str

def _cm(char_id):
    """角色ID→名称, fallback 到 '角色#N'"""
    try:
        cid=int(char_id)
        return _char_name_cache.get(cid, f"角色#{cid}")
    except: return f"角色#{char_id}"

# CheckTeam arg1 语义映射 (基于 TKD脚本注释 + save_editor SEG2字段)
# ┌──────┬──────────┬─────────────────────┬──────────────────────────────┐
# │ arg1 │ 属性     │ SEG2地址            │ 证据                         │
# ├──────┼──────────┼─────────────────────┼──────────────────────────────┤
# │  1   │ 角色存在 │ word_75688C[6]      │ TKD: CheckTeam(1,N,0)角色操作│
# │  2   │ 智慧     │ byte_756886         │ TKD注释: "智慧>150"          │
# │  3   │ 仁德     │ byte_756887         │ TKD注释: "仁德>150"          │
# │  4   │ 勇气     │ word_756888         │ TKD注释: "勇氣>150"          │
# │  5   │ 队伍人数 │ word_75688C[6]      │ TKD: -2=有空位 1=已满        │
# │  6   │ 医术     │ word_75688A         │ TKD注释+上限100              │
#     │ 10   │ 事件完成度│ —                   │ 游戏内事件完成百分比       │
# │ 11   │ 特殊物品 │ — (sub_40E11C)      │ TKD注释:"26個特殊物品"       │
# └──────┴──────────┴─────────────────────┴──────────────────────────────┘
_CAT_NAMES = {1:"角色", 2:"智慧", 3:"仁德", 4:"勇气", 5:"队伍人数", 6:"医术", 10:"事件完成度", 11:"特殊物品"}
# CheckTeam arg3 比较运算符 — 逆向验证 (CheckFlag/Item/Team/Member 四者共用同一 switch)
# 源码 sub_40E40C/40E4E4/40E65C/40E88C: case-2:值<a2  case-1:值≤a2  case0:值==a2  case1:值≥a2  case2:值>a2  case3:值≠a2
# ⚠ 旧表把 -1/-2 写反了 (曾 -1="<" -2="≤"), 实为 -1="≤" -2="<"; 并补全 3="≠"
_CMP_OPS = {'0':"==", '1':"≥", '-1':"≤", '-2':"<", '2':">", '3':"≠"}

def _checkteam_desc(args):
    """根据逆向 + TKD.dat 脚本注释生成 CheckTeam 的人类可读描述。
    ┌──────┬──────────┬──────────────────────────────────────┐
    │ arg1 │ 语义     │ 逆向依据                             │
    ├──────┼──────────┼──────────────────────────────────────┤
    │  1   │ 角色存在 │ sub_40E65C case1: 遍历word_75688C[6]队伍槽 │
    │  2   │ 智慧     │ sub_40E65C case2: word_756884        │
    │  3   │ 仁德     │ sub_40E65C case3: word_756886        │
    │  4   │ 勇气     │ sub_40E65C case4: word_756888        │
    │  5   │ 队伍人数 │ sub_40E65C case5: 统计word_75688C非-1 │
    │  6   │ 医术     │ sub_40E65C case6: word_75688A        │
    │ 10   │ 事件完成度│ sub_40E65C case10: word_757EFE      │
    │ 11   │ 特殊物品 │ sub_40E65C case11: word_757F00      │
    └──────┴──────────┴──────────────────────────────────────┘
    arg3(逆向 sub_40E65C 比较开关): 0===  1=≥  -1=≤  -2=<  2=>  3=≠"""
    if not args:
        return "检查队伍"
    cat = args[0] if len(args) >= 1 else '?'
    val = args[1] if len(args) >= 2 else '?'
    op  = args[2] if len(args) >= 3 else '0'

    cat_name = _CAT_NAMES.get(int(cat) if cat.lstrip('-').isdigit() else 0, f"队伍属性{cat}")
    op_str = _CMP_OPS.get(op, op)

    if cat == '1':
        # 角色是否在队伍中: CheckTeam(1, char_id, 0)
        try:
            cid = int(val)
            cname = _char_name_cache.get(cid, f"角色#{cid}")
            return f"判断角色 {cname} 在队中" if op == '0' else f"判断角色 {cname} {op_str} {val}"
        except ValueError:
            return f"判断角色 {op_str} {val}"
    elif cat == '5':
        # 队伍人数检查: CheckTeam(5, max_slots, op)
        try:
            mx = int(val)
            if op == '-2' and mx >= 5:
                return "判断队伍有空位"
            elif op == '1' and mx >= 5:
                return "判断队伍已满"
            elif op == '0':
                return f"判断队伍人数 {op_str} {mx}"
        except ValueError:
            pass
        return f"判断队伍人数 {op_str} {val}"
    elif cat == '10':
        # 事件完成度: CheckTeam(10, percent, op)
        return f"判断事件完成度 {op_str} {val}%"
    else:
        # 属性检查: CheckTeam(attr, threshold, op)
        return f"判断{cat_name} {op_str} {val}"

# Attribute arg2 语义映射 (逆向 sub_40E11C switch(a2))
# arg2: 1=智慧(757F3E) 2=仁德(757F40) 3=勇气(757F42) 4=医术(757F44) 5=体力值恢复(757F12) 6=内力值恢复(757F14) 10=事件完成度(757EFE) 11=特殊物品(757F00)
# ⚠ 旧表漏了 4=医术 (sub_40E11C case4: word_757F44[527*char]+=delta, 增/减显示SysTalk文本5/15)
_ATTR_NAMES = {1:"智慧", 2:"仁德", 3:"勇气", 4:"医术", 5:"体力值恢复", 6:"内力值恢复", 10:"事件完成度", 11:"特殊物品"}

# SetCursor 光标动画名称
# SetCursor arg1→Cur.JVG块 (sub_411BA4→sub_45408C), arg2→帧延迟(dword_8242CC, sub_411D18)
# ┌──────────┬───────┬──────────┬──────────────────────────────┐
# │ cursor_id│ block │ 帧数/尺寸│ 语义                         │
# ├──────────┼───────┼──────────┼──────────────────────────────┤
# │    0     │  blk0 │ 1帧29x40│ 禁止点击                     │
# │    1     │  blk1 │ 1帧28x40│ 正常(脚本默认)               │
# │    2     │  blk2 │ 3帧29x26│ 对话气泡                     │
# │    3     │  blk3 │ 3帧29x43│ 开门(传送)                   │
# │    4     │  blk4 │ 4帧33x47│ 拾取                         │
# │  5-8     │blk5-8 │ 1帧28x40│ 同正常(战斗/备用)            │
# │    9     │  blk9 │ 1帧24x37│ 调查                         │
# │   10     │ blk10 │38帧30x42│ 苍溟(特殊)                   │
# └──────────┴───────┴──────────┴──────────────────────────────┘
_CURSOR_BLOCKS = {0:"禁止", 1:"常规", 2:"对话", 3:"开门", 4:"拾取", 5:"常规", 6:"常规", 7:"常规", 8:"常规", 9:"调查", 10:"苍溟"}

def _setcursor_desc(args):
    """SetCursor(Cur.JVG块, 帧延迟, 开关): arg1=光标精灵块(sub_411BA4→dword_8242C8选Cur.JVG), arg2=帧延迟(dword_8242CC), arg3=显隐开关(_initfmode)。⚠ arg1是光标块非实体"""
    if not args or len(args) < 3:
        return "设置光标"
    blk = args[0]
    spd = args[1]
    en = args[2]
    en_str = "隐藏" if en == '0' else "显示" if en == '1' else f"模式{en}"
    block_name = _CURSOR_BLOCKS.get(int(blk) if blk.lstrip('-').isdigit() else -1, f"块{blk}")
    spd_str = f" 延迟{spd}t" if spd != '3' else ""  # 3=引擎默认, 不显示
    return f"光标[{block_name}] {en_str}{spd_str}"

def _attribute_desc(args):
    """根据逆向 sub_40E11C 生成 Attribute 的人类可读描述。
    Attribute(目标, 属性, 变化值): 目标 -1=全队(a1<0), 0~35=角色索引; arg2 见 _ATTR_NAMES"""
    if not args or len(args) < 3:
        return "属性变更"
    try:
        target = "全队" if args[0] == '-1' else _cm(args[0])
        attr = int(args[1])
        val = int(args[2])
        name = _ATTR_NAMES.get(attr, f"属性{attr}")
        sign = "+" if val >= 0 else ""
        if attr in (5, 6) and val >= 9999:
            return f"{target} {name.replace('恢复','')}完全恢复"
        return f"{target} {name}{sign}{val}"
    except (ValueError, TypeError):
        return f"属性变更 ({','.join(args[:3])})"

def _menu_options(tkt, id_str, max_opts=8):
    """MenuTalk 菜单文本 → 选项列表。选项在 TKT 中以 0x1E(解码为换行)分隔; 剥离 <TAG> 控制标记。
    源码 sub_40B710: 按字节 0x1E 切分文本为若干可点击选项, 选中项 0-based 索引写入 word_755E50[槽]"""
    try:
        txt = tkt.get(int(id_str), '') if tkt else ''
    except (ValueError, TypeError):
        return []
    if not txt:
        return []
    opts = []
    for seg in txt.split('\n'):
        clean = re.sub(r'<[^>]*>', '', seg).strip()
        if clean:
            opts.append(clean)
    return opts[:max_opts]

def _menutalk_desc(a, t):
    """MenuTalk(文本ID, 变量槽): 解析并显示菜单选项。选中项索引存入 word_755E50[变量槽], 供 CheckResult 判断"""
    if not a:
        return "菜单对话"
    if len(a) < 2:
        return f"菜单对话 文本={a[0]}"
    opts = _menu_options(t, a[0])
    if opts:
        return f"菜单[{'/'.join(opts)}]→变量[{a[1]}]"
    return f"菜单对话 文本={a[0]}→变量[{a[1]}]"

SCRIPT_CMD_DESC = {
    # ===== [Normal] 按 DEFCMD.LST 操作码顺序 =====
    # opcode 0: End(1) — 结束脚本, 参数=结束模式
    # 逆向: sub_40EBD4 case 0; 负值→uint16: -1=0xFFFF -2=0xFFFE ...
    # 0xFFFF/1:A链递增 0xFFFE/2:B链递增 0xFFFD/3:C链递增
    # 0xFFFC/4:A链重置 0xFFFB/5:B链重置 0xFFFA/6:C链重置
    'End':          lambda a, t: (
        "结束 (正常返回, 不修改链)" if not a or a[0] == '0' else
        f"结束 → A链递增 (下一DEFINE)" if a[0] in ('1', '-1') else
        f"结束 → B链递增 (下一DEFINE)" if a[0] in ('2', '-2') else
        f"结束 → C链递增 (下一DEFINE)" if a[0] in ('3', '-3') else
        f"结束 → A链重置 (cur_A=0)" if a[0] in ('4', '-4') else
        f"结束 → B链重置 (cur_B=0)" if a[0] in ('5', '-5') else
        f"结束 → C链重置 (cur_C=0)" if a[0] in ('6', '-6') else
        f"结束 (模式={a[0]})"
    ),
    # opcode 1: TalkB(4) — 阻塞式对话: 实体, 文本ID, 立绘/头像帧, 对话框位置
    # 源码 sub_40A220(a6=1) 入队 + sub_40AEF4 立即显示至按键。⚠ 实体仅 type=20/200 有效
    # a3(立绘): >0 选 Talk.JVG 头像; a4(位置): 1=上 2=下, 其他按实体朝向(1-4→下)自动
    'TalkB':        lambda a, t: f"对话(等待) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"对话(等待) 实体#{a[0]}" if a else "对话(等待)",
    # opcode 2: SetTalkB(4) — 入队对话但不立即显示(等 DoTalkB): 实体, 文本ID, 立绘, 位置
    # 源码 sub_40A220(a6=1), 不调 sub_40AEF4。参数同 TalkB, 仅 type=20/200
    'SetTalkB':     lambda a, t: f"设置对话(不等待) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"设置对话 实体#{a[0]}" if a else "设置对话",
    # opcode 3: DoTalkB(0) — 显示所有已入队的 TalkB 对话, 阻塞渲染至按键 (sub_40AEF4)
    'DoTalkB':      lambda a, t: "执行对话显示",
    # opcode 4: SetNowDef(3) — 切换DEFINE链位置: 实体(-1=上下文/-2=自身), 链(1=A/2=B/3=C), 新位置
    # sub_40B520: 修改目标实体的 cur_A/B/C, 实现 DEFINE 链跳转 (相当于 goto 到链中指定位置)
    'SetNowDef':    lambda a, t: (
        "切换当前定义 (无参数)" if not a else
        f"切换定义 ID={a[0]}" if len(a) < 3 else
        f"切换DEFINE → {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} "
        f"{'A链' if a[1]=='1' else 'B链' if a[1]=='2' else 'C链' if a[1]=='3' else '链'+a[1]} "
        f"→位置{a[2]}"
    ),
    # opcode 5: SysTalk(6) — 系统提示消息 (sub_40B1B4 写入队列 + sub_40B2D0 渲染)
    # 参数: 文本ID, 字体/颜色索引, 持续帧数, 闪烁(0=常亮 非0=每4帧闪), 位置(0=底部左 非0=中部右侧堆叠), 追加(0=移入队列 1=追加到同实体)
    # ★ 首参是"文本ID"而非实体! sub_40B1B4(a1): sub_4067E8(a1)取TKT文本; 后续 dword_754710=字体色 754714=持续帧(每帧--归零自动消失) 754718=闪烁 75471C=位置
    # 铁证: GetItem 内 sub_40B1B4(10,26,40,0,1,0)=获得道具提示; Attribute 内 sub_40B1B4(2,21,50,1,0,0)=智慧+提示; ShowMenu 内 sub_40B1B4(8,18,60,1,1,0)
    'SysTalk':      lambda a, t: (
        f"系统提示 文本={a[0]}({_tkt_text(t, a[0], 20)}) {a[2]}帧"
        + (" 闪烁" if len(a) >= 4 and a[3] != '0' else "")
        + (" 追加" if len(a) >= 6 and a[5] != '0' else "")
        if len(a) >= 3 else
        f"系统提示 文本={a[0]}" if a else "系统提示"
    ),
    # opcode 6: SetHint(3) — 设置提示 (sub_40B650)
    # 参数: 实体(-1=上下文 -2=自身), 提示文本ID, 开关(0=关闭提示 >0=开启提示)
    'SetHint':      lambda a, t: (
        f"设置提示 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} 文本={a[1]} {'开启' if a[2]!='0' else '关闭'}"
        if len(a)>=3 else f"设置提示 ({','.join(a)})" if a else "设置提示"
    ),
    # opcode 7: MenuTalk(2) — 菜单选择 (sub_40B710)
    # 参数: 文本ID(选项以0x1E分隔, 解码为换行), 变量槽(选中项0-based索引→word_755E50[槽], 供CheckResult判断)
    # 菜单文本仅含各选项(提问通常由前置 TalkB 给出); 选项可从 TKT 解析显示
    'MenuTalk':     lambda a, t: _menutalk_desc(a, t),
    # opcode 8: SetScene(2) — 设置场景状态 (sub_40BB70)
    # 参数: 实体(-1=上下文 -2=自身), 场景ID
    'SetScene':     lambda a, t: (
        f"设置场景 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} →场景{a[1]}{('('+_tkt_scene(t,a[1])+')') if _tkt_scene(t,a[1]) else ''}"
        if len(a)>=2 else f"设置场景 ({','.join(a)})" if a else "设置场景"
    ),
    # opcode 9: SetWalk(3) — 设置行走 (sub_40BC10)
    # 参数: 实体(-1=上下文 -2=自身), 目标X, 目标Y (仅type=200有效)
    'SetWalk':      lambda a, t: (
        f"行走 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}→({a[1]},{a[2]})"
        if len(a)>=3 else f"行走 ({','.join(a)})" if a else "行走"
    ),
    # opcode 10: WaitWalk(2) — 等待行走完成 (sub_40BCC0)
    # 参数: 实体(-1=上下文 -2=自身), 模式(0=异步 1=同步阻塞)
    # 同步模式下脚本暂停直到行走完成; 异步模式检查flags bit4判断是否在行走
    'WaitWalk':     lambda a, t: (
        f"等待行走 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} {'同步' if len(a)>=2 and a[1]!='0' else '异步'}"
        if a else "等待行走"
    ),
    # opcode 11: StopWalk(2) — 停止行走 (sub_40BD84)
    # 参数: 实体(-1=上下文 -2=自身), 方向(1-8, 0=清除方向重置动画)
    'StopWalk':     lambda a, t: (
        f"停止行走 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} 方向={a[1] if len(a)>=2 and a[1]!='0' else '重置'}"
        if a else "停止行走"
    ),
    # opcode 12: SetEnabled(2) — 启用/禁用实体 (sub_40BE30)
    # 参数: 实体(-1=上下文 -2=自身), 标志(0=禁用flags bit0清零, 1=启用flags bit0置位)
    'SetEnabled':   lambda a, t: (
        f"{'启用' if len(a)>=2 and a[1]!='0' else '禁用'} {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}"
        if a else "启用/禁用"
    ),
    # opcode 13: SetVisible(2) — 设置实体可见性, 修改 flags bit1
    # 逆向: sub_40CB?? — arg1=实体(-1=上下文 -2=自身) arg2=0隐藏/1显示
    'SetVisible':   lambda a, t: (
        f"显示 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}" if len(a)>=2 and a[1]=='1' else
        f"隐藏 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}" if len(a)>=2 and a[1]=='0' else
        f"设置可见性 实体#{a[0]} 标志={a[1]}" if len(a)>=2 else
        "设置可见性"
    ),
    # opcode 14: SetWait(3) — 设置等待/延时 (sub_40BF88)
    # 参数: 实体(-1=上下文 -2=自身), 最小tick, 最大tick
    # 实体param字段 = random(min, max), 用于随机延时触发
    'SetWait':      lambda a, t: (
        f"设置等待 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} [{a[1]},{a[2]}]tick"
        if len(a)>=3 else f"设置等待 ({','.join(a)})" if a else "设置等待"
    ),
    # opcode 15: Nop(0) — 空操作
    'Nop':          lambda a, t: f"空操作 (填充={a[0]})" if a else "空操作",
    # opcode 16: SetCursor(3) — 设置鼠标光标 (sub_411BA4: dword_8242C8=光标块, dword_8242CC=帧延迟)
    # 参数: (Cur.JVG块, 帧延迟, 显隐开关)  块:0=禁止 1=常规 2=对话 3=开门(传送) 4=拾取 9=调查 10=苍溟  开关:0=隐藏 1=显示
    # ⚠ 首参是光标块(非实体); 帧延迟=3为引擎默认
    'SetCursor':    lambda a, t: _setcursor_desc(a),
    # opcode 17: FadeOut(4) — 淡出至纯色 (sub_409830(0,34,3,delay,R,G,B): 遮罩0→34)
    # 参数: R, G, B, 每步延迟(ms) — ⚠ 越大越慢! 源码 while(GetTickCount-t<a4)忙等a4毫秒/步; 非"速度"
    'FadeOut':      lambda a, t: f"淡出 RGB({a[0]},{a[1]},{a[2]}) 延迟{a[3]}ms/步" if len(a)>=4 else "淡出",
    # opcode 18: FadeIn(4) — 从纯色淡入 (sub_409830(34,0,-3,delay,R,G,B): 遮罩34→0)
    # 参数: R, G, B, 每步延迟(ms) — 越大越慢 (同FadeOut)
    'FadeIn':       lambda a, t: f"淡入 RGB({a[0]},{a[1]},{a[2]}) 延迟{a[3]}ms/步" if len(a)>=4 else "淡入",
    # opcode 19: ChangeScene(4) — 切换场景 (sub_40C044)
    # 参数: 场景ID, 玩家X, 玩家Y, 朝向(1-8)
    # 加载新场景文件, 设置玩家位置和朝向, 重置天气/对话等状态
    # 场景名称通过 TKT_ID = scene_id + 300 获取
    'ChangeScene':  lambda a, t: (
        f"切换场景→#{a[0]} {_tkt_scene(t, a[0])} ({a[1]},{a[2]})朝向{a[3]}"
        if len(a)>=4 else
        f"切换场景→#{a[0]} {_tkt_scene(t, a[0])}" if a else "切换场景"
    ),
    # opcode 20: SetAni(7) — 设置Ani.JVG动画 (sub_40C1A4)。仅 type=20/200 有效; 无条件置 anim_set(d9)=4
    # 参数: 实体(-1=上下文 -2=自身), Ani.JVG块, 帧起点(-1=不变), 帧终点(-1=不变),
    #        当前帧(-1=不变), 保留末帧(-1=不变), 循环(0=关 1=开 -1=不变)
    # ★ 第6参是"保留末帧"(写 d69, 非零则播完停末帧不循环)——非"动画速度"! 速度由 SetTick(d4) 控制
    # 源码 sub_40C1A4: a2(块)>0 且≠d64 时换块并整体复位 → d64=块 d65=句柄 d16=帧数 d67=0 d68=帧数-1 d17=0
    #   a3≥0→d67(帧起点) a4≥0→d68(帧终点/最大帧) a5≥0→d17(当前帧,重播关键) a6≥0→d69(保留末帧) a7≥0→flags bit16(动画循环)
    #   末尾 d14 = d17 + d65 重算渲染帧。⚠ 不复位等待计时 d3, 冻结的一次性动画需另配 SetWait
    'SetAni':       lambda a, t: (
        "设置动画 " + ('自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0])
        + (f" 块{a[1]}" if len(a)>=2 and a[1] not in ('-1','0') else "")
        + (f" 起{a[2]}" if len(a)>=3 and a[2]!='-1' else "")
        + (f" 止{a[3]}" if len(a)>=4 and a[3]!='-1' else "")
        + (f" 当前{a[4]}" if len(a)>=5 and a[4]!='-1' else "")
        + (" 保留末帧" if len(a)>=6 and a[5] not in ('-1','0') else "")
        + (" 循环" if len(a)>=7 and a[6]=='1' else " 单次" if len(a)>=7 and a[6]=='0' else "")
        if a else "设置动画"
    ),
    # opcode 21: SetTick(2) — 设置Tick周期 (sub_40C388)
    # 参数: 实体(-1=上下文 -2=自身), tick周期值
    # 修改实体的tick字段(dword[4]), 控制自动脚本执行频率
    'SetTick':      lambda a, t: (
        f"设置Tick {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}={a[1]}帧"
        if len(a)>=2 else f"设置Tick ({','.join(a)})" if a else "设置Tick"
    ),
    # opcode 22: SetShadow(2) — 设置阴影 (sub_40C428)
    # 参数: 实体(-1=上下文 -2=自身), 阴影帧(0=无 1=小 2=大)
    # 仅type=20/200有效, 修改shadow_frame字段(dword[55])
    'SetShadow':    lambda a, t: (
        f"设置阴影 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}={'无' if a[1]=='0' else '小' if a[1]=='1' else '大' if a[1]=='2' else a[1]}"
        if len(a)>=2 else f"设置阴影 ({','.join(a)})" if a else "设置阴影"
    ),
    # opcode 23: SetPos(4) — 设置位置: 实体, X, Y, 朝向
    'SetPos':       lambda a, t: (
        f"设置位置 实体#{a[0]}→({a[1]},{a[2]})朝向{a[3]}({_dir_name(a[3],a[0])})" if len(a)>=4 else
        f"设置位置 实体#{a[0]}" if a else "设置位置"),
    # opcode 24: Disable(1) — 禁用实体 (sub_40C5A4)
    # 参数: 实体(-1=上下文 -2=自身)
    # 同时清除flags bit0(启用)和bit1(可见), 实体完全不可见不可交互
    'Disable':      lambda a, t: (
        f"禁用 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}"
        if a else "禁用"
    ),
    # opcode 25: Enable(1) — 启用实体 (sub_40C648)
    # 参数: 实体(-1=上下文 -2=自身)
    # 同时设置flags bit0(启用)和bit1(可见), 与Disable相反
    'Enable':       lambda a, t: (
        f"启用 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}"
        if a else "启用"
    ),
    # opcode 26: Redraw(1) — 重绘画面 (sub_40C6EC)
    # 参数: 帧数(持续渲染N帧)
    # 强制执行完整的渲染循环N帧, 包含天气/对话框/光标等所有UI元素
    'Redraw':       lambda a, t: f"重绘 {a[0]}帧" if a else "重绘画面",
    # opcode 27: SetPlayer(1) — 设置玩家角色 (sub_40C7CC)
    # 参数: 实体ID(必须是type=200)
    # 设置当前操控的玩家角色, 修改dword_755B5C和dword_8242E0
    'SetPlayer':    lambda a, t: f"设置玩家→实体#{a[0]}" if a else "设置玩家",
    # opcode 28: SetCamera(1) — 设置镜头跟随目标 (sub_40C854)
    # 参数: 实体(-1=禁用镜头跟随, 其他=跟随该实体)
    # 修改dword_8242E4, 镜头会跟随目标实体移动
    'SetCamera':    lambda a, t: (
        f"镜头→{'禁用' if a[0]=='-1' else '实体#'+a[0]}"
        if a else "设置镜头"
    ),
    # opcode 29: SetView(2) — 设置视角 (sub_40C8E0)
    # 参数: X, Y (世界坐标)
    # 直接设置镜头视口位置, 与SetCamera不同的是不跟随实体
    'SetView':      lambda a, t: f"视角→({a[0]},{a[1]})" if len(a)>=2 else f"设置视角" if a else "设置视角",
    # opcode 30: SlideTo(3) — 平滑移动镜头 (sub_40C9E8)
    # 参数: 目标X, 目标Y, 帧数(移动持续时间)
    # 镜头从当前位置平滑移动到目标位置, 每帧更新
    'SlideTo':      lambda a, t: f"镜头滑动→({a[0]},{a[1]}) {a[2]}帧" if len(a)>=3 else "镜头滑动",
    # opcode 31: PlayerAct(1) — 玩家操作
    # TKD用法: PlayerAct(0)=锁定(脚本开头) PlayerAct(1)=恢复(脚本结尾)
    'PlayerAct':   lambda a, t: (
        "锁定玩家操作" if a and a[0] == '0' else
        "恢复玩家操作" if a and a[0] == '1' else
        f"玩家操作 模式={a[0]}" if a else "玩家操作"),
    # opcode 32: SetFlag(2) — 设置标志 (sub_40CB08→word_756080[1024])
    # 存储位置: 存档 Frame2 SEG1 +0x568, 1024个int16, 随存档持久化
    'SetFlag':      lambda a, t: f"设置标志 #{a[0]}={a[1]}" if len(a)>=2 else f"设置标志 #{a[0]}" if a else "设置标志",
    # opcode 33: AddFlag(2) — 增加标志 (sub_40CB4C→word_756080[flag_id]+=value)
    'AddFlag':      lambda a, t: f"增加标志 #{a[0]}+{a[1]}" if len(a)>=2 else f"增加标志 #{a[0]}" if a else "增加标志",
    # opcode 34: TalkA(5) — 非阻塞浮动对话: 实体, 文本ID, 立绘/头像帧, 对话框位置, 持续帧数
    # 源码 sub_40A220(a6=0) 入队(不阻塞), 由主循环 sub_40A518 渲染; a5=持续帧数(到期消失), 常配 SetWait(-2,a5,a5)。仅 type=20/200
    'TalkA':        lambda a, t: (
        f"对话(即时) 实体#{a[0]} 文本={a[1]}({_tkt_text(t, a[1])}) {a[4]}帧" if len(a)>=5 else
        f"对话(即时) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else
        f"对话(即时) 实体#{a[0]}" if a else "对话(即时)"),
    # opcode 35: Switch(2) — NPC状态切换 (sub_40CB90)
    # 参数: 实体(-1=上下文 -2=自身), 模式(0=常规/站桩 1=动画/行走)
    # 仅type=200有效; arg2=0: anim_set→1(Cha.JVG)+移动模式→0(静止)
    # arg2=1: anim_set→4(Ani.JVG)+移动模式→1(行走)
    # TKD中成对使用: Switch(N,0)在对话/菜单前 → Switch(N,1)在结束后
    'Switch':       lambda a, t: (
        f"切换NPC·{'常规' if a[1]=='0' else '动画'} {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else 'NPC#'+a[0]}"
        if len(a)>=2 else "NPC状态切换"
    ),
    # opcode 36: SetVar(2) — 设置脚本变量 (case 36)
    # 参数: 变量槽(0-249), 值
    # 变量存储在word_755E80[256], 超出范围会报错
    'SetVar':       lambda a, t: f"变量[{a[0]}]={a[1]}" if len(a)>=2 else f"变量[{a[0]}]" if a else "设置变量",
    # opcode 37: Random(3) — 随机数 (case 37)
    # 参数: 变量槽, 最小值, 最大值
    # 生成[min, max]范围的随机数存入变量槽; max必须>min否则报错
    'Random':       lambda a, t: f"随机→变量[{a[0]}] [{a[1]},{a[2]}]" if len(a)>=3 else "随机",
    # opcode 38: SetFlagVar(2) — 设置标志变量
    'SetFlagVar':   lambda a, t: f"标志变量 标志={a[0]},变量槽={a[1]}" if len(a)>=2 else f"标志变量 标志={a[0]}" if a else "设置标志变量",
    # opcode 39: AddFlagVar(2) — 增加标志变量
    'AddFlagVar':   lambda a, t: f"增加标志变量 标志={a[0]},变量槽={a[1]}" if len(a)>=2 else f"增加标志变量 标志={a[0]}" if a else "增加标志变量",
    # opcode 40: GetItem(2) — 道具/金钱增减 (sub_40CE30)
    # 参数: 道具ID(10000=金钱), 数量(正=获得 负=移除)
    # 道具数量上限99, 金钱上限30000; 获得时显示SysTalk提示
    'GetItem':      lambda a, t, i=None: (
        f"金钱 {_sign_qty(a[1])}" if a and len(a)>=2 and a[0]=='10000' else
        f"道具 {a[0]}({_item_name(i, a[0])}) {_sign_qty(a[1])}" if a and len(a)>=2 and i else
        f"道具 {a[0]}({_item_name(i, a[0])})" if a and i else
        f"道具 ID={a[0]}" if a else "道具增减"
    ),
    # opcode 41: BlackTalk(4) — 黑屏对话/旁白
    # 逆向: sub_40B05C(text_id, x, y, color)→sub_4067E8加载TKT+sub_44B028设颜色, 循环渲染至按键
    'BlackTalk':    lambda a, t: (
        f"黑屏对话 文本={a[0]} ({a[1]},{a[2]}) 色{a[3]} — {_tkt_text(t, a[0])}" if len(a)>=4 else
        f"黑屏对话 文本={a[0]} — {_tkt_text(t, a[0])}" if a else "黑屏对话"),
    # opcode 42: SetChaPic(2) — 设置角色立绘 (sub_40D0CC)
    # 参数: 实体(-1=上下文 -2=自身), Cha.JVG块ID
    # 仅type=200有效; 修改立绘ID(dword[51])和相关动画参数
    'SetChaPic':    lambda a, t: (
        f"设置立绘 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]}→块{a[1]}"
        if len(a)>=2 else f"设置立绘 ({','.join(a)})" if a else "设置立绘"
    ),
    # opcode 43: SetWeather(2) — 设置天气效果 (sub_40D2A0)
    # 参数: 天气类型(1=雨), 开关 — ⚠ 是"开关"(arg2)决定关闭, 非arg1!
    # 源码 sub_40D2A0: if(arg2==0)清除粒子sub_405B98; else if(arg1==1)下雨sub_405BE0(1,5,400,10,5)
    'SetWeather':   lambda a, t: (
        "天气→关闭" if len(a)>=2 and a[1]=='0' else
        "天气→下雨" if a and a[0]=='1' else
        f"天气→类型{a[0]}" if a else "设置天气"
    ),
    # opcode 44: ShowMenu(2) — 显示菜单 (sub_40D2D0, 仅取用 arg1)
    # arg1=0: 姓名输入界面(MBName.gxp), 结果写入玩家名 byte_755B6C/755B64 — 证据: TKD "ShowMenu(0,0)//玩家輸入名字"
    # arg1=1: 传送/世界地图菜单(MB.gxp), 选中项经 sub_40C044 传送到预设场景(12/19/26/2); 身处场景内(dword_755B58≠0)时 SysTalk(8) 提示无法使用
    'ShowMenu':     lambda a, t: (
        "姓名输入" if a and a[0] == '0' else
        "传送菜单(世界地图)" if a and a[0] == '1' else
        f"显示菜单 类型={a[0]}" if a else "显示菜单"
    ),
    # opcode 45: TeamMember(2) — 队伍成员增减 (sub_40DA00, a2=1加入/0离开, a1=0清空全队)
    'TeamMember':   lambda a, t: (
        f"角色 {_cm(a[0])} 加入队伍" if len(a)>=2 and a[1]=='1' else
        f"角色 {_cm(a[0])} 离开队伍" if len(a)>=2 and a[1]=='0' else
        "清空全队" if a and a[0]=='0' else "队伍成员"),
    # opcode 46: Note(2) — 注释/标记 (sub_40DBF4)
    # 参数: 标记槽(0-999), 值
    # 存储在word_7568D8[1000], 用于脚本状态标记, 不影响游戏逻辑
    'Note':         lambda a, t: f"标记[{a[0]}]={a[1]}" if len(a)>=2 else f"标记 ({','.join(a)})" if a else "注释",
    # opcode 47: SetBlock(2) — 路径封锁开关 (仅type=10传送点使用)
    # sub_40DC1C: v3[62]=a2; >0封锁(路径网格清零)sub_4526D0(...,0,...); 0开放sub_4526D0(...,*(BYTE*)(a2+252),...)
    # 同时 sub_4081F8 检查 d62 阻止传送
    'SetBlock':     lambda a, t: (
        f"解锁传送点#{a[0]}" if len(a)>=2 and a[1]=="0" else
        f"封锁传送点#{a[0]}" if len(a)>=2 and a[1]!="0" else
        f"传送点路径封锁#{a[0]}" if a else "传送点路径封锁"),
    # 来源: TKD_decoded.txt 664处用法 + 脚本注释
    # arg2: 1=智慧 2=仁德 3=勇气 5=体力值恢复 6=内力值恢复 10=事件完成度 11=特殊物品
    # arg3: 正=增加 负=减少
    'Attribute':   lambda a, t: _attribute_desc(a),
    # opcode 49: SetSwitch(2) — 设置全局运行时开关 (case 49)
    # 参数: 开关槽(0-31), 值
    # 存储在word_755E10[32], 仅运行时有效不存档; 用于UI流程/事件控制
    # 与SetFlag(存档持久)不同: SetSwitch是临时状态
    'SetSwitch':    lambda a, t: f"开关[{a[0]}]={a[1]}" if len(a)>=2 else f"开关[{a[0]}]" if a else "设置开关",
    # opcode 50: BuyMenu(3) — 商店 (sub_40D804 → sub_4233C4(state, arg1, arg2, arg3))
    # ★ 商店分类是 arg2, 不是 arg3! sub_4233C4 switch(a1[28]=arg2) 选物品页(tab_code)过滤(v7/v6):
    #   0=药品(页0) 1=道具(页1) 2=武器+防具(页2,3) 3=药品+道具(页0,1) 4=饰品(页4)  [页名同 item_editor PAGE_NAMES]
    # arg1 存 a1[arg2+13]=商店编号(同编号10分钟内重进保持货物, 否则 sub_4244CC 重生成库存)
    # arg3 存 a1[29] (实测 0 或 22, 疑为价格/折扣等附加标志, 由后续商店逻辑读取)
    'BuyMenu':      lambda a, t: (
        f"商店#{a[0]} 分类={'药品' if a[1]=='0' else '道具' if a[1]=='1' else '武器+防具' if a[1]=='2' else '药品+道具' if a[1]=='3' else '饰品' if a[1]=='4' else a[1]}"
        + (f" 参数{a[2]}" if len(a)>=3 and a[2] not in ('0', '') else "")
        if len(a)>=2 else f"商店菜单 ({','.join(a)})" if a else "商店菜单"
    ),
    # opcode 51: PlaySound(2) — 播放音效 (sub_451780 + sub_451C38)
    # 参数: 音效ID, 循环(0=不循环 1=循环)
    # 音效文件: sound\%04d.wav; 使用DirectSound播放
    'PlaySound':    lambda a, t: (
        f"播放音效 {a[0]} {'循环' if len(a)>=2 and a[1]!='0' else '单次'}"
        if a else "播放音效"
    ),
    # opcode 52: StopSound(1) — 停止指定音效 (sub_451D2C(&unk_A2C1D0, arg1))
    # 参数: 音效ID — 停止该编号音效的播放 (arg1 作为音效缓冲区索引, 越界/负值则忽略)。非"无参数"
    'StopSound':    lambda a, t: f"停止音效 {a[0]}" if a else "停止音效",
    # opcode 53: PlayMusic(2) — 播放音乐 (sub_44AC50 加载 sound\%04d.mp3 + sub_44AC90 播放, DirectShow)
    # 参数: 音乐ID(<0=停止当前音乐 sub_44ACE8), 循环(0=不循环 1=循环)
    # 源码 case53: 循环!=0 时还会把该曲登记为当前场景BGM byte_755B74[dword_755B58]
    'PlayMusic':    lambda a, t: (
        "停止音乐" if a and a[0].startswith('-') else
        f"播放音乐 {a[0]} {'循环' if len(a)>=2 and a[1]!='0' else '单次'}"
        if a else "播放音乐"
    ),
    # opcode 54: SetMusic(2) — 设置场景BGM映射 (case 54)
    # 参数: 场景ID(0-255), 音乐ID(-1=停止当前)
    # 存储在byte_755B74[256], 切换场景时自动播放对应BGM
    # 如果设置的是当前场景的BGM且值<0, 则停止当前音乐
    'SetMusic':     lambda a, t: (
        f"场景BGM 场景{a[0]}{('('+_tkt_scene(t,a[0])+')') if _tkt_scene(t,a[0]) else ''}→{'停止' if a[1]=='-1' else '音乐'+a[1]}"
        if len(a)>=2 else f"场景BGM ({','.join(a)})" if a else "场景BGM"
    ),
    # opcode 55: TheEnd(1) — 游戏结局 (case 55)
    # 参数: 结局ID(0-99)
    # 设置word_951940 = 结局ID + 100, 然后返回-1终止脚本执行
    # 触发游戏结局画面
    'TheEnd':       lambda a, t: f"游戏结局 #{a[0]}" if a else "游戏结局",
    # opcode 56: Fix(1) — 修正/空操作 (case 56)
    # 参数: 保留
    # 仅word_755AB2 += 2, 不执行任何操作; 可能用于版本兼容或调试
    'Fix':          lambda a, t: f"修正(保留={a[0]})" if a else "修正",
    # ===== [Special] 条件跳转类 =====
    # opcode 60: CheckResult(2) — 检查变量结果跳转 (case 60)
    # 参数: 变量槽, 期望值, 跳转偏移(隐含在字节码中)
    # 如果word_755E50[变量槽] == 期望值, 继续执行; 否则跳转
    # word_755E50存储上次比较操作的结果
    'CheckResult':  lambda a, t: f"检查结果 变量[{a[0]}]=={a[1]}?" if len(a)>=2 else "检查结果",
    # opcode 61: CheckFlag(3) — 检查标志条件跳转 (sub_40E40C)
    # 参数: 标志ID(0-1023), 期望值, 操作符(0=== 1=>= -1=<= -2=< 2=> 3=!=)
    # 比较word_756080[标志ID]与期望值, 结果存入dword_755AA0
    # 字节码中隐含跳转偏移: 如果比较失败则跳转
    'CheckFlag':    lambda a, t: (
        f"检查标志 #{a[0]} {_CMP_OPS.get(a[2], a[2])} {a[1]}?"
        if len(a)>=3 else f"检查标志 #{a[0]}" if a else "检查标志"
    ),
    # opcode 62: CheckItem(3) — 检查道具条件跳转 (sub_40E4E4)
    # 参数: 道具ID(10000=金钱), 期望数量, 操作符(0=== 1=>= -1=<= -2=< 2=> 3=!=)
    # 统计背包+队伍装备中的道具总数, 与期望值比较
    # 结果存入dword_755AA0, 字节码中隐含跳转偏移
    'CheckItem':    lambda a, t, i=None: (
        f"检查金钱 {_CMP_OPS.get(a[2], a[2])} {a[1]}?" if len(a)>=3 and a[0]=='10000' else
        f"检查道具 {a[0]}{('('+_item_name(i,a[0])+')') if _item_name(i,a[0]) else ''} {_CMP_OPS.get(a[2], a[2])} {a[1]}?" if len(a)>=3 else
        f"检查道具 {a[0]}" if a else "检查道具"
    ),
    # opcode 63: CheckTeam(3) — 检查队伍条件跳转
    'CheckTeam':    lambda a, t, i=None: _checkteam_desc(a),
    # opcode 64: MiniGame(3) — 小游戏 (sub_40E97C(type, threshold, mode, &result))
    # 参数: 游戏类型(1-7), 通关分阈值, 比较模式(1=分数≥阈值判胜, 其他=分数<阈值判胜); 失败跳转偏移隐含于字节码
    # 游戏类型(名称依原注, C层未逐一验证): 1=华容道 2=八阵图 3=骰子 4=串珠 5=四四同数 6=拼图 7=龙蛇百变
    # 返回dword_755AA0: 1=成功(继续) 0=失败(跳转)
    'MiniGame':     lambda a, t: (
        f"小游戏 {'华容道' if a[0]=='1' else '八阵图' if a[0]=='2' else '骰子' if a[0]=='3' else '串珠' if a[0]=='4' else '四四同数' if a[0]=='5' else '拼图' if a[0]=='6' else '龙蛇百变' if a[0]=='7' else '类型'+a[0]}"
        if a else "小游戏"
    ),
    # opcode 65: CheckMember(4) — 检查队伍成员属性 (sub_40E88C)
    # 参数: 角色ID, 属性类型(0=等级), 期望值, 操作符(0=== 1=>= -1=<= -2=< 2=> 3=!=)
    # 检查指定角色的属性值, 结果存入dword_755AA0
    # 字节码中隐含跳转偏移: 如果比较失败则跳转
    'CheckMember':  lambda a, t: (
        f"检查成员 {_cm(a[0])} {'等级' if a[1]=='0' else '属性'+a[1]} {_CMP_OPS.get(a[3], a[3])} {a[2]}?"
        if len(a)>=4 else f"检查成员 {_cm(a[0])}" if a else "检查成员"
    ),
    # opcode 66: War(1) — 战斗 (sub_40EB10)
    # 参数: 战斗ID
    # 触发战斗, 播放战斗BGM, 切换到战斗场景
    # 返回dword_755AA0: 1=胜利 0=失败; 字节码中隐含跳转偏移
    'War':          lambda a, t: f"战斗 #{a[0]}" if a else "战斗",
    # ===== [NoArg] =====
    # opcode 82: Else — 条件分支的否则 (case 82)
    # 参数: 跳转偏移(隐含在字节码中)
    # 如果dword_755AAC <= 0(上次条件为真), 跳转到指定偏移; 否则继续执行
    # 用于实现if-else结构
    'Else':         lambda a, t: "否则 (条件分支)",
    # ===== TKD 文本层额外命令 (非 DEFCMD.LST 标准，但在脚本中实际出现或用于兼容) =====
    'Yield':        lambda a, t: "让出控制权 (暂停当前帧)",
    'Jump':         lambda a, t: f"跳转到偏移={a[0]}" if a else "跳转",
    'ShowText':     lambda a, t: f"显示文本 ID={a[0]} — {_tkt_text(t, a[0])}" if a else "显示文本",
    'MenuChoice':   lambda a, t: f"菜单选择 实体#{a[0]}" if a else "菜单选择",
    'SetPosFade':   lambda a, t: f"淡入位置 实体#{a[0]}→({a[1]},{a[2]})" if len(a)>=3 else "淡入位置",
    'SceneFade':    lambda a, t: f"场景过渡→#{a[0]}" if a else "场景过渡",
    'SceneBGM':     lambda a, t: f"场景BGM 场景#{a[0]}" if a else "场景BGM",
    'Camera':       lambda a, t: f"镜头控制 ({a[0]},{a[1]},{a[2]})" if len(a)>=3 else "镜头控制",
    'WaitInput':    lambda a, t: "等待玩家输入 (按键继续)",
    'SetGlobal':    lambda a, t: f"设置全局变量={a[0]}" if a else "设置全局变量",
    'SetWord':      lambda a, t: f"设置字={a[0]}" if a else "设置字",
    'WaitTimer':    lambda a, t: f"定时等待 {a[0]}×{a[1]}ms" if len(a)>=2 else "定时等待",
    'Music':        lambda a, t: f"播放音乐 ID={a[0]}" if a else "播放音乐",
}

# ============================================================
# 逐参数说明 (脚本预览详情面板"参数"栏) — cmd → [(参数名, 解释器), ...]
# 解释器: None=仅显示值; dict=枚举{值:含义}; callable=自定义(值→说明);
#         'entity'/'char'/'scene'/'text'/'item'/'cmp'/'menu'=特殊解析器
# ============================================================
_DIR8 = {'1':'↑上', '2':'↗右上', '3':'→右', '4':'↘右下', '5':'↓下', '6':'↙左下', '7':'←左', '8':'↖左上'}
_UNCHG = {'-1':'不变'}          # 帧参数 -1=不变
_KEEP_BLK = {'0':'保持当前块', '-1':'保持当前块'}

def _p_onoff(off, on):
    """工厂: 生成 值=='0'→off, 否则→on 的解释器"""
    return lambda v: off if v == '0' else on

SCRIPT_CMD_PARAMS = {
    'End':        [('结束模式', {'0':'正常返回(不改链)', '1':'A链递增','-1':'A链递增', '2':'B链递增','-2':'B链递增', '3':'C链递增','-3':'C链递增', '4':'A链重置','-4':'A链重置', '5':'B链重置','-5':'B链重置', '6':'C链重置','-6':'C链重置'})],
    'TalkB':      [('实体','entity'), ('文本ID','text'), ('立绘/头像帧', _p_onoff('无立绘','有立绘')), ('对话框位置', {'1':'上','2':'下','-1':'按朝向自动'})],
    'SetTalkB':   [('实体','entity'), ('文本ID','text'), ('立绘/头像帧', _p_onoff('无立绘','有立绘')), ('对话框位置', {'1':'上','2':'下','-1':'按朝向自动'})],
    'DoTalkB':    [],
    'SetNowDef':  [('实体','entity'), ('链', {'1':'A链','2':'B链','3':'C链'}), ('新位置(1-based)', None)],
    'SysTalk':    [('文本ID','text'), ('字体/颜色索引', None), ('持续帧数', None), ('闪烁', _p_onoff('常亮','每4帧闪')), ('位置', {'0':'底部左','1':'中部右堆叠'}), ('追加', _p_onoff('移入队列','追加到同实体'))],
    'SetHint':    [('实体','entity'), ('提示文本ID','text'), ('开关', _p_onoff('关闭提示','开启提示'))],
    'MenuTalk':   [('文本ID(选项)','menu'), ('变量槽(存选中索引)', None)],
    'SetScene':   [('实体','entity'), ('场景ID','scene')],
    'SetWalk':    [('实体(仅type200)','entity'), ('目标X', None), ('目标Y', None)],
    'WaitWalk':   [('实体(仅type200)','entity'), ('模式', _p_onoff('异步(检测忙碌位)','同步(阻塞至完成)'))],
    'StopWalk':   [('实体(仅type200)','entity'), ('方向', dict(_DIR8, **{'0':'重置动画'}))],
    'SetEnabled': [('实体','entity'), ('标志', _p_onoff('禁用(清bit0)','启用(置bit0)'))],
    'SetVisible': [('实体','entity'), ('标志', _p_onoff('隐藏(清bit1)','显示(置bit1)'))],
    'SetWait':    [('实体','entity'), ('最小tick', None), ('最大tick', None)],
    'Nop':        [('填充', None)],
    'SetCursor':  [('Cur.JVG块', lambda v: _CURSOR_BLOCKS.get(int(v), '') if v.lstrip('-').isdigit() else ''), ('帧延迟', lambda v: '引擎默认' if v == '3' else ''), ('显隐', _p_onoff('隐藏','显示'))],
    'FadeOut':    [('R', None), ('G', None), ('B', None), ('每步延迟ms', lambda v: '越大越慢')],
    'FadeIn':     [('R', None), ('G', None), ('B', None), ('每步延迟ms', lambda v: '越大越慢')],
    'ChangeScene':[('场景ID','scene'), ('玩家X', None), ('玩家Y', None), ('朝向', _DIR8)],
    'SetAni':     [('实体','entity'), ('Ani.JVG块', _KEEP_BLK), ('帧起点', _UNCHG), ('帧终点', _UNCHG), ('当前帧', _UNCHG), ('保留末帧', dict(_UNCHG, **{'0':'不保留','1':'播完停末帧'})), ('循环', {'0':'不循环','1':'循环','-1':'不变'})],
    'SetTick':    [('实体','entity'), ('tick周期(帧)', None)],
    'SetShadow':  [('实体','entity'), ('阴影帧', {'0':'无','1':'小','2':'大'})],
    'SetPos':     [('实体','entity'), ('X', None), ('Y', None), ('朝向', _DIR8)],
    'Disable':    [('实体','entity')],
    'Enable':     [('实体','entity')],
    'Redraw':     [('帧数', None)],
    'SetPlayer':  [('实体(须type200)', None)],
    'SetCamera':  [('实体', lambda v: '禁用镜头跟随' if v == '-1' else f'跟随实体#{v}')],
    'SetView':    [('世界X', None), ('世界Y', None)],
    'SlideTo':    [('目标X(视口中心)', None), ('目标Y', None), ('帧数(时长)', None)],
    'PlayerAct':  [('模式', {'0':'锁定玩家操作','1':'恢复玩家操作'})],
    'SetFlag':    [('标志ID(0-1023)', None), ('值', None)],
    'AddFlag':    [('标志ID(0-1023)', None), ('增量', None)],
    'TalkA':      [('实体','entity'), ('文本ID','text'), ('立绘/头像帧', _p_onoff('无立绘','有立绘')), ('对话框位置', {'1':'上','2':'下','-1':'按朝向自动'}), ('持续帧数', None)],
    'Switch':     [('实体(仅type200)','entity'), ('模式', {'0':'常规/站桩(Cha.JVG)','1':'动画/行走(Ani.JVG)'})],
    'SetVar':     [('变量槽(0-249)', None), ('值', None)],
    'Random':     [('变量槽', None), ('最小值', None), ('最大值', None)],
    'SetFlagVar': [('标志ID', None), ('变量槽', None)],
    'AddFlagVar': [('标志ID', None), ('变量槽', None)],
    'GetItem':    [('道具ID','item'), ('数量(正=获得 负=移除)', None)],
    'BlackTalk':  [('文本ID','text'), ('X', None), ('Y', None), ('颜色索引', None)],
    'SetChaPic':  [('实体(仅type200)','entity'), ('Cha.JVG立绘块', None)],
    'SetWeather': [('天气类型', {'1':'雨','0':'—'}), ('开关', _p_onoff('关闭天气','开启'))],
    'ShowMenu':   [('菜单类型', {'0':'姓名输入(命名)','1':'传送/世界地图菜单'})],
    'TeamMember': [('角色','char'), ('模式', _p_onoff('离开队伍','加入队伍'))],
    'Note':       [('标记槽(0-999)', None), ('值', None)],
    'SetBlock':   [('传送点实体(仅type10)','entity'), ('封锁', _p_onoff('开放路径','封锁路径'))],
    'Attribute':  [('目标', lambda v: '全队' if v == '-1' else _cm(v)), ('属性', lambda v: _ATTR_NAMES.get(int(v), '') if v.lstrip('-').isdigit() else ''), ('变化值(正=增 负=减)', None)],
    'SetSwitch':  [('开关槽(0-31)', None), ('值', None)],
    'BuyMenu':    [('商店编号', None), ('分类', {'0':'药品','1':'道具','2':'武器+防具','3':'药品+道具','4':'饰品'}), ('附加参数', None)],
    'PlaySound':  [('音效ID', None), ('循环', _p_onoff('单次','循环'))],
    'StopSound':  [('音效ID', None)],
    'PlayMusic':  [('音乐ID', lambda v: '停止音乐' if v.startswith('-') else ''), ('循环', _p_onoff('单次','循环'))],
    'SetMusic':   [('场景ID','scene'), ('音乐ID', lambda v: '停止当前音乐' if v == '-1' else '')],
    'TheEnd':     [('结局ID', None)],
    'Fix':        [('保留', None)],
    'CheckResult':[('变量槽', None), ('期望值', None)],
    'CheckFlag':  [('标志ID(0-1023)', None), ('期望值', None), ('操作符', _CMP_OPS)],
    'CheckItem':  [('道具ID','item'), ('期望数量', None), ('操作符', _CMP_OPS)],
    'CheckTeam':  [('类别', lambda v: _CAT_NAMES.get(int(v), '') if v.lstrip('-').isdigit() else ''), ('值', None), ('操作符', _CMP_OPS)],
    'MiniGame':   [('游戏类型', {'1':'华容道','2':'八阵图','3':'骰子','4':'串珠','5':'四四同数','6':'拼图','7':'龙蛇百变'}), ('通关分阈值', None), ('比较模式', lambda v: '分数≥阈值判胜' if v == '1' else '分数<阈值判胜')],
    'CheckMember':[('角色','char'), ('属性类型', {'0':'等级'}), ('期望值', None), ('操作符', _CMP_OPS)],
    'War':        [('战斗ID', None)],
    'Else':       [],
}

def _interp_param(interp, val, tkt, item_names):
    """解释参数"做什么"(功能/角色), 而非把引用ID解析成内容(内容已在"描述"栏给出)。"""
    if interp is None:
        return ''
    if isinstance(interp, dict):
        return interp.get(val, '')
    if callable(interp):
        try:
            return interp(val) or ''
        except Exception:
            return ''
    # 字符串 tag: entity/cmp 说明该值选择了什么目标/运算(功能性);
    #            引用类(char/scene/text/item/menu) 只说明该参数用途, 不解析其指向的内容
    if interp == 'entity':
        return '自身' if val == '-2' else '上下文' if val == '-1' else f'实体#{val}'
    if interp == 'cmp':
        return _CMP_OPS.get(val, '')
    if interp == 'char':
        return '角色花名册编号(非地图实体号)'
    if interp == 'scene':
        return '场景编号'
    if interp == 'text':
        return '要显示文本的 TKT 编号'
    if interp == 'item':
        return '道具编号 (10000=金钱)'
    if interp == 'menu':
        return '各菜单选项文本的 TKT 编号'
    return ''

_CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'

def format_cmd_params(cmd_name, args, tkt=None, item_names=None):
    """逐参数说明: 返回 ['① 名称 = 值 — 解释', ...]; 无参数返回 []。供脚本预览"参数"栏使用。"""
    if not args:
        return []
    specs = SCRIPT_CMD_PARAMS.get(cmd_name)
    lines = []
    for i, val in enumerate(args):
        num = _CIRCLED[i] if i < len(_CIRCLED) else f'({i+1})'
        name, interp = (specs[i] if specs and i < len(specs) else (f'参数{i+1}', None))
        expl = _interp_param(interp, val, tkt, item_names)
        lines.append(f"{num} {name} = {val}" + (f" — {expl}" if expl else ""))
    return lines
