"""pyttsx3 (Windows SAPI5) backend.

pyttsx3 is awkward to stop mid-sentence and must not be driven from two
threads at once, so all engine work happens on one dedicated worker thread
and `stop()` is the only cross-thread call (blueprint section 11).
"""

from __future__ import annotations

import queue
import threading

from .base import TTSBackend


class Pyttsx3Backend(TTSBackend):
    def __init__(self, voice: str | None = None):
        self._q: queue.Queue = queue.Queue()
        self._speaking = threading.Event()
        self._ready = threading.Event()
        self._voice = voice
        self._thread = threading.Thread(target=self._run, name="pyttsx3-worker", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("pyttsx3 worker did not start")

    # -- worker thread -----------------------------------------------------
    def _run(self) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        if self._voice:
            engine.setProperty("voice", self._voice)
        default_rate = engine.getProperty("rate")
        self._engine = engine
        self._ready.set()

        while True:
            item = self._q.get()
            if item is None:
                break
            text, rate = item
            self._engine.setProperty("rate", rate if rate else default_rate)
            self._engine.say(text)
            try:
                self._engine.runAndWait()
            except Exception:
                # engine.stop() interrupts runAndWait; pause flushes raise too.
                pass
            finally:
                try:
                    self._engine.stop()
                except Exception:
                    pass
                self._speaking.clear()

    # -- TTSBackend ---------------------------------------------------------
    def start_speak(self, text: str, rate_wpm: int) -> None:
        self._speaking.set()
        self._q.put((text, rate_wpm))

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def stop(self) -> None:
        engine = getattr(self, "_engine", None)
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass

    def close(self) -> None:
        self._q.put(None)
