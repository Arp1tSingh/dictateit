"""Engine + adaptive pacing: the write gap extends while the writer types."""

import queue
import time

from dictateit.engine import Cmd, Command, Engine, State
from dictateit.models import Chunk, ChunkKind
from dictateit.settings import Settings


class StubMonitor:
    """Active until `deadline_has_passed`, then quiet."""

    def __init__(self, active_until: float):
        self.active_until = active_until
        self.start = time.monotonic()

    def active(self) -> bool:
        return time.monotonic() - self.start < self.active_until


class SilentBackend:
    def start_speak(self, text, rate):
        pass

    def is_speaking(self):
        return False

    def stop(self):
        pass

    def close(self):
        pass


def chunk_list():
    return [Chunk(kind=ChunkKind.TEXT, index=0, text="one",
                  spoken_natural="one", spoken_explicit="one", size=1)]


def run_engine(settings, monitor, gap_s):
    settings.set("text.gap_base_s", gap_s)
    settings.set("text.gap_per_word_s", 0.0)
    settings.set("text.pause_between_repeats_s", 0.0)
    settings.set("text.repeat_count", 1)
    commands = queue.Queue()
    commands.put(Command(Cmd.TOGGLE))
    engine = Engine(SilentBackend(), chunk_list(), settings, commands,
                    {"punctuation": {}}, {}, monitor=monitor)
    started = time.monotonic()
    engine.start()
    # the thread stays alive after DONE (waiting to restart), so the
    # clock here is time-to-DONE, not thread exit
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and engine.state is not State.DONE:
        time.sleep(0.01)
    elapsed = time.monotonic() - started
    reached_done = engine.state is State.DONE
    engine.stop_now()
    engine.join(timeout=2)
    assert reached_done
    return elapsed


def make_settings():
    settings = Settings()
    settings.set("adaptive_pacing.idle_ms", 120)
    settings.set("adaptive_pacing.max_extension_s", 2.0)
    return settings


def test_gap_extends_while_writer_active():
    settings = make_settings()
    base = run_engine(make_settings(), None, 0.15)   # no monitor: plain gap
    settings2 = make_settings()
    # the writer keeps typing for 0.5s: the 0.15s gap must stretch to >= 0.5
    elapsed = run_engine(settings2, StubMonitor(active_until=0.5), 0.15)
    assert elapsed >= 0.45, f"gap did not extend: {elapsed:.2f}s vs base {base:.2f}s"
    assert elapsed < 3.0          # and it did end


def test_max_extension_caps_the_wait():
    settings = make_settings()
    settings.set("adaptive_pacing.max_extension_s", 0.3)
    elapsed = run_engine(settings, StubMonitor(active_until=60.0), 0.1)
    assert elapsed < 1.5, f"max_extension_s not honored: {elapsed:.2f}s"


def test_quiet_writer_gets_plain_gap():
    settings = make_settings()
    elapsed = run_engine(settings, StubMonitor(active_until=0.0), 0.15)
    assert elapsed < 0.6
