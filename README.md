# VIDEOTRIMMERCROPPERRESIZER

A fully standalone version and a version for previous FFMPEG owners

A small Windows app for ffmpeg. **Drag in a video, crop it, trim its
length, and export it as a widely compatible H.264 `.mp4`.**

## The app

Easiest: download **`VideoTrimCropResize-Setup.exe`** from the
[Releases page](https://github.com/Ville-Mattila/VideoTrimCropperResizer/releases)
and run it. It installs the app and ffmpeg together, adds a Start Menu
shortcut, and registers an uninstaller (per-user — no admin prompt).

Prefer no install? The portable zip and the standalone
**`dist\VideoTrimCropResize.exe`** also work — just double-click.

> It uses **ffmpeg** for the actual work, found on your PATH (or placed
> next to the .exe). ffmpeg/ffprobe are already on this machine. To run the
> exe on a computer *without* ffmpeg, drop `ffmpeg.exe` and `ffprobe.exe`
> into the same folder as the .exe.

## How to use

1. **Drag a video** onto the window (or click *Open video…*). A preview
   frame appears.
2. **Crop** — drag a rectangle on the preview. Drag inside it to move,
   drag a corner to resize. Pick an aspect preset (9:16, 1:1, 4:5, 16:9) to
   lock the shape, or *Free*. *Reset to full frame* clears it.
3. **Trim** — drag the **Preview** slider to scrub, then click
   *Set from playhead* next to Start or End (or type times like `1:23.500`).
4. **Export** — optionally downscale and set quality (CRF), then
   *Export video…* and choose where to save.

## Output

H.264 (`libx264`), `yuv420p`, `+faststart` for instant web playback, AAC
audio at 128 kbps — a widely compatible format that plays virtually anywhere.
Crop offsets/dimensions are snapped to even numbers as H.264 requires.

## Developing / rebuilding

Source is a single file: `video_trim_crop.py` (Python 3 + tkinter).

- Run from source: `python video_trim_crop.py` (or `Run.bat`)
- Rebuild the exe: `Build-exe.bat`
  (needs `pip install tkinterdnd2 sv-ttk pyinstaller`)

The app uses a native-looking dark theme on Windows — **sv-ttk** (Sun Valley /
Windows 11 Fluent) for the widgets, plus DWM calls for a dark title bar whose
caption colour matches the window. Drag-and-drop is provided by **tkinterdnd2**.
Both are optional: without them the app still runs (button-only, with a
hand-rolled dark fallback theme).

## License

The source code in this repository is licensed under the **MIT License**
(see [`LICENSE`](LICENSE)) — fully free to use, modify, and redistribute.

This app runs **ffmpeg** as a separate program; it does not link ffmpeg's
libraries. The two are independent works:

- **This project's code** — MIT.
- **ffmpeg** — when bundled (the *portable* release), `ffmpeg.exe` is a
  **GPLv3** build by [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), © the
  FFmpeg developers, redistributed with its license and source pointer. The
  GPL applies to that binary only, not to this project's code.
- Other bundled runtimes (Python, Tcl/Tk, tkinterdnd2, the PyInstaller
  bootloader) are under permissive / exception licenses.

Full attribution and license texts: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
and [`licenses/`](licenses/).
