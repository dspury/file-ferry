# Contributing to file-ferry

Thanks for considering it. ferry is a CLI and terminal UI for the
infrastructure underneath video post-production — probing camera cards,
organising them, generating proxies, building DaVinci Resolve projects, and
verifying backups — with every step written to a local SQLite audit trail.

No API keys. No cloud. Just FFmpeg, your local SQLite, and (optionally)
DaVinci Resolve.

## What state the project is in

Read this before you pick something up, so you know what you are walking into.

The **Python engine is mature and heavily tested**: ~1,039 tests, 86% line
coverage, `mypy` clean, and the correctness work that mattered has been found
and fixed through real use — SMB publishing, crashed-job recovery, ffmpeg
discovery. The tracker is currently empty.

The **desktop app is a working shell with unfinished production validation.**
Packaging works, but the real-hardware storage matrix (gates 5 and 6: a
sustained multi-hour transfer, and a real network disconnect) has not been
completed. Do not read the passing test suite as "production-validated."

There is **no PyPI release yet**, and the packaged macOS app is **unsigned**,
so Gatekeeper will refuse the first open. Right-click → Open gets past it.
Both are deliberate, both are documented in [`docs/RELEASE.md`](./docs/RELEASE.md).

Contributions against the Python engine, the CLI, the TUI, and the docs are
all useful today. Large desktop-UI work is more likely to collide with
in-flight design decisions than to be welcomed — see
[`docs/UI-REVISION-SPEC.md`](./docs/UI-REVISION-SPEC.md) and
[`docs/ROAD-TO-PRODUCTION.md`](./docs/ROAD-TO-PRODUCTION.md) before starting.

## Getting set up

**You will need:** Python 3.11+, FFmpeg on your `PATH`, and Node 22.18+ (for
the desktop app only). macOS and Linux are the supported platforms.

```bash
git clone https://github.com/dspury/file-ferry.git
cd file-ferry

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Enable the versioned pre-commit hook, which runs the secret scan over staged
changes and **fails closed** if Gitleaks is unavailable:

```bash
git config core.hooksPath .githooks
```

To try it without your own media, there is bundled sample footage and a
walkthrough in [`examples/`](./examples/):

```bash
bash examples/run-demo.sh
```

### The desktop app

```bash
cd desktop
npm ci
npm run build
```

Development runs against your workspace virtualenv rather than a frozen
sidecar, so Python source changes take effect without a rebuild.

## The gates

CI runs exactly these. Run them before you open a pull request — they are the
same commands, not an approximation of them.

**Python** (from the repo root, venv active):

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=file_ferry --cov-report=term-missing
```

**Desktop** (from `desktop/`):

```bash
npm run lint          # eslint + oxlint (anti-slop)
npm run format:check  # prettier
npm run typecheck
npm test
npm run build
```

**Secret scan** (fails closed if Gitleaks is missing):

```bash
./scripts/secret-scan.sh staged   # what the pre-commit hook runs
./scripts/secret-scan.sh all      # working tree and full history
```

Two things about the lint setup that will otherwise surprise you. First, the
`desktop/` tree is linted by a custom `anti-slop` oxlint plugin that is
stricter than stock oxlint — it rejects runtime `typeof` narrowing, object
parameters, `unknown` parameters and a few other patterns, and it requires a
`SAFETY:` comment on any type assertion. Read
`desktop/tools/oxlint/anti-slop/` when a rule fires. Second, `ruff format` owns
Python formatting and `prettier` owns the desktop tree; do not hand-format
around either.

**The secret scan is not optional and is not to be bypassed.** If it finds
something real, revoke or rotate the credential *first*, then remove it and
rescan. Do not paste a credential into an issue, a pull request, a log, or a
comment explaining a fix. See [`SECURITY.md`](./SECURITY.md).

## Tests

Add tests with the code, not after. Two failure modes this project has already
hit, both worth knowing about:

- **A green suite has covered unreachable code here before.** P5 was tested
  over RPC with no caller; B3's approval stage was tested with nothing
  invoking it. Both times the tests asserted that something *existed* rather
  than that it worked. When you add a test, ask what caller reaches the code.
- **A check that cannot fail is worse than no check.** `desktop/scripts/check-sidecars.ts`
  exists because electron-builder exits 0 when a packaged arch is missing its
  sidecar, and a green build shipped a `ferry.app` that died on first launch.
  If you write a guard, mutate it and watch it go red before you believe it.

For desktop work, note **SR-4**: CI sets `ELECTRON_SKIP_BINARY_DOWNLOAD` and
never loads Electron, so a green desktop job says nothing about how the app
looks or whether it boots. Run it.

## Pull requests

- Branch from `main`. Do not stack branches.
- One piece of work per pull request, and say what it is in the title.
- Describe what you verified and how, not just what you changed. "Fixed by
  reading the diff" is not verification; say what you ran.
- If something in your change cannot be verified in this environment, say so
  explicitly and name what is unproven. An honest gap is useful; a confident
  claim that turns out to be wrong costs more.
- Update the docs your change makes wrong. `SPEC.md`, `README.md` and
  `docs/ROAD-TO-PRODUCTION.md` are load-bearing, not decoration.
- If a gate fails, fix the gate or explain it. Do not weaken a check to make a
  build green.

Do not open a pull request from an agent that has not been told the work is
finished. Do not push, merge, tag, or publish on your own initiative — say
what you would like to happen and let a human decide.

## Reporting bugs

Open an issue with the `.github` bug template. What helps most:

- The ferry version (`ferry --version` or `app.diagnostics` for the app), your
  OS, and whether you installed from source or from a packaged build.
- The command you ran and what happened instead.
- The receipt or audit entry, if one exists — `docs/RELEASE.md` documents
  where the data lives. Receipts are the fastest route to a real diagnosis.
- Whether it reproduces with the bundled sample data in `examples/`.

## Scope and conduct

Scope: this is a post-production tool. Please keep contributions inside it.

Accessibility: the desktop app's keyboard and labelling work is done and
maintained, but **screen-reader support has been explicitly declined by the
maintainer and is out of scope.** Issues requesting a VoiceOver or NVDA pass
will be closed. This is a decision, not an oversight — please do not
re-litigate it in an issue. Accessibility work that is not about speech output
(focus order, labelling, contrast, keyboard traps) is still welcome.

`SECURITY.md` covers how to report a security issue privately. Please do not
open a public issue for one.

## Licence

MIT — see [`LICENSE`](./LICENSE). By contributing you agree your work is
published under it.
