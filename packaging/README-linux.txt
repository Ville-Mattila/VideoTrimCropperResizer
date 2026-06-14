Leike (Linux x86_64)
====================

A small, quick app for ffmpeg: trim, crop, resize, transform, adjust,
overlay, and convert videos, then export.

Requires ffmpeg AND ffprobe on your PATH:
  Debian / Ubuntu:  sudo apt install ffmpeg
  Fedora:           sudo dnf install ffmpeg
  Arch:             sudo pacman -S ffmpeg

Run it:
  ./Leike
  (or double-click it in your file manager, if it's marked executable)

Notes
-----
- Drag-and-drop is not enabled in this build; use the "Open..." button.
- The dark title bar is a Windows-only touch; on Linux you get your
  desktop's native window decorations.

Licence
-------
The app's own code is MIT-licensed (see LICENSE.txt). ffmpeg is a separate
program you install via your distribution; its own licence applies to it.
Full attribution is in THIRD_PARTY_NOTICES.txt.
