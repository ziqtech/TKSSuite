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

使用示例::

    from editor_utils.version import get_version, format_title

    v = get_version("item_editor")
    print(v.app_name)   # "TKItem.dat 可视化编辑器"
    print(v.version)    # "0.0.1"

    # 窗口标题
    self.setWindowTitle(format_title("item_editor"))
    self.setWindowTitle(format_title("item_editor", os.path.basename(path)))
"""
from dataclasses import dataclass


# ── 构建日期 ──
# 打包时由 build_all.py 注入实际日期; 开发阶段保持"开发阶段（未打包）"
BUILD_DATE = "开发阶段（未打包）"


@dataclass(frozen=True)
class EditorVersion:
    """单个编辑器的版本信息 (不可变)"""

    app_id: str    # 编辑器唯一标识 (如 "item_editor")
    app_name: str  # 显示名称 (如 "TKItem.dat 可视化编辑器")
    version: str   # SemVer 版本号 (如 "0.0.1")


# ── 各编辑器版本号登记表 ──
# 修改版本号时只需更新此表, 全部编辑器自动生效
_EDITORS: dict[str, EditorVersion] = {
    "item_editor":        EditorVersion("item_editor",        "TKItem.dat 可视化编辑器",         "1.0.0"),
    "warpc_editor":       EditorVersion("warpc_editor",       "WarPC.dat 可视化编辑器",          "1.0.0"),
    "skill_editor":       EditorVersion("skill_editor",       "TKSkill.dat 可视化编辑器",        "1.0.0"),
    "shop_editor":        EditorVersion("shop_editor",        "TKShop.dat 可视化编辑器",         "1.0.0"),
    "mat_editor":         EditorVersion("mat_editor",         "TKMat.Dat 地图实体编辑器",        "1.0.0"),
    "jvg_editor":         EditorVersion("jvg_editor",         "JVG 图集编辑器",                  "1.0.0"),
    "grp_editor":         EditorVersion("grp_editor",         "GRP 资源包编辑器",                "1.0.0"),
    "tkt_editor":         EditorVersion("tkt_editor",         "TKT.dat 文本数据库编辑器",        "1.0.0"),
    "kon_editor":         EditorVersion("kon_editor",         "TKKon.dat 可视化编辑器",          "1.0.0"),
    "act_editor":         EditorVersion("act_editor",         "TKAct.dat 精灵动画编辑器",        "1.0.0"),
    "wardata_editor":     EditorVersion("wardata_editor",     "WarData.dat 战场数据编辑器",      "1.0.0"),
    "gxp_editor":         EditorVersion("gxp_editor",         "GXP 图像编辑器",                  "1.0.0"),
    "spritesheet_editor": EditorVersion("spritesheet_editor", "精灵表编辑器",                    "1.0.0"),
    "save_editor":        EditorVersion("save_editor",        "TKS 存档编辑器",                  "1.0.0"),
    "configs_editor":     EditorVersion("configs_editor",     "TKS Configs Editor",              "1.0.0"),
    "launcher":           EditorVersion("launcher",           "TKS Mod Launcher",                "1.0.0"),
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

    Args:
        app_id: 编辑器唯一标识
        subtitle: 副标题 (如文件名), None 表示无副标题

    Returns:
        无副标题: "{app_name} v{version}"
        有副标题: "{app_name} v{version} — {subtitle}"
    """
    v = get_version(app_id)
    base = f"{v.app_name} v{v.version}"
    if subtitle:
        return f"{base} — {subtitle}"
    return base


def get_build_date() -> str:
    """获取构建日期 (打包时由 build_all.py 注入)"""
    return BUILD_DATE


def format_about_header(app_id: str) -> str:
    """格式化"关于"对话框的标题行 (含版本号与构建日期)

    Returns:
        "{app_name} v{version}\\n构建日期: {BUILD_DATE}"
    """
    v = get_version(app_id)
    return f"{v.app_name} v{v.version}\n构建日期: {BUILD_DATE}"
