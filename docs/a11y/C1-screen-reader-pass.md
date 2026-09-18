# C-1 (#95) — accessibility pass: written record

Date: 2026-09-17 · Build: `main` @ `f42f65d`, built renderer
(`npm run build`) booted in Electron · Machine: macOS arm64, Aqua session

This is the written record for C-1. It is an **accessibility-tree and keyboard
audit**, not a VoiceOver session. See "Method and limits" before drawing
conclusions from it.

---

## Method and limits

**What was run.** The built renderer was booted over CDP
(`--remote-debugging-port`, `FERRY_RENDERER_URL` → `dist/renderer/index.html`)
and interrogated with:

- `Accessibility.enable` + `Accessibility.getFullAXTree` — Chromium's
  accessibility tree, i.e. the tree Chromium hands to the macOS accessibility
  API that VoiceOver consumes.
- DOM/ARIA attribute inspection for the same elements.
- Real key events through the `Input` domain (`Tab`, `Shift+Tab`,
  `ArrowUp/Down`, `ArrowLeft/Right`), reading `document.activeElement` and the
  computed focus ring (`outline-color` / `outline-width`) at every stop.
- An emulated 1280×800 viewport.

The harness is committed at `docs/a11y/audit-a11y.mjs`; raw per-route JSON was
captured to a scratch directory and is summarised here.

**What this proves.** Role/name/state as the platform accessibility API
receives them, the order and reachability of focus, the association of table
headers, and the computed focus ring.

**What this does not prove.** It is not VoiceOver output. It says nothing about
what VoiceOver *says*, how it orders or groups an announcement, its verbosity,
its pronunciation, or the timing/experience of live-region announcements. An
aria audit is evidence about markup and the accessibility tree, not about a
screen reader's speech.

**VoiceOver was not run.** VoiceOver exposes an AppleScript interface
(`vo cursor`, `last phrase`, `commander perform command`) and the machine is a
real Aqua session, so it was attempted. VoiceOver launched but its scripting
objects never became available (`Can't get bounds of vo cursor`,
`Can't get content of last phrase`, `output` unrecognised) even after the
Cmd-F5 toggle, and the operator asked for it to be turned off. It is not
claimed to have been exercised. A real VoiceOver pass remains outstanding.

---

## Coverage

Ten route states were audited: Dashboard, Transfer (empty and
plan-reached), Activity, Projects, Assets, Destinations, Presets, Environment,
Settings.

### Nav — PASS

- `navigation "Primary"` landmark; three groups with accessible names
  `Work` / `Library` / `Setup` (`role="group"` + `aria-label`). The visible
  group heading is `aria-hidden`, so the name is not read twice.
- Exactly one item carries `aria-current="page"`, and it tracks the route.
- Arrow traversal runs in visual order and wraps at both ends:
  `Transfer → Activity → Projects → Assets → Destinations → Presets →
  Environment → Settings → Dashboard → Transfer`, with the active state
  following focus. (This is the `#86` fix, re-verified.)

### Stage tab bar — PASS

- `role="tablist"` named "Transfer stages"; five `role="tab"` children with
  `aria-controls`.
- Roving tabindex is correct: only the selected tab has `tabindex="0"`; the
  rest are `-1`.
- Left/Right cycles only the **reached** tabs and selection follows:
  `Plan → Preflight → Approve → Copy → Scan → Plan`. In the empty state the
  unreached tabs are `disabled` and are skipped.
- Reached-but-inactive vs unreached is conveyed by `disabled` (AX
  `disabled: false` vs `true`), so a reached tab is announced as a normal,
  selectable tab; an unreached one as disabled. The writing stage's hidden
  text survives in the accessible name: `Copy (writes to disk)`.

### Transfer dock — FAIL

- The dock is `<aside class="dock" aria-label="Active transfer">`, AX role
  `complementary`, name "Active transfer".
- **It has no live semantics** — no `aria-live`, no `role="status"`, no
  `role="alert"`. When a transfer starts (dock appears) or settles (dock
  clears), nothing is announced; verified by adding a running job (dock
  present) and removing it (dock unmounts, no live region reports it). Filed
  #198.
- **Cancel is announced as bare "Cancel"** — unlike the Activity table, which
  uses `jobRowLabel` to say `Cancel transfer <id>`. Filed #199.
- The progress meter is present in the tree
  (`progressbar "Transfer progress for <id>"`); the dock's `View` button is
  named.

### Banners and state chips — PASS on state-in-text, FAIL on announcement

- **Chips**: the SR-10 glyph is `aria-hidden="true"` and the state is the
  chip's text (`running`, `succeeded`, `missing`, …). The state is therefore
  announced as words and does not depend on the glyph or hue. PASS.
- **Banners**: the glyph is `aria-hidden`; the state is a text label
  (`Error:`, `Incomplete:`, …). Reading order is fine. PASS.
- **Announcement**: only `banner--danger` is `role="alert"`. `ok`, `warn`,
  `attention` and `info` banners have no live semantics, so banners inserted
  in response to an action ("Preflight passed", "Plan superseded", "Start is
  locked", export results) are not announced on appearance. Filed #200.

### Plan table and Activity table — PASS, with observations

- Headers are `<th>` in `<thead>` in every table, so column association is by
  position and is exposed; no `scope` attributes are used, which is correct
  for single-tier headers.
- Out-of-order row context is carried by the names, not by the column:
  - Activity actions: `Cancel transfer <id>`, `Resume transfer <id>`,
    `Receipt transfer <id>` (`jobRowLabel`).
  - Activity meter: `aria-label="Progress for transfer <id>"` with
    `aria-valuetext` (`25%`, `complete`, `held at 25% — waiting for you`).
  - State cell: chip text plus the current step.
- Observations (not filed — not conformance defects):
  - The `<table>` elements have no accessible name; each sits under an `h2`
    that names its panel, so context is present but the table itself is
    unnamed.
  - Headers render uppercase (`text-transform: uppercase`), which Chromium
    bakes into the computed name, so headers announce as `COMMAND`, `STATE`
    (a styling choice, not a barrier).

### Focus visibility (incl. R-10a) — PASS

- Every Tab stop on all ten route states had a visible `2px` outline; zero
  stops with `outline-width: 0px` or a transparent colour.
- Two ring colours are in use, both correct for their surface:
  `rgb(84, 164, 231)` (`--c-accent-interactive`) on dark surfaces, and
  `rgb(15, 22, 34)` (`--c-on-accent`) **on the active stage tab** — the R-10a
  filled pill. The accent-on-accent ring would have been invisible; the
  on-accent override works.
- The skip link is the first Tab stop and moves focus to `main#content`.

### Additional checks — PASS / observation

- Heading outline is `h1` per screen, `h2` per panel — no skipped ranks.
- The sidecar readout is `role="status"` with
  `live: polite, atomic: true, relevant: additions text`.
- The Activity filter is `role="radiogroup"` with named radios and the search
  box is `searchbox "Search jobs"` — but the group has **no roving tabindex
  and no Arrow keys** (all five radios are `tabindex 0`), which contradicts
  the announced role. Filed #201.

---

## Defects filed

| issue | summary |
| --- | --- |
| #198 | transfer dock is not a live region; appearance and clearing are not announced |
| #199 | dock Cancel is announced as bare "Cancel" |
| #200 | non-danger banners are not announced when they appear (WCAG 4.1.3) |
| #201 | segmented filter announces `radiogroup` but has no roving tabindex or arrow keys |

None of these were fixed in this pass.

## Not covered by this pass

- **VoiceOver speech / a real screen-reader session.** See above. This is the
  central limitation.
- **NVDA / Narrator and Windows rendering** — #148, needs a Windows host.
- **Forced-colours / real Windows High Contrast** — not exercised here.
- **OS text scaling / zoom above 100%** — not exercised here (overlaps #101;
  the type scale is now `rem`).
- **The typed-move confirmation dialog** — not reachable from the seeded data;
  only its static markup (`role="alertdialog"`, `aria-modal`,
  `aria-describedby`, focus trap) was re-read, not exercised.
- **The live "sidecar unreachable" path** — the sidecar came up.
- **A packaged build** — this was the built renderer in a checkout, not
  `electron-builder` output.
