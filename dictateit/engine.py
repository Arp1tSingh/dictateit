"""Playback engine: the dictation state machine (blueprint section 7).

States:  IDLE, SPEAKING_1, PAUSE, SPEAKING_2, GAP, SPEAKING_3, PAUSED, DONE

Runs in its own thread. All commands (hotkeys, UI, CLI) go through a
thread-safe queue; the engine is the only consumer. Waits are interruptible
slices so a hotkey is acted on within ~30 ms, never `time.sleep`d away.

The double take: pass 1 speaks `spoken_natural` at normal speed, a short
pause follows, pass 2 speaks `spoken_explicit` at the slow speed, then the
silent write gap lets the writer catch up. Math chunks use the math timing
profile (slower, longer gaps).
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum

from .models import Chunk, ChunkKind
from .spelling import last_word_of, spell_word


class State(str, Enum):
    IDLE = "idle"
    SPEAKING_1 = "speaking_1"
    PAUSE = "pause"          # the short pause between the two passes
    SPEAKING_2 = "speaking_2"
    GAP = "gap"              # silent write gap
    SPEAKING_3 = "speaking_3"  # symbol-by-symbol re-read
    PAUSED = "paused"
    DONE = "done"


class Cmd(str, Enum):
    TOGGLE = "toggle"        # start / pause
    REPEAT = "repeat"
    PREV = "previous"
    NEXT = "next"
    SLOWER = "slower"
    FASTER = "faster"
    SPELL = "spell"
    SYMBOLS = "symbols"
    EQUATION = "equation"
    EXIT = "exit"


@dataclass
class Command:
    cmd: Cmd
    payload: object = None


class Engine(threading.Thread):
    """Consumes commands, walks the chunk list, drives the TTS backend."""

    POLL_S = 0.03

    def __init__(self, backend, chunks: list[Chunk], settings, commands: queue.Queue,
                 pack: dict, letters: dict, on_state=None, monitor=None):
        super().__init__(name="dictateit-engine", daemon=True)
        self.backend = backend
        self.chunks = chunks
        self.settings = settings
        self.commands = commands
        self.pack = pack
        self.letters = letters
        self.on_state = on_state or (lambda *a: None)
        self.monitor = monitor  # optional TypingMonitor for adaptive pacing

        self._pos = 0
        self._speed_mult = 1.0
        self._state = State.IDLE
        self._resume_pass = 1    # which pass to continue at after PAUSED
        self._running = True

    # -- helpers -------------------------------------------------------------
    @property
    def state(self) -> State:
        return self._state

    @property
    def position(self) -> int:
        return self._pos

    @property
    def speed_mult(self) -> float:
        return self._speed_mult

    def _set_state(self, state: State) -> None:
        self._state = state
        chunk = self.chunks[self._pos] if self.chunks and self._pos < len(self.chunks) else None
        self.on_state(state, self._pos, len(self.chunks), chunk)

    def _poll(self) -> Command | None:
        try:
            return self.commands.get_nowait()
        except queue.Empty:
            return None

    def _normal_rate(self, kind: str) -> int:
        return max(60, int(self.settings.get("audio.normal_wpm", 190) * self._speed_mult))

    def _slow_rate(self, kind: str) -> int:
        factor = self.settings.slow_factor(kind)
        return max(60, int(self.settings.get("audio.normal_wpm", 190) * factor * self._speed_mult))

    def _repeat_count(self, kind: str) -> int:
        if kind == ChunkKind.MATH.value or kind == ChunkKind.MATH:
            return int(self.settings.get("math.repeat_count", 2))
        return int(self.settings.get("text.repeat_count", 2))

    # -- interruptible waits ---------------------------------------------------
    def _wait(self, seconds: float, adaptive: bool = False) -> Command | None:
        """Wait up to `seconds`, draining the command queue. Returns a command
        if one arrives (caller decides what it means).

        Adaptive waits extend while the writer is still typing (the
        TypingMonitor reports keystroke timing only), capped by
        `adaptive_pacing.max_extension_s` so a stuck writer is never
        waited on forever.
        """
        now = time.time()
        deadline = now + seconds
        hard = deadline + (float(self.settings.get(
            "adaptive_pacing.max_extension_s", 10.0)) if adaptive else 0.0)
        while True:
            cmd = self._poll()
            if cmd is not None:
                return cmd
            if adaptive and self.monitor is not None and self.monitor.active():
                # the writer is still typing; push the deadline out
                idle = float(self.settings.get("adaptive_pacing.idle_ms", 1500)) / 1000.0
                extended = min(max(deadline, time.time() + idle), hard)
                if extended > deadline + 1e-9:
                    deadline = extended
                    self.on_state(State.GAP, self._pos, len(self.chunks), self._chunk())
            if time.time() >= deadline:
                return None
            time.sleep(self.POLL_S)

    def _chunk(self) -> Chunk | None:
        if 0 <= self._pos < len(self.chunks):
            return self.chunks[self._pos]
        return None

    def _speak(self, text: str, rate: int) -> Command | None:
        """Speak `text`, polling for commands. Returns any interrupting command."""
        if not text or not text.strip():
            return None
        self.backend.start_speak(text, rate)
        while self.backend.is_speaking():
            cmd = self._poll()
            if cmd is not None:
                self.backend.stop()
                return cmd
            time.sleep(self.POLL_S)
        return None

    # -- thread body ------------------------------------------------------------
    def run(self) -> None:
        try:
            while self._running:
                cmd = self._wait_for_start()
                if cmd is None:
                    break
                if cmd.cmd is Cmd.EXIT:
                    break
                if cmd.cmd is Cmd.TOGGLE:
                    self._play_all()
        finally:
            self.backend.stop()
            self._set_state(State.IDLE)

    def _wait_for_start(self) -> Command | None:
        """Block until TOGGLE or EXIT. Also service REPEAT etc. while idle."""
        while self._running:
            cmd = self._poll()
            if cmd is None:
                time.sleep(self.POLL_S)
                continue
            if cmd.cmd is Cmd.EXIT:
                return cmd
            if cmd.cmd is Cmd.TOGGLE:
                if self._state is State.DONE:
                    self._pos = 0
                if self._state is not State.PAUSED:
                    self._resume_pass = 1
                return cmd
            if cmd.cmd is Cmd.NEXT:
                self._pos = min(len(self.chunks) - 1, self._pos + 1)
            elif cmd.cmd is Cmd.PREV:
                self._pos = max(0, self._pos - 1)
        return None

    # -- playback ------------------------------------------------------------------
    def _play_all(self) -> None:
        while self._running and self._pos < len(self.chunks):
            result = self._play_chunk(self.chunks[self._pos])
            if result == "paused":
                return
            if result == "replay":
                continue            # same chunk again
            if result == "retreat":
                self._pos = max(0, self._pos - 1)
                continue
            self._pos += 1          # "advance"
            self._resume_pass = 1
        if self._running:
            self._set_state(State.DONE)

    def _play_chunk(self, chunk: Chunk) -> str:
        """Play one chunk: natural pass, pause, explicit pass, write gap.

        Returns "paused", "replay", "retreat" or "advance".
        """
        kind = chunk.kind.value if isinstance(chunk.kind, ChunkKind) else str(chunk.kind)

        passes = self._passes_for(chunk)
        start = self._resume_pass if self._state is State.PAUSED else 1
        for pass_no, text in [p for p in passes if p[0] >= start]:
            state = State.SPEAKING_1 if pass_no == 1 else State.SPEAKING_2
            self._set_state(state)
            while True:
                # rate is computed per attempt so SLOWER/FASTER apply immediately
                rate = self._normal_rate(kind) if pass_no == 1 else self._slow_rate(kind)
                cmd = self._speak(text, rate)
                if cmd is None:
                    break
                action = self._handle_interrupt(cmd, chunk)
                if action == "paused":
                    self._resume_pass = pass_no
                    return "paused"
                if action == "replay":
                    continue
                return action

            if pass_no == 1 and len(passes) > 1:
                # the short pause between the two passes
                self._set_state(State.PAUSE)
                cmd = self._wait(float(self.settings.get("text.pause_between_repeats_s", 0.8)))
                if cmd is not None:
                    action = self._handle_interrupt(cmd, chunk)
                    if action == "paused":
                        self._resume_pass = 2
                        return "paused"
                    return action

        # write gap
        self._set_state(State.GAP)
        gap = self.settings.gap_for(kind, chunk.size, chunk.extra_gap_s)
        cmd = self._wait(gap, adaptive=True)
        if cmd is not None:
            action = self._handle_interrupt(cmd, chunk)
            if action == "paused":
                # the writer finished this chunk; resume with the next one
                self._pos += 1
                self._resume_pass = 1
                return "paused"
            return action
        return "advance"

    def _passes_for(self, chunk: Chunk):
        """The utterances for one chunk: [(pass_no, text), ...]."""
        passes = [(1, chunk.spoken_natural), (2, chunk.spoken_explicit)]
        repeats = self._repeat_count(chunk.kind.value)
        if repeats < 2:
            return passes[:repeats]
        for _ in range(repeats - 2):
            passes.append((2, chunk.spoken_explicit))
        return passes

    # -- command handling -------------------------------------------------------
    def _handle_interrupt(self, cmd: Command, chunk: Chunk) -> str:
        """Act on a command that arrived mid-pass. Returns an action code."""
        code = cmd.cmd
        if code is Cmd.TOGGLE:
            self._set_state(State.PAUSED)
            return "paused"
        if code is Cmd.REPEAT:
            return "replay"
        if code is Cmd.NEXT:
            return "advance"
        if code is Cmd.PREV:
            return "retreat"
        if code is Cmd.SLOWER:
            self._speed_mult = max(0.5, self._speed_mult - 0.1)
            return "replay"
        if code is Cmd.FASTER:
            self._speed_mult = min(1.5, self._speed_mult + 0.1)
            return "replay"
        if code is Cmd.SPELL:
            self._do_spell(chunk)
            return "replay"
        if code is Cmd.SYMBOLS:
            self._do_symbols(chunk)
            return "replay"
        if code is Cmd.EQUATION:
            self._do_equation(chunk)
            return "replay"
        return "ignore"

    def _do_spell(self, chunk: Chunk) -> None:
        word = last_word_of(chunk.text)
        if not word:
            return
        seq = spell_word(word, self.letters, self.pack.get("punctuation", {}).get("capital", "capital"))
        rate = self._slow_rate(chunk.kind.value)
        gap = float(self.settings.get("timing.spell_gap_s", 0.35))
        for part in seq:
            self._speak(part, rate)
            self._wait(gap)

    def _do_symbols(self, chunk: Chunk) -> None:
        symbols = chunk.spoken_symbols or chunk.spoken_natural.split()
        rate = self._slow_rate(chunk.kind.value)
        gap = float(self.settings.get("timing.symbols_gap_s", 0.4))
        self._set_state(State.SPEAKING_3)
        for symbol in symbols:
            cmd = self._speak(symbol, rate)
            if cmd is not None:
                self._handle_interrupt(cmd, chunk)
                return
            self._wait(gap)

    def _do_equation(self, chunk: Chunk) -> None:
        """Re-read every chunk of the current equation, naturally, once."""
        if chunk.segment_id < 0:
            return
        rate = self._normal_rate(chunk.kind.value)
        gap = float(self.settings.get("timing.equation_gap_s", 0.5))
        for c in self.chunks:
            if c.segment_id == chunk.segment_id:
                cmd = self._speak(c.spoken_natural, rate)
                if cmd is not None:
                    self._handle_interrupt(cmd, chunk)
                    return
                self._wait(gap)

    def stop_now(self) -> None:
        """External stop: exit the thread."""
        self._running = False
        self.commands.put(Command(Cmd.EXIT))
        self.backend.stop()
