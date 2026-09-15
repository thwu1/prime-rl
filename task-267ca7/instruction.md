Build a converter at `/app/convert.py` that transforms United States Legislative Markup (USLM) XML files into structured Markdown section files.

The input XML file is at `/app/input/title-99.xml`. It contains a fictional title of the US Code with 4 sections across varying complexity: definition sections with deeply nested legal hierarchies (subsection → paragraph → subparagraph → clause), reporting requirements with cross-references between sections and to other titles, a penalties section with statutory notes containing markdown tables and editorial notes, and a repealed section with an embedded historical section inside a note.

The output should be individual Markdown files in `/app/output/`, one per section. Each file must have YAML frontmatter with section metadata and a formatted body with:

- Bold-labeled subsections `**(a)** text` with proper indentation hierarchy (paragraphs at 0, subparagraphs at 2, clauses at 4, etc.)
- Cross-reference `<ref href="/us/usc/tN/sS">` elements rewritten to relative markdown links using canonical title headings for directory slugs and 5-digit zero-padded section numbers
- Statutory notes under `## Statutory Notes` with individual `###` headings, including XML tables rendered as markdown tables
- Editorial notes under `## Notes`
- Sections nested inside `<note>` or `<notes>` elements must NOT produce output files (note scope boundary)
- Embedded sections inside notes rendered as plain text within the note body

The complete specification is at `/app/spec.md`.