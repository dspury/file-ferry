# Example organization presets

Status: Destination-first product direction agreed; detailed acceptance examples proposed, not shipped configuration.
Date: 2026-09-10
Companion: [Destination presets production spec](DESTINATION-PRESETS-PRODUCTION-SPEC.md).

These examples define observable behavior for implementation and review. They are intentionally not importable JSON: the preset schema is being revised. Implementers should translate them into the final validated schema without changing the expected mappings.

## Agreed product direction

Saved destinations and storage recognition are the primary experience. Connect a drive or mount a share, select the recognized saved destination, load its pinned organization preset, select sources, review, and transfer. Recognition never starts a transfer automatically; ambiguous identity requires confirmation under the production spec.

The two organization choices are **Preserve source structure** and **Organize by rules**. “Sort loose files by category” is a starter preset for the second choice. Users can save their own desired structure and assign the same preset to multiple destinations.

**Keep selected folders intact** is an optional rule in either workflow, not a third project-specific preset. It applies equally to albums, libraries, client folders, application bundles, or video projects. Existing project records remain optional for media features; general transfers do not require one. Do not introduce a Projects destination root or project-creation step as a default in this workflow.

## Shared behavior

- A preset contains relative organization rules, never a NAS address, mount path, drive UUID, credentials, or personal configuration. Any saved destination can pin any preset revision.
- All examples copy and verify. They never move, replace, or delete source content.
- Unknown files remain accounted for. No extension-based automatic exclusions. System-artifact exclusions follow the shared scanner policy and appear in review and receipts.
- Unsupported objects, unreadable paths, and ambiguous destinations block approval until resolved or explicitly excluded. “Unsorted” means a readable file without a routing rule, not a place to hide scan errors.
- Classification is case-insensitive by extension. No FFmpeg, content AI, capture-date extraction, or project dependency inference is required.
- Preserve source-relative subfolders inside each category. Initial defaults favor traceability and avoiding accidental flattening. A user may create a separate flatter preset after reviewing its collision implications.
- The source label is user-visible and editable before planning. Never derive identity from it. Duplicate labels remain separate sources and trigger ordinary target collision handling.
- Conflict default: keep both using a stable planned suffix, reserving all names across the plan and existing contents. **Confirmed in the implementation contract (spec §6.4): the form is `name (n).ext`, counting from 2** — the original is conceptually copy 1, and the parenthesised form does not collide with filenames that legitimately end in `-1`. Earlier drafts of this document showed `name-1.ext`; the examples below use the confirmed form. What mattered was deterministic, reviewed, non-overwriting behavior, and that is unchanged.
- Verified existing outputs from prior matching transfer provenance may be reused under the production spec. Unrelated files are not skipped just because their names or sizes match. Explicit `skip_identical` requires full checksum evidence.
- Preserve-group decisions run before individual file rules. Show the group and rule responsible for each proposed location.
- Do not create empty category folders merely because a preset lists them. Preserve actual empty source directories as described below.

## 1. Preserve source structure

**Picker name:** Preserve source structure

**Description:** Keep each drive or folder's layout intact inside its own source folder.

**Best fit:** First offload, unfamiliar drives, archives, project collections, and sources whose internal relationships should remain unchanged.

**Default preset for a newly saved destination:** Yes.

**Routing:** Every supported file → `Sources/{source_label}/{relative_dir}/{filename}`.

**Empty directories:** `Sources/{source_label}/` plus original relative directory path.

**Grouping:** The source structure is already preserved; no category split occurs. Recognized package boundaries remain intact. Unsupported contents still require explicit review.

Example source label: `Drive-A`.

```text
SOURCE                              DESTINATION-RELATIVE PATH
Photos/Trip/IMG_001.JPG              Sources/Drive-A/Photos/Trip/IMG_001.JPG
Projects/Interview/edit.drp          Sources/Drive-A/Projects/Interview/edit.drp
Projects/Interview/Media/A001.mov    Sources/Drive-A/Projects/Interview/Media/A001.mov
Documents/notes.pdf                  Sources/Drive-A/Documents/notes.pdf
misc/file.custom                    Sources/Drive-A/misc/file.custom
Empty/                              Sources/Drive-A/Empty/
```

An unknown extension follows the same rule; it does not need an Unsorted folder because this preset explicitly accepts all files.

**Tradeoff shown in picker help:** Retains existing disorder as well as useful structure. Use a category preset when the source is a collection of loose files.

## 2. Sort loose files by category

**Picker name:** Sort loose files by category

**Description:** Separate loose video, audio, images, documents, and archives while keeping their source folders traceable.

**Best fit:** Download folders, export collections, and mixed loose-file drives. Users can mark any folders with related contents “Keep selected folders intact” before applying category rules.

**Default preset for new destinations:** No; explicit selection.

Apply the following rules in order. Each row is one category-match rule with the stated fixed destination template.

| Rule ID | Condition | Destination template |
| --- | --- | --- |
| category-video | Category = video | `Video/{source_label}/{relative_dir}/{filename}` |
| category-audio | Category = audio | `Audio/{source_label}/{relative_dir}/{filename}` |
| category-images | Category = image | `Images/{source_label}/{relative_dir}/{filename}` |
| category-documents | Category = document | `Documents/{source_label}/{relative_dir}/{filename}` |
| category-archives | Category = archive | `Archives/{source_label}/{relative_dir}/{filename}` |
| fallback | No category rule matches | `Unsorted/{source_label}/{relative_dir}/{filename}` |

The acceptance fixture uses unambiguous extensions: `.mov` → video, `.wav` → audio, `.jpg` → image, `.pdf` → document, `.zip` → archive. Unknown `.custom`, `.xmp`, `.drp`, and extensionless files use fallback for these examples unless inside a preserved group. This does not define the entire extension registry; the implementation must document its versioned map and must not silently classify every unknown sidecar as a document.

**Empty directories outside groups:** `Unsorted/{source_label}/` plus the original relative directory path. A directory containing routed files is not itself an empty directory; do not create an empty fallback duplicate for every source parent.

**User-selected preserved groups:** Route under `Collections/{source_label}/` plus the selected group's original relative path; keep all descendants beneath that group. The group destination is the directory root, not a per-file template. Recognized packages use the same preservation behavior. See §4 for group-token semantics.

```text
SOURCE                          DESTINATION-RELATIVE PATH
Exports/trailer.mov             Video/Drive-A/Exports/trailer.mov
Recordings/interview.wav        Audio/Drive-A/Recordings/interview.wav
Photos/Trip/IMG_001.JPG          Images/Drive-A/Photos/Trip/IMG_001.JPG
Admin/notes.pdf                 Documents/Drive-A/Admin/notes.pdf
Backups/export.zip              Archives/Drive-A/Backups/export.zip
misc/file.custom                Unsorted/Drive-A/misc/file.custom
misc/README                     Unsorted/Drive-A/misc/README
Empty/                          Unsorted/Drive-A/Empty/
```

**Tradeoff shown before review:** Category routing can separate related files. Review proposed groups before starting. A `.jpg` and adjacent `.xmp` are not automatically paired by matching basenames.

## 3. Optional rule: Keep selected folders intact

**Control label:** Keep selected folders intact

**Description:** Keep a selected folder and all its contents together, preserving internal paths.

This is a rule available within either organization choice. In Preserve source structure, existing routing already retains folders; marking a group also protects internal names during conflict resolution. In Organize by rules, a group takes precedence over individual category rules.

**Selection:** Choose directory roots during planning or save explicit directory-glob rules in a preset revision. Do not infer projects from filenames, extensions, or top-level folder names. A group may contain any supported readable file type.

**Routing:** Under Preserve source structure, retain `Sources/{source_label}/` plus the group's original relative path. Under the category starter preset, use `Collections/{source_label}/` plus the group's original relative path. Collections is an editable example prefix, not a mandatory folder on every destination.

**Outside selected groups:** Apply the selected preset's ordinary file and empty-directory rules unchanged.

Example using the category starter preset, with `Photos/Trip` and `Music/Album` selected:

```text
SOURCE                              DESTINATION-RELATIVE PATH
Photos/Trip/IMG_001.JPG              Collections/Drive-A/Photos/Trip/IMG_001.JPG
Photos/Trip/IMG_001.xmp              Collections/Drive-A/Photos/Trip/IMG_001.xmp
Photos/Trip/notes.txt                Collections/Drive-A/Photos/Trip/notes.txt
Photos/Trip/Empty/                   Collections/Drive-A/Photos/Trip/Empty/
Music/Album/track.wav                Collections/Drive-A/Music/Album/track.wav
Music/Album/artwork.jpg              Collections/Drive-A/Music/Album/artwork.jpg
Loose/trailer.mov                   Video/Drive-A/Loose/trailer.mov
Admin/notes.pdf                     Documents/Drive-A/Admin/notes.pdf
misc/file.custom                    Unsorted/Drive-A/misc/file.custom
```

All descendants stay together even when a category rule would otherwise separate them. Nested selections do not split an outer group: the outermost group wins.

**Help:** Internal relative paths are retained. Ferry does not rewrite absolute references inside files or infer dependencies outside the selected folder.

## 4. Group template clarification for implementation

The production spec defines group destinations but does not yet specify the meaning of file-oriented tokens when evaluating a directory group. These examples require a directory-aware contract before serializing presets:

- For group evaluation only, `{relative_dir}` is the selected group's parent path relative to the source root.
- `{filename}` is the complete selected group directory basename, including any dots. It is not a descendant filename.
- Thus `Collections/{source_label}/{relative_dir}/{filename}` evaluates once to the group root. Descendant-relative paths are appended unchanged afterward.
- The group `Photos/Trip` evaluates to `Collections/Drive-A/Photos/Trip`.
- A top-level group `Trip` has an empty relative parent; join components without doubled separators.
- Selecting the entire source as a group uses `Collections/{source_label}` in the category example directly, avoiding duplication of the source's basename. Preserve-source preset similarly starts at `Sources/{source_label}`.
- Do not expose `{ext}`, `{stem}`, `{category}`, `{year}`, or `{month}` for group destinations in this increment. They are unnecessary for these examples and risk splitting or renaming directory groups unexpectedly.

**Accepted and implemented in P4.** These semantics are now in spec §6.3 and enforced at save time: a group destination may use only `{source_label}`, `{relative_dir}` and `{filename}`, and the other tokens are rejected with a field-specific error rather than silently splitting or relocating a preserved subtree. No new token was required.

## 5. Optional customization: modification-year buckets

Do not include date routing in the two starter presets. Users often expect photo capture dates; current scoped tokens mean filesystem modification time in UTC.

An explicit user-created variation may route images to:

`Images/{year}/{source_label}/{relative_dir}/{filename}`

Example: `Photos/IMG_001.JPG` with source mtime `2024-12-31T23:30:00Z` → `Images/2024/Drive-A/Photos/IMG_001.JPG` regardless of the workstation's timezone. Display “Year from file modification time (UTC).” Missing time goes to Unsorted with a warning; it must not become the year of transfer.

## 6. Common acceptance examples

These supplement A01–A26 in the production spec; they do not replace transfer-safety gates.

| ID | Input / decision | Expected behavior |
| --- | --- | --- |
| E01 | Same preset pinned to an SSD folder and a mounted share folder | Identical destination-relative tree; storage paths only differ outside the preset |
| E02 | `Drive-A/Photos/a.jpg` and `Drive-B/Photos/a.jpg` | Both retained beneath their own source labels |
| E03 | Two distinct sources both labeled `Drive-A` with same relative path | Both inventoried; visible collision and stable keep-both resolution, no implicit exclusion |
| E04 | Existing `a.jpg` contains different same-length bytes | Conflict; never skip-identical from size |
| E05 | Keep-both with existing `a.jpg` and `a (2).jpg` | Proposed `a (3).jpg`; allocation persists in approved plan |
| E06 | External writer creates approved `a (2).jpg` before publication | Stop that write for review; no overwrite or silent `a (3).jpg` substitution |
| E07 | Same completed plan resumed/repeated with matching provenance | Reuse only verified recorded output; no suffix explosion |
| E08 | Preserved folder contains video, audio, images, sidecars, unknown files and empty folders | Entire supported tree remains together; no descendant category split |
| E09 | Outer and inner groups selected | Outer group wins; review explains containment |
| E10 | Loose `.custom` and extensionless file | Preset 1 preserves; preset 2 routes to Unsorted outside preserved groups |
| E11 | Source contains an unreadable directory or symlink | Visible blocking finding until explicitly resolved/excluded; not ordinary fallback |
| E12 | Preset edited after destination was saved | Existing destination stays on pinned revision until explicitly updated |
| E13 | User changes source label/group selection after preview | Plan approval invalidated; new destinations shown before execution |
| E14 | Source-relative names contain Unicode/spaces | Names retained where target permits; incompatible names/conflicts shown before copying |
| E15 | Entire source selected as preserved group | One source folder, no repeated source basename |
| E16 | File renamed by keep-both belongs to a preserved folder group | Do not silently rename a group member and risk breaking references; resolve collision at group-root level or require review |

For E16, when a preserved group collides with an existing folder tree, the conservative default is allocate a new group-root name and retain every internal relative path. Merging an existing group is allowed only when the planner can prove compatible mappings and reviewed per-file decisions; this is not required for the initial examples. Never suffix arbitrary internal members automatically.

## 7. Decision summary

1. Center navigation and setup on saved destinations and storage recognition. Preserve source structure is the default organization choice; Organize by rules offers a category starter preset and custom presets.
2. Preserve source-relative paths inside categories initially.
3. Offer Keep selected folders intact as a general rule, not a project-specific preset or required project record.
4. Keep dates out of defaults until users opt into the clearly labeled modification-time policy.
5. Resolve preserved-folder conflicts at the group root to preserve internal references.

The final three choices requiring P4 contract alignment are group token evaluation (§4), group-root collision handling (E16), and placement of empty ungrouped directories. These examples propose exact behavior so the implementing agent does not have to invent it while coding.

**All three are now settled in the spec.** Group token evaluation is §6.3 (evaluated once for the group root; file-oriented tokens rejected at save time). Group-root collision handling is §6.3 (the whole group moves to a suffixed root with internal paths intact, or the whole group blocks; no member is ever suffixed automatically). Empty-directory placement is §6.2: a directory holding entries this plan copies is created by them and gets no entry of its own; a genuinely empty source directory keeps its entry and is preserved.
