# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata
ROOT = Path(r"C:\Users\qqq\Documents\ChatGPT\ADC")
PATCH = ROOT / "patch_sticker_22"
ASSETS = Path(r"C:\Users\qqq\Desktop\常客AI2.2\_internal\assets")
datas = [(str(ASSETS), "assets"), (str(PATCH / "translator_desktop_patched.pyc"), ".")]
for package in ("faster_whisper", "edge_tts"):
    try: datas += collect_data_files(package)
    except Exception: pass
for package in ("faster-whisper", "ctranslate2", "edge-tts"):
    try: datas += copy_metadata(package)
    except Exception: pass
binaries = collect_dynamic_libs("ctranslate2")
pathex = [str(PATCH), str(ROOT), str(ROOT / "changke-ai-windows")]
a = Analysis([str(PATCH / "patched_entry.py")], pathex=pathex, binaries=binaries, datas=datas,
             hiddenimports=["asyncio", "ctypes", "hashlib", "json", "math", "os", "queue", "re", "shutil", "subprocess", "tempfile", "threading", "time", "wave", "sys", "random", "secrets", "traceback", "urllib.parse", "urllib.request", "concurrent.futures", "dataclasses", "pathlib", "typing", "tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.simpledialog", "tkinter.ttk", "tkinter.font", "faster_whisper", "ctranslate2", "edge_tts", "av", "PIL.ImageTk",
                            "deepseek_translation", "local_translation", "translation_runtime",
                            "translation_highlights", "dedup_preview", "modal_drawer", "effect_library", "effect_picker",
                            "sticker_enhancements", "package_self_check", "performance_checks.translation_batch_check", "PIL.ImageSequence"],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=["argostranslate", "torch", "torchaudio", "torchvision", "transformers",
                       "ctranslate2.converters", "ctranslate2.specs", "tensorflow", "scipy",
                       "spacy", "pandas", "matplotlib", "IPython", "pytest"],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="常客AI核心", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False)
COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="常客AI核心")


