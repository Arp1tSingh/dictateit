"""edge-tts backend: online neural voices (blueprint section 6, v2).

Requires `pip install edge-tts` (Microsoft Edge's online neural voices;
an internet connection is needed per utterance, ~0.3 s latency). MP3
streamed back from the service is decoded with `miniaudio`
(`pip install miniaudio`) and played through AudioPlayer.

Like Piper, dependencies are imported lazily: selecting the backend is
the only thing that pulls them in.
"""

from __future__ import annotations

import queue
import threading

from .audio_play import AudioPlayer, edge_rate_percent, wav_from_pcm
from .base import BackendUnavailable, TTSBackend


class EdgeBackend(TTSBackend):
    def __init__(self, voice: str = "en-GB-RyanNeural"):
        self._q: queue.Queue = queue.Queue()
        self._speaking = threading.Event()
        self._player = AudioPlayer()
        self._voice = voice
        self._cancelled = False

        try:
            import edge_tts  # noqa: F401  (lazy dependency)
        except Exception as e:
            raise BackendUnavailable(
                "edge-tts is not installed (pip install edge-tts)") from e

        self._thread = threading.Thread(target=self._run, name="edge-worker",
                                        daemon=True)
        self._thread.start()

    # -- worker thread -----------------------------------------------------
    def _run(self) -> None:
        import asyncio

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        while True:
            item = self._q.get()
            if item is None:
                break
            text, rate_wpm = item
            try:
                self._speak_one(text, rate_wpm)
            except Exception:
                pass  # offline / network error: skip the utterance
            finally:
                self._speaking.clear()

    def _speak_one(self, text: str, rate_wpm: int) -> None:
        import asyncio

        import edge_tts

        async def collect() -> bytes:
            communicate = edge_tts.Communicate(
                text, self._voice, rate=edge_rate_percent(rate_wpm))
            mp3 = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3.extend(chunk["data"])
            return bytes(mp3)

        mp3 = self._loop.run_until_complete(collect())
        if not mp3 or self._cancelled:
            return
        pcm, rate, channels = self._decode(mp3)
        self._player.play_wav(wav_from_pcm(pcm, rate, channels))
        while self._player.is_playing():
            if self._cancelled:
                return
            threading.Event().wait(0.03)

    @staticmethod
    def _decode(mp3: bytes) -> tuple[bytes, int, int]:
        try:
            from .audio_play import pcm_from_mp3

            return pcm_from_mp3(mp3)
        except ImportError:
            raise BackendUnavailable(
                "miniaudio is not installed (pip install miniaudio); "
                "needed to play edge-tts audio")

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
