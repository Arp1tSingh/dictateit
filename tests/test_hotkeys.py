"""Hotkey tests: combo parsing and binding construction (no global listener)."""

import pytest

from dictateit.hotkeys import HotkeyManager, to_pynput_combo
from dictateit.settings import DEFAULT_CONFIG


def test_combo_parsing():
    assert to_pynput_combo("ctrl+alt+space") == "<ctrl>+<alt>+<space>"
    assert to_pynput_combo("ctrl+alt+left") == "<ctrl>+<alt>+<left>"
    assert to_pynput_combo("f9") == "<f9>"
    # single letters stay bare: pynput's parser requires '<ctrl>+<alt>+r'
    assert to_pynput_combo("ctrl+alt+r") == "<ctrl>+<alt>+r"


def test_combo_normalises_case_and_spaces():
    assert to_pynput_combo(" Ctrl + Alt + R ") == "<ctrl>+<alt>+r"


def test_empty_combo_rejected():
    with pytest.raises(ValueError):
        to_pynput_combo("+")


def test_manager_builds_bindings():
    actions = []
    mgr = HotkeyManager(DEFAULT_CONFIG["hotkeys"], actions.append)
    # listener not started (would grab global keys); construction must succeed
    assert mgr._listener is None
    assert len(mgr._hotkeys) == len([v for v in DEFAULT_CONFIG["hotkeys"].values() if v])


def test_manager_skips_unparseable():
    actions = []
    bindings = {"toggle": "ctrl+alt+space", "repeat": "not+a+combo+with+brackets"}
    mgr = HotkeyManager(bindings, actions.append)
    assert "<ctrl>" in mgr._hotkeys or len(mgr._hotkeys) >= 1
    # the malformed combo was skipped, not crashed on
    assert all("not" not in k for k in mgr._hotkeys)


def test_manager_start_stop():
    actions = []
    mgr = HotkeyManager({"toggle": "ctrl+alt+shift+f12"}, actions.append)
    try:
        mgr.start()
        assert mgr._listener is not None
    finally:
        mgr.stop()
    assert mgr._listener is None
