#!/usr/bin/env python3
"""
USLM Multi-Law Amendment Reconciler: processes multiple public laws that amend
the same base statute, applying them in enactment order, handling conditional
savings clauses, amendment-on-amendment patterns, and redesignation chains.
Produces both the final amended statute and a structured reconciliation report.
"""

import json
import re
import sys
from lxml import etree

USLM = "http://schemas.gpo.gov/xml/uslm"


def T(name):
    return f"{{{USLM}}}{name}"


def text_of(elem):
    if elem is None:
        return ""
    return "".join(elem.itertext())


def strip_outer_quotes(s):
    s = s.strip()
    if s.startswith("\u201c") or s.startswith('"'):
        s = s[1:]
    if s.endswith("\u201d") or s.endswith('"'):
        s = s[:-1]
    return s.strip()


def first_ref_href(elem):
    ref = elem.find(f".//{T('ref')}")
    return ref.get("href", "") if ref is not None else ""


def parse_path(href):
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


def path_str(path):
    parts = [f"/us/usc/t6/s{path.get('section', '?')}"]
    if "subsection" in path:
        parts.append(path["subsection"])
    if "paragraph" in path:
        parts.append(path["paragraph"])
    if "subparagraph" in path:
        parts.append(path["subparagraph"])
    return "/".join(parts)


# ── provision accessors ──────────────────────────────────────────


def _resolve(law, path):
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


def provision_exists(law, path):
    if not path.get("section"):
        return False
    container, key = _resolve(law, path)
    if container is None:
        return False
    return key in container


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


# ── heading / quoted-content extraction ──────────────────────────


def _clean_heading(raw):
    raw = raw.strip()
    raw = re.sub(r"\.\s*[\u2014\u2013\-]+\s*$", "", raw)
    return raw.strip()


def extract_level(elem):
    tag_local = etree.QName(elem.tag).localname
    result = {}
    num_elem = elem.find(T("num"))
    num_val = num_elem.get("value", "") if num_elem is not None else ""
    heading_elem = elem.find(T("heading"))
    if heading_elem is not None:
        result["heading"] = _clean_heading(text_of(heading_elem))
    chapeau = elem.find(T("chapeau"))
    content = elem.find(T("content"))
    child_paras = elem.findall(T("paragraph"))
    child_subparas = elem.findall(T("subparagraph"))
    if chapeau is not None:
        result["text"] = strip_outer_quotes(text_of(chapeau))
    elif content is not None and not child_paras and not child_subparas:
        result["text"] = strip_outer_quotes(text_of(content))
    if child_paras:
        paras = {}
        for p in child_paras:
            pn = p.find(T("num"))
            pv = pn.get("value", "") if pn is not None else ""
            pc = p.find(T("content"))
            if pc is not None:
                paras[pv] = {"text": strip_outer_quotes(text_of(pc))}
        result["paragraphs"] = paras
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
    for lt in ("subsection", "paragraph", "subparagraph"):
        child = qc.find(T(lt))
        if child is not None:
            return extract_level(child)
    return None


# ── amendment application helpers ────────────────────────────────


def apply_substitution(law, path, old, new, global_replace=False):
    cur = get_text(law, path)
    if cur is None:
        return False
    if old not in cur:
        return False
    if global_replace:
        set_text(law, path, cur.replace(old, new))
    else:
        set_text(law, path, cur.replace(old, new, 1))
    return True


def add_at_end(law, target, qc_info):
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


def replace_provision(law, target, qc_info):
    sec = law["sections"].get(target.get("section"))
    if sec is None:
        return
    if "subsection" in target:
        sec.setdefault("subsections", {})[target["subsection"]] = qc_info["data"]
    elif "paragraph" in target:
        sec.setdefault("paragraphs", {})[target["paragraph"]] = qc_info["data"]


def redesignate(law, parent_target, content_elem):
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


# ── conditional clause detection ─────────────────────────────────


def is_conditional_skip(text, content_elem, law):
    """Detect a conditional savings clause and determine whether to skip."""
    if "has not been added by prior enactment" in text:
        href = first_ref_href(content_elem)
        if href:
            target = parse_path(href)
            if provision_exists(law, target):
                return True, target
    return False, None


# ── action type helpers ──────────────────────────────────────────


def _action_types(elem):
    return [a.get("type", "") for a in elem.findall(f".//{T('amendingAction')}")]


def _quoted_texts(elem):
    return [text_of(qt) for qt in elem.findall(f".//{T('quotedText')}")]


def _quoted_contents(elem):
    return elem.findall(f".//{T('quotedContent')}")


# ── content-level dispatch ───────────────────────────────────────


def process_content(content_elem, law, fallback_target, law_id, sec_num, log):
    ft = text_of(content_elem)
    href = first_ref_href(content_elem)
    target = parse_path(href) if href else (fallback_target or {})
    if not target.get("section") and fallback_target:
        target = dict(fallback_target)

    # Check for conditional savings clause before any processing
    skip, skip_target = is_conditional_skip(ft, content_elem, law)
    if skip:
        log.append({
            "source_law": law_id,
            "source_section": sec_num,
            "target_provision": path_str(skip_target),
            "action_type": "conditional_add",
            "status": "skipped",
            "skip_reason": "Provision already added by prior enactment",
        })
        return

    atypes = _action_types(content_elem)
    qtexts = _quoted_texts(content_elem)
    qconts = _quoted_contents(content_elem)

    # Full replacement ("to read as follows")
    if "to read as follows" in ft and qconts:
        qc = extract_quoted_content(qconts[0])
        if qc:
            replace_provision(law, target, qc)
            log.append({
                "source_law": law_id,
                "source_section": sec_num,
                "target_provision": path_str(target),
                "action_type": "replace",
                "status": "applied",
            })
        return

    # Add at end
    if "add" in atypes and qconts:
        qc = extract_quoted_content(qconts[0])
        if qc:
            pt = target if target.get("section") else fallback_target
            add_at_end(law, pt, qc)
            log.append({
                "source_law": law_id,
                "source_section": sec_num,
                "target_provision": path_str(pt),
                "action_type": "add",
                "status": "applied",
            })
        return

    # Insert after
    if "insert" in atypes and qconts:
        qc = extract_quoted_content(qconts[0])
        if qc:
            pt = target if target.get("section") else fallback_target
            add_at_end(law, pt, qc)
            log.append({
                "source_law": law_id,
                "source_section": sec_num,
                "target_provision": path_str(pt),
                "action_type": "insert",
                "status": "applied",
            })
        return

    # Redesignation
    if "redesignate" in atypes:
        redesignate(law, fallback_target or target, content_elem)
        log.append({
            "source_law": law_id,
            "source_section": sec_num,
            "target_provision": path_str(fallback_target or target),
            "action_type": "redesignate",
            "status": "applied",
        })
        return

    # Repeal
    if "repeal" in atypes:
        delete_provision(law, target)
        log.append({
            "source_law": law_id,
            "source_section": sec_num,
            "target_provision": path_str(target),
            "action_type": "repeal",
            "status": "applied",
        })
        return

    # Text substitution (delete + insert with quotedText)
    if "delete" in atypes and "insert" in atypes and len(qtexts) == 2:
        gl = "each place" in ft
        apply_substitution(law, target, qtexts[0], qtexts[1], gl)
        log.append({
            "source_law": law_id,
            "source_section": sec_num,
            "target_provision": path_str(target),
            "action_type": "substitute",
            "status": "applied",
        })
        return

    # Fallback: adding at the end with natural language
    if "adding" in ft and "at the end" in ft and qconts:
        qc = extract_quoted_content(qconts[0])
        if qc:
            pt = target if target.get("section") else fallback_target
            add_at_end(law, pt, qc)
            log.append({
                "source_law": law_id,
                "source_section": sec_num,
                "target_provision": path_str(pt),
                "action_type": "add",
                "status": "applied",
            })
        return


# ── section-level traversal ──────────────────────────────────────


def process_subparagraph(sp_elem, law, parent_target, law_id, sec_num, log):
    content = sp_elem.find(T("content"))
    if content is not None:
        href = first_ref_href(content)
        target = parse_path(href) if href else dict(parent_target)
        if not target.get("section"):
            target = dict(parent_target)
        process_content(content, law, target, law_id, sec_num, log)


def process_paragraph(para_elem, law, parent_target, law_id, sec_num, log):
    subparas = para_elem.findall(T("subparagraph"))
    if subparas:
        chapeau = para_elem.find(T("chapeau"))
        content_direct = para_elem.find(T("content"))
        para_target = dict(parent_target)
        if chapeau is not None:
            href = first_ref_href(chapeau)
            if href:
                para_target = parse_path(href)
        elif content_direct is not None:
            atypes = _action_types(content_direct)
            if "redesignate" in atypes:
                redesignate(law, parent_target, content_direct)
                log.append({
                    "source_law": law_id,
                    "source_section": sec_num,
                    "target_provision": path_str(parent_target),
                    "action_type": "redesignate",
                    "status": "applied",
                })
                return
            href = first_ref_href(content_direct)
            if href:
                para_target = parse_path(href)
        for sp in subparas:
            process_subparagraph(sp, law, para_target, law_id, sec_num, log)
    else:
        content = para_elem.find(T("content"))
        if content is not None:
            href = first_ref_href(content)
            target = parse_path(href) if href else dict(parent_target)
            if not target.get("section"):
                target = dict(parent_target)
            atypes = _action_types(content)
            if "redesignate" in atypes:
                redesignate(law, parent_target, content)
                log.append({
                    "source_law": law_id,
                    "source_section": sec_num,
                    "target_provision": path_str(parent_target),
                    "action_type": "redesignate",
                    "status": "applied",
                })
                return
            if "repeal" in atypes:
                delete_provision(law, target)
                log.append({
                    "source_law": law_id,
                    "source_section": sec_num,
                    "target_provision": path_str(target),
                    "action_type": "repeal",
                    "status": "applied",
                })
                return
            process_content(content, law, parent_target, law_id, sec_num, log)


def process_section(section_elem, law, law_id, log):
    num_elem = section_elem.find(T("num"))
    sec_val = num_elem.get("value", "") if num_elem is not None else ""
    if sec_val == "1":
        return  # skip short title

    # Section has its own subsections
    subsections = section_elem.findall(T("subsection"))
    if subsections:
        for sub in subsections:
            content = sub.find(T("content"))
            if content is not None:
                process_content(content, law, None, law_id, sec_val, log)
        return

    # Section has a chapeau with paragraphs
    chapeau = section_elem.find(T("chapeau"))
    if chapeau is not None:
        href = first_ref_href(chapeau)
        parent_target = parse_path(href)
        for para in section_elem.findall(T("paragraph")):
            process_paragraph(para, law, parent_target, law_id, sec_val, log)
        return

    # Section has direct content
    content = section_elem.find(T("content"))
    if content is not None:
        process_content(content, law, None, law_id, sec_val, log)


# ── main ─────────────────────────────────────────────────────────


def main():
    with open("/data/base_statute.json") as f:
        law = json.load(f)

    with open("/data/enactment_metadata.json") as f:
        metadata = json.load(f)

    amendment_log = []

    for law_info in metadata["enactment_order"]:
        law_id = law_info["law_id"]
        xml_path = f"/data/{law_info['file']}"
        print(f"Processing {law_id} from {xml_path}...", file=sys.stderr)
        tree = etree.parse(xml_path)
        root = tree.getroot()
        main_elem = root.find(T("main"))
        if main_elem is None:
            print(f"ERROR: no <main> element in {xml_path}", file=sys.stderr)
            continue
        for section in main_elem.findall(T("section")):
            process_section(section, law, law_id, amendment_log)

    # Write the final amended statute
    with open("/app/amended_statute.json", "w") as f:
        json.dump(law, f, indent=2)

    # Build and write the reconciliation report
    applied = [a for a in amendment_log if a["status"] == "applied"]
    skipped = [a for a in amendment_log if a["status"] == "skipped"]
    report = {
        "enactment_order": [
            {"law_id": l["law_id"], "enacted_date": l["enacted_date"]}
            for l in metadata["enactment_order"]
        ],
        "amendments": amendment_log,
        "summary": {
            "total_amendments": len(amendment_log),
            "applied": len(applied),
            "skipped": len(skipped),
        },
    }
    with open("/app/reconciliation_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(
        f"Done. {len(applied)} applied, {len(skipped)} skipped, "
        f"{len(amendment_log)} total.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
