A pipeline at `/app/backfill.py` converts USLM XML legislative snapshots into a versioned git repository. It executes without error but the output repository has deficiencies across markdown rendering, history construction, and metadata generation.

Golden reference files at `/app/expected/` show the correct markdown for the first vintage. The full format specification and output schemas are at `/app/spec.md`. Manifest and vintage data are at `/app/manifest.json` and `/app/vintages/`.

Evaluate the pipeline's markdown output against the golden references and specification to identify formatting defects. Then redesign the pipeline so that the output repository at `/app/output/repo/` satisfies all of the following:

- Markdown files that faithfully implement the specification across all seven nesting levels, cross-reference links, note sections, and label formatting
- A git history constructed via `git fast-import` with properly backdated author and committer timestamps, commits in chronological order, and annotated (not lightweight) tags
- A `refs-report.json` in the repository root cataloging every cross-reference link in the final commit's markdown, conforming to the schema in section 6 of `/app/spec.md`
- A `changelog.json` in the repository root recording semantic differences between consecutive vintage snapshots — structural additions, text amendments, and note changes — conforming to the schema in section 7 of `/app/spec.md`. This requires parsing each vintage's XML into an intermediate representation, comparing IR trees across consecutive vintage pairs in chronological order, and classifying each detected difference by type.

Run: `python3 /app/backfill.py /app/manifest.json /app/vintages/ /app/output/repo/`