"""
面板注册表 — 新增配置类型时在此添加面板类即可。
"""
from .drop_probability_panel import DropProbabilityPanel
from .equip_type_labels_panel import EquipTypeLabelsPanel
from .summon_table_panel import SummonTablePanel
from .font_config_panel import FontConfigPanel
from .animation_speed_panel import AnimationSpeedPanel

PANEL_REGISTRY = [
    DropProbabilityPanel,
    EquipTypeLabelsPanel,
    SummonTablePanel,
    FontConfigPanel,
    AnimationSpeedPanel,
]
