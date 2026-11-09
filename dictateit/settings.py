"""Settings: defaults, JSON load/save, and profiles.

Everything the blueprint marks configurable lives here. config.json in the
project root overrides the defaults; profiles override a subset at runtime.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

DEFAULT_CONFIG: dict = {
    "locale": "en_uk",  # "en_uk" | "en_us"
    "audio": {
        "backend": "pyttsx3",  # "pyttsx3" | "piper" | "edge"
        "normal_wpm": 190,
        "slow_factor_text": 0.75,
        "slow_factor_math": 0.65,
        "piper_voice": "voices/en_GB-alan-low.onnx",
        "edge_voice": "en-GB-RyanNeural",
    },
    "text": {
        "repeat_count": 2,
        "pause_between_repeats_s": 0.8,
        "gap_base_s": 1.0,
        "gap_per_word_s": 0.5,
        "max_chunk_words": 8,
        "min_chunk_words": 2,
        "say_punctuation": True,
    },
    "math": {
        "ambiguous_detection": "ask",  # "ask" | "text" | "math"
        "bracket_word": "bracket",     # UK; US pack says "parenthesis"
        "multiply_word": "times",
        "unary_minus_word": "minus",
        "fraction_style": "over",
        "number_style": "words",       # "words" | "digits"
        "announce_case": "when_ambiguous",  # "always" | "when_ambiguous" | "never"
        "repeat_count": 2,
        "slow_speed": 0.65,
        "gap_base_s": 1.5,
        "gap_per_token_s": 0.8,
        "max_chunk_tokens": 6,
        "third_pass": "on_request",    # symbol-by-symbol re-read
    },
    "hotkeys": {
        "toggle": "ctrl+alt+space",
        "repeat": "ctrl+alt+r",
        "previous": "ctrl+alt+left",
        "next": "ctrl+alt+right",
        "slower": "ctrl+alt+down",
        "faster": "ctrl+alt+up",
        "spell": "ctrl+alt+s",
        "symbols": "ctrl+alt+m",
        "equation": "ctrl+alt+e",
        "preview": "ctrl+alt+f",
    },
    "custom_names": ["cost", "Var"],
    "timing": {
        "spell_gap_s": 0.35,      # gap between spoken letters
        "symbols_gap_s": 0.4,     # gap between symbols in pass 3
        "equation_gap_s": 0.5,    # gap between chunks of a whole-equation re-read
    },
    "adaptive_pacing": {
        "enabled": False,   # opt-in; never records key values, only timing
        "idle_ms": 1500,
        "max_extension_s": 10.0,
    },
    "active_profile": "default",
    "profiles": {
        "default": {
            "say_punctuation": True,
            "show_preview": True,
            "third_pass": "on_request",
        },
        "exam": {
            "say_punctuation": True,
            "show_preview": False,
            "third_pass": "off",
            "slow_factor_text": 0.7,
            "slow_factor_math": 0.6,
        },
        "practice": {
            "say_punctuation": True,
            "show_preview": True,
            "third_pass": "on_request",
            "repeat_count": 3,
        },
        "proofread": {
            "say_punctuation": False,
            "show_preview": False,
            "repeat_count": 1,
            "gap_base_s": 0.3,
            "gap_per_word_s": 0.1,
        },
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """Merge override into a deep copy of base (nested dicts, not lists)."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Settings:
    """Typed-ish access to the config with profile support."""

    def __init__(self, data: dict | None = None, path: Path | None = None):
        self.path = Path(path) if path else Path("config.json")
        self._data = deep_merge(DEFAULT_CONFIG, data or {})
        self.apply_profile(self._data.get("active_profile", "default"))

    # -- loading / saving -------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        p = Path(path) if path else Path("config.json")
        data = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        return cls(data, path=p)

    def save(self, path: Path | None = None) -> None:
        p = Path(path) if path else self.path
        p.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- access -----------------------------------------------------------
    def get(self, dotted: str, default=None):
        node: object = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value) -> None:
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    # -- profiles -----------------------------------------------------------
    def apply_profile(self, name: str) -> None:
        profiles = self._data.get("profiles", {})
        if name in profiles:
            # Profile overrides are applied on top of the *base* sections,
            # so switching profiles twice never accumulates overrides.
            base = deep_merge(DEFAULT_CONFIG, {
                k: v for k, v in self._data.items() if k != "profiles"
            })
            merged = deep_merge(base, profiles[name])
            merged["active_profile"] = name
            self._data = merged
        else:
            self._data["active_profile"] = "default"

    @property
    def profile(self) -> str:
        return self._data.get("active_profile", "default")

    # -- derived values -------------------------------------------------
    def slow_factor(self, kind: str) -> float:
        if kind == "math":
            return float(self.get("math.slow_speed", 0.65))
        return float(self.get("audio.slow_factor_text", 0.75))

    def gap_for(self, kind: str, size: int, extra_s: float = 0.0) -> float:
        if kind == "math":
            g = float(self.get("math.gap_base_s", 1.5)) + float(
                self.get("math.gap_per_token_s", 0.8)) * size
        else:
            g = float(self.get("text.gap_base_s", 1.0)) + float(
                self.get("text.gap_per_word_s", 0.5)) * size
        return g + extra_s
