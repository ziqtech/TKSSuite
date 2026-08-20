"""单次启动任务的不可变输入快照。"""
from dataclasses import dataclass
from typing import FrozenSet


@dataclass(frozen=True)
class LaunchContext:
    exe_path: str
    game_dir: str
    mode: str = "standard"
    selected_patches: FrozenSet[str] = frozenset()
    enabled_mod_ids: FrozenSet[str] = frozenset()
    selected_tool: str = ""

    def normalized(self) -> "LaunchContext":
        mode = self.mode if self.mode in {"standard", "compatible"} else "standard"
        return LaunchContext(
            exe_path=self.exe_path,
            game_dir=self.game_dir,
            mode=mode,
            selected_patches=frozenset(self.selected_patches),
            enabled_mod_ids=frozenset(self.enabled_mod_ids),
            selected_tool=self.selected_tool,
        )
