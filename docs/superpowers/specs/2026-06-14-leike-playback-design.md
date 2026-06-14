# Built-in Playback with Live Effect Preview — Design

**Date:** 2026-06-14
**Component:** `leike.py` (Leike — the ffmpeg front-end)
**Status:** Approved (pending spec review)

## Goal

Let the user **play** the loaded video inside the app — with **audio** — and
see **effects and overlays applied live** during playback, so the preview
matches the exported result. Today the app only shows a single scrubbed,
*un-effected* frame; the crop box is drawn as a guide and nothing else is
previewed.

## Approach (decided)

- **Engine:** embed **libmpv** via the `python-mpv` ctypes wrapper, rendering
  into a Tk frame by passing its window id (`mpv.MPV(wid=...)`). mpv gives
  hardware-decoded video + audio and applies our libavfilter graph live.
- **Dependency posture:** **optional with graceful fallback.** Playback is a
  best-effort enhancement. If `python-mpv`/libmpv is missing, or embedding
  fails (notably on macOS), the app silently falls back to today's
  scrub/frame preview and never crashes.

## Architecture

### Two modes sharing one preview area

- **Edit mode** (default — current behavior): the `tk.Canvas` shows one
  scrubbed frame with the crop rectangle drawn on top for dragging/resizing.
- **Play mode:** a sibling `tk.Frame` occupying the same grid cell is handed
  to libmpv as its render surface. mpv draws the **effected** video there
  with sound. Entering Play mode raises the mpv frame; pausing/stopping
  returns to Edit mode so crop editing resumes.

Rationale: the crop box is an editing affordance and is meaningless once the
crop is actually applied by mpv, so the two are naturally exclusive. The swap
keeps the layout stable and avoids a second large widget.

### Engine wrapper and fallback

- Lazy import mirroring the existing `tkinterdnd2` pattern:
  ```python
  try:
      import mpv
      HAS_MPV = True
  except Exception:
      HAS_MPV = False
  ```
- A small `Player` helper encapsulates the mpv instance, created on first
  play. Construction is wrapped in `try/except`; any failure sets a
  `playback_available = False` flag, hides/disables transport controls beyond
  the basic scrub, and shows a one-line "Playback unavailable — install mpv"
  hint. Every mpv interaction is guarded so the editing app keeps working.
- When `HAS_MPV` is false the play button is disabled with the same hint.

### Effects/overlays via mpv's filtergraph

The preview must match export, so it is built from the **same**
`ExportSettings` and the **same** filter helpers used by `build_commands`
(`_video_graph`, `_adjust_filters`, `_drawtext_filter`, etc.). A new **pure**
function:

```python
def build_preview_vf(s: ExportSettings) -> tuple[str, dict]:
    """Return (mpv_vf_string, mpv_props) for the live-previewable subset
    of settings s. Pure and unit-testable; no GUI, no mpv import."""
```

- `mpv_vf_string` is a libavfilter chain applied via the mpv `vf` property.
- `mpv_props` carries properties set directly on mpv rather than via filters
  (e.g. `speed`, `volume`, `mute`, `sub-file`).
- The function is re-invoked and re-applied whenever a relevant control
  changes while in Play mode (debounced).

**Live-previewable (single linear pass):**

| Setting | Mechanism |
| --- | --- |
| Crop, rotate, mirror | `crop`, `transpose`, `hflip`/`vflip` |
| Speed | mpv `speed` property (keeps A/V in sync) |
| Fade in / out | `fade` (video) + `afade` (audio) |
| Brightness / contrast / saturation | `eq` |
| Grayscale | `hue=s=0` |
| Denoise / sharpen | `hqdn3d` / `unsharp` |
| Text caption | `drawtext` |
| Subtitles | mpv native `sub-file` (not burn-in) |
| Watermark image | lavfi bridge: `movie='logo'[wm];[vid][wm]overlay=...` |
| Volume / mute | mpv `volume` / `mute` properties |

**Not live-previewable (playback still works, shows un-applied + a note):**

| Setting | Why |
| --- | --- |
| Reverse / boomerang | needs the whole clip buffered; cannot stream live |
| Stabilization | inherently 2-pass (vidstab detect → transform) |
| Target size / format / GPU encode | encode-only; no visual difference |

For reverse/boomerang/stabilize a subtle "not shown in preview" label appears
next to that control while in Play mode. All effects still apply on export
unchanged — `build_commands` is **not** modified by this feature.

### Trim integration

- mpv plays the trim range: seek to `trim_in` on play; loop the segment with
  ab-loop (`ab-loop-a = trim_in`, `ab-loop-b = trim_out`) when loop is on.
- mpv `time-pos` is observed/polled (~30 Hz via `self.after`) to drive the
  existing playhead label and scrub bar; dragging the scrub seeks mpv
  (`time-pos`). Trim handles, filmstrip, and playhead stay in sync.
- On reaching `trim_out` without loop, playback pauses and returns to Edit
  mode at `trim_out`.

### Transport UI

A transport row under the preview (near the current scrub row):

- ▶ / ⏸ play-pause
- ⏹ stop (return to Edit mode at trim start)
- ⟳ loop toggle (loop the trim range)
- current / total time readout (reuses the trim duration)
- Keyboard: `Space` = play/pause.

Deferred (not in this feature): speed dropdown in transport, frame-step
buttons. (Speed is already controllable in the Effects tab and is honored.)

## On-demand ffprobe download (and the ffplay detour)

During implementation we briefly considered **ffplay** instead of mpv (it
ships with ffmpeg and applies `-vf`/`-af`). It was rejected: ffplay opens its
own SDL window (no clean tk embedding) and offers no live transport/seek or
live filter updates — it cannot deliver the scrubbable, live-updating embedded
player. **Playback stays on embedded mpv.**

One idea from that detour is kept: **fetch native tooling on demand** rather
than always bundling it. Concretely, add a small **"Download ffprobe"** action:

- `ffprobe` is currently optional — the app falls back to parsing `ffmpeg -i`.
  A button (in an unobtrusive spot, e.g. next to the "no ffprobe" hint or in an
  About/Tools area) downloads `ffprobe.exe` for precise metadata.
- **Source:** the **gyan.dev** GPL Windows build the project already credits,
  **pinned to a known URL and verified by SHA-256** before extracting
  `ffprobe.exe` next to the executable. Never run an unverified binary.
- **Windows only.** On macOS/Linux the button is replaced by an install hint
  (`brew install ffmpeg` / `sudo apt install ffmpeg`), since ffprobe comes from
  the package manager there.
- The download/verify/extract logic is split so the **URL-pinning + checksum
  policy is unit-testable** without performing a real download.
- `libmpv` itself is **bundled** in the Windows build (not downloaded) — it is
  not available from gyan.dev, and bundling keeps playback working out of the
  box.

## Packaging

- **`python-mpv`** added to build/runtime deps (pure-Python ctypes wrapper —
  trivial; pip install for source runs, bundled into PyInstaller builds).
- **Windows:** bundle `libmpv-2.dll` beside the exe via PyInstaller
  `--add-binary`; the portable zip and the Inno installer include it.
  Adds ~40 MB. `python-mpv` locates it next to the executable.
- **Linux:** rely on system `libmpv` (`apt install libmpv2` / `mpv`,
  `dnf install mpv-libs`, …). Documented in the Linux readme; graceful
  fallback if absent.
- **macOS:** attempt libmpv from Homebrew (`brew install mpv`). If embedding
  into the Tk view does not work cleanly, fall back to frame preview —
  consistent with the existing "where it works" stance (drag-and-drop is
  already Windows-only in the builds).

## Testing

- `build_commands` and the export filter logic remain pure and keep their
  current unit tests (unchanged behavior).
- New unit tests for `build_preview_vf(settings)` — pure, no GUI/mpv — assert
  the right filters appear for each live-previewable setting and that
  non-live settings are omitted from the preview graph.
- A guarded structural test that the transport controls and `Player` wrapper
  exist on the shared `app` fixture (no mpv exercised).
- mpv playback itself is **not** exercised in CI (no display/libmpv); CI
  covers the import-guarded fallback path. The existing macOS/Linux release
  workflow continues to build the fallback-capable app.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| libmpv embedding fails on macOS (NSView vs Tk) | optional + graceful fallback; macOS targeted last |
| libmpv build lacks `drawtext`/`overlay` filters | common builds include them; if a filter errors, catch and drop it from the preview graph with a note |
| Windows bundle grows ~40 MB | acceptable; documented; only affects the installer/portable, not the standalone exe path that relies on system mpv |
| mpv API/version differences | pin a known-good `python-mpv`; guard property access |
| Re-applying `vf` on every control change is heavy | debounce; only rebuild when in Play mode |

## Out of scope

- Modifying `build_commands` or export behavior.
- Audio scrubbing / waveform display.
- Frame-accurate stepping and an in-transport speed control (possible later).
- Live preview of reverse, boomerang, and stabilization.
- Bundling libmpv on macOS/Linux (system-provided there).
