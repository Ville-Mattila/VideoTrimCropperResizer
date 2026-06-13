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

# Speed presets: label -> playback-rate multiplier.
SPEEDS = [("0.25×", 0.25), ("0.5×", 0.5), ("1×", 1.0), ("2×", 2.0), ("4×", 4.0)]

# Aspect-fill modes: label -> ExportSettings.fill_mode value.
FILL_MODES = [("Crop to fit", "crop"), ("Blurred background", "blur_pad")]

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
    rotate: int = 0                 # 0/90/180/270 clockwise
    flip_h: bool = False            # mirror horizontally
    flip_v: bool = False            # mirror vertically
    speed: float = 1.0              # playback speed (2.0 = 2x faster)
    fade_in: float = 0.0            # seconds of fade-from-black at the start
    fade_out: float = 0.0           # seconds of fade-to-black at the end
    fill_mode: str = "crop"         # "crop" | "blur_pad" (aspect conversion)
    target_aspect: float | None = None   # w/h for blur_pad
    reverse: bool = False           # play backwards
    boomerang: bool = False         # forward then backward
    loop: int = 0                   # repeat the clip N times (0/1 = once)
    brightness: float = 0.0         # eq brightness (-1..1, 0 = unchanged)
    contrast: float = 1.0           # eq contrast (1.0 = unchanged)
    saturation: float = 1.0         # eq saturation (1.0 = unchanged)
    grayscale: bool = False         # desaturate to black & white
    denoise: bool = False           # hqdn3d denoise
    sharpen: bool = False           # unsharp mask
    watermark_path: str | None = None    # image overlaid in a corner
    watermark_pos: str = "br"       # tl | tr | bl | br
    text: str = ""                  # caption text (drawtext)
    text_pos: str = "bottom"        # top | bottom
    subtitles_path: str | None = None    # SRT to burn in
    stabilize: bool = False         # two-pass vidstab deshake


def _out_dims(s):
    """Final output (w, h) after crop + optional downscale, even numbers."""
    w, h = (s.crop[2], s.crop[3]) if s.crop else (s.src_w, s.src_h)
    w, h = even(w), even(h)
    if s.scale_cap and max(w, h) > s.scale_cap:
        f = s.scale_cap / max(w, h)
        w, h = even(w * f), even(h * f)
    return max(2, w), max(2, h)


def _crop_filter(s):
    if s.crop:
        x, y, w, h = s.crop
        return [f"crop={even(w)}:{even(h)}:{even(x)}:{even(y)}"]
    return []


def _orient_filters(s):
    out = []
    r = getattr(s, "rotate", 0) % 360
    if r == 90:
        out.append("transpose=1")
    elif r == 180:
        out += ["transpose=1", "transpose=1"]
    elif r == 270:
        out.append("transpose=2")
    if getattr(s, "flip_h", False):
        out.append("hflip")
    if getattr(s, "flip_v", False):
        out.append("vflip")
    return out


def _adjust_filters(s):
    """Colour / denoise / sharpen filters (all linear)."""
    out = []
    b = getattr(s, "brightness", 0.0)
    c = getattr(s, "contrast", 1.0)
    sat = getattr(s, "saturation", 1.0)
    if b != 0.0 or c != 1.0 or sat != 1.0:
        out.append(f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={sat:.3f}")
    if getattr(s, "grayscale", False):
        out.append("hue=s=0")
    if getattr(s, "denoise", False):
        out.append("hqdn3d")
    if getattr(s, "sharpen", False):
        out.append("unsharp")
    return out


def _ff_escape_path(p):
    """Escape a Windows path for use inside an ffmpeg filter option value."""
    return p.replace("\\", "/").replace(":", "\\:")


def _drawtext_filter(s):
    """Caption via drawtext; uses a temp textfile to avoid text escaping."""
    txt = getattr(s, "text", "") or ""
    if not txt.strip():
        return []
    tf = os.path.join(tempfile.gettempdir(), f"leike_text_{os.getpid()}.txt")
    try:
        with open(tf, "w", encoding="utf-8") as f:
            f.write(txt)
    except OSError:
        return []
    y = "h-th-40" if getattr(s, "text_pos", "bottom") == "bottom" else "40"
    font = _ff_escape_path("C:/Windows/Fonts/arial.ttf")
    return [f"drawtext=fontfile='{font}':textfile='{_ff_escape_path(tf)}':"
            f"fontcolor=white:fontsize=36:borderw=3:bordercolor=black:"
            f"x=(w-tw)/2:y={y}"]


def _subtitles_filter(s):
    p = getattr(s, "subtitles_path", None)
    return [f"subtitles='{_ff_escape_path(p)}'"] if p else []


def _inputs(s):
    """ffmpeg input section, adding the watermark image as a 2nd input."""
    dur = max(0.001, s.end - s.start)
    base = ["-ss", f"{s.start:.3f}", "-i", s.input_path]
    if getattr(s, "watermark_path", None) and s.fmt in ("mp4", "webm"):
        base += ["-i", s.watermark_path]
    return base + ["-t", f"{dur:.3f}"]


def _speed_filter(s):
    sp = getattr(s, "speed", 1.0)
    return [f"setpts={1.0 / sp:.4f}*PTS"] if sp != 1.0 else []


def _scale_filter(s):
    ow, oh = _out_dims(s)
    cw = even(s.crop[2]) if s.crop else even(s.src_w)
    ch = even(s.crop[3]) if s.crop else even(s.src_h)
    return [f"scale={ow}:{oh}:flags=lanczos"] if (ow, oh) != (cw, ch) else []


def _fade_filters(s):
    out = []
    od = (s.end - s.start) / (getattr(s, "speed", 1.0) or 1.0)
    fi = getattr(s, "fade_in", 0.0) or 0.0
    fo = getattr(s, "fade_out", 0.0) or 0.0
    if fi > 0:
        out.append(f"fade=t=in:st=0:d={fi:.2f}")
    if fo > 0:
        out.append(f"fade=t=out:st={max(0.0, od - fo):.2f}:d={fo:.2f}")
    return out


def _atempo_chain(speed):
    out, r = [], speed
    while r > 2.0:
        out.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        out.append("atempo=0.5")
        r *= 2.0
    out.append(f"atempo={r:.4f}")
    return out


def _linear_video(s, with_scale=True):
    """Linear video filters: crop, orient, adjust, speed, scale, fade, reverse."""
    chain = (_crop_filter(s) + _orient_filters(s) + _adjust_filters(s)
             + _speed_filter(s))
    if with_scale:
        chain += _scale_filter(s)
    chain += _fade_filters(s)
    if getattr(s, "reverse", False):
        chain.append("reverse")
    chain += _drawtext_filter(s) + _subtitles_filter(s)
    return chain


def _blurpad_dims(s):
    sh = even(s.crop[3]) if s.crop else even(s.src_h)
    w, h = even(sh * s.target_aspect), sh
    if s.scale_cap and max(w, h) > s.scale_cap:
        f = s.scale_cap / max(w, h)
        w, h = even(w * f), even(h * f)
    return max(2, w), max(2, h)


def _is_complex(s):
    """True when the video pipeline needs -filter_complex (splits/overlay)."""
    return bool((getattr(s, "fill_mode", "crop") == "blur_pad"
                 and getattr(s, "target_aspect", None))
                or getattr(s, "boomerang", False)
                or (getattr(s, "loop", 0) or 0) > 1
                or getattr(s, "watermark_path", None))


def _video_graph(s, add_format=True):
    """Return (flag, value, out_label). flag is '-vf' (label None) or
    '-filter_complex' (label like '[v3]')."""
    if not _is_complex(s):
        chain = _linear_video(s)
        if add_format:
            chain.append("format=yuv420p")
        return ("-vf", ",".join(chain) if chain else "null", None)

    segs, idx = [], [0]

    def lab():
        idx[0] += 1
        return f"v{idx[0]}"

    cur = "0:v"
    pre = (_crop_filter(s) + _orient_filters(s) + _adjust_filters(s)
           + _speed_filter(s))
    if getattr(s, "fill_mode", "crop") == "blur_pad" and s.target_aspect:
        w, h = _blurpad_dims(s)
        prestr = (",".join(pre) + ",") if pre else ""
        segs.append(f"[{cur}]{prestr}split=2[bg][fg]")
        segs.append(f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
                    f"crop={w}:{h},gblur=sigma=20[bgb]")
        segs.append(f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs]")
        o = lab()
        segs.append(f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[{o}]")
        cur = o
    else:
        chain = pre + _scale_filter(s)
        o = lab()
        segs.append(f"[{cur}]{','.join(chain) if chain else 'null'}[{o}]")
        cur = o

    post = _fade_filters(s)
    if getattr(s, "reverse", False):
        post.append("reverse")
    post += _drawtext_filter(s) + _subtitles_filter(s)
    if post:
        o = lab()
        segs.append(f"[{cur}]{','.join(post)}[{o}]")
        cur = o

    if getattr(s, "boomerang", False):
        o = lab()
        segs.append(f"[{cur}]split=2[ba][bb];[bb]reverse[br];"
                    f"[ba][br]concat=n=2:v=1[{o}]")
        cur = o
    elif (getattr(s, "loop", 0) or 0) > 1:
        n = s.loop
        ls = [f"lc{i}" for i in range(n)]
        o = lab()
        segs.append(f"[{cur}]split={n}" + "".join(f"[{x}]" for x in ls) + ";"
                    + "".join(f"[{x}]" for x in ls) + f"concat=n={n}:v=1[{o}]")
        cur = o

    if getattr(s, "watermark_path", None):
        pad = 12
        pos = {"tl": f"{pad}:{pad}", "tr": f"W-w-{pad}:{pad}",
               "bl": f"{pad}:H-h-{pad}", "br": f"W-w-{pad}:H-h-{pad}"}
        o = lab()
        segs.append(f"[{cur}][1:v]overlay="
                    f"{pos.get(s.watermark_pos, pos['br'])}[{o}]")
        cur = o

    if add_format:
        o = lab()
        segs.append(f"[{cur}]format=yuv420p[{o}]")
        cur = o
    return ("-filter_complex", ";".join(segs), f"[{cur}]")


def _af_chain(s):
    """Audio filters for the linear path: volume, atempo (speed), areverse."""
    af = []
    if not getattr(s, "mute", False) and getattr(s, "volume", 1.0) != 1.0:
        af.append(f"volume={s.volume:.3f}")
    if getattr(s, "speed", 1.0) != 1.0:
        af += _atempo_chain(s.speed)
    if getattr(s, "reverse", False):
        af.append("areverse")
    return af


def _av_reencode(s, vcodec, acodec, abr, extra_v=()):
    """Video + audio args for a re-encode, choosing -vf vs -filter_complex."""
    flag, fval, vmap = _video_graph(s)
    if vmap:  # filter_complex: explicit maps; audio passes through (or muted)
        args = [flag, fval, "-map", vmap, *vcodec, *extra_v]
        if not getattr(s, "mute", False):
            args += ["-map", "0:a?", "-c:a", acodec, "-b:a", abr]
    else:     # -vf: audio auto-mapped; filter with -af
        args = [flag, fval, *vcodec, *extra_v]
        if getattr(s, "mute", False):
            args += ["-an"]
        else:
            af = _af_chain(s)
            if af:
                args += ["-af", ",".join(af)]
            args += ["-c:a", acodec, "-b:a", abr]
    return args


def _gif_passes(s):
    """GIF via two passes: build an optimal palette, then render with it."""
    pre = ",".join(_linear_video(s) + [f"fps={s.gif_fps}"])
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
            and not getattr(s, "audio_only", False)
            and getattr(s, "brightness", 0.0) == 0.0
            and getattr(s, "contrast", 1.0) == 1.0
            and getattr(s, "saturation", 1.0) == 1.0
            and not getattr(s, "grayscale", False)
            and not getattr(s, "denoise", False)
            and not getattr(s, "sharpen", False)
            and not getattr(s, "watermark_path", None)
            and not (getattr(s, "text", "") or "").strip()
            and not getattr(s, "subtitles_path", None)
            and not getattr(s, "stabilize", False))


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
    flag, fval, vmap = _video_graph(s)
    inp = _inputs(s)
    vbase = [flag, fval] + (["-map", vmap] if vmap else []) \
        + ["-c:v", "libx264", "-b:v", f"{vbit}k"]
    p1 = [FFMPEG, "-y", *inp, *vbase, "-pass", "1", "-passlogfile", log,
          "-an", "-f", "mp4", null]
    if s.mute:
        a2 = ["-an"]
    elif vmap:
        a2 = ["-map", "0:a?", "-c:a", "aac", "-b:a", "128k"]
    else:
        a2 = (["-af", ",".join(_af_chain(s))] if _af_chain(s) else []) \
            + ["-c:a", "aac", "-b:a", "128k"]
    p2 = [FFMPEG, "-y", *inp, *vbase, "-pass", "2", "-passlogfile", log,
          *a2, "-movflags", "+faststart", s.output_path]
    return [p1, p2]


def _stabilize_passes(s):
    """Two-pass vidstab: detect camera shake, then compensate."""
    trf = _ff_escape_path(s.output_path + ".trf")
    dur = max(0.001, s.end - s.start)
    inp = ["-ss", f"{s.start:.3f}", "-i", s.input_path, "-t", f"{dur:.3f}"]
    null = "NUL" if os.name == "nt" else "/dev/null"
    p1 = [FFMPEG, "-y", *inp,
          "-vf", f"vidstabdetect=shakiness=6:accuracy=12:result='{trf}'",
          "-f", "null", null]
    chain = ([f"vidstabtransform=input='{trf}':smoothing=14"]
             + _linear_video(s) + ["format=yuv420p"])
    p2 = [FFMPEG, "-y", *inp, "-vf", ",".join(chain), *_venc(s),
          "-pix_fmt", "yuv420p"]
    if s.mute:
        p2 += ["-an"]
    else:
        af = _af_chain(s)
        if af:
            p2 += ["-af", ",".join(af)]
        p2 += ["-c:a", "aac", "-b:a", "128k"]
    p2 += ["-movflags", "+faststart", s.output_path]
    return [p1, p2]


def build_commands(s):
    """Return a list of ffmpeg command arg-lists (one or more passes)."""
    dur = max(0.001, s.end - s.start)
    common = ["-ss", f"{s.start:.3f}", "-i", s.input_path, "-t", f"{dur:.3f}"]

    if getattr(s, "audio_only", False):
        af = _af_chain(s)
        extra = ["-af", ",".join(af)] if af else []
        return [[FFMPEG, "-y", *common, "-vn", *extra,
                 "-c:a", "libmp3lame", "-q:a", "2", s.output_path]]

    if s.fmt == "gif":
        return _gif_passes(s)

    if s.fmt == "webm":
        return [[FFMPEG, "-y", *_inputs(s),
                 *_av_reencode(s, ["-c:v", "libvpx-vp9", "-crf", str(s.crf),
                                   "-b:v", "0"], "libopus", "128k"),
                 s.output_path]]

    # mp4
    if getattr(s, "stabilize", False):
        return _stabilize_passes(s)
    if s.target_size_mb:
        return _size_target_passes(s)
    if _is_passthrough(s):
        return [[FFMPEG, "-y", *common, "-c", "copy", "-movflags", "+faststart",
                 s.output_path]]
    return [[FFMPEG, "-y", *_inputs(s),
             *_av_reencode(s, _venc(s), "aac", "128k",
                           extra_v=["-pix_fmt", "yuv420p"]),
             "-movflags", "+faststart", s.output_path]]


def _config_path():
    base = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()),
                        "Leike")
    return os.path.join(base, "config.json")


def load_config():
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(_config_path()), exist_ok=True)
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


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
        self._strip_img = None
        self._strip_token = 0
        self._strip_after = None
        self._tmp_png = os.path.join(
            tempfile.gettempdir(), f"vtc_preview_{os.getpid()}.png"
        )

        self.export_proc = None
        self._cancelled = False
        self.has_nvenc = self._detect_nvenc()

        self._apply_theme()
        self._build_ui()
        self._apply_dark_titlebar()
        self._cfg = load_config()
        self.out_dir = self._cfg.get("out_dir")
        self._apply_config()
        self._bind_shortcuts()

    def _apply_config(self):
        c = self._cfg
        try:
            if c.get("fmt") in [f[0] for f in FORMATS]:
                self.fmt_var.set(c["fmt"])
                self._on_format_change()
            if c.get("scale") in [s[0] for s in SCALE_OPTIONS]:
                self.scale_var.set(c["scale"])
            if isinstance(c.get("crf"), int):
                self.crf_var.set(c["crf"])
                self.crf_label.config(text=str(c["crf"]))
            if isinstance(c.get("fast_trim"), bool):
                self.fast_trim_var.set(c["fast_trim"])
            if isinstance(c.get("hw"), bool) and self.has_nvenc:
                self.hw_var.set(c["hw"])
        except Exception:
            pass

    def _save_config(self):
        save_config({
            "out_dir": self.out_dir,
            "fmt": self.fmt_var.get(),
            "scale": self.scale_var.get(),
            "crf": self.crf_var.get(),
            "fast_trim": self.fast_trim_var.get(),
            "hw": self.hw_var.get(),
        })

    def _bind_shortcuts(self):
        self.bind("<Control-e>", lambda e: self._shortcut_export())
        self.bind("<Control-g>",
                  lambda e: self.grab_frame() if self.input_path else None)
        self.bind("<Escape>", lambda e: self.cancel_export())
        self.bind("[", lambda e: (self.set_from_playhead("start")
                                  if self.input_path else None))
        self.bind("]", lambda e: (self.set_from_playhead("end")
                                  if self.input_path else None))

    def _shortcut_export(self):
        if self.input_path and str(self.export_btn["state"]) == "normal":
            self.export()

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
        # Notebook (tabs)
        style.configure("TNotebook", background=BASE_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_BG, foreground=MUTED,
                        padding=(10, 6), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", PANEL_HI)],
                  foreground=[("selected", GOLD)])
        # Primary (accent) button — gold fill, dark text
        style.configure("Accent.TButton", background=GOLD, foreground=BASE_BG,
                        bordercolor=GOLD_DEEP, relief="flat", padding=7)
        style.map("Accent.TButton",
                  background=[("active", GOLD_LIGHT), ("pressed", GOLD_DEEP)],
                  foreground=[("disabled", MUTED)])
        # Small uppercase section label
        style.configure("Section.TLabel", foreground=MUTED, background=BASE_BG)

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

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.configure(bg=BASE_BG)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # ---- Header bar ----
        header = ttk.Frame(self, padding=(12, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(3, weight=1)
        logo = tk.Canvas(header, width=16, height=16, bg=BASE_BG,
                         highlightthickness=0)
        logo.create_rectangle(0, 0, 16, 16, fill=GOLD, outline="")
        logo.grid(row=0, column=0, padx=(0, 8))
        ttk.Label(header, text="Leike", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=1)
        ttk.Button(header, text="Open…", command=self.open_file).grid(
            row=0, column=2, padx=(12, 0))
        hint = "No file loaded — drag a video in or click Open…"
        self.file_label = ttk.Label(header, text=hint, foreground=MUTED,
                                    anchor="e")
        self.file_label.grid(row=0, column=3, sticky="e")
        ttk.Separator(self, orient="horizontal").grid(row=0, column=0,
                                                      sticky="sew")

        # ---- Body ----
        root = ttk.Frame(self, padding=10)
        root.grid(row=1, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=0)
        root.rowconfigure(0, weight=1)

        # Left: preview + scrub + filmstrip + trim + grab
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(left, width=PREVIEW_MAX_W, height=PREVIEW_MAX_H,
                                bg=CANVAS_BG, highlightthickness=1,
                                highlightbackground=CANVAS_BORDER)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_up)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._draw_drop_hint()

        scrub = ttk.Frame(left)
        scrub.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        scrub.columnconfigure(1, weight=1)
        ttk.Label(scrub, text="Preview").grid(row=0, column=0, padx=(0, 6))
        self.scrub_var = tk.DoubleVar(value=0.0)
        self.scrub = ttk.Scale(scrub, from_=0, to=1, variable=self.scrub_var,
                               command=self.on_scrub)
        self.scrub.grid(row=0, column=1, sticky="ew")
        self.playhead_label = ttk.Label(scrub, text="00:00.000", width=12)
        self.playhead_label.grid(row=0, column=2, padx=(6, 0))

        self.strip = tk.Canvas(left, height=52, bg=PANEL_BG,
                               highlightthickness=1, highlightbackground=BORDER)
        self.strip.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.strip.bind("<Button-1>", self._strip_seek)
        self.strip.bind("<B1-Motion>", self._strip_seek)
        self.strip.bind("<Configure>", self._on_strip_resize)

        self._build_trim_row(left, row=3)
        self.grab_btn = ttk.Button(left, text="Grab frame",
                                   command=self.grab_frame, state="disabled")
        self.grab_btn.grid(row=4, column=0, sticky="w", pady=(6, 0))

        if HAS_DND:
            for w in (self, self.canvas):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)

        # Right: notebook + persistent footer
        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        right.rowconfigure(0, weight=1)
        nb = ttk.Notebook(right, width=330)
        nb.grid(row=0, column=0, sticky="nsew")
        tab_crop = ttk.Frame(nb, padding=8)
        tab_fx = ttk.Frame(nb, padding=8)
        tab_overlay = ttk.Frame(nb, padding=8)
        tab_audio = ttk.Frame(nb, padding=8)
        tab_export = ttk.Frame(nb, padding=8)
        for f in (tab_crop, tab_fx, tab_overlay, tab_audio, tab_export):
            f.columnconfigure(0, weight=1)
        nb.add(tab_crop, text="Crop")
        nb.add(tab_fx, text="Effects")
        nb.add(tab_overlay, text="Overlay")
        nb.add(tab_audio, text="Audio")
        nb.add(tab_export, text="Export")
        self.notebook = nb

        self._build_crop_panel(tab_crop)
        self._build_transform_panel(tab_fx)
        self._build_adjust_panel(tab_fx)
        self._build_overlay_panel(tab_overlay)
        self._build_audio_panel(tab_audio)
        self._build_export_panel(tab_export)

        self._build_footer(right, row=1)

    def _build_trim_row(self, parent, row):
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(box, text="TRIM", style="Section.TLabel").grid(
            row=0, column=0, columnspan=6, sticky="w")
        self.start_var = tk.StringVar(value="00:00.000")
        e1 = ttk.Entry(box, textvariable=self.start_var, width=11)
        e1.grid(row=1, column=0, padx=(0, 4), pady=(2, 0))
        e1.bind("<Return>", lambda _e: self.commit_times())
        e1.bind("<FocusOut>", lambda _e: self.commit_times())
        ttk.Button(box, text="Set start",
                   command=lambda: self.set_from_playhead("start")).grid(
            row=1, column=1, pady=(2, 0))
        ttk.Label(box, text="→").grid(row=1, column=2, padx=4)
        self.end_var = tk.StringVar(value="00:00.000")
        e2 = ttk.Entry(box, textvariable=self.end_var, width=11)
        e2.grid(row=1, column=3, padx=(0, 4), pady=(2, 0))
        e2.bind("<Return>", lambda _e: self.commit_times())
        e2.bind("<FocusOut>", lambda _e: self.commit_times())
        ttk.Button(box, text="Set end",
                   command=lambda: self.set_from_playhead("end")).grid(
            row=1, column=4, pady=(2, 0))
        self.trim_label = ttk.Label(box, text="Duration: 0.000 s",
                                    foreground=MUTED)
        self.trim_label.grid(row=2, column=0, columnspan=6, sticky="w",
                             pady=(3, 0))

    def _build_footer(self, parent, row):
        box = ttk.Frame(parent, padding=(0, 10, 0, 0))
        box.grid(row=row, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        self.export_btn = ttk.Button(box, text="⬇  Export video",
                                     style="Accent.TButton",
                                     command=self.export, state="disabled")
        self.export_btn.grid(row=0, column=0, sticky="ew")
        self.cancel_btn = ttk.Button(box, text="Cancel",
                                     command=self.cancel_export, state="disabled")
        self.cancel_btn.grid(row=0, column=1, padx=(6, 0))
        self.export_hint = ttk.Label(box, text="", foreground=GOLD)
        self.export_hint.grid(row=1, column=0, columnspan=2, sticky="w",
                              pady=(6, 0))
        self.progress = ttk.Progressbar(box, mode="determinate")
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew",
                           pady=(4, 0))
        self.status_label = ttk.Label(box, text="", foreground=MUTED)
        self.status_label.grid(row=3, column=0, columnspan=2, sticky="w",
                               pady=(3, 0))

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

    def _build_export_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Export", padding=8)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))

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

        # Encoding options (fast-trim / GPU / target size) share this tab.
        self._build_encoding_panel(parent)

    def _build_encoding_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Encoding", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 8))
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
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
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

    def _build_transform_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Transform", padding=8)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hint = self._update_export_hint

        self.rotate_val = 0
        rrow = ttk.Frame(box)
        rrow.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(rrow, text="⟲", width=3,
                   command=lambda: self._rotate(-90)).grid(row=0, column=0)
        ttk.Button(rrow, text="⟳", width=3,
                   command=lambda: self._rotate(90)).grid(row=0, column=1,
                                                          padx=(2, 6))
        self.rotate_label = ttk.Label(rrow, text="0°", width=4)
        self.rotate_label.grid(row=0, column=2)
        self.flip_h_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(rrow, text="Mirror H", variable=self.flip_h_var,
                        command=hint).grid(row=0, column=3, padx=(6, 0))
        self.flip_v_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(rrow, text="Mirror V", variable=self.flip_v_var,
                        command=hint).grid(row=0, column=4, padx=(6, 0))

        ttk.Label(box, text="Speed").grid(row=1, column=0, sticky="w",
                                          pady=(6, 0))
        self.speed_var = tk.StringVar(value="1×")
        sc = ttk.Combobox(box, textvariable=self.speed_var, state="readonly",
                          width=8, values=[s[0] for s in SPEEDS])
        sc.grid(row=1, column=1, sticky="w", pady=(6, 0))
        sc.bind("<<ComboboxSelected>>", lambda _e: hint())

        frow = ttk.Frame(box)
        frow.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(frow, text="Fade in").grid(row=0, column=0)
        self.fade_in_var = tk.StringVar(value="0")
        ttk.Entry(frow, textvariable=self.fade_in_var, width=4).grid(
            row=0, column=1, padx=(2, 8))
        ttk.Label(frow, text="out").grid(row=0, column=2)
        self.fade_out_var = tk.StringVar(value="0")
        ttk.Entry(frow, textvariable=self.fade_out_var, width=4).grid(
            row=0, column=3, padx=(2, 2))
        ttk.Label(frow, text="sec").grid(row=0, column=4)

        ttk.Label(box, text="Aspect fill").grid(row=3, column=0, sticky="w",
                                                pady=(6, 0))
        self.fill_var = tk.StringVar(value=FILL_MODES[0][0])
        fc = ttk.Combobox(box, textvariable=self.fill_var, state="readonly",
                          width=18, values=[f[0] for f in FILL_MODES])
        fc.grid(row=3, column=1, sticky="w", pady=(6, 0))
        fc.bind("<<ComboboxSelected>>", lambda _e: hint())

        ttk.Label(box, text="Effect").grid(row=4, column=0, sticky="w",
                                           pady=(6, 0))
        self.effect_var = tk.StringVar(value="None")
        ec = ttk.Combobox(box, textvariable=self.effect_var, state="readonly",
                          width=10, values=["None", "Reverse", "Boomerang"])
        ec.grid(row=4, column=1, sticky="w", pady=(6, 0))
        ec.bind("<<ComboboxSelected>>", lambda _e: hint())

        ttk.Label(box, text="Loop ×").grid(row=5, column=0, sticky="w",
                                           pady=(6, 0))
        self.loop_var = tk.IntVar(value=1)
        ttk.Spinbox(box, from_=1, to=10, width=4, textvariable=self.loop_var,
                    command=hint).grid(row=5, column=1, sticky="w", pady=(6, 0))

    def _rotate(self, delta):
        self.rotate_val = (self.rotate_val + delta) % 360
        self.rotate_label.config(text=f"{self.rotate_val}°")
        self._update_export_hint()

    def _build_adjust_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Adjust", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        def slider(row, label, var, frm, to, suffix):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w")
            lbl = ttk.Label(box, text=f"{var.get()}{suffix}", width=5)
            ttk.Scale(box, from_=frm, to=to, variable=var, length=130,
                      command=lambda _v: lbl.config(
                          text=f"{var.get()}{suffix}")).grid(row=row, column=1,
                                                             sticky="w")
            lbl.grid(row=row, column=2, padx=(4, 0))

        self.bright_var = tk.IntVar(value=0)
        slider(0, "Brightness", self.bright_var, -100, 100, "")
        self.contrast_var = tk.IntVar(value=100)
        slider(1, "Contrast", self.contrast_var, 0, 200, "%")
        self.satur_var = tk.IntVar(value=100)
        slider(2, "Saturation", self.satur_var, 0, 200, "%")

        self.gray_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Grayscale", variable=self.gray_var,
                        command=self._update_export_hint).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.denoise_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Denoise", variable=self.denoise_var,
                        command=self._update_export_hint).grid(
            row=4, column=0, sticky="w")
        self.sharpen_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Sharpen", variable=self.sharpen_var,
                        command=self._update_export_hint).grid(
            row=4, column=1, sticky="w")
        self.stabilize_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Stabilize (deshake · 2-pass · MP4)",
                        variable=self.stabilize_var,
                        command=self._update_export_hint).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _build_overlay_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Overlay", padding=8)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.watermark_path = None
        self.subtitles_path = None

        ttk.Label(box, text="Text").grid(row=0, column=0, sticky="w")
        self.text_var = tk.StringVar(value="")
        te = ttk.Entry(box, textvariable=self.text_var, width=18)
        te.grid(row=0, column=1, columnspan=2, sticky="ew")
        te.bind("<KeyRelease>", lambda _e: self._update_export_hint())
        self.text_pos_var = tk.StringVar(value="bottom")
        ttk.Combobox(box, textvariable=self.text_pos_var, state="readonly",
                     width=8, values=["top", "bottom"]).grid(
            row=1, column=1, sticky="w", pady=(0, 4))

        ttk.Button(box, text="Watermark…",
                   command=self._pick_watermark).grid(row=2, column=0, sticky="w")
        self.wm_label = ttk.Label(box, text="none", foreground=MUTED, width=16)
        self.wm_label.grid(row=2, column=1, sticky="w")
        self.wm_pos_var = tk.StringVar(value="br")
        ttk.Combobox(box, textvariable=self.wm_pos_var, state="readonly", width=5,
                     values=["tl", "tr", "bl", "br"]).grid(row=2, column=2,
                                                           sticky="w")

        ttk.Button(box, text="Subtitles…",
                   command=self._pick_subtitles).grid(row=3, column=0, sticky="w",
                                                      pady=(4, 0))
        self.sub_label = ttk.Label(box, text="none", foreground=MUTED, width=16)
        self.sub_label.grid(row=3, column=1, sticky="w", pady=(4, 0))
        ttk.Button(box, text="Clear", width=6,
                   command=self._clear_overlays).grid(row=3, column=2, pady=(4, 0))

    def _pick_watermark(self):
        p = filedialog.askopenfilename(
            title="Watermark image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp"), ("All", "*.*")])
        if p:
            self.watermark_path = p
            self.wm_label.config(text=os.path.basename(p))
            self._update_export_hint()

    def _pick_subtitles(self):
        p = filedialog.askopenfilename(
            title="Subtitle file",
            filetypes=[("Subtitles", "*.srt *.ass"), ("All", "*.*")])
        if p:
            self.subtitles_path = p
            self.sub_label.config(text=os.path.basename(p))
            self._update_export_hint()

    def _clear_overlays(self):
        self.watermark_path = None
        self.wm_label.config(text="none")
        self.subtitles_path = None
        self.sub_label.config(text="none")
        self.text_var.set("")
        self._update_export_hint()

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
        self.grab_btn.config(state="normal")
        self.update_labels()
        self.request_preview(0.0)
        self._build_filmstrip()

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

    # ------------------------------------------------------------- filmstrip
    def _on_strip_resize(self, _e):
        if self._strip_after:
            self.after_cancel(self._strip_after)
        self._strip_after = self.after(250, self._build_filmstrip)

    def _build_filmstrip(self):
        if not self.input_path:
            return
        w = max(self.strip.winfo_width(), 200)
        self._strip_token += 1
        threading.Thread(target=self._gen_strip,
                         args=(w, self._strip_token), daemon=True).start()

    def _gen_strip(self, w, token):
        h = 50
        n = max(6, w // 90)               # ~one thumbnail per 90 px
        tw = max(1, w // n)
        fps = n / max(0.1, self.duration)
        out = os.path.join(tempfile.gettempdir(),
                           f"leike_strip_{os.getpid()}.png")
        run_capture([FFMPEG, "-y", "-i", self.input_path,
                     "-vf", f"fps={fps:.6f},scale={tw}:{h},tile={n}x1",
                     "-frames:v", "1", "-update", "1", out])
        if token != self._strip_token or not os.path.exists(out):
            return
        self.after(0, lambda: self._show_strip(out, token))

    def _show_strip(self, path, token):
        if token != self._strip_token:
            return
        try:
            img = tk.PhotoImage(file=path)
        except tk.TclError:
            return
        self._strip_img = img
        self.strip.delete("all")
        self.strip.create_image(0, 0, anchor="nw", image=img)

    def _strip_seek(self, ev):
        if not self.input_path or not self.duration:
            return
        w = max(self.strip.winfo_width(), 1)
        frac = min(max(ev.x / w, 0.0), 1.0)
        self.scrub_var.set(frac * self.duration)
        self.on_scrub(None)

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
        speed = dict(SPEEDS)[self.speed_var.get()]
        aspect = dict(ASPECTS)[self.aspect_var.get()]
        fill = dict(FILL_MODES)[self.fill_var.get()]
        if fill == "blur_pad" and aspect:
            crop, fill_mode, target_aspect = None, "blur_pad", aspect
        else:
            crop = tuple(self.crop) if self.crop else None
            fill_mode, target_aspect = "crop", None
        effect = self.effect_var.get()
        return ExportSettings(
            input_path=self.input_path, output_path=out,
            src_w=self.src_w, src_h=self.src_h,
            start=self.start_t, end=self.end_t,
            crop=crop,
            scale_cap=dict(SCALE_OPTIONS)[self.scale_var.get()],
            crf=self.crf_var.get(), fmt=dict(FORMATS)[self.fmt_var.get()],
            fast_trim=self.fast_trim_var.get(), hw=self.hw_var.get(),
            gif_fps=self.gif_fps_var.get(), target_size_mb=self._target_mb(),
            mute=self.mute_var.get(), volume=self.volume_var.get() / 100.0,
            audio_only=self.audio_only_var.get(),
            rotate=self.rotate_val, flip_h=self.flip_h_var.get(),
            flip_v=self.flip_v_var.get(), speed=speed,
            fade_in=self._fade_secs(self.fade_in_var),
            fade_out=self._fade_secs(self.fade_out_var),
            fill_mode=fill_mode, target_aspect=target_aspect,
            reverse=(effect == "Reverse"), boomerang=(effect == "Boomerang"),
            loop=self.loop_var.get(),
            brightness=self.bright_var.get() / 100.0,
            contrast=self.contrast_var.get() / 100.0,
            saturation=self.satur_var.get() / 100.0,
            grayscale=self.gray_var.get(), denoise=self.denoise_var.get(),
            sharpen=self.sharpen_var.get(),
            watermark_path=self.watermark_path,
            watermark_pos=self.wm_pos_var.get(),
            text=self.text_var.get(), text_pos=self.text_pos_var.get(),
            subtitles_path=self.subtitles_path,
            stabilize=self.stabilize_var.get())

    @staticmethod
    def _fade_secs(var):
        try:
            return max(0.0, float(var.get() or 0))
        except ValueError:
            return 0.0

    def grab_frame(self):
        """Save the current playhead frame as an image (crop + rotate/flip)."""
        if not self.input_path:
            return
        base = os.path.splitext(os.path.basename(self.input_path))[0]
        out = filedialog.asksaveasfilename(
            title="Save frame as", defaultextension=".png",
            initialfile=f"{base}_frame.png",
            initialdir=self.out_dir or os.path.dirname(self.input_path),
            filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg")])
        if not out:
            return
        s = self._settings(out)
        vf = _crop_filter(s) + _orient_filters(s) + _scale_filter(s)
        cmd = [FFMPEG, "-y", "-ss", f"{self.playhead:.3f}", "-i", self.input_path,
               "-frames:v", "1", "-update", "1"]
        if vf:
            cmd += ["-vf", ",".join(vf)]
        cmd += [out]
        if run_capture(cmd).returncode == 0 and os.path.exists(out):
            self.status_label.config(text="Frame saved.")
            messagebox.showinfo("Frame saved", f"Saved:\n{out}")
        else:
            messagebox.showerror("Grab failed", "Could not save the frame.")

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
            initialdir=self.out_dir or os.path.dirname(self.input_path),
            filetypes=ftypes,
        )
        if not out:
            return
        if os.path.abspath(out) == os.path.abspath(self.input_path):
            messagebox.showerror("Error", "Choose a different output file.")
            return
        self.out_dir = os.path.dirname(out)
        self._save_config()

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
        # Remove any two-pass log / stabilization files.
        if out:
            for f in glob.glob(out + ".2pass*") + glob.glob(out + ".trf"):
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
