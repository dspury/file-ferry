# File-Ferry Brand Style Guide

Branch: `branding/file-ferry-assets` · Masters live in `assets/brand/`.

## 1. Asset inventory

| File | Size | Dimensions | Use |
|---|---|---|---|
| `assets/brand/file-ferry-logo-gen.png` | 2048 × 2048 | Full lockup: mark + `FILE-FERRY` wordmark on ink field | Hero, README, marketing, about screens |
| `assets/brand/file-ferry-icon-gen.png` | 2048 × 2048 | Mark on navy squircle, shown on a light-grey surround | Source presentation only — see §5 |
| `assets/brand/file-ferry-icon-macOS-v1.png` | 1024 × 1024 | Mark in macOS squircle, transparent corners | macOS app icon candidate |
| `assets/brand/file-ferry-icon.ai` | Illustrator master (PDF-1.6 compatible) | Vector source of the mark | Canonical source for all exports and exact color values |
| `assets/brand/ferry-logo-black.svg` | Vector, viewBox `1033 × 498` (2.9 KB) | Mono black mark, no wordmark, unstyled paths | Single-color use: light backgrounds, favicons, print, engraving; recolor via `fill` |

Excluded: `media-mate-old/` (superseded explorations, intentionally not imported).

## 2. The mark

A starboard-bow ferry in motion, built from three ideas:

- **Hull** — white-to-pale-blue gradient, pointing right (forward = progress, delivery).
- **Wake** — three steel-blue speed lines trailing to port (throughput, offload speed).
- **Cargo** — three ascending rounded bars in steel blue plus one white
  file/document shape with a dark slot (media files, rising volume, ingest).

**Wordmark** — uppercase geometric sans, wide letter-spacing:
`FILE-` in bone off-white, `FERRY` in light steel blue.

## 3. Palette

Measured from `file-ferry-icon-macOS-v1.png` (1024x1024, RGBA) by
area-weighted k-means over every opaque pixel, cross-checked against
`file-ferry-logo-gen.png`. Neither PNG carries an ICC profile, so the values
are sRGB as written.

The `.ai` master is **not** a usable source for this: it stores only
`AIPrivateData` with no PDF vector content and no image XObjects, and its
swatch panel holds Illustrator's 57 default swatches, not the artwork's
colours. The raster master is the authoritative machine-readable source.

The artwork is gradient throughout — there are no flat regions, so each value
below is the area-weighted mean of its cluster, not a sampled pixel.

| Token | Hex | Role | On `ink` |
|---|---|---|---|
| `ink` | `#0F1622` | app background | — |
| `ink-raise` | `#1C283B` | raised surface | 1.22:1 |
| `bone` | `#F6F5F2` | wordmark, brand marks | 16.63:1 |
| `body` | `#EDEBE6` | product body text | 15.22:1 |
| `ferry` | `#75A1C6` | lead accent | 6.62:1 |
| `mist` | `#DCE5EA` | highlights, dividers | 14.19:1 |
| `steel` | `#36465D` | **decoration only** — see below | 1.89:1 |

`bone` and `body` are both measured: `bone` is the icon master's value, used
for the wordmark; `body` is the logo master's slightly softer value, which is
the better choice for long-form product text on a dark field.

### `steel` is decoration only

At **1.89:1 on `ink`** it fails every WCAG level. It is the cargo-bar / hull
colour and reads as form, not information. Never use it for text, for a control
boundary that carries meaning, or for a focus ring. Its one legitimate product
role is `--c-border-strong`, where it is a visible edge rather than a
conveyed value.

### Where the earlier estimates were off

The first pass of this guide eyeballed these from downscaled 4-bit BMPs. That
held up better than expected — `ferry` was within 5/255 per channel and `steel`
within 3. Two were further out and are corrected above: `ink-raise` was off by
21 (it is markedly bluer and lighter than estimated) and `bone` by 15.

One correction that matters to a decision rather than a value: ferry blue on
`ink` is **6.62:1**, which is *parity* with the outgoing orange on coal
(6.62:1), not an improvement. Contrast is not an argument for the migration.
It is also not an argument against it.

## 3a. Product token mapping

Derived from the palette above and calibrated against the separations the
current design already ships, so the migration changes hue, not legibility.

| Product token | Value | Ratio | Current equivalent |
|---|---|---|---|
| `--c-rail` | `#0A0E16` | 1.07:1 recessed | `#0d0a08` |
| `--c-bg` | `#0F1622` | — | `#14100e` |
| `--c-surface` | `#151E2D` | 1.08:1 | `#1b1714` (1.06) |
| `--c-surface-2` | `#1C283B` | 1.22:1 | `#231e1a` (1.14) |
| `--c-surface-3` | `#223046` | 1.36:1 | `#2b2420` (1.25) |
| `--c-border` | `#243042` | 1.36:1 | `#322b25` (1.36) |
| `--c-border-strong` | `#36465D` | 1.89:1 | `#443b32` |
| `--c-text` | `#EDEBE6` | 15.22:1 | `#efe7d8` |
| `--c-text-dim` | `#A6A7A7` | 7.52:1 | `#9e9384` (6.27) |
| `--c-text-faint` | `#898B8E` | 5.31:1 | `#8f8576` (5.21) |
| `--c-accent` | `#75A1C6` | 6.62:1 | `#ff6a2c` (6.62) |
| `--c-accent-hover` | `#99B9D3` | 8.84:1 | — |
| `--c-accent-soft` | `#1D2939` | 1.23:1 fill | — |
| `--c-on-accent` | `#0F1622` | 6.62:1 on ferry | — |

Every text tier clears WCAG AA, and the surface ramp is slightly *more*
separated than the one the app ships today.

### Functional colours survive unchanged

The brand artwork defines no success/warn/danger, and the existing ramps do not
need to move — checked against the new background:

| | on new `ink` | on old coal | verdict |
|---|---|---|---|
| `--c-ok` `#35a96c` | 6.08:1 | 6.34:1 | AA text |
| `--c-warn` `#e7b923` | 9.81:1 | 10.23:1 | AA text |
| `--c-danger` `#f0495a` | 5.01:1 | 5.23:1 | AA text |

Keep them as they are.

## 4. Typography

- **Brand voice** — the existing lines stand: `INGEST · ORGANIZE · PROXY ·
  RESOLVE · VERIFY` and “Zero-cost post-production media ops · every step
  audited” (`src/file_ferry/tui.py:76-77`).
- **Wordmark style** — uppercase, geometric/grotesque sans, generous
  tracking. The in-repo match is **Archivo** (the desktop shell already
  ships `@fontsource-variable/archivo`): use Archivo SemiBold/Bold with
  wide letter-spacing for brand headings.
- **Data/code** — keep **IBM Plex Mono** (already in the desktop shell).

## 5. Usage rules

- Dark-first: the full-color lockup is designed for ink backgrounds. On
  light backgrounds use the mono `ferry-logo-black.svg` mark (or a white
  export from the `.ai`).
- The SVG paths carry no fill attributes, so it recolors cleanly with a
  single CSS `fill` — that is its purpose; do not bake new colors into copies.
- `file-ferry-icon-gen.png` has a **baked light-grey surround** — do not
  use it directly in-app. Crop it or, preferably, export a clean squircle
  from the `.ai` master.
- `file-ferry-icon-macOS-v1.png` (transparent corners) is the current
  candidate for mac packaging (`desktop/build/` is `buildResources` per
  `desktop/build/electron-builder.yml:5-7`; wiring the icon in is
  follow-up work, not done on this branch).
- Clear space: at least the cap-height of the wordmark's `F` on all sides.
  Minimum width: 160 px digital for the full lockup, 32 px for the solo mark.
- Don'ts: no recoloring, no rotation/skew, no drop shadows, no busy or
  photographic backgrounds, no pairing with the legacy orange accent.

## 6. Open decision: migrating the product theme

> **Values are settled** (§3, §3a) — a full product token mapping exists,
> contrast-checked and calibrated against the current design. What remains is
> purely the directional call below: whether to migrate at all, and what
> happens to the TUI theme.

The new brand diverges from the current in-app themes — this branch changes
**no code**, but the next step needs a call:

- TUI `ferry-studio` theme (`src/file_ferry/tui.py:51-63`) leads with
  orange primary `#ff7a45`, violet `#a970ff`, cyan `#35c5f0`.
- Desktop renderer (`desktop/renderer/src/styles.css:26-140`) leads with
  orange accent `#ff6a2c` on coal `#14100e` with bone text `#efe7d8`.
- The brand artwork contains **no orange**; its lead accent is ferry blue
  on ink navy.

Proposed direction: migrate primary/accent tokens to the `ferry`/`steel`
family on `ink`, keep bone text and the existing ok/warn/danger ramps.
See §7 — the TUI is rebranded too, not left on the old theme.

## 7. The TUI

The terminal UI is rebranded with the rest of the product, not left behind as a
legacy surface. It cannot show the raster masters, so it carries the brand
through palette and wordmark instead.

### Theme

`MM_THEME` in `src/file_ferry/tui.py:51-63`. Its background `#0d0f14` is
already close to brand `ink`, so this is mostly an accent migration rather than
a reskin.

| Textual slot | From | To | On ink |
|---|---|---|---|
| `background` | `#0d0f14` | `#0F1622` (ink) | — |
| `surface` | `#171922` | `#151E2D` | 1.08:1 |
| `panel` | `#20232f` | `#1C283B` | 1.22:1 |
| `primary` | `#ff7a45` | `#75A1C6` (ferry) | 6.62:1 |
| `secondary` | `#a970ff` | `#5F87A8` | 4.76:1 |
| `accent` | `#35c5f0` | `#A3C0D7` | 9.57:1 |
| `success` | `#52d273` | `#35a96c` | 6.08:1 |
| `warning` | `#ffc857` | `#e7b923` | 9.81:1 |
| `error` | `#ff5c5c` | `#f0495a` | 5.01:1 |

Every slot clears WCAG AA on ink. `secondary` is `steel` lifted toward `mist`
until it cleared 4.5:1 — raw `steel` is 1.89:1 and must not be used for
anything a terminal renders as text.

The functional three are moved to the **desktop's** values rather than keeping
the TUI's own. They are the same three states, and two surfaces disagreeing
about what "warning" looks like is the cross-surface divergence this codebase
keeps getting bitten by.

### Wordmark

`ASCII_LOGO` (`src/file_ferry/tui.py:67-74`) stays figlet — a terminal cannot
render the mark — but it stops being monochrome. §2 specifies `FILE-` in bone
and `FERRY` in light steel blue; a terminal can do exactly that with two
colours, so the ASCII wordmark should carry the same split rather than
rendering flat.

The figlet currently reads `ferry`. It should read `file-ferry` to match the
wordmark, regenerated the same way the existing comment documents:

    python -c "import pyfiglet; print(pyfiglet.figlet_format('file-ferry', font='slant'))"

Check the result fits a standard 80-column terminal and degrades sanely at
narrower widths before adopting it.

`STRAP` and `TAGLINE` are unchanged — §4 keeps them as brand voice.

### Fold in #124 while here

The theme constant is still called `MM_THEME`, a leftover from the pre-rename
name (issue #124). Renaming it to `FERRY_THEME` belongs in this change; the
theme's own `name="ferry-studio"` is already correct.

### Acceptance

- No orange or violet remains in the TUI theme
- Every slot clears AA on the new background
- Functional colours match the desktop's, not a second set
- The ASCII wordmark renders `FILE-` and `FERRY` in the two brand colours
- It fits 80 columns and degrades sanely below that
- `MM_THEME` renamed; no `MM_` prefixes left in `tui.py`
