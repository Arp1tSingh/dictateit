"""Typing monitor: keystroke TIMING only, for adaptive pacing (blueprint 7).

Privacy contract: the listener receives every global key event and stores
only `time.monotonic()` timestamps. Key values, key names, and window
titles are never read, stored, or transmitted. The feature is opt-in via
`adaptive_pacing.enabled` and must be described that way in the UI.

Adaptive pacing semantics: during a write gap, the engine keeps waiting
while the writer is `active()` — a keystroke within the last `idle_ms`.
Once the writer goes quiet, the gap ends and dictation advances.
"""

from __future__ import annotations

import threading
import time


class TypingMonitor:
    """Passive global keystroke listener that remembers only when keys happen."""

    def __init__(self, idle_ms: int = 1500):
        self.idle_s = max(0.05, idle_ms / 1000.0)
        self._lock = threading.Lock()
        self._last_press: float | None = None
        self._listener = None

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._listener is not None:
            return
        from pynput import keyboard   # lazy: optional dependency

        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=lambda key: None)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # -- recording -------------------------------------------------------------
    def _on_press(self, key) -> None:
        """Listener callback: timestamp only; the key object is discarded."""
        del key
        self.note_press()

    def note_press(self) -> None:
        """Record a keystroke now (tests call this directly)."""
        with self._lock:
            self._last_press = time.monotonic()

    # -- queries -----------------------------------------------------------------
    def active(self) -> bool:
        """True when the writer has typed within the last `idle_ms`.

        False before the first keystroke: a writer who has not started
        writing gets the plain gap, not an extension.
        """
        with self._lock:
            last = self._last_press
        return last is not None and (time.monotonic() - last) < self.idle_s

    def idle_for(self) -> float | None:
        """Seconds since the last keystroke, or None if there was none."""
        with self._lock:
            last = self._last_press
        if last is None:
            return None
        return time.monotonic() - last
