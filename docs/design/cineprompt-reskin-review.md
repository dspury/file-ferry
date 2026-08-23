# CinePrompt reskin — visual and accessibility acceptance review

Acceptance pass for issue #86, the final gate on epic #83 (`UI: reskin desktop app with
CinePrompt design language`) after #87 (tokens), #85 (shell and primitives) and #88
(workflow and operational states) landed.

- **Branch reviewed:** `ui/cineprompt-reskin` at `a2ff6e6` (#88), plus the fixes this pass made.
- **Date:** 2026-08-23
- **Scope:** presentation and interaction only. No media-operation behaviour or safety policy
  was changed.

---

## 1. Eight screens, not six

Every issue in this epic — #83, #85, #86, #87, #88 — says the app has six screens: Home,
Ingest, Organize, Projects, Activity, Settings. `NAV_GROUPS` in `renderer/src/App.tsx` ships
**eight**:

| Group | View id | Label | In the issues? |
| --- | --- | --- | --- |
| Overview | `home` | Dashboard | yes |
| Overview | `activity` | Activity | yes |
| Transfer | `ingest` | Offload | yes |
| Transfer | `organize` | Organize | yes |
| Library | `projects` | Projects | yes |
| Library | `asset` | Media | **no** |
| System | `onboarding` | Environment | **no** |
| System | `settings` | Settings | yes |

Media and Environment are absent from every issue in the epic. All three implementation
commits covered them anyway; this review documents all eight. The issue text is what is
wrong, not the implementation.

---

## 2. What was actually exercised

### 2.1 The real Electron application — done for the first time in this epic

The three prior passes verified the **built renderer in headless Chromium with a stubbed
`window.ferry`**. Nothing in the chain had launched Electron. This pass did.

- Launched `dist/electron/main.js` under `node_modules/electron/dist/Electron.app` with
  `--remote-debugging-port=9444`, driven over CDP.
- The renderer was forced down its **production** path (`isDev = false` patched into the
  built `dist/electron/main.js`, which is gitignored build output — the source is untouched
  and the patch is gone after the next `npm run build`). That matters: with
  `!app.isPackaged` the shell loads `http://localhost:5173` under `DEVELOPMENT_CSP`, so the
  default dev launch cannot test the shipped policy at all. Forced to production it loads
  `file://…/dist/renderer/index.html`, which is exactly the packaged path, and the
  `<meta>` CSP in `index.html` is the only policy in force (`onHeadersReceived` does not
  fire for `file://`).
- **The Python sidecar came up.** The workspace `.venv` has file-ferry installed, so this
  was a live app against a real `ferry.db`: real volumes (`/`, apfs, 60.8 GB free), real
  jobs (four `offload` succeeded, one `ingest` cancelled, one `ingest` awaiting_review),
  real doctor output (ffmpeg and ffprobe present at `/opt/homebrew/bin`, DaVinci Resolve
  missing). The "Sidecar unreachable" path was therefore reviewed from the Chromium
  failure fixtures, not from the live app.

Results, all measured rather than eyeballed:

| Check | Result |
| --- | --- |
| Shell boots and renders the reskin | yes — `#root` populated, 836 chars of text on Dashboard |
| Production CSP vs the bundled fonts | **passes.** All four woff2 files load `200` from `file://`; `document.fonts.status === "loaded"`; `Archivo Variable` + `IBM Plex Mono` 400/500/600 report `loaded`; `document.fonts.check("16px Archivo")` and `…("16px \"IBM Plex Mono\"")` both true. `font-src 'self'` does not block them. |
| Console on boot | **zero.** No `Runtime.exceptionThrown`, no `Log.entryAdded`, no `console.*`, no `Network.loadingFailed` — across boot, a hard reload, all eight views, and every keyboard interaction below. |
| `backdrop-filter` in Electron 33 | **works.** #85 flagged this as unverified. Electron 33.4.11 / Chrome 130.0.6723.191: `getComputedStyle(.modal).backdropFilter === "blur(3px)"`, and a screenshot of the real `.modal` markup over the Media table shows every path string behind the scrim visibly smeared. Not a no-op. |
| All eight views at the app's own `BrowserWindow` size (1280×800) | render, correct header kicker and title, `documentElement.scrollWidth === clientWidth` on every one — no horizontal overflow |

### 2.2 Chromium screenshot matrix

`shoot.mjs` — 37 shots across 8 views × 10 scenarios (populated, empty, failure, loading,
unsafe, all-ten-states sweep, at-risk library, asset detail, driven plan/executed/blocked/
partial/typed-confirm flows). The full 37 were run at **1280×800**, **1440×900** and
**1728×1080** before the fixes in §6, and again at 1440×900 after them — 148 shots in total.
No page errors and no blank screens at any width, before or after.

**Every one of the 37 was opened and looked at.** #88's pass left roughly 18 unopened;
those 18 are called out individually in §4.

### 2.3 Instrumented audits

Written for this pass, driving real Chromium over CDP against the built bundle:

- **Focus traversal.** Real `Tab` key events (`Input.dispatchKeyEvent`), identity-keyed so
  the walk does not stop early on two same-looking buttons; for every element reached, the
  computed outline and its contrast against the resolved opaque background behind it.
- **Contrast on live nodes.** Computed `color` over the resolved background, including
  `::placeholder` and `:disabled`, per view and per state element.
- **Fold and overflow.** Every element's `scrollWidth` vs `clientWidth` (ignoring
  deliberately scrollable containers), plus the viewport position of every empty-state well
  and call-to-action, at three widths.
- **Reduced motion.** `Emulation.setEmulatedMedia` with `prefers-reduced-motion: reduce`.

---

## 3. Acceptance criteria, verdict by criterion

| Criterion (#83 / #86) | Verdict | Evidence |
| --- | --- | --- |
| All screens documented | **pass** | eight, §4 |
| Recognisably a CinePrompt sibling | **pass** | warm matte-black surfaces, bone/tape text, mono engraved eyebrows, one accent; §5.1 |
| Safety states understandable without colour | **pass** | every state carries a word; ten job states also differ by dot silhouette (`●` `○` `▶` `–` `▲`); a stopped meter hatches its remainder and stamps `STOPPED`/`HELD`/`DONE`; §4.2 |
| Danger red distinct from the orange accent | **pass** (improved by this pass) | danger `#f0495a` vs accent `#ff6a2c`: −23.7° hue and 0.76× relative luminance, so they separate in greyscale too. `Cancel` was drawn in danger red on every cancellable row — fixed, §6.3 |
| Contrast | **pass** | 156 distinct live element/background pairs measured across eight views; **zero** below the applicable threshold; minimum 4.55:1 (`table th`, 11px). Placeholder text 5.21:1, disabled button labels 5.47:1, enabled primary 6.66:1 (computed from `--c-on-accent` on `--c-accent`). |
| Visible keyboard focus | **pass** (after fix) | every focusable element on all eight views carries `outline: solid 2px #ff6a2c` at **6.23–6.91:1** against its own background — 0 with no indicator, 0 below 3:1, across 126 elements in the exhaustive walk (108 in a second, independently-keyed walk). Distinct from danger red by hue and luminance. |
| Keyboard navigation | **pass** (after fix) | ArrowUp/ArrowDown/Enter, wrap-around, skip link — §6.1, §7 |
| Dense-table legibility | **pass** | §4.2, §4.6 |
| Status labels/icons | **pass** | §4 throughout |
| Progress semantics | **pass** | #88's meter statuses hold up; nothing claims completion before it is confirmed; §4.2 |
| Long paths, collision/verification banners, sidecar-confirmed execution, typed move confirmation, safe-to-format | **pass** | §4.3, §4.4, §5.3 |
| Supported desktop sizes | **pass with one filed item** | three widths; one empty-state fold issue partly fixed, remainder filed — §6.4 |
| No major layout/overflow/focus/contrast/state-hierarchy regression left open | **pass** | four regressions found and fixed (§6); the items left open are pre-existing or design decisions, filed (§8) |
| Build and tests pass | **pass** | §9 |

---

## 4. Screen by screen

Shots marked **(unopened by #88)** are the ones the previous pass generated but never looked
at. They are where two of this pass's four fixes came from.

### 4.1 Dashboard (`home`)

- `populated` **(unopened)** — six stat tiles, connected sources, six recent jobs. The tone
  rails and value colours are correct per `homeCards`: active work is the accent, not green.
  All six values share a baseline: the wrapping labels ("Needs attention", "Unverified
  replicas") are held on one line's worth of extra height by `min-height: calc(2 * 1.45 *
  --fs-xs)` on `.stat__label`, verified by measurement — all six `.stat__value` boxes report
  `top: 137` in the live app at 1280 wide. A zero count correctly falls back to neutral so a
  healthy system shows no alarm.
- `empty` — **found a regression.** Two empty wells, 297px and 278px, pushed "Start an
  offload" — the only actionable thing on a first-run Dashboard — to y=887 in a 900px
  window. It was above the fold before the reskin. Fixed (§6.4).
- `loading` **(unopened)** — framed inside the card the content will arrive in, with an
  indeterminate accent sweep and a hint that says nothing is being written. Correct: an
  indeterminate bar cannot be read as a fraction.
- `failure` — danger banner over an accent `Retry`; the two hues sit adjacent here and are
  clearly distinguishable.
- `unsafe` **(unopened)** — `FAILED 1` in danger, `NEEDS ATTENTION 1` in attention purple,
  chips matching. Noted while here: `unsafeCards`, `unverifiedReplicas` and `proxyPending`
  are hard-coded to `0` in `Home.tsx`, so three of six tiles — including both safety tiles —
  can never report anything. Pre-existing, filed (§8.6).
- `states` — all ten job states in the recent-jobs list, each separable in greyscale.

### 4.2 Activity (`activity`)

- `populated` **(unopened)** — the busiest screen in the app and the one this pass changed
  most. `job.error` renders as a note row under its job; the meter hatches a stopped
  remainder and stamps `HELD`; `CANCELLED` is a dashed plate with a `–` glyph, not a red one.
- `states` — ten states at once: `PLANNED`, `AWAITING_REVIEW`, `QUEUED`, `RUNNING`,
  `VERIFYING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `NEEDS_ATTENTION`, `RESUMABLE`. Each has
  its own word, its own dot silhouette and — where it has one — its own meter treatment.
  This is the strongest single piece of evidence for the no-colour-alone criterion.
- **Found:** `Cancel` was `btn btn--danger` on every cancellable row. On this table that is
  four red outlined buttons at once, competing with the `FAILED` chip, the failed bar and the
  `FAILED:` banner that genuinely need that hue — and the same word in the typed-move dialog
  is rendered as the *neutral* button, because there it is the safe choice. Fixed (§6.3).
- `failure` **(unopened)** — `CANNOT LOAD: sidecar unreachable`, with copy that says
  retrying costs nothing because no media is touched by a failed read. Good.
- `loading` **(unopened)** — "Reading the job log… Running jobs keep going while this loads."
- Accent density here is real: at 1280 wide the toolbar carries the `LIVE · N WATCHED` chip,
  the segmented control's active marker, up to four accent state chips and the accent
  progress fills. Judged acceptable — every one of those except the `LIVE` chip is either
  interactive or genuinely live work — but the passive `LIVE` chip is the weakest claim on
  the accent. Filed as design polish (§8.1), not a defect.

### 4.3 Offload (`ingest`)

- `empty` **(unopened)** — the six-stage rail with the yellow `WRITES` gate between REVIEW
  and EXECUTE. The gate carries a visually-hidden "from here on, ferry writes to disk", so
  it is not a colour-only marker.
- `populated-plan` **(unopened)** — long source paths split on the last separator
  (`PRIVATE/M4ROOT/CLIP/DAY_014_EXT_HARBO… A014C0031_260814_R1XZ.mxf`), head elided, filename
  intact. This is #88's fix for the `direction: rtl` bug and it reads correctly. `CAPACITY OK`
  chip beside `6 copies · 27.1 GB`.
- `collisions-blocked` — `NOT ENOUGH ROOM: The destination is short by 442.4 GB. Execute stays
  disabled until it fits` and `COLLISIONS: 2 group(s) below would land on paths that already
  hold a file`, both danger banners, plus a `NEEDS 442.4 GB MORE` chip in the panel header.
  Blocking conditions are stated, not implied.
- `populated-executed` — the offload is created only after a sidecar-confirmed plan, and
  "safe to format" appears as the standing instruction to keep the card until the receipt
  says otherwise.
- Noted: `Scan source` stays a filled accent primary after it has been used, so a mid-flow
  screen shows two solid primaries (`Scan source` and `Build plan`) plus the accent active
  stage. Pre-existing hierarchy noise, filed (§8.5).

### 4.4 Organize (`organize`)

- `empty` **(unopened)** — five-stage rail, `WRITES` gate before APPLY, mode select with
  "Source files are left untouched." under Copy.
- `collisions-blocked` — move mode with collisions: blocking banner plus the destructive
  acknowledgement checkbox.
- `populated-confirm` — the typed move confirmation. Danger-bordered dialog, `MOVE FILES` in
  danger, the phrase `move` set in mono inside a danger-outlined plate so its own casing
  survives, sans sentence-case body copy, `Move files` disabled until the phrase matches, and
  `Cancel` as the neutral button. The scrim blur is real in Electron (§2.1).
- `populated-partial` — **found, filed not fixed.** After an apply where one entry failed,
  the `Result: 5 of 6 entries written, 1 failed` and `Incomplete:` banners sit at y=1053 and
  y=1098 while the fold shows the stage rail with `DONE` as the current stage and a green
  `NO COLLISIONS` chip. An operator who does not scroll sees a screen that looks like a clean
  success. Pre-existing page order, unchanged by the reskin, and fixing it means moving
  content within the screen rather than restyling it — so it is filed (§8.4) rather than
  changed unilaterally in an acceptance pass.

### 4.5 Projects (`projects`)

- `populated` — `UNVERIFIED` in warn with a `▲` glyph, `POLICY MET` in ok with a `●`. Two
  different silhouettes, so the two states are not distinguished by hue alone. Policy summary
  in mono (`2 replica(s) · xxhash64 · backup`).
- `empty` **(unopened)** — one well, "A project is created as part of an offload", with a
  `Go to Offload` primary. Correct: this screen has no create action of its own.
- `failure` **(unopened)** / `loading` — shared `ScreenError` / `ScreenLoading`, framed.

### 4.6 Media (`asset`)

- `populated` **(unopened)** — 24 rows, five columns, mono paths, lifecycle chips
  (`VERIFIED` / `NEEDS_REVIEW` / `MISSING`) toned per #88. Dense but legible; the state
  column is the only coloured thing per row.
- `atrisk` / `atrisk-assetdetail` — the tally block above the table can stack a `MISSING`
  danger banner and a `NEEDS REVIEW` warn banner; a library that is also carrying unverified
  replicas gets a third. Two already take ~12% of the fold. Filed as design polish (§8.3).
- Asset detail: metadata, replicas with per-copy status, proxy state with three derivative
  states (`ready` 100% `DONE`, `running` 42% no stamp, `failed` 18% hatched `STOPPED`).
  **Found:** the replica status cell printed the chip *and* the availability string, so a
  missing replica read `MISSING` then `missing` underneath — the same fact twice, the second
  time more weakly. Fixed (§6.5).
- `empty` **(unopened)** — one well, `Go to Offload`.
- `loading` **(unopened)** — "Reading the media library… No file on disk is opened or
  checksummed by this."

### 4.7 Environment (`onboarding`)

- `populated` **(unopened)** — **found the epic's outstanding two-hue defect and its cause.**
  #88 handed over "the banner says INCOMPLETE in warn yellow while the chip says MISSING in
  attention purple". The cause is that `Onboarding.tsx` never called `overallHealth` at all:
  it hard-coded `tone="warn"` for any absence. `overallHealth` was exported, unit-tested, and
  unused by the product. Fixed (§6.2) — and fixing it exposed a second, worse bug in
  `overallHealth` itself, §6.2.
- `unsafe` **(unopened)** — ffmpeg and ffprobe missing. Before this pass the headline said
  `INCOMPLETE` in warn yellow directly above two danger-red `MISSING` chips: a missing
  *required* tool was being understated. Now `MISSING REQUIRED` in danger, matching its own
  chips, with the optional Resolve still in attention purple.
- `empty` — no volumes at all gets its own explanation ("On macOS that usually means the app
  has not been granted access to removable volumes yet") rather than an empty table head.
- In the live app: real paths (`/opt/homebrew/bin/ffmpeg`, `/Users/dspury/.ferry/config.toml`)
  render in mono without wrapping at 1280 wide.

### 4.8 Settings (`settings`)

- `populated` / `empty` **(unopened)** — mono inputs and textareas (every one holds a path, a
  template, a number or a confirm phrase), sans selects (a select can hold a human-named
  project). Validation appears as a warn `CANNOT SAVE: unknown conflict policy: suffix;
  unknown proxy codec: dnxhr_lb` banner with `Save settings` disabled.
- `failure` **(unopened)** — shared `ScreenError`.
- At 1728 wide the content column stays at its editorial max-width instead of stretching the
  fields across the window.

---

## 5. Settled decisions, re-examined not re-litigated

These were decided in #87/#85/#88. This pass checked only whether they cause a concrete
defect. None did.

1. **Danger holds at 353.9°** — verified separable from the accent by both hue (−23.7°) and
   luminance (0.76×), and measured at 4.92–5.01:1 wherever it carries text.
2. **Mono inputs, sans selects** — consistent across Settings, Offload, Organize and the
   confirm dialog. No case found where a select holds a machine value or an input holds prose.
3. **Opaque `-soft` plates** — every chip and banner foreground measured on its own fill;
   minimum 5.01:1.
4. **`active` is the accent** — the interaction hue doubles as the live-work hue. This is the
   root of the accent-density question in §8.1, but it is coherent: the accent means "live or
   pressable", and nothing dead wears it.

---

## 6. Defects fixed in this pass

### 6.1 Arrow-key navigation moved the route and left focus behind — `App.tsx`

`onNavKeyDown` called `navigateTo` and nothing else. Measured before the fix: from Dashboard,
ArrowDown → route `#/activity`, `aria-current="page"` on **Activity**, `document.activeElement`
still **Dashboard**. A second ArrowDown → `#/ingest`, current Offload, focus still Dashboard.
So the one visible indicator that says "you are here" pointed at the wrong row, and assistive
tech was told nothing at all, because nothing it was watching had changed.

Fixed with a gated roving-focus effect: an arrow key sets a flag, and the effect that runs on
`viewId` moves DOM focus to `.nav__item--active`. It is gated rather than unconditional
because a click already focuses the button it pressed, and an in-content link ("View all in
Activity") must be allowed to leave focus in the content it came from.

Verified in the **real Electron app** after the fix — start Dashboard; ArrowDown → Activity
focused and current, ring `rgb(255,106,44) 2px`; ArrowDown → Offload; ArrowUp → Activity;
Enter → stays on Activity (no double-handling); from Settings, ArrowDown wraps to Dashboard
across the footer-group boundary. Zero console output throughout.

`keyToAction`'s `activate` result stays deliberately unhandled: Enter and Space already press
a `<button>`.

### 6.2 The Environment verdict was decoupled from the facts — `lib/doctor.ts`, `Onboarding.tsx`

Two bugs, one of which was only visible once the first was fixed.

1. `Onboarding.tsx` hard-coded `tone="warn"` / `label="Incomplete"` for any missing tool. A
   missing **required** tool was announced in warning yellow above its own danger-red chip.
   `overallHealth` — exported and unit-tested since #87 — was never called by any screen.
2. Wiring `overallHealth` in produced `READY: 1 tool not found: DaVinci Resolve` in green. Its
   optional-tool test was `t.name === 'resolve'`, but the sidecar reports `"DaVinci Resolve"`
   — **the identical bug #88 fixed in `toolTone` and did not fix here.** Its required list was
   `['ffmpeg', 'ffprobe']`, so any other absence (the real doctor payload also carries
   `config`) also fell through to `ok`.

Fixed by giving both derivations one shared predicate, `isOptionalTool`, and defining required
by exclusion — a tool the sidecar reports and cannot find is a tool ferry wanted:

```
overallHealth: no absences → ok; any absence that is not the optional integration → danger;
               otherwise → attention
```

`Banner` gained the `attention` tone it was missing (`.banner--attention`, 7.28:1 for its
label — the same pair the chip it now matches already measured). The Environment screen now
draws one fact in one hue: optional-only → purple `INCOMPLETE` over a purple `MISSING` chip;
required missing → red `MISSING REQUIRED` over red chips, with the optional one still purple.

### 6.3 `Cancel` spent the danger hue — `Activity.tsx`

Flagged by the epic owner for judgement. Cancelling a job is not destructive: the source card
is untouched, the partial copy stays on disk, nothing is irreversible — and ferry already
gates its one genuinely destructive action behind a typed confirmation whose own `Cancel` is
rendered *neutral*. So the app was using its loudest hue for a reversible control in one place
and its quietest for the same word in another, while a busy table put up to four red outlines
next to the `FAILED` chip and `FAILED:` banner that need that hue to mean something.

`Cancel` is now the plain `btn`, matching `Receipt`/`Resume`/`Retry` — row actions of equal
weight. `btn--danger` is now exactly two controls, both of which delete or move originals:
`Apply (move)` and the typed move confirmation. Contrast improved as a side effect, 4.92:1 →
13.44:1.

Trade-off, stated plainly: `Cancel` no longer stands out from its sibling row actions. That is
the correct trade — it is not the destructive one — but it is a real change in emphasis.

### 6.4 The empty Dashboard pushed its only action off the fold — `styles.css`

Measured: `.empty` wells at 297px and 278px, empty-Dashboard content 949px, "Start an offload"
at y=887 in a 900px window and y=887 in an 800px one. The pre-reskin baseline shot
(`before/empty--home.png`, 1440×900) has the same two wells but shorter hint copy and no
action in the first one; measuring its button off that screenshot puts it at roughly y=778 —
inside the fold. (That number is read off a pixel, not measured in a running pre-reskin build,
which is no longer checked out; the two post-fix numbers below are live measurements.) So this
is a regression introduced within the epic by #88's richer empty states.

Fixed by tightening the well: vertical padding `--sp-7` → `--sp-5`, and `.empty__hint`'s
measure `44ch` → `58ch` so two- and three-line hints lose a line (still inside the readable
45–75ch band).

| | before fix | after fix |
| --- | --- | --- |
| Dashboard wells | 297 / 278 px | 254 / 234 px |
| Dashboard content height | 949 px | 862 px |
| CTA at 1440×900 | y=887, **off-screen** | y=812, **visible** |
| CTA at 1280×800 | y=887, off-screen | y=812, off-screen by 12px |

Resolved at 1440×900 and above. At the app's own 1280×800 default the page still scrolls and
the CTA is 12px short; closing that needs a compact empty variant and a decision about which
of Dashboard's two panels gets it, which is design work rather than regression repair. Filed
(§8.2) with these numbers.

### 6.5 A replica said `MISSING` and then `missing` — `lib/asset.ts`, `AssetDetail.tsx`

The status cell rendered the health chip and then `r.availability` under it. That line exists
for a real case — a verified copy on an unmounted drive is still verified and still not
openable — but when availability *is* the state, it repeated the chip's own word in lower case
as a second, weaker claim. Extracted `availabilityNote`, which returns `null` when the
availability adds nothing.

---

## 7. Keyboard, focus and motion

- **Focus indicator.** 126 focusable elements walked with real `Tab` events across all eight
  views: nav items, skip link, segmented radios, search inputs, selects, path-picker buttons,
  table row buttons, form inputs, ghost buttons. Every one: `outline: solid 2px
  rgb(255,106,44)` at offset 1–2px, measuring **6.23–6.91:1** against the background actually
  behind it. Zero without an indicator; zero below 3:1 (WCAG 1.4.11 wants 3:1). The ring is
  the accent, not danger red — different hue and different luminance, so "focused" can never
  be mistaken for "dangerous".
- **Skip link.** On a fresh load the first Tab lands on `a.skip-link`, which becomes visible
  at the top-left (`rect [0,0,110,36]`, `z-index: 100`) with the accent ring; Enter moves
  focus to `main#content`.
- **Arrow keys.** ArrowDown/ArrowUp traverse the flattened eight-view list across group
  boundaries and wrap at both ends. After §6.1 the focus follows. Enter and Space activate
  natively.
- **`prefers-reduced-motion: reduce`** — verified by emulation, not by reading the CSS:
  `.busy__meter` computes `display: none` (removed rather than frozen, so a stopped
  indeterminate bar cannot be misread as a stalled fraction), `.busy__sweep`'s
  `animation-name` is `none`, and `.nav__item`'s `transition-duration` drops from `0.14s` to
  `0s`. Unhandled state count under emulation: 0 animated elements.

---

## 8. Filed as follow-ups

Deferred polish, recorded separately from the behaviour changes above, as #86 requires. None
of these was fixed in this pass.

| Issue | Title | Labels | Source |
| --- | --- | --- | --- |
| #89 | Activity's accent load — the passive `LIVE · N WATCHED` chip competes with live-work chips | design | #88's handover, judged here |
| #90 | Empty Dashboard still scrolls at the 1280×800 default window — needs a compact empty variant | design | residual of §6.4 |
| #91 | Media's tally block can stack three banners above the table | design | #88's handover, confirmed here |
| #92 | Organize's apply result lands below the fold, under a `DONE` stage marker | design | found here, §4.4 |
| #93 | A completed stage's action stays a filled primary, so two primaries compete mid-flow | design | found here, §4.3 |
| #94 | Dashboard: three tiles, including both safety tiles, are hard-coded to zero | design | found here, §4.1 |
| #95 | No assistive-technology pass has been run against the reskin | accessibility | gap, §10 |

#89 and #91 are the two items #88 handed over that turned out not to be defects; #90 is what is
left of one that was. The Environment two-hue item #88 also handed over was a defect and is
fixed (§6.2); the `Cancel`-in-danger-red item the epic owner handed over was also a defect and
is fixed (§6.3). Nothing from either handover is left undecided.

---

## 9. Gates

Run from `desktop/` at the end of this pass:

| Gate | Result |
| --- | --- |
| `npm run typecheck` | pass |
| `npm test` | **221 passed** (baseline 209; +12 from `tests/p7h-lib.test.ts`) |
| `npm run lint` (eslint + oxlint anti-slop) | pass |
| `npm run format:check` | pass |
| `npx prettier --check renderer/src/styles.css` | pass |
| `npm run build` | pass |
| `shoot.mjs` × 3 viewports (+ a post-fix re-run) | 148 shots, no page errors, no blank screens |

The 12 new tests cover the pure logic this pass changed: `isOptionalTool` against the name the
sidecar really sends, `overallHealth` never returning `ok` while a tool is missing, `healthBanner`
agreeing with `toolTone` about the tool that decided the verdict, and `availabilityNote`.

---

## 10. What this pass could **not** verify

Stated plainly rather than implied.

- **A real screen reader.** No VoiceOver/NVDA/Narrator session was run. What was verified is
  the markup and the computed accessibility affordances: `role="status"` on the sidecar
  indicator, `aria-current="page"` on the active nav item and `aria-current="step"` on the
  active stage, `role="group"` + `aria-label` per nav group, `aria-busy` and a polite live
  region on loading states, `role="alert"` on danger banners, `aria-modal` plus a focus trap
  on the dialog, visually-hidden text on the `WRITES` gate and completed stages, and radio
  semantics on the segmented control. Whether those *announce well in sequence* is unverified.
  Filed as §8.7.
- **Windows path rendering.** macOS only. `splitPathTail` splits on the last separator and is
  unit-tested, but no build was run on Windows and no backslash-separated path was rendered in
  a real window. Drive letters, UNC paths (`\\server\share`) and long-path prefixes
  (`\\?\C:\…`) are untested in the UI.
- **The live "sidecar unreachable" path.** The sidecar came up in the real app, so that state
  was reviewed from Chromium fixtures rather than from a genuinely dead sidecar.
- **A packaged build.** `app.isPackaged` was forced false-to-production in the built main
  process; `electron-builder` was not run, so the frozen-sidecar resolution path
  (`resources/sidecar/ferry-service`) and code signing are untested here.
- **Windows/Linux Electron.** macOS arm64 only, Electron 33.4.11.
- **Non-default OS settings.** No forced-colours / high-contrast mode, no OS text scaling, no
  zoom above 100% was exercised.
- **Real camera-card hardware.** Volumes, collisions and capacity shortfalls came from
  fixtures; the live app saw only the system disk.
