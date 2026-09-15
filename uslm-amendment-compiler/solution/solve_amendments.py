#!/usr/bin/env python3
"""
USLM Amendment Compiler: parses a USLM XML public law and applies its
amendment instructions to an existing statute represented as JSON.
"""

import json
import re
import sys
from lxml import etree

USLM = "http://schemas.gpo.gov/xml/uslm"


def T(name):
    """Namespaced USLM tag."""
    return f"{{{USLM}}}{name}"


def text_of(elem):
    """All text content from an element tree, concatenated."""
    if elem is None:
        return ""
    return "".join(elem.itertext())


def strip_outer_quotes(s):
    """Strip the outermost USLM quotation marks (the amendment quoting convention)."""
    s = s.strip()
    if s.startswith("\u201c") or s.startswith('"'):
        s = s[1:]
    if s.endswith("\u201d") or s.endswith('"'):
        s = s[:-1]
    return s.strip()


def first_ref_href(elem):
    """Return the href of the first <ref> descendant, or ''."""
    ref = elem.find(f".//{T('ref')}")
    return ref.get("href", "") if ref is not None else ""


def parse_path(href):
    """Parse /us/usc/t6/s1201/b/3/C into {section, subsection?, paragraph?, subparagraph?}."""
    result = {}
    m = re.search(r"/s(\d+)(.*)", href)
    if not m:
        return result
    result["section"] = m.group(1)
    rest = [p for p in m.group(2).strip("/").split("/") if p]
    idx = 0
    if idx < len(rest) and len(rest[idx]) == 1 and rest[idx].islower():
        result["subsection"] = rest[idx]
        idx += 1
    if idx < len(rest) and rest[idx].isdigit():
        result["paragraph"] = rest[idx]
        idx += 1
    if idx < len(rest) and len(rest[idx]) == 1 and rest[idx].isalpha():
        result["subparagraph"] = rest[idx]
        idx += 1
    return result


# ── provision accessors ────────────────────────────────────────────────

def _resolve(law, path):
    """Return (container_dict, key) for a path so caller can get/set/delete."""
    sec = law["sections"].get(path.get("section"))
    if sec is None:
        return None, None

    if "subsection" in path:
        sub = sec.get("subsections", {}).get(path["subsection"])
        if sub is None:
            return None, None
        if "paragraph" in path:
            para = sub.get("paragraphs", {}).get(path["paragraph"])
            if para is None:
                return None, None
            if "subparagraph" in path:
                return para.setdefault("subparagraphs", {}), path["subparagraph"]
            return sub["paragraphs"], path["paragraph"]
        return sec["subsections"], path["subsection"]

    if "paragraph" in path:
        para = sec.get("paragraphs", {}).get(path["paragraph"])
        if para is None:
            return None, None
        if "subparagraph" in path:
            return para.setdefault("subparagraphs", {}), path["subparagraph"]
        return sec["paragraphs"], path["paragraph"]

    return law["sections"], path["section"]


def get_text(law, path):
    container, key = _resolve(law, path)
    if container is None:
        return None
    item = container.get(key)
    return item.get("text") if isinstance(item, dict) else None


def set_text(law, path, new_text):
    container, key = _resolve(law, path)
    if container is not None and key in container:
        container[key]["text"] = new_text


def delete_provision(law, path):
    container, key = _resolve(law, path)
    if container is not None:
        container.pop(key, None)


# ── quoted-content extraction ──────────────────────────────────────────

def _clean_heading(raw):
    """Strip trailing '.—' / '.--' from heading text."""
    raw = raw.strip()
    raw = re.sub(r"\.\s*[\u2014\u2013\-]+\s*$", "", raw)
    return raw.strip()


def extract_level(elem):
    """Convert a USLM level element inside <quotedContent> to a dict.

    Returns {"level_type": ..., "num": ..., "data": {...}}.
    """
    tag_local = etree.QName(elem.tag).localname
    result = {}

    # num
    num_elem = elem.find(T("num"))
    num_val = num_elem.get("value", "") if num_elem is not None else ""

    # heading
    heading_elem = elem.find(T("heading"))
    if heading_elem is not None:
        result["heading"] = _clean_heading(text_of(heading_elem))

    # chapeau → text
    chapeau = elem.find(T("chapeau"))
    content = elem.find(T("content"))
    child_paras = elem.findall(T("paragraph"))
    child_subparas = elem.findall(T("subparagraph"))

    if chapeau is not None:
        result["text"] = strip_outer_quotes(text_of(chapeau))
    elif content is not None and not child_paras and not child_subparas:
        result["text"] = strip_outer_quotes(text_of(content))

    # child paragraphs
    if child_paras:
        paras = {}
        for p in child_paras:
            pn = p.find(T("num"))
            pv = pn.get("value", "") if pn is not None else ""
            pc = p.find(T("content"))
            if pc is not None:
                paras[pv] = {"text": strip_outer_quotes(text_of(pc))}
        result["paragraphs"] = paras

    # child subparagraphs
    if child_subparas:
        sps = {}
        for sp in child_subparas:
            spn = sp.find(T("num"))
            spv = spn.get("value", "") if spn is not None else ""
            spc = sp.find(T("content"))
            if spc is not None:
                sps[spv] = {"text": strip_outer_quotes(text_of(spc))}
        result["subparagraphs"] = sps

    return {"level_type": tag_local, "num": num_val, "data": result}


def extract_quoted_content(qc):
    """Try each known level type inside a <quotedContent>."""
    for lt in ("subsection", "paragraph", "subparagraph"):
        child = qc.find(T(lt))
        if child is not None:
            return extract_level(child)
    return None


# ── amendment application helpers ──────────────────────────────────────

def apply_substitution(law, path, old, new, global_replace=False):
    cur = get_text(law, path)
    if cur is None:
        print(f"WARNING: no text at {path}", file=sys.stderr)
        return
    if global_replace:
        set_text(law, path, cur.replace(old, new))
    else:
        set_text(law, path, cur.replace(old, new, 1))


def add_at_end(law, target, qc_info):
    """Add a provision at the end of the container identified by target."""
    lt = qc_info["level_type"]
    num = qc_info["num"]
    data = qc_info["data"]
    sec = law["sections"].get(target.get("section"))
    if sec is None:
        return

    if lt == "subsection":
        sec.setdefault("subsections", {})[num] = data
    elif lt == "paragraph":
        if "subsection" in target:
            sub = sec.get("subsections", {}).get(target["subsection"])
            if sub is not None:
                if "paragraph" in target:
                    para = sub.get("paragraphs", {}).get(target["paragraph"])
                    if para is not None:
                        para.setdefault("subparagraphs", {})[num] = data
                else:
                    sub.setdefault("paragraphs", {})[num] = data
        else:
            sec.setdefault("paragraphs", {})[num] = data
    elif lt == "subparagraph":
        if "subsection" in target and "paragraph" in target:
            sub = sec.get("subsections", {}).get(target["subsection"])
            if sub:
                para = sub.get("paragraphs", {}).get(target["paragraph"])
                if para:
                    para.setdefault("subparagraphs", {})[num] = data


def insert_after(law, target, qc_info):
    """Insert is functionally the same as add for dict-based storage."""
    add_at_end(law, target, qc_info)


def replace_provision(law, target, qc_info):
    """Full replacement of a provision."""
    sec = law["sections"].get(target.get("section"))
    if sec is None:
        return
    if "subsection" in target:
        sec.setdefault("subsections", {})[target["subsection"]] = qc_info["data"]
    elif "paragraph" in target:
        sec.setdefault("paragraphs", {})[target["paragraph"]] = qc_info["data"]


def redesignate(law, parent_target, content_elem):
    """Handle redesignation by parsing the natural-language instruction."""
    ft = text_of(content_elem)
    m = re.search(r"subsection\s+\((\w+)\)\s+as\s+subsection\s+\((\w+)\)", ft)
    if m:
        old_k, new_k = m.group(1), m.group(2)
        sec = law["sections"].get(parent_target.get("section"))
        if sec and "subsections" in sec and old_k in sec["subsections"]:
            sec["subsections"][new_k] = sec["subsections"].pop(old_k)
            return
    m = re.search(r"paragraph\s+\((\w+)\)\s+as\s+paragraph\s+\((\w+)\)", ft)
    if m:
        old_k, new_k = m.group(1), m.group(2)
        sec = law["sections"].get(parent_target.get("section"))
        if sec is None:
            return
        if "subsection" in parent_target:
            sub = sec.get("subsections", {}).get(parent_target["subsection"])
            if sub and "paragraphs" in sub and old_k in sub["paragraphs"]:
                sub["paragraphs"][new_k] = sub["paragraphs"].pop(old_k)


# ── content-level dispatch ────────────────────────────────────────────

def _action_types(elem):
    return [a.get("type", "") for a in elem.findall(f".//{T('amendingAction')}")]


def _quoted_texts(elem):
    return [text_of(qt) for qt in elem.findall(f".//{T('quotedText')}")]


def _quoted_contents(elem):
    return elem.findall(f".//{T('quotedContent')}")


def process_content(content_elem, law, fallback_target=None):
    """Interpret a <content> element that carries amendment instructions."""
    ft = text_of(content_elem)
    href = first_ref_href(content_elem)
    target = parse_path(href) if href else (fallback_target or {})
    if not target.get("section") and fallback_target:
        target = dict(fallback_target)

    atypes = _action_types(content_elem)
    qtexts = _quoted_texts(content_elem)
    qconts = _quoted_contents(content_elem)

    # full replacement ("to read as follows")
    if "to read as follows" in ft and qconts:
        qc = extract_quoted_content(qconts[0])
        if qc:
            replace_provision(law, target, qc)
        return

    # add at end
    if "add" in atypes and qconts:
        qc = extract_quoted_content(qconts[0])
        if qc:
            # Determine the correct parent target.
            # If the target path already points deeper than the level being added,
            # use it as-is; otherwise fall back.
            add_at_end(law, target if target.get("section") else fallback_target, qc)
        return

    # insert after
    if "insert" in atypes and qconts:
        qc = extract_quoted_content(qconts[0])
        if qc:
            # parent target for insert
            pt = target if target.get("section") else fallback_target
            insert_after(law, pt, qc)
        return

    # redesignation
    if "redesignate" in atypes:
        redesignate(law, fallback_target or target, content_elem)
        return

    # repeal / strike a provision
    if "repeal" in atypes:
        delete_provision(law, target)
        return

    # text substitution (delete + insert with quotedText)
    if "delete" in atypes and "insert" in atypes and len(qtexts) == 2:
        gl = "each place" in ft
        apply_substitution(law, target, qtexts[0], qtexts[1], gl)
        return

    # Adding at end with quotedContent at the section level
    if "adding" in ft and "at the end" in ft and qconts:
        qc = extract_quoted_content(qconts[0])
        if qc:
            add_at_end(law, target if target.get("section") else fallback_target, qc)
        return


# ── section-level traversal ───────────────────────────────────────────

def process_subparagraph(sp_elem, law, parent_target):
    content = sp_elem.find(T("content"))
    if content is not None:
        href = first_ref_href(content)
        target = parse_path(href) if href else dict(parent_target)
        if not target.get("section"):
            target = dict(parent_target)
        process_content(content, law, fallback_target=target)


def process_paragraph(para_elem, law, parent_target):
    subparas = para_elem.findall(T("subparagraph"))
    if subparas:
        # Determine paragraph-level target from chapeau or content
        chapeau = para_elem.find(T("chapeau"))
        content_direct = para_elem.find(T("content"))
        para_target = dict(parent_target)
        if chapeau is not None:
            href = first_ref_href(chapeau)
            if href:
                para_target = parse_path(href)
        elif content_direct is not None:
            # Check for redesignation at paragraph level
            atypes = _action_types(content_direct)
            if "redesignate" in atypes:
                redesignate(law, parent_target, content_direct)
                return
            href = first_ref_href(content_direct)
            if href:
                para_target = parse_path(href)

        for sp in subparas:
            process_subparagraph(sp, law, para_target)
    else:
        content = para_elem.find(T("content"))
        if content is not None:
            href = first_ref_href(content)
            target = parse_path(href) if href else dict(parent_target)
            if not target.get("section"):
                target = dict(parent_target)

            atypes = _action_types(content)
            # redesignation
            if "redesignate" in atypes:
                redesignate(law, parent_target, content)
                return
            # repeal
            if "repeal" in atypes:
                delete_provision(law, target)
                return
            # all other patterns
            process_content(content, law, fallback_target=parent_target)


def process_section(section_elem, law):
    """Process one section of the amending public law."""
    num_elem = section_elem.find(T("num"))
    sec_val = num_elem.get("value", "") if num_elem is not None else ""
    if sec_val == "1":
        return  # skip short title

    # Section has its own subsections → each is an independent amendment unit
    subsections = section_elem.findall(T("subsection"))
    if subsections:
        for sub in subsections:
            content = sub.find(T("content"))
            if content is not None:
                process_content(content, law)
        return

    # Section has a chapeau → paragraphs are amendment instructions
    chapeau = section_elem.find(T("chapeau"))
    if chapeau is not None:
        href = first_ref_href(chapeau)
        parent_target = parse_path(href)
        for para in section_elem.findall(T("paragraph")):
            process_paragraph(para, law, parent_target)
        return

    # Section has direct content
    content = section_elem.find(T("content"))
    if content is not None:
        process_content(content, law)


# ── main ──────────────────────────────────────────────────────────────

def main():
    with open("/app/existing_law.json") as f:
        law = json.load(f)

    tree = etree.parse("/app/public_law.xml")
    root = tree.getroot()
    main_elem = root.find(T("main"))
    if main_elem is None:
        print("ERROR: no <main> element found in public_law.xml", file=sys.stderr)
        sys.exit(1)

    for section in main_elem.findall(T("section")):
        process_section(section, law)

    with open("/app/amended_law.json", "w") as f:
        json.dump(law, f, indent=2)

    print("Wrote /app/amended_law.json")


if __name__ == "__main__":
    main()
