"""Engine tests: the double take, controls and state transitions.

Uses the FakeBackend (is_speaking False immediately) plus a holding backend
for interrupt tests, and zero-gap timing so tests run instantly.
"""

import queue
import time

from dictateit.engine import Cmd, Command, Engine, State
from dictateit.models import Chunk, ChunkKind
from dictateit.settings import Settings
from dictateit.tts.fake_backend import FakeBackend


def make_chunks(n=2):
    chunks = []
    for i in range(n):
        chunks.append(
            Chunk(
                kind=ChunkKind.TEXT,
                index=i,
                text=f"chunk number {i}",
                spoken_natural=f"natural {i}",
                spoken_explicit=f"explicit {i}",
                size=3,
            )
        )
    return chunks


def make_engine(chunks=None, backend=None, monitor=None):
    settings = Settings()
    # zero every wait so tests are instant and deterministic
    settings.set("text.pause_between_repeats_s", 0.0)
    settings.set("text.gap_base_s", 0.0)
    settings.set("text.gap_per_word_s", 0.0)
    settings.set("math.gap_base_s", 0.0)
    settings.set("math.gap_per_token_s", 0.0)
    settings.set("timing.spell_gap_s", 0.0)
    settings.set("timing.symbols_gap_s", 0.0)
    settings.set("timing.equation_gap_s", 0.0)

    q = queue.Queue()
    events = []
    engine = Engine(
        backend or FakeBackend(),
        chunks or make_chunks(),
        settings,
        q,
        pack={"punctuation": {"capital": "capital"}},
        letters={"a": "ay", "b": "bee", "c": "see"},
        on_state=lambda s, pos, total, ch: events.append((s, pos)),
        monitor=monitor,
    )
    return engine, q, events


class TestDoubleTake:
    def test_each_chunk_read_twice_natural_then_explicit(self):
        import time
        engine, q, events = make_engine(make_chunks(2))
        engine.start()
        q.put(Command(Cmd.TOGGLE))
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.DONE:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        utts = [u[0] for u in engine.backend.utterances]
        assert utts == ["natural 0", "explicit 0", "natural 1", "explicit 1"]

    def test_state_sequence(self):
        engine, q, events = make_engine(make_chunks(1))
        q.put(Command(Cmd.TOGGLE))
        import time
        engine.start()
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.DONE:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        states = [s for s, _ in events]
        assert State.SPEAKING_1 in states
        assert State.PAUSE in states
        assert State.SPEAKING_2 in states
        assert State.GAP in states
        assert State.DONE in states
        assert states[-1] is State.IDLE  # stop_now() parks the engine back in IDLE

    def test_done_then_toggle_restarts(self):
        engine, q, events = make_engine(make_chunks(1))
        q.put(Command(Cmd.TOGGLE))
        import time
        engine.start()
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.DONE:
            time.sleep(0.01)
        q.put(Command(Cmd.TOGGLE))
        deadline = time.time() + 2
        while time.time() < deadline and len(engine.backend.utterances) < 4:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)
        utts = [u[0] for u in engine.backend.utterances]
        assert utts == ["natural 0", "explicit 0", "natural 0", "explicit 0"]


class _HoldingBackend(FakeBackend):
    """Holds the first `hold_first` utterances until stop() is called,
    then behaves like the instant FakeBackend."""

    def __init__(self, hold_first: int = 1):
        super().__init__()
        self._held = False
        self._remaining = hold_first

    def start_speak(self, text, rate):
        self.utterances.append((text, rate))
        if self._remaining > 0:
            self._remaining -= 1
            self._held = True

    def is_speaking(self):
        return self._held

    def stop(self):
        self.stopped += 1
        self._held = False


class TestControls:
    def test_repeat_replays_chunk(self):
        backend = _HoldingBackend(hold_first=2)
        engine, q, events = make_engine(make_chunks(1), backend=backend)
        engine.start()
        q.put(Command(Cmd.TOGGLE))
        # engine is speaking pass 1 (held); request a repeat
        q.put(Command(Cmd.REPEAT))
        # now it replays pass 1 (held again); toggle to pause and stop
        q.put(Command(Cmd.TOGGLE))
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.PAUSED:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        utts = [u[0] for u in backend.utterances]
        assert utts.count("natural 0") == 2  # spoken, repeated, then paused

    def test_pause_resume_same_pass(self):
        backend = _HoldingBackend()
        engine, q, events = make_engine(make_chunks(2), backend=backend)
        engine.start()
        q.put(Command(Cmd.TOGGLE))
        q.put(Command(Cmd.TOGGLE))          # pause during pass 1
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.PAUSED:
            time.sleep(0.01)
        assert engine.position == 0
        q.put(Command(Cmd.TOGGLE))          # resume
        # resumes pass 1 of chunk 0, then finishes everything
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.DONE:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        utts = [u[0] for u in backend.utterances]
        assert utts == ["natural 0", "natural 0", "explicit 0", "natural 1", "explicit 1"]

    def test_next_skips_chunk(self):
        backend = _HoldingBackend()
        engine, q, events = make_engine(make_chunks(2), backend=backend)
        engine.start()
        q.put(Command(Cmd.TOGGLE))
        q.put(Command(Cmd.NEXT))            # skip chunk 0
        deadline = time.time() + 2
        while time.time() < deadline and len(backend.utterances) < 3:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        utts = [u[0] for u in backend.utterances]
        assert utts[0] == "natural 0"
        assert utts[1] == "natural 1"

    def test_prev_goes_back(self):
        backend = _HoldingBackend(hold_first=2)
        engine, q, events = make_engine(make_chunks(2), backend=backend)
        engine.start()
        q.put(Command(Cmd.TOGGLE))
        q.put(Command(Cmd.NEXT))            # to chunk 1
        q.put(Command(Cmd.PREV))            # back to chunk 0
        deadline = time.time() + 2
        while time.time() < deadline and len(backend.utterances) < 3:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        utts = [u[0] for u in backend.utterances]
        assert utts[2] == "natural 0"

    def test_slower_replays_at_lower_rate(self):
        backend = _HoldingBackend(hold_first=2)
        engine, q, events = make_engine(make_chunks(1), backend=backend)
        engine.start()
        q.put(Command(Cmd.TOGGLE))
        q.put(Command(Cmd.SLOWER))          # replay at reduced rate
        q.put(Command(Cmd.TOGGLE))          # pause to stop the loop
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.PAUSED:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        utts = backend.utterances
        assert len(utts) >= 2
        assert utts[1][1] < utts[0][1]      # second attempt has a lower wpm


class TestSpellAndSymbols:
    def test_spell_reads_letters(self):
        backend = _HoldingBackend(hold_first=2)
        engine, q, events = make_engine(make_chunks(1), backend=backend)
        engine.start()
        q.put(Command(Cmd.TOGGLE))
        q.put(Command(Cmd.SPELL))
        q.put(Command(Cmd.TOGGLE))
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.PAUSED:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        utts = [u[0] for u in backend.utterances]
        # "chunk number 0" -> last word "0" -> "zero"
        assert "zero" in utts

    def test_symbols_reads_one_at_a_time(self):
        backend = _HoldingBackend()
        engine, q, events = make_engine(make_chunks(1), backend=backend)
        chunk = make_chunks(1)[0]
        chunk.spoken_symbols = ["x", "squared"]
        engine.chunks = [chunk]
        engine.start()
        q.put(Command(Cmd.TOGGLE))
        q.put(Command(Cmd.SYMBOLS))
        q.put(Command(Cmd.TOGGLE))
        deadline = time.time() + 2
        while time.time() < deadline and engine.state is not State.PAUSED:
            time.sleep(0.01)
        engine.stop_now()
        engine.join(timeout=2)

        utts = [u[0] for u in backend.utterances]
        assert "x" in utts and "squared" in utts
