"""Tkinter control window: the small always-on-top dictation remote (blueprint 9).

Layout (~340 x 300), per the sketch:

    DictateIt            [Profile v]
    Chunk 14 / 92
    "transformed the global economy"   <- hideable text
    [rendered formula if math chunk]   <- hidden in exam mode
    [<<] [Repeat] [Pause] [>>]
    Speed: [-] 1.0x [+]   [Spell] [Symbols] [Equation]
    [x] Say punctuation    [ ] Hide text

Threading: the engine calls `update_state` from its thread, which only
pushes onto a queue; the Tk main loop polls that queue with `after`.
No tkinter call is ever made from a non-main thread.
"""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from ..engine import State
from ..math.preview import PreviewCache
from ..models import ChunkKind

STATE_LABEL = {
    State.IDLE: "idle",
    State.SPEAKING_1: "speaking (natural)",
    State.PAUSE: "pause",
    State.SPEAKING_2: "speaking (explicit)",
    State.GAP: "WRITE",
    State.SPEAKING_3: "symbols",
    State.PAUSED: "paused",
    State.DONE: "done",
}

TOGGLE_LABEL = {State.PAUSED: "Resume", State.IDLE: "Start", State.DONE: "Restart"}


class UiModel:
    """Headless display logic for the window (unit-tested without a display)."""

    @staticmethod
    def counter(pos: int, total: int, state: State) -> str:
        shown = min(pos + 1, total)
        return f"Chunk {shown} / {total}"

    @staticmethod
    def state_label(state: State) -> str:
        return STATE_LABEL.get(state, state.value)

    @staticmethod
    def toggle_label(state: State) -> str:
        return TOGGLE_LABEL.get(state, "Pause")

    @staticmethod
    def speed_label(mult: float) -> str:
        return f"{mult:.1f}x"

    @staticmethod
    def chunk_text(chunk) -> str:
        if chunk is None:
            return ""
        return chunk.spoken_natural

    @staticmethod
    def show_preview(chunk, show_setting: bool) -> bool:
        return bool(show_setting and chunk is not None
                    and chunk.kind is ChunkKind.MATH and chunk.display_latex)

    @staticmethod
    def show_text(chunk_text: str, hide: bool) -> str:
        return "(hidden)" if hide else chunk_text


class ControlWindow:
    """The dictation remote. Owns no playback logic — it emits Commands."""

    POLL_MS = 80

    def __init__(self, settings, chunks, on_close=None, speed_fn=None,
                 on_action=None):
        self.settings = settings
        self.chunks = chunks
        self._on_close = on_close
        self._speed_fn = speed_fn or (lambda: 1.0)
        self._on_action = on_action   # when set, button presses go there
        self.commands = queue.Queue()          # UI -> engine commands
        self._state_queue = queue.Queue()      # engine thread -> UI thread
        self._preview_cache = PreviewCache()
        self._hidden = False
        self._model = UiModel

        self.root = tk.Tk()
        self.root.title("DictateIt")
        self.root.wm_attributes("-topmost", True)
        self.root.minsize(340, 280)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self._build_widgets()
        self.root.after(self.POLL_MS, self._poll_state)

    # -- construction --------------------------------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 6, "pady": 3}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="DictateIt", font=("Segoe UI", 11, "bold")).pack(side="left")
        self.profile_var = tk.StringVar(
            value=self.settings.get("active_profile", "default"))
        profiles = sorted((self.settings.get("profiles") or {}).keys()) or ["default"]
        box = ttk.Combobox(top, textvariable=self.profile_var, values=profiles,
                           state="readonly", width=10)
        box.bind("<<ComboboxSelected>>", self._on_profile)
        box.pack(side="right")

        self.counter_var = tk.StringVar(value=self._model.counter(0, len(self.chunks), State.IDLE))
        ttk.Label(self.root, textvariable=self.counter_var).pack(anchor="w", **pad)

        self.state_var = tk.StringVar(value=self._model.state_label(State.IDLE))
        ttk.Label(self.root, textvariable=self.state_var,
                  foreground="#555").pack(anchor="w", padx=6)

        self.amb_var = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.amb_var,
                  foreground="#b06000").pack(anchor="w", padx=6)

        self.text_var = tk.StringVar(value="")
        self.text_label = ttk.Label(self.root, textvariable=self.text_var,
                                    wraplength=320, justify="left", font=("Segoe UI", 10))
        self.text_label.pack(anchor="w", **pad)

        self.preview_label = ttk.Label(self.root)
        self.preview_label.pack(anchor="w", **pad)

        buttons = ttk.Frame(self.root)
        buttons.pack(fill="x", **pad)
        for text, cmd in (("\u00ab\u00ab", "prev"), ("Repeat", "repeat"),
                          ("Pause", "toggle"), ("\u00bb\u00bb", "next")):
            btn = ttk.Button(buttons, text=text, width=8,
                             command=lambda c=cmd: self._send(c))
            btn.pack(side="left", expand=True, fill="x", padx=2)
        self.toggle_btn = buttons.winfo_children()[2]

        speed = ttk.Frame(self.root)
        speed.pack(fill="x", **pad)
        ttk.Button(speed, text="-", width=3,
                   command=lambda: self._send("slower")).pack(side="left")
        self.speed_var = tk.StringVar(value=self._model.speed_label(1.0))
        ttk.Label(speed, textvariable=self.speed_var, width=6,
                  anchor="center").pack(side="left", expand=True)
        ttk.Button(speed, text="+", width=3,
                   command=lambda: self._send("faster")).pack(side="left")
        for text, cmd in (("Spell", "spell"), ("Symbols", "symbols"),
                          ("Equation", "equation")):
            ttk.Button(speed, text=text,
                        command=lambda c=cmd: self._send(c)).pack(side="right", padx=2)

        checks = ttk.Frame(self.root)
        checks.pack(fill="x", **pad)
        self.punct_var = tk.BooleanVar(
            value=bool(self.settings.get("say_punctuation", True)))
        ttk.Checkbutton(checks, text="Say punctuation", variable=self.punct_var,
                        command=self._on_punctuation).pack(side="left")
        self._hide_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(checks, text="Hide text", variable=self._hide_var,
                        command=self._on_hide_text).pack(side="right")

    # -- UI -> engine ----------------------------------------------------------
    def _send(self, action: str) -> None:
        if self._on_action is not None:
            self._on_action(action)
        else:
            self.commands.put(action)

    def _on_profile(self, _event=None) -> None:
        name = self.profile_var.get()
        self.settings.apply_profile(name)
        self.settings.set("active_profile", name)
        self.settings.save()
        self.punct_var.set(bool(self.settings.get("say_punctuation", True)))

    def _on_punctuation(self) -> None:
        self.settings.set("say_punctuation", bool(self.punct_var.get()))
        self.settings.save()

    def _on_hide_text(self) -> None:
        self._hidden = bool(self._hide_var.get())
        self._apply_text_visibility()

    def _apply_text_visibility(self, chunk_text: str = "") -> None:
        self.text_var.set(self._model.show_text(chunk_text, self._hidden))

    # -- engine -> UI -----------------------------------------------------------
    def update_state(self, state, pos, total, chunk) -> None:
        """Thread-safe entry point for the engine's on_state callback."""
        self._state_queue.put((state, pos, total, chunk))

    def _poll_state(self) -> None:
        while True:
            try:
                state, pos, total, chunk = self._state_queue.get_nowait()
            except queue.Empty:
                break
            self._apply(state, pos, total, chunk)
        # speed can change from hotkeys as well as the window buttons
        self.speed_var.set(self._model.speed_label(self._speed_fn()))
        self.root.after(self.POLL_MS, self._poll_state)

    def _apply(self, state, pos, total, chunk) -> None:
        self.counter_var.set(self._model.counter(pos, total, state))
        self.state_var.set(self._model.state_label(state))
        self.toggle_btn.config(text=self._model.toggle_label(state))
        self.amb_var.set("\u26a0 ambiguous \u2014 check the original" if chunk and chunk.ambiguous else "")
        self._apply_text_visibility(self._model.chunk_text(chunk))

        show = self._model.show_preview(chunk, self.settings.get("show_preview", True))
        if show:
            png = self._preview_cache.get(chunk.display_latex)
            if png is not None:
                photo = tk.PhotoImage(data=png)
                self.preview_label.configure(image=photo, text="")
                self.preview_label.image = photo  # keep a reference
            else:
                self.preview_label.configure(image="", text="(formula \u2014 no preview)")
        else:
            self.preview_label.configure(image="", text="")

    # -- lifecycle ---------------------------------------------------------------
    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self._on_close is not None:
            self._on_close()
        self.root.destroy()
