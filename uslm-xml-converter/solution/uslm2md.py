#!/usr/bin/env python3
"""
USLM XML to Markdown converter.

"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ContentNode:
    type: str  # subsection, paragraph, subparagraph, clause, subclause, item, subitem, text
    label: str = ""
    heading: str = ""
    text: str = ""
    children: List["ContentNode"] = field(default_factory=list)


@dataclass
class Note:
    heading: str = ""
    text: str = ""


@dataclass
class SectionIR:
    title_number: int = 0
    section_number: str = ""
    heading: str = ""
    chapter: str = ""
    content: List[ContentNode] = field(default_factory=list)
    statutory_notes: List[Note] = field(default_factory=list)
    editorial_notes: List[Note] = field(default_factory=list)


@dataclass
class ChapterInfo:
    number: str = ""
    heading: str = ""


@dataclass
class TitleIR:
    title_number: int = 0
    heading: str = ""
    positive_law: bool = False
    chapters: List[ChapterInfo] = field(default_factory=list)
    sections: List[SectionIR] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Indentation map
# ---------------------------------------------------------------------------

INDENT_MAP = {
    "subsection": 0,
    "paragraph": 0,
    "subparagraph": 2,
    "clause": 4,
    "subclause": 6,
    "item": 8,
    "subitem": 10,
}

BODY_TAGS = {"subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem"}


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def strip_ns(tag: str) -> str:
    """Remove namespace prefix from an XML tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def strip_ns_tree(elem: ET.Element):
    """Recursively strip namespace from an entire element tree."""
    elem.tag = strip_ns(elem.tag)
    for child in elem:
        strip_ns_tree(child)
    return elem


def extract_text(elem: Optional[ET.Element]) -> str:
    """Extract text from an element, converting <ref> children to Markdown links."""
    if elem is None:
        return ""
    parts: List[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        tag = strip_ns(child.tag)
        if tag == "ref":
            href = child.attrib.get("href", "")
            link_text = child.text or ""
            url = href_to_url(href)
            parts.append(f"[{link_text}]({url})")
        else:
            # Treat any other inline element as plain text container
            parts.append(extract_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def href_to_url(href: str) -> str:
    """Convert /us/usc/t{N}/s{S} to canonical OLRC URL."""
    m = re.match(r"/us/usc/t(\d+)/s(.+)", href)
    if not m:
        return href
    title = m.group(1)
    section = m.group(2)
    return (
        f"https://uscode.house.gov/view.xhtml?"
        f"req=granuleid:USC-prelim-title{title}-section{section}"
        f"&num=0&edition=prelim"
    )


def get_attr(elem: ET.Element, name: str) -> str:
    """Get attribute value, stripping namespace if needed."""
    val = elem.attrib.get(name, "")
    if not val:
        # Try with common namespace prefixes
        for key, v in elem.attrib.items():
            if strip_ns(key) == name:
                return v
    return val


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def parse_uslm(xml_path: str) -> TitleIR:
    tree = ET.parse(xml_path)
    root = strip_ns_tree(tree.getroot())

    title_ir = TitleIR()

    # Positive law
    for prop in root.iter("property"):
        role = prop.attrib.get("role", "")
        if role == "is-positive-law":
            title_ir.positive_law = (prop.text or "").strip().lower() == "yes"

    # Find <title> element
    title_elem = None
    for elem in root.iter("title"):
        title_elem = elem
        break
    if title_elem is None:
        return title_ir

    # Title number
    num_elem = title_elem.find("num")
    if num_elem is not None:
        title_ir.title_number = int(num_elem.attrib.get("value", "0"))

    # Title heading
    heading_elem = title_elem.find("heading")
    if heading_elem is not None:
        title_ir.heading = (heading_elem.text or "").strip()

    # Chapters
    for ch_elem in title_elem.iter("chapter"):
        ch_num_elem = ch_elem.find("num")
        ch_heading_elem = ch_elem.find("heading")
        ch_num = ch_num_elem.attrib.get("value", "") if ch_num_elem is not None else ""
        ch_heading = (ch_heading_elem.text or "").strip() if ch_heading_elem is not None else ""
        chapter = ChapterInfo(number=ch_num, heading=ch_heading)
        if not any(c.number == ch_num for c in title_ir.chapters):
            title_ir.chapters.append(chapter)

        # Sections within this chapter
        for sec_elem in ch_elem.findall("section"):
            section = parse_section(sec_elem, title_ir.title_number, ch_num)
            title_ir.sections.append(section)

    return title_ir


def parse_section(elem: ET.Element, title_number: int, chapter: str) -> SectionIR:
    section = SectionIR(title_number=title_number, chapter=chapter)

    num_elem = elem.find("num")
    if num_elem is not None:
        section.section_number = num_elem.attrib.get("value", "")

    heading_elem = elem.find("heading")
    if heading_elem is not None:
        section.heading = (heading_elem.text or "").strip()

    # Content
    content_elem = elem.find("content")
    if content_elem is not None:
        section.content = parse_content_children(content_elem)

    # Notes
    for notes_elem in elem.findall("notes"):
        notes_type = notes_elem.attrib.get("type", "statutory")
        for note_elem in notes_elem.findall("note"):
            note = parse_note(note_elem)
            if notes_type == "editorial":
                section.editorial_notes.append(note)
            else:
                section.statutory_notes.append(note)

    return section


def parse_content_children(parent: ET.Element) -> List[ContentNode]:
    """Parse child content nodes from a parent element."""
    nodes: List[ContentNode] = []
    for child in parent:
        tag = strip_ns(child.tag)
        if tag in BODY_TAGS:
            nodes.append(parse_labeled_node(child, tag))
    return nodes


def parse_labeled_node(elem: ET.Element, node_type: str) -> ContentNode:
    """Parse a labeled node (subsection, paragraph, etc.)."""
    node = ContentNode(type=node_type)

    # Label from <num value="...">
    num_elem = elem.find("num")
    if num_elem is not None:
        node.label = num_elem.attrib.get("value", "")

    # Heading
    heading_elem = elem.find("heading")
    if heading_elem is not None:
        node.heading = extract_text(heading_elem)

    # Chapeau becomes the node's text
    chapeau_elem = elem.find("chapeau")
    if chapeau_elem is not None:
        node.text = extract_text(chapeau_elem)

    # If no chapeau, check for direct <text> element
    if not node.text:
        text_elem = elem.find("text")
        if text_elem is not None:
            node.text = extract_text(text_elem)

    # Child labeled nodes
    for child in elem:
        tag = strip_ns(child.tag)
        if tag in BODY_TAGS:
            node.children.append(parse_labeled_node(child, tag))

    # Continuation becomes a text child
    cont_elem = elem.find("continuation")
    if cont_elem is not None:
        cont_text = extract_text(cont_elem)
        if cont_text:
            node.children.append(ContentNode(type="text", text=cont_text))

    return node


def parse_note(elem: ET.Element) -> Note:
    """Parse a note element."""
    note = Note()
    heading_elem = elem.find("heading")
    if heading_elem is not None:
        note.heading = (heading_elem.text or "").strip()

    paragraphs: List[str] = []
    for p_elem in elem.findall("p"):
        paragraphs.append(extract_text(p_elem))

    note.text = "\n\n".join(paragraphs)
    return note


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def format_label(label: str) -> str:
    """Ensure label is wrapped in parentheses."""
    label = label.strip()
    if not label:
        return ""
    return label if label.startswith("(") else f"({label})"


def is_labeled_line(line: str) -> bool:
    """Check if a line starts with a label pattern like (a) or **(a)**."""
    return bool(re.match(r"^\s*(?:\*\*)?\([^)]+\)", line))


def render_content_nodes(nodes: List[ContentNode]) -> List[str]:
    """Render a list of content nodes to lines."""
    lines: List[str] = []
    for node in nodes:
        rendered = render_node(node)
        if not rendered:
            continue
        # Add blank line before labeled nodes
        if lines and is_labeled_line(rendered[0]):
            lines.append("")
        lines.extend(rendered)
    return lines


def render_node(node: ContentNode) -> List[str]:
    """Render a single content node to lines."""
    if node.type == "text":
        return [node.text] if node.text else []

    lines: List[str] = []
    label = format_label(node.label)
    indent = INDENT_MAP.get(node.type, 0)
    prefix = " " * indent

    if node.type == "subsection":
        # Subsection: bold label
        heading_part = f"{label} {node.heading}".strip() if node.heading else label
        if heading_part and node.text:
            lines.append(f"**{heading_part}** {node.text}")
        elif heading_part:
            lines.append(f"**{heading_part}**")
        elif node.text:
            lines.append(node.text)
    else:
        # Other levels: plain label with indentation
        parts = []
        if label:
            parts.append(label)
        if node.text:
            parts.append(node.text)
        line_text = " ".join(parts)
        if line_text:
            lines.append(f"{prefix}{line_text}")

    # Render children
    child_indent = indent + 2 if node.type != "subsection" else 0
    for child in node.children:
        child_lines = render_child_node(child, child_indent)
        if not child_lines:
            continue
        if lines and is_labeled_line(child_lines[0]):
            lines.append("")
        lines.extend(child_lines)

    return lines


def render_child_node(node: ContentNode, parent_child_indent: int) -> List[str]:
    """Render a child content node at specified indent level."""
    if node.type == "text":
        if not node.text:
            return []
        return [f"{' ' * parent_child_indent}{node.text}"]

    lines: List[str] = []
    label = format_label(node.label)
    indent = INDENT_MAP.get(node.type, parent_child_indent)
    prefix = " " * indent

    # Main line
    parts = []
    if label:
        parts.append(label)
    if node.text:
        parts.append(node.text)
    line_text = " ".join(parts)
    if line_text:
        lines.append(f"{prefix}{line_text}")

    # Children
    child_indent = indent + 2
    for child in node.children:
        child_lines = render_child_node(child, child_indent)
        if not child_lines:
            continue
        if lines and is_labeled_line(child_lines[0]):
            lines.append("")
        lines.extend(child_lines)

    return lines


def render_section_body(
    section: SectionIR,
    heading_level: int,
    notes_level: int,
    note_item_level: int,
    anchor: Optional[str] = None,
) -> List[str]:
    """Render section body to lines."""
    lines: List[str] = []

    # Anchor (chapter mode only)
    if anchor:
        lines.append(f'<a id="{anchor}"></a>')

    # Section heading
    prefix = "#" * heading_level
    heading = (
        f"{prefix} \u00a7 {section.section_number}. {section.heading}"
        if section.heading
        else f"{prefix} \u00a7 {section.section_number}."
    )
    lines.append(heading)

    # Content
    content_lines = render_content_nodes(section.content)
    if content_lines:
        # First content line: add blank line before labeled, otherwise just append
        if is_labeled_line(content_lines[0]):
            lines.extend(content_lines)
        else:
            lines.append("")
            lines.extend(content_lines)

    # Statutory notes
    if section.statutory_notes:
        lines.append("")
        lines.append(f"{'#' * notes_level} Statutory Notes")
        for note in section.statutory_notes:
            lines.append("")
            if note.heading:
                lines.append(f"{'#' * note_item_level} {note.heading}")
            if note.text:
                for text_line in note.text.split("\n"):
                    lines.append(text_line)

    # Editorial notes
    if section.editorial_notes:
        lines.append("")
        lines.append(f"{'#' * notes_level} Notes")
        for note in section.editorial_notes:
            lines.append("")
            if note.text:
                for text_line in note.text.split("\n"):
                    lines.append(text_line)

    return lines


def compact_lines(lines: List[str]) -> str:
    """Join lines, remove consecutive blank lines, ensure trailing newline."""
    result: List[str] = []
    for line in lines:
        if line == "" and result and result[-1] == "":
            continue
        result.append(line)
    return "\n".join(result).rstrip() + "\n"


def section_anchor(section_number: str) -> str:
    """Generate anchor ID for a section."""
    normalized = re.sub(r"[^a-z0-9-]+", "-", section_number.lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return f"section-{normalized or 'unknown'}"


def slugify(text: str) -> str:
    """Convert heading to URL-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

def render_chapter_md(title_ir: TitleIR, chapter: ChapterInfo, sections: List[SectionIR]) -> str:
    """Render chapter mode markdown."""
    # Frontmatter
    fm_lines = [
        "---",
        f"title: {title_ir.title_number}",
        f"chapter: '{chapter.number}'",
        f"heading: {chapter.heading}",
        f"section_count: {len(sections)}",
        f"source: https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{title_ir.title_number}&num=0&edition=prelim",
        "---",
    ]

    # Section bodies
    section_bodies: List[str] = []
    for sec in sections:
        anchor = section_anchor(sec.section_number)
        body_lines = render_section_body(sec, 2, 3, 4, anchor=anchor)
        section_bodies.append(compact_lines(body_lines))

    body = "\n".join(section_bodies).rstrip() + "\n"
    return "\n".join(fm_lines) + "\n" + body


def render_section_md(section: SectionIR) -> str:
    """Render section mode markdown."""
    fm_lines = [
        "---",
        f"title: {section.title_number}",
        f"section: '{section.section_number}'",
        f"heading: {section.heading}",
        "status: in-force",
        f"source: https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{section.title_number}-section{section.section_number}&num=0&edition=prelim",
        f"chapter: '{section.chapter}'",
        "---",
    ]

    body_lines = render_section_body(section, 1, 2, 3)
    body = compact_lines(body_lines)

    return "\n".join(fm_lines) + "\n" + body


def section_file_safe_id(section_number: str) -> str:
    """Pad section number to 5 digits."""
    m = re.match(r"^(\d+)(.*)", section_number)
    if m:
        return m.group(1).zfill(5) + m.group(2).replace("/", "-")
    return section_number.zfill(5)


def chapter_file_safe_id(chapter_number: str) -> str:
    """Pad chapter number to 3 digits."""
    if chapter_number.isdigit():
        return chapter_number.zfill(3)
    return re.sub(r"[^a-z0-9]+", "-", chapter_number.lower()).strip("-") or "unnamed"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <chapter|section> <input.xml> <output_dir>", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    input_path = sys.argv[2]
    output_dir = sys.argv[3]
    os.makedirs(output_dir, exist_ok=True)

    title_ir = parse_uslm(input_path)

    if mode == "chapter":
        for chapter in title_ir.chapters:
            chapter_sections = [s for s in title_ir.sections if s.chapter == chapter.number]
            md = render_chapter_md(title_ir, chapter, chapter_sections)
            slug = slugify(chapter.heading)
            safe_id = chapter_file_safe_id(chapter.number)
            filename = f"chapter-{safe_id}-{slug}.md" if slug else f"chapter-{safe_id}.md"
            with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as f:
                f.write(md)

    elif mode == "section":
        for section in title_ir.sections:
            md = render_section_md(section)
            safe_id = section_file_safe_id(section.section_number)
            filename = f"section-{safe_id}.md"
            with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as f:
                f.write(md)

    else:
        print(f"Unknown mode: {mode}. Use 'chapter' or 'section'.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
