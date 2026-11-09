"""Audio playback shared by the neural backends.

The neural backends produce audio data (Piper: WAV, edge-tts: MP3), so
playback is ours to drive. Windows route: `winsound` (stdlib, SND_ASYNC).
Elsewhere: `sounddevice` if installed. Both poll an estimated duration —
`winsound` has no done-callback, and the estimate is good enough for a
dictation gap.

MP3 (edge-tts) is decoded to PCM with `miniaudio` when available; PCM is
then wrapped into a WAV container so one playback route serves both.
"""

from __future__ import annotations

import io
import threading
import time
import wave

# spoken words per minute the neural voices were trained at
BASE_WPM = 190


def wav_duration(wav_bytes: bytes) -> float:
    """Seconds of audio in a WAV container (0.0 if unparseable)."""
    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            return w.getnframes() / max(1, w.getframerate())
    except Exception:
        return 0.0


def wav_from_pcm(pcm: bytes, rate: int, channels: int = 1, bits: int = 16) -> bytes:
    """Wrap raw PCM bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def pcm_from_mp3(mp3_bytes: bytes) -> tuple[bytes, int, int]:
    """Decode MP3 to (pcm_bytes, sample_rate, channels) via miniaudio."""
    import miniaudio  # lazy: optional

    decoded = miniaudio.decode(mp3_bytes)
    return decoded.samples.tobytes(), decoded.sample_rate, decoded.nchannels


def piper_length_scale(rate_wpm: int) -> float:
    """WPM -> Piper's length_scale (bigger = slower). Clamped."""
    scale = BASE_WPM / max(60, rate_wpm)
    return min(2.5, max(0.5, scale))


def edge_rate_percent(rate_wpm: int) -> str:
    """WPM -> edge-tts rate string like '+12%' / '-30%'. Clamped."""
    percent = round((max(60, rate_wpm) / BASE_WPM - 1) * 100)
    percent = min(100, max(-100, percent))
    return f"{percent:+d}%"


class AudioPlayer:
    """Non-blocking WAV playback with a duration-estimate is_playing()."""

    def __init__(self):
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._duration = 0.0
        self._cancelled = False
        self._backend = self._pick_backend()

    @staticmethod
    def _pick_backend() -> str:
        try:
            import sounddevice  # noqa: F401

            return "sounddevice"
        except Exception:
            pass
        import sys

        return "winsound" if sys.platform == "win32" else "none"

    def play_wav(self, wav_bytes: bytes) -> None:
        """Start playing; returns immediately."""
        with self._lock:
            self._cancelled = False
            self._duration = wav_duration(wav_bytes)
            if self._duration <= 0:
                return
            try:
                if self._backend == "sounddevice":
                    self._play_sounddevice(wav_bytes)
                elif self._backend == "winsound":
                    import winsound

                    winsound.PlaySound(
                        wav_bytes, winsound.SND_MEMORY | winsound.SND_ASYNC)
                self._started_at = time.monotonic()
            except Exception:
                # no audio device: continue silently rather than crash
                self._started_at = None

    def _play_sounddevice(self, wav_bytes: bytes) -> None:
        import numpy as np
        import sounddevice as sd

        with wave.open(io.BytesIO(wav_bytes)) as w:
            rate = w.getframerate()
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            frames = w.readframes(w.getnframes())
        dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sampwidth, np.int16)
        data = np.frombuffer(frames, dtype=dtype)
        if channels > 1:
            data = data.reshape(-1, channels)
        sd.play(data, rate)

    def is_playing(self) -> bool:
        with self._lock:
            if self._cancelled or self._started_at is None:
                return False
            return time.monotonic() - self._started_at < self._duration

    def stop(self) -> None:
        with self._lock:
            self._cancelled = True
            self._started_at = None
        try:
            if self._backend == "sounddevice":
                import sounddevice as sd

                sd.stop()
            elif self._backend == "winsound":
                import winsound

                winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def close(self) -> None:
        self.stop()


def wav_header_summary(wav_bytes: bytes) -> dict:
    """Rate/channels/bits for tests and debugging."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return {
            "rate": w.getframerate(),
            "channels": w.getnchannels(),
            "bits": w.getsampwidth() * 8,
            "frames": w.getnframes(),
        }


def assert_wav(data: bytes) -> bool:
    """Cheap sanity check for tests: RIFF....WAVE."""
    return len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
