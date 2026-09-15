# USLM XML to Markdown Converter — Format Specification

## CLI Interface

```
python3 /app/convert.py <input.xml> <output_dir> [--mode chapter|section]
```

- `input.xml`: Path to USLM XML input file
- `output_dir`: Directory for output markdown files (create if needed)
- `--mode`: `chapter` (default) or `section`

## XML Input Format

USLM XML uses `<uscDoc>` as root with `<meta>` and `<main><title>` children:

```xml
<uscDoc>
  <meta><property role="is-positive-law">yes|no</property></meta>
  <main>
    <title identifier="/us/usc/tN">
      <num value="N">Title N</num>
      <heading>Title Heading</heading>
      <!-- hierarchy: subtitle > part > subpart > chapter > subchapter > section -->
    </title>
  </main>
</uscDoc>
```

### Number Elements

`<num>` elements may have a `value` attribute (canonical value) or decorated text like `§ 1.` or `Chapter 1`. Strip prefixes (`§`, `Title`, `Chapter`, `Subtitle`, `Subchapter`, `Subpart`, `Part`) and trailing `.—` to get the canonical value. Prefer the `value` attribute when present.

### Content Hierarchy

Section content uses a 7-level labeled hierarchy. Each node may contain:
- `<num>` — label
- `<heading>` — optional heading  
- `<chapeau>` — introductory text (rendered before children)
- `<content>`, `<text>`, or `<p>` — inline text
- Nested labeled children of any deeper level
- `<continuation>` — text after children

Hierarchy levels and typical labels:

| Level | Tag | Labels |
|---|---|---|
| 1 | `subsection` | (a), (b), (c)... |
| 2 | `paragraph` | (1), (2), (3)... |
| 3 | `subparagraph` | (A), (B), (C)... |
| 4 | `clause` | (i), (ii), (iii)... |
| 5 | `subclause` | (I), (II), (III)... |
| 6 | `item` | (aa), (bb), (cc)... |
| 7 | `subitem` | (AA), (BB), (CC)... |

### Cross-References

Inline `<ref href="/us/usc/tN/sM">text</ref>` elements link to other USC sections.

### Notes

- `<sourceCredit>` — publication citation  
- `<note>` (direct child of section) — editorial/misc notes; has `<type>` child (`editorial`, `cross-reference`, `source-credit`, etc.) and `<text>` child
- `<notes type="statutory">` — contains `<note>` children with `<heading>` and `<p>` body paragraphs; notes may contain `<table>` elements

### Status

`<status>` element: `in-force` (default if absent), `repealed`, `transferred`, `omitted`.

## Output Formats

### Chapter Mode

**Files produced:**
- `chapter-{ID}-{slug}.md` — one per chapter
- `title-index.md` — title overview

**Chapter ID**: Numeric chapters zero-padded to 3 digits (e.g., `1` → `001`). Non-numeric chapters lowercased (e.g., `6A` → `6a`).

**Slug**: Heading lowercased, quotes removed, non-alphanumeric → hyphens, collapsed.

**Chapter frontmatter** (YAML between `---` markers):
```yaml
title: 9
chapter: '1'
heading: GENERAL PROVISIONS
section_count: 3
source: https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title9&num=0&edition=prelim
```

**Section rendering** (within chapter file):
```markdown
<a id="section-{anchor}"></a>
## § {num}. {heading}

{content}

### Statutory Notes

#### {note heading}
{note text}

### Notes
{editorial note text}
```

**Anchor slug**: Section number lowercased, non-alphanumeric → hyphens, trimmed.

**Title index frontmatter:**
```yaml
title: 9
heading: Arbitration
positive_law: true
sections: 3
chapters: 1
```

**Title index body:**
```markdown
# Title 9. Arbitration

## Chapters
- 1 — GENERAL PROVISIONS
```

### Section Mode

**Files produced:** `section-{NNNNN}.md` — one per section

**Section safe ID**: Numeric part zero-padded to 5 digits, non-numeric suffix preserved (e.g., `247d` → `00247d`).

**Section frontmatter:**
```yaml
title: 26
section: '2'
heading: Definitions and special rules
status: in-force
source: https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section2&num=0&edition=prelim
subtitle: A
part: I
chapter: '1'
subchapter: A
enacted: Aug. 16, 1954
public_law: ch. 736
last_amended: '2018'
last_amended_by: Pub. L. 115–141
source_credit: (Aug. 16, 1954, ch. 736, 68A Stat. 8; ...)
```

Include only fields that have values. Heading level is `#` (level 1). No anchor tag.

## Rendering Rules

### Labels

All labels must be parenthesized: a bare `a` becomes `(a)`. Labels already wrapped in parens stay as-is.

### Indentation

Indentation in spaces per content level:

| Type | Indent |
|---|---|
| subsection | 0 |
| paragraph | 0 |
| subparagraph | 2 |
| clause | 4 |
| subclause | 6 |
| item | 8 |
| subitem | 10 |

Children of a node are indented 2 more than the node, except: children of a subsection stay at the subsection's indent (0).

### Subsection Formatting (Chapter Mode)

Subsection labels are **bold** in chapter mode:

- Label + heading + text: `**(a) Heading** text`
- Label + text (no heading): `**(a)** text`
- Label + heading (no text): `**(a) Heading**`

### Paragraph and Below Formatting

In chapter mode with emphasis enabled:

- With heading at indent 0: `(1) **Heading** — text`
- With heading at indent > 0: `(1) *Heading* — text`
- Without heading: `(1) text`

In section mode: no emphasis on headings, space separator instead of ` — `.

### Chapeau and Continuation

- Chapeau text is the inline text of a labeled node, appearing on the same line as the label
- Continuation text appears as a text block after labeled children

### Blank Lines

- Insert a blank line between labeled siblings
- Insert a blank line before content if the first content line is labeled and the preceding line is not a heading or anchor

### Cross-Reference Links

Extract title number N and section tail M from `href="/us/usc/tN/sM"`.

**Chapter mode**: Rewrite to canonical URL:
```
[link text](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-titleN-sectionM&num=0&edition=prelim)
```

**Section mode**: Rewrite to relative markdown path:
```
[link text](../title-{NN}-{slug}/section-{MMMMM}.md)
```

Title directory name: `title-{NN}-{slug}` where NN is zero-padded title number and slug is from the title heading. Use the mapping at `/app/title_headings.json`.

### Notes Rendering

**Statutory notes** (from `<notes>` groups):
- Chapter mode: `### Statutory Notes` then `#### {heading}` per note
- Section mode: `## Statutory Notes` then `### {heading}` per note
- Note body from `<p>` children, separated by blank lines

**Editorial notes** (from individual `<note>` with type != `source-credit`):
- Chapter mode: `### Notes`
- Section mode: `## Notes`
- Note text from `<text>` child

### Tables

Render `<table>` elements as markdown pipe tables:

```
| Header 1 | Header 2 |
| --- | --- |
| Cell 1 | Cell 2 |
```

First non-empty row is the header. Pipe characters in cell text escaped as `\|`. Empty rows skipped.

### Source URL Default

If a section has no `<source>` element, generate:
`https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{N}-section{M}&num=0&edition=prelim`
