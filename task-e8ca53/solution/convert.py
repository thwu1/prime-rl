#!/usr/bin/env python3
"""USLM XML to structured Markdown converter.

"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIERARCHY_TAGS = ["subtitle", "part", "subpart", "chapter", "subchapter"]
SECTION_BODY_TAGS = [
    "subsection", "paragraph", "subparagraph",
    "clause", "subclause", "item", "subitem",
]
SECTION_BODY_SET = set(SECTION_BODY_TAGS)

TITLE_HEADINGS_PATH = "/app/title_headings.json"

_title_headings: Optional[Dict[int, str]] = None


def get_title_headings() -> Dict[int, str]:
    global _title_headings
    if _title_headings is None:
        try:
            with open(TITLE_HEADINGS_PATH) as f:
                raw = json.load(f)
            _title_headings = {int(k): v for k, v in raw.items()}
        except (FileNotFoundError, json.JSONDecodeError):
            _title_headings = {}
    return _title_headings


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ContentNode:
    type: str  # 'text' or one of SECTION_BODY_TAGS
    label: str = ""
    heading: str = ""
    text: str = ""
    children: List["ContentNode"] = field(default_factory=list)


@dataclass
class StatutoryNote:
    heading: str = ""
    note_type: str = ""
    topic: str = ""
    text: str = ""


@dataclass
class EditorialNote:
    kind: str = "misc"
    text: str = ""


@dataclass
class SectionIR:
    title_number: int = 0
    section_number: str = ""
    heading: str = ""
    status: str = "in-force"
    source: str = ""
    enacted: str = ""
    public_law: str = ""
    last_amended: str = ""
    last_amended_by: str = ""
    source_credit: str = ""
    hierarchy: Dict[str, str] = field(default_factory=dict)
    content: List[ContentNode] = field(default_factory=list)
    statutory_notes: List[StatutoryNote] = field(default_factory=list)
    editorial_notes: List[EditorialNote] = field(default_factory=list)


@dataclass
class ChapterInfo:
    number: str = ""
    heading: str = ""


@dataclass
class TitleIR:
    title_number: int = 0
    heading: str = ""
    positive_law: Optional[bool] = None
    chapters: List[ChapterInfo] = field(default_factory=list)
    sections: List[SectionIR] = field(default_factory=list)
    source_url: str = ""


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def normalize_whitespace(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def get_child(element: ET.Element, tag: str) -> Optional[ET.Element]:
    for child in element:
        if strip_ns(child.tag) == tag:
            return child
    return None


def get_children(element: ET.Element, tag: str) -> List[ET.Element]:
    return [c for c in element if strip_ns(c.tag) == tag]


def get_text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    return normalize_whitespace(element.text or "")


def clean_num_text(value: str) -> str:
    value = normalize_whitespace(value)
    value = re.sub(r"^§\s*", "", value)
    for prefix in ["Title", "Subtitle", "Subchapter", "Subpart", "Part", "Chapter"]:
        value = re.sub(rf"^{prefix}\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[.\u2014]+$", "", value)
    return value.strip()


def read_num(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    value_attr = element.get("value", "")
    if value_attr:
        return normalize_whitespace(value_attr)
    return clean_num_text(normalize_whitespace(element.text or ""))


# ---------------------------------------------------------------------------
# Mixed-content text extraction
# ---------------------------------------------------------------------------

def extract_mixed_text(
    element: Optional[ET.Element],
    link_mode: str = "chapter",
    title_number: int = 0,
) -> str:
    if element is None:
        return ""
    parts: List[str] = []
    if element.text:
        parts.append(element.text)
    for child in element:
        tag = strip_ns(child.tag)
        if tag == "ref":
            href = child.get("href", "")
            link_text = extract_mixed_text(child, link_mode, title_number)
            md_link = make_link(href, link_mode, title_number)
            if md_link:
                parts.append(f"[{link_text}]({md_link})")
            else:
                parts.append(link_text)
        else:
            parts.append(extract_mixed_text(child, link_mode, title_number))
        if child.tail:
            parts.append(child.tail)
    return normalize_whitespace("".join(parts))


# ---------------------------------------------------------------------------
# Link generation
# ---------------------------------------------------------------------------

def make_link(href: str, mode: str, current_title: int = 0) -> Optional[str]:
    match = re.match(r"^/us/usc/t(\d+)/s(.+)$", href)
    if not match:
        return None
    title_num = int(match.group(1))
    section_tail = match.group(2).strip()
    if not section_tail:
        return None
    if mode == "chapter":
        return (
            f"https://uscode.house.gov/view.xhtml?"
            f"req=granuleid:USC-prelim-title{title_num}-section{section_tail}"
            f"&num=0&edition=prelim"
        )
    else:
        title_dir = title_directory_name(title_num)
        safe_id = section_file_safe_id(section_tail.replace("/", ""))
        return f"../{title_dir}/section-{safe_id}.md"


def title_directory_name(title_num: int) -> str:
    base = f"title-{str(title_num).zfill(2)}"
    heading = get_title_headings().get(title_num)
    if heading:
        slug = slugify(heading)
        if slug:
            return f"{base}-{slug}"
    return base


def slugify(text: str) -> str:
    text = normalize_whitespace(text).lower()
    text = re.sub(r"['\"\u201c\u201d\u2018\u2019]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def section_file_safe_id(section_number: str) -> str:
    section_number = section_number.strip().replace("/", "-")
    match = re.match(r"^(\d+)(.*)", section_number)
    if not match:
        return section_number
    numeric = match.group(1)
    suffix = match.group(2)
    return f"{numeric.zfill(5)}{suffix}"


def chapter_file_safe_id(chapter: str) -> str:
    chapter = chapter.strip()
    if re.match(r"^\d+$", chapter):
        return chapter.zfill(3)
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", chapter)
    normalized = re.sub(r"-+", "-", normalized).strip("-").lower()
    return normalized or "unnamed"


def embedded_section_anchor(section_number: str) -> str:
    normalized = normalize_whitespace(section_number).lower()
    normalized = re.sub(r"[^a-z0-9-]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return f"section-{normalized or 'unknown'}"


def canonical_section_url(title_num: int, section_num: str) -> str:
    return (
        f"https://uscode.house.gov/view.xhtml?"
        f"req=granuleid:USC-prelim-title{title_num}-section{section_num}"
        f"&num=0&edition=prelim"
    )


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def parse_xml(xml_path: str, link_mode: str = "chapter") -> TitleIR:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    root_tag = strip_ns(root.tag)
    title_node = None
    meta_node = None

    if root_tag == "uscDoc":
        meta_node = get_child(root, "meta")
        main_node = get_child(root, "main")
        if main_node is not None:
            title_node = get_child(main_node, "title")
    elif root_tag == "uslm":
        title_node = get_child(root, "title")

    if title_node is None:
        raise ValueError("Could not find <title> element in XML")

    num_el = get_child(title_node, "num")
    title_number = _parse_title_number(read_num(num_el))
    heading_el = get_child(title_node, "heading")
    heading = extract_mixed_text(heading_el, link_mode, title_number) if heading_el is not None else ""
    positive_law = _read_positive_law(meta_node)

    title_ir = TitleIR(
        title_number=title_number,
        heading=heading,
        positive_law=positive_law,
        source_url=(
            f"https://uscode.house.gov/view.xhtml?"
            f"req=granuleid:USC-prelim-title{title_number}&num=0&edition=prelim"
        ),
    )

    _collect_hierarchy(title_node, title_ir, {}, link_mode, title_number)
    return title_ir


def _parse_title_number(value: str) -> int:
    try:
        n = int(value)
        if n > 0:
            return n
    except (ValueError, TypeError):
        pass
    match = re.search(r"(\d+)", value or "")
    return int(match.group(1)) if match else 0


def _read_positive_law(meta_node: Optional[ET.Element]) -> Optional[bool]:
    if meta_node is None:
        return None
    for prop in get_children(meta_node, "property"):
        if prop.get("role") == "is-positive-law":
            text = normalize_whitespace(prop.text or "")
            if text == "yes":
                return True
            if text == "no":
                return False
    return None


def _collect_hierarchy(
    node: ET.Element,
    title_ir: TitleIR,
    hierarchy: Dict[str, str],
    link_mode: str,
    title_number: int,
) -> None:
    for tag in HIERARCHY_TAGS:
        for child in get_children(node, tag):
            num_el = get_child(child, "num")
            number = clean_num_text(read_num(num_el)) if num_el is not None else ""
            new_hierarchy = dict(hierarchy)
            if number:
                new_hierarchy[tag] = number

            if tag == "chapter" and number:
                heading_el = get_child(child, "heading")
                ch_heading = extract_mixed_text(heading_el, link_mode, title_number) if heading_el is not None else ""
                if not any(c.number == number for c in title_ir.chapters):
                    title_ir.chapters.append(ChapterInfo(number=number, heading=ch_heading))

            _collect_hierarchy(child, title_ir, new_hierarchy, link_mode, title_number)

    for section_el in get_children(node, "section"):
        section_ir = _parse_section(section_el, title_number, hierarchy, link_mode)
        title_ir.sections.append(section_ir)


def _parse_section(
    section_el: ET.Element,
    title_number: int,
    hierarchy: Dict[str, str],
    link_mode: str,
) -> SectionIR:
    num_el = get_child(section_el, "num")
    section_number = read_num(num_el)

    heading_el = get_child(section_el, "heading")
    heading = extract_mixed_text(heading_el, link_mode, title_number) if heading_el is not None else ""

    status_el = get_child(section_el, "status")
    status = _normalize_status(get_text(status_el))

    source_el = get_child(section_el, "source")
    source = get_text(source_el) or canonical_section_url(title_number, section_number)

    enacted_el = get_child(section_el, "enacted")
    enacted = get_text(enacted_el)

    pl_el = get_child(section_el, "public-law")
    public_law = get_text(pl_el)

    la_el = get_child(section_el, "last-amended")
    last_amended = get_text(la_el)

    lab_el = get_child(section_el, "last-amended-by")
    last_amended_by = get_text(lab_el)

    sc_el = get_child(section_el, "sourceCredit")
    source_credit = extract_mixed_text(sc_el, link_mode, title_number) if sc_el is not None else ""

    content_el = get_child(section_el, "content")
    content = _parse_content(content_el if content_el is not None else section_el, link_mode, title_number)

    statutory_notes, editorial_notes = _parse_notes(section_el, link_mode, title_number)

    return SectionIR(
        title_number=title_number,
        section_number=section_number,
        heading=heading,
        status=status,
        source=source,
        enacted=enacted,
        public_law=public_law,
        last_amended=last_amended,
        last_amended_by=last_amended_by,
        source_credit=source_credit,
        hierarchy=dict(hierarchy),
        content=content,
        statutory_notes=statutory_notes,
        editorial_notes=editorial_notes,
    )


def _normalize_status(value: str) -> str:
    normalized = normalize_whitespace(value)
    if normalized in ("repealed", "transferred", "omitted"):
        return normalized
    return "in-force"


# ---------------------------------------------------------------------------
# Content parsing
# ---------------------------------------------------------------------------

def _parse_content(
    node: ET.Element,
    link_mode: str,
    title_number: int,
) -> List[ContentNode]:
    content: List[ContentNode] = []

    for chapeau_el in get_children(node, "chapeau"):
        text = extract_mixed_text(chapeau_el, link_mode, title_number)
        if text:
            content.append(ContentNode(type="text", text=text))

    for tag in SECTION_BODY_TAGS:
        for child in get_children(node, tag):
            content.append(_parse_labeled_node(tag, child, link_mode, title_number))

    for cont_el in get_children(node, "continuation"):
        text = extract_mixed_text(cont_el, link_mode, title_number)
        if text:
            content.append(ContentNode(type="text", text=text))

    if not content:
        for try_tag in ["text", "p", "content"]:
            el = get_child(node, try_tag)
            if el is not None:
                has_labeled = any(strip_ns(gc.tag) in SECTION_BODY_SET for gc in el)
                if has_labeled:
                    sub_content = _parse_content(el, link_mode, title_number)
                    content.extend(sub_content)
                else:
                    text = extract_mixed_text(el, link_mode, title_number)
                    if text:
                        content.append(ContentNode(type="text", text=text))
                break

        if not content:
            text = _extract_direct_text(node, link_mode, title_number)
            if text:
                content.append(ContentNode(type="text", text=text))

    return [c for c in content if c.type != "text" or c.text]


def _extract_direct_text(
    node: ET.Element,
    link_mode: str,
    title_number: int,
) -> str:
    skip_tags = set(HIERARCHY_TAGS) | SECTION_BODY_SET | {
        "num", "heading", "sourceCredit", "note", "notes",
        "chapeau", "continuation", "status", "source",
        "enacted", "public-law", "last-amended", "last-amended-by",
    }
    parts: List[str] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        tag = strip_ns(child.tag)
        if tag in skip_tags:
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(extract_mixed_text(child, link_mode, title_number))
        if child.tail:
            parts.append(child.tail)
    return normalize_whitespace("".join(parts))


def _parse_labeled_node(
    node_type: str,
    element: ET.Element,
    link_mode: str,
    title_number: int,
) -> ContentNode:
    num_el = get_child(element, "num")
    label = read_num(num_el)

    heading_el = get_child(element, "heading")
    heading = extract_mixed_text(heading_el, link_mode, title_number) if heading_el is not None else ""

    inline_parts: List[str] = []
    children: List[ContentNode] = []
    saw_labeled = False

    for child in element:
        tag = strip_ns(child.tag)

        if tag in ("num", "heading"):
            continue

        if tag == "chapeau":
            text = extract_mixed_text(child, link_mode, title_number)
            if text:
                inline_parts.append(text)
            continue

        if tag in SECTION_BODY_SET:
            saw_labeled = True
            children.append(_parse_labeled_node(tag, child, link_mode, title_number))
            continue

        if tag == "continuation":
            text = extract_mixed_text(child, link_mode, title_number)
            if text:
                children.append(ContentNode(type="text", text=text))
            continue

        if tag in ("content", "text", "p"):
            has_labeled = any(strip_ns(gc.tag) in SECTION_BODY_SET for gc in child)
            if has_labeled:
                sub_inline, sub_children = _parse_content_children(child, link_mode, title_number)
                inline_parts.extend(sub_inline)
                children.extend(sub_children)
            else:
                text = extract_mixed_text(child, link_mode, title_number)
                if text:
                    inline_parts.append(text)
            continue

        text = extract_mixed_text(child, link_mode, title_number)
        if text:
            inline_parts.append(text)

    return ContentNode(
        type=node_type,
        label=label,
        heading=heading,
        text=" ".join(inline_parts) if inline_parts else "",
        children=[c for c in children if c.type != "text" or c.text],
    )


def _parse_content_children(
    element: ET.Element,
    link_mode: str,
    title_number: int,
) -> Tuple[List[str], List[ContentNode]]:
    inline_parts: List[str] = []
    children: List[ContentNode] = []

    for child in element:
        tag = strip_ns(child.tag)
        if tag == "chapeau":
            text = extract_mixed_text(child, link_mode, title_number)
            if text:
                inline_parts.append(text)
        elif tag in SECTION_BODY_SET:
            children.append(_parse_labeled_node(tag, child, link_mode, title_number))
        elif tag == "continuation":
            text = extract_mixed_text(child, link_mode, title_number)
            if text:
                children.append(ContentNode(type="text", text=text))
        else:
            text = extract_mixed_text(child, link_mode, title_number)
            if text:
                inline_parts.append(text)

    return inline_parts, children


# ---------------------------------------------------------------------------
# Notes parsing
# ---------------------------------------------------------------------------

def _parse_notes(
    section_el: ET.Element,
    link_mode: str,
    title_number: int,
) -> Tuple[List[StatutoryNote], List[EditorialNote]]:
    statutory_notes: List[StatutoryNote] = []
    editorial_notes: List[EditorialNote] = []

    for note_el in get_children(section_el, "note"):
        type_el = get_child(note_el, "type")
        kind = normalize_whitespace(type_el.text or "") if type_el is not None else ""
        if kind == "source-credit":
            continue

        text = _extract_note_text(note_el, link_mode, title_number)
        if not text:
            continue

        if kind in ("editorial", "cross-reference"):
            editorial_notes.append(EditorialNote(kind=kind, text=text))
        else:
            editorial_notes.append(EditorialNote(kind="misc", text=text))

    for notes_el in get_children(section_el, "notes"):
        note_type = notes_el.get("type", "")
        for note_el in get_children(notes_el, "note"):
            heading_el = get_child(note_el, "heading")
            note_heading = extract_mixed_text(heading_el, link_mode, title_number) if heading_el is not None else ""
            topic = note_el.get("topic", "")

            text = _extract_note_text(note_el, link_mode, title_number)
            if not text:
                continue

            statutory_notes.append(StatutoryNote(
                heading=note_heading,
                note_type=note_type,
                topic=topic,
                text=text,
            ))

    return statutory_notes, editorial_notes


def _extract_note_text(
    note_el: ET.Element,
    link_mode: str,
    title_number: int,
) -> str:
    blocks: List[str] = []

    for child in note_el:
        tag = strip_ns(child.tag)
        if tag in ("heading", "type"):
            continue
        if tag == "p":
            text = extract_mixed_text(child, link_mode, title_number)
            if text:
                blocks.append(text)
        elif tag == "table":
            table = _render_table(child)
            if table:
                blocks.append(table)
        elif tag == "text":
            text = extract_mixed_text(child, link_mode, title_number)
            if text:
                blocks.append(text)
        else:
            text = extract_mixed_text(child, link_mode, title_number)
            if text:
                blocks.append(text)

    if not blocks:
        text_el = get_child(note_el, "text")
        if text_el is not None:
            text = extract_mixed_text(text_el, link_mode, title_number)
            if text:
                blocks.append(text)

    return "\n\n".join(blocks).strip()


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

def _render_table(table_el: ET.Element) -> str:
    rows = _parse_table_rows(table_el)
    if not rows:
        return ""

    col_count = max(len(row) for row in rows)
    normalized = [row + [""] * (col_count - len(row)) for row in rows]

    header_idx = None
    for i, row in enumerate(normalized):
        if any(cell.strip() for cell in row):
            header_idx = i
            break
    if header_idx is None:
        return ""

    header = normalized[header_idx]
    body = [row for row in normalized[header_idx + 1:] if any(cell.strip() for cell in row)]

    def escape_cell(s: str) -> str:
        return s.replace("|", "\\|").strip()

    lines = [
        "| " + " | ".join(escape_cell(c) for c in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        padded = row + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(escape_cell(c) for c in padded) + " |")

    return "\n".join(lines)


def _parse_table_rows(element: ET.Element) -> List[List[str]]:
    rows: List[List[str]] = []
    for child in element:
        tag = strip_ns(child.tag)
        if tag == "tr":
            row: List[str] = []
            for cell in child:
                cell_tag = strip_ns(cell.tag)
                if cell_tag in ("th", "td"):
                    row.append(_extract_table_cell_text(cell))
            if row:
                rows.append(row)
        else:
            rows.extend(_parse_table_rows(child))
    return rows


def _extract_table_cell_text(cell: ET.Element) -> str:
    parts: List[str] = []
    if cell.text:
        parts.append(cell.text)
    for child in cell:
        tag = strip_ns(child.tag)
        if tag == "p":
            text = normalize_whitespace(child.text or "")
            if text:
                parts.append(text)
        else:
            text = extract_mixed_text(child)
            if text:
                parts.append(text)
        if child.tail:
            parts.append(child.tail)
    return normalize_whitespace(" ".join(parts))


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_chapter_markdown(title_ir: TitleIR, chapter_number: str, sections: List[SectionIR]) -> str:
    chapter_info = next((c for c in title_ir.chapters if c.number == chapter_number), None)
    chapter_heading = chapter_info.heading if chapter_info else f"Chapter {chapter_number}"

    frontmatter = {
        "title": title_ir.title_number,
        "chapter": chapter_number,
        "heading": chapter_heading,
        "section_count": len(sections),
        "source": title_ir.source_url,
    }

    section_bodies: List[str] = []
    for section in sections:
        anchor = embedded_section_anchor(section.section_number)
        body = _render_section_body(
            section,
            heading_level=2,
            notes_level=3,
            note_item_level=4,
            anchor=anchor,
            emphasize=True,
        )
        section_bodies.append(body)

    content = "\n\n".join(section_bodies).rstrip() + "\n"
    return _render_yaml_frontmatter(frontmatter) + content


def render_section_markdown(section: SectionIR) -> str:
    frontmatter: Dict[str, object] = {}
    if section.title_number:
        frontmatter["title"] = section.title_number
    if section.section_number:
        frontmatter["section"] = section.section_number
    if section.heading:
        frontmatter["heading"] = section.heading
    if section.status:
        frontmatter["status"] = section.status
    if section.source:
        frontmatter["source"] = section.source
    if section.hierarchy.get("subtitle"):
        frontmatter["subtitle"] = section.hierarchy["subtitle"]
    if section.hierarchy.get("part"):
        frontmatter["part"] = section.hierarchy["part"]
    if section.hierarchy.get("subpart"):
        frontmatter["subpart"] = section.hierarchy["subpart"]
    if section.hierarchy.get("chapter"):
        frontmatter["chapter"] = section.hierarchy["chapter"]
    if section.hierarchy.get("subchapter"):
        frontmatter["subchapter"] = section.hierarchy["subchapter"]
    if section.enacted:
        frontmatter["enacted"] = section.enacted
    if section.public_law:
        frontmatter["public_law"] = section.public_law
    if section.last_amended:
        frontmatter["last_amended"] = section.last_amended
    if section.last_amended_by:
        frontmatter["last_amended_by"] = section.last_amended_by
    if section.source_credit:
        frontmatter["source_credit"] = section.source_credit

    body = _render_section_body(
        section,
        heading_level=1,
        notes_level=2,
        note_item_level=3,
        anchor=None,
        emphasize=False,
    )
    return _render_yaml_frontmatter(frontmatter) + body


def render_title_index(title_ir: TitleIR) -> str:
    frontmatter: Dict[str, object] = {
        "title": title_ir.title_number,
        "heading": title_ir.heading,
        "positive_law": title_ir.positive_law if title_ir.positive_law is not None else False,
        "sections": len(title_ir.sections),
    }
    if title_ir.chapters:
        frontmatter["chapters"] = len(title_ir.chapters)

    lines = [f"# Title {title_ir.title_number}. {title_ir.heading}"]
    if title_ir.chapters:
        lines.append("")
        lines.append("## Chapters")
        for ch in title_ir.chapters:
            lines.append(f"- {ch.number} \u2014 {ch.heading}")

    return _render_yaml_frontmatter(frontmatter) + _compact_lines(lines)


# ---------------------------------------------------------------------------
# Section body rendering
# ---------------------------------------------------------------------------

def _render_section_body(
    section: SectionIR,
    heading_level: int,
    notes_level: int,
    note_item_level: int,
    anchor: Optional[str],
    emphasize: bool,
) -> str:
    lines: List[str] = []

    if anchor:
        lines.append(f'<a id="{anchor}"></a>')

    prefix = "#" * heading_level
    if section.heading:
        lines.append(f"{prefix} \u00a7 {section.section_number}. {section.heading}")
    else:
        lines.append(f"{prefix} \u00a7 {section.section_number}.")

    content_lines = _render_content_nodes(section.content, emphasize=emphasize)
    if content_lines:
        if _is_labeled_line(content_lines[0]):
            lines.extend(content_lines)
        else:
            lines.append("")
            lines.extend(content_lines)

    if section.statutory_notes:
        lines.append("")
        lines.append(f"{'#' * notes_level} Statutory Notes")
        for note in section.statutory_notes:
            lines.append("")
            if note.heading:
                lines.append(f"{'#' * note_item_level} {note.heading}")
            if note.text:
                lines.extend(note.text.split("\n"))

    if section.editorial_notes:
        lines.append("")
        lines.append(f"{'#' * notes_level} Notes")
        for note in section.editorial_notes:
            lines.append("")
            lines.extend(note.text.split("\n"))

    return _compact_lines(lines)


def _render_content_nodes(nodes: List[ContentNode], emphasize: bool = True) -> List[str]:
    lines: List[str] = []
    for node in nodes:
        rendered = _render_content_node(node, indent=0, emphasize=emphasize)
        if not rendered:
            continue
        if lines and _should_separate(lines, rendered):
            lines.append("")
        lines.extend(rendered)
    return lines


def _should_separate(existing: List[str], new_lines: List[str]) -> bool:
    last = next((l for l in reversed(existing) if l.strip()), None)
    first = next((l for l in new_lines if l.strip()), None)
    if not last or not first:
        return False
    return _is_labeled_line(first) and not last.startswith("#") and not last.startswith('<a id=')


def _is_labeled_line(line: str) -> bool:
    return bool(re.match(r"^\s*(?:\*\*)?\([^)]+\)", line))


def _render_content_node(
    node: ContentNode,
    indent: int,
    emphasize: bool = True,
) -> List[str]:
    if node.type == "text":
        return [f"{' ' * indent}{node.text}"] if node.text else []

    lines: List[str] = []

    line = _render_labeled_line(node, indent, emphasize)
    if line:
        lines.append(line)

    child_indent = indent if node.type == "subsection" else indent + 2
    for child in node.children:
        child_lines = _render_content_node(child, child_indent, emphasize)
        if not child_lines:
            continue
        if lines and _should_separate_children(lines, child_lines):
            lines.append("")
        lines.extend(child_lines)

    return lines


def _should_separate_children(existing: List[str], child_lines: List[str]) -> bool:
    last = next((l for l in reversed(existing) if l.strip()), None)
    first = next((l for l in child_lines if l.strip()), None)
    if not last or not first:
        return False
    return _is_labeled_line(first)


def _render_labeled_line(node: ContentNode, indent: int, emphasize: bool) -> str:
    label = _format_label(node.label)
    heading = node.heading.strip()
    text = node.text.strip() if node.text else ""

    if node.type == "subsection" and emphasize:
        return _render_subsection_heading(label, heading, text)

    if heading:
        if emphasize:
            fmt_heading = f"**{heading}**" if indent == 0 else f"*{heading}*"
            heading_text = f"{fmt_heading} \u2014 {text}" if text else fmt_heading
        else:
            heading_text = f"{heading} {text}" if text else heading
        parts = [p for p in [label, heading_text] if p]
    else:
        parts = [p for p in [label, text] if p]

    if not parts:
        return ""
    return f"{' ' * indent}{' '.join(parts)}".rstrip()


def _render_subsection_heading(label: str, heading: str, text: str) -> str:
    heading_part = f"{label} {heading}".strip() if heading else label
    heading_part = heading_part.strip()
    if heading_part and text:
        return f"**{heading_part}** {text}"
    elif heading_part:
        return f"**{heading_part}**"
    return text or ""


def _format_label(label: str) -> str:
    label = label.strip()
    if not label:
        return ""
    return label if label.startswith("(") else f"({label})"


# ---------------------------------------------------------------------------
# YAML frontmatter
# ---------------------------------------------------------------------------

class _QuotedStr(str):
    pass


def _quoted_str_representer(dumper: yaml.Dumper, data: _QuotedStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")


yaml.add_representer(_QuotedStr, _quoted_str_representer)


def _render_yaml_frontmatter(data: Dict[str, object]) -> str:
    prepared: Dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, str) and not re.match(r"^\d+$", value):
            prepared[key] = value
        elif isinstance(value, str):
            prepared[key] = _QuotedStr(value)
        else:
            prepared[key] = value

    yaml_str = yaml.dump(
        prepared,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    )
    return f"---\n{yaml_str}---\n"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _compact_lines(lines: List[str]) -> str:
    result: List[str] = []
    for line in lines:
        if line == "" and result and result[-1] == "":
            continue
        result.append(line)
    return "\n".join(result).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Convert USLM XML to Markdown")
    parser.add_argument("input_xml", help="Path to input USLM XML file")
    parser.add_argument("output_dir", help="Output directory for markdown files")
    parser.add_argument(
        "--mode",
        choices=["chapter", "section"],
        default="chapter",
        help="Output mode (default: chapter)",
    )
    args = parser.parse_args()

    title_ir = parse_xml(args.input_xml, link_mode=args.mode)
    os.makedirs(args.output_dir, exist_ok=True)

    if args.mode == "chapter":
        chapters: Dict[str, List[SectionIR]] = {}
        for section in title_ir.sections:
            ch = section.hierarchy.get("chapter", "")
            chapters.setdefault(ch, []).append(section)

        for chapter_num, sections in chapters.items():
            if not chapter_num:
                filename = "uncategorized.md"
            else:
                ch_info = next((c for c in title_ir.chapters if c.number == chapter_num), None)
                heading = ch_info.heading if ch_info else ""
                safe_id = chapter_file_safe_id(chapter_num)
                slug = slugify(heading) if heading else ""
                filename = f"chapter-{safe_id}-{slug}.md" if slug else f"chapter-{safe_id}.md"

            md = render_chapter_markdown(title_ir, chapter_num, sections)
            with open(os.path.join(args.output_dir, filename), "w") as f:
                f.write(md)

        index_md = render_title_index(title_ir)
        with open(os.path.join(args.output_dir, "title-index.md"), "w") as f:
            f.write(index_md)

    else:
        for section in title_ir.sections:
            safe_id = section_file_safe_id(section.section_number)
            filename = f"section-{safe_id}.md"
            md = render_section_markdown(section)
            with open(os.path.join(args.output_dir, filename), "w") as f:
                f.write(md)


if __name__ == "__main__":
    main()
