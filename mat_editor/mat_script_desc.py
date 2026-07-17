# -*- coding: utf-8 -*-
"""mat_editor_v2 脚本命令描述系统 — 命令列表/描述模板与人类可读描述辅助函数。
从 mat_editor_v2.py 原样迁出, 无 UI 逻辑 (§工程化拆分)。"""
import os
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
        cnt = min(50, len(dec) // REC)
        for i in range(cnt):
            off = i * REC
            name_id = struct.unpack_from('<h', dec, off)[0]
            if name_id > 0 and name_id in tkt_lookup:
                name = tkt_lookup[name_id].split('\n')[0].strip()
                if name:
                    _char_name_cache[i] = name
        # 主角 (index 0): TKT#9000 是控制字符占位, 用 "主角"
        if 0 not in _char_name_cache:
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
# CheckTeam arg3 比较运算符 (基于TKD脚本注释语义 + 队伍人数检查模式推断)
_CMP_OPS = {'0':"==", '1':"≥", '-1':"<", '-2':"≤", '2':">"}

def _checkteam_desc(args):
    """根据逆向 + TKD.dat 脚本注释生成 CheckTeam 的人类可读描述。
    ┌──────┬──────────┬──────────────────────────────────────┐
    │ arg1 │ 语义     │ 逆向依据                             │
    ├──────┼──────────┼──────────────────────────────────────┤
    │  1   │ 角色存在 │ TKD: CheckTeam(1,N,0) 后跟角色操作    │
    │  2   │ 智慧     │ TKD注释+save_editor SEG2 byte_756886 │
    │  3   │ 仁德     │ TKD注释+save_editor SEG2 byte_756887 │
    │  4   │ 勇气     │ TKD注释+save_editor SEG2 word_756888 │
    │  5   │ 队伍人数 │ TKD:-2=有空位/1=已满 word_75688C[6]  │
    │  6   │ 医术     │ TKD注释+save_editor SEG2 word_75688A │
    │ 10   │ 随机概率 │ TKD注释:"事件概率N%触发"             │
    │ 11   │ 特殊物品 │ TKD注释+save_editor sub_40E11C case11│
    └──────┴──────────┴──────────────────────────────────────┘
    arg3: 0=存在/==  1=≥  -1=<  -2=≤  2=>"""
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

# Attribute arg2 语义映射 (来源: TKD_decoded.txt 664处用法 + 脚本注释)
# arg2: 1=智慧 2=仁德 3=勇气 5=体力值恢复 6=内力值恢复 10=事件完成度 11=特殊物品
_ATTR_NAMES = {1:"智慧", 2:"仁德", 3:"勇气", 5:"体力值恢复", 6:"内力值恢复", 10:"事件完成度", 11:"特殊物品"}

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
    """SetCursor(Cur.JVG块, 帧延迟, 开关): arg1选择光标精灵块, arg2动画帧延迟, arg3显示开关"""
    if not args or len(args) < 3:
        return "设置光标"
    ent = args[0]
    spd = args[1]
    en = args[2]
    en_str = "隐藏" if en == '0' else "显示" if en == '1' else f"模式{en}"
    block_name = _CURSOR_BLOCKS.get(int(ent) if ent.lstrip('-').isdigit() else -1, f"块{ent}")
    spd_str = f"延迟{spd}t" if spd != '3' else ""  # 3=引擎默认, 不显示
    ent_str = "玩家" if ent == '1' else "当前" if ent == '-1' else f"实体{ent}"
    return f"{ent_str}光标 {en_str} [{block_name}]{' '+spd_str if spd_str else ''}"

def _attribute_desc(args):
    """根据 TKD脚本注释生成 Attribute 的人类可读描述。
    Attribute(实体, 属性, 变化值): arg2=1智慧 2仁德 3勇气 5体力 6内力 10事件 11特殊"""
    if not args or len(args) < 3:
        return "属性变更"
    try:
        attr = int(args[1])
        val = int(args[2])
        name = _ATTR_NAMES.get(attr, f"属性{attr}")
        sign = "+" if val >= 0 else ""
        if attr in (5, 6) and val >= 9999:
            return f"{name}完全恢复"
        return f"属性变更 {name}{sign}{val}"
    except (ValueError, TypeError):
        return f"属性变更 ({','.join(args[:3])})"

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
    # opcode 1: TalkB(4) — 阻塞式对话: 实体, 文本ID, 参数, 参数
    'TalkB':        lambda a, t: f"对话(等待) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"对话(等待) 实体#{a[0]}" if a else "对话(等待)",
    # opcode 2: SetTalkB(4) — 设置对话不等待: 实体, 文本ID, 参数, 参数
    'SetTalkB':     lambda a, t: f"设置对话(不等待) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"设置对话 实体#{a[0]}" if a else "设置对话",
    # opcode 3: DoTalkB(0) — 执行对话显示
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
    # opcode 5: SysTalk(6) — 系统对话 (sub_40B1B4)
    # 参数: 实体, 文本ID, 颜色索引, 位置X, 位置Y, 模式(0=阻塞 1=非阻塞)
    'SysTalk':      lambda a, t: (
        f"系统对话 实体#{a[0]} 文本={a[1]} 色{a[2]} ({a[3]},{a[4]}) {'非阻塞' if a[5]=='1' else '阻塞'}"
        if len(a)>=6 else f"系统对话 ({','.join(a)})" if a else "系统对话"
    ),
    # opcode 6: SetHint(3) — 设置提示 (sub_40B650)
    # 参数: 实体(-1=上下文 -2=自身), 提示文本ID, 开关(0=关闭提示 >0=开启提示)
    'SetHint':      lambda a, t: (
        f"设置提示 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} 文本={a[1]} {'开启' if a[2]!='0' else '关闭'}"
        if len(a)>=3 else f"设置提示 ({','.join(a)})" if a else "设置提示"
    ),
    # opcode 7: MenuTalk(2) — 菜单对话 (sub_40B710)
    # 参数: 文本ID, 变量槽(存储选择结果)
    'MenuTalk':     lambda a, t: f"菜单对话 文本={a[0]}→变量[{a[1]}]" if len(a)>=2 else f"菜单对话 ({','.join(a)})" if a else "菜单对话",
    # opcode 8: SetScene(2) — 设置场景状态 (sub_40BB70)
    # 参数: 实体(-1=上下文 -2=自身), 场景ID
    'SetScene':     lambda a, t: (
        f"设置场景 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} →场景{a[1]}"
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
    # opcode 16: SetCursor(3) — 设置光标
    # 逆向: sub_411BA4/sub_412390, TKMat[d8]=cursor_id
    # 参数: (实体, 光标动画, 开关)  动画:0=默认 1=标准 3=开门(传送)  开关:0=隐藏 1=显示
    'SetCursor':    lambda a, t: _setcursor_desc(a),
    # opcode 17: FadeOut(4) — 淡出 (sub_409830)
    # 参数: R, G, B, 速度(越大越快)
    'FadeOut':      lambda a, t: f"淡出 RGB({a[0]},{a[1]},{a[2]}) 速度={a[3]}" if len(a)>=4 else "淡出",
    # opcode 18: FadeIn(4) — 淡入: R, G, B, 速度
    'FadeIn':       lambda a, t: f"淡入 RGB({a[0]},{a[1]},{a[2]}) 速度={a[3]}" if len(a)>=4 else "淡入",
    # opcode 19: ChangeScene(4) — 切换场景 (sub_40C044)
    # 参数: 场景ID, 玩家X, 玩家Y, 朝向(1-8)
    # 加载新场景文件, 设置玩家位置和朝向, 重置天气/对话等状态
    # 场景名称通过 TKT_ID = scene_id + 300 获取
    'ChangeScene':  lambda a, t: (
        f"切换场景→#{a[0]} {_tkt_scene(t, a[0])} ({a[1]},{a[2]})朝向{a[3]}"
        if len(a)>=4 else
        f"切换场景→#{a[0]} {_tkt_scene(t, a[0])}" if a else "切换场景"
    ),
    # opcode 20: SetAni(7) — 设置动画 (sub_40C1A4)
    # 参数: 实体(-1=上下文 -2=自身), Ani.JVG块ID, 帧起点(-1=不变), 帧终点(-1=不变),
    #        当前帧(-1=不变), 动画速度(-1=不变), 循环标志(0=不循环 1=循环 -1=不变)
    # 仅type=20/200有效; 设置anim_set=4(Ani.JVG), 修改子模型和动画参数
    'SetAni':       lambda a, t: (
        f"设置动画 {'自身' if a[0]=='-2' else '上下文' if a[0]=='-1' else '实体#'+a[0]} 块={a[1]}"
        if len(a)>=2 else f"设置动画 ({','.join(a)})" if a else "设置动画"
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
    # opcode 34: TalkA(5) — 即时式对话: 实体, 文本ID, 参数, 参数, 参数
    'TalkA':        lambda a, t: f"对话(即时) 实体#{a[0]} 文本={a[1]} — {_tkt_text(t, a[1])}" if len(a)>=2 else f"对话(即时) 实体#{a[0]}" if a else "对话(即时)",
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
    # 参数: 天气类型(0=关闭 1=雨), 保留
    # a1=0: 清除天气粒子(sub_405B98)
    # a1=1: 开启下雨效果(sub_405BE0), 参数: 类型=1, 粒子数=5, 最大=400, 增速=10, 速度=5
    'SetWeather':   lambda a, t: (
        f"天气→{'关闭' if a[0]=='0' else '下雨' if a[0]=='1' else '类型'+a[0]}"
        if a else "设置天气"
    ),
    # opcode 44: ShowMenu(2) — 显示菜单
    # 逆向: sub_40D2D0(__int16 a1), 参数: 0=主菜单 1=存档/读档菜单
    'ShowMenu':     lambda a, t: (
        f"显示主菜单" if a and a[0] == '0' else
        f"显示存档菜单" if a and a[0] == '1' else
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
    # opcode 50: BuyMenu(3) — 商店菜单
    # 逆向: sub_40D804(__int16 a1, __int16 a2, __int16 a3)
    # a1=商品ID, a2=商品索引, a3=商店模式(0-4: 0=武器 1=防具 2=药品 3=杂货 4=特殊)
    'BuyMenu':      lambda a, t: (
        f"商店菜单 商品={a[0]} 索引={a[1]} 模式={'武器' if a[2]=='0' else '防具' if a[2]=='1' else '药品' if a[2]=='2' else '杂货' if a[2]=='3' else '特殊' if a[2]=='4' else a[2]}"
        if len(a)>=3 else "商店菜单"
    ),
    # opcode 51: PlaySound(2) — 播放音效 (sub_451780 + sub_451C38)
    # 参数: 音效ID, 循环(0=不循环 1=循环)
    # 音效文件: sound\%04d.wav; 使用DirectSound播放
    'PlaySound':    lambda a, t: (
        f"播放音效 {a[0]} {'循环' if len(a)>=2 and a[1]!='0' else '单次'}"
        if a else "播放音效"
    ),
    # opcode 52: StopSound(1) — 停止音效 (sub_451D2C)
    # 无参数; 停止当前播放的音效
    'StopSound':    lambda a, t: "停止音效",
    # opcode 53: PlayMusic(2) — 播放音乐 (sub_44AC50 + sub_44AC90)
    # 参数: 音乐ID, 循环(0=不循环 1=循环)
    # 音乐文件: sound\%04d.mp3; 使用DirectShow播放
    'PlayMusic':    lambda a, t: (
        f"播放音乐 {a[0]} {'循环' if len(a)>=2 and a[1]!='0' else '单次'}"
        if a else "播放音乐"
    ),
    # opcode 54: SetMusic(2) — 设置场景BGM映射 (case 54)
    # 参数: 场景ID(0-255), 音乐ID(-1=停止当前)
    # 存储在byte_755B74[256], 切换场景时自动播放对应BGM
    # 如果设置的是当前场景的BGM且值<0, 则停止当前音乐
    'SetMusic':     lambda a, t: (
        f"场景BGM 场景{a[0]}→{'停止' if a[1]=='-1' else '音乐'+a[1]}"
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
    # 参数: 标志ID(0-1023), 期望值, 操作符(0=== 1=>= -1=< -2=<= 2=> 3=!=)
    # 比较word_756080[标志ID]与期望值, 结果存入dword_755AA0
    # 字节码中隐含跳转偏移: 如果比较失败则跳转
    'CheckFlag':    lambda a, t: (
        f"检查标志 #{a[0]} {_CMP_OPS.get(a[2], a[2])} {a[1]}?"
        if len(a)>=3 else f"检查标志 #{a[0]}" if a else "检查标志"
    ),
    # opcode 62: CheckItem(3) — 检查道具条件跳转 (sub_40E4E4)
    # 参数: 道具ID(10000=金钱), 期望数量, 操作符(0=== 1=>= -1=< -2=<= 2=> 3=!=)
    # 统计背包+队伍装备中的道具总数, 与期望值比较
    # 结果存入dword_755AA0, 字节码中隐含跳转偏移
    'CheckItem':    lambda a, t: (
        f"检查道具 {a[0]} {_CMP_OPS.get(a[2], a[2])} {a[1]}?"
        if len(a)>=3 else f"检查道具 {a[0]}" if a else "检查道具"
    ),
    # opcode 63: CheckTeam(3) — 检查队伍条件跳转
    'CheckTeam':    lambda a, t, i=None: _checkteam_desc(a),
    # opcode 64: MiniGame(3) — 小游戏 (sub_40E97C)
    # 参数: 游戏类型(1-7), 难度/参数, 跳转偏移(失败时跳转)
    # 游戏类型: 1=华容道 2=八阵图 3=骰子 4=串珠 5=四四同数 6=拼图 7=龙蛇百变
    # 返回dword_755AA0: 1=成功 0=失败; 失败时跳转到指定偏移
    'MiniGame':     lambda a, t: (
        f"小游戏 {'华容道' if a[0]=='1' else '八阵图' if a[0]=='2' else '骰子' if a[0]=='3' else '串珠' if a[0]=='4' else '四四同数' if a[0]=='5' else '拼图' if a[0]=='6' else '龙蛇百变' if a[0]=='7' else '类型'+a[0]}"
        if a else "小游戏"
    ),
    # opcode 65: CheckMember(4) — 检查队伍成员属性 (sub_40E88C)
    # 参数: 角色ID, 属性类型(0=等级), 期望值, 操作符(0=== 1=>= -1=< -2=<= 2=> 3=!=)
    # 检查指定角色的属性值, 结果存入dword_755AA0
    # 字节码中隐含跳转偏移: 如果比较失败则跳转
    'CheckMember':  lambda a, t: (
        f"检查成员 角色#{a[0]} 属性{a[1]} {_CMP_OPS.get(a[3], a[3])} {a[2]}?"
        if len(a)>=4 else f"检查成员 ({','.join(a)})" if a else "检查成员"
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
