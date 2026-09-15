Build a legislative change-tracking pipeline for US Code Title 9 from four USLM XML vintage snapshots.

Inputs at `/app/`: `vintages/{id}/title-09.xml`, `manifest.json`, `SPEC.md`, `title_headings.json`.

Entry point: executable script at `/app/pipeline.sh`. It must produce all outputs described below.

**Git Repository** (`/app/repo/`): One commit per vintage on `main`, chronologically ordered by `release_date`. Author and committer: `us-code-tools <sync@us-code-tools.local>`, timestamps set to the vintage's `release_date` at midnight UTC. Working tree must contain chapter-mode markdown under `title-09/` per `/app/SPEC.md`, including repealed sections rendered with their `[Repealed]` heading annotation. The repository's git fast-import stream must be saved to `/app/output/fast-import.stream`.

Each commit message first line: `Update US Code through Public Law {congress}-{law_number}`. The body must contain a `Changes:` block listing structural diffs from the prior vintage. Each change line format: `- {type}: {identifier} ({pub_law})` where type is one of `section_added`, `section_amended`, `section_repealed`, `chapter_added`; identifier is the section's USLM identifier (e.g. `/us/usc/t9/s1`) or chapter number; `pub_law` is the `Pub. L.` citation attributable to the change (omitted when none applies). The first vintage's commit lists all sections and chapters as initial additions.

Tags: `annual/{year}` on the last vintage released in each calendar year (when two vintages share a year, only the later one gets the tag); `congress/{N}` on vintages where `congress_boundary` is true in the manifest.

**Amendment Provenance** (`/app/output/provenance.json`): JSON object keyed by section identifier. Each entry: `heading` (string), `status` (`in-force` or `repealed`), `public_laws` (array of `Pub. L.` citation strings from the latest vintage), `first_appeared` (vintage ID where the section first appears across all vintages).

**Cross-Reference Analysis** (`/app/output/xref_analysis.json`): For the latest vintage only, classify every cross-reference found in section content (excluding notes). Output: `summary` with counts for `intra_title` (target within title 9), `inter_title` (target in a different title present in `/app/title_headings.json`), and `dangling` (target title absent from the headings map); `references` array with each entry having `source`, `target`, `link_text`, and `classification`.

**Structural Changelog** (`/app/output/changelog.json`): Array of diff entries, one per consecutive vintage pair (3 entries for 4 vintages). Each: `from_vintage`, `to_vintage`, and `changes` array. Each change: `type`, `identifier`, and `attribution` (the `Pub. L.` citation attributable to the change, or null).