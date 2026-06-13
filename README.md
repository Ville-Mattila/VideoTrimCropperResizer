# Leike

**Leike** (Finnish for *a clip*) — a small, quick Windows app for ffmpeg.
**Drag in a video; crop, trim, resize, transform, adjust, overlay, and
convert it — then export.** Defaults to a widely compatible H.264 `.mp4`,
with WebM, GIF, and MP3 a click away.

## The app

Easiest: download **`Leike-Setup.exe`** from the
[Releases page](https://github.com/Ville-Mattila/Leike/releases)
and run it. It installs the app and ffmpeg together, adds a Start Menu
shortcut, and registers an uninstaller (per-user — no admin prompt).

Prefer no install? The **portable zip** (ffmpeg bundled) and the standalone
**`Leike.exe`** also work — just unzip / double-click.

> Leike uses **ffmpeg** for the actual work. The exe looks for it next to
> the .exe, inside the bundle, then on your PATH. The installer and portable
> zip ship `ffmpeg.exe`, so they work out of the box. For the standalone
> `Leike.exe` on a machine without ffmpeg, drop an `ffmpeg.exe` beside it.
> (`ffprobe` is used when present for precise metadata, but isn't required —
> Leike falls back to `ffmpeg` alone.)

## Features

- **Crop** with aspect presets (9:16, 1:1, 4:5, 16:9) that lock the shape, or
  *Free* — drag a box on the preview, move it, resize from the corners.
- **Trim** with a scrubbable preview and a filmstrip timeline. *Fast trim*
  cuts losslessly (no re-encode) when the cut allows it.
- **Resize / downscale** to common heights, or **fit under a target file
  size** (auto two-pass bitrate).
- **Formats:** H.264 MP4, WebM (VP9), animated GIF, or MP3 (audio-only).
- **GPU encoding** (NVENC) — on by default when a compatible GPU is detected,
  for much faster exports.
- **Transforms:** rotate, mirror, change speed, fade in/out, aspect-fill
  (crop or blurred pad), reverse / boomerang, and loop.
- **Adjustments:** brightness, contrast, saturation, grayscale, denoise,
  sharpen, and **stabilization** (two-pass deshake).
- **Overlays:** a text caption, an image watermark, or burned-in subtitles.
- **Audio:** mute, set volume, or export audio only.
- **Frame grab** — save the current preview frame as a still image.
- Remembers your settings between runs, keyboard shortcuts, and a native
  dark title bar.

## How to use

1. **Open** — drag a video onto the window (or click **Open…**). A preview
   frame appears.
2. **Crop** *(Crop tab)* — drag a rectangle on the preview. Drag inside it to
   move, a corner to resize. Pick an aspect preset to lock the shape, or
   *Free*. *Reset to full frame* clears it.
3. **Trim** — drag the **Preview** slider to scrub, then click **Set start**
   / **Set end** (or type times like `1:23.500`). The duration shows below.
4. **Tweak** *(optional)* — the tabs hold everything else:
   - **Effects** — rotate/mirror, speed, fades, aspect fill, reverse/loop,
     plus brightness/contrast/saturation, grayscale, denoise, sharpen, and
     stabilize.
   - **Overlay** — add a text caption, watermark image, or subtitle file.
   - **Audio** — mute, adjust volume, or export audio only.
5. **Export** *(Export tab)* — pick the format, optional downscale, quality
   (CRF), target size, and GPU toggle. Then hit **Export video** (pinned at
   the bottom, always visible) and choose where to save.

## Output

By default: H.264 (`libx264`), `yuv420p`, `+faststart` for instant web
playback, AAC audio at 128 kbps — a widely compatible format that plays
virtually anywhere. Crop offsets/dimensions are snapped to even numbers as
H.264 requires. WebM, GIF, and MP3 outputs are also available.

## Developing / rebuilding

Source is a single file: `leike.py` (Python 3 + tkinter).

- Run from source: `python leike.py` (or `Run.bat`)
- Run the tests: `python -m pytest` (pure command-builder + UI-structure tests)
- Rebuild the exe: `Build-exe.bat` (needs `pip install tkinterdnd2 pyinstaller`)
- Rebuild the installer: `Build-installer.bat` (needs Inno Setup 6 and ffmpeg
  on PATH)

The app uses a custom **warm-dark + gold** theme drawn from the Leike logo
(`leike.svg`) — including a hand-built flat tab bar — plus DWM calls for a
dark title bar whose caption colour matches the window. Drag-and-drop is
provided by **tkinterdnd2** (optional — without it the app still runs via the
*Open…* button).

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
