# DictateIt

Text-to-speech dictation for people who **write while listening** — supports
algebra, worked examples, proofs. It reads assignments in short chunks,
says everything twice (once naturally, once slowly and explicitly), and
leaves a silent gap sized to what you have to write down.

## Features

- **Phrase chunking** — prose in 3–8 word chunks at natural pause points; math in ≤6-token chunks split on the AST
- **Double take** — every chunk twice: natural pass at normal speed, then a slow explicit pass that names every structure ("numerator", "end power", "close bracket")
- **Write gaps** — silence after each chunk, scaled to words (text) or tokens (math) plus extra time for structures you must draw (fractions, matrices)
- **Spoken punctuation and spelling** — "comma", "full stop", "new paragraph" on the slow pass; spell-the-last-word command
- **Math dictation** — LaTeX (`$...$`, `\(..\)`), plain text (`x^2 + 3x = 0`) and Unicode (`x² + 3x − 4 = 0`) all reach the same AST; fractions, roots, powers, subscripts, big operators, matrices and multi-line derivations ("line one… line two…")
- **Global hotkeys** — pause, repeat, previous/next, slower/faster, spell, symbol-by-symbol, whole-equation re-read; all remappable
- **Control window** — small always-on-top tkinter remote with a rendered formula preview, profile switcher and hide-text toggle
- **Adaptive pacing** (opt-in) — keystroke *timing only* extends the write gap while you are still writing; key values are never read
- **Voice backends** — pyttsx3 (offline, default), Piper (offline neural), edge-tts (online neural); swappable behind one interface
- **Word support** — dictate straight from `.docx` equation objects (OMML → LaTeX → the same AST), plus `.txt` / `.md` / `.tex` / stdin
- **UK/US speech packs** — "full stop" vs "period", "zed" vs "zee"; switchable at runtime
- **Profiles** — default / exam (no preview) / practice (3 repeats) / proofread

## How it sounds

```
Solve x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
```
becomes:

| # | Pass 1 (natural) | Pass 2 (explicit, slow) |
|---|------------------|--------------------------|
| 1 | ex equals | ex, equals |
| 2 | fraction minus bee | fraction, numerator, minus, bee |
| 3 | plus or minus square root of open bracket bee squared minus four ay see close bracket | plus or minus, square root of, open bracket, bee, squared, minus, four, ay, see, close bracket |
| 4 | over two ay end fraction | end numerator, over, denominator, two, ay, end fraction |

## Quick start

Requires Windows (SAPI5/winsound) and Python 3.12+.

```powershell
git clone https://github.com/Arp1tSingh/dictateit.git
cd dictateit
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m dictateit.main --input notes.txt --ui
```

Optional voice upgrades (see *requirements.txt* for the full list):

```powershell
.venv\Scripts\pip install edge-tts miniaudio   # online neural voices
.venv\Scripts\pip install piper-tts            # offline neural voices
```

```powershell
# see the chunk plan without any audio
python -m dictateit.main --input notes.txt --list-chunks
# walk the plan through the engine silently
python -m dictateit.main --input notes.txt --dry-run
# keyboard controls in the terminal instead of global hotkeys
python -m dictateit.main --input notes.txt --cli
```

Inputs: `.txt`, `.md`, `.tex`, `.docx` (Word equations are extracted and
dictated properly), or `--stdin`.

## Controls

| Action | Default hotkey | UI button |
|---|---|---|
| Start / pause / resume | Ctrl+Alt+Space | Pause |
| Repeat this chunk | Ctrl+Alt+R | Repeat |
| Previous / next chunk | Ctrl+Alt+Left / Right | « / » |
| Slower / faster | Ctrl+Alt+Down / Up | − / + |
| Spell the last word | Ctrl+Alt+S | Spell |
| Symbol-by-symbol re-read | Ctrl+Alt+M | Symbols |
| Re-read the whole equation | Ctrl+Alt+E | Equation |
| Show / hide formula preview | Ctrl+Alt+F | — |

All hotkeys are remappable in `config.json`.

## How it works

```
input text
    │
    ▼
Normalizer      smart quotes, "e.g.", "&", whitespace, unicode math chars
    │
    ▼
Segmenter       prose | explicit math ($...$, \(..\), \begin{..}) | detected plain math
    │
    ▼
┌───────────────────────────────┬──────────────────────────────────┐
│ text chunks                   │ math pipeline                    │
│ sentences → clauses → chunks  │ parser → AST → verbalizer        │
│ (8 words max, min 2)          │ → chunker (relations end chunks, │
│                               │  +/- starts chunks, fractions    │
│                               │  split by parts, matrices by row)│
└───────────────┬───────────────┴──────────────┬───────────────────┘
                ▼                              ▼
            Chunk objects (kind, three spoken forms, size, display_latex)
                │
                ▼
            Engine (state machine thread)
            natural pass → pause → explicit pass → write gap
                │                                    ▲
                ▼                                    │
            TTS backend (pyttsx3 / piper / edge / fake)   TypingMonitor (opt-in)
```

One `Chunk` model feeds the engine regardless of origin; one AST feeds the
verbalizer regardless of input format (LaTeX, plain text, Unicode, OMML).

## Architecture decisions worth knowing

**The parser never simplifies or reorders.** `3x + x^2` is dictated as
written, `(2x)` grouped by precedence. sympy is a test-only dependency:
it would reorder terms, which is wrong for someone copying left to right.

**Chunking works on the AST, not the spoken string.** Size is measured in
*tokens* (numbers, variables, operators, brackets), max 6 for math. A
split never happens inside a bracket group that fits in one chunk; the
chunker verbalizes at split time, so chunk boundaries always fall on
structure the writer can see.

**Ambiguity is flagged, never guessed silently.** Plain-text math is
read strict left-to-right: `1/2x` is `(1/2)·x`, `dy/dx` is `(dy/d)·x`,
`a/b*c` is `(a/b)·c`. All three are flagged (⚠ in the UI), and the flag
propagates to every chunk they produce. The derivative reading comes
only from the LaTeX form `\frac{dy}{dx}`. Parser failure is not fatal:
the fallback reads raw symbols and flags it.

**The double take is contract, not convention.** Both passes say
structure markers ("end power", "new line"); the explicit pass names
*everything* (numerator/denominator words, commas between tokens) at
~0.65× speed. The natural pass stays fluent ("over", no commas).

**Relations end chunks; `±` starts one.** "x equals" | "five" — the
writer hears the relation, then what to write. The same rule puts every
additive operator at the *start* of the chunk that needs it.

**Threads and queues everywhere.** pynput callbacks and UI buttons only
enqueue commands; the engine thread is the sole consumer. The Tk window
never receives engine calls on the Tk thread — state is pushed to a
queue and polled with `after`. Hotkeys therefore never stutter playback,
and the window never freezes during a write gap.

**pyttsx3 quirks are contained in its backend.** It cannot stop cleanly
mid-sentence and must not be driven from two threads, so its backend
owns one worker thread and exposes only the tiny `TTSBackend` interface
(`start_speak` / `is_speaking` / `stop`). Piper and edge-tts render
audio data instead, with playback handled by `audio_play.py` — same
interface, different mechanism, engine unchanged.

**The typing monitor is privacy-strict and opt-in.** It records
keystroke *timestamps only* — key values are discarded in the listener
callback before anything is stored. Off by default
(`adaptive_pacing.enabled`), announced when enabled, and it extends write
gaps only while you are actively typing (capped by
`adaptive_pacing.max_extension_s`).

**No heavy optional dependencies in the core.** `.docx` support uses the
stdlib (a docx is zipped XML); OMML → LaTeX feeds the existing parser
instead of a second math pipeline. piper-tts, edge-tts, and miniaudio
are lazy imports that raise a clean `BackendUnavailable` with install
instructions. matplotlib is needed only for the formula preview.

## Speech packs and locales

Both `en_uk` ("full stop", "square bracket", "zed") and `en_us`
("period", "parenthesis", "zee") ship in `dictateit/speech_data/`; pick
with `--locale` or `config.json` (`locale`). Letter respellings live in
`letters.json` (with per-locale overrides) because TTS engines misread
single letters ("a" → "ay", "x" → "ex", "z" → "zed").

Profiles (`default`, `exam`, `practice`, `proofread`) override gaps,
repeats, preview visibility and punctuation speech. Exam mode hides the
preview; study mode shows it.

## Building the exe

```powershell
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python -m PyInstaller dictateit.spec --noconfirm
# → dist\dictateit\dictateit.exe
```

Onefolder build (~90 MB with matplotlib and pyttsx3 bundled; console
window kept for the status line). Piper/edge voices are **not** bundled:
download a Piper `.onnx` voice into `voices/` and point
`audio.piper_voice` at it, or install `edge-tts` + `miniaudio` and set
`audio.backend`.

## Project structure

```
dictateit/
├── dictateit/
│   ├── main.py            # CLI entry: --input/--stdin/--ui/--cli/--dry-run
│   ├── pipeline.py        # normalize → segment → chunk → fold → renumber
│   ├── chunker.py         # text chunking (sentences → clauses → chunks)
│   ├── normalizer.py      # quotes, "e.g.", "&", unicode math characters
│   ├── models.py          # the Chunk dataclass
│   ├── engine.py          # playback state machine (double take, gaps)
│   ├── hotkeys.py         # pynput global hotkeys
│   ├── typing_monitor.py  # adaptive pacing (timing only, opt-in)
│   ├── spelling.py        # letter-by-letter respellings
│   ├── settings.py        # config.json, profiles
│   ├── speech.py          # speech pack loading
│   ├── loader.py          # .txt/.md/.tex/.docx input
│   ├── math/              # segmenter, parser, verbalizer, math_chunker,
│   │                      #   ast_nodes, normalize_math, omml, preview
│   ├── tts/               # pyttsx3 / piper / edge / fake backends + playback
│   ├── ui/                # tkinter control window
│   └── speech_data/       # en_uk.json, en_us.json, letters.json
├── tests/                 # 370+ tests incl. a 44-formula corpus
├── run.py                 # PyInstaller entry point
└── dictateit.spec         # PyInstaller build spec
```

## Development

```powershell
.venv\Scripts\python -m pytest tests/ -q      # 370+ tests
```

The 44-formula corpus (`tests/formulas_corpus.json`) asserts that the
same formula in LaTeX, plain text and Unicode produces identical ASTs,
with sympy-based numeric equivalence spot checks (tests only).

## License

[MIT](LICENSE) © Arpit Singh

