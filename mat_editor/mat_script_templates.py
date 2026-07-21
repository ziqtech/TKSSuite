# -*- coding: utf-8 -*-
"""mat_editor_v2 常用脚本模板库 (纯数据, 无 UI 逻辑, §工程化拆分)。

模板来源: 解析 TKS 原版 TKD.dat 全部 1605 个 DEFINE (39635 条命令), 按命令频率、
相邻二/三元组、以及 DEFINE 命令集合骨架统计, 归纳出出现频率最高的脚本写法。

统计要点 (供维护参考):
  单命令 Top: TalkB(10355) End(2619) CheckFlag(2573) SetPos(2482) Disable(2311)
              Enable(2123) AddFlag(1391) CheckResult(1383) SetWalk(1368) GetItem(1335)
              SetWait(1300) WaitWalk(1196) Switch(1143) FadeIn(752) Attribute(664)
              MenuTalk(641) FadeOut(607) PlayerAct(517) ...
  三元组 Top: TalkB→TalkB→TalkB(3515) MenuTalk→CheckResult→TalkB(400)
              SetWalk→WaitWalk→SetPos(499) CheckFlag→Attribute→AddFlag(378)
              TalkB→GetItem→AddFlag(366) FadeOut→FadeIn→TalkB(261) ...
  DEFINE 骨架 Top: SetPos+TalkB+End(214) Switch+TalkB+End(128) 招募链(116)
              纯对话 TalkB+End(106) Attribute+End(48) SetWalk+WaitWalk 巡逻(25) ...

每个模板 body 为可直接插入脚本编辑框的命令行文本; 实体默认用 -2(自身),
需替换的编号(文本ID/物品ID/场景ID等)以占位数字给出, 并在开头 // 注释行说明。
⚠ 行内 // 注释禁止包含英文括号, 否则会被 (.*) 命令解析正则误吞 (整行 // 注释不受限)。
"""

# 每个分类: (分类名, [ (模板名, 一句话说明, body), ... ])
SCRIPT_TEMPLATES = [
    ("对话类", [
        (
            "单段对话",
            "最基础的一句对话, 显示后按键结束 (TalkB+End)",
            "// 单段对话: -2=自身  25000=TKT对话文本编号  1=显示立绘  -1=对话框按朝向自动\n"
            "TalkB(-2,25000,1,-1)\n"
            "End(0)\n"
        ),
        (
            "多段连续对话",
            "按顺序逐条显示多句台词 (TalkB×N+End, 最高频三元组)",
            "// 多段连续对话: 逐条显示, 每条等待玩家按键; 修改各行的文本编号即可\n"
            "TalkB(-2,25000,1,-1)\n"
            "TalkB(-2,25001,1,-1)\n"
            "TalkB(-2,25002,1,-1)\n"
            "End(0)\n"
        ),
        (
            "NPC对话·冻结与恢复",
            "对话前冻结NPC动画, 结束后恢复行走 (Switch+TalkB+Switch)",
            "// NPC对话: Switch 第2参 0=冻结站桩 1=恢复行走; 仅 type=200 NPC 有效\n"
            "Switch(-2,0)\n"
            "TalkB(-2,25000,1,-1)\n"
            "Switch(-2,1)\n"
            "End(0)\n"
        ),
        (
            "浮动旁白",
            "非阻塞浮动文字, 停留数帧自动消失 (TalkA+SetWait)",
            "// 浮动旁白: TalkA 第5参=持续帧数; SetWait 让脚本停留同样时长再继续\n"
            "TalkA(-2,25000,0,-1,17)\n"
            "SetWait(-2,10,25)\n"
            "End(0)\n"
        ),
    ]),
    ("分支·菜单类", [
        (
            "菜单二选一",
            "对话后弹出菜单, 按选择分支执行 (MenuTalk+CheckResult)",
            "// 菜单二选一: MenuTalk 选项文本以换行分隔, 选中项索引存入变量槽0\n"
            "TalkB(-2,25000,1,-1)\n"
            "MenuTalk(25001,0)\n"
            "CheckResult(0,0)\n"
            "{\n"
            "  TalkB(-2,25002,1,-1)\n"
            "}\n"
            "CheckResult(0,1)\n"
            "{\n"
            "  TalkB(-2,25003,1,-1)\n"
            "}\n"
            "End(0)\n"
        ),
        (
            "标志条件分支",
            "按剧情标志走不同分支 (CheckFlag + Else)",
            "// 标志条件分支: 标志100 与值1 比较, 运算符0=相等; 满足走花括号, 否则走 Else\n"
            "CheckFlag(100,1,0)\n"
            "{\n"
            "  TalkB(-2,25000,1,-1)\n"
            "}\n"
            "Else\n"
            "{\n"
            "  TalkB(-2,25001,1,-1)\n"
            "}\n"
            "End(0)\n"
        ),
    ]),
    ("道具·队伍类", [
        (
            "给予道具与金钱",
            "对话后发放道具和金钱 (TalkB+GetItem, End(2)不重复)",
            "// 给予道具与金钱: 物品编号100给1个; 10000=金钱给300; End(2)推进B链避免重复领取\n"
            "TalkB(-2,25000,1,-1)\n"
            "GetItem(100,1)\n"
            "GetItem(10000,300)\n"
            "End(2)\n"
        ),
        (
            "队伍属性变更",
            "增减全队属性 (Attribute)",
            "// 队伍属性: -1=全队; 属性 1=智慧 2=仁德 3=勇气 4=医术 5=体力恢复 6=内力恢复; 末参=增减值\n"
            "Attribute(-1,1,2)\n"
            "End(0)\n"
        ),
        (
            "招募队友",
            "询问加入→检查空位→入队 (MenuTalk+CheckTeam+TeamMember)",
            "// 招募队友: 花名册编号30; CheckTeam(5,6,-2) 判断队伍是否有空位\n"
            "TalkB(-2,25000,1,-1)\n"
            "MenuTalk(25001,1)\n"
            "CheckResult(1,0)\n"
            "{\n"
            "  CheckTeam(5,6,-2)\n"
            "  {\n"
            "    FadeOut(255,255,255,50)\n"
            "    TeamMember(30,1)\n"
            "    Disable(-2)\n"
            "    FadeIn(255,255,255,50)\n"
            "  }\n"
            "  Else\n"
            "  {\n"
            "    TalkB(-2,25002,1,-1)\n"
            "  }\n"
            "}\n"
            "End(0)\n"
        ),
    ]),
    ("移动·演出类", [
        (
            "NPC定点行走",
            "行走到坐标并等待, 可复制多段做巡逻 (SetWalk+WaitWalk+SetWait)",
            "// NPC定点行走: 仅 type=200 有效; 走到 320,240 后等待随机帧再继续\n"
            "SetWalk(-2,320,240)\n"
            "WaitWalk(-2,0)\n"
            "SetWait(-2,15,20)\n"
            "End(0)\n"
        ),
        (
            "过场演出·锁定操作",
            "锁定玩家操作演出, 结束恢复 (PlayerAct 0/1)",
            "// 过场演出: PlayerAct(0) 锁定玩家操作, 演出结束用 PlayerAct(1) 恢复\n"
            "PlayerAct(0)\n"
            "TalkB(-2,25000,1,-1)\n"
            "PlayerAct(1)\n"
            "End(2)\n"
        ),
        (
            "设置位置与朝向",
            "把实体瞬移到指定坐标并转向 (SetPos)",
            "// 设置位置与朝向: 实体号 X Y 朝向; 朝向 1=上 3=右 5=下 7=左\n"
            "SetPos(-2,320,240,5)\n"
            "End(0)\n"
        ),
    ]),
    ("场景·系统类", [
        (
            "淡入淡出切换场景",
            "黑屏过渡到新场景 (FadeOut+ChangeScene+FadeIn)",
            "// 淡入淡出切换场景: 目标场景编号1, 玩家落点 X Y 与朝向; End(2)推进B链\n"
            "FadeOut(0,0,0,100)\n"
            "ChangeScene(1,320,240,5)\n"
            "FadeIn(0,0,0,100)\n"
            "End(2)\n"
        ),
        (
            "触发战斗",
            "战前对话后进入战斗, 花括号内为战后处理 (War)",
            "// 触发战斗: 0=主角; War 参数为战斗编号; 花括号内在战斗结束后执行\n"
            "StopWalk(0,0)\n"
            "TalkB(0,25000,0,-1)\n"
            "War(1)\n"
            "{\n"
            "  End(0)\n"
            "}\n"
            "End(2)\n"
        ),
        (
            "商店买卖",
            "打开商店买卖界面 (Switch+BuyMenu)",
            "// 商店买卖: BuyMenu 首参=商店编号, 第2参分类 0药品 1道具 2武器防具 3药品道具 4饰品\n"
            "Switch(-2,0)\n"
            "TalkB(-2,25000,1,-1)\n"
            "BuyMenu(1,2,0)\n"
            "TalkB(-2,25001,1,-1)\n"
            "Switch(-2,1)\n"
            "End(0)\n"
        ),
        (
            "显示/隐藏实体",
            "启用显示或禁用隐藏地图实体 (Enable/Disable)",
            "// 显示/隐藏实体: Enable 显示并启用, Disable 隐藏并禁用; 参数为地图实体号\n"
            "Enable(100)\n"
            "Disable(101)\n"
            "End(0)\n"
        ),
    ]),
]
