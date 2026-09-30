"""编辑器注册表 — build/gen_entries.py 与 build/build_all.py 的单一事实来源 (T5 单源化)。

新增编辑器只改这一张表:
  1. python build/gen_entries.py  重新生成入口脚本
  2. build_all.py 的构建/校验/组装自动跟随

字段: (打包名, 入口文件名, 导入模块路径, 编辑器目录, 是否需要 runtime bootstrap)
- 导入路径: 单层模块名 (from item_editor import main) 或点号路径
  (from configs_editor.configs_editor import main)。
  configs_editor/font_editor 是正规包 (有 __init__.py + 子包), 必须用点号路径;
  其他编辑器目录无 __init__.py, 单层模块名 (item_editor) 优先解析到编辑器目录内
  的同名主文件, 根目录同名目录仅作 namespace package 片段兜底。
- bootstrap: 是否需要运行时 bootstrap (依赖 PySide6/PIL 的编辑器需开启)。
"""

EDITORS = [
    ("TKSItemEditor",        "entry_item_editor.py",        "item_editor",                   "item_editor",       True),
    ("TKSWarpcEditor",       "entry_warpc_editor.py",       "warpc_editor",                  "warpc_editor",      True),
    ("TKSSkillEditor",       "entry_skill_editor.py",       "skill_editor",                  "skill_editor",      True),
    ("TKSShopEditor",        "entry_shop_editor.py",        "shop_editor",                   "shop_editor",       True),
    ("TKSMatEditor",         "entry_mat_editor.py",         "mat_editor",                    "mat_editor",        True),
    ("TKSJvgEditor",         "entry_jvg_editor.py",         "jvg_editor",                    "jvg_editor",        True),
    ("TKSGrpEditor",         "entry_grp_editor.py",         "grp_editor",                    "grp_editor",        True),
    ("TKSTktEditor",         "entry_tkt_editor.py",         "tkt_editor",                    "tkt_editor",        True),
    ("TKSKonEditor",         "entry_kon_editor.py",         "kon_editor",                    "kon_editor",        True),
    ("TKSActEditor",         "entry_act_editor.py",         "act_editor",                    "act_editor",        True),
    ("TKSWardataEditor",     "entry_wardata_editor.py",     "wardata_editor",                "wardata_editor",    True),
    ("TKSGxpEditor",         "entry_gxp_editor.py",         "gxp_editor",                    "gxp_editor",        True),
    ("TKSSpritesheetEditor", "entry_spritesheet_editor.py", "spritesheet_editor",            "spritesheet_editor",True),
    ("TKSSaveEditor",        "entry_save_editor.py",        "save_editor",                   "save_editor",       True),
    ("TKSConfigsEditor",     "entry_configs_editor.py",     "configs_editor.configs_editor", "configs_editor",    True),
    ("TKSFontEditor",        "entry_font_editor.py",        "font_editor.font_editor",       "font_editor",       True),
    ("TKSBook",              "entry_tks_book.py",           "tks_book",                      "tks_book",          True),
    ("TKSLauncher",          "entry_launcher.py",           "main",                          "tks_launcher_gui",  True),
]
