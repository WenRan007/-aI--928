"""Sticker-library helpers for the 2.2 Windows patch.

This module is deliberately independent from ``translator_desktop.py``.  The
compiled application can import the helpers from a replacement entry point,
or the functions can be copied into a future source build.  It keeps the
per-sticker settings beside the existing ``stickers`` directory and builds
FFmpeg arguments/filters without requiring a second rendering engine.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


# Pillow can decode more formats than FFmpeg can overlay on every build.  The
# file picker and validation use this list; FFmpeg will report a useful error
# if a particular optional codec (for example HEIC) is unavailable.
IMAGE_SUFFIXES: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".ico",
    ".avif",
    ".heic",
    ".heif",
    ".jfif",
)

STICKER_SCALE_MIN = 0.05
STICKER_SCALE_MAX = 0.20
STICKER_SCALE_DEFAULT = 0.05
STICKER_ANIMATIONS = ("静态", "滑入", "弹入", "轻微放大")
_ANIMATION_ALIASES = {
    "none": "静态",
    "static": "静态",
    "slide": "滑入",
    "slide-in": "滑入",
    "pop": "弹入",
    "pop-in": "弹入",
    "zoom": "轻微放大",
    "微放大": "轻微放大",
}


def is_supported_image(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* is one of the formats exposed by the picker."""

    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def image_filetypes() -> list[tuple[str, str]]:
    """Tkinter ``filetypes`` value shared by both sticker-library buttons."""

    patterns = " ".join(f"*{suffix}" for suffix in IMAGE_SUFFIXES)
    return [("图片（含 GIF）", patterns), ("所有文件", "*.*")]


def sticker_format(path: str | os.PathLike[str]) -> tuple[str, bool]:
    """Read the image header, rather than treating an extension as its format."""
    from PIL import Image

    try:
        with Image.open(path) as image:
            return str(image.format or "").upper(), bool(getattr(image, "is_animated", False))
    except (OSError, ValueError):
        return "", False


def is_editable_gif(path: str | os.PathLike[str]) -> bool:
    image_format, animated = sticker_format(path)
    # GIF is the user-selectable animated format.  A one-frame GIF remains
    # editable so the format rule is stable even when a design export has
    # only one frame; it is still looped safely by FFmpeg.
    return image_format == "GIF"


def _clamp_scale(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return STICKER_SCALE_DEFAULT
    return max(STICKER_SCALE_MIN, min(STICKER_SCALE_MAX, result))


def normalize_animation(value: object) -> str:
    text = str(value or "静态").strip()
    return _ANIMATION_ALIASES.get(text.lower(), text if text in STICKER_ANIMATIONS else "静态")


class StickerConfigStore:
    """Small atomic JSON store for per-sticker size and animation settings.

    The file is intentionally human-readable so a patch never needs to touch
    the user's media.  A corrupt or partially written file is ignored and
    replaced on the next save.
    """

    def __init__(self, sticker_dir: str | os.PathLike[str]):
        self.sticker_dir = Path(sticker_dir)
        self.sticker_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.sticker_dir / "sticker_config.json"
        self._values: dict[str, dict[str, object]] = {}
        self._global_scale = STICKER_SCALE_DEFAULT
        self.reload()

    def reload(self) -> dict[str, dict[str, object]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            values = raw.get("stickers", raw) if isinstance(raw, dict) else {}
            version = int(raw.get("version", 0)) if isinstance(raw, dict) else 0
            self._global_scale = _clamp_scale(raw.get("global_scale", STICKER_SCALE_DEFAULT)) if isinstance(raw, dict) else STICKER_SCALE_DEFAULT
            self._values = {
                str(name): {
                    # 2.2.3 used 10% as its implicit default.  Migrate that
                    # legacy default to the new 5% minimum once; later edits
                    # are saved with version 2 and are left untouched.
                    "scale": STICKER_SCALE_MIN if version < 2 and abs(_clamp_scale(item.get("scale")) - 0.10) < 1e-9 else _clamp_scale(item.get("scale")),
                    "animation": normalize_animation(item.get("animation")),
                }
                for name, item in values.items()
                if isinstance(item, dict)
            }
        except (OSError, ValueError, TypeError):
            self._values = {}
            self._global_scale = STICKER_SCALE_DEFAULT
        return self._values.copy()

    def get_global_scale(self) -> float:
        return _clamp_scale(self._global_scale)

    def set_global_scale(self, value: object) -> float:
        self._global_scale = _clamp_scale(value)
        self.save()
        return self._global_scale

    def get(self, name: str | os.PathLike[str]) -> dict[str, object]:
        key = Path(name).name
        value = self._values.get(key, {})
        return {
            "scale": _clamp_scale(value.get("scale", STICKER_SCALE_DEFAULT)),
            "animation": normalize_animation(value.get("animation", "静态")),
        }

    def set(self, name: str | os.PathLike[str], *, scale: object = None, animation: object = None) -> dict[str, object]:
        key = Path(name).name
        current = self.get(key)
        if scale is not None:
            current["scale"] = _clamp_scale(scale)
        if animation is not None:
            current["animation"] = normalize_animation(animation)
        self._values[key] = current
        self.save()
        return current.copy()

    def remove(self, name: str | os.PathLike[str]) -> None:
        if self._values.pop(Path(name).name, None) is not None:
            self.save()

    def prune(self, paths: Iterable[str | os.PathLike[str]]) -> None:
        names = {Path(path).name for path in paths}
        if any(name not in names for name in self._values):
            self._values = {name: value for name, value in self._values.items() if name in names}
            self.save()

    def save(self) -> None:
        self.sticker_dir.mkdir(parents=True, exist_ok=True)
        payload = {"version": 3, "global_scale": self.get_global_scale(), "stickers": self._values}
        fd, temporary = tempfile.mkstemp(prefix="sticker_config.", suffix=".tmp", dir=self.sticker_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def sticker_input_args(path: str | os.PathLike[str]) -> list[str]:
    """Return FFmpeg input arguments that keep a sticker alive.

    ``-stream_loop -1`` is required for animated GIFs.  ``-loop 1`` is used
    for still images so ``overlay=shortest=1`` can cleanly stop at the main
    video duration.  Both options are placed immediately before ``-i`` as
    required by FFmpeg's input-option parser.
    """

    source = Path(path)
    if sticker_format(source)[0] == "GIF":
        return ["-stream_loop", "-1", "-i", str(source)]
    return ["-loop", "1", "-i", str(source)]


def _even(value: float | str) -> str:
    """Return an FFmpeg expression producing a positive even pixel value."""

    return f"trunc(({value})/2)*2"


def _scale_filter(size: float, *, animated: bool = False, zoom: bool = False) -> str:
    # The main output is 720px wide.  Keep the size relative to that width,
    # while preserving each sticker's aspect ratio with ``-2``.
    base = f"720*{_clamp_scale(size):.5f}"
    if zoom:
        width = _even(f"({base})*(1+0.06*sin(2*PI*t/2))")
    elif animated:
        width = f"max(2,{_even(f'({base})*min(1,t/0.35)')})"
    else:
        width = _even(base)
    eval_arg = ":eval=frame" if animated or zoom else ""
    return f"scale=w='{width}':h=-2{eval_arg},format=rgba"


def _corner_xy(corner: int) -> tuple[str, str]:
    return (
        ("10", "10"),
        ("W-w-10", "10"),
        ("10", "H-h-10"),
        ("W-w-10", "H-h-10"),
    )[corner % 4]


def _slide_xy(corner: int) -> tuple[str, str]:
    # Each sticker enters from the nearest edge and settles into its corner.
    if corner % 4 == 0:
        return ("if(lt(t,0.45),-w+(w+10)*t/0.45,10)", "10")
    if corner % 4 == 1:
        return ("if(lt(t,0.45),W-(W-w-10)*t/0.45,W-w-10)", "10")
    if corner % 4 == 2:
        return ("10", "if(lt(t,0.45),H-(H-h-10)*t/0.45,H-h-10)")
    return ("if(lt(t,0.45),W-(W-w-10)*t/0.45,W-w-10)", "if(lt(t,0.45),H-(H-h-10)*t/0.45,H-h-10)")


def sticker_filter_chain(
    sticker_index: int,
    previous_label: str,
    output_label: str,
    *,
    size: object = STICKER_SCALE_DEFAULT,
    animation: object = "静态",
    corner: int = 0,
) -> str:
    """Build one filter-chain segment for a sticker input.

    ``sticker_index`` is the FFmpeg input index (0 is the main video), and
    labels are returned in the familiar ``[v0]``/``[v1]`` form used by the
    existing 2.2 renderer.
    """

    scale = _clamp_scale(size)
    effect = normalize_animation(animation)
    if effect == "弹入":
        prep = _scale_filter(scale, animated=True)
    elif effect == "轻微放大":
        prep = _scale_filter(scale, zoom=True)
    else:
        prep = _scale_filter(scale)
    x, y = _corner_xy(corner)
    if effect == "滑入":
        x, y = _slide_xy(corner)
    # ``eof_action=repeat`` keeps a short still/GIF frame available, while
    # ``shortest=1`` makes the main video duration the output boundary.
    return (
        f"[{sticker_index}:v]{prep}[s{sticker_index}];"
        f"[{previous_label}][s{sticker_index}]overlay=x='{x}':y='{y}':"
        f"shortest=1:eof_action=repeat[{output_label}]"
    )


def sticker_filter_graph(
    sticker_specs: Sequence[Mapping[str, object]],
    *,
    main_label: str = "v0",
    first_input_index: int = 1,
) -> tuple[list[str], str]:
    """Build chained filter segments from ``{size, animation, corner}`` specs."""

    filters: list[str] = []
    previous = main_label
    for offset, spec in enumerate(sticker_specs):
        input_index = first_input_index + offset
        output = f"v{input_index}"
        filters.append(
            sticker_filter_chain(
                input_index,
                previous,
                output,
                size=spec.get("scale", STICKER_SCALE_DEFAULT),
                animation=spec.get("animation", "静态"),
                corner=int(spec.get("corner", offset)),
            )
        )
        previous = output
    return filters, previous


def sticker_spec(store: StickerConfigStore, path: str | os.PathLike[str], corner: int) -> dict[str, object]:
    """Resolve a sticker's render settings by file type.

    One global size controls all four randomly assigned corner stickers;
    GIF frame animation is handled by the input loop, so it needs no motion
    selector.
    """
    source = Path(path)
    # One global size is shared by all four random corner stickers. GIF frame
    # animation is preserved by sticker_input_args(), which loops the source
    # stream; the overlay itself stays static.
    return {
        "scale": store.get_global_scale(),
        "animation": "静态",
        "corner": corner,
        "gif": is_editable_gif(source),
    }


def sticker_editor(parent, path: str | os.PathLike[str], store: StickerConfigStore, *, on_saved: Callable[[], None] | None = None):
    """Open a compact Tk editor for one sticker and return the Toplevel.

    Kept as a function so the existing library dialog can add an ``编辑``
    button without adopting a new widget class.  Importing this module does
    not import Tkinter; the dependency is loaded only when this function is
    called.
    """

    import tkinter as tk
    from tkinter import ttk

    source = Path(path)
    if not is_editable_gif(source):
        return None
    current = store.get(source.name)
    win = tk.Toplevel(parent)
    win.title(f"编辑贴纸 · {source.name}")
    win.geometry("360x245")
    win.resizable(False, False)
    win.configure(bg="#171a22")
    tk.Label(win, text=source.name, bg="#171a22", fg="#dfe4f2", anchor="w").pack(fill="x", padx=18, pady=(18, 8))
    size = tk.DoubleVar(win, value=float(current["scale"]) * 100)
    tk.Label(win, text="贴纸宽度（占视频宽度）", bg="#171a22", fg="#aeb8d0", anchor="w").pack(fill="x", padx=18)
    tk.Scale(
        win,
        from_=5,
        to=20,
        resolution=1,
        orient="horizontal",
        variable=size,
        bg="#171a22",
        fg="#dfe4f2",
        troughcolor="#2a3040",
        highlightthickness=0,
        showvalue=True,
    ).pack(fill="x", padx=18)
    animation = tk.StringVar(win, value=str(current["animation"]))
    row = tk.Frame(win, bg="#171a22"); row.pack(fill="x", padx=18, pady=(8, 0))
    tk.Label(row, text="入场动画", bg="#171a22", fg="#aeb8d0").pack(side="left")
    ttk.Combobox(row, textvariable=animation, values=STICKER_ANIMATIONS, state="readonly", width=12).pack(side="right")
    buttons = tk.Frame(win, bg="#171a22"); buttons.pack(fill="x", padx=18, pady=18)
    def save():
        store.set(source.name, scale=float(size.get()) / 100, animation=animation.get())
        if on_saved:
            on_saved()
        win.destroy()
    ttk.Button(buttons, text="保存", command=save).pack(side="right")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right", padx=(0, 8))
    win.transient(parent); win.grab_set()
    return win


__all__ = [
    "IMAGE_SUFFIXES",
    "STICKER_ANIMATIONS",
    "STICKER_SCALE_DEFAULT",
    "STICKER_SCALE_MAX",
    "STICKER_SCALE_MIN",
    "StickerConfigStore",
    "image_filetypes",
    "is_supported_image",
    "normalize_animation",
    "sticker_editor",
    "sticker_filter_chain",
    "sticker_filter_graph",
    "sticker_input_args",
]


# The functions below are used by the portable application's replacement
# entry point.  Keeping the UI and renderer hooks here makes the patch
# additive: the original bundled module remains available for rollback.
_APP_NS: dict[str, object] = {}
_ORIGINAL_SUBPROCESS_RUN = None
_CUDA_DLL_HANDLES: list[object] = []


def _prepare_cuda_runtime(ns: dict) -> None:
    """Make the portable package's bundled CUDA DLLs discoverable."""
    app_dir = Path(ns.get("APP_DIR") or Path(sys.executable).resolve().parent)
    candidates = (
        app_dir / "_internal" / "runtime" / "cuda",
        app_dir / "_internal" / "ctranslate2",
        app_dir / "_internal" / "cuda",
        app_dir / "cuda",
        app_dir / "_internal",
        app_dir,
    )
    found: list[str] = []
    for directory in candidates:
        if not directory.is_dir():
            continue
        value = str(directory.resolve())
        if value in found:
            continue
        found.append(value)
        try:
            if hasattr(os, "add_dll_directory"):
                _CUDA_DLL_HANDLES.append(os.add_dll_directory(value))
        except (OSError, AttributeError):
            pass
    if found:
        os.environ["PATH"] = os.pathsep.join(found + [os.environ.get("PATH", "")])


def _enhanced_process_video(self, video, out, batch, serial, settings=None):
    """Replacement for the 2.2 dedup renderer with GIF/motion support."""
    ns = _APP_NS
    settings = dict(settings or {})
    for key, var in getattr(self, "opts", {}).items():
        settings.setdefault(key, bool(var.get()))
    opacity_var = getattr(self, "opacity", None)
    settings.setdefault("opacity", int(opacity_var.get()) if hasattr(opacity_var, "get") else 35)
    settings.setdefault("effects", list(getattr(self, "EFFECTS", ())))

    ffmpeg = ns["TranslationBackend"]._ffmpeg()
    # ``av`` is imported inside the original renderer, so it is not a
    # top-level global in the marshalled module.  Import it here explicitly.
    import av
    duration = 0.0
    with av.open(str(video)) as container:
        duration = float(container.duration or 0) / av.time_base
    factor = ns["random"].uniform(1.1, 1.2) if settings.get("speed") else 1.0
    trim = ns["random"].uniform(0.1, 0.2) if settings.get("tail") else 0.0
    head_trim = ns["random"].uniform(0.1, 0.2) if settings.get("head") else 0.0
    filters: list[str] = []
    inputs = (["-ss", f"{head_trim:.3f}"] if head_trim else []) + ["-i", str(video)]
    base = "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
    if settings.get("background"):
        base = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,split=2[bg][fg];"
            f"[bg]gblur=sigma={ns['random'].randint(12, 28)}[bgb];"
            "[fg]scale=720:1280:force_original_aspect_ratio=decrease,"
            "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black@0[fg2];"
            "[bgb][fg2]overlay=(W-w)/2:(H-h)/2"
        )
    vf = base
    if settings.get("template"):
        vf += f",drawbox=x=0:y=0:w=iw:h=ih:color=white@{settings.get('opacity', 35)/1000:.3f}:t=fill"
    if settings.get("effect") and settings.get("effects"):
        vf += "," + ns["build_effect_filter"](ns["random"].choice(settings["effects"]), settings.get("opacity", 35))
    if factor != 1.0:
        vf += f",setpts=PTS/{factor:.5f}"

    sticker_dir = Path(getattr(self, "sticker_dir", ns["APP_DIR"] / "stickers"))
    store = StickerConfigStore(sticker_dir)
    files = [p for p in sticker_dir.iterdir() if p.is_file() and is_supported_image(p)] if settings.get("sticker") else []
    chosen = ns["random"].sample(files, min(4, len(files))) if files else []
    for path in chosen:
        inputs.extend(sticker_input_args(path))
    filters.append(vf + "[v0]")
    specs = []
    for index, path in enumerate(chosen):
        specs.append(sticker_spec(store, path, index))
    sticker_filters, label = sticker_filter_graph(specs, main_label="v0", first_input_index=1)
    filters.extend(sticker_filters)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"] + inputs + [
        "-filter_complex", ";".join(filters), "-map", f"[{label}]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac",
        "-movflags", "+faststart", "-shortest",
    ]
    if settings.get("md5"):
        cmd += ["-metadata", "comment=dedup-" + ns["secrets"].token_hex(16)]
    if factor != 1.0:
        cmd += ["-af", f"atempo={factor:.5f}"]
    if head_trim or trim:
        cmd += ["-t", f"{max(.1, (duration - head_trim - trim) / factor):.3f}"]
    cmd.append(str(out))
    ns["subprocess"].run(cmd, check=True, capture_output=True, text=True, timeout=900)


def _build_library(ns):
    """Create a shared sticker library with per-file settings controls."""
    tk = ns["tk"]
    ttk = ns["ttk"]
    Image = ns["Image"]
    ImageTk = ns["ImageTk"]
    ImageSequence = getattr(ns, "ImageSequence", None)
    if ImageSequence is None:
        try:
            from PIL import ImageSequence as _ImageSequence
            ImageSequence = _ImageSequence
        except Exception:
            ImageSequence = None
    filedialog = ns["filedialog"]
    messagebox = ns["messagebox"]

    def open_sticker_library(owner, sticker_dir, is_busy=None, on_close=None):
        sticker_dir = Path(sticker_dir)
        sticker_dir.mkdir(parents=True, exist_ok=True)
        busy = is_busy or (lambda: False)
        win = tk.Toplevel(owner)
        win.title("我的贴纸库")
        win.geometry("780x570")
        win.minsize(700, 480)
        win.configure(bg="#171a22")
        try:
            win.transient(owner.winfo_toplevel())
        except Exception:
            pass
        store = StickerConfigStore(sticker_dir)
        win._sticker_refs = []
        win._sticker_gif_jobs = []
        win._sticker_scale_reload_job = None

        size_bar = tk.Frame(win, bg="#171a22")
        size_bar.pack(fill="x", padx=14, pady=(14, 0))
        tk.Label(size_bar, text="四角贴纸大小（占视频宽度）", bg="#171a22", fg="#dfe4f2").pack(side="left")
        global_size = tk.DoubleVar(value=store.get_global_scale() * 100)
        global_size_label = tk.Label(size_bar, text=f"{global_size.get():.0f}%", width=6, bg="#171a22", fg="#8fe6c4")
        global_size_label.pack(side="left", padx=(8, 4))

        def set_global_size(value):
            percent = max(STICKER_SCALE_MIN * 100, min(STICKER_SCALE_MAX * 100, float(value)))
            global_size_label.configure(text=f"{percent:.0f}%")
            store.set_global_scale(percent / 100.0)
            pending = getattr(win, "_sticker_scale_reload_job", None)
            if pending:
                try: win.after_cancel(pending)
                except Exception: pass
            win._sticker_scale_reload_job = win.after(80, reload)

        tk.Scale(
            size_bar, from_=STICKER_SCALE_MIN * 100, to=STICKER_SCALE_MAX * 100,
            resolution=1, orient="horizontal", variable=global_size,
            command=set_global_size, bg="#171a22", fg="#dfe4f2",
            troughcolor="#3b4160", highlightthickness=0, showvalue=False,
            length=220,
        ).pack(side="left", padx=(2, 8))
        tk.Label(size_bar, text="四角统一调整，贴纸仍随机分配", bg="#171a22", fg="#7f8aa3").pack(side="left")

        scroll_area = tk.Frame(win, bg="#171a22"); scroll_area.pack(fill="both", expand=True, padx=14, pady=14)
        canvas = tk.Canvas(scroll_area, bg="#171a22", highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg="#171a22")
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))

        def reload():
            for child in body.winfo_children(): child.destroy()
            win._sticker_refs.clear()
            for job in getattr(win, "_sticker_gif_jobs", []):
                try: win.after_cancel(job)
                except Exception: pass
            win._sticker_gif_jobs.clear()
            paths = sorted((p for p in sticker_dir.iterdir() if p.is_file() and is_supported_image(p)), key=lambda p: p.name.lower())
            store.prune(paths)
            preview_limit = max(18, min(112, round(112 * store.get_global_scale() / STICKER_SCALE_MAX)))
            if not paths:
                tk.Label(body, text="贴纸库为空，请上传图片或 GIF", bg="#171a22", fg="#7f8aa3").grid(row=0, column=0, padx=20, pady=20)
                return
            for index, path in enumerate(paths):
                editable_gif = is_editable_gif(path)
                card = tk.Frame(body, bg="#242936", padx=8, pady=8)
                card.grid(row=index // 3, column=index % 3, padx=6, pady=6, sticky="nsew")
                try:
                    image = Image.open(path).convert("RGBA")
                    image.thumbnail((preview_limit, preview_limit), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image)
                    win._sticker_refs.append(photo)
                    preview = tk.Label(card, image=photo, bg="#242936", width=112, height=112)
                    preview.pack()
                    # A lightweight animated preview for GIFs; output rendering
                    # always loops independently through FFmpeg.
                    if editable_gif and ImageSequence is not None:
                        frames = []
                        delays = []
                        with Image.open(path) as gif:
                            for frame in ImageSequence.Iterator(gif):
                                item = frame.convert("RGBA"); item.thumbnail((preview_limit, preview_limit), Image.Resampling.LANCZOS); frames.append(item.copy())
                                delays.append(max(20, int(frame.info.get("duration", 100))))
                        def animate(frame_index=0, frames=frames, delays=delays, label=preview):
                            if not win.winfo_exists() or not label.winfo_exists() or not frames: return
                            current = ImageTk.PhotoImage(frames[frame_index % len(frames)])
                            label.configure(image=current); label._sticker_photo = current
                            # Bind each card's callback independently; otherwise
                            # all GIF cards eventually use the last card's loop.
                            job = win.after(delays[frame_index % len(frames)], lambda tick=label._sticker_tick: tick(frame_index + 1))
                            label._sticker_job = job
                        preview._sticker_tick = animate
                        animate()
                except Exception:
                    tk.Label(card, text="图片无法预览", bg="#242936", fg="#d96c7c", width=16, height=7).pack()
                tk.Label(card, text=path.name[:24], bg="#242936", fg="#dfe4f2", width=24).pack(pady=(5, 2))
                if editable_gif:
                    status_text, status_color = "GIF · 自动循环 · 固定最小尺寸 5%", "#8fe6c4"
                else:
                    status_text, status_color = "静态图片 · 固定最小尺寸 5%", "#7f8aa3"
                tk.Label(card, text=status_text, bg="#242936", fg=status_color, anchor="w").pack(fill="x", pady=(6, 6))
                ttk.Button(card, text="删除", style="Dedup.TButton", command=lambda p=path: delete_sticker(p), state="disabled" if busy() else "normal").pack(side="left", fill="x", expand=True, padx=(5, 0), pady=(4, 0))
            for column in range(3): body.grid_columnconfigure(column, weight=1)
            body.update_idletasks(); canvas.configure(scrollregion=canvas.bbox("all"))

        def delete_sticker(path):
            if busy(): return
            try:
                path.unlink(); store.remove(path.name)
            except OSError as exc:
                messagebox.showwarning("删除失败", str(exc), parent=win)
            reload()

        def upload():
            if busy(): return
            for src in filedialog.askopenfilenames(parent=win, title="选择贴纸图片或 GIF", filetypes=image_filetypes()):
                source = Path(src); destination = sticker_dir / source.name
                if source.resolve() == destination.resolve(): continue
                suffix = 1
                while destination.exists():
                    destination = sticker_dir / f"{source.stem}_{suffix}{source.suffix}"; suffix += 1
                try:
                    with Image.open(source) as image: image.verify()
                    shutil.copy2(source, destination)
                except Exception as exc:
                    messagebox.showwarning("上传失败", f"{source.name}：{exc}", parent=win)
            reload()

        def close():
            for job in getattr(win, "_sticker_gif_jobs", []):
                try: win.after_cancel(job)
                except Exception: pass
            if on_close:
                try: on_close()
                except Exception: pass
            win.destroy()

        bar = tk.Frame(win, bg="#171a22"); bar.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(bar, text="上传图片 / GIF", style="Dedup.Accent.TButton", command=upload, state="disabled" if busy() else "normal").pack(side="left")
        tk.Label(bar, text="GIF 自动循环播放；四角贴纸随机分配", bg="#171a22", fg="#7f8aa3").pack(side="left", padx=12)
        ttk.Button(bar, text="关闭", style="Dedup.TButton", command=close).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", close)
        reload()
        try:
            drawer = getattr(owner, "drawer", None)
            if drawer is not None and drawer.active: drawer.attach_dialog(win)
        except Exception: pass
        return win

    return open_sticker_library


def _install_foreign_sticker_runner(ns: dict) -> None:
    """Extend the existing Chinese-to-foreign sticker export command.

    That workflow owns a large renderer in the original 2.2 bytecode.  Its
    final FFmpeg invocation is recognizable by the temporary ``_sticker.mp4``
    output.  A narrow wrapper keeps that renderer intact while adding the
    same looping, size, and motion settings used by the dedup page.
    """
    global _ORIGINAL_SUBPROCESS_RUN
    module = ns["subprocess"]
    if getattr(module.run, "_changke_sticker_patch", False):
        return
    original = module.run
    _ORIGINAL_SUBPROCESS_RUN = original

    def run(command, *args, **kwargs):
        if isinstance(command, (list, tuple)):
            cmd = list(command)
            is_sticker_export = any(str(item).lower().endswith("_sticker.mp4") for item in cmd)
            if is_sticker_export and "-filter_complex" in cmd:
                try:
                    input_paths = []
                    input_index = 0
                    rebuilt = []
                    i = 0
                    while i < len(cmd):
                        item = cmd[i]
                        if item == "-i" and i + 1 < len(cmd):
                            path = Path(str(cmd[i + 1]))
                            if input_index >= 1 and is_supported_image(path):
                                input_paths.append(path)
                                rebuilt.extend(sticker_input_args(path))
                            else:
                                rebuilt.extend((item, str(path)))
                            input_index += 1
                            i += 2
                            continue
                        rebuilt.append(item)
                        i += 1
                    if input_paths:
                        store = StickerConfigStore(ns["APP_DIR"] / "stickers")
                        specs = []
                        for corner, path in enumerate(input_paths):
                            specs.append(sticker_spec(store, path, corner))
                        graph, label = sticker_filter_graph(specs, main_label="0:v", first_input_index=1)
                        filter_index = rebuilt.index("-filter_complex") + 1
                        rebuilt[filter_index] = ";".join(graph)
                        map_index = rebuilt.index("-map", filter_index + 1) + 1
                        rebuilt[map_index] = f"[{label}]"
                    if "-shortest" not in rebuilt:
                        output_index = len(rebuilt) - 1
                        rebuilt.insert(output_index, "-shortest")
                    command = rebuilt
                except Exception:
                    # Preserve the original foreign renderer if a future build
                    # changes its command shape; the dedup path is unaffected.
                    command = cmd
        return original(command, *args, **kwargs)

    run._changke_sticker_patch = True
    module.run = run


def install(ns: dict) -> None:
    """Install the sticker library and renderer hooks into the raw module."""
    global _APP_NS
    _APP_NS = ns
    _prepare_cuda_runtime(ns)
    ns["open_sticker_library"] = _build_library(ns)
    panel = ns.get("DedupPanel")
    if panel is not None:
        panel._process_video = _enhanced_process_video
    _install_foreign_sticker_runner(ns)
    ns["STICKER_ENHANCEMENTS_VERSION"] = "2.2.6"


__all__ += ["install"]
