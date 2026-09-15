# USLM XML to Markdown Converter — Specification

## Overview

Build a converter at `/app/convert.py` that reads USLM (United States Legislative Markup) XML files from `/app/input/` and produces structured Markdown files in `/app/output/`.

Each `<title>` in the input XML is a title of the United States Code. Each `<section>` within becomes an individual Markdown file with YAML frontmatter and formatted body content.

## Input Format

USLM XML files follow this general structure:

```
<uscDoc>
  <meta>
    <property role="is-positive-law">yes|no</property>
  </meta>
  <main>
    <title>
      <num value="N">Title N</num>
      <heading>Title Heading</heading>
      <chapter>
        <num value="C">Chapter C</num>
        <heading>Chapter Heading</heading>
        <section identifier="/us/usc/tN/sS">
          <num value="S">§S.</num>
          <heading>Section Heading</heading>
          <enacted>YYYY-MM-DD</enacted>
          <public-law>Pub. L. NNN–NNN</public-law>
          <last-amended>YYYY-MM-DD</last-amended>
          <last-amended-by>Pub. L. NNN–NNN</last-amended-by>
          <status>in-force|repealed|transferred|omitted</status>
          <content>...</content>
          <sourceCredit>...</sourceCredit>
          <notes type="statutory">...</notes>
          <note type="editorial">...</note>
        </section>
      </chapter>
    </title>
  </main>
</uscDoc>
```

### Content Structure

Section content uses a 7-level hierarchy of labeled elements:

1. `<subsection>` — labeled (a), (b), (c)...
2. `<paragraph>` — labeled (1), (2), (3)...
3. `<subparagraph>` — labeled (A), (B), (C)...
4. `<clause>` — labeled (i), (ii), (iii)...
5. `<subclause>` — labeled (I), (II), (III)...
6. `<item>` — labeled (aa), (bb), (cc)...
7. `<subitem>` — labeled (AA), (BB), (CC)...

Each labeled element may have:
- `<num value="X">(X)</num>` — the label (use the `value` attribute)
- `<heading>text</heading>` — optional heading
- `<chapeau>text</chapeau>` — introductory text before child elements
- `<text>text</text>` or `<content>text</content>` or `<p>text</p>` — text content
- `<continuation>text</continuation>` — text after child elements
- Nested child labeled elements

### Cross-References

`<ref href="/us/usc/tN/sS">link text</ref>` elements appear inline within text. These reference other US Code sections.

### Notes

Statutory notes: `<notes type="statutory"><note topic="..."><heading>H</heading><text>T</text></note></notes>`

Editorial notes: `<note type="editorial"><text>T</text></note>` (direct children of `<section>`)

Tables may appear inside notes: `<table><tr><th>...</th></tr><tr><td>...</td></tr></table>`

Sections may appear inside notes (historical references) — these embedded sections are rendered as plain text within the note body, NOT as separate output files.

## Output Structure

### Directory

Output directory: `title-{NN}-{slug}/`
- `NN` = title number zero-padded to 2 digits
- `slug` = title heading lowercased, apostrophes/quotes removed, non-alphanumeric sequences replaced with single hyphens, leading/trailing hyphens removed

### File Names

`section-{NNNNN}.md`
- `NNNNN` = section number zero-padded to 5 digits
- Slashes in section numbers become dashes (e.g., section "5/3" → `section-00005-3.md`)

## Markdown Format

### Frontmatter

YAML frontmatter with these fields (omit if not present in the XML):

| Field | Type | Source |
|-------|------|--------|
| `title` | integer | Title number from `<num value="N">` |
| `section` | string | Section number from `<num value="S">` |
| `heading` | string | Section `<heading>` text |
| `status` | string | `<status>` element text, default "in-force" |
| `source` | string | Generated URL (see below) |
| `chapter` | string | Parent chapter number from hierarchy |
| `enacted` | string | `<enacted>` text |
| `public_law` | string | `<public-law>` text |
| `last_amended` | string | `<last-amended>` text |
| `last_amended_by` | string | `<last-amended-by>` text |
| `source_credit` | string | `<sourceCredit>` text |

Source URL format: `https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{N}-section{S}&num=0&edition=prelim`

### Section Heading

```
# § {number}. {heading}
```

### Content Rendering

| Level | Element | Indent | Format |
|-------|---------|--------|--------|
| 1 | subsection | 0 | Bold: `**(a)** text` or `**(a) heading** text` |
| 2 | paragraph | 0 | Plain: `(1) text` |
| 3 | subparagraph | 2 | Plain: `  (A) text` |
| 4 | clause | 4 | Plain: `    (i) text` |
| 5 | subclause | 6 | Plain: `      (I) text` |
| 6 | item | 8 | Plain: `        (aa) text` |
| 7 | subitem | 10 | Plain: `          (AA) text` |

**Subsection formatting rules:**
- If label only: `**(a)** text`
- If label + heading, no text: `**(a) heading**`
- If label + heading + text: `**(a) heading** text`

**Spacing:** Insert a blank line before each labeled element.

**Text extraction:** Concatenate `element.text` content, inline `<ref>` children (as markdown links), and all `element.tail` content. Normalize whitespace (collapse runs of whitespace to single spaces, trim).

### Cross-Reference Links

Rewrite `<ref href="/us/usc/t{N}/s{S}">text</ref>` to:

```
[text](../title-{NN}-{slug}/section-{SSSSS}.md)
```

Where:
- `NN` = referenced title number (2-digit zero-padded)
- `slug` = canonical heading for the referenced title, slugified
- `SSSSS` = referenced section number (5-digit zero-padded, slashes removed)

For the current title being processed, use the heading from the input XML.

**Known canonical title headings** (for cross-reference link generation):

| Title | Heading |
|-------|---------|
| 1 | General Provisions |
| 2 | The Congress |
| 3 | The President |
| 4 | Flag and Seal, Seat of Government, and the States |
| 5 | Government Organization and Employees |
| 6 | Domestic Security |
| 7 | Agriculture |
| 8 | Aliens and Nationality |
| 9 | Arbitration |
| 10 | Armed Forces |
| 11 | Bankruptcy |
| 12 | Banks and Banking |
| 13 | Census |
| 14 | Coast Guard |
| 15 | Commerce and Trade |
| 16 | Conservation |
| 17 | Copyrights |
| 18 | Crimes and Criminal Procedure |
| 19 | Customs Duties |
| 20 | Education |
| 21 | Food and Drugs |
| 22 | Foreign Relations and Intercourse |
| 23 | Highways |
| 24 | Hospitals and Asylums |
| 25 | Indians |
| 26 | Internal Revenue Code |
| 27 | Intoxicating Liquors |
| 28 | Judiciary and Judicial Procedure |
| 29 | Labor |
| 30 | Mineral Lands and Mining |
| 31 | Money and Finance |
| 32 | National Guard |
| 33 | Navigation and Navigable Waters |
| 34 | Crime Control and Law Enforcement |
| 35 | Patents |
| 36 | Patriotic and National Observances, Ceremonies, and Organizations |
| 37 | Pay and Allowances of the Uniformed Services |
| 38 | Veterans Benefits |
| 39 | Postal Service |
| 40 | Public Buildings, Property, and Works |
| 41 | Public Contracts |
| 42 | The Public Health and Welfare |
| 43 | Public Lands |
| 44 | Public Printing and Documents |
| 45 | Railroads |
| 46 | Shipping |
| 47 | Telecommunications |
| 48 | Territories and Insular Possessions |
| 49 | Transportation |
| 50 | War and National Defense |
| 51 | National and Commercial Space Programs |
| 52 | Voting and Elections |
| 54 | National Park Service and Related Programs |

Non-USC hrefs (not matching `/us/usc/t{N}/s{S}`) should be rendered as plain text (no link).

### Notes Sections

After the content body:

```markdown
## Statutory Notes

### {Note Heading}

{Note text}

### {Note Heading}

{Note text with table}

## Notes

{Editorial note text}
```

Only include these sections if notes exist.

**Tables** in notes render as markdown:
```
| Header 1 | Header 2 |
| --- | --- |
| Cell 1 | Cell 2 |
```

Pipe characters `|` inside cell text must be escaped as `\|`.

**Embedded sections** inside notes render as plain text within the note:
```
§ {number}. {heading}

{section text}
```

These are NOT separate output files.

## Section Collection

**Critical rule:** Only collect `<section>` elements that are NOT nested inside `<note>` or `<notes>` elements. Sections nested inside notes are historical references and must not generate output files. They should be rendered as plain text within the note body.

## Whitespace Normalization

All text content should have whitespace normalized: collapse consecutive whitespace characters (spaces, tabs, newlines) to a single space, then trim leading/trailing whitespace.
