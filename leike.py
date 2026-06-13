"""
Leike - a simple native Windows UI for ffmpeg.

Open a video, drag a crop rectangle, set trim start/end, and export an
H.264 .mp4 in a widely compatible format.

Requires: ffmpeg and ffprobe on PATH (already detected on this machine).
No third-party Python packages needed - uses only the standard library.
"""

import os
import re
import sys
import glob
import json
import shutil
import subprocess
import threading
import tempfile
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Drag-and-drop support (tkinterdnd2). Falls back to button-only if missing.
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    BaseTk = TkinterDnD.Tk
    HAS_DND = True
except Exception:
    BaseTk = tk.Tk
    HAS_DND = False

# Brand palette, extracted from the Leike logo (leike.svg): warm near-black
# and marigold gold.
GOLD       = "#FFC551"   # accent
GOLD_LIGHT = "#FFD580"   # hover / highlight
GOLD_DEEP  = "#D99A2E"   # pressed / active
BASE_BG    = "#1B1508"   # window background (warm near-black)
PANEL_BG   = "#251D0C"   # raised panels, fields, buttons
PANEL_HI   = "#33280F"   # button hover
BORDER     = "#3A2E12"   # subtle borders
TEXT       = "#F5EFE3"   # primary text (warm off-white)
MUTED      = "#A89A82"   # secondary / hint text
DISABLED   = "#6B5E45"

# Canvas + custom-drawn crop overlay (not ttk-themed).
CANVAS_BG = "#120D04"
CANVAS_BORDER = BORDER
HINT_FG = MUTED
CROP_COLOR = GOLD

# Max size of the on-screen preview area (the source is scaled to fit).
PREVIEW_MAX_W, PREVIEW_MAX_H = 760, 560
HANDLE = 7  # half-size of a corner grab handle, in canvas pixels

# Aspect presets: label -> width/height ratio (None = free draw).
ASPECTS = [
    ("Free", None),
    ("9:16 (Reels/TikTok)", 9 / 16),
    ("1:1 (Square)", 1.0),
    ("4:5 (Portrait)", 4 / 5),
    ("16:9 (Landscape)", 16 / 9),
]

# Target-size presets: label -> max MB (None = off, "custom" = use the entry).
SIZE_TARGETS = [
    ("Off", None),
    ("8 MB", 8.0),
    ("10 MB", 10.0),
    ("25 MB", 25.0),
    ("Custom…", "custom"),
]

# Output formats: label -> ExportSettings.fmt value.
FORMATS = [
    ("MP4 (H.264)", "mp4"),
    ("GIF", "gif"),
    ("WebM (VP9)", "webm"),
]

# Downscale options: label -> max length of the longest side (None = original).
SCALE_OPTIONS = [
    ("Original", None),
    ("1080p (max 1920)", 1920),
    ("720p (max 1280)", 1280),
    ("Small (max 1080)", 1080),
]

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def tool_path(name):
    """Locate ffmpeg/ffprobe: next to the exe, inside the bundle, then PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(sys.executable))
        if getattr(sys, "_MEIPASS", None):
            bases.append(sys._MEIPASS)
    else:
        bases.append(os.path.dirname(os.path.abspath(__file__)))
    for base in bases:
        cand = os.path.join(base, exe)
        if os.path.exists(cand):
            return cand
    found = shutil.which(name)
    return found or name


FFMPEG = tool_path("ffmpeg")
FFPROBE = tool_path("ffprobe")


def resource_path(name):
    """Locate a bundled data file (e.g. the window icon)."""
    if getattr(sys, "_MEIPASS", None):
        bundled = os.path.join(sys._MEIPASS, name)
        if os.path.exists(bundled):
            return bundled
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


ICON_FILE = resource_path("leike.ico")


def run_capture(cmd):
    return subprocess.run(
        cmd, capture_output=True, text=True, creationflags=NO_WINDOW
    )


def fmt_time(seconds):
    if seconds is None:
        seconds = 0
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h:d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"


def parse_time(text):
    text = text.strip()
    if not text:
        return None
    try:
        parts = text.split(":")
        parts = [float(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def even(n):
    n = int(round(n))
    return n - (n % 2)


# --------------------------------------------------------------------------
# Export command builder: pure UI-state -> list of ffmpeg passes.
# Each feature adds a field here and a hook in the helpers below; the GUI just
# fills an ExportSettings and runs whatever passes come back.
# --------------------------------------------------------------------------
@dataclass
class ExportSettings:
    input_path: str
    output_path: str
    src_w: int
    src_h: int
    start: float
    end: float
    crop: tuple | None = None       # (x, y, w, h) in source px
    scale_cap: int | None = None    # longest-side cap, or None for original
    crf: int = 20
    fmt: str = "mp4"                # mp4 | gif | webm (mp3 arrives in Phase 4)
    fast_trim: bool = True          # allow lossless -c copy for trim-only jobs
    hw: bool = False                # GPU encode (h264_nvenc) instead of libx264
    gif_fps: int = 15               # frame rate for GIF output
    target_size_mb: float | None = None  # two-pass to hit a max file size (mp4)
    mute: bool = False              # drop the audio track
    volume: float = 1.0             # audio gain (1.0 = unchanged)
    audio_only: bool = False        # export audio as MP3, no video


def _out_dims(s):
    """Final output (w, h) after crop + optional downscale, even numbers."""
    w, h = (s.crop[2], s.crop[3]) if s.crop else (s.src_w, s.src_h)
    w, h = even(w), even(h)
    if s.scale_cap and max(w, h) > s.scale_cap:
        f = s.scale_cap / max(w, h)
        w, h = even(w * f), even(h * f)
    return max(2, w), max(2, h)


def _geom_filters(s):
    """crop + optional downscale (no pixel-format); shared by all formats."""
    chain = []
    if s.crop:
        x, y, w, h = s.crop
        chain.append(f"crop={even(w)}:{even(h)}:{even(x)}:{even(y)}")
    ow, oh = _out_dims(s)
    cw = even(s.crop[2]) if s.crop else even(s.src_w)
    ch = even(s.crop[3]) if s.crop else even(s.src_h)
    if (ow, oh) != (cw, ch):
        chain.append(f"scale={ow}:{oh}:flags=lanczos")
    return chain


def _video_filters(s):
    return _geom_filters(s) + ["format=yuv420p"]


def _gif_passes(s):
    """GIF via two passes: build an optimal palette, then render with it."""
    pre = ",".join(_geom_filters(s) + [f"fps={s.gif_fps}"])
    dur = max(0.001, s.end - s.start)
    palette = os.path.join(tempfile.gettempdir(), f"leike_pal_{os.getpid()}.png")
    p1 = [FFMPEG, "-y", "-ss", f"{s.start:.3f}", "-i", s.input_path,
          "-t", f"{dur:.3f}", "-vf", pre + ",palettegen=stats_mode=diff", palette]
    p2 = [FFMPEG, "-y", "-ss", f"{s.start:.3f}", "-i", s.input_path,
          "-t", f"{dur:.3f}", "-i", palette,
          "-lavfi", pre + " [x];[x][1:v] paletteuse=dither=bayer",
          s.output_path]
    return [p1, p2]


def _is_passthrough(s):
    """A trim-only job (no crop/scale/format change or future transforms) can be
    a lossless stream copy. getattr() keeps this forward-compatible as later
    phases add transform/audio fields."""
    return (getattr(s, "fast_trim", True)
            and not getattr(s, "target_size_mb", None)
            and s.crop is None and s.scale_cap is None and s.fmt == "mp4"
            and not getattr(s, "rotate", 0)
            and not getattr(s, "flip_h", False)
            and not getattr(s, "flip_v", False)
            and getattr(s, "speed", 1.0) == 1.0
            and not getattr(s, "fade_in", 0) and not getattr(s, "fade_out", 0)
            and getattr(s, "fill_mode", "crop") in ("crop", "none")
            and not getattr(s, "boomerang", False)
            and not getattr(s, "reverse", False)
            and getattr(s, "loop", 0) == 0
            and not getattr(s, "mute", False)
            and getattr(s, "volume", 1.0) == 1.0
            and not getattr(s, "audio_only", False))


def _venc(s):
    """Video encoder args: GPU (NVENC) or software (libx264)."""
    if getattr(s, "hw", False):
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(s.crf)]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(s.crf)]


def _size_target_passes(s):
    """Two-pass libx264 sized to hit s.target_size_mb (audio at 128 kbit/s)."""
    dur = max(0.001, s.end - s.start)
    total_kbit = (s.target_size_mb * 8192) / dur
    silent = getattr(s, "audio_only", False) or getattr(s, "mute", False)
    audio_kbit = 0 if silent else 128
    vbit = max(64, int((total_kbit - audio_kbit) * 0.97))   # 3% mux headroom
    log = s.output_path + ".2pass"
    null = "NUL" if os.name == "nt" else "/dev/null"
    common = ["-ss", f"{s.start:.3f}", "-i", s.input_path, "-t", f"{dur:.3f}",
              "-vf", ",".join(_video_filters(s)),
              "-c:v", "libx264", "-b:v", f"{vbit}k"]
    p1 = [FFMPEG, "-y", *common, "-pass", "1", "-passlogfile", log,
          "-an", "-f", "mp4", null]
    p2 = [FFMPEG, "-y", *common, "-pass", "2", "-passlogfile", log,
          *_audio_filter(s), *_audio_codec(s, "aac", "128k"),
          "-movflags", "+faststart", s.output_path]
    return [p1, p2]


def _audio_filter(s):
    """`-af volume=...` (skipped when muted or at unity gain)."""
    if not getattr(s, "mute", False) and getattr(s, "volume", 1.0) != 1.0:
        return ["-af", f"volume={s.volume:.3f}"]
    return []


def _audio_codec(s, codec, bitrate):
    if getattr(s, "mute", False):
        return ["-an"]
    return ["-c:a", codec, "-b:a", bitrate]


def build_commands(s):
    """Return a list of ffmpeg command arg-lists (one or more passes)."""
    dur = max(0.001, s.end - s.start)
    common = ["-ss", f"{s.start:.3f}", "-i", s.input_path, "-t", f"{dur:.3f}"]

    if getattr(s, "audio_only", False):
        return [[FFMPEG, "-y", *common, "-vn", *_audio_filter(s),
                 "-c:a", "libmp3lame", "-q:a", "2", s.output_path]]

    if s.fmt == "gif":
        return _gif_passes(s)

    if s.fmt == "webm":
        return [[FFMPEG, "-y", *common, "-vf", ",".join(_video_filters(s)),
                 "-c:v", "libvpx-vp9", "-crf", str(s.crf), "-b:v", "0",
                 *_audio_filter(s), *_audio_codec(s, "libopus", "128k"),
                 s.output_path]]

    # mp4
    if s.target_size_mb:
        return _size_target_passes(s)
    if _is_passthrough(s):
        return [[FFMPEG, "-y", *common, "-c", "copy", "-movflags", "+faststart",
                 s.output_path]]
    return [[FFMPEG, "-y", *common, "-vf", ",".join(_video_filters(s)), *_venc(s),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             *_audio_filter(s), *_audio_codec(s, "aac", "128k"), s.output_path]]


class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("Leike")
        self.resizable(True, True)
        self.minsize(900, 600)
        try:
            if os.path.exists(ICON_FILE):
                self.iconbitmap(ICON_FILE)
        except Exception:
            pass

        # --- source video state ---
        self.input_path = None
        self.src_w = 0
        self.src_h = 0
        self.duration = 0.0
        self.scale = 1.0      # display px per source px
        self.disp_w = 0
        self.disp_h = 0
        self.off_x = 0        # canvas px offset of the letterboxed image
        self.off_y = 0
        self._resize_after = None

        # --- crop rect in SOURCE coordinates (or None = full frame) ---
        self.crop = None      # [x, y, w, h]
        self.aspect = None    # locked ratio w/h, or None
        self.drag = None      # interaction state dict

        # --- trim state (seconds) ---
        self.start_t = 0.0
        self.end_t = 0.0
        self.playhead = 0.0

        # --- preview frame plumbing ---
        self._preview_img = None
        self._preview_token = 0
        self._scrub_after = None
        self._tmp_png = os.path.join(
            tempfile.gettempdir(), f"vtc_preview_{os.getpid()}.png"
        )

        self.export_proc = None
        self._cancelled = False
        self.has_nvenc = self._detect_nvenc()

        self._apply_theme()
        self._build_ui()
        self._apply_dark_titlebar()

    def _detect_nvenc(self):
        try:
            r = run_capture([FFMPEG, "-hide_banner", "-encoders"])
            return "h264_nvenc" in (r.stdout or "")
        except OSError:
            return False

    # --------------------------------------------------------------- theming
    def _apply_theme(self):
        # Warm-dark + gold theme built on 'clam' (fully recolourable) to match
        # the Leike logo. Replaces sv-ttk, whose accent can't be recoloured.
        self.configure(bg=BASE_BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BASE_BG, foreground=TEXT,
                        fieldbackground=PANEL_BG, bordercolor=BORDER,
                        lightcolor=BASE_BG, darkcolor=BASE_BG,
                        insertcolor=TEXT, focuscolor=GOLD)
        style.map(".", foreground=[("disabled", DISABLED)])

        style.configure("TFrame", background=BASE_BG)
        style.configure("TLabel", background=BASE_BG, foreground=TEXT)

        style.configure("TLabelframe", background=BASE_BG,
                        bordercolor=BORDER, borderwidth=1)
        style.configure("TLabelframe.Label", background=BASE_BG,
                        foreground=GOLD)

        style.configure("TButton", background=PANEL_BG, foreground=TEXT,
                        bordercolor=BORDER, relief="flat", padding=6)
        style.map("TButton",
                  background=[("disabled", BASE_BG), ("pressed", GOLD_DEEP),
                              ("active", PANEL_HI)],
                  foreground=[("pressed", BASE_BG)],
                  bordercolor=[("focus", GOLD)])

        style.configure("TEntry", fieldbackground=PANEL_BG, foreground=TEXT,
                        bordercolor=BORDER, insertcolor=TEXT)
        style.map("TEntry", bordercolor=[("focus", GOLD)])

        style.configure("TCombobox", fieldbackground=PANEL_BG, foreground=TEXT,
                        background=PANEL_BG, bordercolor=BORDER,
                        arrowcolor=GOLD)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_BG)],
                  bordercolor=[("focus", GOLD)],
                  arrowcolor=[("active", GOLD_LIGHT)])
        # Combobox drop-down list (a classic tk Listbox).
        self.option_add("*TCombobox*Listbox.background", PANEL_BG)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", GOLD)
        self.option_add("*TCombobox*Listbox.selectForeground", BASE_BG)

        # Slider: gold grip on a dark groove.
        style.configure("Horizontal.TScale", background=GOLD,
                        troughcolor=PANEL_BG, bordercolor=BORDER)
        # Progress bar: gold fill.
        style.configure("Horizontal.TProgressbar", background=GOLD,
                        troughcolor=PANEL_BG, bordercolor=BORDER)

    def _apply_dark_titlebar(self):
        # Make the native Windows title bar dark (DWM immersive dark mode).
        if os.name != "nt":
            return
        try:
            import ctypes
            self.update_idletasks()
            hwnd = (ctypes.windll.user32.GetParent(self.winfo_id())
                    or self.winfo_id())
            for attr in (20, 19):  # 20 = Win10 1903+/Win11, 19 = older builds
                val = ctypes.c_int(1)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(val),
                        ctypes.sizeof(val)) == 0:
                    break
            # Paint the title bar the same colour as the window background, so
            # the caption and the content read as one surface (Win 11 22000+).
            r, g, b = (int(BASE_BG[i:i + 2], 16) for i in (1, 3, 5))
            caption = ctypes.c_int(r | (g << 8) | (b << 16))  # 0x00BBGGRR
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
            # Force the title bar to repaint with the new colour.
            self.withdraw()
            self.deiconify()
        except Exception:
            pass

    # --------------------------------------------------------- display map
    def _recompute_display(self):
        """Fit the source frame into the current canvas, centred (letterboxed)."""
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        if not self.src_w or not self.src_h:
            self.scale, self.disp_w, self.disp_h = 1.0, cw, ch
            self.off_x = self.off_y = 0
            return
        self.scale = min(cw / self.src_w, ch / self.src_h)
        self.disp_w = max(2, int(self.src_w * self.scale))
        self.disp_h = max(2, int(self.src_h * self.scale))
        self.off_x = (cw - self.disp_w) // 2
        self.off_y = (ch - self.disp_h) // 2

    def _s2c(self, x, y):
        """Source pixel -> canvas pixel."""
        return self.off_x + x * self.scale, self.off_y + y * self.scale

    def _c2s(self, ex, ey):
        """Canvas pixel -> source pixel (clamped to the frame)."""
        x = min(max((ex - self.off_x) / self.scale, 0), self.src_w)
        y = min(max((ey - self.off_y) / self.scale, 0), self.src_h)
        return x, y

    def _on_canvas_resize(self, _e):
        self._recompute_display()
        if not self.input_path:
            self._draw_drop_hint()
            return
        self.redraw()  # instant re-letterbox of the cached frame
        if self._resize_after:
            self.after_cancel(self._resize_after)
        self._resize_after = self.after(
            150, lambda: self.request_preview(self.playhead))

    def _scrollable(self, parent):
        """A vertically scrollable container for the controls column."""
        outer = ttk.Frame(parent)
        outer.grid(row=0, column=1, sticky="ns", padx=(14, 0))
        outer.rowconfigure(0, weight=1)
        cv = tk.Canvas(outer, bg=BASE_BG, highlightthickness=0,
                       width=320, height=560)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv)
        win = cv.create_window((0, 0), window=inner, anchor="nw")

        def _conf(_e=None):
            cv.configure(scrollregion=cv.bbox("all"))
            cv.itemconfigure(win, width=cv.winfo_width())

        inner.bind("<Configure>", _conf)
        cv.bind("<Configure>", _conf)
        cv.configure(yscrollcommand=sb.set)
        cv.grid(row=0, column=0, sticky="ns")
        sb.grid(row=0, column=1, sticky="ns")

        def _wheel(e):
            cv.yview_scroll(int(-e.delta / 120), "units")

        cv.bind("<Enter>", lambda e: cv.bind_all("<MouseWheel>", _wheel))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        return inner

    def _toggle_adv(self):
        if self.adv_shown:
            self.advanced.grid_remove()
            self.adv_btn.config(text="More options  ▸")
        else:
            self.advanced.grid(row=4, column=0, sticky="ew", pady=(0, 4))
            self.adv_btn.config(text="More options  ▾")
        self.adv_shown = not self.adv_shown

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)   # preview column grows
        root.columnconfigure(1, weight=0)   # controls column fixed
        root.rowconfigure(0, weight=1)

        # Left: preview canvas
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)      # canvas row grows

        ttk.Button(left, text="Open video...", command=self.open_file).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        hint = "No file loaded — drag a video in or click Open video…"
        self.file_label = ttk.Label(left, text=hint, width=70)
        self.file_label.grid(row=1, column=0, sticky="w")

        self.canvas = tk.Canvas(
            left, width=PREVIEW_MAX_W, height=PREVIEW_MAX_H,
            bg=CANVAS_BG, highlightthickness=1,
            highlightbackground=CANVAS_BORDER,
        )
        self.canvas.grid(row=2, column=0, sticky="nsew", pady=6)
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_up)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._draw_drop_hint()

        # Accept files dropped from Explorer onto the window / canvas.
        if HAS_DND:
            for widget in (self, self.canvas):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self.on_drop)

        # Scrub slider (preview playhead)
        scrub = ttk.Frame(left)
        scrub.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        scrub.columnconfigure(1, weight=1)
        ttk.Label(scrub, text="Preview").grid(row=0, column=0, padx=(0, 6))
        self.scrub_var = tk.DoubleVar(value=0.0)
        self.scrub = ttk.Scale(
            scrub, from_=0, to=1, variable=self.scrub_var,
            command=self.on_scrub, length=620,
        )
        self.scrub.grid(row=0, column=1, sticky="ew")
        self.playhead_label = ttk.Label(scrub, text="00:00.000", width=12)
        self.playhead_label.grid(row=0, column=2, padx=(6, 0))

        # Right: controls (scrollable, so a short window still reaches Export)
        right = self._scrollable(root)
        self._build_crop_panel(right)
        self._build_trim_panel(right)
        self._build_export_panel(right)

        # "More options" expander — feature panels land in self.advanced later.
        self.adv_shown = False
        self.adv_btn = ttk.Button(right, text="More options  ▸",
                                  command=self._toggle_adv)
        self.adv_btn.grid(row=3, column=0, sticky="ew", pady=(8, 2))
        self.advanced = ttk.Frame(right)
        self._build_encoding_panel(self.advanced)
        self._build_audio_panel(self.advanced)

    def _build_crop_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Crop", padding=8)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(box, text="Aspect ratio").grid(row=0, column=0, sticky="w")
        self.aspect_var = tk.StringVar(value=ASPECTS[0][0])
        aspect_cb = ttk.Combobox(
            box, textvariable=self.aspect_var, state="readonly",
            values=[a[0] for a in ASPECTS], width=22,
        )
        aspect_cb.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        aspect_cb.bind("<<ComboboxSelected>>", self.on_aspect_change)

        self.crop_label = ttk.Label(box, text="Crop: full frame")
        self.crop_label.grid(row=2, column=0, columnspan=2, sticky="w")

        ttk.Button(box, text="Reset to full frame",
                   command=self.reset_crop).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        ttk.Label(
            box, text="Drag on the preview to draw a crop box.\n"
                      "Drag inside to move, corners to resize.",
            foreground="#666",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _build_trim_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Trim", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(box, text="Start").grid(row=0, column=0, sticky="w")
        self.start_var = tk.StringVar(value="00:00.000")
        e1 = ttk.Entry(box, textvariable=self.start_var, width=14)
        e1.grid(row=0, column=1, padx=4)
        e1.bind("<Return>", lambda _e: self.commit_times())
        e1.bind("<FocusOut>", lambda _e: self.commit_times())
        ttk.Button(box, text="Set from playhead",
                   command=lambda: self.set_from_playhead("start")).grid(
            row=0, column=2)

        ttk.Label(box, text="End").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.end_var = tk.StringVar(value="00:00.000")
        e2 = ttk.Entry(box, textvariable=self.end_var, width=14)
        e2.grid(row=1, column=1, padx=4, pady=(6, 0))
        e2.bind("<Return>", lambda _e: self.commit_times())
        e2.bind("<FocusOut>", lambda _e: self.commit_times())
        ttk.Button(box, text="Set from playhead",
                   command=lambda: self.set_from_playhead("end")).grid(
            row=1, column=2, pady=(6, 0))

        self.trim_label = ttk.Label(box, text="Duration: 0.000 s")
        self.trim_label.grid(row=2, column=0, columnspan=3, sticky="w",
                             pady=(6, 0))

    def _build_export_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Export", padding=8)
        box.grid(row=2, column=0, sticky="ew")

        ttk.Label(box, text="Format").grid(row=0, column=0, sticky="w")
        self.fmt_var = tk.StringVar(value=FORMATS[0][0])
        fmt_cb = ttk.Combobox(
            box, textvariable=self.fmt_var, state="readonly",
            values=[f[0] for f in FORMATS], width=22,
        )
        fmt_cb.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        fmt_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_format_change())

        ttk.Label(box, text="Downscale").grid(row=2, column=0, sticky="w")
        self.scale_var = tk.StringVar(value=SCALE_OPTIONS[0][0])
        scale_cb = ttk.Combobox(
            box, textvariable=self.scale_var, state="readonly",
            values=[s[0] for s in SCALE_OPTIONS], width=22,
        )
        scale_cb.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        scale_cb.bind("<<ComboboxSelected>>",
                      lambda _e: self._update_export_hint())

        # Quality (CRF) — used by MP4 and WebM.
        self.quality_row = ttk.Frame(box)
        self.quality_row.grid(row=4, column=0, columnspan=2, sticky="ew",
                              pady=(0, 6))
        ttk.Label(self.quality_row,
                  text="Quality (CRF, lower = better)").grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.crf_var = tk.IntVar(value=20)
        ttk.Scale(self.quality_row, from_=14, to=30, variable=self.crf_var,
                  command=self._on_crf, length=170).grid(row=1, column=0)
        self.crf_label = ttk.Label(self.quality_row, text="20", width=3)
        self.crf_label.grid(row=1, column=1, padx=(6, 0))

        # GIF frame rate — shown only when the format is GIF.
        self.gif_row = ttk.Frame(box)
        ttk.Label(self.gif_row, text="GIF frame rate").grid(
            row=0, column=0, sticky="w")
        self.gif_fps_var = tk.IntVar(value=15)
        ttk.Spinbox(self.gif_row, from_=5, to=30, width=5,
                    textvariable=self.gif_fps_var).grid(
            row=0, column=1, padx=(6, 0))

        btns = ttk.Frame(box)
        btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        btns.columnconfigure(0, weight=1)
        self.export_btn = ttk.Button(btns, text="Export...",
                                     command=self.export, state="disabled")
        self.export_btn.grid(row=0, column=0, sticky="ew")
        self.cancel_btn = ttk.Button(btns, text="Cancel",
                                     command=self.cancel_export, state="disabled")
        self.cancel_btn.grid(row=0, column=1, padx=(6, 0))

        self.export_hint = ttk.Label(box, text="", foreground=GOLD)
        self.export_hint.grid(row=7, column=0, columnspan=2, sticky="w")
        self.progress = ttk.Progressbar(box, length=240, mode="determinate")
        self.progress.grid(row=8, column=0, columnspan=2, sticky="ew")
        self.status_label = ttk.Label(box, text="")
        self.status_label.grid(row=9, column=0, columnspan=2, sticky="w",
                               pady=(4, 0))

    def _build_encoding_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Encoding", padding=8)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.fast_trim_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            box, text="Fast trim when possible (lossless, no re-encode)",
            variable=self.fast_trim_var,
            command=self._update_export_hint).grid(row=0, column=0, sticky="w")
        self.hw_var = tk.BooleanVar(value=False)
        self.hw_chk = ttk.Checkbutton(
            box, text="Fast encode (GPU / NVENC)", variable=self.hw_var,
            command=self._update_export_hint)
        self.hw_chk.grid(row=1, column=0, sticky="w", pady=(4, 0))
        if not self.has_nvenc:
            self.hw_chk.config(state="disabled")
            ttk.Label(box, text="(no NVENC GPU detected)",
                      foreground=MUTED).grid(row=2, column=0, sticky="w")

        size_box = ttk.Frame(box)
        size_box.grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Label(size_box, text="Target file size (MP4)").grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.size_var = tk.StringVar(value=SIZE_TARGETS[0][0])
        size_cb = ttk.Combobox(
            size_box, textvariable=self.size_var, state="readonly",
            values=[s[0] for s in SIZE_TARGETS], width=10)
        size_cb.grid(row=1, column=0, sticky="w")
        size_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_size_change())
        self.size_custom_var = tk.StringVar(value="")
        self.size_custom = ttk.Entry(size_box, textvariable=self.size_custom_var,
                                     width=6)
        self.size_custom.bind("<KeyRelease>",
                              lambda _e: self._update_export_hint())
        self.size_mb_lbl = ttk.Label(size_box, text="MB")

    def _on_size_change(self):
        if dict(SIZE_TARGETS)[self.size_var.get()] == "custom":
            self.size_custom.grid(row=1, column=1, padx=(6, 0))
            self.size_mb_lbl.grid(row=1, column=2, padx=(2, 0))
        else:
            self.size_custom.grid_remove()
            self.size_mb_lbl.grid_remove()
        self._update_export_hint()

    def _target_mb(self):
        v = dict(SIZE_TARGETS)[self.size_var.get()]
        if v is None:
            return None
        if v == "custom":
            try:
                mb = float(self.size_custom_var.get())
                return mb if mb > 0 else None
            except ValueError:
                return None
        return v

    def _build_audio_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Audio", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.mute_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Mute (remove audio)", variable=self.mute_var,
                        command=self._update_export_hint).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(box, text="Volume").grid(row=1, column=0, sticky="w",
                                           pady=(4, 0))
        self.volume_var = tk.IntVar(value=100)
        vrow = ttk.Frame(box)
        vrow.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Scale(vrow, from_=0, to=200, variable=self.volume_var,
                  command=self._on_volume, length=150).grid(row=0, column=0)
        self.volume_label = ttk.Label(vrow, text="100%", width=5)
        self.volume_label.grid(row=0, column=1, padx=(6, 0))
        self.audio_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Export audio only (MP3)",
                        variable=self.audio_only_var,
                        command=self._update_export_hint).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _on_volume(self, _v):
        self.volume_label.config(text=f"{self.volume_var.get()}%")

    def _on_crf(self, _v):
        self.crf_label.config(text=str(self.crf_var.get()))

    def _on_format_change(self):
        fmt = dict(FORMATS)[self.fmt_var.get()]
        if fmt == "gif":
            self.quality_row.grid_remove()
            self.gif_row.grid(row=5, column=0, columnspan=2, sticky="w",
                              pady=(0, 6))
        else:
            self.gif_row.grid_remove()
            self.quality_row.grid(row=4, column=0, columnspan=2, sticky="ew",
                                  pady=(0, 6))
        self._update_export_hint()

    def _update_export_hint(self):
        if not self.input_path:
            self.export_hint.config(text="")
            return
        s = self._settings("")
        if s.audio_only:
            self.export_hint.config(text="Audio only (MP3)")
        elif s.fmt == "gif":
            self.export_hint.config(text=f"GIF · {s.gif_fps} fps (2-pass palette)")
        elif s.fmt == "webm":
            self.export_hint.config(text="WebM (VP9)")
        elif s.target_size_mb:
            self.export_hint.config(
                text=f"Target {s.target_size_mb:g} MB (H.264 · 2-pass)")
        elif _is_passthrough(s):
            self.export_hint.config(text="⚡ Lossless fast trim (no re-encode)")
        elif s.hw:
            self.export_hint.config(text="Re-encode: H.264 (GPU)")
        else:
            self.export_hint.config(text="Re-encode: H.264")

    def cancel_export(self):
        self._cancelled = True
        if self.export_proc and self.export_proc.poll() is None:
            self.export_proc.kill()
        self.cancel_btn.config(state="disabled")
        self.status_label.config(text="Cancelling…")

    # -------------------------------------------------------------- loading
    def _draw_drop_hint(self):
        self.canvas.delete("all")
        msg = "Drop a video here\nor click “Open video…”"
        if not HAS_DND:
            msg = "Click “Open video…” to begin"
        cw = max(self.canvas.winfo_width(), PREVIEW_MAX_W)
        ch = max(self.canvas.winfo_height(), PREVIEW_MAX_H)
        self.canvas.create_text(
            cw // 2, ch // 2,
            text=msg, fill=HINT_FG, font=("Segoe UI", 14), justify="center",
        )

    def on_drop(self, event):
        # event.data is a brace/space-delimited list; take the first path.
        raw = event.data.strip()
        if raw.startswith("{"):
            path = raw[1:raw.find("}")] if "}" in raw else raw[1:]
        else:
            path = raw.split()[0] if " " in raw and not os.path.exists(raw) else raw
        self.load_path(path)

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open video",
            filetypes=[
                ("Video files",
                 "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.mpg *.mpeg"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.load_path(path)

    def load_path(self, path):
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            return
        info = self.probe(path)
        if not info:
            messagebox.showerror(
                "Error",
                "Could not read this file as a video with ffprobe.")
            return
        self.input_path = path
        self.src_w, self.src_h, self.duration = info
        self.file_label.config(
            text=f"{os.path.basename(path)}   "
                 f"({self.src_w}x{self.src_h}, {fmt_time(self.duration)})")

        # Fit the source into the current canvas (recomputed on every resize).
        self._recompute_display()

        # Reset edit state.
        self.crop = None
        self.aspect = None
        self.aspect_var.set(ASPECTS[0][0])
        self.start_t = 0.0
        self.end_t = self.duration
        self.playhead = 0.0
        self.start_var.set(fmt_time(0.0))
        self.end_var.set(fmt_time(self.duration))
        self.scrub.config(to=max(self.duration, 0.001))
        self.scrub_var.set(0.0)
        self.export_btn.config(state="normal")
        self.update_labels()
        self.request_preview(0.0)

    def probe(self, path):
        # Prefer ffprobe (precise JSON); fall back to parsing `ffmpeg -i` so a
        # bundle can ship ffmpeg.exe alone, without the large ffprobe binary.
        return self._probe_ffprobe(path) or self._probe_ffmpeg(path)

    def _probe_ffprobe(self, path):
        try:
            r = run_capture([
                FFPROBE, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-show_entries", "format=duration",
                "-of", "json", path,
            ])
        except OSError:
            return None  # ffprobe not present
        if r.returncode != 0:
            return None
        try:
            data = json.loads(r.stdout)
            stream = data["streams"][0]
            return (int(stream["width"]), int(stream["height"]),
                    float(data["format"]["duration"]))
        except (KeyError, IndexError, ValueError):
            return None

    def _probe_ffmpeg(self, path):
        try:
            r = run_capture([FFMPEG, "-hide_banner", "-i", path])
        except OSError:
            return None
        text = r.stderr or ""
        dur = None
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if m:
            dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                   + float(m.group(3)))
        w = h = None
        for line in text.splitlines():
            if "Video:" in line:
                d = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
                if d:
                    w, h = int(d.group(1)), int(d.group(2))
                    break
        if w and h and dur is not None:
            return w, h, dur
        return None

    # ------------------------------------------------------- preview frames
    def on_scrub(self, _v):
        if not self.input_path:
            return
        self.playhead = float(self.scrub_var.get())
        self.playhead_label.config(text=fmt_time(self.playhead))
        # Debounce: only extract a frame once scrubbing settles.
        if self._scrub_after:
            self.after_cancel(self._scrub_after)
        self._scrub_after = self.after(
            120, lambda: self.request_preview(self.playhead))

    def request_preview(self, t):
        if not self.input_path:
            return
        self._preview_token += 1
        token = self._preview_token
        threading.Thread(
            target=self._extract_frame, args=(t, token), daemon=True).start()

    def _extract_frame(self, t, token):
        out = self._tmp_png
        run_capture([
            FFMPEG, "-y", "-ss", f"{max(0.0, t):.3f}", "-i", self.input_path,
            "-frames:v", "1", "-update", "1",
            "-vf", f"scale={self.disp_w}:{self.disp_h}", out,
        ])
        if token != self._preview_token:
            return  # a newer request superseded this one
        if os.path.exists(out):
            self.after(0, lambda: self._show_frame(out, token))

    def _show_frame(self, path, token):
        if token != self._preview_token:
            return
        try:
            img = tk.PhotoImage(file=path)
        except tk.TclError:
            return
        self._preview_img = img  # keep a reference
        self.redraw()

    # ------------------------------------------------------------ rendering
    def redraw(self):
        c = self.canvas
        c.delete("all")
        if self._preview_img is not None:
            c.create_image(self.off_x, self.off_y, anchor="nw",
                           image=self._preview_img)
        if self.crop:
            x, y, w, h = self.crop
            x0, y0 = self._s2c(x, y)
            x1, y1 = self._s2c(x + w, y + h)
            ix0, iy0 = self.off_x, self.off_y
            ix1, iy1 = self.off_x + self.disp_w, self.off_y + self.disp_h
            # Dim the image area outside the crop box.
            for rect in (
                (ix0, iy0, ix1, y0),
                (ix0, y1, ix1, iy1),
                (ix0, y0, x0, y1),
                (x1, y0, ix1, y1),
            ):
                c.create_rectangle(*rect, fill="#000000", stipple="gray50",
                                    outline="", width=0)
            c.create_rectangle(x0, y0, x1, y1, outline=CROP_COLOR, width=2)
            for hx, hy in self._handle_points(x0, y0, x1, y1):
                c.create_rectangle(hx - HANDLE, hy - HANDLE,
                                    hx + HANDLE, hy + HANDLE,
                                    fill=CROP_COLOR, outline="white")

    def _handle_points(self, x0, y0, x1, y1):
        return [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]  # nw ne sw se

    # --------------------------------------------------------- crop editing
    def on_aspect_change(self, _e=None):
        label = self.aspect_var.get()
        self.aspect = dict(ASPECTS)[label]
        if self.crop and self.aspect:
            # Re-fit the current crop to the new ratio, centred, ratio-exact.
            cx = self.crop[0] + self.crop[2] / 2
            cy = self.crop[1] + self.crop[3] / 2
            w = min(self.crop[2], self.src_w)
            h = w / self.aspect
            if h > self.src_h:
                h = self.src_h
                w = h * self.aspect
            # Move (not resize) into bounds so the ratio stays exact.
            self.crop = self._clamp_rect([cx - w / 2, cy - h / 2, w, h],
                                         keep_size=True)
            self.update_labels()
            self.redraw()

    def reset_crop(self):
        self.crop = None
        self.update_labels()
        self.redraw()

    def on_canvas_down(self, ev):
        if not self.input_path:
            return
        sx, sy = self._c2s(ev.x, ev.y)
        if self.crop:
            x, y, w, h = self.crop
            cx0, cy0 = self._s2c(x, y)
            cx1, cy1 = self._s2c(x + w, y + h)
            handles = self._handle_points(cx0, cy0, cx1, cy1)
            names = ["nw", "ne", "sw", "se"]
            for (hx, hy), name in zip(handles, names):
                if abs(ev.x - hx) <= HANDLE + 2 and abs(ev.y - hy) <= HANDLE + 2:
                    self.drag = {"mode": "resize", "corner": name}
                    return
            if x <= sx <= x + w and y <= sy <= y + h:
                self.drag = {"mode": "move", "ox": sx - x, "oy": sy - y}
                return
        # Start drawing a new rect.
        self.drag = {"mode": "draw", "ax": sx, "ay": sy}

    def on_canvas_drag(self, ev):
        if not self.drag:
            return
        sx, sy = self._c2s(ev.x, ev.y)
        mode = self.drag["mode"]

        if mode == "draw":
            ax, ay = self.drag["ax"], self.drag["ay"]
            if self.aspect:
                dx = 1 if sx >= ax else -1
                dy = 1 if sy >= ay else -1
                desired_w = max(abs(sx - ax), abs(sy - ay) * self.aspect)
                self.crop = self._aspect_box(ax, ay, dx, dy, desired_w)
            else:
                x0, x1 = sorted((ax, sx))
                y0, y1 = sorted((ay, sy))
                self.crop = self._clamp_rect([x0, y0, x1 - x0, y1 - y0])

        elif mode == "move":
            x = sx - self.drag["ox"]
            y = sy - self.drag["oy"]
            self.crop = self._clamp_rect([x, y, self.crop[2], self.crop[3]],
                                         keep_size=True)

        elif mode == "resize":
            self.crop = self._resize(self.drag["corner"], sx, sy)

        self.update_labels()
        self.redraw()

    def on_canvas_up(self, _ev):
        if self.drag and self.crop:
            # Discard tiny accidental rectangles.
            if self.crop[2] < 8 or self.crop[3] < 8:
                self.crop = None
                self.update_labels()
                self.redraw()
        self.drag = None

    def _resize(self, corner, sx, sy):
        x, y, w, h = self.crop
        if self.aspect:
            # Anchor the opposite corner and grow keeping the locked ratio.
            anchors = {
                "se": (x, y, 1, 1),
                "nw": (x + w, y + h, -1, -1),
                "ne": (x, y + h, 1, -1),
                "sw": (x + w, y, -1, 1),
            }
            ax, ay, dx, dy = anchors[corner]
            desired_w = max(abs(sx - ax), abs(sy - ay) * self.aspect)
            return self._aspect_box(ax, ay, dx, dy, desired_w)

        left, top, right, bottom = x, y, x + w, y + h
        if "w" in corner:
            left = sx
        if "e" in corner:
            right = sx
        if "n" in corner:
            top = sy
        if "s" in corner:
            bottom = sy
        nx, nw = min(left, right), abs(right - left)
        ny, nh = min(top, bottom), abs(bottom - top)
        return self._clamp_rect([nx, ny, nw, nh])

    def _aspect_box(self, ax, ay, dx, dy, desired_w):
        """Build a rect of the locked ratio anchored at (ax, ay), growing in
        direction (dx, dy in {-1, +1}). Capped to the frame so the ratio is
        preserved exactly even at the edges."""
        ratio = self.aspect
        avail_w = (self.src_w - ax) if dx > 0 else ax
        avail_h = (self.src_h - ay) if dy > 0 else ay
        w = min(desired_w, avail_w, avail_h * ratio)
        w = max(2.0, w)
        h = w / ratio
        nx = ax if dx > 0 else ax - w
        ny = ay if dy > 0 else ay - h
        return [nx, ny, w, h]

    def _clamp_rect(self, rect, keep_size=False):
        x, y, w, h = rect
        w = max(2, min(w, self.src_w))
        h = max(2, min(h, self.src_h))
        if keep_size:
            x = min(max(0, x), self.src_w - w)
            y = min(max(0, y), self.src_h - h)
        else:
            x = max(0, x)
            y = max(0, y)
            w = min(w, self.src_w - x)
            h = min(h, self.src_h - y)
        return [x, y, w, h]

    # -------------------------------------------------------------- trim/labels
    def set_from_playhead(self, which):
        if not self.input_path:
            return
        if which == "start":
            self.start_var.set(fmt_time(self.playhead))
        else:
            self.end_var.set(fmt_time(self.playhead))
        self.commit_times()

    def commit_times(self):
        s = parse_time(self.start_var.get())
        e = parse_time(self.end_var.get())
        if s is None:
            s = 0.0
        if e is None:
            e = self.duration
        s = min(max(0.0, s), self.duration)
        e = min(max(0.0, e), self.duration)
        if e <= s:
            e = min(self.duration, s + 0.001)
        self.start_t, self.end_t = s, e
        self.start_var.set(fmt_time(s))
        self.end_var.set(fmt_time(e))
        self.update_labels()

    def update_labels(self):
        if self.crop:
            x, y, w, h = self.crop
            ow, oh = even(w), even(h)
            self.crop_label.config(text=f"Crop: {ow}x{oh} at ({even(x)},{even(y)})")
        else:
            self.crop_label.config(text="Crop: full frame")
        self.trim_label.config(
            text=f"Duration: {max(0.0, self.end_t - self.start_t):.3f} s")
        self._update_export_hint()

    # ------------------------------------------------------------- exporting
    def _settings(self, out):
        """Snapshot the current UI state into an ExportSettings."""
        return ExportSettings(
            input_path=self.input_path, output_path=out,
            src_w=self.src_w, src_h=self.src_h,
            start=self.start_t, end=self.end_t,
            crop=tuple(self.crop) if self.crop else None,
            scale_cap=dict(SCALE_OPTIONS)[self.scale_var.get()],
            crf=self.crf_var.get(), fmt=dict(FORMATS)[self.fmt_var.get()],
            fast_trim=self.fast_trim_var.get(), hw=self.hw_var.get(),
            gif_fps=self.gif_fps_var.get(), target_size_mb=self._target_mb(),
            mute=self.mute_var.get(), volume=self.volume_var.get() / 100.0,
            audio_only=self.audio_only_var.get())

    def export(self):
        if not self.input_path:
            return
        self.commit_times()
        if self.audio_only_var.get():
            ext, ftypes = ".mp3", [("MP3 audio", "*.mp3")]
        else:
            fmt = dict(FORMATS)[self.fmt_var.get()]
            ext = {"mp4": ".mp4", "gif": ".gif", "webm": ".webm"}[fmt]
            ftypes = {"mp4": [("MP4 video", "*.mp4")], "gif": [("GIF", "*.gif")],
                      "webm": [("WebM video", "*.webm")]}[fmt]
        base = os.path.splitext(os.path.basename(self.input_path))[0]
        out = filedialog.asksaveasfilename(
            title="Export as", defaultextension=ext,
            initialfile=f"{base}_export{ext}",
            initialdir=os.path.dirname(self.input_path),
            filetypes=ftypes,
        )
        if not out:
            return
        if os.path.abspath(out) == os.path.abspath(self.input_path):
            messagebox.showerror("Error", "Choose a different output file.")
            return

        dur = max(0.001, self.end_t - self.start_t)
        cmds = build_commands(self._settings(out))
        self.export_btn.config(state="disabled")
        if getattr(self, "cancel_btn", None):
            self.cancel_btn.config(state="normal")
        self.progress["value"] = 0
        self.status_label.config(text="Exporting...")
        threading.Thread(target=self._run_export, args=(cmds, dur, out),
                         daemon=True).start()

    def _run_export(self, cmds, dur, out):
        """Run each pass in sequence; report combined progress; honour cancel."""
        self._cancelled = False
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        last_err = ""
        n = len(cmds)
        for i, cmd in enumerate(cmds):
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    text=True, creationflags=NO_WINDOW)
            except OSError as exc:
                return self.after(
                    0, lambda e=str(exc): self._export_done(False, e, out))
            self.export_proc = proc
            for line in proc.stderr:
                if self._cancelled:
                    proc.kill()
                    break
                m = time_re.search(line)
                if m:
                    t = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                         + float(m.group(3)))
                    frac = (i + min(1.0, t / dur)) / n
                    self.after(0, lambda p=frac * 100:
                               self.progress.config(value=p))
                elif line.strip():
                    last_err = line.strip()
            code = proc.wait()
            if self._cancelled:
                break
            if code != 0:
                return self.after(
                    0, lambda e=last_err: self._export_done(False, e, out))
        self.after(0, lambda: self._export_done(not self._cancelled, last_err, out))

    def _export_done(self, ok, err, out):
        self.export_btn.config(state="normal")
        if getattr(self, "cancel_btn", None):
            self.cancel_btn.config(state="disabled")
        # Remove any two-pass log files left by a size-targeted export.
        if out:
            for f in glob.glob(out + ".2pass*"):
                try:
                    os.remove(f)
                except OSError:
                    pass
        if ok:
            self.progress["value"] = 100
            self.status_label.config(text="Done.")
            messagebox.showinfo("Export complete", f"Saved:\n{out}")
        elif self._cancelled:
            self.progress["value"] = 0
            self.status_label.config(text="Cancelled.")
            try:
                if out and os.path.exists(out):
                    os.remove(out)
            except OSError:
                pass
        else:
            self.progress["value"] = 0
            self.status_label.config(text="Export failed.")
            messagebox.showerror("Export failed", err or "ffmpeg error.")


if __name__ == "__main__":
    App().mainloop()
