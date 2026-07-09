"""
editor_utils — 编辑器公共模块 (10 个模块)

UI 层:
  - theme_manager:    QSS 主题加载/切换 (ThemeManager)
  - window_theme:     Windows DWM 标题栏颜色 (apply_godot_theme)
  - dock_components:  Godot 风格 Dock 面板 (DockHeader, create_dock)
  - ui_helpers:       路径标签/输入框/图标/CSV/确认退出/弹窗标题栏主题过滤器
  - picker_dialogs:   TKT ID 选择器对话框 (TktPickerDialog)
  - mod_exporter:     统一 .tksmod MOD 导出 (差异算法/打包/元数据对话框)

数据层:
  - lzss:             统一 LZSS 压缩/解压 (DAT/Save/Stream 三种格式)
  - tkt_loader:       统一 TKT.dat 文本加载 (simple/full/raw 三种模式)
  - rgb565:           RGB565 ↔ RGBA 颜色转换 (供 GRP/GXP 使用)

初始化:
  - app_init:         打包/开发环境路径抽象 + 翻译器/图标帮助函数
"""
