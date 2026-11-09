# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DictateIt.

Build (from the repo root, venv active):
    python -m PyInstaller dictateit.spec --noconfirm

Output: dist/dictateit/dictateit.exe (onedir — one folder, one exe).

Notes:
- speech_data/*.json are bundled as data files; speech.py finds them
  next to the dictateit package, which is where datas puts them.
- piper-tts / edge-tts / miniaudio are optional and imported lazily;
  they are deliberately NOT hiddenimports so the exe builds and runs
  without them (the backends raise BackendUnavailable instead).
- pynput (hotkeys, typing monitor), matplotlib (formula preview) and
  pyttsx3 are discovered automatically from the lazy imports.
"""

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[("dictateit/speech_data", "dictateit/speech_data")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dictateit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,        # the status line is useful; windowed later
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="dictateit",
)
