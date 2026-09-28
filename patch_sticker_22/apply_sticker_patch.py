from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox


PATCH_VERSION = "2.2.9-core-bootstrap"
CORE_NAME = "常客AI核心.exe"
LAUNCHER_NAME = "常客AI2.2.exe"
PATCHED_PYC_NAME = "translator_desktop_patched.pyc"


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def candidate_dirs() -> list[Path]:
    home = Path.home()
    candidates = [
        home / "Desktop" / "常客AI2.2",
        home / "桌面" / "常客AI2.2",
        Path.cwd() / "常客AI2.2",
        Path.cwd(),
    ]
    seen: set[Path] = set()
    result: list[Path] = []
    for item in candidates:
        item = item.resolve()
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def is_target_dir(folder: Path) -> bool:
    # The core executable may be absent on an older team copy; the patch
    # carries a fresh one and can bootstrap it as long as the one-folder
    # runtime (_internal) and launcher are present.
    return (folder / "_internal").is_dir() and (
        (folder / CORE_NAME).is_file() or (folder / LAUNCHER_NAME).is_file()
    )


def find_target_near(folder: Path) -> Path | None:
    """Find the actual portable root when the zip was extracted one level deep."""
    folder = folder.resolve()
    roots = [folder, folder.parent]
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in [root, *root.iterdir()]:
            if candidate in seen or not candidate.is_dir():
                continue
            seen.add(candidate)
            if is_target_dir(candidate):
                return candidate
            # Common extraction layout: Desktop\常客AI2.2\常客AI2.2\...
            try:
                for nested in candidate.iterdir():
                    if nested.is_dir() and is_target_dir(nested):
                        return nested
            except OSError:
                pass
    return None


def detect_target() -> Path:
    for folder in candidate_dirs():
        found = find_target_near(folder)
        if found is not None:
            return found
    return candidate_dirs()[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stop_running_app() -> None:
    # The patch targets the portable 2.2 package. taskkill is used only for
    # these two exact image names so the files are not locked during replace.
    for image in (CORE_NAME, LAUNCHER_NAME):
        subprocess.run(
            ["taskkill", "/IM", image, "/F", "/T"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    time.sleep(0.8)


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=target.name + ".", suffix=".new", dir=target.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def apply_patch(target: Path) -> tuple[Path, Path]:
    source_dir = bundle_dir()
    source_core = source_dir / CORE_NAME
    source_pyc = source_dir / PATCHED_PYC_NAME
    resolved = find_target_near(target)
    if resolved is not None:
        target = resolved
    target_core = target / CORE_NAME
    target_pyc = target / "_internal" / PATCHED_PYC_NAME
    target_internal = target / "_internal"

    if not source_core.is_file() or not source_pyc.is_file():
        raise FileNotFoundError("补丁包内容不完整，请重新下载补丁包。")
    if not target_internal.is_dir():
        missing = []
        missing.append("_internal")
        raise FileNotFoundError(
            f"未找到常客AI2.2完整软件目录：{target}\n"
            f"缺少：{'、'.join(missing)}\n\n"
            "请先解压完整软件包，再选择包含常客AI核心.exe和_internal的那一层目录；"
            "不要选择只包含补丁文件的文件夹。"
        )

    stop_running_app()
    backup_dir = target / "update_backups" / ("sticker_patch_" + time.strftime("%Y%m%d_%H%M%S"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    if target_core.exists():
        shutil.copy2(target_core, backup_dir / CORE_NAME)
    if target_pyc.exists():
        shutil.copy2(target_pyc, backup_dir / PATCHED_PYC_NAME)

    atomic_copy(source_core, target_core)
    atomic_copy(source_pyc, target_pyc)
    return backup_dir, target_core


def launch_updated_app(target: Path) -> None:
    launcher = target / LAUNCHER_NAME
    executable = launcher if launcher.is_file() else target / CORE_NAME
    subprocess.Popen([str(executable)], cwd=str(target), close_fds=True)


class PatchWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("常客AI · 翻译运行库修复补丁")
        self.root.geometry("600x250")
        self.root.resizable(False, False)
        self.root.configure(bg="#111521")
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

        tk.Label(
            self.root,
            text="常客AI 2.2 翻译运行库修复补丁",
            fg="#ffffff",
            bg="#111521",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w", padx=26, pady=(22, 5))
        tk.Label(
            self.root,
            text="自动识别常客AI目录；即使缺少常客AI核心.exe，也会用补丁内置核心自动补齐，同时修复 CUDA 运行库加载并保留贴纸功能。",
            fg="#aeb8d0",
            bg="#111521",
            wraplength=540,
            justify="left",
        ).pack(anchor="w", padx=26, pady=(0, 16))

        row = tk.Frame(self.root, bg="#111521")
        row.pack(fill="x", padx=26)
        self.target_var = tk.StringVar(value=str(detect_target()))
        tk.Entry(row, textvariable=self.target_var, width=55, bg="#1b2130", fg="#ffffff", insertbackground="#ffffff").pack(side="left", ipady=5)
        tk.Button(row, text="选择目录", command=self.choose_dir, width=10).pack(side="left", padx=(8, 0))

        self.restart_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            self.root,
            text="更新完成后启动常客AI",
            variable=self.restart_var,
            fg="#dbe4ff",
            bg="#111521",
            activebackground="#111521",
            activeforeground="#ffffff",
            selectcolor="#1b2130",
        ).pack(anchor="w", padx=26, pady=(15, 0))
        self.status = tk.StringVar(value="准备就绪")
        tk.Label(self.root, textvariable=self.status, fg="#8fe6c4", bg="#111521").pack(anchor="w", padx=26, pady=(4, 4))
        tk.Button(self.root, text="开始更新", command=self.start, width=14, bg="#6f54ed", fg="#ffffff", activebackground="#846df5").pack(anchor="e", padx=26, pady=(0, 18))

    def choose_dir(self) -> None:
        selected = filedialog.askdirectory(title="选择常客AI2.2安装目录")
        if selected:
            self.target_var.set(selected)

    def start(self) -> None:
        if hasattr(self, "worker") and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def _run(self) -> None:
        target = Path(self.target_var.get().strip().strip('"')).expanduser()
        self.root.after(0, lambda: self.status.set("正在关闭程序并创建备份…"))
        try:
            backup, _ = apply_patch(target)
            self.root.after(0, lambda: self.status.set("更新完成，正在校验文件…"))
            source_dir = bundle_dir()
            expected_core = sha256(source_dir / CORE_NAME)
            expected_pyc = sha256(source_dir / PATCHED_PYC_NAME)
            if sha256(target / CORE_NAME) != expected_core or sha256(target / "_internal" / PATCHED_PYC_NAME) != expected_pyc:
                raise RuntimeError("文件校验失败，已保留原文件备份，请不要继续启动。")
            if self.restart_var.get():
                launch_updated_app(target)
            self.root.after(0, lambda: messagebox.showinfo("更新完成", f"常客AI更新完成。\n\n备份位置：\n{backup}\n\n核心程序已自动补齐，CUDA DLL 搜索路径、翻译和贴纸功能均已保留。"))
            self.root.after(0, self.root.destroy)
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, lambda: messagebox.showerror("更新失败", str(exc)))
            self.root.after(0, lambda: self.status.set("更新失败，请检查安装目录"))

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    PatchWindow().run()
