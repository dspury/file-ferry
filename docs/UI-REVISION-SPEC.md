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

### SR-1 — No edge marks

> "The little braces being used are terrible. I've never liked those and
> don't want to see any version of them in the app. If we need to identify
> something with a colour, use the outline or the highlight of primary text
> as the indicator — never those brace things."
> — operator, 2026-09-14

A single coloured edge is never the state indicator — **in any state**,
resting or hovered, and whether it is drawn as a `border-left` or an
`inset` box-shadow. Use, in order of preference:

1. **The primary text** in the state colour (`.stat__value`, a label)
2. **The full outline** — `border-color` on all four sides
3. **A tinted background** (`--c-*-soft`)

The reference for the look that *is* wanted: the stage-rail cell
(`.step`) — a uniform bordered chip.

**Structural dividers are not braces** and are exempt: a full-height rule
separating two controls, or marking a boundary, carries no state. Exempt
today: `.pathpick .btn` (the divider between the input and its Browse
button) and the `.tabs__item` hairline between stage cells.

**Amended by R-10b (2026-09-17):** the original scoping to three
selectors treated a hover mark as an exemption. It is not. Hover is a
state.

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
luminance over a 7px grid, sRGB linearised, `0.2126R + 0.7152G + 0.0722B`.

**The floor is relative, not absolute.** Measure the same screen at the same
window size on `main` and on the branch, and report both. A pass that lowers
the number is a regression regardless of how it looks; a pass that raises it
has done the work. R-7 measured, at 1280×800:

| screen | before | after | |
| --- | --- | --- | --- |
| Transfer | 0.0124 | 0.0209 | +68% |
| Dashboard | 0.0140 | 0.0248 | +77% |
| Activity | 0.0122 | 0.0197 | +61% |

**An earlier version of this rule named an absolute target of 0.049. It was
wrong and has been removed.** That figure was measured on the *generated
reference images* — mockups packed edge to edge with bright panels, display
numerals and full tables. The real app has empty space, sparse data and a
dark canvas by design, and measures far lower on the same method. The two
were never comparable, and the rejected-pass figures in the old table
(0.0311, 0.0272) came from the same reference set, so they cannot be used to
judge a screenshot of the app either.

**The ceiling is the contrast floors, and it is already reached.** Brightness
cannot be raised further without breaking SR-3. Measured on the R-7 palette:

| pair | measured | floor | headroom |
| --- | --- | --- | --- |
| `--c-border-indicator` on `--c-wash` | **3.01:1** | 3.0 (SC 1.4.11) | +0.01 |
| `--c-text-faint` on `--c-surface-2` | **4.57:1** | 4.5 | +0.07 |

Brightening the canvas fails the first; brightening the panels fails the
second. These two pairs are load-bearing and nothing in the suite guards
them — treat any change to `--c-wash`, `--c-surface-2`, `--c-border-indicator`
or `--c-text-faint` as requiring both numbers recomputed.

**Do not flatten the wash to chase a contrast number.** That was tried on the
references: the wash went from 11.2× corner-to-corner luminance down to 1.7×,
and the result was darker than either option it was meant to combine.

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
| done / ok | filled dot | `--c-ok` green (amended by R-10d) |
| needs review / attention | hollow ring | amber |
| failed | filled hexagon | danger |
| cancelled | horizontal bar | muted |

Two different glyphs for one state is a defect, not a style choice. It has
already appeared once in review.

---

## R-1 — Remove the left-edge colour bars · DONE — #186 (first slice), folded into #192

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

## R-2 — Responsiveness and a minimum width · DONE — #185

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

## R-3 — One Transfer workspace, with navigable stages · DONE — #172 (`43996c4`)

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
  discrete countable cells. Cell legends are title case. The active cell
  is a **solid accent-filled pill with dark text** (`--c-accent-interactive`
  fill, `--c-on-accent` text) — the reference treatment, added by R-10a,
  which supersedes the raised plate plus inset underline this item shipped
  with.
- The transfer is a **context** the tabs are views onto. The route hash
  already carries everything needed to restore it; keep that.

### Offload and Organize — decided 2026-09-14

**Organize is withdrawn.** It duplicates something the engine already does
better. `OrganizeApplyParams` is `sourceRoot` -> `destRoot` plus entries and
a folder template, copy-only (move and link are already rejected at
`organize.py:120-123`). A `Destination` carries `organizationProfileId`.
A transfer to a preset-routed destination is therefore the *same operation*
— source to destination, applying a folder template, copying — and it is
durable, while Organize is a synchronous loop holding the sidecar's RPC
thread. There is no capability here to preserve, only a worse path to the
same result.

Withdrawal means the screen **and** the `organize.preview` / `organize.apply`
RPC methods. Removing the nav entry while the synchronous path stays
reachable over RPC resolves nothing.

**Offload is absorbed, not withdrawn.** Its camera-card work is real
capability with no equivalent in the transfer path — `source.inspect`,
`intake.adoptSource`, `intake.createSession`, and the card-safety messaging
("keep the card"). That becomes a **source type inside the Transfer
workspace**: choosing a card as the source runs inspection and surfaces the
card-safety statements, then the normal Scan -> Plan -> Preflight -> Approve
-> Copy path takes over on `TransferRunner`. The `OffloadRunner` job kind
stays for already-created jobs; no new UI path creates one.

### Acceptance

- One transfer entry point in the nav
- Every reached stage is clickable and lossless to revisit
- No UI path reaches a transfer that lacks preflight, an approval gate and
  an item ledger
- `organize.preview` and `organize.apply` are gone from the RPC surface,
  not merely unreferenced by the UI
- Selecting a camera card as a transfer source still runs inspection and
  still shows the card-safety messaging — losing that is a regression, not
  a simplification
- No new job is created with the `offload` kind

---

## R-4 — Persistent transfer dock · DONE — #177

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

## R-5 — Regroup the nav · DONE — #174 (`85133ca`)

Eleven peer entries for an app with one job. Destinations and Presets are
configuration filed among the verbs; `Media` is a label whose component is
`AssetDetail.tsx`.

### Required

Two groups. **WORK** — Dashboard, Transfer, Activity. **SETUP**, pinned to
the bottom — Destinations, Presets, Library, Settings. Rename `Media` to
match what it does.

Depends on R-3 for the Transfer consolidation.

---

## R-6 — Compact the header · DONE — #174 (`85133ca`)

Every view renders a kicker, a title, and a fixed `description` subtitle —
three lines of chrome that never change and never respond to state. It is
the direct cause of the 760px collision in R-2.

### Required

One line: title left, status readout right. The `description` field either
moves to a tooltip or is dropped; the nav already says where you are.

---

## R-7 — Surface and material migration · DONE — #192

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

## R-8 — Add an interactive accent token · DONE — #171 (`47f5461`)

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

## R-10 — Reference parity · OPEN

R-7 (#192) implemented this spec faithfully and still does not look like the
reference the operator approved. Found by booting the built renderer over CDP
at 1280x800 — not by reading the diff, which is why it took until after
review. Two of the four items below are defects in **this document**, not in
the code.

### R-10a — The active tab is an underline, not a filled pill

`.tabs__item--active` is a raised plate plus `box-shadow: inset 0 -2px 0`.
The reference (`docs/ui-refs/transfer.jpg`) shows the active stage as a
**solid accent-filled pill with dark text**.

**The code is not wrong, and neither is the builder.** R-3 specified the tab
bar's *behaviour* — clickable, divided, lossless — and said nothing at all
about how the active tab should look. The implementation picked the
underline and documented the choice honestly at `styles.css:1881` ("marked
three ways — a raised plate, full-contrast weight, and an inset accent
rule"). **The gap is that this document was silent where its own reference
image was explicit**, so there was nothing to follow but the text.

**Resolution: the reference wins.** The tab bar is the signature element of
the direction and the filled pill is what was approved on sight. Change
`.tabs__item--active` to a solid `--c-accent-interactive` fill with
`--c-on-accent` text, update the `styles.css:1881` comment to match, and
add the active-tab treatment to R-3's text so the next reader is not left
choosing between a silent spec and a picture.

Under SR-6 the active tab then becomes the screen's one emitting element on
the Transfer view — which is what the reference shows. Re-scope the glow
budget accordingly rather than having two.

### R-10b — A left-edge colour bar survived, on table rows

`styles.css:1254` — `.table tbody tr:hover td:first-child { box-shadow:
inset 2px 0 0 var(--c-accent) }`. Visible on Activity.

R-1 scoped removal to `.stat`, `.banner` and `.nav__item`, and this was
waved through in review as "line-like, not a fill". Against the operator's
actual words — *"don't want to see any version of them in the app"* — that
was the wrong reading. Hover is not an exemption.

**Resolution: remove it.** The hovered row already changes background; that
is the affordance. **SR-1 is amended**: a coloured left edge is out
regardless of whether it signals state or pointer position, and regardless
of whether it is a `border-left` or an `inset` shadow. The two structural
dividers stay exempt (`.pathpick .btn`, the `.tabs__item` hairline) because
they are full-height rules between controls, not marks on one edge of a
row.

### R-10c — Everything is uppercase · DECIDED

17 `text-transform: uppercase` rules. Tabs read `SCAN / PLAN / PREFLIGHT`,
the wordmark `FERRY / MEDIA MANAGER`, panel titles `SOURCES`. The reference
is title case throughout. This is the largest single reason the app reads
more utilitarian than the mockup.

**Decided: follow the reference.** Uppercase survives only in the
**micro-label tier** — the small, letterspaced, muted labels that sit above
or beside data and are read as annotation rather than as language. Anything
a person reads as a word goes to sentence or title case.

All 17 are classified here so none is left to judgement:

| keep uppercase (micro-label tier) | line |
| --- | --- |
| `.eyebrow` | 391 |
| `.nav__group-label` (WORK / LIBRARY / SETUP) | 488 |
| `.stat__label` | 878 |
| `.table th` | 1190 |
| `.field label` | 1337 |
| `.kv dt` | 2114 |
| `.dock__state` (TRANSFERRING) | 688 |
| `.banner__label` (the stamped severity word) | 1595 |
| `.status` (SIDECAR · PROTOCOL V1) | 610 |

| drop uppercase | line | becomes |
| --- | --- | --- |
| `.nav__wordmark` | 460 | lowercase `ferry`, per the brand guide |
| `.nav__tagline` | 470 | sentence case |
| `.card__title` | 809 | title case — `Sources`, `Plan` |
| `.tabs__item` | 1908 | title case — `Scan`, `Preflight` |
| `.seg__item` | 1138 | title case |
| `.chip` | 944 | lowercase — the reference shows `running`, `done`, `review` |
| `.progress-cell__note` | 2073 | lowercase |
| `.confirm__title` | 2182 | title case |

Letterspacing goes with the casing: a title-case label keeps normal
tracking, since `--tr-label` exists to make uppercase legible.

### R-10d — `ok` renders green; SR-10 said muted grey · DECIDED

`--c-ok: #35a96c` drives the `SUCCEEDED` chip, its dot, and the progress
bar. SR-10's table said `done / ok -> filled dot, muted grey`.

**Decided: amend SR-10, not the app.** Green for success is a strong
convention, and SR-10's actual requirement — that state survives greyscale —
is already met by the distinct dot shape. Draining the colour out of a
success state to satisfy a table entry would make the app worse. **SR-10's
`done / ok` row now reads `filled dot, ok green`.**

**But mute a settled progress bar.** Three filled green bars on Activity
strain SR-6: a finished transfer is not live and must not be the loudest
thing on the screen. A progress bar at 100% on a settled job renders in a
muted tone; only a bar that is actually moving carries `--c-ok` or the
accent. The chip stays green either way — it is the state, the bar is only
its magnitude.

### Acceptance

- Active stage tab is a solid accent fill with dark text; R-3's text
  corrected to match
- No `border-left` or `inset` edge mark anywhere on a row, tile, banner or
  nav item, in any state including hover
- Whatever is decided for R-10c and R-10d is applied consistently and this
  document is corrected in the same PR
- Verified by booting and comparing against `docs/ui-refs/`, screenshots in
  the PR — not by reading the diff

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
| 2026-09-14 | R-3 resolved: Organize withdrawn (screen + RPC), Offload absorbed as a source type |
| 2026-09-17 | SR-1 amended: no edge mark in any state, hover included (R-10b) |
| 2026-09-17 | Where this spec and its reference images disagree, the reference wins (R-10a) |
| 2026-09-17 | Uppercase survives only in the micro-label tier; all 17 rules classified (R-10c) |
| 2026-09-17 | SR-10 amended: `ok` is green; a settled progress bar is muted instead (R-10d) |

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
