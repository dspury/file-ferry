"""Allow ``python -m media_mate.service``.

The Electron shell spawns the sidecar with ``python -m
media_mate.service`` (see ``desktop/electron/main.ts``). This module is
the entry point that makes that invocation work.
"""

from media_mate.service.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
