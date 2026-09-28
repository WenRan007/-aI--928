"""Portable entry point for the additive 2.2.3 sticker patch."""

from __future__ import annotations

import marshal
import os
import pathlib
import sys
import types


_DLL_HANDLES = []


def _prepare_cuda_runtime() -> None:
    """Expose bundled CUDA DLLs before faster-whisper/ctranslate2 imports."""
    app_dir = pathlib.Path(sys.executable).resolve().parent
    candidates = [
        app_dir / "_internal" / "runtime" / "cuda",
        app_dir / "_internal" / "ctranslate2",
        app_dir / "_internal" / "cuda",
        app_dir / "cuda",
        app_dir / "_internal",
        app_dir,
    ]
    found = []
    for directory in candidates:
        if not directory.is_dir():
            continue
        value = str(directory)
        if value in found:
            continue
        found.append(value)
        try:
            if hasattr(os, "add_dll_directory"):
                _DLL_HANDLES.append(os.add_dll_directory(value))
        except (OSError, AttributeError):
            pass
    if found:
        os.environ["PATH"] = os.pathsep.join(found + [os.environ.get("PATH", "")])


def _load_code() -> tuple[object, pathlib.Path]:
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(pathlib.Path(sys._MEIPASS) / "translator_desktop_patched.pyc")
    candidates.append(pathlib.Path(__file__).with_name("translator_desktop_patched.pyc"))
    for path in candidates:
        if path.exists():
            data = path.read_bytes()
            return marshal.loads(data[16:] if len(data) >= 16 else data), path
    raise FileNotFoundError("translator_desktop_patched.pyc")


def _run() -> int:
    _prepare_cuda_runtime()
    code, source_path = _load_code()
    module_name = "translator_desktop_runtime"
    module = types.ModuleType(module_name)
    module.__file__ = str(source_path)
    module.__package__ = None
    module.__spec__ = None
    sys.modules[module_name] = module
    exec(code, module.__dict__, module.__dict__)

    # The original 2.2 payload used ``asr_parallel`` as Whisper's
    # ``num_workers`` value.  A value of 10 creates ten model instances and
    # exhausts RAM/VRAM on most team machines.  Keep task-level parallelism in
    # the app queue, but load exactly one model and choose CUDA only when the
    # bundled runtime reports a usable NVIDIA device.
    def _portable_model_path(backend):
        from pathlib import Path
        configured = str(getattr(backend, "_model_name", "") or "").strip()
        if configured and Path(configured).is_dir():
            return configured
        root = Path(getattr(backend, "_model_cache_dir", Path(sys.executable).parent / "models_cache"))
        aliases = []
        if configured:
            aliases.append(configured.lower())
        aliases.extend(("small", "large-v3-turbo", "large-v3"))
        for model_dir in sorted(root.glob("models--*")):
            if not model_dir.is_dir():
                continue
            name = model_dir.name.lower()
            if not any(alias in name for alias in aliases):
                continue
            for snapshot in sorted((model_dir / "snapshots").glob("*"), reverse=True):
                if (snapshot / "model.bin").is_file():
                    return str(snapshot)
        return configured or "small"

    def _safe_prepare_recognition_model(self):
        from faster_whisper import WhisperModel
        import ctranslate2

        with self._model_lock:
            if self._whisper is not None:
                return self._whisper
            model_path = _portable_model_path(self)
            self._model_name = model_path
            logical = os.cpu_count() or 4
            cpu_threads = max(1, min(8, logical - 2 if logical > 2 else logical))
            cuda_count = 0
            try:
                cuda_count = int(ctranslate2.get_cuda_device_count())
            except Exception:
                cuda_count = 0
            configured = str(getattr(self, "asr_device", "cuda") or "cuda").lower()
            attempts = []
            if configured != "cpu" and cuda_count > 0:
                attempts.append(("cuda", "int8_float16"))
            attempts.append(("cpu", "int8"))
            last_error = None
            for device, compute_type in attempts:
                try:
                    self._whisper = WhisperModel(
                        model_path,
                        device=device,
                        compute_type=compute_type,
                        cpu_threads=cpu_threads,
                        # Never duplicate the full model for task parallelism.
                        num_workers=1,
                        download_root=str(getattr(self, "_model_cache_dir", pathlib.Path(sys.executable).parent / "models_cache")),
                        local_files_only=True,
                    )
                    self.asr_device = device
                    self.asr_compute_type = compute_type
                    self.asr_status = f"{device} / {compute_type}"
                    return self._whisper
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    self._whisper = None
            raise RuntimeError(
                f"本地 Whisper 模型启动失败：{last_error}\n"
                f"已检查模型路径：{model_path}\n"
                "请确认完整解压安装包，不要只复制 exe 文件。"
            )

    if hasattr(module, "TranslationBackend"):
        module.TranslationBackend.prepare_recognition_model = _safe_prepare_recognition_model

    from sticker_enhancements import install
    install(module.__dict__)
    args = sys.argv[1:]
    if args and args[0] == "--self-check":
        from package_self_check import run
        return int(run(module, args[1] if len(args) > 1 else "self_check"))
    if args and args[0] == "--translation-check":
        from performance_checks.translation_batch_check import run
        return int(run(module, args[1] if len(args) > 1 else "translation_check"))
    module.TranslatorApp().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
