# Third-Party Notices

This project's own source code is licensed under the MIT License (see
[`LICENSE`](LICENSE)). The built binaries and the "portable" release bundle a
number of third-party components, each under its own license. They are listed
here with attribution as required.

## How the licenses fit together

The app calls **ffmpeg as a separate command-line program** (via a child
process). It does **not** link against ffmpeg's libraries. Under the GPL, this
is *mere aggregation*: bundling an independent GPL program alongside MIT code
does not place the MIT code under the GPL. The two remain separately licensed.

- **`VideoTrimCropResize.exe` (standalone, 11 MB)** contains only the MIT app
  code plus permissively-licensed runtimes (Python, Tcl/Tk, tkinterdnd2) and
  the PyInstaller bootloader (GPL **with an exception** that permits any-license
  apps). It contains **no GPL-covered code**.
- **The portable `.zip`** additionally contains `ffmpeg.exe`, which **is**
  licensed under the **GNU GPL v3**. That binary is redistributed in compliance
  with the GPL (license text + source pointer included; see below).

---

## ffmpeg  (bundled in the portable release)

- **License:** GNU General Public License, version 3 (GPLv3).
  Full text: [`licenses/ffmpeg-GPLv3.txt`](licenses/ffmpeg-GPLv3.txt).
- **Copyright:** © the FFmpeg developers.
- **Build:** Windows GPL build by Gyan Doshi — https://www.gyan.dev/ffmpeg/builds/
  (configured with `--enable-gpl --enable-version3`; it contains **no**
  `nonfree` components, so it is freely redistributable).
- **Corresponding source code** (GPLv3 §6): FFmpeg source is available from
  https://git.ffmpeg.org/ffmpeg.git and https://ffmpeg.org/download.html .
  Build configuration and scripts for these binaries are published at
  https://github.com/GyanD/codexffmpeg and https://www.gyan.dev/ffmpeg/builds/ .
- "FFmpeg" is a trademark of Fabrice Bellard, originator of the FFmpeg project.
  This project is not affiliated with or endorsed by the FFmpeg project.

## tkinterdnd2  (bundled in every build, for drag-and-drop)

- **License:** MIT License. © Petasis (python wrapper) and contributors.
- https://github.com/pmgagne/tkinterdnd2 / https://pypi.org/project/tkinterdnd2/
- Wraps the native **tkdnd** library (BSD-style license), © George Petasis.

## PyInstaller bootloader  (embedded in the .exe)

- **License:** GPL 2.0 **with a bootloader exception** that explicitly allows
  distributing the bundled bootloader as part of applications under any license.
- https://github.com/pyinstaller/pyinstaller

## CPython runtime  (embedded in the .exe)

- **License:** Python Software Foundation License (permissive, GPL-compatible).
- https://docs.python.org/3/license.html

## Tcl/Tk  (embedded in the .exe, for the GUI)

- **License:** Tcl/Tk License (BSD-style).
- https://www.tcl-lang.org/software/tcltk/license.html
