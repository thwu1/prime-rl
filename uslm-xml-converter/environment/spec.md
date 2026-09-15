# USLM XML to Chapter-Grouped Markdown — Format Specification

This document specifies how to convert United States Legislative Markup (USLM) XML
into chapter-grouped Markdown files suitable for storage in a git repository.

## 1. XML Structure

The input is USLM XML (namespace `http://xml.house.gov/schemas/uslm/1.0`). Strip
the namespace when parsing.

```
uscDoc
  meta
    property[@role="is-positive-law"]   → "yes" or "no"
  main
    title[@identifier]
      num[@value]                        → integer title number
      heading                            → title heading text
      chapter[@identifier]
        num[@value]                      → chapter number (string)
        heading                          → chapter heading
        section[@identifier]*
          num[@value]                    → section number (string)
          heading                        → section heading
          content                        → body content tree
          notes[@type]                   → "statutory" or "editorial"
```

### 1.1 Content Tree

Inside `<content>`, the body is a tree of labeled nodes at seven nesting levels:

| Level | Tag            | Typical labels |
|-------|----------------|----------------|
| 1     | `subsection`   | a, b, c, ...   |
| 2     | `paragraph`    | 1, 2, 3, ...   |
| 3     | `subparagraph` | A, B, C, ...   |
| 4     | `clause`       | i, ii, iii, ... |
| 5     | `subclause`    | I, II, III, ... |
| 6     | `item`         | aa, bb, cc, ... |
| 7     | `subitem`      | AA, BB, CC, ...|

Each labeled node may contain:
- `<num value="...">` — the label value
- `<heading>` — optional heading text
- `<text>` — inline body text (may contain `<ref>` elements)
- `<chapeau>` — introductory text before children (becomes inline text of parent)
- `<continuation>` — closing text after children (rendered as text block after children)
- Nested labeled child nodes

### 1.2 Cross-References

`<ref href="/us/usc/t{N}/s{S}">link text</ref>` elements appear within `<text>`,
`<chapeau>`, `<continuation>`, and `<p>` elements. Transform to Markdown links:

```
[link text](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{N}-section{S}&num=0&edition=prelim)
```

### 1.3 Notes

`<notes type="statutory">` contains statutory notes. Each child `<note>` has an
optional `<heading>` and one or more `<p>` content elements.

`<notes type="editorial">` contains editorial notes. Each child `<note>` has one or
more `<p>` content elements (headings are not rendered for editorial notes).

Multiple `<p>` elements in a single note are separated by blank lines.
`<p>` elements may contain `<ref>` elements (render as Markdown links).

## 2. Output Filename

`chapter-{CCC}-{slug}.md` where:
- `{CCC}` = chapter number zero-padded to 3 digits
- `{slug}` = heading lowercased, non-alphanumeric replaced with `-`, collapsed

## 3. YAML Frontmatter

```yaml
---
title: {title_number}
chapter: '{chapter_number}'
heading: {CHAPTER_HEADING}
section_count: {count}
source: https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{N}&num=0&edition=prelim
---
```

- `title` and `section_count` are integers (no quotes)
- `chapter` is a string (single-quoted)
- Key order must match the example above

## 4. Body Rendering

### 4.1 Section Heading

Each section opens with an anchor and a level-2 heading:

```
<a id="section-{N}"></a>
## § {N}. {heading}
```

The anchor ID `section-{N}` is the section number lowercased with non-alphanumeric
characters replaced by `-`.

### 4.2 Subsection Formatting

Subsection labels are **bold**: `**(label)** text`

If a subsection has a heading: `**(label) Heading** text`

If only label, no text: `**(label)**`

### 4.3 Content Indentation

All levels below subsection use plain (non-bold) labels with indentation:

| Node type    | Indent (spaces) |
|--------------|-----------------|
| paragraph    | 0               |
| subparagraph | 2               |
| clause       | 4               |
| subclause    | 6               |
| item         | 8               |
| subitem      | 10              |

Format: `{indent}({label}) {text}`

### 4.4 Label Formatting

If a label does not start with `(`, wrap it: `a` → `(a)`.
If already parenthesized, keep as-is.

### 4.5 Blank Lines

- Insert a blank line **before** each labeled node
- Do **not** insert a blank line before non-labeled text (continuation, plain text)

### 4.6 Chapeau and Continuation

- **Chapeau**: becomes the inline text of the parent labeled node
- **Continuation**: rendered as a text node after all sibling labeled nodes, at the
  same indent as those siblings, with **no** preceding blank line

### 4.7 Note Sections

| Note type  | Group heading | Item heading |
|------------|--------------|--------------|
| Statutory  | `###`        | `####`       |
| Editorial  | `###`        | (none)       |

- Statutory notes: group heading `Statutory Notes`, then each note with heading + text
- Editorial notes: group heading `Notes`, then each note's text (no per-note headings)
- Blank line before group heading and before each note

## 5. Section Ordering

Sections within a chapter appear in document order. Sections are separated by a
blank line. The output file ends with a single trailing newline.

## 6. Cross-Reference Report Schema (`refs-report.json`)

The pipeline must produce a `refs-report.json` file in the repository root that
catalogs every cross-reference link found in the markdown files of the final commit.

The file must conform to this schema:

```json
{
  "references": [
    {
      "source_section": "<string>",
      "link_text": "<string>",
      "target_title": "<integer>",
      "target_section": "<string>",
      "url": "<string>",
      "internal": "<boolean>"
    }
  ],
  "summary": {
    "total": "<integer>",
    "internal": "<integer>",
    "external": "<integer>"
  }
}
```

### 6.1 Field definitions

| Field | Type | Description |
|-------|------|-------------|
| `references` | array | One entry per cross-reference link found in the markdown |
| `references[].source_section` | string | Section number where the reference appears (e.g. `"101"`) |
| `references[].link_text` | string | Display text of the Markdown link |
| `references[].target_title` | integer | USC title number the link points to |
| `references[].target_section` | string | Section number the link points to |
| `references[].url` | string | Full resolved URL of the link |
| `references[].internal` | boolean | `true` if `target_title` has markdown files in this repository; `false` otherwise |
| `summary.total` | integer | Length of `references` array |
| `summary.internal` | integer | Count of entries where `internal == true` |
| `summary.external` | integer | Count of entries where `internal == false` |

### 6.2 Constraints

- `target_title` must be an integer, not a string
- `internal` must be a boolean, not a string
- `summary.total == summary.internal + summary.external`
- `summary.total == len(references)`

## 7. Changelog Schema (`changelog.json`)

The pipeline must produce a `changelog.json` file in the repository root that records
structural differences between consecutive vintage snapshots. Vintages must be compared
in chronological order (sorted by `release_date` from the manifest). For N vintages,
the file contains N-1 diff entries.

The changelog requires parsing each vintage's XML into a section-level intermediate
representation, then structurally comparing the IR trees of consecutive vintage pairs
to detect and classify additions and amendments.

```json
{
  "diffs": [
    {
      "from_vintage": "<string>",
      "to_vintage": "<string>",
      "changes": [
        {
          "change_type": "<string>",
          "section": "<string>",
          "<additional fields>": "..."
        }
      ]
    }
  ]
}
```

### 7.1 Diff entry fields

| Field | Type | Description |
|-------|------|-------------|
| `from_vintage` | string | Vintage ID of the older snapshot |
| `to_vintage` | string | Vintage ID of the newer snapshot |
| `changes` | array | List of change records between these two vintages |

### 7.2 Change types and required fields

| `change_type` | Required fields | Description |
|---|---|---|
| `section_added` | `section` (string), `heading` (string) | A new section appeared in the newer vintage |
| `subsection_added` | `section` (string), `location` (string) | A new subsection added to an existing section |
| `paragraph_added` | `section` (string), `location` (string) | A new paragraph added within an existing subsection |
| `text_amended` | `section` (string), `location` (string), `old_value` (string), `new_value` (string) | Text content changed within a provision |
| `notes_amended` | `section` (string), `note_type` (string: `"editorial"` or `"statutory"`) | Notes section was modified |

### 7.3 Location notation

The `location` field uses statutory hierarchy path notation:
- `"d"` — subsection (d)
- `"a/5"` — paragraph (5) within subsection (a)
- `"a/2/B"` — subparagraph (B) within paragraph (2) of subsection (a)

### 7.4 Text amendment values

For `text_amended` entries, `old_value` and `new_value` contain the key changed
substring — typically the specific value that was amended (e.g. a monetary amount
that was increased or decreased by legislation).

### 7.5 Constraints

- `len(diffs) == number_of_vintages - 1`
- Diffs are ordered chronologically (matching vintage sort by `release_date`)
- Every change record must include `change_type` and `section`
- `change_type` must be one of the five defined types
- `note_type` must be `"editorial"` or `"statutory"`
