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

**Amended by R-8:** one token is added — the interactive accent. That is
the only sanctioned change, and #162 is updated in the same commit.

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

### SR-5 — Material: translucent glass over an atmospheric wash

The shell is layered translucent material, not a wireframe. Three levels:

| level | role | note |
| --- | --- | --- |
| wash | the canvas | a large-scale, single-direction gradient, brighter toward the upper left of the **content area** |
| rail | recessed | darker than the content at every height, including the top |
| panel | raised | frosted translucent over the wash, ~14px radius, gentle vertical gradient lighter at the top, soft ambient shadow |

**Rims.** A large panel and the transfer dock each carry a soft 1px rim of
lighter tone around the whole perimeter. That rim, not the fill, is what
gives a panel its silhouette — measured, a panel fill differs from adjacent
canvas by only **1.16:1**, which is not enough to define an edge on its own.

**Rims stop there.** Table rows, status words, chips, and the individual
statistics in a hero panel get no rim and no box. They are separated by
spacing and the faintest hairlines. SR-1 still governs: a rim is a full
perimeter, never one edge.

**No row striping.** Table rows are one tone, divided by hairlines only.

**Gradients** belong in exactly three places: the canvas wash, a panel's
own vertical fill, and an accent fill. Never on text, icons, or borders.

### SR-6 — Glow budget: one emitting element per screen

Exactly **one** element emits light at any time — the active stage tab, or
the leading progress bar, or the primary action. Everything else is *lit*
but does not emit: rims, nav plates, buttons, status pills, dividers, text.

The intensity is restrained — roughly a third of what reads as "neon."

This is not decoration policy, it is a state-signalling budget. Spending
the brightest thing on screen on chrome leaves nothing in reserve for an
actual alarm.

### SR-7 — Brightness floor

The interface is bright and legible. A "more restrained" pass that darkens
the whole frame is a regression, and it is measurable — mean frame
luminance, sampled on a 7px grid:

| pass | mean luminance | verdict |
| --- | --- | --- |
| luminous glass (adopted) | **0.0492** | the target |
| elevated, flat canvas | 0.0311 | dimmer |
| "converged" (rejected) | 0.0272 | dimmest — rejected for this reason |

**Do not flatten the wash to chase a contrast number.** That was tried: the
wash went from 11.2× corner-to-corner luminance down to 1.7×, and the whole
app got darker than either option it was meant to combine.

### SR-8 — Monospace is for data only

File paths, byte counts, durations, hashes, ids. Never headings, never
button labels, never micro-labels. Mono everywhere is what makes an
interface read as a terminal utility rather than a product.

### SR-9 — Dramatic scale contrast

One number per view is at display scale; its label is a small uppercase
letterspaced micro-label. A ratio around 6× between the hero numeral and
the labels around it is the intent. Everything at one middling size is the
look being replaced.

### SR-10 — One glyph per state, globally

A state's glyph is fixed across the whole app, so state survives greyscale
and never depends on hue alone:

| state | glyph | tint |
| --- | --- | --- |
| running / active | filled triangle | accent |
| done / ok | filled dot | muted grey |
| needs review / attention | hollow ring | amber |
| failed | filled hexagon | danger |
| cancelled | horizontal bar | muted |

Two different glyphs for one state is a defect, not a style choice. It has
already appeared once in review.

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
2. **No window floor.** `BrowserWindow` (`electron/main.ts:36-37`) sets
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

## R-3 — One Transfer workspace, with navigable stages · OPEN

Offload, Organize and Transfers are three peer entries in the nav
presenting the same shape — pick a source, preview, approve, watch, get a
receipt. They share components and read as siblings. They are not siblings;
they have **zero RPC methods in common** and three different durability
levels:

| screen | backend | preflight | approval gate | job record | crash resume | cancel | progress |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Transfers | `TransferRunner` | yes | yes | yes + item ledger | per item | yes | yes |
| Offload | `OffloadRunner` | no | job-level | yes | whole job | job-level | job-level |
| Organize | **no runner** | no | no | **none** | **none** | **none** | **none** |

`organize_apply` (`src/file_ferry/application/organize.py:112`) is a
synchronous loop inside the RPC handler. It holds the sidecar's RPC thread
for the whole operation, so a large organize makes the app stop answering.

**The UI presents these as three equal choices and an operator cannot tell
them apart.** That is the defect; the visual merge is downstream of it.

### Required

- One **Transfer** nav entry. The five stages — Scan, Plan, Preflight,
  Approve, Copy — become a **segmented tab bar**, not a wizard: a stage
  already reached stays clickable, and leaving a stage never discards it.
  Segments are divided by thin vertical hairlines so the five read as
  discrete countable cells.
- The transfer is a **context** the tabs are views onto. The route hash
  already carries everything needed to restore it; keep that.
- Offload and Organize are resolved, not merely hidden. **This is a
  decision the spec does not make**: either their capabilities port onto
  `TransferRunner`, or they are withdrawn. Hiding a nav entry while the
  synchronous `organize_apply` path stays reachable over RPC resolves
  nothing.

### Acceptance

- One transfer entry point in the nav
- Every reached stage is clickable and lossless to revisit
- No UI path reaches a transfer that lacks preflight, an approval gate and
  an item ledger
- The Organize RPC-thread block is either gone or documented as withdrawn

---

## R-4 — Persistent transfer dock · OPEN

There is no always-visible representation of work in flight. A running
transfer lives in the Transfers hash; navigate away and the route back is
a hash the operator no longer has. For an app whose value is long-running
operations that must not be lost, that is the wrong default.

### Required

A dock pinned across the bottom of the window whenever a transfer is
active, present on every screen: source → destination, a progress track,
files and bytes and time remaining, and **View** plus **Pause/Cancel**.

- Dock material follows SR-5: frosted, rimmed, ambient shadow upward.
- The progress fill may be the screen's one emitting element (SR-6).
- The dock is also what makes collapsing the nav (R-2) safe — navigating
  away can no longer lose your place in the work.

### Acceptance

- Visible on every view while a transfer is active, absent otherwise
- Cancel routes through the same gate the Transfer screen uses; the dock
  never gets a privileged path to a destructive action
- Does not overlap content — the content area shortens by the dock height
- Present and usable at the R-2 minimum width

---

## R-5 — Regroup the nav · OPEN

Eleven peer entries for an app with one job. Destinations and Presets are
configuration filed among the verbs; `Media` is a label whose component is
`AssetDetail.tsx`.

### Required

Two groups. **WORK** — Dashboard, Transfer, Activity. **SETUP**, pinned to
the bottom — Destinations, Presets, Library, Settings. Rename `Media` to
match what it does.

Depends on R-3 for the Transfer consolidation.

---

## R-6 — Compact the header · OPEN

Every view renders a kicker, a title, and a fixed `description` subtitle —
three lines of chrome that never change and never respond to state. It is
the direct cause of the 760px collision in R-2.

### Required

One line: title left, status readout right. The `description` field either
moves to a tooltip or is dropped; the nav already says where you are.

---

## R-7 — Surface and material migration · OPEN

Apply SR-5 through SR-10 to the existing stylesheet. This is the visual
pass, and it depends on R-8 for the accent token.

Scope: canvas wash, rail recession, panel fills and rims, radius, removal
of per-element boxes and row striping, mono restricted to data, the type
scale gap, the state-glyph table.

### Rail recession is a fix, not a preference

Measured on the reference: the muted `WORK` / `SETUP` labels sat at
**3.34:1** because the wash was brightest at the top of the rail — a real
WCAG failure. Recessing the rail to `#0A1A2F` takes the same labels to
**5.73:1**. The rail should read as behind the content regardless; this
makes it required.

---

## R-8 — Add an interactive accent token · OPEN

`ferry #75A1C6` is hue 207.4°, **saturation 41.5%**, lightness 61.8%. It is
the identity colour and it stays. It is also too muted to carry a filled
interactive state — a gradient on it reads as muddy.

**Contrast does not decide this.** Holding hue and lightness and sweeping
saturation moves contrast by 0.15 across the whole usable range:

| saturation | hex | ink text on fill | as text on `--c-surface-2` |
| --- | --- | --- | --- |
| 41.5% (`ferry`) | `#75A1C6` | 6.62:1 | 5.42:1 |
| **75.4% (chosen)** | **`#54A4E7`** | **6.77:1** | **5.54:1** |
| 97.8% (as rendered) | `#4BACFD` | 7.44:1 | 5.61:1 |

### Required

Add one token — `#54A4E7`, ferry's exact hue and lightness at 75%
saturation — for **filled interactive accents only**: active tab, primary
button, progress fill, focus ring. `ferry` keeps the logo, brand surfaces,
and every non-filled use.

**This amends SR-2.** #162 pins all 33 `--c-*` values and will fail on the
addition; that test is updated as part of this item, deliberately and in
one commit, not worked around.

### Acceptance

- Exactly one new colour token; no other pinned value changes
- #162 updated in the same commit, with the new value pinned
- No filled accent uses `ferry`; no brand surface uses the new token

---

## Decisions log

| Date | Decision |
| --- | --- |
| 2026-09-14 | SR-1 adopted: no left-edge colour bars, anywhere |
| 2026-09-14 | `.nav__item` included in R-1 — "no exceptions" |
| 2026-09-14 | `minWidth` 600 with layout work, over 900 or 1000 |
| 2026-09-14 | `.step--gate` and `.pathpick .btn` exempt as structural dividers |
| 2026-09-14 | Visual direction: luminous translucent glass, not flat elevated surfaces |
| 2026-09-14 | Glow kept but budgeted to one emitting element per screen |
| 2026-09-14 | Brightness is a floor, not a preference — a darker pass was tried and rejected |
| 2026-09-14 | Offload / Organize / Transfers consolidate into one Transfer workspace (R-3) |
| 2026-09-14 | Stages are a clickable tab bar over a persistent context, never a wizard |
| 2026-09-14 | A persistent transfer dock is adopted (R-4) |
| 2026-09-14 | One interactive accent token added at 75% saturation; SR-2 amended (R-8) |

---

## Reference images

`docs/ui-refs/` holds the approved visual direction. They are generated
mockups, not screenshots of the app, and they are **directional, not
literal**:

| file | shows |
| --- | --- |
| `transfer.jpg` | stage tab bar, hero panel, plan list, panel material |
| `dashboard.jpg` | scale contrast, hero progress, unboxed statistics, state glyphs |
| `dock.jpg` | the persistent dock material and contents (ignore the screen behind it — it drifted) |

Known inaccuracies in all three, do not reproduce them:

- **The logo is a generic wave, not the ferry mark.** The real SVG lives at
  `assets/brand/ferry-logo-black.svg`.
- The accent renders near **97% saturation**; the spec value is
  `#54A4E7` at **75%**, which is calmer. Build to the token, not the image.
- Nav labels and file paths in the images are placeholder.

---

## Coordination

Stage A packaging landed on `feat/stage-a-packaging` (`1b4996e`) and
touches `desktop/build/`, `electron-builder.yml`, `scripts/`, and the
frozen sidecar. This spec touches `styles.css`, `App.tsx`, the screens,
and `electron/main.ts`. **`main.ts` is the one overlap** — R-2 needs it
for `minWidth`. Rebase on Stage A rather than racing it.

## Suggested order

R-8 first: the accent token settles the palette everything else is drawn
against, and it is a small, self-contained change that includes its own
test update.

Then R-3, because it decides what screens exist. R-5 and R-6 fall out of
it. R-7 is the bulk of the visual work and wants a settled screen list.
R-1 is subsumed by R-7 but can land early on its own. R-2 and R-4 are
coupled — the dock has to survive the minimum width, and the collapsed
nav is only safe once the dock exists.

**R-3 has an open question that is not the builder's to answer:** whether
Offload and Organize port onto `TransferRunner` or are withdrawn. Raise it
rather than picking one.
