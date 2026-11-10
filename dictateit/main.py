"""DictateIt entry point.

Modes:
    python -m dictateit.main --input file.txt            # speak via hotkeys
    python -m dictateit.main --input file.txt --cli      # keyboard controls in terminal
    python -m dictateit.main --input file.txt --dry-run  # print chunks, no audio
    python -m dictateit.main --list-chunks --input f.txt # dump the chunk plan
    cat text | python -m dictateit.main --stdin --dry-run

Backends: pyttsx3 (default, built into Windows), piper, edge (v2), fake.
"""

from __future__ import annotations

import argparse
import queue
import sys

from .engine import Cmd, Command, Engine, State
from .models import Chunk, ChunkKind
from .pipeline import build_chunks
from .settings import Settings
from .speech import load_pack
from .tts.base import BackendUnavailable, create_backend
from .tts.fake_backend import FakeBackend

ACTION_TO_CMD = {
    "toggle": Cmd.TOGGLE,
    "repeat": Cmd.REPEAT,
    "previous": Cmd.PREV,
    "next": Cmd.NEXT,
    "slower": Cmd.SLOWER,
    "faster": Cmd.FASTER,
    "spell": Cmd.SPELL,
    "symbols": Cmd.SYMBOLS,
    "equation": Cmd.EQUATION,
}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="dictateit", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=str, help="text/markdown/docx file to dictate")
    src.add_argument("--stdin", action="store_true", help="read input from stdin")
    p.add_argument("--cli", action="store_true", help="terminal key controls instead of global hotkeys")
    p.add_argument("--ui", action="store_true", help="open the control window (global hotkeys stay active)")
    p.add_argument("--dry-run", action="store_true", help="no audio; print what would be spoken")
    p.add_argument("--list-chunks", action="store_true", help="print the chunk plan and exit")
    p.add_argument("--backend", type=str, help="pyttsx3 | piper | edge | fake")
    p.add_argument("--locale", type=str, choices=["en_uk", "en_us"], help="speech pack")
    p.add_argument("--profile", type=str, help="default | exam | practice | proofread")
    p.add_argument("--config", type=str, help="path to config.json")
    p.add_argument("--max", type=int, help="only dictate the first N chunks (debugging)")
    return p.parse_args(argv)


def read_input(args) -> str:
    if args.stdin:
        return sys.stdin.read().lstrip("\ufeff")
    from .loader import load_text

    return load_text(args.input)


def make_backend(settings, dry_run: bool):
    name = "fake" if dry_run else settings.get("audio.backend", "pyttsx3")
    try:
        return create_backend(name, settings)
    except BackendUnavailable as e:
        print(f"backend {name!r} unavailable: {e}", file=sys.stderr)
        print("falling back to the fake (dry-run) backend", file=sys.stderr)
        return FakeBackend()


def state_line(state: State, pos: int, total: int, chunk: Chunk | None) -> str:
    label = {
        State.IDLE: "idle", State.PAUSE: "pause", State.GAP: "WRITE",
        State.PAUSED: "paused", State.DONE: "done",
    }.get(state, state.value)
    kind = f" [{chunk.kind.value}]" if chunk else ""
    amb = " (ambiguous)" if chunk and chunk.ambiguous else ""
    shown = min(pos + 1, total) if state is not State.IDLE else pos
    return f"\r{label:10} {shown:>3}/{total:<3}{kind}{amb}"


def print_plan(chunks: list[Chunk]) -> None:
    for c in chunks:
        flag = " !amb" if c.ambiguous else ""
        print(f"[{c.index:3}] {c.kind.value:5}{flag} nat={c.spoken_natural!r}")
        if c.spoken_explicit != c.spoken_natural:
            print(f"            exp={c.spoken_explicit!r}")


def run_cli(engine: Engine, commands: queue.Queue, chunks: list[Chunk]) -> None:
    """Terminal controls: space toggles, r repeats, arrows navigate, q quits."""
    import msvcrt

    print("\ncontrols: space=start/pause  r=repeat  [=previous  ]=next  "
          "-/+ speed  s=spell  m=symbols  e=equation  q=quit")
    engine.start()
    try:
        while True:
            if engine.state is State.DONE:
                break
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                cmd = _key_to_cmd(key)
                if cmd is Cmd.EXIT:
                    break
                if cmd is not None:
                    commands.put(Command(cmd))
            engine._set_state(engine.state)  # refresh status line
            import time
            time.sleep(0.05)
    finally:
        engine.stop_now()
        engine.join(timeout=2)
        print()


def _key_to_cmd(key: str) -> Cmd | None:
    return {
        " ": Cmd.TOGGLE, "r": Cmd.REPEAT, "[": Cmd.PREV, "]": Cmd.NEXT,
        "-": Cmd.SLOWER, "=": Cmd.FASTER, "s": Cmd.SPELL, "m": Cmd.SYMBOLS,
        "e": Cmd.EQUATION, "q": Cmd.EXIT, "\x1b": Cmd.EXIT,
    }.get(key)


def run_hotkeys(engine: Engine, commands: queue.Queue, settings: Settings) -> None:
    from .hotkeys import HotkeyManager

    actions = []
    mgr = HotkeyManager(settings.get("hotkeys") or {}, actions.append)
    engine.start()
    print("DictateIt running. Global hotkeys active (see config). Ctrl+C to quit.")
    try:
        mgr.start()
        while True:
            import time
            time.sleep(0.2)
            while actions:
                action = actions.pop(0)
                cmd = ACTION_TO_CMD.get(action)
                if cmd is not None:
                    commands.put(Command(cmd))
    except KeyboardInterrupt:
        pass
    finally:
        mgr.stop()
        engine.stop_now()
        engine.join(timeout=2)


def run_ui(engine: Engine, settings: Settings, chunks: list[Chunk]) -> None:
    """Control window + global hotkeys + engine, three threads, one queue."""
    from .hotkeys import HotkeyManager
    from .ui.control_window import ControlWindow

    ui_actions: queue.Queue = queue.Queue()

    def on_ui_action(action: str) -> None:
        cmd = ACTION_TO_CMD.get(action)
        if cmd is not None:
            commands.put(Command(cmd))

    hotkeys = HotkeyManager(settings.get("hotkeys") or {},
                            lambda a: commands.put(Command(ACTION_TO_CMD[a])))
    window = ControlWindow(settings, chunks,
                           on_close=lambda: commands.put(Command(Cmd.EXIT)),
                           speed_fn=lambda: engine.speed_mult,
                           on_action=on_ui_action)
    engine.on_state = window.update_state
    engine.start()
    hotkeys.start()
    try:
        window.run()          # blocks until the window closes
    finally:
        hotkeys.stop()
        engine.stop_now()
        engine.join(timeout=2)


def make_monitor(settings):
    """The typing monitor is opt-in and timing-only (blueprint privacy note)."""
    if not settings.get("adaptive_pacing.enabled", False):
        return None
    from .typing_monitor import TypingMonitor

    monitor = TypingMonitor(int(settings.get("adaptive_pacing.idle_ms", 1500)))
    monitor.start()
    print("Adaptive pacing on: keystroke TIMING is recorded to extend write "
          "gaps. Key values are never read or stored.")
    return monitor


def main(argv=None) -> int:
    args = parse_args(argv)

    settings = Settings.load(args.config and __import__("pathlib").Path(args.config))
    if args.locale:
        settings.set("locale", args.locale)
    if args.profile:
        settings.apply_profile(args.profile)

    text = read_input(args)
    chunks = build_chunks(text, settings)
    if args.max:
        chunks = chunks[:args.max]
        for i, c in enumerate(chunks):
            c.index = i

    if args.list_chunks or args.dry_run:
        print_plan(chunks)
        if args.list_chunks:
            return 0
        # the walk must be instant: zero the write gaps and pauses
        settings.set("text.pause_between_repeats_s", 0.0)
        settings.set("text.gap_base_s", 0.0)
        settings.set("text.gap_per_word_s", 0.0)
        settings.set("math.gap_base_s", 0.0)
        settings.set("math.gap_per_token_s", 0.0)

    if not chunks:
        print("nothing to dictate")
        return 0

    pack, letters = load_pack(settings.get("locale", "en_uk"))
    backend = make_backend(settings, args.dry_run)
    commands: queue.Queue = queue.Queue()
    monitor = make_monitor(settings)

    def show_state(state, pos, total, chunk):
        if args.dry_run and state in (State.SPEAKING_1, State.SPEAKING_2, State.SPEAKING_3):
            return  # plan already printed
        print(state_line(state, pos, total, chunk), end="", flush=True)

    engine = Engine(backend, chunks, settings, commands, pack, letters,
                    on_state=show_state, monitor=monitor)

    try:
        if args.cli:
            run_cli(engine, commands, chunks)
        elif args.ui:
            run_ui(engine, settings, chunks)
        elif args.dry_run or args.list_chunks:
            # dry-run: walk the whole plan through the engine with the fake backend
            commands.put(Command(Cmd.TOGGLE))
            engine.start()
            import time
            deadline = time.time() + 30
            while time.time() < deadline and engine.state is not State.DONE:
                time.sleep(0.05)
            engine.stop_now()
            engine.join(timeout=2)
            print("\n(dry run complete)")
        else:
            run_hotkeys(engine, commands, settings)
    finally:
        if monitor is not None:
            monitor.stop()
        backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
