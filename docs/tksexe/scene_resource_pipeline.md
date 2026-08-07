# 场景 / 地图 / 音乐资源管线

> 覆盖 `SC.GRP`、`WSC.GRP`、`SWS.GRP`、`SSF.GRP`、`SMG.GRP`、`Sound/*.mp3` 与 `ChangeScene` 的资源加载链。

## 1. 资源包

| 包 | 区段数 | 内容 |
| --- | --- | --- |
| `SC.GRP` + `SC.IDX` | 214 | 主场景背景图，section 0 为大地图 |
| `WSC.GRP` + `WSC.IDX` | 83 | 战斗/特殊场景背景 |
| `SWS.GRP` + `SWS.IDX` | 506 | 战斗音效 WAV |
| `SSF.GRP` + `SSF.IDX` | 63 | 通用音效 WAV，被 `PlaySound` 引用 |
| `SMG.GRP` + `SMG.IDX` | 21 | 备用 BGM WAV |
| `Sound/*.mp3` | 29 | 主要 BGM，`SetMusic`/`PlayMusic` 使用 |

## 2. 加载链

```text
ChangeScene(scene_id, x, y, dir)
  -> sub_40C044
  -> sub_402B88: SC.GRP 场景贴图
  -> sub_405CBC: 实体排序/精灵初始化
  -> sub_402E88: 实体放置
  -> byte_755B74[scene_id] -> Sound/%04d.mp3
```

## 3. 场景与 BGM

- `SetMusic(scene_id, music_id)` 写入 `byte_755B74`。
- `ChangeScene` 时读取该表播放对应 MP3。
- `PlayMusic` 直接播放，不写场景绑定。
- 部分场景无显式绑定，由进入前场景或引擎内部默认处理。

## 4. 关键函数

| 地址 | 函数 | 职责 |
| --- | --- | --- |
| `0x0040C044` | ChangeScene | 场景切换入口 |
| `0x00402B88` | LoadMap | 从 SC.GRP 加载场景贴图 |
| `0x00405600` 系列 | LoadGRP | GRP/IDX 资源包加载 |
| `0x0044AC50` | PlayMP3 | BGM 加载/播放 |
| `0x00451780` | PlayWAV | 音效加载/播放 |

## 5. 已知局限

- 已确认：`scene_id` 直接索引 `SC.IDX`，对应 `SC.GRP` 区段；完整映射见 [scene_grp_mapping.md](scene_grp_mapping.md)。
- `WSC.GRP` 由 `sub_402BB8 -> sub_42FA50` 使用，不参与 `ChangeScene` 场景背景；索引由 `WarData.map_id` 提供，见 [wsc_grp_mapping.md](wsc_grp_mapping.md)。
- 部分场景的 BGM 由剧情动态切换，如李府区域 0006 -> 0014。

## 6. 参考

- [`逆向工作区/docs/08_渲染与资源管线/场景地图BGM资源关系.md`](../../../逆向工作区/docs/08_渲染与资源管线/场景地图BGM资源关系.md)
- [`逆向工作区/docs/08_渲染与资源管线/渲染与资源管线.md`](../../../逆向工作区/docs/08_渲染与资源管线/渲染与资源管线.md)
- [`resource_formats.md`](resource_formats.md)
