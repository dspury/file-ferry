# Road to production

The complete remaining work, in order. **Every numbered item is one PR.**
Branch each off `main` directly — do not stack. Stop and report after each.

Two documents govern the work and this one does not repeat them:

- `docs/UI-REVISION-SPEC.md` — standing rules SR-1..SR-10 and items R-1..R-8.
  The rules bind every item, including ones that do not mention them.
- `docs/BRAND-STYLE-GUIDE.md` — palette, tokens, identity.

**SR-4 applies to everything here.** CI sets `ELECTRON_SKIP_BINARY_DOWNLOAD`
and never loads Electron, so a green desktop job says nothing about how the
app looks or whether it boots. Run it.

---

## Where things stand

| phase | state |
| --- | --- |
| P1-P5 engine | complete — durable verified transfer with an item ledger |
| P6 UI bridge | complete — B1 #158, B2 #161, B3 #164 |
| P7 desktop shell | in progress — this document |
| Packaging | Stage A landed (#167); unsigned local builds work |

Merged from the UI spec: R-3 (#172), R-5 and R-6 (#174), R-8 (#171).
Remaining: R-1 (folded into R-7), R-2, R-4, R-7.

---

# Track A — the UI, sequential

A-1 through A-3 all touch `styles.css`. Do them in order, one at a time,
merging each before starting the next.

## A-1 — R-4: the persistent transfer dock

Spec: `UI-REVISION-SPEC.md` R-4. Reference: `docs/ui-refs/dock.jpg`.

**This comes before the reskin.** It is structural — it changes what the
content area's height is — and a reskin done first would have to be redone
around it.

**Acceptance** is in the spec. Two additions:

- Cancel must route through the same gate the Transfer screen uses. The
  dock never gets a privileged path to a destructive action.
- It must not be possible for the dock to show a transfer as running after
  the job has settled. Drive a real job to completion and watch it clear.

## A-2 — R-2: minimum width and breakpoints

Spec: `UI-REVISION-SPEC.md` R-2, including the measured overflow table.
Reference: `docs/ui-refs/` (the narrow-width behaviour is described, not
pictured — the narrow reference predates the current nav).

R-6 already removed the title/subtitle collision the spec measured at
760px; re-measure rather than trusting the old table. The nav is now 9
entries in 3 groups, which changes the collapse behaviour the spec
describes.

**The dock (A-2) must survive every width ≥ 600.** That is why A-1 comes
first.

## A-3 — R-7: the surface and material migration

Spec: `UI-REVISION-SPEC.md` R-7, governed by SR-5 through SR-10.
References: `docs/ui-refs/transfer.jpg`, `dashboard.jpg`, `dock.jpg`.

**This is the largest item in the project.** It is also the one where the
references are directional rather than literal — their known inaccuracies
are listed in the spec's "Reference images" section. Build to the tokens.

**R-1 is folded in here.** The left-edge colour bars on `.stat`, `.banner`
and `.nav__item` go as part of this pass, under SR-1. The spec's R-1 section
still holds the selector-by-selector detail; use it.

Because of its size, **A-3 may be split into more than one PR** — that is
the one exception to one-item-one-PR. If you split it, split by surface
(tokens and panels / tables and lists / states and banners), not by screen.

**Acceptance:** SR-5..SR-10 hold across every screen, and the brightness
floor in SR-7 is met — measure it, do not judge it by eye.

---

# Track B — correctness, independent

None of these touch `styles.css`, so they can be done at any point, in any
order, without conflicting with Track A.

## B-1 — #123: an unpackaged Electron run cannot load the renderer

`electron/main.ts` picks the renderer source from `app.isPackaged` alone, so
`electron .` from a checkout always tries the Vite dev server and fails hard
without it. Add an explicit override.

This matters more than its age suggests: every SR-4 verification in this
document depends on booting a checkout.

## B-2 — #138: no `"type": "module"` in `desktop/package.json`

Vite 8 warns about it. Adding it changes how every `.js` in the package is
interpreted — verify the Electron main process and preload still load, both
unpackaged and packaged. Not a one-line change.

## B-3 — #101: close it

Every `--fs-*` token is already `rem` on main (`styles.css:192-198`), and
#162 pins the scale. The issue is resolved in fact. Verify text-only zoom
actually scales, then close it with that evidence. **No code expected** — if
something does not scale, that is a finding, report it.

## B-4a — eslint 10: drop `eslint-plugin-react`, add `@eslint-react`

**Decided.** #150 and #151 are the same eslint major and go together as one
PR. The only thing blocking them is `eslint-plugin-react`.

Upstream is not going to fix this. `eslint-plugin-react@7.37.5` is the
**latest published version** — there is no newer release — and it peers
`eslint: ^3 || … || ^9.7`. Holding the upgrade waits on something that is
not queued.

Nothing else in the toolchain objects:

| package | eslint peer | blocks 10? |
| --- | --- | --- |
| `eslint-plugin-react-hooks` 7.1.1 | `… \|\| ^10.0.0` | no |
| `@typescript-eslint/*` 8.70.0 | `^8.57 \|\| ^9 \|\| ^10` | no |
| `eslint-plugin-react` 7.37.5 | `… \|\| ^9.7` | **yes** |

**Do:** remove `eslint-plugin-react`, keep `eslint-plugin-react-hooks` (it
is the valuable one — `rules-of-hooks` and `exhaustive-deps`), and add
`@eslint-react/eslint-plugin` (5.19.1, peers `eslint: '*'`, TypeScript-first,
actively maintained) to replace what is lost.

**What is lost is less than it looks.** `eslint.config.js:69-70` already
disables `react/react-in-jsx-scope` and `react/prop-types`, the two largest
rules in `recommended`. Of the remainder, most is class-component era
(`no-direct-mutation-state`, `no-is-mounted`, `no-string-refs`,
`require-render-return`, `no-find-dom-node`) and irrelevant here, and several
more (`jsx-no-undef`, `jsx-no-duplicate-props`, `jsx-uses-vars`) are already
caught by TypeScript in strict mode.

The one rule with unique value is **`react/jsx-key`** — TypeScript does not
catch a missing `key` in a `.map()`, and there are ~60 `.map(` sites in the
`.tsx` files. It reports nothing today (the lint job is green on main), so it
guards against a future mistake rather than holding a current bug back.
`@eslint-react`'s `no-missing-key` covers it.

**The config header comment is now wrong** — it says eslint is pinned to 9.x
because of this plugin. Update it to record what happened instead.

**Two PRs, not one.** The bump and the swap land together in one PR; any
source changes the new ruleset demands go in a **separate follow-up**. The
new plugin will surface findings the old ruleset never produced — that is
expected and is not a reason to weaken the config. Do not silently fold
fixes into the dependency bump, and do not reach for `--legacy-peer-deps`.

**Acceptance:** eslint 10 installs with no `ERESOLVE` and no
`--legacy-peer-deps`; `npm run lint` passes; a deliberately unkeyed `.map()`
is reported by the new plugin (prove the replacement works, do not assume
it); the stale config comment is corrected.

## B-4b — TypeScript 7 (#149): hold, and say why

**Blocked upstream, genuinely.** `@typescript-eslint` 8.70.0 — the latest —
peers `typescript >=4.8.4 <6.1.0`. TypeScript 7 is outside it, and
`typescript-eslint` is the type-aware lint engine for the whole codebase, so
dropping it is not an option the way dropping `eslint-plugin-react` is.

**Do not force it.** Leave #149 open. Add a comment recording the exact peer
range and that the block is `@typescript-eslint`, not the codebase, so the
next person does not re-derive it. Re-check when `typescript-eslint` ships TS
7 support.

Nothing is broken by waiting — the version is merely old.

## B-5 — R-9: stop surfacing CLI-only options in the desktop

**Decided: the desktop does not surface CLI features.**

Remove the Settings → "Organize command" panel and the three fields behind
it from the desktop only — the section, its form state, and the
`organizeTemplate` / `organizeMode` / `organizeOnConflict` params on the
desktop settings call.

**Do not touch the config itself.** `[organize]` stays in `config.py`,
`models.py` and `config_hash()`, and the CLI (`organize.py`, `cli.py`) and
the TUI (`tui.py:1044-1057`) keep reading and editing it. They are the
surfaces those settings belong to. Only the desktop stops exposing them.

**Acceptance:** no desktop path reads or writes the three values; `ferry
organize` and the TUI behave identically before and after; `config_hash()`
unchanged, so existing run provenance is not invalidated.

## B-6 — Remove `OffloadRunner`

**Decided: the runner goes; the offloading capability stays.**

The capability already lives in the Transfer workspace — a camera card is a
source type, `source.inspect({kind: 'card'})` runs inspection, the
"Keep the card" safety statements render, and the durable `TransferRunner`
does the work. That is offloading, on the engine with preflight, an approval
gate and an item ledger. Nothing about it depends on `OffloadRunner`.

Remove: `application/offload.py`, the import and `register_runner("offload")`
in `service.py:33,959,968`, and the now-unreachable
`intake.createSession` session-kind path if nothing else reaches it.

**Two things to get right:**

1. **Do not touch `source.inspect`'s `kind`.** `"card" | "existing_media"`
   (`protocol.py:783`) is the *source* axis and is what the capability runs
   on. The `"offload" | "existing_folder"` literal at `protocol.py:355` is
   the intake *session* axis — a different thing that happens to share a
   word. Confusing them removes the feature.

2. **Orphaned jobs must explain themselves.** An existing `offload` job in
   a user's database survives the removal. `scheduler.py:125-127` already
   handles a missing runner safely — it transitions to `needs_attention`
   rather than crashing — but it does so *silently*, so the operator sees a
   job stuck in "needs attention" with no reason. Make that path record why,
   so a withdrawn runner reads as "this job kind no longer exists" rather
   than as an unexplained stall.

**Acceptance:** a camera-card offload still completes end to end through the
Transfer workspace, verified by running it — not by reading the diff; an
`offload` job seeded into a test database lands in `needs_attention` with a
stated reason; no `OffloadRunner` reference remains.

---

# Track C — accessibility, after A-3

Do not start these before the reskin lands. Auditing a UI that is about to
be restyled wastes the audit.

## C-1 — #95: the screen-reader pass

No VoiceOver pass has ever been run against the reskin. This is the issue
that most plausibly should gate a release and currently does not.

Cover, at minimum: the nav and its three groups, the stage tab bar, the
transfer dock, every banner and state chip, and the plan table. Record what
was tested and what was found — a pass with no written record is not a pass.

## C-2 — #148: Windows verification

NVDA/Narrator, backslash path rendering, real forced-colours. Needs a
Windows machine; if none is available, say so and leave the issue open
rather than closing it on inference.

---

# Track D — production readiness

Sequential, and each depends on the one before.

## D-1 — §12.1: disposable local pilot

A full offload → verify → receipt cycle on the packaged app against
throwaway data. Proves the packaged bundle does real work, which Stage A
explicitly did not test (A4 verified the shell only — no files were
transferred).

## D-2 — §12.2: the real storage matrix

**Argue for doing this as early as Track D allows.** It is the step most
likely to send work back into the engine, and every day it is deferred is a
day of UI work built on an unproven base.

Required, on real hardware, not fixtures: a directory of ≥10,001 entries; a
single file ≥10 GiB; a sustained transfer ≥2 hours; real mid-transfer
cancellation; real network-volume disconnect. Everything verified so far has
been injected failures against byte-sized fixtures on a local disk.

## D-3 — §12.3: operational documentation

What an operator does when a transfer needs attention, how to read a
receipt, where the data lives, how to recover from a crash mid-transfer.

## D-4 — signing and notarization

Needs an Apple Developer ID and notarization credentials. **The operator
supplies these; do not ask for them and do not handle them.** The unsigned
local path (`scripts/package-mac-local.sh`) stays as-is for development.

## D-5 — §13: final handoff

---

# Standing blockers

**R13 has not fired in many consecutive runs. That is not the same as being
fixed.** Treat it as live until something proves otherwise.

**Two green suites have covered unreachable code in this project** — P5 over
RPC with no caller, and B3's approval stage with nothing invoking it. Both
times the tests asserted existence rather than end-to-end function. When
adding tests, ask what caller reaches the code.

---
