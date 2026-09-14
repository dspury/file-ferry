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

> Sampled from the raster masters (4-bit quantization of downscaled BMP
> conversions). Approximate — confirm exact values against
> `file-ferry-icon.ai` before hard-coding tokens.

| Token | Approx. hex | Role |
|---|---|---|
| `ink` | `#0E1219` | Primary field / app background |
| `ink-raise` | `#171C26` | Surfaces, cards, panels on ink |
| `bone` | `#F0ECE3` | Primary text, `FILE-` half of wordmark |
| `ferry` | `#7AA6C8` | Lead accent, `FERRY` half, wake lines |
| `steel` | `#33475E` | Secondary elements, cargo bars (dark end) |
| `mist` | `#D4DEE7` | Hull highlight, dividers on ink |

Functional colors (success/warn/danger) are not defined by the brand
artwork — keep the existing ramps until §6 is decided.

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
TUI `ASCII_LOGO` (`src/file_ferry/tui.py:67-74`) stays as the terminal
fallback; graphical surfaces use the new masters.
