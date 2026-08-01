# -*- coding: utf-8 -*-
"""TKS 游戏音频 1:1 复刻 — 点击音效 (SSF.GRP WAV) + 背景音乐 (Sound\\XXXX.mp3)

逆向证据 (反编译产物/decompile):
  sub_451C38 — 播放音效: SSF.GRP 音轨 (PCM WAV 22050Hz 16bit 立体声);
               开关 = a1[22] = dword_A2C228 (= word_755C74, 系统页第二行)
  sub_451DF8 — 音效音量: 212*(5-vol), vol 1..5 → 848/636/424/212/0 (a1[6] 保存)
  sub_44AC50 — 加载 BGM: sprintf(a1+20, "sound\\%04d.mp3", id) + sub_44A8D8
  sub_44AC90 — BGM 播放/循环 (a2==1 循环); 0000.mp3 = 标题/菜单 BGM (sub_412BE8)
  sub_44ACE8 — BGM 停止 (定时器容器 uIDEvent: +4 播放器对象)
  sub_44AD18 — BGM 音量: 212*(5-vol) (系统页第一行 word_755C7A)
  sub_41FAAC — 系统页交互 case 5: 第一行(y=97-129)=BGM 开关/音量 (word_755C78/7A),
               第二行(y=164-198)=音效 开关/音量 (word_755C74/76, 仅状态+sub_451DF8)

注: 图鉴沿用旧命名 _se_*(第一行)/_bgm_*(第二行), 语义按游戏源码:
    第一行 = BGM(mp3) 控制, 第二行 = 音效(WAV) 控制。
"""
import os
import struct
import tempfile

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect

# 游戏音量 1-5 → DirectSound SetVolume 值 → Qt 线性 0..1
# (sub_41FAAC/41103C 公式化简 = -300*(5-vol) 百分之一分贝:
#   vol=5 → 0dB 最大, vol=1 → -12dB 最小; 滑块: 左=vol1 小, 右=vol5 大)
def _game_vol(vol):
    """游戏音量档 1..5 → Qt 音量 0..1 (vol=5 最大, vol=1 最小)"""
    v = max(1, min(5, int(vol)))
    db = -300 * (5 - v) / 100.0   # 百分之一分贝 → 分贝 (-12/-9/-6/-3/0)
    return 10 ** (db / 20.0)


class GameAudio(QObject):
    """TKS 音频复刻: 点击音效 (SSF.GRP 音轨) + BGM (Sound mp3 循环)。

    资源挂 GameData 缓存, 跨角色视图重建复用; 缺资源/无音频设备时静默降级。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sfx_cache = {}      # sfx_id → QSoundEffect (SSF.GRP 音轨, sub_451C38)
        self._bgm = None          # QMediaPlayer: 0000.mp3 循环 (sub_412BE8)
        self._bgm_out = None
        self._cache_dir = ""
        self._ssf_grp = ""       # SSF.GRP 路径 (按需提取音轨)
        self._ssf_idx = ""
        # 游戏状态 (sub_411624 初值: word_755C74=1, 76=3, 78=1, 7A=2)
        # 第二行 (音效): word_755C74 开关 / word_755C76 音量
        self._sfx_on = True
        self._sfx_vol = 3
        # 第一行 (BGM): word_755C78 开关 / word_755C7A 音量
        self._bgm_on = True
        self._bgm_vol = 2
        self._loaded = False
    
    # ── 加载 ──
    
    def load(self, game_dir):
        """加载游戏目录音频资源: SSF.GRP 音轨 (WAV) + Sound\0000.mp3 (BGM)
    
        音效 ID (机器码 edx 实证, Borland fastcall): 3=头像行/翻页, 4=页签/系统页,
        6=列表行/存档按钮, 7=分类/槽/焦点/队伍, 8=标题界面, 1=系统页离开。
        """
        try:
            self._cache_dir = os.path.join(tempfile.gettempdir(), "tks_book_audio")
            os.makedirs(self._cache_dir, exist_ok=True)
            self._ssf_grp = os.path.join(game_dir, "SSF.GRP")
            self._ssf_idx = os.path.join(game_dir, "SSF.IDX")
            mp3 = os.path.join(game_dir, "Sound", "0000.mp3")
            if os.path.exists(mp3):
                self._bgm_out = QAudioOutput(self)
                self._bgm = QMediaPlayer(self)
                self._bgm.setAudioOutput(self._bgm_out)
                self._bgm.setSource(QUrl.fromLocalFile(mp3))
                self._bgm.setLoops(QMediaPlayer.Loops.Infinite)
            self._loaded = True
        except Exception:
            self._loaded = False

    @staticmethod
    def _extract_track(grp_path, idx_path, track_id):
        """从 GRP 包提取第 track_id 轨原始数据到缓存 (sub_451600 加载的包)"""
        with open(idx_path, 'rb') as f:
            idx = f.read()
        off0 = struct.unpack_from('<I', idx, track_id * 4)[0]
        off1 = struct.unpack_from('<I', idx, (track_id + 1) * 4)[0]
        with open(grp_path, 'rb') as f:
            f.seek(off0)
            data = f.read(off1 - off0)
        if data[:4] != b'RIFF':
            return None
        out = os.path.join(tempfile.gettempdir(), "tks_book_audio",
                           f"sfx{track_id:04d}.wav")
        with open(out, 'wb') as f:
            f.write(data)
        return out

    # ── 音效 (SSF 包, sub_451C38) ──

    def play_sfx(self, sfx_id=0):
        """播放音效 (sub_451C38): 受第二行开关 word_755C74 (a1[22]) 控制。

        sfx_id = SSF.GRP 音轨号 (机器码 edx 实证); 按需提取缓存 QSoundEffect。
        """
        if not self._loaded or not self._sfx_on:   # 游戏: a1[22] = dword_A2C228
            return
        if sfx_id not in self._sfx_cache:
            wav = self._extract_track(self._ssf_grp, self._ssf_idx, sfx_id)
            if not wav:
                return
            e = QSoundEffect(self)
            e.setSource(QUrl.fromLocalFile(wav))
            self._sfx_cache[sfx_id] = e
        e = self._sfx_cache[sfx_id]
        e.setVolume(_game_vol(self._sfx_vol))
        e.play()

    def set_sfx_enabled(self, on):
        """第二行 (音效) 开关 (word_755C74 → dword_A2C228)"""
        self._sfx_on = bool(on)

    def set_sfx_volume(self, vol):
        """第二行 (音效) 音量 1-5 (word_755C76 → sub_451DF8)"""
        self._sfx_vol = max(1, min(5, int(vol)))

    # ── BGM (Sound mp3, sub_44AC50/44AC90/44ACE8/44AD18) ──

    def start_bgm(self):
        """播放 BGM 循环 (sub_412BE8: sub_44AC50(&ppv,0)+sub_44AC90(&ppv,1))"""
        if not self._loaded or self._bgm is None:
            return
        if not self._bgm_on:          # 第一行开关 (word_755C78)
            return
        if self._bgm.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._bgm.play()

    def stop_bgm(self):
        """停止 BGM (sub_44ACE8)"""
        if self._bgm is not None:
            self._bgm.stop()

    def set_bgm_enabled(self, on):
        """第一行 (BGM) 开关 (word_755C78): 仅记录状态。

        播放由 start_bgm 触发 (标题界面进入时, 对齐 sub_412BE8); 关闭时停止。
        """
        self._bgm_on = bool(on)
        if not on and self._bgm is not None:
            self._bgm.stop()

    def set_bgm_volume(self, vol):
        """第一行 (BGM) 音量 1-5 (word_755C7A → sub_44AD18)"""
        self._bgm_vol = max(1, min(5, int(vol)))
        if self._bgm_out is not None:
            self._bgm_out.setVolume(_game_vol(self._bgm_vol))

    def close(self):
        """释放音频 (离开图鉴时)"""
        if self._bgm is not None:
            self._bgm.stop()
            self._bgm = None
        self._sfx_cache.clear()
