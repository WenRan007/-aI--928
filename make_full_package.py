from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


APP = Path(r"C:\Users\qqq\Desktop\常客AI2.2")
WORK = Path(r"C:\Users\qqq\Documents\ChatGPT\ADC")
OUT = Path(r"C:\Users\qqq\Desktop\常客AI2.2-完整安装包-本地模型和源码.zip")
VERSION = "2.2.10"
TEAM_CONFIG = {
    "whisper_model": "models_cache/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120",
    "whisper_device": "cuda",
    "whisper_compute_type": "int8_float16",
    # This value controls the number of model copies in the legacy payload.
    # The compatible core clamps it to one as well; keep the distributed
    # config conservative for older cores and CPU-only team computers.
    "asr_parallel": 1,
    "translation_parallel": 10,
    "translation_engine": "deepseek",
    "ollama_host": "http://127.0.0.1:11434",
    "ollama_model": "qwen2.5:3b",
    "ollama_executable": "runtime/ollama/ollama.exe",
    "ollama_models_dir": "runtime/ollama-models",
    "ollama_num_gpu": 0,
    "deepseek_model": "deepseek-flash",
    "deepseek_endpoint": "https://api.deepseek.com/chat/completions",
    "deepseek_timeout": 90,
    "cuda_dir": "runtime/cuda",
}

# Private data and generated test output are not part of a distributable app.
EXCLUDED_NAMES = {
    "deepseek_api_key.txt",
    "deepl_api_key.txt",
    "openai_api_key.txt",
    "aliyun_access_key.txt",
    "foreign_video_errors.log",
}
EXCLUDED_DIRS = {
    "temp_audio",
    "update_backups",
    "translation_smoke_227",
    ".git",
    "__pycache__",
    "build",
    "dist",
    "models_cache",  # excluded only while collecting source trees
}
SOURCE_SUFFIXES = {".py", ".pyc", ".ps1", ".bat", ".spec", ".md", ".json", ".txt"}


def add_file(z: zipfile.ZipFile, path: Path, arcname: str, seen: set[str]) -> None:
    key = arcname.replace("\\", "/")
    if key in seen or not path.is_file():
        return
    if path.name in EXCLUDED_NAMES:
        return
    z.write(path, key)
    seen.add(key)


def add_app(z: zipfile.ZipFile, seen: set[str]) -> int:
    count = 0
    for path in APP.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(APP)
        if path.name in EXCLUDED_NAMES or path.name == "translation_config.json" or any(part in EXCLUDED_DIRS - {"models_cache"} for part in rel.parts):
            continue
        add_file(z, path, str(Path("常客AI2.2") / rel), seen)
        count += 1
    # Replace the legacy config in the archive only. The on-disk installation
    # is left untouched; the compatible core performs a second runtime check.
    config_key = "常客AI2.2/translation_config.json"
    if config_key in seen:
        seen.remove(config_key)
    z.writestr(config_key, json.dumps(TEAM_CONFIG, ensure_ascii=False, indent=2) + "\n")
    seen.add(config_key)
    # The package is an explicitly versioned, clean distribution. This file
    # is written into the archive only and does not modify the user's install.
    z.writestr(
        "常客AI2.2/version.json",
        json.dumps({"app_id": "changke-ai", "version": VERSION}, ensure_ascii=False, indent=2),
    )
    return count


def add_source_tree(z: zipfile.ZipFile, source: Path, prefix: str, seen: set[str]) -> int:
    count = 0
    for path in source.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        rel = path.relative_to(source)
        if path.name in EXCLUDED_NAMES or any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        add_file(z, path, str(Path("源码") / prefix / rel), seen)
        count += 1
    return count


def add_selected_root_sources(z: zipfile.ZipFile, seen: set[str]) -> int:
    count = 0
    # These are the latest local patch/update sources used by the installed app.
    names = [
        "sticker_enhancements.py", "online_updater.py", "online_updater.spec",
        "常客AI在线更新.bat", "translation_runtime.py", "translation_highlights.py",
        "local_translation.py", "translator_desktop.py", "deepseek_translation.py",
        "desktop_account.py", "desktop_account_ui.py", "dedup_preview.py",
        "effect_library.py", "effect_picker.py", "modal_drawer.py",
        "package_self_check.py", "translation_config.json", "README_DESKTOP.md",
    ]
    for name in names:
        path = WORK / name
        if path.is_file():
            add_file(z, path, str(Path("源码") / "本机最新源文件" / name), seen)
            count += 1
    for path in (WORK / "updater_release").glob("*.py"):
        add_file(z, path, str(Path("源码") / "在线更新器" / path.name), seen)
        count += 1
    return count


def main() -> None:
    if not (APP / "_internal").is_dir() or not (APP / "models_cache").is_dir():
        raise SystemExit("完整安装目录缺少 _internal 或 models_cache")
    OUT.unlink(missing_ok=True)
    seen: set[str] = set()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        app_count = add_app(z, seen)
        source_count = add_source_tree(z, WORK / "changke-ai-windows", "changke-ai-windows", seen)
        patch_count = add_source_tree(z, WORK / "patch_sticker_22", "补丁源码", seen)
        extra_count = add_selected_root_sources(z, seen)
        z.writestr(
            "安装说明.txt",
            "常客AI 2.2.10 完整安装包\n\n"
            "1. 解压后双击 常客AI2.2\\常客AI2.2.exe。\n"
            "2. 首次启动按提示输入 DeepSeek API Key；本包不包含任何私人密钥。\n"
            "3. 常客AI2.2 目录已包含本地 faster-whisper 模型、CUDA/FFmpeg 运行库和贴纸库。\n"
            "4. 本版核心会自动检测 NVIDIA CUDA；不可用时自动改用 CPU/int8，并且只加载一个 Whisper 模型副本，避免团队电脑因内存不足无法识别。\n"
            "5. 源码位于 源码 目录。更新时请使用 常客AI在线更新.bat。\n",
        )
    digest = hashlib.sha256()
    with OUT.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    print(json.dumps({"path": str(OUT), "size": OUT.stat().st_size, "sha256": digest.hexdigest(), "app_files": app_count, "source_files": source_count + patch_count + extra_count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
