# Security and secret handling

## Reporting a vulnerability

**Report privately. Do not open a public issue for a security problem.**

ferry handles local media paths, file contents, and an audit database. If you
have found something that lets one local user read or write another user's
data, escape a sandbox boundary, or execute code through a crafted media file
or project, report it to the maintainer directly at **security@dspury.com**.

Please include: what you found, how to reproduce it, the affected version
(`ferry --version`, or `app.diagnostics` for the packaged app), and your
platform. You should get an acknowledgement within a few days. If you need
the report to stay quiet while it is investigated, say so and it will.

Note that the maintainer is a single person, so a realistic response time is
"eventually" rather than "within 24 hours" for non-critical reports. Reports
of credential exposure or data loss are treated as urgent.

Once a fix is ready, please keep the details private until it is released so
that users have a version to upgrade to. Credit will be given in the release
notes unless you would rather not be named.

Everything else — bugs, packaging questions, feature requests — belongs in a
public issue or a discussion. This section is only for things that should not
be public yet.

## Secret scanning

Live credentials, private keys, bearer values, recovery material, and
secret-bearing production exports do not belong in this repository, whether it
is private or public.

Install Gitleaks and run:

```bash
./scripts/secret-scan.sh staged
./scripts/secret-scan.sh all
```

Enable the versioned local pre-commit hook with:

```bash
git config core.hooksPath .githooks
```

The hook fails closed when Gitleaks is unavailable. CI downloads the pinned
Gitleaks release, verifies its upstream checksum, and scans both the working
tree and complete fetched history with read-only repository permissions.

Do not bypass a failed scan. If a finding is real, revoke or rotate it first,
then remove the material and rescan. Do not copy a credential into an issue,
pull request, log, or remediation note. Any allowlist exception must be narrow
to the exact rule, path, and proven synthetic or false-positive value.

Before making a private repository public, also review every branch and tag,
Git LFS and submodule content, release and Actions artifacts, generated
archives, source maps, notebooks, fixtures, logs, screenshots, workflows, and
private topology. Repeat the scan from a fresh clone and obtain repository-owner
approval before changing visibility.
