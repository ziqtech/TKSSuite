"""
version.py — TKS 编辑器版本号管理 (单一数据源)
=================================================
符合 SemVer (语义化版本规范): https://semver.org/lang/zh-CN/

版本号格式: MAJOR.MINOR.PATCH
  - MAJOR: 不兼容的 API 变更
  - MINOR: 向下兼容的功能新增
  - PATCH: 向下兼容的缺陷修复

开发阶段约定:
  - 0.x.x: 开发阶段 (未正式发布)
  - 1.0.0: 首个正式发布版本

所有编辑器处于开发阶段, 初始版本统一为 0.0.1。
正式发布时将主版本号升至 1.0.0, 后续按 SemVer 规范递增。

构建日期:
  - 开发环境 (非编译): 显示 "开发阶段（未打包）"
  - Nuitka 编译环境: 自动读取 exe 文件 mtime 作为构建日期
    无需 build_all.py 注入, 纯运行时计算

使用示例::

    from editor_utils.version import get_version, format_title

    v = get_version("item_editor")
    print(v.app_name)   # "TKItem.dat 可视化编辑器"
    print(v.version)    # "0.0.1"

    # 窗口标题
    self.setWindowTitle(format_title("item_editor"))
    self.setWindowTitle(format_title("item_editor", os.path.basename(path)))
"""
import os
import sys
from dataclasses import dataclass


# ── 构建日期 ──
# 开发阶段固定文案; 编译环境由 get_build_date() 运行时计算 exe mtime
_BUILD_DATE_DEV = "开发阶段（未打包）"


# ── 版权声明 (追加到所有编辑器窗口标题末尾) ──
_LICENSE_NOTICE = "本软件免费开源，仅供个人学习、研究使用，不得用于商业目的"


def _detect_build_date() -> str:
    """检测构建日期。

    开发环境: 返回 "开发阶段（未打包）"
    Nuitka 编译环境: 返回 exe 文件的修改时间 (YYYY-MM-DD HH:MM)
    """
    # Nuitka 编译后存在 __compiled__ 全局变量
    if "__compiled__" not in globals() and not getattr(sys, "frozen", False):
        return _BUILD_DATE_DEV

    # 编译环境: 从 sys.argv[0] (原始 exe 路径, Nuitka onefile 下保留) 读取 mtime
    try:
        exe_path = sys.argv[0] if sys.argv and sys.argv[0] else sys.executable
        if exe_path and os.path.isfile(exe_path):
            mtime = os.path.getmtime(exe_path)
            from datetime import datetime
            return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        pass
    return _BUILD_DATE_DEV


@dataclass(frozen=True)
class EditorVersion:
    """单个编辑器的版本信息 (不可变)"""

    app_id: str    # 编辑器唯一标识 (如 "item_editor")
    app_name: str  # 显示名称 (如 "TKItem.dat 可视化编辑器")
    version: str   # SemVer 版本号 (如 "0.0.1")


# ── 各编辑器版本号登记表 ──
# 修改版本号时只需更新此表, 全部编辑器自动生效
_EDITORS: dict[str, EditorVersion] = {
    "item_editor":        EditorVersion("item_editor",        "TKItem.dat 可视化编辑器",         "1.3.0"),
    "warpc_editor":       EditorVersion("warpc_editor",       "WarPC.dat 可视化编辑器",          "1.3.0"),
    "skill_editor":       EditorVersion("skill_editor",       "TKSkill.dat 可视化编辑器",        "1.3.0"),
    "shop_editor":        EditorVersion("shop_editor",        "TKShop.dat 可视化编辑器",         "1.3.0"),
    "mat_editor":         EditorVersion("mat_editor",         "TKMat.Dat 可视化编辑器",          "1.3.0"),
    "jvg_editor":         EditorVersion("jvg_editor",         "JVG 图集编辑器",                  "1.3.0"),
    "grp_editor":         EditorVersion("grp_editor",         "GRP 资源包编辑器",                "1.3.0"),
    "tkt_editor":         EditorVersion("tkt_editor",         "TKT.dat 可视化编辑器",            "1.3.0"),
    "kon_editor":         EditorVersion("kon_editor",         "TKKon.dat 可视化编辑器",          "1.3.0"),
    "act_editor":         EditorVersion("act_editor",         "TKAct.dat 可视化编辑器",          "1.3.0"),
    "wardata_editor":     EditorVersion("wardata_editor",     "WarData.dat 可视化编辑器",        "1.3.0"),
    "gxp_editor":         EditorVersion("gxp_editor",         "GXP 图像编辑器",                  "1.3.0"),
    "spritesheet_editor": EditorVersion("spritesheet_editor", "精灵表编辑器",                    "1.3.0"),
    "save_editor":        EditorVersion("save_editor",        "TKS 存档编辑器",                  "1.3.0"),
    "configs_editor":     EditorVersion("configs_editor",     "TKS 配置编辑器",                  "1.3.0"),
    "font_editor":        EditorVersion("font_editor",        "TKS 字体生成器",                  "1.3.0"),
    "tks_book":           EditorVersion("tks_book",           "TKS 图鉴",                        "1.3.0"),
    "launcher":           EditorVersion("launcher",           "TKS Mod 启动器",                  "1.3.0"),
}


def get_version(app_id: str) -> EditorVersion:
    """获取指定编辑器的版本信息

    Args:
        app_id: 编辑器唯一标识 (如 "item_editor")

    Returns:
        EditorVersion 实例

    Raises:
        KeyError: 未知编辑器标识
    """
    if app_id not in _EDITORS:
        raise KeyError(f"未知编辑器标识: {app_id} (已注册: {', '.join(_EDITORS)})")
    return _EDITORS[app_id]


def version_string(app_id: str) -> str:
    """获取指定编辑器的版本号字符串 (如 "0.0.1")"""
    return get_version(app_id).version


def app_name(app_id: str) -> str:
    """获取指定编辑器的显示名称"""
    return get_version(app_id).app_name


def format_title(app_id: str, subtitle: str | None = None) -> str:
    """格式化窗口标题

    标题含 Qt 的 ``[*]`` 占位符: setWindowModified(True) 时标题栏自动显示
    修改标记 ``*`` (未修改时 Qt 将 ``[*]`` 渲染为空, 标题外观不变)。

    Args:
        app_id: 编辑器唯一标识
        subtitle: 副标题 (如文件名), None 表示无副标题

    Returns:
        无副标题: "{app_name} v{version}[*] — {版权声明}"
        有副标题: "{app_name} v{version}[*] — {subtitle} — {版权声明}"
    """
    v = get_version(app_id)
    base = f"{v.app_name} v{v.version}[*]"
    if subtitle:
        base = f"{base} — {subtitle}"
    return f"{base} — {_LICENSE_NOTICE}"


def get_build_date() -> str:
    """获取构建日期 (编译环境自动检测 exe mtime, 开发环境返回占位文案)"""
    return _detect_build_date()


def format_about_header(app_id: str) -> str:
    """格式化"关于"对话框的标题行 (含版本号、作者、构建日期与免费提示)

    Returns:
        "{app_name} v{version}\\n作者：端木子青\\n构建日期: {build_date}\\n\\n{免费提示}"
    """
    v = get_version(app_id)
    return (
        f"{v.app_name} v{v.version}\n作者：端木子青\n构建日期: {get_build_date()}"
        f"\n\n{_LICENSE_NOTICE}\n本软件开源免费、永久为爱发电。若你付费获得，建议向卖家申请退款。"
    )
