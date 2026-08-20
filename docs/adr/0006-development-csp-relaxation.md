# ADR-0006 — Development-only Content-Security-Policy relaxation

- **Status:** Accepted
- **Date:** 2026-08-20
- **Amends:** [ADR-0001](0001-desktop-shell-architecture.md) (the renderer
  security boundary; the frozen `SECURITY` options are unchanged)

## Context

`electron/security.ts` declares the renderer's Content-Security-Policy and
states that relaxing it requires a new ADR. Two problems were found while
making the desktop shell boot for the first time.

**1. The policy was never enforced as written.** The directive list was passed
to Electron as a `string[]`:

```ts
'Content-Security-Policy': ["default-src 'self'", "script-src 'self'", ...]
```

Electron sends a `string[]` response header as *one header line per element*,
and multiple `Content-Security-Policy` headers are multiple independent
policies — a resource must satisfy every one of them. The shipped app was
therefore running ten single-directive policies rather than one ten-directive
policy. `default-src 'self'` stood alone and vetoed every relaxation sitting
beside it: `img-src 'self' data:` did not admit data URIs, and `script-src` was
absent from the `default-src` policy so scripts fell back to it. The effective
policy was stricter than the declared one, in ways nobody had chosen.

**2. The declared policy makes `npm run dev` render an empty window.** Vite's
React plugin installs its refresh preamble as an inline `<script>` and reaches
the dev server over a websocket. `script-src 'self'` blocks the preamble, so
React never mounts: the window loads, the preload bridge is present, and the
page stays blank with `@vitejs/plugin-react can't detect preamble` on the
console. The desktop UI could not be developed at all.

The policy is delivered twice, and both copies must allow a resource:

- as a response header from `applyContentSecurityPolicy()`, which covers the
  Vite dev server's `http://` responses;
- as a `<meta http-equiv>` element in `renderer/index.html`, which is the only
  copy that applies to the packaged renderer — it loads over `file://`, where
  `webRequest.onHeadersReceived` does not fire.

## Decision

**One policy per header.** `cspHeaderValue()` joins the directives with `"; "`
and the header is sent as a single-element array. The declared policy is now
the enforced policy.

**Two named policies.** `PRODUCTION_CSP` is what every packaged build runs
under and is unchanged in content. `DEVELOPMENT_CSP` adds exactly two things:
`'unsafe-inline'` in `script-src`, and `ws://localhost:5173` /
`http://localhost:5173` in `connect-src`. It adds no `unsafe-eval` and no
wildcard.

**The dev policy is unreachable in a packaged build.** `main.ts` selects it
with `isDev`, which is `!app.isPackaged`. `vite.config.ts` applies the matching
relaxation to the `<meta>` copy through a `transformIndexHtml` plugin marked
`apply: 'serve'`, so `vite build` emits the strict policy untouched.

**`frame-ancestors` is header-only.** A `<meta>` element cannot deliver it —
the browser ignores it and logs an error — so it lives in `PRODUCTION_CSP`
alone and is excluded from the page's copy.

Four tests in `desktop/tests/security.test.ts` hold this in place: the header
is a single joined policy; the shipped policy names no localhost origin and no
inline/eval script source; the dev policy adds only the two intended
relaxations; and the `<meta>` copy matches `PRODUCTION_CSP` minus
`frame-ancestors`.

## Consequences

**Positive.** The shipped policy now means what it says, including the
`img-src data:` allowance that was silently dead. The renderer is developable.
The two policies cannot drift apart unnoticed, and neither can the header and
the `<meta>` copy.

**Negative.** A development session runs with inline script permitted. It is a
weaker boundary than production, on a locally-served page, and it is the
standard cost of a hot-reloading dev server. The relaxation is one `git grep`
away from being audited (`DEVELOPMENT_CSP`).

**Neutral.** Correcting defect 1 makes the effective production policy
*less* strict than what shipped before, because the accidental single-directive
policies were over-restrictive. It matches the policy that was always intended
and reviewed.

## References

- [ADR-0001](0001-desktop-shell-architecture.md) — renderer security boundary
- `desktop/electron/security.ts` — `PRODUCTION_CSP`, `DEVELOPMENT_CSP`, `cspHeaderValue`
- `desktop/vite.config.ts` — `ferry-dev-csp` plugin (`apply: 'serve'`)
- `desktop/renderer/index.html` — the `<meta>` copy for the `file://` renderer
