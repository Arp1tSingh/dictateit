"""Typing monitor tests: timing-only recording, active() semantics.

No global listener is started; presses are injected with note_press().
"""

import time

from dictateit.typing_monitor import TypingMonitor


class TestPrivacy:
    def test_key_values_never_stored(self):
        class FakeKey:
            def __init__(self):
                self.secret = "the letter q"

        monitor = TypingMonitor()
        monitor._on_press(FakeKey())
        # nothing but the timestamp survives
        assert monitor._last_press is not None
        assert not hasattr(monitor, "_keys")
        stored = [v for v in vars(monitor).values()]
        assert all(not isinstance(v, (list, dict)) or not v for v in stored)


class TestActive:
    def test_false_before_any_press(self):
        assert TypingMonitor().active() is False
        assert TypingMonitor().idle_for() is None

    def test_true_right_after_press(self):
        monitor = TypingMonitor(idle_ms=500)
        monitor.note_press()
        assert monitor.active() is True
        assert monitor.idle_for() < 0.5

    def test_false_after_idle(self):
        monitor = TypingMonitor(idle_ms=50)
        monitor.note_press()
        time.sleep(0.08)
        assert monitor.active() is False

    def test_recent_press_revives(self):
        monitor = TypingMonitor(idle_ms=80)
        monitor.note_press()
        time.sleep(0.06)
        monitor.note_press()          # second keystroke resets the clock
        time.sleep(0.03)
        assert monitor.active() is True

    def test_idle_s_floor(self):
        # absurdly small idle_ms is floored to avoid a busy-loop gap
        assert TypingMonitor(idle_ms=0).idle_s >= 0.05


class TestLifecycle:
    def test_start_stop_without_listener(self):
        monitor = TypingMonitor()
        # stop before start is a no-op
        monitor.stop()
        assert monitor._listener is None
