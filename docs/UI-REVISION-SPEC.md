# UI revision spec

Living document. The operator adds items as they find them; each gets an
`R-` number, a verdict, and acceptance criteria. Items are implemented in
whatever order suits, unless one says otherwise.

**Status key:** `OPEN` — specified, not started · `IN PROGRESS` ·
`DONE` — merged · `WONTFIX` — considered and declined, with the reason.

**Baseline:** `main` @ `bd0e77f`, after #165.

---

## Standing rules

Rules outlive the item that produced them. A new component that breaks one
of these is wrong even if no `R-` item mentions it.

### SR-1 — No left-edge colour bars

> "The little braces being used are terrible. I've never liked those and
> don't want to see any version of them in the app. If we need to identify
> something with a colour, use the outline or the highlight of primary text
> as the indicator — never those brace things."
> — operator, 2026-09-14

A single coloured edge is never the state indicator. Use, in order of
preference:

1. **The primary text** in the state colour (`.stat__value`, a label)
2. **The full outline** — `border-color` on all four sides
3. **A tinted background** (`--c-*-soft`)

The reference for the look that *is* wanted: the stage-rail cell
(`.step`) — a uniform bordered chip.

**Structural dividers are not braces** and are exempt: a 1px rule
separating two controls, or marking a boundary, carries no state. Exempt
today: `.step--gate`, `.pathpick .btn`.

### SR-2 — Token values are frozen

`#162` pins all 33 `--c-*` values, the `rem` type scale, and the absence
of legacy orange. Changing a value fails those tests, and that is the
guard working as intended.

Fair game: layout, spacing, borders, and **which** token a rule reaches
for.

### SR-3 — Contrast floors

- `--c-text-faint` `#919497` is 4.86:1 on `--c-surface-2`. Moving text to
  a lighter surface means re-checking it.
- `steel` `#36465D` is 1.89:1 — decoration only. Never text, never a
  meaningful boundary, never a focus ring.
- Check a foreground token against the surface it renders on, not against
  `ink`. (This one has already caused a defect.)

### SR-4 — Verify by running

CI sets `ELECTRON_SKIP_BINARY_DOWNLOAD` and never loads Electron. A green
desktop job says nothing about how anything looks. Boot the app, and for
layout work resize it.

---

## R-1 — Remove the left-edge colour bars · OPEN

Applies SR-1 to what exists today. 19 declarations across 5 selectors;
all are accounted for below.

### In scope — remove

| Selector | Lines | What goes |
| --- | --- | --- |
| `.stat` | 724–743 | 3px bar, `--c-border-strong` at rest, recoloured by `--active/ok/warn/danger/cancelled/attention` |
| `.banner` | 1490–1552 | 3px bar plus `border-left-color` on all five modifiers |
| `.nav__item` | 455, 470, 482 | 2px transparent base, hover `--c-border-indicator`, active `--c-accent` |

**`.stat`** — give it a uniform border, like a stage-rail cell. The state
signal already exists: `.stat--X .stat__value` colours the value text.
That is SR-1's preferred indicator; keep it. If a state must read harder,
colour the whole outline.

**`.banner`** — pure deletion. Every `.banner--X` already sets
`border-color` (full outline), a tinted `background`, *and* `color`. The
bar is a fourth cue on top of three. Nothing is lost.

**`.nav__item`** — operator's call was "no exceptions". Two cautions:

- `border-left: 2px solid transparent` is load-bearing for alignment.
  Removing it shifts every item 2px left; compensate with padding so the
  icons hold their x-position.
- Hover keeps `background: var(--c-surface-2)` and `color: var(--c-text)`.
  Active keeps the gradient plate, `font-weight: 600`, and the
  accent-coloured icon. Neither loses meaning.
- Drop `border-color` from the `.nav__item` transition list once nothing
  animates.
- The comment above `.nav__item--active` says the active view is "marked
  three ways: an accent rail…, a plate…, and heavier type". Update it —
  two ways remain.

### Out of scope — keep

| Selector | Line | Why |
| --- | --- | --- |
| `.step--gate` | 1887, 1893 | The rule before the WRITES marker. It is *in* the screenshot the operator called "much better". |
| `.pathpick .btn` | 1428 | Separator between the input and its Browse button. Structural. |

### Acceptance

- No `border-left*` on `.stat`, `.banner`, or `.nav__item`
- Every state still distinguishable on all three
- Nav icons sit at the same x-position as before
- Render tests assert the new signal, not the bar

---

## R-2 — Responsiveness and a minimum width · OPEN

> "Responsiveness at different dimensions is poor. Even if it's small, a
> min width needs to be established."

**Operator's decision: `minWidth` 600, and fix the layout to cope.** The
demanding option, chosen deliberately over 900 or 1000.

### Root causes

1. **No width breakpoints exist.** The only `@media` rules in
   `styles.css` are `prefers-reduced-motion` (1669, 2293) and
   `forced-colors` (2317). The layout only squashes.
2. **No window floor.** `BrowserWindow` (`electron/main.ts:34-37`) sets
   `width: 1280, height: 800` with no `minWidth`/`minHeight`.

### Measured behaviour

Dashboard, via `Emulation.setDeviceMetricsOverride`:

| width | overflow | nav | content |
| --- | --- | --- | --- |
| 1280 | 0 | 236 | 1044 |
| 900 | 0 | 236 | 664 |
| 760 | 0 | 236 | 524 |
| 640 | 0 | 236 | 404 |
| 560 | **+41px** | 236 | 354 |
| 480 | **+121px** | 236 | 354 |

The nav never collapses — fixed 236px at every width, 39% of a 600px
window. Content floors at ~354px, so the scroll-free floor today is
~590px.

### What visibly breaks at 760 (before any scrollbar appears)

- The page title and its subtitle collide; the divider rule is lost
- The `SIDECAR · PROTOCOL V1` pill wraps to two lines
- `NEEDS ATTENTION` wraps while the other two stat labels do not, so the
  three cards go visually uneven

### Required

- `minWidth: 600`, `minHeight: 600` on `BrowserWindow`
- **Collapse the nav** to an icon-only rail (~64px) below ~1000px.
  Accessible names must survive — the a11y tests assert `aria-current`
  and the nav's accessible names; do not regress them
- **Reflow the header** so the title, subtitle and status pill never
  overlap: let the subtitle drop below the title, and the pill wrap or
  move, before anything collides
- **Wrap the stat row** 3-up → 2-up → 1-up rather than squeezing
- Tables get a horizontal scroll container of their own rather than
  forcing the page to scroll

### Acceptance

- No horizontal page scroll at any width ≥ 600
- No overlapping text at any width ≥ 600
- Stat labels do not wrap unevenly
- Nav is usable and named at every width
- A render test pins the breakpoint behaviour

---

## Decisions log

| Date | Decision |
| --- | --- |
| 2026-09-14 | SR-1 adopted: no left-edge colour bars, anywhere |
| 2026-09-14 | `.nav__item` included in R-1 — "no exceptions" |
| 2026-09-14 | `minWidth` 600 with layout work, over 900 or 1000 |
| 2026-09-14 | `.step--gate` and `.pathpick .btn` exempt as structural dividers |

---

## Coordination

Stage A packaging is running in parallel and touches `desktop/build/`,
`electron-builder.yml`, `scripts/`, and the frozen sidecar. This spec
touches `styles.css`, `App.tsx`, and `electron/main.ts`. **`main.ts` is
the one overlap** — R-2 needs it for `minWidth`, and Stage A may not.
Coordinate before editing it.
