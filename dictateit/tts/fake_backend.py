"""Dry-run backend: records utterances instead of speaking.

Used by the test-suite and by `main.py --dry-run` to exercise the whole
dictation flow without audio hardware.
"""

from __future__ import annotations

import threading

from .base import TTSBackend


class FakeBackend(TTSBackend):
    def __init__(self, speaking_seconds: float = 0.0):
        self.utterances: list[tuple[str, int]] = []
        self.stopped = 0
        self._speaking = threading.Event()
        self._speaking_seconds = speaking_seconds

    def start_speak(self, text: str, rate_wpm: int) -> None:
        self.utterances.append((text, rate_wpm))
        if self._speaking_seconds > 0:
            self._speaking.set()
            threading.Timer(self._speaking_seconds, self._speaking.clear).start()

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def stop(self) -> None:
        self.stopped += 1
        self._speaking.clear()
