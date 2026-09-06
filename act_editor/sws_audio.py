"""act_editor 音效层 — SWS 音效包解析 + MCI 播放 (T16 自 act_editor.py 迁出)。"""
import os
import struct
import sys

# ============================================================
# 音效播放 (Windows MCI + SWS.GRP 资源包)
#   sub_451780 关键逻辑 (L48-61):
#     if dword_A2C22C == 1:
#         sub_4B22A8(*(+28), *(+16)+4*v19, 0)   # 从 GRP 资源包按 sid 取
#     elif dword_A2C22C == 0:
#         sub_4B2ECC(..., "sound\\%04d.wav", v19)  # 文件路径 fallback
# ============================================================
_mci_alias_counter = [0]
_sws_tempfiles = []


class _SWSGrp:
    """SWS.GRP 音效资源包最小读取器 (按需流式读取, 不一次性载入).
    get_wav(sid) → 返回原始 WAV 字节或 None.
    extract_to_temp(sid) → 写到临时 .wav 文件供 MCI 播放, 返回路径或 None.
    """

    def __init__(self, grp_path, idx_path):
        self.grp_path = grp_path
        self.idx_path = idx_path
        self.offsets = []
        self._wav_cache = {}
        self._temp_cache = {}

    def load_index(self):
        with open(self.idx_path, 'rb') as f:
            data = f.read()
        if len(data) < 8 or len(data) % 4:
            return 0
        self.offsets = [struct.unpack_from('<I', data, i)[0]
                       for i in range(0, len(data), 4)]
        try:
            grp_sz = os.path.getsize(self.grp_path)
        except OSError:
            return 0
        if not self.offsets or self.offsets[-1] != grp_sz:
            self.offsets = []
            return 0
        return self.section_count

    @property
    def section_count(self):
        return max(0, len(self.offsets) - 1)

    def get_wav(self, sid):
        if sid < 0 or sid >= self.section_count:
            return None
        cached = self._wav_cache.get(sid)
        if cached is not None:
            return cached
        start = self.offsets[sid]
        end = self.offsets[sid + 1]
        if end <= start:
            return None
        try:
            with open(self.grp_path, 'rb') as f:
                f.seek(start)
                data = f.read(end - start)
        except OSError:
            return None
        if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
            return None
        if len(self._wav_cache) < 32:
            self._wav_cache[sid] = data
        return data

    def extract_to_temp(self, sid):
        if sid in self._temp_cache and os.path.exists(self._temp_cache[sid]):
            return self._temp_cache[sid]
        data = self.get_wav(sid)
        if not data:
            return None
        import tempfile
        fd, path = tempfile.mkstemp(prefix=f'tkact_sws_{sid:04d}_',
                                     suffix='.wav')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
        except OSError:
            return None
        self._temp_cache[sid] = path
        _sws_tempfiles.append(path)
        return path

    def wav_info(self, sid):
        data = self.get_wav(sid)
        if not data:
            return None
        try:
            import io as _io
            import wave as _wave
            with _wave.open(_io.BytesIO(data), 'rb') as wf:
                nf = wf.getnframes()
                sr = wf.getframerate()
                return (wf.getnchannels(), sr, wf.getsampwidth() * 8,
                        nf / sr if sr > 0 else 0.0)
        except Exception:
            return None


def _mci_send(cmd):
    """winmm.dll mciSendStringW 包装; 失败返回 (errno, err_msg)"""
    if sys.platform != 'win32':
        return (-1, 'not-windows')
    try:
        import ctypes
        winmm = ctypes.windll.winmm
        rc = winmm.mciSendStringW(ctypes.c_wchar_p(cmd), None, 0, None)
        if rc != 0:
            buf = ctypes.create_unicode_buffer(256)
            winmm.mciGetErrorStringW(rc, buf, 256)
            return (rc, buf.value)
        return (0, '')
    except Exception as e:
        return (-1, str(e))


def _mci_play_async(path):
    """异步播放 wav 文件, 返回 alias; 失败返回 None"""
    if not path or not os.path.exists(path):
        return None
    _mci_alias_counter[0] += 1
    alias = f"tkact_snd_{_mci_alias_counter[0]}"
    _mci_send(f'close {alias}')
    rc, msg = _mci_send(f'open "{path}" type waveaudio alias {alias}')
    if rc != 0:
        rc, msg = _mci_send(f'open "{path}" alias {alias}')
        if rc != 0:
            return None
    rc, msg = _mci_send(f'play {alias}')
    if rc != 0:
        _mci_send(f'close {alias}')
        return None
    return alias


def _mci_close(alias):
    if alias:
        _mci_send(f'stop {alias}')
        _mci_send(f'close {alias}')


def _cleanup_sws_tempfiles():
    for p in list(_sws_tempfiles):
        try:
            if os.path.exists(p):
                os.unlink(p)
        except OSError:
            pass
    _sws_tempfiles.clear()


# ------------------------------------------------------------
# JVG 按需加载器 (只解码当前条目引用的块, 不加载全量 40MB+347MB)
# ------------------------------------------------------------
