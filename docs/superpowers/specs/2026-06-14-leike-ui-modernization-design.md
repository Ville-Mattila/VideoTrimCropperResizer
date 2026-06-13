# Leike UI Modernization — Design Spec

**Date:** 2026-06-14
**Status:** Approved (brainstorming) — pending implementation plan

## Goal

Make Leike's interface feel modern and polished by (1) reorganizing the
controls from one long scrolling column into a **tabbed** layout, and
(2) applying consistent, brand-aligned styling — all within tkinter/ttk's
constraints. No feature behavior changes.

## Current state (what we're changing)

`leike.py` builds a single window: a left preview column and a right controls
column. The right column is a **scrollable frame** holding stacked
`ttk.LabelFrame` panels — Crop, Trim, Export — plus a **"More options ▸"**
expander that reveals Encoding, Audio, Transform, Adjust, and Overlay panels.
The result is a tall, scroll-heavy column. The theme is a hand-rolled warm-dark
+ gold `clam` theme (`_apply_theme`).

Everything below the widget layer — `ExportSettings`, `build_commands`, the
filter graph, the export runner, the 42 unit tests — stays **untouched**. This
is a layout + styling refactor only.

## Layout

```
┌───────────────────────────────────────────────────────────────┐
│  HEADER:  [logo] Leike   [Open…]            file.mp4 · WxH · 0:42│
├───────────────────────────────┬───────────────────────────────┤
│ LEFT (grows)                  │ RIGHT (fixed ~340px)          │
│   preview canvas (fills)      │  ┌─ tabs ─────────────────┐    │
│   scrubber                    │  │ Crop Effects Overlay … │    │
│   filmstrip                   │  ├────────────────────────┤    │
│   Trim: [start][end] Set/Set  │  │  active tab content     │    │
│   [Grab frame]                │  │                         │    │
│                               │  └────────────────────────┘    │
│                               │  ── persistent footer ──       │
│                               │  [ ⬇ Export video ] [Cancel]   │
│                               │  progress ▓▓▓▒▒  · hint         │
└───────────────────────────────┴───────────────────────────────┘
```

### Header bar
- One continuous dark surface (matches the DWM dark title bar) spanning the
  window width.
- Left: gold logo square (16px), bold "Leike", an **Open…** button.
- Right: the loaded file's name · dimensions · duration (the old `file_label`).
- Drag-and-drop still works on the whole window.

### Left column (preview)
- Preview canvas (expands to fill, letterboxed — unchanged behavior).
- Scrub slider, filmstrip canvas, click-to-seek — unchanged.
- **Trim** moves here (under the scrubber, where it belongs): Start/End entry
  fields, Set-start / Set-end buttons, duration label.
- **Grab frame** button.

### Right column (notebook + footer)
- A `ttk.Notebook` with five tabs. Tab frames replace the old LabelFrames.
- A **persistent footer** below the notebook (NOT inside a tab): the primary
  **Export** button, **Cancel**, the progress bar, and the live export hint.
  The Export button is enabled once a file is loaded and works from any tab.

### Tab contents
| Tab | Holds (existing controls, re-homed) |
|---|---|
| **Crop** | aspect-ratio preset, Crop-to-fit vs Blurred-fill, crop readout, Reset |
| **Effects** | Transform group (rotate/flip, speed, fade, effect, loop) + Adjust group (brightness/contrast/saturation, grayscale, denoise, sharpen, stabilize) |
| **Overlay** | text caption + position, watermark + corner, subtitles |
| **Audio** | mute, volume, export-audio-only (MP3) |
| **Export** | format, downscale, quality (CRF) / target size, fast-trim toggle, GPU toggle |

Note: downscale is a sizing/output concern, so it lives only in the **Export**
tab (one `scale_var`, one widget) — not duplicated under Crop.

## Styling (clam theme, refined)

Keep the warm-dark + gold palette, formalized as named tokens already in the
file (`GOLD`, `GOLD_DEEP`, `BASE_BG`, `PANEL_BG`, `PANEL_HI`, `BORDER`, `TEXT`,
`MUTED`). Refinements:

- **Notebook tabs:** flat, `PANEL_BG` background; active tab gets a gold bottom
  border / gold text; inactive tabs `MUTED` text. Style `TNotebook` and
  `TNotebook.Tab` in `_apply_theme`.
- **Primary vs secondary buttons:** a new `Accent.TButton` style (gold fill,
  dark text) for **Export**; existing neutral `TButton` for everything else.
- **Section labels:** small uppercase `MUTED` labels above control groups for
  rhythm (a reusable helper or a `Section.TLabel` style).
- **Header:** a `tk.Frame`/`ttk.Frame` with `BASE_BG`, separated from the body
  by a 1px `BORDER` line.
- **Spacing:** consistent `padding`/`pady` rhythm (e.g., 10px panel padding,
  6px between rows) applied uniformly.
- Gold focus rings and gold slider/progress (already present) carry over.

### Honest constraints (tkinter/clam)
- No rounded corners, drop shadows, or gradients. The delivered UI is **flat** —
  the approved mockup minus the rounding and glow. We compensate with spacing,
  typography hierarchy, and the gold accent.
- `ttk.Notebook` is the tab widget; its tabs are styleable but not pixel-perfect
  to the mockup.

## Code approach

- Rewrite `_build_ui`: build the header, the left preview column (now including
  trim + grab), and the right notebook + footer.
- Convert each `_build_*_panel(parent)` to grid into a **notebook tab frame**
  instead of the scrollable advanced column. Merge Transform + Adjust panels
  into one **Effects** tab; Encoding + format/quality into the **Export** tab.
- Delete the `_scrollable` helper, the `More options` toggle (`_toggle_adv`,
  `adv_btn`, `advanced`), and the standalone scroll column.
- Extend `_apply_theme` with `TNotebook`, `TNotebook.Tab`, and `Accent.TButton`
  styles.
- All `*_var` widget variables and their `_settings()` reads stay the same —
  only their parent containers change. `build_commands` and tests are unaffected.

## Non-goals
- No new export features (concat/batch remain deferred on the roadmap).
- No change to the filter/command logic or output behavior.
- No switch away from tkinter (no web UI, no sv-ttk return, no extra deps).

## Success criteria
- The window opens with a header, a tabbed right panel, trim under the preview,
  and a persistent Export footer.
- Every existing control is reachable and functional in its new home.
- All 42 unit tests still pass; a real export still produces identical output.
- The app builds (PyInstaller) and runs; visual check confirms the tabbed,
  polished look.
