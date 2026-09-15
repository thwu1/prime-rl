Two USLM (United States Legislative Markup) XML public laws at `/data/pl_119_45.xml` and `/data/pl_119_67.xml` both amend the same base statute at `/data/base_statute.json`. The file `/data/enactment_metadata.json` specifies their chronological enactment order.

Build a program that applies all amendments from both laws to the base statute **in enactment order**, producing:

1. `/app/amended_statute.json` — the final state of the statute after all amendments from both laws.
2. `/app/reconciliation_report.json` — a structured audit trail of every amendment action.

The USLM XML uses namespace `http://schemas.gpo.gov/xml/uslm`. Amendment actions are encoded via `<amendingAction>` elements with `type` attributes (`amend`, `insert`, `delete`, `add`, `redesignate`, `repeal`). Text to be struck or inserted is wrapped in `<quotedText>`. Structured provisions to be inserted or substituted are wrapped in `<quotedContent>` containing full USLM hierarchy (`<subsection>`, `<paragraph>`, `<subparagraph>`, etc.). Cross-references use `<ref href="...">` elements with hierarchical identifiers (e.g., `/us/usc/t6/s1201/b/3/C`).

The second law (PL 119-67) was drafted with knowledge that PL 119-45 would already be enacted. Its amendments target the statute *as already amended* by PL 119-45. This means:

- References to provisions use post-redesignation identifiers (e.g., if PL 119-45 redesignated subsection (c) as (d), PL 119-67 references subsection (d) to target the former (c)).
- Text substitutions target text as modified by PL 119-45, not the original base text.
- One amendment in PL 119-67 contains a conditional savings clause ("if paragraph (7) ... has not been added by prior enactment"). This must be detected and **skipped** if the referenced provision already exists from the first law's amendments. The provision's original content from PL 119-45 must be preserved intact.

USLM quoting conventions: opening `"` in `<num>` elements and closing `"` at the end of `<quotedContent>` text must be stripped. Headings from `<quotedContent>` should have trailing `.—` suffixes removed.

The output JSON structure for the amended statute: top-level `title`, `chapter`, and `sections` keyed by section number, containing optional `heading`, `text`, `paragraphs` (keyed by number string), and `subsections` (keyed by letter). Paragraphs may contain `subparagraphs` (keyed by uppercase letter).

The reconciliation report must include:
- `enactment_order`: array of objects with `law_id` and `enacted_date` fields
- `amendments`: array of records, each with `source_law`, `source_section`, `target_provision`, `action_type`, and `status` ("applied" or "skipped"). Skipped amendments must include a `skip_reason` field.
- `summary`: object with `total_amendments`, `applied`, and `skipped` integer counts