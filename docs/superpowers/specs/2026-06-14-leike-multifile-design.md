# Leike Multi-File (Combine + Batch) — Design

**Date:** 2026-06-14
**Status:** Approved design (pending user review of this spec)
**Ships as:** v2.3

## Goal

Add the two remaining roadmap features — **Join/Combine clips** (N clips → 1
file) and **Batch export** (N files → N files, same recipe) — by introducing a
persistent **file-list column** and a **Combine / Batch** mode toggle, while
keeping the existing single-file editing experience exactly as it is today.

## Context

The app (`leike.py`, single file) is built around one `self.input_path` with a
per-file `start_t` / `end_t` / `crop`, a preview canvas, a trim slider, and
embedded mpv playback. The export path is already clean and reusable:

- `ExportSettings` (dataclass) + `build_commands(s)` is **pure**: settings → a
  list of ffmpeg command arg-lists (one or more passes).
- `App._run_export(cmds, dur, out)` runs that *list of passes* sequentially in a
  worker thread with combined progress and Cancel (`_cancelled`, `export_proc`).
- Filter helpers exist and are reused: `_crop_filter`, `_orient_filters`,
  `_adjust_filters`, `_speed_filter`, `_scale_filter`, `_fade_filters`,
  `_drawtext_filter`, `_subtitles_filter`, `_af_chain`, `_linear_video`,
  `_blurpad_dims`, and the blurred-pad `filter_complex` pattern in
  `_video_graph`.

Both new features break the single-`input_path` assumption, which is why the
roadmap (`docs/superpowers/plans/2026-06-13-leike-feature-roadmap.md`, tasks 8.1
and 8.8) flagged them as deserving their own plan. This spec unifies them under
one file-list model so they share UI and most code.

## Decisions (resolved during brainstorming)

1. **Structure:** a persistent file-list column on the far left + a
   **Combine / Batch** toggle at its top. The list is *always present*; in
   single-file use it simply holds one item (no separate code path).
2. **Per-file vs global:** per-file = **trim + crop**. Everything else
   (format, scale, rotate/flip, speed, fades, colour/denoise/sharpen, overlay,
   audio, target-size, GPU) is a **single global recipe**.
3. **Combine canvas:** normalize every clip to the **largest clip's W×H**, fps =
   **highest** among the clips, padding with a **blurred fill** (the existing
   aspect-fill look). The global scale dropdown still caps the final output size.
4. **Batch output:** prompt for **one destination folder** per run; name each
   output `<original>_export.<ext>`; auto-number on collision
   (`<original>_export_2.<ext>`); **never overwrite**.

## Architecture overview

Replace the single active file with a **clip list**. The editor always edits the
*active* clip; switching clips saves the current clip's trim+crop and loads the
next. The global recipe is unchanged and lives in the tabs. Two export modes:

- **Combine** → one new pure builder `build_concat_commands(clips, g)` that
  emits a single `filter_complex` job (normalize each segment, concat, then the
  global recipe on the joined stream).
- **Batch** → loop the **existing** `build_commands(s)` once per clip and run
  each through the existing `_run_export` machinery, in series.

### Data model

```python
@dataclass
class Clip:
    path: str
    src_w: int
    src_h: int
    dur: float
    rotation: int = 0
    fps: float = 30.0
    has_audio: bool = True
    start: float = 0.0          # per-file trim in
    end: float = 0.0            # per-file trim out (set to dur on load)
    crop: tuple | None = None   # (x, y, w, h) source px, per-file
```

App state:
- `self.clips: list[Clip]` — ordered; drives the list column.
- `self.active: int` — index of the clip currently in the editor (or `-1`).
- `self.mode: "combine" | "batch"` — from the toggle (only meaningful with ≥2
  clips; defaults to `combine`).

`probe()` already returns `{w, h, dur, rotation, fps, codec, bitrate,
has_audio}`; adding a clip probes once and fills a `Clip`. The existing
single-file fields (`self.input_path`, `self.src_w/h`, `self.start_t/end_t`,
`self.crop`, `self.playhead`) become **views onto the active clip** — on
`_select_clip(i)` they're loaded from `clips[i]`; on any trim/crop edit and
before switching away they're written back via `_commit_active()`.

`_settings(out)` is unchanged in spirit: it reads the active clip's trim+crop
(already mirrored into `self.start_t/end_t/self.crop`) plus the global widgets.

## UI / layout

```
┌──────────┬──────────────────────┬──────────────┐
│ FILES    │   preview canvas      │   [tabs]      │
│ ◉ Combine│   (active clip)       │  Crop Effects │
│ ○ Batch  │   trim slider         │  Overlay …    │
│ ──────── │   transport           │               │
│ clip1 ✓  │                       │  [footer:     │
│ clip2    │                       │   Export]     │
│ clip3 ✎  │                       │               │
│ + Open   │                       │               │
│ − Remove │                       │               │
│ ↑  ↓     │                       │               │
└──────────┴──────────────────────┴──────────────┘
```

- New grid column 0 (~190px) holds the list; the existing preview column moves
  to col 1 and the tabs to col 2. Window `minsize` grows from `900` to ~`1060`
  wide.
- **Combine / Batch** segmented toggle pinned at the top of the column; disabled
  (greyed) until `len(clips) >= 2`.
- **List:** a `tk.Listbox` (or a frame of row labels) showing basenames; the
  active row is highlighted; a small marker shows clips you've edited
  (`✓` trimmed, `✎` cropped). Reorder via **↑ / ↓** buttons (drag-reorder is a
  nice-to-have, not required for v2.3).
- **Open…** appends multiple files (`askopenfilenames`); **drag-drop** of one or
  more files onto the column or canvas appends them; **− Remove** drops the
  selected clip (and re-points `active`).
- Selecting a row → `_select_clip(i)`: commit the current clip, load clip *i*
  into the editor (preview re-extract, crop box redraw, trim slider reset to its
  range, playback reset).
- The footer **Export** button label/behavior reflects the mode: single file →
  "Export video" (today); 2+ clips Combine → "Combine & export"; Batch →
  "Export N files".

## Combine pipeline — `build_concat_commands(clips, g)`

`clips` is the ordered `list[Clip]`; `g` is the global `ExportSettings` (its
`input_path`/`crop`/`start`/`end`/`src_w`/`src_h` are ignored — per-clip values
come from `clips`). Returns `list[list[str]]` (a single pass for the common case;
GIF/size-target combine are out of scope for v2.3 — Combine targets mp4/webm).

**Target canvas:** `W = max(out_w_i)`, `H = max(out_h_i)` where `out_w/h_i` is
clip *i*'s size *after its own crop* (even-rounded); `F = max(fps_i)`. Apply the
global `scale_cap` to `(W, H)` if set (longest side cap), so the final size is
capped exactly like single-file export.

**Per-segment filter** (blurred fill to the target canvas):

```
[i:v] crop=cw:ch:cx:cy ,                      # only if clip i has a crop
      split=2 [bg_i][fg_i];
[bg_i] scale=W:H:force_original_aspect_ratio=increase,
       crop=W:H, gblur=sigma=20 [bgb_i];
[fg_i] scale=W:H:force_original_aspect_ratio=decrease [fgs_i];
[bgb_i][fgs_i] overlay=(W-w)/2:(H-h)/2,
       setsar=1, fps=F, format=yuv420p [v_i];
[i:a] aresample=async=1:first_pts=0 [a_i]      # real audio, OR:
# (no audio) anullsrc=channel_layout=stereo:sample_rate=48000 [a_i]
```

**Join + global recipe:**

```
[v_0][a_0][v_1][a_1]…[v_{N-1}][a_{N-1}] concat=n=N:v=1:a=1 [vc][ac];
[vc] <global video chain> [v];      # orient, adjust, speed, fades(total dur),
                                    #   overlay/text/subs — reuse helpers
[ac] <global audio chain> [a]       # _af_chain (volume/atempo); or drop if mute
```

- **Inputs:** for each clip, `-ss start -t (end-start) -i path` (input-seek trim,
  like the single-file path).
- **Global video chain** on `[vc]`: `_orient_filters(g)`, `_adjust_filters(g)`,
  `_speed_filter(g)`, `_fade_filters` computed over the **total** output duration
  `Σ (end_i-start_i) / speed`, then `_drawtext_filter(g)` / `_subtitles_filter(g)`.
  (Crop is always per-file — it was already applied per segment above; the Crop
  tab stays enabled in every mode and edits the active clip's crop.)
- **Audio:** if `g.mute`, drop `[ac]` and `-an`; else `_af_chain(g)` on `[ac]`.
  Mixed audio/no-audio clips stay in sync because audio-less clips get
  `anullsrc` of their trimmed duration.
- **Map + encode:** `-map "[v]" -map "[a]"` (or `-an`) then the existing encoder
  selection: mp4 → `_venc(g)` + `aac`; webm → `libvpx-vp9` + `libopus`. Reuse
  `_av_reencode`-style tails where practical; concat needs explicit `-map`, so a
  small dedicated tail is acceptable.
- Combine is always a **re-encode** (no stream-copy / fast-trim).

The single-pass `filter_complex` string is built by a pure helper so it is
unit-testable without ffmpeg.

## Batch pipeline

For each clip *i*:
1. Build `s_i = _settings_for_clip(clips[i], out_i)` — the clip's trim+crop
   merged with the global recipe (same construction as `_settings`, but sourced
   from a `Clip` instead of the live widgets for trim/crop).
2. `cmds_i = build_commands(s_i)` (the **existing** builder — gets fast-trim,
   GIF, webm, size-target, stabilize, overlays, audio, all for free).
3. Run `cmds_i` through `_run_export`-style execution.

- **Output naming:** `_batch_out_name(folder, src_path, ext, taken)` →
  `<original>_export<ext>`, bumping `_export_2`, `_export_3`, … against names
  already used this run / already on disk. Pure + unit-tested.
- **Destination:** one `askdirectory()` prompt before the run.
- **Progress:** overall = `(i + within_i) / N`; status text "Exporting file
  i/N: name".
- **Errors:** a failing file is recorded and the run **continues**; on completion
  show "Exported M of N (K failed)" with the failed names. Cancel stops cleanly
  between and within files (reuse `_cancelled` + `export_proc`).

## Builder / settings changes (summary)

- **New:** `Clip` dataclass; `build_concat_commands(clips, g)` and its pure
  filter-graph helper; `_batch_out_name(...)`; `_settings_for_clip(clip, out)`.
- **New combine geometry helper:** `_combine_target(clips, scale_cap)` →
  `(W, H, F)` (max-of-cropped-sizes, capped; max fps). Pure + unit-tested.
- **Reused unchanged:** `build_commands`, all `_*_filter(s)` helpers,
  `_run_export`, `_export_done`, `probe`.
- **App changes:** clip-list column widgets; `self.clips/active/mode`;
  `_add_clips(paths)`, `_remove_clip()`, `_move_clip(delta)`, `_select_clip(i)`,
  `_commit_active()`, `_set_mode(m)`, `_update_export_button()`; `export()`
  branches on `len(clips)` + mode into the existing single-file path, a new
  combine path, or a new batch path; multi-file `on_drop` / `open_file` append.

## Error handling

- A file that fails to probe on add is rejected with a status message and **not**
  added (the rest of a multi-drop still add).
- Combine validates ≥2 clips and that every clip still exists on disk before
  building; one atomic output (partial file removed on failure/cancel, as today).
- Batch is resilient: per-file failures don't abort the queue; a final summary
  reports successes/failures.
- The Combine/Batch toggle and per-mode Export label prevent ambiguous actions
  (e.g. you can't "combine" a single clip — the toggle is disabled).

## Testing (pytest, pure layer only)

- `build_concat_commands`:
  - N inputs each with `-ss/-t`; `concat=n=N:v=1:a=1` present.
  - Per-segment crop appears only for clips that have a crop.
  - Blurred-pad (`gblur`, `overlay`, `setsar=1`, `fps=F`, target `W:H`) per
    segment; target = max cropped size, capped by `scale_cap`.
  - Audio-less clip → `anullsrc`; `g.mute` → `-an` and no `[ac]` map.
  - Global chain (e.g. `eq=`, `transpose=`) applied **after** concat, once.
- `_combine_target`: max-of-cropped-dims and max-fps, scale-cap applied.
- `_batch_out_name`: suffix + collision numbering against a "taken" set.
- `_settings_for_clip`: produces an `ExportSettings` with the clip's trim+crop
  and the global recipe.
- A `Clip` save/load round-trip (pure dict) for the select-to-edit flow.

UI, real encodes, drag-drop, and playback are verified by **building and
running** (the project's existing convention).

## Build phases (one feature; ship as v2.3)

- **Phase A — Foundation (shippable):** file-list column, multi-open + drag
  append, `Clip` model, `_select_clip` / `_commit_active`, the Combine/Batch
  toggle (inert until ≥2 clips). Single-file editing behaves exactly as today.
- **Phase B — Batch:** `_settings_for_clip`, `_batch_out_name`, the batch run
  loop over `build_commands`, folder prompt, series progress, resilient errors +
  summary.
- **Phase C — Combine:** `_combine_target`, `build_concat_commands` (+ pure
  graph helper), the combine export path, blurred-fill normalization, audio
  silent-fill. Then bump version, build, and release **v2.3**.

Each phase ends in a working, testable state.

## Risks

- **State refactor:** routing the existing single-file fields through "active
  clip" touches `load_path`, `_settings`, trim commit, crop, preview, and
  playback. Mitigation: keep the single-clip list as the *only* path so existing
  behavior is exercised continuously; land Phase A before any export work.
- **Concat filter correctness:** mixed fps/SAR/audio is the classic failure
  mode. Mitigation: explicit `setsar=1` + `fps=F` + `anullsrc` per segment, and
  unit tests on the generated graph string.
- **Window width:** the third column needs more horizontal room; bump `minsize`
  and verify the layout on a small screen.
