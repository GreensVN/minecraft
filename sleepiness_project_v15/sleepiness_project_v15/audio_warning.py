"""
audio_warning.py — Cảnh báo âm thanh đa tầng (v17).

CHANGELOG v17:
    [FIX]  Defer pygame.mixer init: trước đây init ngay khi import → side
           effect trên headless server / CI. Nay chỉ init khi AudioWarner()
           đầu tiên được tạo.
    [NEW]  AudioWarner.test(): phát thử cấp 1 + 2 cho CLI debug.

CHANGELOG v16:
    [FIX]      Python 3.8 compat (Dict thay dict).
    [FIX]      pgm.quit() → pgm.stop().
    [FIX]      get_warner() thread-safe.
    [NEW]      set_volume, set_mute, toggle_mute, is_available.

Backends:
  1. pygame.mixer
  2. winsound (Windows fallback)
  3. silent
"""

import logging
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_BACKEND: str = "silent"
_BACKEND_LOCK = threading.Lock()
_BACKEND_INIT_DONE = False


def _ensure_backend() -> str:
    """[v17] Defer init đến lần đầu cần dùng (không side-effect lúc import)."""
    global _BACKEND, _BACKEND_INIT_DONE
    if _BACKEND_INIT_DONE:
        return _BACKEND
    with _BACKEND_LOCK:
        if _BACKEND_INIT_DONE:
            return _BACKEND
        try:
            import pygame.mixer as _pgmixer
            _pgmixer.pre_init(frequency=44100, size=-16, channels=1, buffer=512)
            _pgmixer.init()
            _BACKEND = "pygame"
            logger.info("[Audio] Backend: pygame.mixer")
        except Exception:
            try:
                import winsound  # noqa: F401
                _BACKEND = "winsound"
                logger.info("[Audio] Backend: winsound (Windows fallback)")
            except ImportError:
                logger.warning(
                    "[Audio] Không có pygame/winsound. Cảnh báo âm thanh TẮT."
                )
                _BACKEND = "silent"
        _BACKEND_INIT_DONE = True
    return _BACKEND


def _make_beep_buffer(
    freq_hz: float,
    duration_sec: float,
    amplitude: float = 0.4,
    sample_rate: int = 44100,
    fade_ms: int = 10,
):
    import numpy as np
    n = int(sample_rate * duration_sec)
    t = np.linspace(0, duration_sec, n, endpoint=False)
    wave = (amplitude * np.sin(2 * np.pi * freq_hz * t) * 32767).astype(np.int16)
    fade_samples = int(sample_rate * fade_ms / 1000)
    if fade_samples > 0 and 2 * fade_samples < n:
        ramp = np.linspace(0, 1, fade_samples)
        wave[:fade_samples]  = (wave[:fade_samples]  * ramp).astype(np.int16)
        wave[-fade_samples:] = (wave[-fade_samples:] * ramp[::-1]).astype(np.int16)
    return wave


def _make_alarm_buffer(sample_rate: int = 44100):
    import numpy as np
    lo = _make_beep_buffer(800,  0.5, amplitude=0.6, sample_rate=sample_rate)
    hi = _make_beep_buffer(1200, 0.5, amplitude=0.6, sample_rate=sample_rate)
    return np.concatenate([lo, hi])


class AudioWarner:
    """Phát cảnh báo non-blocking với cooldown chống spam."""

    _COOLDOWN = {1: 3.0, 2: 1.5}

    def __init__(self):
        self._backend = _ensure_backend()
        self._lock    = threading.Lock()
        self._last_played: Dict[int, float] = {1: 0.0, 2: 0.0}
        self._channel1: Optional[object] = None
        self._channel2: Optional[object] = None
        self._volume: float = 1.0
        self._muted:  bool  = False

        if self._backend == "pygame":
            self._init_pygame_sounds()

    @property
    def is_available(self) -> bool:
        return self._backend != "silent"

    def _init_pygame_sounds(self) -> None:
        try:
            import pygame.mixer as pgm
            import pygame.sndarray as sndarray

            buf1 = _make_beep_buffer(600, 0.3, amplitude=0.35)
            self._sound1 = sndarray.make_sound(buf1)
            buf2 = _make_alarm_buffer()
            self._sound2 = sndarray.make_sound(buf2)

            self._channel1 = pgm.Channel(0)
            self._channel2 = pgm.Channel(1)
            self._channel1.set_volume(self._volume)
            self._channel2.set_volume(self._volume)
            logger.info("[Audio] Pygame sounds sẵn sàng (2 kênh).")
        except Exception as e:
            logger.warning(f"[Audio] Không init pygame sounds: {e}")
            self._backend = "silent"

    def warn(self, level: int) -> None:
        """Phát cảnh báo theo cấp độ (non-blocking)."""
        if level == 0 or self._backend == "silent" or self._muted:
            return
        now = time.monotonic()
        cooldown = self._COOLDOWN.get(level, 2.0)
        with self._lock:
            if now - self._last_played.get(level, 0.0) < cooldown:
                return
            self._last_played[level] = now
        threading.Thread(target=self._play, args=(level,), daemon=True).start()

    def _play(self, level: int) -> None:
        try:
            if self._backend == "pygame":
                self._play_pygame(level)
            elif self._backend == "winsound":
                self._play_winsound(level)
        except Exception as e:
            logger.debug(f"[Audio] Lỗi phát cấp {level}: {e}")

    def _play_pygame(self, level: int) -> None:
        if level == 1 and self._channel1 and hasattr(self, "_sound1"):
            if not self._channel1.get_busy():
                self._channel1.play(self._sound1)
        elif level == 2 and self._channel2 and hasattr(self, "_sound2"):
            self._channel2.play(self._sound2, loops=1)

    def _play_winsound(self, level: int) -> None:
        import winsound
        if level == 1:
            winsound.Beep(600, 300)
        elif level == 2:
            for freq in (800, 1200, 800, 1200):
                winsound.Beep(freq, 250)

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))
        if self._backend == "pygame":
            if self._channel1: self._channel1.set_volume(self._volume)
            if self._channel2: self._channel2.set_volume(self._volume)

    def set_mute(self, muted: bool) -> None:
        self._muted = bool(muted)
        if muted and self._backend == "pygame":
            try:
                if self._channel1: self._channel1.stop()
                if self._channel2: self._channel2.stop()
            except Exception:
                pass

    def toggle_mute(self) -> bool:
        self.set_mute(not self._muted)
        return self._muted

    @property
    def muted(self) -> bool:
        return self._muted

    def test(self) -> None:
        """[v17] Phát thử cấp 1 rồi cấp 2 (block ~3s) cho CLI debug."""
        logger.info("[Audio] Test cấp 1 (bíp nhẹ) ...")
        self.warn(1)
        time.sleep(1.0)
        self._last_played[2] = 0.0
        logger.info("[Audio] Test cấp 2 (còi hú) ...")
        self.warn(2)
        time.sleep(2.0)

    def close(self) -> None:
        if self._backend == "pygame":
            try:
                import pygame.mixer as pgm
                pgm.stop()
            except Exception:
                pass
        logger.info("[Audio] AudioWarner đã đóng.")


# ─── Thread-safe singleton ────────────────────────────────────────────────────

_default_warner: Optional[AudioWarner] = None
_singleton_lock = threading.Lock()


def get_warner() -> AudioWarner:
    global _default_warner
    if _default_warner is None:
        with _singleton_lock:
            if _default_warner is None:
                _default_warner = AudioWarner()
    return _default_warner


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    w = get_warner()
    print(f"Backend: {w._backend}  available={w.is_available}")
    w.test()
    w.close()
