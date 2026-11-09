"""Neural backend tests: pure helpers and graceful unavailability.

No audio is played and no network is touched; piper-tts / edge-tts /
miniaudio are optional dependencies that are absent in CI, so the
backends must raise BackendUnavailable cleanly.
"""

import importlib.util
import io
import time
import wave

import pytest

from dictateit.settings import Settings
from dictateit.tts.audio_play import (
    AudioPlayer, edge_rate_percent, piper_length_scale, wav_duration,
    wav_from_pcm,
)
from dictateit.tts.base import BackendUnavailable, create_backend


def make_wav(seconds: float, rate: int = 8000) -> bytes:
    """A real (silent) WAV for duration tests."""
    frames = b"\x00\x00" * int(rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


class TestRateConversion:
    def test_piper_length_scale_inverse(self):
        # baseline: 190 wpm -> scale 1.0; slower rate -> bigger scale
        assert piper_length_scale(190) == pytest.approx(1.0)
        assert piper_length_scale(95) == pytest.approx(2.0)
        assert piper_length_scale(380) == pytest.approx(0.5)

    def test_piper_clamped(self):
        assert piper_length_scale(60) == 2.5     # can't slow past 2.5
        assert piper_length_scale(10**6) == 0.5  # can't speed past 0.5

    def test_edge_percent_format(self):
        assert edge_rate_percent(190) == "+0%"
        assert edge_rate_percent(209) == "+10%"
        assert edge_rate_percent(95) == "-50%"

    def test_edge_clamped(self):
        assert edge_rate_percent(60) == "-68%"   # floor 60 wpm
        assert edge_rate_percent(10**6) == "+100%"


class TestWavHelpers:
    def test_duration(self):
        assert wav_duration(make_wav(1.0)) == pytest.approx(1.0, abs=1e-3)
        assert wav_duration(make_wav(0.25, rate=22050)) == pytest.approx(
            0.25, abs=1e-3)

    def test_duration_of_garbage(self):
        assert wav_duration(b"not a wav") == 0.0

    def test_pcm_roundtrip(self):
        pcm = b"\x00\x00" * 8000                    # 1 s of 8 kHz silence
        wav = wav_from_pcm(pcm, rate=8000, channels=1)
        assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
        assert wav_duration(wav) == pytest.approx(1.0, abs=1e-3)


class TestAudioPlayer:
    def test_idle(self):
        player = AudioPlayer()
        assert player.is_playing() is False
        player.close()

    def test_playing_state_estimates_duration(self):
        player = AudioPlayer()
        if player._backend == "none":
            pytest.skip("no audio backend on this machine")
        wav = make_wav(0.35)
        if player._backend == "winsound":
            # actually plays on Windows; very short quiet beep-free silence
            player.play_wav(wav)
            assert player.is_playing() is True
            time.sleep(0.45)
            assert player.is_playing() is False
        player.close()

    def test_stop_when_idle_safe(self):
        player = AudioPlayer()
        player.stop()
        player.close()


def make_settings(**overrides) -> Settings:
    settings = Settings()
    settings.set("audio.piper_voice", "voices/x.onnx")
    settings.set("audio.edge_voice", "en-GB-RyanNeural")
    for key, value in overrides.items():
        settings.set(key, value)
    return settings


class TestBackendFactory:
    def test_unknown_backend(self):
        with pytest.raises(BackendUnavailable):
            create_backend("bogus", None)

    def test_fake_always_available(self):
        from dictateit.tts.fake_backend import FakeBackend

        assert isinstance(create_backend("fake", None), FakeBackend)

    def test_piper_unavailable_cleanly(self):
        if importlib.util.find_spec("piper") is not None:
            pytest.skip("piper installed; cannot test its absence")
        with pytest.raises(BackendUnavailable):
            create_backend("piper", make_settings())

    def test_edge_unavailable_cleanly(self):
        if importlib.util.find_spec("edge_tts") is not None:
            pytest.skip("edge-tts installed; cannot test its absence")
        with pytest.raises(BackendUnavailable):
            create_backend("edge", make_settings())
