# TKSSuite

三国群侠传（TKS）编辑与 MOD 套件 —— 面向《三国群侠传》的一整套数据表编辑器、MOD 启动器与游戏图鉴，
另附对该游戏二进制的逆向分析文档。

> 本仓库**不包含游戏本体数据**。所有编辑器都需要你自备正版游戏的 `.dat` / `.jvg` / `.grp`
> 等数据文件才能实际工作；仓库的 `.gitignore` 已按扩展名排除这些文件。

## 组件

| 组件 | 目录 | 说明 |
| --- | --- | --- |
| MOD 启动器 | `tks_launcher_gui/` | 以补丁方式为原版 TKS.exe 增补功能（宽屏、技能扩展、经验锁定等），并管理 MOD 包 |
| 物品编辑器 | `item_editor/` | TKItem.dat |
| 人物编辑器 | `warpc_editor/` | WarPC.dat |
| 技能编辑器 | `skill_editor/` | TKSkill.dat |
| 技能动作编辑器 | `kon_editor/` | TKKon.dat |
| 动画编辑器 | `act_editor/` | TKAct.dat |
| 商店编辑器 | `shop_editor/` | TKShop.dat |
| 场景实体编辑器 | `mat_editor/` | TKMat.dat / TKD.dat |
| 战场数据编辑器 | `wardata_editor/` | WarData.dat |
| 存档编辑器 | `save_editor/` | Save/*.sav |
| 精灵图集编辑器 | `jvg_editor/` | *.JVG |
| 图包编辑器 | `grp_editor/` | *.GRP |
| 场景编辑器 | `gxp_editor/` | *.GXP |
| 贴图集编辑器 | `spritesheet_editor/` | 单帧图片集 |
| 文本编辑器 | `tkt_editor/` | TKT.dat |
| 字库编辑器 | `font_editor/` | FONT9696 |
| 配置编辑器 | `configs_editor/` | `configs/*.json` |
| 游戏图鉴 | `tks_book/` | 以只读方式浏览游戏数据 |
| 逆向工具 | `utils/` | PE 分析、反汇编、二进制比对等辅助脚本 |

编辑器与启动器的共享代码在 `editor_utils/`，主题在 `editor_themes/`。

## 运行环境

- Python 3.13
- 运行编辑器：`PySide6`
- 运行部分编辑器：`Pillow`、`zhconv`
- 运行图鉴：`markdown-it-py>=3.0,<4`
- 运行测试：`pefile`、`capstone`、`unicorn`

```bash
pip install PySide6 Pillow zhconv "markdown-it-py>=3.0,<4" pefile capstone unicorn
```

## 使用

直接以脚本方式启动任一编辑器：

```bash
python item_editor/item_editor.py
python tks_launcher_gui/main.py
```

界面内通过菜单打开游戏对应的数据文件即可。启动器首次运行会让你指定 `TKS.exe` 的位置。

## 测试

测试用例需要真实的游戏数据才有意义，通过环境变量指定，**不设则自动跳过**而不会失败：

| 环境变量 | 指向 |
| --- | --- |
| `TKS_GAME_DIR` | 原版游戏目录（含 `TKS.exe`、`TKSkill.dat`、`WarPC.dat` 等） |
| `TKS_MOD_DIR` | 改版/MOD 目录（含追加帧的 `Mu.JVG`） |
| `TKS_VANILLA_EXE` | 原版 `TKS.exe` 完整路径 |
| `TKS_MU2_JVG` | 原版 `Mu2.JVG` 完整路径 |
| `TKS_MEM_DUMP` | 反汇编内存转储文本（仅 `test_trap_exp_jp_emu` 使用） |

```bash
TKS_GAME_DIR=/path/to/TKS python -m unittest discover -s tests -t .
```

## 打包

```bash
pip install -r build/requirements.txt
python build/build_all.py --list          # 查看可构建项
python build/build_all.py --onefile       # 全部打包为独立 exe
python build/build_all.py --only TKSLauncher --release
```

需要 MSVC（VS Build Tools）提供 C 编译器。编辑器清单见 `build/editors_registry.py`。

## 文档

`docs/` 下是开发过程中的逆向分析、补丁设计与实现记录，按模块分子目录。
其中 `docs/tksexe/` 是对游戏二进制的系统性分析。文档中引用的反编译产物、
内存转储等中间资料不在本仓库内。

## 许可证

本仓库作者原创的代码与文档，以 **CC BY-NC-SA 4.0**
（署名—非商业性使用—相同方式共享 4.0 国际）许可协议授权，**禁止任何商业用途**。

> Copyright (c) 2026 aaron. Licensed under CC BY-NC-SA 4.0.
> To view a copy of this license, visit
> https://creativecommons.org/licenses/by-nc-sa/4.0/

您可以自由地共享与改编本作品，惟须遵守以下条件：

- **署名** —— 保留上述版权声明与许可声明，并标明是否作了修改
- **非商业性使用** —— 不得将本作品用于商业目的
- **相同方式共享** —— 若基于本作品再创作，须以相同许可协议分发您的作品

完整法律文本见 [LICENSE](LICENSE)，
可读摘要见[简体中文译本](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh)。

> 注意：因含"禁止商业使用"条款，本项目属于 **source-available**，
> 不符合 OSI 的开源定义，请勿将其标注为 open source 项目。

## 关于游戏本体的权利声明

**上述许可仅覆盖本仓库作者原创的内容。**

《三国群侠传》游戏本体（含 `TKS.exe` 及其全部数据文件）的著作权属于其权利人。
本仓库不主张任何相关权利，也不授予任何相关许可。仓库中以特征码、偏移量等形式
记录、用于定位游戏二进制位点的补丁数据，以及对其行为的逆向分析结论，
其所依据作品的权利同样属于游戏权利人。

使用者需自行确保对游戏本体的持有与使用合法（例如自备正版），
并自行承担因分发或商用游戏衍生内容而产生的一切责任。

本项目为爱好者制作的第三方工具，与游戏权利人无任何关联。
