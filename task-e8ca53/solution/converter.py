#!/usr/bin/env python3
"""USLM XML to structured Markdown converter - chapter mode.

"""

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional


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


@dataclass
class ContentNode:
    type: str
    label: str = ""
    heading: str = ""
    text: str = ""
    children: List["ContentNode"] = field(default_factory=list)


@dataclass
class StatutoryNote:
    heading: str = ""
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
    section_chapter_map: Dict[str, str] = field(default_factory=dict)
    source_url: str = ""


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def nws(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def get_child(el: ET.Element, tag: str) -> Optional[ET.Element]:
    for c in el:
        if strip_ns(c.tag) == tag:
            return c
    return None


def get_children(el: ET.Element, tag: str) -> List[ET.Element]:
    return [c for c in el if strip_ns(c.tag) == tag]


def clean_num(value: str) -> str:
    value = nws(value)
    value = re.sub(r"^§\s*", "", value)
    for pfx in ["Title", "Subtitle", "Subchapter", "Subpart", "Part", "Chapter"]:
        value = re.sub(rf"^{pfx}\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[.\u2014]+$", "", value)
    return value.strip()


def read_num(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    v = el.get("value", "")
    if v:
        return nws(v)
    return clean_num(nws(el.text or ""))


def extract_mixed(el: Optional[ET.Element], title_number: int = 0) -> str:
    if el is None:
        return ""
    parts: List[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        tag = strip_ns(child.tag)
        if tag == "ref":
            href = child.get("href", "")
            link_text = extract_mixed(child, title_number)
            md_link = make_chapter_link(href)
            if md_link:
                parts.append(f"[{link_text}]({md_link})")
            else:
                parts.append(link_text)
        else:
            parts.append(extract_mixed(child, title_number))
        if child.tail:
            parts.append(child.tail)
    return nws("".join(parts))


def make_chapter_link(href: str) -> Optional[str]:
    m = re.match(r"^/us/usc/t(\d+)/s(.+)$", href)
    if not m:
        return None
    title_num = int(m.group(1))
    section_tail = m.group(2).strip()
    if not section_tail:
        return None
    return (
        f"https://uscode.house.gov/view.xhtml?"
        f"req=granuleid:USC-prelim-title{title_num}-section{section_tail}"
        f"&num=0&edition=prelim"
    )


def slugify(text: str) -> str:
    text = nws(text).lower()
    text = re.sub(r"['\"\u201c\u201d\u2018\u2019]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def chapter_file_id(chapter: str) -> str:
    chapter = chapter.strip()
    if re.match(r"^\d+$", chapter):
        return chapter.zfill(3)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", chapter.lower())).strip("-") or "unnamed"


def section_anchor(section_number: str) -> str:
    normalized = nws(section_number).lower()
    normalized = re.sub(r"[^a-z0-9-]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return f"section-{normalized or 'unknown'}"


def canonical_section_url(title_num: int, section_num: str) -> str:
    return (
        f"https://uscode.house.gov/view.xhtml?"
        f"req=granuleid:USC-prelim-title{title_num}-section{section_num}"
        f"&num=0&edition=prelim"
    )


def parse_xml(xml_path: str) -> TitleIR:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    meta_node = get_child(root, "meta")
    main_node = get_child(root, "main")
    title_node = get_child(main_node, "title") if main_node is not None else None
    if title_node is None:
        raise ValueError("Could not find <title> element")

    title_number = _parse_title_number(read_num(get_child(title_node, "num")))
    heading_el = get_child(title_node, "heading")
    heading = extract_mixed(heading_el, title_number) if heading_el is not None else ""
    positive_law = _read_positive_law(meta_node)

    title_ir = TitleIR(
        title_number=title_number,
        heading=heading,
        positive_law=positive_law,
        source_url=(
            f"https://uscode.house.gov/view.xhtml?"
            f"req=granuleid:USC-prelim-title{title_number}"
            f"&num=0&edition=prelim"
        ),
    )

    _collect_chapters(title_node, title_ir)
    _collect_sections(title_node, title_ir, title_number, current_chapter="")
    return title_ir


def _parse_title_number(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        m = re.search(r"\d+", value)
        return int(m.group()) if m else 0


def _read_positive_law(meta: Optional[ET.Element]) -> Optional[bool]:
    if meta is None:
        return None
    for prop in get_children(meta, "property"):
        if prop.get("role") == "is-positive-law":
            text = nws(prop.text or "")
            if text == "yes":
                return True
            if text == "no":
                return False
    return None


def _collect_chapters(node: ET.Element, title_ir: TitleIR):
    for tag in HIERARCHY_TAGS:
        for child in get_children(node, tag):
            if tag == "chapter":
                num = read_num(get_child(child, "num"))
                heading_el = get_child(child, "heading")
                heading = extract_mixed(heading_el, title_ir.title_number) if heading_el is not None else ""
                if num and not any(c.number == num and c.heading == heading for c in title_ir.chapters):
                    title_ir.chapters.append(ChapterInfo(number=num, heading=heading))
            _collect_chapters(child, title_ir)


def _collect_sections(
    node: ET.Element,
    title_ir: TitleIR,
    title_number: int,
    current_chapter: str,
    inside_note: bool = False,
):
    for tag in HIERARCHY_TAGS:
        for child in get_children(node, tag):
            ch = current_chapter
            if tag == "chapter":
                ch = read_num(get_child(child, "num"))
            _collect_sections(child, title_ir, title_number, ch, inside_note)

    for sec_el in get_children(node, "section"):
        if not inside_note:
            section_ir = _parse_section(sec_el, title_number)
            title_ir.sections.append(section_ir)
            if current_chapter:
                title_ir.section_chapter_map[section_ir.section_number] = current_chapter
        _collect_sections(sec_el, title_ir, title_number, current_chapter, inside_note)

    for child in node:
        tag = strip_ns(child.tag)
        if tag in HIERARCHY_TAGS or tag == "section":
            continue
        next_inside = inside_note or tag in ("note", "notes")
        _collect_sections(child, title_ir, title_number, current_chapter, next_inside)


def _parse_section(sec_el: ET.Element, title_number: int) -> SectionIR:
    section_number = read_num(get_child(sec_el, "num"))
    heading_el = get_child(sec_el, "heading")
    heading = extract_mixed(heading_el, title_number) if heading_el is not None else ""
    status_el = get_child(sec_el, "status")
    status = nws(status_el.text or "") if status_el is not None else "in-force"
    if status not in ("in-force", "repealed", "transferred", "omitted"):
        status = "in-force"

    section_ir = SectionIR(
        title_number=title_number,
        section_number=section_number,
        heading=heading,
        status=status,
        source=canonical_section_url(title_number, section_number),
    )

    content_el = get_child(sec_el, "content")
    if content_el is not None:
        section_ir.content = _parse_content(content_el, title_number)

    _parse_notes(sec_el, section_ir, title_number)
    return section_ir


def _parse_content(node: ET.Element, title_number: int) -> List[ContentNode]:
    content: List[ContentNode] = []
    for child in node:
        tag = strip_ns(child.tag)
        if tag == "chapeau":
            text = extract_mixed(child, title_number)
            if text:
                content.append(ContentNode(type="text", text=text))
        elif tag in SECTION_BODY_SET:
            content.append(_parse_labeled_node(tag, child, title_number))
        elif tag == "continuation":
            text = extract_mixed(child, title_number)
            if text:
                content.append(ContentNode(type="text", text=text))
        elif tag in ("text", "p", "content"):
            text = extract_mixed(child, title_number)
            if text:
                content.append(ContentNode(type="text", text=text))

    if not content:
        text = extract_mixed(node, title_number)
        if text:
            content.append(ContentNode(type="text", text=text))

    return [c for c in content if not (c.type == "text" and not c.text)]


def _parse_labeled_node(tag: str, el: ET.Element, title_number: int) -> ContentNode:
    label = read_num(get_child(el, "num"))
    heading_el = get_child(el, "heading")
    heading = extract_mixed(heading_el, title_number) if heading_el is not None else ""

    inline_parts: List[str] = []
    children: List[ContentNode] = []

    for child in el:
        ctag = strip_ns(child.tag)
        if ctag in ("num", "heading"):
            continue
        if ctag == "chapeau":
            text = extract_mixed(child, title_number)
            if text:
                inline_parts.append(text)
        elif ctag in SECTION_BODY_SET:
            children.append(_parse_labeled_node(ctag, child, title_number))
        elif ctag == "continuation":
            text = extract_mixed(child, title_number)
            if text:
                children.append(ContentNode(type="text", text=text))
        elif ctag in ("content", "text", "p"):
            text = extract_mixed(child, title_number)
            if text:
                inline_parts.append(text)

    return ContentNode(
        type=tag,
        label=label,
        heading=heading,
        text=" ".join(inline_parts) if inline_parts else "",
        children=[c for c in children if not (c.type == "text" and not c.text)],
    )


def _parse_notes(sec_el: ET.Element, section_ir: SectionIR, title_number: int):
    for notes_el in get_children(sec_el, "notes"):
        for note_el in get_children(notes_el, "note"):
            heading_el = get_child(note_el, "heading")
            heading = extract_mixed(heading_el, title_number) if heading_el is not None else ""
            paragraphs: List[str] = []
            for p_el in get_children(note_el, "p"):
                text = extract_mixed(p_el, title_number)
                if text:
                    paragraphs.append(text)
            if paragraphs:
                section_ir.statutory_notes.append(
                    StatutoryNote(heading=heading, text="\n\n".join(paragraphs))
                )

    for note_el in get_children(sec_el, "note"):
        type_el = get_child(note_el, "type")
        kind = nws(type_el.text or "") if type_el is not None else "misc"
        if kind == "source-credit":
            continue
        text_el = get_child(note_el, "text")
        text = extract_mixed(text_el, title_number) if text_el is not None else ""
        if not text:
            text = extract_mixed(note_el, title_number)
        if text:
            section_ir.editorial_notes.append(EditorialNote(kind=kind, text=text))


def render_chapter_mode(title_ir: TitleIR) -> Dict[str, str]:
    files: Dict[str, str] = {}
    title_dir = f"title-{str(title_ir.title_number).zfill(2)}"

    chapter_sections: Dict[str, List[SectionIR]] = {}
    for section in title_ir.sections:
        ch = title_ir.section_chapter_map.get(section.section_number, "")
        if ch not in chapter_sections:
            chapter_sections[ch] = []
        chapter_sections[ch].append(section)

    for chapter_info in title_ir.chapters:
        ch_num = chapter_info.number
        sections = chapter_sections.get(ch_num, [])
        ch_id = chapter_file_id(ch_num)
        ch_slug = slugify(chapter_info.heading)
        filename = f"chapter-{ch_id}-{ch_slug}.md" if ch_slug else f"chapter-{ch_id}.md"
        filepath = f"{title_dir}/{filename}"

        fm = {
            "title": title_ir.title_number,
            "chapter": ch_num,
            "heading": chapter_info.heading,
            "section_count": len(sections),
            "source": title_ir.source_url,
        }
        body = _render_embedded_sections(sections)
        files[filepath] = _format_frontmatter(fm) + body

    idx_fm = {
        "title": title_ir.title_number,
        "heading": title_ir.heading,
        "positive_law": title_ir.positive_law if title_ir.positive_law is not None else False,
        "sections": len(title_ir.sections),
    }
    if title_ir.chapters:
        idx_fm["chapters"] = len(title_ir.chapters)

    idx_lines = [f"# Title {title_ir.title_number}. {title_ir.heading}"]
    if title_ir.chapters:
        idx_lines.append("")
        idx_lines.append("## Chapters")
        for ch in title_ir.chapters:
            idx_lines.append(f"- {ch.number} \u2014 {ch.heading}")

    idx_body = "\n".join(idx_lines) + "\n"
    files[f"{title_dir}/title-index.md"] = _format_frontmatter(idx_fm) + idx_body

    return files


def _format_frontmatter(data: dict) -> str:
    import yaml
    yml = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{yml}---\n"


def _render_embedded_sections(sections: List[SectionIR]) -> str:
    bodies: List[str] = []
    for section in sections:
        anchor = section_anchor(section.section_number)
        body = _render_section_body(section, heading_level=2, anchor=anchor)
        bodies.append(body)
    return "\n\n".join(bodies).rstrip() + "\n"


def _render_section_body(section: SectionIR, heading_level: int = 2, anchor: str = "") -> str:
    lines: List[str] = []

    if anchor:
        lines.append(f'<a id="{anchor}"></a>')

    heading_prefix = "#" * heading_level
    if section.heading:
        lines.append(f"{heading_prefix} \u00a7 {section.section_number}. {section.heading}")
    else:
        lines.append(f"{heading_prefix} \u00a7 {section.section_number}.")

    content_lines = _render_content_nodes(section.content)
    if content_lines:
        first = content_lines[0]
        if _is_labeled_line(first):
            lines.extend(content_lines)
        else:
            lines.append("")
            lines.extend(content_lines)

    if section.statutory_notes:
        lines.append("")
        lines.append(f"{'#' * (heading_level + 1)} Statutory Notes")
        for note in section.statutory_notes:
            lines.append("")
            if note.heading:
                lines.append(f"{'#' * (heading_level + 2)} {note.heading}")
            if note.text:
                lines.extend(note.text.split("\n"))

    if section.editorial_notes:
        lines.append("")
        lines.append(f"{'#' * (heading_level + 1)} Notes")
        for note in section.editorial_notes:
            lines.append("")
            lines.extend(note.text.split("\n"))

    return _compact_lines(lines)


def _render_content_nodes(nodes: List[ContentNode]) -> List[str]:
    lines: List[str] = []
    for node in nodes:
        rendered = _render_content_node(node, indent=0)
        if not rendered:
            continue
        if lines and _should_separate(lines, rendered):
            lines.append("")
        lines.extend(rendered)
    return lines


def _should_separate(existing: List[str], next_lines: List[str]) -> bool:
    last = next((l for l in reversed(existing) if l != ""), None)
    first = next((l for l in next_lines if l != ""), None)
    if not last or not first:
        return False
    return _is_labeled_line(first) and not re.match(r"^#+\s", last) and not re.match(r'^<a id=', last)


def _is_labeled_line(line: str) -> bool:
    return bool(re.match(r"^\s*(?:\*\*)?\([^)]+\)", line))


def _render_content_node(node: ContentNode, indent: int) -> List[str]:
    if node.type == "text":
        return [f"{' ' * indent}{node.text}"] if node.text else []

    lines: List[str] = []
    label = _format_label(node.label)

    if node.type == "subsection":
        heading_part = " ".join(filter(None, [label, node.heading]))
        if heading_part and node.text:
            lines.append(f"**{heading_part}** {node.text}")
        elif heading_part:
            lines.append(f"**{heading_part}**")
        elif node.text:
            lines.append(node.text)

        for child in node.children:
            child_lines = _render_content_node(child, 0)
            if child_lines:
                if lines and _should_separate(lines, child_lines):
                    lines.append("")
                lines.extend(child_lines)
    else:
        INDENT_MAP = {
            "paragraph": 0, "subparagraph": 2, "clause": 4,
            "subclause": 6, "item": 8, "subitem": 10,
        }
        my_indent = INDENT_MAP.get(node.type, indent)

        if node.heading and node.text:
            if my_indent == 0:
                line = f"{label} **{node.heading}** \u2014 {node.text}"
            else:
                line = f"{' ' * my_indent}{label} *{node.heading}* \u2014 {node.text}"
        elif node.heading:
            if my_indent == 0:
                line = f"{label} **{node.heading}**"
            else:
                line = f"{' ' * my_indent}{label} *{node.heading}*"
        elif node.text:
            line = f"{' ' * my_indent}{label} {node.text}" if label else f"{' ' * my_indent}{node.text}"
        else:
            line = f"{' ' * my_indent}{label}" if label else ""

        if line:
            lines.append(line)

        child_indent = my_indent + 2
        for child in node.children:
            child_lines = _render_content_node(child, child_indent)
            if child_lines:
                if lines and _should_separate(lines, child_lines):
                    lines.append("")
                lines.extend(child_lines)

    return lines


def _format_label(label: str) -> str:
    label = label.strip()
    if not label:
        return ""
    return label if label.startswith("(") else f"({label})"


def _compact_lines(lines: List[str]) -> str:
    result = []
    for i, line in enumerate(lines):
        if line == "" and i > 0 and result and result[-1] == "":
            continue
        result.append(line)
    return "\n".join(result).rstrip() + "\n"
