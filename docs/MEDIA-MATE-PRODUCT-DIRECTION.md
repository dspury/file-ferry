# Media-mate Product Direction — Local Media Intake Workstation

> **Status:** Draft for discussion
> **Date:** 2026-08-11
> **Scope:** Product and architecture direction after v0.2.4; no application
> behavior changes are specified as shipped by this document.

## 1. Purpose and relationship to the current specification

Media-mate v0.2.4 is a local CLI and Textual TUI for probing, organizing,
proxying, verifying, and recording media operations. Its current `SPEC.md`
remains the source of truth for shipped behavior.

This document proposes the next product shape: a local-first desktop workstation
for safely bringing media into a project, organizing received media, and
understanding the state of that media over time. It is deliberately a direction
document, not an implementation plan. Decisions marked **Open** require a
separate, implementation-ready specification before code changes begin.

## 2. Product thesis

> **Media-mate tells a small production what media exists, where it lives,
> whether it is safe, and what it is ready for.**

Media-mate should serve solo creators and small post-production teams who work
with local drives and need trustworthy media operations without adopting a
cloud-hosted digital asset manager. Its value is not a prettier file browser;
it is durable proof of how physical media entered, moved through, and became
ready for a project.

The product should become the local media-intake workstation that sits between
camera cards, drives received from collaborators, working storage, backup
storage, proxy generation, and NLE handoff.

## 3. The three core workflows

### 3.1 Verified card offload

**User need:** "I have a camera card. Can I copy it safely, make the edit-ready
media, and know when it is safe to format the card?"

The default offload preserves the camera-card directory structure. It creates
one or more independently verifiable destination copies, records a durable
receipt, and may enqueue proxy generation afterward. Media-mate must never say
a card is safe to format until the configured offload policy is satisfied.

An offload is not an organize operation. A card's original hierarchy and source
identity are evidence and must remain reconstructable from the project record.

### 3.2 Existing-folder adoption and organization

**User need:** "Another editor gave me this drive. I need to bring the material
into my preferred project structure without losing track of where it came from."

The user selects an existing folder or mounted drive, inspects its inventory,
chooses a project and named organization profile, reviews a concrete plan, and
then copies, moves, or links media according to that explicit policy.

This is not a lesser version of card offload. It accepts less certain source
information, but it must still record the original root, selected profile,
planned and completed file operations, and any collisions, skips, or failures.

### 3.3 Project reconciliation and handoff

**User need:** "What is missing, changed, offline, unprotected, or not ready
for editorial?"

Media-mate compares known project media against filesystem reality. It surfaces
replica health, proxy readiness, missing media, verification drift, and failed
operations. It can export a clear project or handoff receipt for another editor
without requiring them to adopt the same application.

## 4. Product boundaries

### In scope

- Local drive, folder, and removable-media intake.
- Verified copies, checksums, manifests, and reconciliation.
- Project-scoped organization profiles and explicit transfer policies.
- Proxy generation and honest NLE handoff status.
- A desktop application for ordinary daily use, with the CLI and TUI retained.
- A local SQLite-backed media ledger and exportable, portable receipts.

### Explicitly out of scope for the first desktop product

- Cloud-hosted storage, user accounts, or a hosted web application.
- Editing, transcoding decisions beyond proxies, or replacing an NLE.
- AI-based content description, auto-selects, or creative scoring.
- Team permissions, real-time collaboration, and review workflows.
- A generic consumer photo library or broad enterprise DAM.

These may become integrations later, but they must not dilute the core promise
of safe local media intake and traceable organization.

## 5. Shared domain model

The two intake paths should be different policies over one common model, not
two disconnected pipelines.

| Concept | Definition |
| --- | --- |
| **Project** | A named production workspace with organization, proxy, and protection policies. |
| **Source** | A card, mounted volume, or selected folder supplied to Media-mate. |
| **Intake session** | A user-visible operation that adopts or offloads one source into a project. |
| **Asset** | A known media file plus its durable identity and observed metadata. |
| **Logical clip** | A future grouping of one or more physical files that editorial treats as one clip. |
| **Replica** | A known physical location of an asset, such as a card, working drive, or backup drive. |
| **Derivative** | A generated proxy or later supported output tied to a source asset. |
| **Organization profile** | A named, versioned rule set that turns an intake source into a project layout. |
| **Operation receipt** | An immutable summary of the plan, commands/results, warnings, failures, and verification state. |

File paths are locations, not identities. Initial identity can use checksums plus
file metadata; the exact duplicate and logical-clip strategy remains **Open**.

## 6. Workflow contracts

### 6.1 Every destructive or expensive operation follows one pattern

```text
Plan -> Review -> Execute -> Verify -> Receipt
```

- **Plan:** enumerate the affected files, required space, destinations, policy,
  collisions, and any unsupported media before writing.
- **Review:** show the user the concrete change, not a vague confirmation.
- **Execute:** perform a resumable, observable job and preserve partial-failure
  evidence.
- **Verify:** apply the selected verification policy without silently replacing
  a known-good baseline.
- **Receipt:** retain a readable and exportable record of the completed work.

`Move` must remain opt-in and visually distinct from copy or link operations.
No UI path may hide deletion, overwrite, collision resolution, or baseline
acceptance behind a default action.

### 6.2 Offload policy

An offload policy declares the required destinations and verification level.
For example, a project may require one working replica and one backup replica
before showing "safe to format." The policy must show its unmet conditions
plainly; a green transfer bar alone is not enough.

The first desktop version should preserve source structure by default. A
separate, opt-in post-offload organization step can derive the user's preferred
working layout while retaining the original offload replica.

### 6.3 Organization policy

Organization profiles are project-scoped, named, and previewable. They should
support the existing source-structure-preserving behavior and future reusable
templates, but cannot mutate material until the user reviews the proposed tree.

When adopting a collaborator's drive, the receipt must identify the supplied
source even if the user later chooses to move material into their own layout.

## 7. Desktop application experience

The TUI is a valuable power-user, offline, and automation-adjacent surface. It
should remain supported. The desktop application becomes the primary daily-use
interface because most users need visual planning, progress, and media health
at a glance rather than terminal operation.

### 7.1 Primary navigation

| View | Primary question it answers |
| --- | --- |
| **Home** | What needs attention: active work, connected sources, incomplete protection, failed jobs, and proxy readiness? |
| **Ingest** | How do I safely offload this card or source into this project? |
| **Organize** | How will this existing media look under my selected project profile? |
| **Projects** | What assets, replicas, derivatives, warnings, and receipts belong to this project? |
| **Activity** | What is currently running, what finished, and what exactly happened? |

### 7.2 Core interaction principles

- Drive discovery is informative, never an automatic promise that the drive is
  a camera card.
- The default UI language uses operational truth: `copied`, `verified`,
  `missing`, `needs review`, and `safe to format`—not generic success states.
- Progress is useful only when it includes work completed, remaining work,
  current stage, failures, and safe cancellation behavior.
- Users see both the preferred project layout and the retained source/provenance
  record.
- The app should work fully offline and avoid requiring an account.

## 8. Proposed application architecture

The existing capability modules—probe, organize, proxy, verify, Resolve, and
logging—should remain the source of domain behavior. Do not reimplement them in
the desktop frontend.

Before a desktop shell is introduced, extract a shared application layer that:

- creates plans and durable jobs;
- applies project and intake policies;
- invokes the existing capability modules;
- persists job state, receipts, and project media state;
- exposes narrowly scoped local commands for CLI, TUI, and desktop clients.

```text
CLI / Textual TUI / desktop application
                  |
          shared application and job layer
                  |
probe / organize / proxy / verify / Resolve / audit storage
                  |
         filesystem / FFmpeg / SQLite / Resolve
```

The desktop app uses Electron with a React/Vite frontend and local Python
sidecar. Electron is the preferred shell because it supports a cross-platform
desktop product while fitting the team's existing desktop experience. The
renderer remains separate from filesystem and job ownership; Electron main
supervises the sidecar and provides a narrow, secure bridge. Tauri and a native
Swift shell are deferred alternatives, not parallel implementation targets.

Any local service boundary must bind privately, avoid remote exposure by default,
and define authentication/ownership before accepting requests outside the
desktop process.

## 9. Delivery sequence

### Phase A — operational truth

Strengthen the existing core before expanding presentation:

- Complete real-media validation for offload, checksum, proxy, and database
  failure paths.
- Define safe offload policy and the exact meaning of `safe to format`.
- Make organization plans and receipts explicit reusable concepts.
- Resolve known provenance gaps such as logical/spanned clips and unsupported
  RAW-codec handling to the degree needed for truthful operation.

### Phase B — project and intake foundations

- Add project records, sources, intake sessions, replicas, and receipt storage.
- Support card offload and existing-folder adoption as policies over shared jobs.
- Introduce project-scoped organization profiles and reconciliation.
- Provide CLI and TUI access to the new model before a desktop release.

### Phase C — desktop alpha

- Ship Home, Ingest, Organize, Projects, and Activity views.
- Support plan/review/execute/verify/receipt end to end.
- Prove packaging, permissions, removable-drive discovery, cancellation, and
  recovery with real media on supported platforms.

### Phase D — editorial handoff and maturity

- Improve proxy readiness and Resolve handoff from project state.
- Export portable manifests and operator-facing handoff reports.
- Add watch folders or storage adapters only after the core local workflow is
  dependable.

## 10. Definition of a successful first desktop release

The release is successful when a user can:

1. connect a source, choose a project, and see an understandable intake plan;
2. create and verify the required working and backup replicas;
3. know accurately whether the source is safe to format;
4. adopt an existing collaborator drive into a preferred, previewed structure;
5. see which project media is missing, changed, unverified, or lacks proxies;
6. retrieve an operation receipt that explains what happened without relying on
   a terminal or memory of the run.

## 11. Open decisions before implementation

- Which platforms are supported in the desktop alpha: macOS only, then Windows,
  or both from the start?
- Does a project require two verified replicas by default, or is that a
  user-selectable policy with no universal default?
- What checksum and sample-verification choices balance trust and realistic
  offload time for large camera cards?
- How should identical files, renamed files, and logical/spanned clips be
  represented without turning the first release into a full DAM?
- Is a source-preserving offload replica mandatory before an organization
  profile can move files?
- Which desktop shell proves most reliable with the Python core and long-running
  FFmpeg/file-copy jobs?
- What exact evidence must be preserved to resume or safely recover a
  partially completed offload?

## 12. Immediate next specification work

The next implementation-grade document should focus on one bounded slice:
**verified card offload and intake sessions**. It should define the SQLite
schema, state machine, policy model, filesystem behavior, cancellation and
resume semantics, receipt format, UI acceptance criteria, migration strategy,
and real-media validation matrix.

Do not begin the desktop-shell implementation until that contract exists and
the shared job/application boundary has been designed around it.
