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
import json
import shutil
import subprocess
import threading
import tempfile
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

# Native-looking dark theme (Sun Valley / Windows 11 Fluent). Optional: the
# app falls back to a hand-rolled dark theme if the package is unavailable.
try:
    import sv_ttk
    HAS_SVTTK = True
except Exception:
    sv_ttk = None
    HAS_SVTTK = False

# Dark palette for the tk Canvas and custom-drawn overlay (not ttk-themed).
DARK_BG = "#1c1c1c"
CANVAS_BG = "#0f0f0f"
CANVAS_BORDER = "#3a3a3a"
HINT_FG = "#9a9a9a"
CROP_COLOR = "#4ec9ff"

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


class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("Leike")
        self.resizable(False, False)

        # --- source video state ---
        self.input_path = None
        self.src_w = 0
        self.src_h = 0
        self.duration = 0.0
        self.scale = 1.0      # display px per source px
        self.disp_w = 0
        self.disp_h = 0

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

        self._apply_theme()
        self._build_ui()
        self._apply_dark_titlebar()

    # --------------------------------------------------------------- theming
    def _apply_theme(self):
        self.configure(bg=DARK_BG)
        if HAS_SVTTK:
            try:
                sv_ttk.set_theme("dark")
                return
            except Exception:
                pass
        self._apply_fallback_dark()

    def _apply_fallback_dark(self):
        # Used only if sv_ttk is missing: recolour the 'clam' theme by hand.
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        fg, bg, field = "#e6e6e6", DARK_BG, "#2d2d2d"
        style.configure(".", background=bg, foreground=fg,
                        fieldbackground=field, bordercolor="#3a3a3a",
                        lightcolor=bg, darkcolor=bg, insertcolor=fg)
        style.map(".", foreground=[("disabled", "#777777")])
        style.configure("TButton", background=field, padding=5)
        style.map("TButton", background=[("active", "#3a3a3a")])
        style.configure("TLabelframe", background=bg)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)
        style.configure("TCombobox", fieldbackground=field, background=field)
        style.configure("TEntry", fieldbackground=field, foreground=fg)
        style.configure("Horizontal.TScale", background=bg)
        style.configure("Horizontal.TProgressbar", background=CROP_COLOR,
                        troughcolor=field)

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
            r, g, b = (int(DARK_BG[i:i + 2], 16) for i in (1, 3, 5))
            caption = ctypes.c_int(r | (g << 8) | (b << 16))  # 0x00BBGGRR
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
            # Force the title bar to repaint with the new colour.
            self.withdraw()
            self.deiconify()
        except Exception:
            pass

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0)

        # Left: preview canvas
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="n")

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
        self.canvas.grid(row=2, column=0, pady=6)
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_up)
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

        # Right: controls
        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="n", padx=(14, 0))

        self._build_crop_panel(right)
        self._build_trim_panel(right)
        self._build_export_panel(right)

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
        box = ttk.LabelFrame(parent, text="Export (H.264 .mp4)", padding=8)
        box.grid(row=2, column=0, sticky="ew")

        ttk.Label(box, text="Downscale").grid(row=0, column=0, sticky="w")
        self.scale_var = tk.StringVar(value=SCALE_OPTIONS[0][0])
        ttk.Combobox(
            box, textvariable=self.scale_var, state="readonly",
            values=[s[0] for s in SCALE_OPTIONS], width=22,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(box, text="Quality (CRF, lower = better)").grid(
            row=2, column=0, columnspan=2, sticky="w")
        self.crf_var = tk.IntVar(value=20)
        crf_row = ttk.Frame(box)
        crf_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Scale(crf_row, from_=14, to=30, variable=self.crf_var,
                  command=self._on_crf, length=170).grid(row=0, column=0)
        self.crf_label = ttk.Label(crf_row, text="20", width=3)
        self.crf_label.grid(row=0, column=1, padx=(6, 0))

        self.export_btn = ttk.Button(box, text="Export video...",
                                     command=self.export, state="disabled")
        self.export_btn.grid(row=4, column=0, columnspan=2, sticky="ew",
                             pady=(4, 4))

        self.progress = ttk.Progressbar(box, length=240, mode="determinate")
        self.progress.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.status_label = ttk.Label(box, text="")
        self.status_label.grid(row=6, column=0, columnspan=2, sticky="w",
                               pady=(4, 0))

    def _on_crf(self, _v):
        self.crf_label.config(text=str(self.crf_var.get()))

    # -------------------------------------------------------------- loading
    def _draw_drop_hint(self):
        self.canvas.delete("all")
        msg = "Drop a video here\nor click “Open video…”"
        if not HAS_DND:
            msg = "Click “Open video…” to begin"
        self.canvas.create_text(
            self.disp_w // 2 if self.disp_w else PREVIEW_MAX_W // 2,
            self.disp_h // 2 if self.disp_h else PREVIEW_MAX_H // 2,
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

        # Fit the source into the preview box.
        self.scale = min(PREVIEW_MAX_W / self.src_w,
                         PREVIEW_MAX_H / self.src_h, 1.0)
        self.disp_w = max(1, int(self.src_w * self.scale))
        self.disp_h = max(1, int(self.src_h * self.scale))
        self.canvas.config(width=self.disp_w, height=self.disp_h)

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
            c.create_image(0, 0, anchor="nw", image=self._preview_img)
        if self.crop:
            x, y, w, h = self.crop
            x0, y0 = x * self.scale, y * self.scale
            x1, y1 = (x + w) * self.scale, (y + h) * self.scale
            # Dim everything outside the crop box.
            for rect in (
                (0, 0, self.disp_w, y0),
                (0, y1, self.disp_w, self.disp_h),
                (0, y0, x0, y1),
                (x1, y0, self.disp_w, y1),
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
        sx, sy = ev.x / self.scale, ev.y / self.scale
        if self.crop:
            x, y, w, h = self.crop
            cx0, cy0 = x * self.scale, y * self.scale
            cx1, cy1 = (x + w) * self.scale, (y + h) * self.scale
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
        sx = min(max(ev.x / self.scale, 0), self.src_w)
        sy = min(max(ev.y / self.scale, 0), self.src_h)
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

    # ------------------------------------------------------------- exporting
    def _output_dims(self):
        """Final output (w, h) after crop + optional downscale, even numbers."""
        if self.crop:
            w, h = even(self.crop[2]), even(self.crop[3])
        else:
            w, h = even(self.src_w), even(self.src_h)
        cap = dict(SCALE_OPTIONS)[self.scale_var.get()]
        if cap and max(w, h) > cap:
            factor = cap / max(w, h)
            w, h = even(w * factor), even(h * factor)
        return max(2, w), max(2, h)

    def build_filters(self):
        chain = []
        if self.crop:
            x, y, w, h = self.crop
            chain.append(f"crop={even(w)}:{even(h)}:{even(x)}:{even(y)}")
        ow, oh = self._output_dims()
        cw = even(self.crop[2]) if self.crop else even(self.src_w)
        ch = even(self.crop[3]) if self.crop else even(self.src_h)
        if (ow, oh) != (cw, ch):
            chain.append(f"scale={ow}:{oh}:flags=lanczos")
        chain.append("format=yuv420p")
        return ",".join(chain)

    def export(self):
        if not self.input_path:
            return
        self.commit_times()
        base = os.path.splitext(os.path.basename(self.input_path))[0]
        out = filedialog.asksaveasfilename(
            title="Export as", defaultextension=".mp4",
            initialfile=f"{base}_export.mp4",
            initialdir=os.path.dirname(self.input_path),
            filetypes=[("MP4 video", "*.mp4")],
        )
        if not out:
            return
        if os.path.abspath(out) == os.path.abspath(self.input_path):
            messagebox.showerror("Error", "Choose a different output file.")
            return

        dur = max(0.001, self.end_t - self.start_t)
        cmd = [
            FFMPEG, "-y",
            "-ss", f"{self.start_t:.3f}",
            "-i", self.input_path,
            "-t", f"{dur:.3f}",
            "-vf", self.build_filters(),
            "-c:v", "libx264", "-preset", "medium",
            "-crf", str(self.crf_var.get()),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "128k",
            out,
        ]
        self.export_btn.config(state="disabled")
        self.progress["value"] = 0
        self.status_label.config(text="Exporting...")
        threading.Thread(target=self._run_export, args=(cmd, dur, out),
                         daemon=True).start()

    def _run_export(self, cmd, dur, out):
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, creationflags=NO_WINDOW)
        except OSError as exc:
            self.after(0, lambda: self._export_done(False, str(exc), out))
            return
        last_err = ""
        for line in proc.stderr:
            m = time_re.search(line)
            if m:
                t = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                     + float(m.group(3)))
                pct = min(100.0, t / dur * 100.0)
                self.after(0, lambda p=pct: self.progress.config(value=p))
            elif line.strip():
                last_err = line.strip()
        code = proc.wait()
        self.after(0, lambda: self._export_done(code == 0, last_err, out))

    def _export_done(self, ok, err, out):
        self.export_btn.config(state="normal")
        if ok:
            self.progress["value"] = 100
            self.status_label.config(text="Done.")
            messagebox.showinfo("Export complete", f"Saved:\n{out}")
        else:
            self.progress["value"] = 0
            self.status_label.config(text="Export failed.")
            messagebox.showerror("Export failed", err or "ffmpeg error.")


if __name__ == "__main__":
    App().mainloop()
