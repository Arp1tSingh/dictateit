"""Piper backend: offline neural voices (blueprint section 6, v2).

Requires `pip install piper-tts` and a voice model (a `.onnx` file plus
its `.onnx.json` sidecar; download from the Piper voices release page).
Both dependencies are checked lazily so the rest of the app never
imports onnxruntime unless Piper is actually selected.

The worker thread renders each utterance to WAV, then plays it through
AudioPlayer (winsound/sounddevice). Synthesis latency (~0.1-0.3 s per
phrase) is hidden by the engine's non-blocking start_speak contract.
"""

from __future__ import annotations

import queue
import threading

from .audio_play import AudioPlayer, piper_length_scale
from .base import BackendUnavailable, TTSBackend


class PiperBackend(TTSBackend):
    def __init__(self, voice_path: str = "", length_scale_base: float = 1.0):
        self._q: queue.Queue = queue.Queue()
        self._speaking = threading.Event()
        self._player = AudioPlayer()
        self._voice_path = voice_path
        self._length_scale_base = length_scale_base
        self._voice = None

        try:
            from piper import PiperVoice  # noqa: F401  (lazy dependency)
        except Exception as e:
            raise BackendUnavailable(
                "piper-tts is not installed (pip install piper-tts); "
                "falling back is recommended") from e

        if not voice_path:
            raise BackendUnavailable(
                "piper voice model not configured (audio.piper_voice); "
                "point it at a downloaded .onnx voice file")
        self._thread = threading.Thread(target=self._run, name="piper-worker",
                                        daemon=True)
        self._thread.start()

    # -- worker thread -----------------------------------------------------
    def _run(self) -> None:
        from piper import PiperVoice

        self._voice = PiperVoice.load(self._voice_path)
        while True:
            item = self._q.get()
            if item is None:
                break
            text, rate_wpm = item
            try:
                self._synthesize(text, rate_wpm)
            except Exception:
                pass  # a failed utterance must not kill the worker
            finally:
                self._speaking.clear()

    def _synthesize(self, text: str, rate_wpm: int) -> None:
        """Render to WAV and play; blocks until playback ends (worker thread)."""
        import io
        import wave

        from piper import SynthesisConfig  # type: ignore

        config = SynthesisConfig(
            length_scale=piper_length_scale(rate_wpm) * self._length_scale_base)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file, syn_config=config)
        data = buf.getvalue()
        self._player.play_wav(data)
        while self._player.is_playing():
            if self._cancelled:
                return
            threading.Event().wait(0.03)

    # -- TTSBackend ---------------------------------------------------------
    def start_speak(self, text: str, rate_wpm: int) -> None:
        self._cancelled = False
        self._speaking.set()
        self._q.put((text, rate_wpm))

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def stop(self) -> None:
        self._cancelled = True
        self._player.stop()
        self._speaking.clear()

    def close(self) -> None:
        self.stop()
        self._q.put(None)
