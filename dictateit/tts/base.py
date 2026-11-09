"""TTS backend interface.

The engine drives utterances in small steps so hotkeys stay responsive:

    backend.start_speak(text, rate)   # begins speaking, returns immediately
    while backend.is_speaking(): ...  # engine polls and processes commands
    backend.stop()                    # interrupts the current utterance
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BackendUnavailable(RuntimeError):
    """Raised when a backend's dependencies or assets are missing."""


class TTSBackend(ABC):
    @abstractmethod
    def start_speak(self, text: str, rate_wpm: int) -> None:
        """Start speaking `text` at `rate_wpm` words per minute. Non-blocking."""

    @abstractmethod
    def is_speaking(self) -> bool:
        """True while an utterance is in progress."""

    @abstractmethod
    def stop(self) -> None:
        """Interrupt the current utterance. Safe when idle."""

    def close(self) -> None:
        """Release resources."""


def create_backend(name: str, settings) -> TTSBackend:
    """Factory: build a backend by name, with graceful failure."""
    if name == "pyttsx3":
        from .pyttsx3_backend import Pyttsx3Backend
        return Pyttsx3Backend(
            voice=settings.get("audio.voice"),
        )
    if name == "piper":
        from .piper_backend import PiperBackend
        return PiperBackend(
            voice_path=settings.get("audio.piper_voice", ""),
            length_scale_base=1.0,
        )
    if name == "edge":
        from .edge_backend import EdgeBackend
        return EdgeBackend(voice=settings.get("audio.edge_voice", "en-GB-RyanNeural"))
    if name == "fake":
        from .fake_backend import FakeBackend
        return FakeBackend()
    raise BackendUnavailable(f"unknown backend: {name!r}")
