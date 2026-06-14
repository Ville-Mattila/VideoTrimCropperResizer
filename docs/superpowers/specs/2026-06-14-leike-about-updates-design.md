# Leike — About dialog + Check for updates — Design

**Date:** 2026-06-14
**Status:** Approved design (pending user review of this spec)
**Ships as:** v2.5

## Goal

Give Leike a themed **About** dialog — reachable from a header button — that shows
the app version, links, ffmpeg version, and license info, with a manual **Check
for updates** button that compares the running version against the latest GitHub
release.

## Context

`leike.py` (single file) currently has **no app version constant** — the version
lives only in `installer/Leike.iss` (`MyAppVersion`). The app already uses
`urllib.request` for HTTP (the on-demand libmpv download) and ships license files
(`LICENSE`, `THIRD_PARTY_NOTICES.md`, `licenses/ffmpeg-GPLv3.txt`), which the
installer stages next to the exe as `LICENSE.txt` / `THIRD_PARTY_NOTICES.txt`. The
header (`_build_ui`) is a custom `ttk.Frame` with an **Open…** button (west) and a
file-info label (east). The whole chrome is custom warm-dark themed with a DWM
dark titlebar (`_apply_dark_titlebar`); native menus would render OS-grey and
clash, so About is a **themed dialog**, not a menu bar.

## Decisions (resolved during brainstorming)

1. **Surfacing:** a themed **"About"** button at the top-right of the header opens
   a modal `Toplevel` dialog. No native menu bar.
2. **Update check:** **manual only** — no auto-check, no network until the user
   clicks the button.
3. **Licenses:** a one-line summary + a **"View licenses"** button that opens the
   bundled `LICENSE` / `THIRD_PARTY_NOTICES` in the OS default viewer.
4. **Website link:** the landing page, `https://ville-mattila.github.io/Leike/`.

## Architecture

### New constants

```python
APP_VERSION = "2.5"          # keep in sync with installer/Leike.iss MyAppVersion
GITHUB_REPO = "Ville-Mattila/Leike"
SITE_URL = "https://ville-mattila.github.io/Leike/"
REPO_URL = f"https://github.com/{GITHUB_REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
```

`APP_VERSION` is the single source for what the app reports; it is bumped together
with the installer version at release time (added to the release recipe).

### Pure helpers (unit-tested)

```python
def _parse_version(s):
    """'v2.4.1' / '2.5' -> (2, 4, 1) / (2, 5). Empty tuple on garbage."""
    s = (s or "").strip().lstrip("vV")
    parts = []
    for p in s.split("."):
        m = re.match(r"\d+", p)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts)

def _is_newer(latest, current):
    """True if version string `latest` is strictly newer than `current`."""
    a, b = _parse_version(latest), _parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b

def _latest_tag_from_json(data):
    """Extract tag_name from a parsed /releases/latest response, or None."""
    if isinstance(data, dict):
        tag = data.get("tag_name")
        return tag if isinstance(tag, str) and tag else None
    return None
```

### Network fetch (thin, run-verified)

```python
def fetch_latest_tag(url=LATEST_API, timeout=8):
    """Return the latest release tag (e.g. 'v2.5') or None on any error."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Leike"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _latest_tag_from_json(json.loads(r.read().decode("utf-8")))
    except Exception:
        return None
```

(GitHub's `/releases/latest` already excludes drafts/pre-releases, so the tag is
the right comparison target. The `User-Agent` header is required by the API.)

### App methods (run-verified)

- **Header button:** add an `"About"` `ttk.Button` to the header (new column on
  the right of the file label) → `command=self._show_about`.
- **`_show_about()`** builds a modal `Toplevel`:
  - Themed `bg=BASE_BG`; apply the dark titlebar (factor `_apply_dark_titlebar`
    to accept any window so the dialog gets it too); `transient(self)` +
    `grab_set()`; centered over the main window; Esc / Close to dismiss.
  - **Header row:** the **"Leike"** wordmark as styled text (large gold/cream
    font — tk `PhotoImage` can't load the `.ico`/`.svg`, so no raster logo) +
    `APP_VERSION`, then the tagline. The Toplevel still gets `leike.ico` as its
    window/titlebar icon via `iconbitmap`.
  - **Links row:** "GitHub" → `REPO_URL`, "Website" → `SITE_URL` (open via
    `webbrowser.open`).
  - **ffmpeg line:** first line of `ffmpeg -version` (via `run_capture`), or
    "ffmpeg not found" — fetched once when the dialog opens.
  - **License row:** "Leike is MIT-licensed; bundled ffmpeg is GPLv3." +
    a **"View licenses"** button → `self._open_licenses()`.
  - **Update row:** a **"Check for updates"** button → `self._check_updates()`,
    and a result `ttk.Label` (the `update_status`).
  - **Close** button.
- **`_check_updates()`**: disable the button, set status "Checking…", spawn a
  daemon thread that calls `fetch_latest_tag()`, then `after(0, ...)` to:
  - tag is None → "Couldn't check for updates (no connection?)";
  - `_is_newer(tag, APP_VERSION)` → "Update available: {tag}" + reveal a
    **Download** link/button → `webbrowser.open(RELEASES_URL)`;
  - else → "You're on the latest version (v{APP_VERSION})".
  Re-enable the button afterward.
- **`_open_licenses()`**: find the bundled `LICENSE.txt`/`LICENSE` and
  `THIRD_PARTY_NOTICES.txt`/`.md` (next to the exe when frozen, else repo root),
  open each existing one with the OS default app
  (`os.startfile` on Windows; `open` on macOS; `xdg-open` on Linux). If none are
  found locally, `webbrowser.open(f"{REPO_URL}/blob/main/LICENSE")`.

### Files touched

`leike.py` only (single-file app): the constants, the three pure helpers,
`fetch_latest_tag`, the header button, and the `_show_about` / `_check_updates` /
`_open_licenses` methods. Plus `installer/Leike.iss` (version) and the release
recipe at ship time.

## Error handling

- All network failures (offline, timeout, 403 rate-limit, malformed JSON) funnel
  through `fetch_latest_tag` returning `None` → a single friendly "Couldn't check"
  message. No tracebacks reach the user.
- `_open_licenses` degrades to opening the GitHub LICENSE in the browser if the
  local files aren't present.
- The dialog is modal (`grab_set`) and cleans up its grab on close; a second
  click on About while it's open just refocuses (guard with a stored handle).

## Testing (pytest, pure layer)

- `_parse_version`: `"v2.4.1"→(2,4,1)`, `"2.5"→(2,5)`, `"v3"→(3,)`, `""→()`,
  `"garbage"→()`.
- `_is_newer`: `("v2.5","2.4.1")→True`, `("2.4.1","2.4.1")→False`,
  `("2.4","2.4.1")→False`, `("v2.10","v2.9")→True` (numeric, not lexical),
  `("2.5","2.5.0")→False`.
- `_latest_tag_from_json`: `{"tag_name":"v2.5"}→"v2.5"`, `{}→None`,
  `{"tag_name":""}→None`, `[]→None`.
- The dialog, the live network fetch, and license-file opening are
  **run-verified** (build + run; a real `fetch_latest_tag()` against the live API
  returns the current tag).

## Out of scope (v2.5)

- Auto-update / in-app download+install of new versions (just links to the
  releases page).
- Auto-check on startup or background polling.
- A native menu bar.
- Showing license texts inside the app (opens the bundled files instead).
