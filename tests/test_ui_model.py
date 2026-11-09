"""UI model tests: headless display logic of the control window."""

import pytest

tkinter = pytest.importorskip("tkinter", reason="tkinter not available")

from dictateit.engine import State
from dictateit.models import Chunk, ChunkKind
from dictateit.ui.control_window import UiModel

model = UiModel


def math_chunk(**kw):
    defaults = dict(kind=ChunkKind.MATH, index=3, text="x=1",
                    spoken_natural="ex equals", spoken_explicit="ex, equals",
                    display_latex="x = 1", size=2)
    defaults.update(kw)
    return Chunk(**defaults)


class TestCounter:
    def test_first(self):
        assert model.counter(0, 92, State.IDLE) == "Chunk 1 / 92"

    def test_mid(self):
        assert model.counter(13, 92, State.GAP) == "Chunk 14 / 92"

    def test_done_does_not_overflow(self):
        assert model.counter(92, 92, State.DONE) == "Chunk 92 / 92"

    def test_idle_before_start(self):
        assert model.counter(0, 5, State.IDLE) == "Chunk 1 / 5"


class TestLabels:
    def test_state_labels(self):
        assert model.state_label(State.GAP) == "WRITE"
        assert model.state_label(State.PAUSED) == "paused"

    def test_toggle_label_by_state(self):
        assert model.toggle_label(State.IDLE) == "Start"
        assert model.toggle_label(State.PAUSED) == "Resume"
        assert model.toggle_label(State.SPEAKING_1) == "Pause"

    def test_speed(self):
        assert model.speed_label(1.0) == "1.0x"
        assert model.speed_label(0.75) == "0.8x"


class TestChunkDisplay:
    def test_text_chunk(self):
        chunk = Chunk(kind=ChunkKind.TEXT, index=0, text="hello",
                      spoken_natural="hello", spoken_explicit="hello")
        assert model.chunk_text(chunk) == "hello"

    def test_none_chunk(self):
        assert model.chunk_text(None) == ""

    def test_hide_text(self):
        assert model.show_text("hello", True) == "(hidden)"
        assert model.show_text("hello", False) == "hello"

    def test_preview_only_for_math_with_latex(self):
        assert model.show_preview(math_chunk(), True) is True
        assert model.show_preview(math_chunk(), False) is False
        no_latex = math_chunk(display_latex=None)
        assert model.show_preview(no_latex, True) is False
        text_chunk = Chunk(kind=ChunkKind.TEXT, index=0, text="t",
                           spoken_natural="t", spoken_explicit="t")
        assert model.show_preview(text_chunk, True) is False
