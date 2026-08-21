"""Allow ``python -m file_ferry.service``.

The Electron shell spawns the sidecar with ``python -m
file_ferry.service`` (see ``desktop/electron/main.ts``). This module is
the entry point that makes that invocation work.
"""

from file_ferry.service.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
