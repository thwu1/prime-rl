#!/usr/bin/env python3
"""
USLM XML to Markdown Converter.

Reads USLM XML files from /app/input/ and produces structured Markdown
section files in /app/output/.

"""
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

INPUT_DIR = "/app/input"
OUTPUT_DIR = "/app/output"

# ─────────────────── Known US Code title headings ───────────────────

KNOWN_TITLE_HEADINGS = {
    1: "General Provisions",
    2: "The Congress",
    3: "The President",
    4: "Flag and Seal, Seat of Government, and the States",
    5: "Government Organization and Employees",
    6: "Domestic Security",
    7: "Agriculture",
    8: "Aliens and Nationality",
    9: "Arbitration",
    10: "Armed Forces",
    11: "Bankruptcy",
    12: "Banks and Banking",
    13: "Census",
    14: "Coast Guard",
    15: "Commerce and Trade",
    16: "Conservation",
    17: "Copyrights",
    18: "Crimes and Criminal Procedure",
    19: "Customs Duties",
    20: "Education",
    21: "Food and Drugs",
    22: "Foreign Relations and Intercourse",
    23: "Highways",
    24: "Hospitals and Asylums",
    25: "Indians",
    26: "Internal Revenue Code",
    27: "Intoxicating Liquors",
    28: "Judiciary and Judicial Procedure",
    29: "Labor",
    30: "Mineral Lands and Mining",
    31: "Money and Finance",
    32: "National Guard",
    33: "Navigation and Navigable Waters",
    34: "Crime Control and Law Enforcement",
    35: "Patents",
    36: "Patriotic and National Observances, Ceremonies, and Organizations",
    37: "Pay and Allowances of the Uniformed Services",
    38: "Veterans Benefits",
    39: "Postal Service",
    40: "Public Buildings, Property, and Works",
    41: "Public Contracts",
    42: "The Public Health and Welfare",
    43: "Public Lands",
    44: "Public Printing and Documents",
    45: "Railroads",
    46: "Shipping",
    47: "Telecommunications",
    48: "Territories and Insular Possessions",
    49: "Transportation",
    50: "War and National Defense",
    51: "National and Commercial Space Programs",
    52: "Voting and Elections",
    54: "National Park Service and Related Programs",
}

# ─────────────────── Note scope tags ───────────────────

NOTE_SCOPE_TAGS = {"note", "notes"}
HIERARCHY_TAGS = {"subtitle", "part", "subpart", "chapter", "subchapter"}
SECTION_BODY_TAGS = [
    "subsection", "paragraph", "subparagraph",
    "clause", "subclause", "item", "subitem",
]
INDENT_FOR_LEVEL = {
    "subsection": 0,
    "paragraph": 0,
    "subparagraph": 2,
    "clause": 4,
    "subclause": 6,
    "item": 8,
    "subitem": 10,
}


# ─────────────────── Utility functions ───────────────────

def normalize_ws(text):
    """Collapse whitespace runs to single space, trim."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def slugify(heading):
    """Convert heading to URL-safe slug."""
    if not heading:
        return None
    s = heading.lower()
    s = re.sub(r"['\u2018\u2019\u201c\u201d\u0022]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s or None


def pad_title(n):
    """Zero-pad title number to 2 digits."""
    return str(n).zfill(2)


def pad_section(s):
    """Zero-pad section number to 5 digits, slashes become dashes."""
    s = s.replace("/", "-")
    m = re.match(r"^(\d+)(.*)", s)
    if m:
        return m.group(1).zfill(5) + m.group(2)
    return s.zfill(5)


def title_dir_name(title_num, heading):
    """Build title directory name."""
    base = f"title-{pad_title(title_num)}"
    slug = slugify(heading)
    return f"{base}-{slug}" if slug else base


def section_file_name(section_num):
    """Build section file name."""
    return f"section-{pad_section(section_num)}.md"


def canonical_section_url(title_num, section_num):
    """Build canonical OLRC URL."""
    return (
        f"https://uscode.house.gov/view.xhtml?"
        f"req=granuleid:USC-prelim-title{title_num}-section{section_num}"
        f"&num=0&edition=prelim"
    )


# ─────────────────── Text extraction ───────────────────

def extract_text(element, title_num, title_heading):
    """Extract all text from an element, rewriting <ref> elements to
    markdown links. Handles mixed content (text, children, tails)."""
    if element is None:
        return ""
    parts = []
    if element.text:
        parts.append(element.text)
    for child in element:
        if child.tag == "ref":
            href = child.get("href", "")
            link_text = normalize_ws(child.text or "")
            md_link = href_to_markdown_link(href, title_num, title_heading)
            if md_link and link_text:
                parts.append(f"[{link_text}]({md_link})")
            else:
                parts.append(link_text)
        else:
            # Recurse into non-ref children
            parts.append(extract_text(child, title_num, title_heading))
        if child.tail:
            parts.append(child.tail)
    return normalize_ws("".join(parts))


def href_to_markdown_link(href, current_title_num, current_title_heading):
    """Convert /us/usc/tN/sS href to relative markdown link."""
    m = re.match(r"^/us/usc/t(\d+)/s(.+)$", href)
    if not m:
        return None
    ref_title = int(m.group(1))
    ref_section = m.group(2).replace("/", "")
    # Determine title heading for the referenced title
    if ref_title == current_title_num:
        heading = current_title_heading
    else:
        heading = KNOWN_TITLE_HEADINGS.get(ref_title)
    ref_dir = title_dir_name(ref_title, heading)
    return f"../{ref_dir}/{section_file_name(ref_section)}"


# ─────────────────── XML parsing ───────────────────

def get_child_text(element, tag):
    """Get text content of a child element."""
    child = element.find(tag)
    if child is None:
        return None
    return normalize_ws(child.text)


def get_num_value(element):
    """Get the canonical number from a <num> element."""
    num_el = element.find("num")
    if num_el is None:
        return ""
    val = num_el.get("value", "")
    if val:
        return val
    # Fallback: clean decorated text
    raw = normalize_ws(num_el.text)
    raw = re.sub(r"^§\s*", "", raw)
    raw = re.sub(r"^Title\s+", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^Chapter\s+", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[.\u2014]+$", "", raw)
    return raw.strip()


def collect_sections(element, hierarchy, sections, inside_note_scope=False):
    """Recursively collect <section> elements, skipping those inside notes."""
    for child in element:
        tag = child.tag
        if tag in HIERARCHY_TAGS:
            num = get_num_value(child)
            new_hier = dict(hierarchy)
            if num:
                new_hier[tag] = num
            collect_sections(child, new_hier, sections, inside_note_scope)
        elif tag == "section":
            if not inside_note_scope:
                sections.append((child, dict(hierarchy)))
            # Still recurse into sections (they might contain notes with
            # embedded sections we need to skip)
            collect_sections(child, hierarchy, sections, inside_note_scope)
        elif tag in NOTE_SCOPE_TAGS:
            collect_sections(child, hierarchy, sections, True)
        else:
            collect_sections(child, hierarchy, sections, inside_note_scope)


# ─────────────────── Content tree ───────────────────

class ContentNode:
    """Represents a node in the content tree."""
    def __init__(self, node_type, label="", heading="", text="", children=None):
        self.type = node_type
        self.label = label
        self.heading = heading
        self.text = text
        self.children = children or []


def parse_labeled_node(element, node_type, title_num, title_heading):
    """Parse a labeled element (subsection, paragraph, etc.) into a ContentNode."""
    label = get_num_value(element)
    heading = ""
    heading_el = element.find("heading")
    if heading_el is not None:
        heading = extract_text(heading_el, title_num, title_heading)

    text_parts = []
    children = []

    for child in element:
        tag = child.tag
        if tag == "num" or tag == "heading":
            continue
        elif tag == "chapeau":
            t = extract_text(child, title_num, title_heading)
            if t:
                text_parts.append(t)
        elif tag in SECTION_BODY_TAGS:
            children.append(
                parse_labeled_node(child, tag, title_num, title_heading)
            )
        elif tag == "continuation":
            t = extract_text(child, title_num, title_heading)
            if t:
                children.append(ContentNode("text", text=t))
        elif tag == "content":
            # Content wrapper — parse its children
            sub_text, sub_children = parse_content_children(
                child, title_num, title_heading
            )
            if sub_text:
                text_parts.append(sub_text)
            children.extend(sub_children)
        elif tag == "text" or tag == "p":
            t = extract_text(child, title_num, title_heading)
            if t:
                text_parts.append(t)
        else:
            t = extract_text(child, title_num, title_heading)
            if t:
                text_parts.append(t)

    return ContentNode(
        node_type=node_type,
        label=label,
        heading=heading,
        text=" ".join(text_parts) if text_parts else "",
        children=children,
    )


def parse_content_children(element, title_num, title_heading):
    """Parse the children of a <content> element.
    Returns (chapeau_text, child_nodes)."""
    text_parts = []
    children = []

    for child in element:
        tag = child.tag
        if tag == "chapeau":
            t = extract_text(child, title_num, title_heading)
            if t:
                text_parts.append(t)
        elif tag in SECTION_BODY_TAGS:
            children.append(
                parse_labeled_node(child, tag, title_num, title_heading)
            )
        elif tag == "continuation":
            t = extract_text(child, title_num, title_heading)
            if t:
                children.append(ContentNode("text", text=t))
        elif tag == "text" or tag == "p":
            t = extract_text(child, title_num, title_heading)
            if t and not children:
                text_parts.append(t)
        else:
            t = extract_text(child, title_num, title_heading)
            if t and not children:
                text_parts.append(t)

    return " ".join(text_parts), children


def parse_section_content(section_el, title_num, title_heading):
    """Parse the content of a section element into a list of ContentNodes."""
    content_el = section_el.find("content")
    if content_el is None:
        # Try to find text directly
        text = extract_text(section_el, title_num, title_heading)
        if text:
            return [ContentNode("text", text=text)]
        return []

    nodes = []
    for child in content_el:
        tag = child.tag
        if tag in SECTION_BODY_TAGS:
            nodes.append(
                parse_labeled_node(child, tag, title_num, title_heading)
            )
        elif tag == "chapeau":
            t = extract_text(child, title_num, title_heading)
            if t:
                nodes.append(ContentNode("text", text=t))
        elif tag == "continuation":
            t = extract_text(child, title_num, title_heading)
            if t:
                nodes.append(ContentNode("text", text=t))
        elif tag == "text" or tag == "p":
            t = extract_text(child, title_num, title_heading)
            if t:
                nodes.append(ContentNode("text", text=t))

    return nodes


# ─────────────────── Notes parsing ───────────────────

class StatutoryNote:
    def __init__(self, heading, text):
        self.heading = heading
        self.text = text


class EditorialNote:
    def __init__(self, text):
        self.text = text


def render_table(table_el):
    """Render an XML <table> element as a markdown table."""
    rows = []
    for child in table_el:
        tag = child.tag
        if tag == "tr":
            row = []
            for cell in child:
                if cell.tag in ("th", "td"):
                    cell_text = normalize_ws(
                        "".join(cell.itertext())
                    ).replace("|", "\\|")
                    row.append(cell_text)
            if row:
                rows.append(row)
        elif tag in ("thead", "tbody", "tfoot"):
            for tr in child:
                if tr.tag == "tr":
                    row = []
                    for cell in tr:
                        if cell.tag in ("th", "td"):
                            cell_text = normalize_ws(
                                "".join(cell.itertext())
                            ).replace("|", "\\|")
                            row.append(cell_text)
                    if row:
                        rows.append(row)

    if not rows:
        return ""

    # Find the first non-empty row as header
    header_idx = 0
    for i, row in enumerate(rows):
        if any(c for c in row):
            header_idx = i
            break

    header = rows[header_idx]
    data_rows = [r for r in rows[header_idx + 1:] if any(c for c in r)]
    col_count = max(len(header), *(len(r) for r in data_rows) if data_rows else [0])

    def pad_row(r):
        return r + [""] * (col_count - len(r))

    lines = []
    lines.append("| " + " | ".join(pad_row(header)) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row in data_rows:
        lines.append("| " + " | ".join(pad_row(row)) + " |")

    return "\n".join(lines)


def render_embedded_note_section(section_el):
    """Render an embedded <section> inside a note as plain text."""
    num = get_num_value(section_el)
    heading_el = section_el.find("heading")
    heading = normalize_ws(heading_el.text) if heading_el is not None else ""

    heading_line = ""
    if num and heading:
        heading_line = f"\u00a7 {num}. {heading}"
    elif num:
        heading_line = f"\u00a7 {num}."
    elif heading:
        heading_line = heading

    body_parts = []
    for child in section_el:
        if child.tag in ("num", "heading"):
            continue
        if child.tag == "text" or child.tag == "p":
            t = normalize_ws("".join(child.itertext()))
            if t:
                body_parts.append(t)
        elif child.tag == "content":
            for sub in child:
                t = normalize_ws("".join(sub.itertext()))
                if t:
                    body_parts.append(t)

    parts = []
    if heading_line:
        parts.append(heading_line)
    if body_parts:
        parts.append("\n\n".join(body_parts))
    return "\n\n".join(parts)


def parse_note_body(note_el):
    """Parse the body of a <note> element, handling text, tables,
    and embedded sections."""
    blocks = []
    inline_parts = []

    def flush_inline():
        if inline_parts:
            text = normalize_ws(" ".join(inline_parts))
            if text:
                blocks.append(text)
            inline_parts.clear()

    for child in note_el:
        tag = child.tag
        if tag == "heading" or tag == "type":
            continue
        elif tag == "table":
            flush_inline()
            table_md = render_table(child)
            if table_md:
                blocks.append(table_md)
        elif tag == "section":
            flush_inline()
            embedded = render_embedded_note_section(child)
            if embedded:
                blocks.append(embedded)
        elif tag == "p":
            flush_inline()
            t = normalize_ws("".join(child.itertext()))
            if t:
                blocks.append(t)
        elif tag == "text":
            t = normalize_ws("".join(child.itertext()))
            if t:
                inline_parts.append(t)
        else:
            t = normalize_ws("".join(child.itertext()))
            if t:
                inline_parts.append(t)

    flush_inline()
    return "\n\n".join(blocks)


def parse_notes(section_el):
    """Parse statutory and editorial notes from a section element."""
    statutory_notes = []
    editorial_notes = []
    source_credit = None

    # Source credit
    sc_el = section_el.find("sourceCredit")
    if sc_el is not None:
        source_credit = normalize_ws("".join(sc_el.itertext()))

    # Statutory notes: <notes type="statutory"><note>...</note></notes>
    for notes_el in section_el.findall("notes"):
        for note_el in notes_el.findall("note"):
            heading_el = note_el.find("heading")
            heading = normalize_ws(heading_el.text) if heading_el is not None else ""
            text = parse_note_body(note_el)
            if text:
                statutory_notes.append(StatutoryNote(heading, text))

    # Editorial notes: <note type="editorial">
    for note_el in section_el.findall("note"):
        note_type = note_el.get("type", "")
        if note_type == "source-credit":
            if source_credit is None:
                text_el = note_el.find("text")
                if text_el is not None:
                    source_credit = normalize_ws("".join(text_el.itertext()))
            continue
        text_el = note_el.find("text")
        if text_el is not None:
            t = normalize_ws("".join(text_el.itertext()))
            if t:
                editorial_notes.append(EditorialNote(t))

    return source_credit, statutory_notes, editorial_notes


# ─────────────────── Section data ───────────────────

class SectionData:
    def __init__(self):
        self.title_num = 0
        self.section_num = ""
        self.heading = ""
        self.status = "in-force"
        self.source = ""
        self.hierarchy = {}
        self.enacted = None
        self.public_law = None
        self.last_amended = None
        self.last_amended_by = None
        self.source_credit = None
        self.content = []
        self.statutory_notes = []
        self.editorial_notes = []


def parse_section(section_el, title_num, title_heading, hierarchy):
    """Parse a <section> XML element into SectionData."""
    sd = SectionData()
    sd.title_num = title_num
    sd.section_num = get_num_value(section_el)
    sd.heading = ""
    heading_el = section_el.find("heading")
    if heading_el is not None:
        sd.heading = normalize_ws(heading_el.text)

    # Status
    status_el = section_el.find("status")
    if status_el is not None:
        status_text = normalize_ws(status_el.text)
        if status_text in ("repealed", "transferred", "omitted"):
            sd.status = status_text
        else:
            sd.status = "in-force"

    sd.source = canonical_section_url(title_num, sd.section_num)
    sd.hierarchy = hierarchy

    sd.enacted = get_child_text(section_el, "enacted")
    sd.public_law = get_child_text(section_el, "public-law")
    sd.last_amended = get_child_text(section_el, "last-amended")
    sd.last_amended_by = get_child_text(section_el, "last-amended-by")

    # Parse content
    sd.content = parse_section_content(section_el, title_num, title_heading)

    # Parse notes
    sd.source_credit, sd.statutory_notes, sd.editorial_notes = parse_notes(
        section_el
    )

    return sd


# ─────────────────── Markdown rendering ───────────────────

def format_label(label):
    """Format a label, ensuring it has parentheses."""
    label = label.strip()
    if not label:
        return ""
    return label if label.startswith("(") else f"({label})"


def render_content_lines(nodes):
    """Render content nodes to lines of markdown."""
    lines = []
    for node in nodes:
        rendered = render_node_lines(node)
        if not rendered:
            continue
        # Add blank line before labeled elements
        if lines and is_labeled_line(rendered[0]):
            lines.append("")
        lines.extend(rendered)
    return lines


def is_labeled_line(line):
    """Check if a line starts with a label like (a) or **(a)**."""
    return bool(re.match(r"^\s*(\*\*)?\([^)]+\)", line))


def render_node_lines(node):
    """Render a single content node to lines."""
    if node.type == "text":
        return [node.text] if node.text.strip() else []

    label = format_label(node.label)
    heading = node.heading
    text = node.text
    indent = INDENT_FOR_LEVEL.get(node.type, 0)
    prefix = " " * indent

    if node.type == "subsection":
        # Subsections always use bold labels
        line = render_subsection_line(label, heading, text)
    else:
        # Other levels use plain labels
        parts = []
        if label:
            parts.append(label)
        if heading:
            if text:
                parts.append(f"{heading} {text}")
            else:
                parts.append(heading)
        elif text:
            parts.append(text)
        line = f"{prefix}{' '.join(parts)}" if parts else ""

    result = []
    if line:
        result.append(line)

    for child in node.children:
        child_lines = render_node_lines(child)
        if not child_lines:
            continue
        if result and is_labeled_line(child_lines[0]):
            result.append("")
        result.extend(child_lines)

    return result


def render_subsection_line(label, heading, text):
    """Render a subsection line with bold label."""
    heading_part = " ".join(filter(None, [label, heading]))
    if heading_part and text:
        return f"**{heading_part}** {text}"
    elif heading_part:
        return f"**{heading_part}**"
    else:
        return text or ""


def render_section_markdown(sd):
    """Render a SectionData object to a complete markdown string."""
    # Build frontmatter
    fm = {}
    fm["title"] = sd.title_num
    fm["section"] = sd.section_num
    if sd.heading:
        fm["heading"] = sd.heading
    fm["status"] = sd.status
    fm["source"] = sd.source
    if sd.hierarchy.get("chapter"):
        fm["chapter"] = sd.hierarchy["chapter"]
    if sd.hierarchy.get("subtitle"):
        fm["subtitle"] = sd.hierarchy["subtitle"]
    if sd.hierarchy.get("part"):
        fm["part"] = sd.hierarchy["part"]
    if sd.hierarchy.get("subpart"):
        fm["subpart"] = sd.hierarchy["subpart"]
    if sd.hierarchy.get("subchapter"):
        fm["subchapter"] = sd.hierarchy["subchapter"]
    if sd.enacted:
        fm["enacted"] = sd.enacted
    if sd.public_law:
        fm["public_law"] = sd.public_law
    if sd.last_amended:
        fm["last_amended"] = sd.last_amended
    if sd.last_amended_by:
        fm["last_amended_by"] = sd.last_amended_by
    if sd.source_credit:
        fm["source_credit"] = sd.source_credit

    # Render frontmatter
    fm_str = yaml.dump(
        fm,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    ).rstrip("\n")

    # Build body
    lines = []

    # Section heading
    if sd.heading:
        lines.append(f"# \u00a7 {sd.section_num}. {sd.heading}")
    else:
        lines.append(f"# \u00a7 {sd.section_num}.")

    # Content
    content_lines = render_content_lines(sd.content)
    if content_lines:
        lines.append("")
        lines.extend(content_lines)

    # Statutory notes
    if sd.statutory_notes:
        lines.append("")
        lines.append("## Statutory Notes")
        for note in sd.statutory_notes:
            lines.append("")
            if note.heading:
                lines.append(f"### {note.heading}")
            if note.text:
                lines.append("")
                lines.append(note.text)

    # Editorial notes
    if sd.editorial_notes:
        lines.append("")
        lines.append("## Notes")
        for note in sd.editorial_notes:
            lines.append("")
            lines.append(note.text)

    body = "\n".join(lines) + "\n"

    return f"---\n{fm_str}\n---\n\n{body}"


# ─────────────────── Main ───────────────────

def process_title(xml_path):
    """Process a single USLM XML file."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Find the title element (handle uscDoc/main/title or uslm/title)
    title_el = None
    main_el = root.find("main")
    if main_el is not None:
        title_el = main_el.find("title")
    if title_el is None:
        title_el = root.find("title")
    if title_el is None:
        print(f"Warning: No <title> found in {xml_path}")
        return

    title_num = int(get_num_value(title_el) or 0)
    heading_el = title_el.find("heading")
    title_heading = normalize_ws(heading_el.text) if heading_el is not None else ""

    # Collect sections (not inside notes)
    sections = []
    collect_sections(title_el, {}, sections)

    # Determine output directory
    out_dir = os.path.join(OUTPUT_DIR, title_dir_name(title_num, title_heading))
    os.makedirs(out_dir, exist_ok=True)

    # Process each section
    for section_el, hierarchy in sections:
        sd = parse_section(section_el, title_num, title_heading, hierarchy)
        md = render_section_markdown(sd)

        file_name = section_file_name(sd.section_num)
        file_path = os.path.join(out_dir, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"  Written: {file_path}")


def main():
    """Process all XML files in the input directory."""
    xml_files = sorted(Path(INPUT_DIR).glob("*.xml"))
    if not xml_files:
        print(f"No XML files found in {INPUT_DIR}")
        return

    for xml_path in xml_files:
        print(f"Processing: {xml_path}")
        process_title(str(xml_path))

    print("Done.")


if __name__ == "__main__":
    main()
