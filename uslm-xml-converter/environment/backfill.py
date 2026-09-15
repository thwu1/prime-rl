#!/usr/bin/env python3
"""USLM-to-Git backfill pipeline."""
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ContentNode:
    type: str
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
    chapters: List[ChapterInfo] = field(default_factory=list)
    sections: List[SectionIR] = field(default_factory=list)


BODY_TAGS = {
    "subsection", "paragraph", "subparagraph",
    "clause", "subclause", "item", "subitem",
}

INDENT_MAP = {
    "subsection": 0, "paragraph": 0, "subparagraph": 2,
    "clause": 4, "subclause": 4, "item": 8, "subitem": 10,
}


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def strip_ns_tree(elem: ET.Element) -> ET.Element:
    elem.tag = strip_ns(elem.tag)
    for child in elem:
        strip_ns_tree(child)
    return elem


def extract_text(elem: Optional[ET.Element]) -> str:
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
            parts.append(extract_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def href_to_url(href: str) -> str:
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


def parse_uslm(xml_path: str) -> TitleIR:
    tree = ET.parse(xml_path)
    root = strip_ns_tree(tree.getroot())
    title_ir = TitleIR()

    title_elem = None
    for elem in root.iter("title"):
        title_elem = elem
        break
    if title_elem is None:
        return title_ir

    num_elem = title_elem.find("num")
    if num_elem is not None:
        title_ir.title_number = int(num_elem.attrib.get("value", "0"))

    heading_elem = title_elem.find("heading")
    if heading_elem is not None:
        title_ir.heading = (heading_elem.text or "").strip()

    for ch_elem in title_elem.iter("chapter"):
        ch_num_elem = ch_elem.find("num")
        ch_heading_elem = ch_elem.find("heading")
        ch_num = ch_num_elem.attrib.get("value", "") if ch_num_elem is not None else ""
        ch_heading = (ch_heading_elem.text or "").strip() if ch_heading_elem is not None else ""
        if not any(c.number == ch_num for c in title_ir.chapters):
            title_ir.chapters.append(ChapterInfo(number=ch_num, heading=ch_heading))
        for sec_elem in ch_elem.findall("section"):
            title_ir.sections.append(
                parse_section(sec_elem, title_ir.title_number, ch_num)
            )

    return title_ir


def parse_section(elem: ET.Element, title_number: int, chapter: str) -> SectionIR:
    section = SectionIR(title_number=title_number, chapter=chapter)

    num_elem = elem.find("num")
    if num_elem is not None:
        section.section_number = num_elem.attrib.get("value", "")

    heading_elem = elem.find("heading")
    if heading_elem is not None:
        section.heading = (heading_elem.text or "").strip()

    content_elem = elem.find("content")
    if content_elem is not None:
        section.content = parse_content_children(content_elem)

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
    nodes: List[ContentNode] = []
    for child in parent:
        tag = strip_ns(child.tag)
        if tag in BODY_TAGS:
            nodes.append(parse_labeled_node(child, tag))
    return nodes


def parse_labeled_node(elem: ET.Element, node_type: str) -> ContentNode:
    node = ContentNode(type=node_type)

    num_elem = elem.find("num")
    if num_elem is not None:
        node.label = num_elem.attrib.get("value", "")

    heading_elem = elem.find("heading")
    if heading_elem is not None:
        node.heading = extract_text(heading_elem)

    chapeau_elem = elem.find("chapeau")
    if chapeau_elem is not None:
        node.text = extract_text(chapeau_elem)

    if not node.text:
        text_elem = elem.find("text")
        if text_elem is not None:
            node.text = extract_text(text_elem)

    cont_elem = elem.find("continuation")
    if cont_elem is not None:
        cont_text = extract_text(cont_elem)
        if cont_text:
            node.children.append(ContentNode(type="text", text=cont_text))

    for child in elem:
        tag = strip_ns(child.tag)
        if tag in BODY_TAGS:
            node.children.append(parse_labeled_node(child, tag))

    return node


def parse_note(elem: ET.Element) -> Note:
    note = Note()
    heading_elem = elem.find("heading")
    if heading_elem is not None:
        note.heading = (heading_elem.text or "").strip()
    paragraphs: List[str] = []
    for p_elem in elem.findall("p"):
        paragraphs.append(extract_text(p_elem))
    note.text = "\n\n".join(paragraphs)
    return note


def format_label(label: str) -> str:
    label = label.strip()
    if not label:
        return ""
    return label if label.startswith("(") else f"({label})"


def is_labeled_line(line: str) -> bool:
    return bool(re.match(r"^\s*(?:\*\*)?\([^)]+\)", line))


def render_content_nodes(nodes: List[ContentNode]) -> List[str]:
    lines: List[str] = []
    for node in nodes:
        rendered = render_node(node)
        if not rendered:
            continue
        if lines and is_labeled_line(rendered[0]):
            lines.append("")
        lines.extend(rendered)
    return lines


def render_node(node: ContentNode) -> List[str]:
    if node.type == "text":
        return [node.text] if node.text else []

    lines: List[str] = []
    label = format_label(node.label)
    indent = INDENT_MAP.get(node.type, 0)

    if node.type == "subsection":
        if label and node.text:
            lines.append(f"{label} {node.text}")
        elif label:
            lines.append(label)
        elif node.text:
            lines.append(node.text)
    else:
        parts = []
        if label:
            parts.append(label)
        if node.text:
            parts.append(node.text)
        line_text = " ".join(parts)
        if line_text:
            lines.append(f"{' ' * indent}{line_text}")

    child_indent = 0 if node.type == "subsection" else indent + 2
    for child in node.children:
        child_lines = render_child_node(child, child_indent)
        if not child_lines:
            continue
        if lines and is_labeled_line(child_lines[0]):
            lines.append("")
        lines.extend(child_lines)

    return lines


def render_child_node(node: ContentNode, parent_child_indent: int) -> List[str]:
    if node.type == "text":
        if not node.text:
            return []
        return [f"{' ' * parent_child_indent}{node.text}"]

    lines: List[str] = []
    label = format_label(node.label)
    indent = INDENT_MAP.get(node.type, parent_child_indent)

    parts = []
    if label:
        parts.append(label)
    if node.text:
        parts.append(node.text)
    line_text = " ".join(parts)
    if line_text:
        lines.append(f"{' ' * indent}{line_text}")

    child_indent = indent + 2
    for child in node.children:
        child_lines = render_child_node(child, child_indent)
        if not child_lines:
            continue
        if lines and is_labeled_line(child_lines[0]):
            lines.append("")
        lines.extend(child_lines)

    return lines


def section_anchor(section_number: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", section_number.lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return f"section-{normalized or 'unknown'}"


def slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def chapter_file_safe_id(chapter_number: str) -> str:
    if chapter_number.isdigit():
        return chapter_number.zfill(3)
    return re.sub(r"[^a-z0-9]+", "-", chapter_number.lower()).strip("-") or "unnamed"


def compact_lines(lines: List[str]) -> str:
    result: List[str] = []
    for line in lines:
        if line == "" and result and result[-1] == "":
            continue
        result.append(line)
    return "\n".join(result).rstrip() + "\n"


def render_section_body(
    section: SectionIR, heading_level: int, notes_level: int,
    note_item_level: int, anchor: Optional[str] = None,
) -> List[str]:
    lines: List[str] = []
    if anchor:
        lines.append(f'<a id="{anchor}"></a>')
    prefix = "#" * heading_level
    heading = (
        f"{prefix} \u00a7 {section.section_number}. {section.heading}"
        if section.heading
        else f"{prefix} \u00a7 {section.section_number}."
    )
    lines.append(heading)
    content_lines = render_content_nodes(section.content)
    if content_lines:
        if is_labeled_line(content_lines[0]):
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
                for text_line in note.text.split("\n"):
                    lines.append(text_line)
    if section.editorial_notes:
        lines.append("")
        lines.append(f"{'#' * notes_level} Notes")
        for note in section.editorial_notes:
            lines.append("")
            if note.text:
                for text_line in note.text.split("\n"):
                    lines.append(text_line)
    return lines


def render_chapter_md(
    title_ir: TitleIR, chapter: ChapterInfo, sections: List[SectionIR],
) -> str:
    fm_lines = [
        "---",
        f"title: {title_ir.title_number}",
        f"chapter: '{chapter.number}'",
        f"heading: {chapter.heading}",
        f"section_count: {len(sections)}",
        f"source: https://uscode.house.gov/view.xhtml?"
        f"req=granuleid:USC-prelim-title{title_ir.title_number}&num=0&edition=prelim",
        "---",
    ]
    section_bodies: List[str] = []
    for sec in sections:
        anchor = section_anchor(sec.section_number)
        body_lines = render_section_body(sec, 2, 3, 4, anchor=anchor)
        section_bodies.append(compact_lines(body_lines))
    body = "\n".join(section_bodies).rstrip() + "\n"
    return "\n".join(fm_lines) + "\n" + body


def main():
    if len(sys.argv) != 4:
        print(
            f"Usage: {sys.argv[0]} <manifest.json> <vintages_dir> <output_repo>",
            file=sys.stderr,
        )
        sys.exit(1)

    manifest_path = sys.argv[1]
    vintages_dir = sys.argv[2]
    repo_path = sys.argv[3]

    with open(manifest_path) as f:
        manifest = json.load(f)

    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
    os.makedirs(repo_path)

    subprocess.run(
        ["git", "init", repo_path],
        check=True, capture_output=True,
    )

    vintage_commits = {}

    for vintage in manifest["vintages"]:
        xml_path = os.path.join(vintages_dir, vintage["id"], "title-99.xml")
        title_ir = parse_uslm(xml_path)

        output_dir = os.path.join(repo_path, manifest["output_prefix"])
        os.makedirs(output_dir, exist_ok=True)

        for fname in os.listdir(output_dir):
            fp = os.path.join(output_dir, fname)
            if os.path.isfile(fp):
                os.remove(fp)

        for chapter in title_ir.chapters:
            chapter_sections = [
                s for s in title_ir.sections if s.chapter == chapter.number
            ]
            md = render_chapter_md(title_ir, chapter, chapter_sections)
            slug = slugify(chapter.heading)
            safe_id = chapter_file_safe_id(chapter.number)
            filename = (
                f"chapter-{safe_id}-{slug}.md" if slug else f"chapter-{safe_id}.md"
            )
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w") as fh:
                fh.write(md)

        commit_msg = (
            f"Update US Code through Public Law "
            f"{vintage['congress']}-{vintage['law_number']}\n\n"
            f"Release point: {vintage['id']}\n"
            f"Year: {vintage['year']}"
        )

        subprocess.run(
            ["git", "-C", repo_path, "add", "."],
            check=True, capture_output=True,
        )

        env = dict(os.environ)
        env["GIT_COMMITTER_NAME"] = manifest["committer_name"]
        env["GIT_COMMITTER_EMAIL"] = manifest["committer_email"]

        subprocess.run(
            ["git", "-C", repo_path, "commit",
             "-m", commit_msg,
             f"--author={vintage['author_name']} <{vintage['author_email']}>"],
            check=True, capture_output=True, env=env,
        )

        sha = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        vintage_commits[vintage["id"]] = sha

    for tag_name, vintage_id in manifest["tags"].items():
        sha = vintage_commits[vintage_id]
        subprocess.run(
            ["git", "-C", repo_path, "tag", tag_name, sha],
            check=True, capture_output=True,
        )

    print("Backfill complete.")


if __name__ == "__main__":
    main()
