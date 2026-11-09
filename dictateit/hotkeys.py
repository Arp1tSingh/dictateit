"""Global hotkeys (blueprint feature 7).

Uses pynput's GlobalHotKeys so controls work while another window
(Word, browser, notes) has focus. Callbacks only enqueue commands; the
engine thread consumes them (thread safety, blueprint section 11).
"""

from __future__ import annotations

from pynput import keyboard


def to_pynput_combo(combo: str) -> str:
    """'ctrl+alt+space' -> '<ctrl>+<alt>+<space>'; single letters stay bare.

    pynput's parser wants '<ctrl>+<alt>+r' — letters are keys by character,
    named keys (space, arrows, F-keys, modifiers) are bracketed.
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"empty hotkey combo: {combo!r}")
    out = []
    for part in parts:
        named = part in _NAMED_KEYS or len(part) > 1
        out.append(f"<{part}>" if named else part)
    return "+".join(out)


_NAMED_KEYS = {
    "space", "tab", "enter", "esc", "escape", "backspace", "delete", "home",
    "end", "page_up", "page_down", "insert",
    "left", "right", "up", "down",
    "shift", "ctrl", "alt", "cmd", "alt_gr", "cmd_ctrl", "caps_lock",
}


class HotkeyManager:
    """Maps config hotkey combos to actions delivered as callback(action_name)."""

    def __init__(self, bindings: dict[str, str], on_action):
        self._on_action = on_action
        self._listener = None
        hotkeys = {}
        for action, combo in bindings.items():
            if not combo:
                continue
            try:
                pynput_combo = to_pynput_combo(combo)
                keyboard.HotKey.parse(pynput_combo)  # validate before listening
                hotkeys[pynput_combo] = (lambda a=action: on_action(a))
            except (ValueError, KeyError, Exception):
                continue  # unparseable combo: skip rather than crash
        self._hotkeys = hotkeys

    def start(self) -> None:
        if self._listener is None and self._hotkeys:
            self._listener = keyboard.GlobalHotKeys(self._hotkeys)
            self._listener.daemon = True
            self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
