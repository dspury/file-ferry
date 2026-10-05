# Pull request

<!--
One piece of work per pull request, branched from `main`, not stacked.
Do not merge, tag, or publish on your own initiative.
-->

## What this changes

<!-- What, and why. Link the issue it closes, if there is one. -->

## How it was verified

<!--
The important box. What you ran, and what you observed — not just what you
changed. "Fixed by reading the diff" is not verification.

  [ ] ruff check . && ruff format --check . && mypy src && pytest
  [ ] (desktop changes) npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
  [ ] ./scripts/secret-scan.sh all
  [ ] Ran the thing, not just the test for the thing
-->

Note that CI never loads Electron (`ELECTRON_SKIP_BINARY_DOWNLOAD`), so a green
desktop job says nothing about how the app looks or whether it boots. If you
changed anything you can see, please attach a screenshot or say plainly that
you did not run it.

## What is still unproven

<!--
Anything you could not verify in this environment, and why. Hardware, a real
network share, a specific platform, a long soak. An honest gap is useful; a
confident claim that turns out to be wrong costs more.
-->

## Notes for the reviewer

<!--
Anything that makes this harder to review than it needs to be: a decision you
had to make, a trade-off you took, something you deliberately did not do.
-->
