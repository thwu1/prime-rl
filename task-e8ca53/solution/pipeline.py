#!/usr/bin/env python3
"""Legislative change-tracking pipeline for US Code Title 9.

Processes USLM XML vintage snapshots into a git repository with structured
commit messages, amendment provenance, cross-reference analysis, and
structural changelog.

"""

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from converter import parse_xml, render_chapter_mode

MANIFEST_PATH = "/app/manifest.json"
VINTAGES_DIR = "/app/vintages"
REPO_DIR = "/app/repo"
OUTPUT_DIR = "/app/output"
TITLE_HEADINGS_PATH = "/app/title_headings.json"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    title_num = manifest["title"]
    vintages = manifest["vintages"]

    with open(TITLE_HEADINGS_PATH) as f:
        title_headings = json.load(f)

    # --- Parse all vintage XMLs for structural metadata ---
    vintage_data = {}
    for vintage in vintages:
        vid = vintage["id"]
        xml_path = os.path.join(VINTAGES_DIR, vid, f"title-{title_num:02d}.xml")
        vintage_data[vid] = parse_vintage_xml(xml_path)

    # --- Convert each vintage to chapter-mode markdown ---
    vintage_files = {}
    for vintage in vintages:
        vid = vintage["id"]
        xml_path = os.path.join(VINTAGES_DIR, vid, f"title-{title_num:02d}.xml")
        title_ir = parse_xml(xml_path)
        vintage_files[vid] = render_chapter_mode(title_ir)

    # --- Compute structural diffs ---
    diffs = compute_all_diffs(vintages, vintage_data)

    # --- Build changelog.json (consecutive pairs only) ---
    changelog = [d for d in diffs if d["from_vintage"] is not None]
    write_json(os.path.join(OUTPUT_DIR, "changelog.json"), changelog)

    # --- Build provenance.json ---
    provenance = build_provenance(vintages, vintage_data)
    write_json(os.path.join(OUTPUT_DIR, "provenance.json"), provenance)

    # --- Build xref_analysis.json (latest vintage) ---
    latest_vid = vintages[-1]["id"]
    xref = build_xref_analysis(vintage_data[latest_vid], title_headings, title_num)
    write_json(os.path.join(OUTPUT_DIR, "xref_analysis.json"), xref)

    # --- Build git repository ---
    build_git_repo(manifest, vintage_files, diffs)

    print("Pipeline complete.")


# ---------------------------------------------------------------------------
# XML metadata extraction
# ---------------------------------------------------------------------------

def parse_vintage_xml(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    sections_map = {}
    chapters = set()
    refs = []

    _walk_for_metadata(root, sections_map, chapters, refs, inside_note=False)

    return {
        "sections_map": sections_map,
        "chapters": chapters,
        "refs": refs,
    }


def _walk_for_metadata(elem, sections_map, chapters, refs, inside_note):
    for child in elem:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "chapter":
            num_el = child.find("num")
            if num_el is not None:
                ch_num = num_el.get("value", "").strip()
                if ch_num:
                    chapters.add(ch_num)
            _walk_for_metadata(child, sections_map, chapters, refs, inside_note)
        elif tag == "section" and not inside_note:
            identifier = child.get("identifier", "")
            if identifier:
                _parse_section_metadata(child, identifier, sections_map, refs)
            _walk_for_metadata(child, sections_map, chapters, refs, inside_note)
        elif tag in ("note", "notes"):
            _walk_for_metadata(child, sections_map, chapters, refs, True)
        else:
            _walk_for_metadata(child, sections_map, chapters, refs, inside_note)


def _parse_section_metadata(sec_el, identifier, sections_map, refs):
    heading_el = sec_el.find("heading")
    heading = _get_full_text(heading_el).strip() if heading_el is not None else ""

    status_el = sec_el.find("status")
    status = (status_el.text or "").strip() if status_el is not None else "in-force"

    sc_el = sec_el.find("sourceCredit")
    source_credit = _get_full_text(sc_el).strip() if sc_el is not None else ""

    content_el = sec_el.find("content")
    content_text = _get_full_text(content_el).strip() if content_el is not None else ""

    sections_map[identifier] = {
        "heading": heading,
        "status": status,
        "source_credit": source_credit,
        "content_text": content_text,
    }

    if content_el is not None:
        _extract_content_refs(content_el, identifier, refs)


def _extract_content_refs(elem, source_id, refs):
    for child in elem:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "ref":
            href = child.get("href", "")
            if href.startswith("/us/usc/"):
                link_text = _get_full_text(child).strip()
                refs.append({
                    "source": source_id,
                    "target": href,
                    "link_text": link_text,
                })

        _extract_content_refs(child, source_id, refs)


def _get_full_text(elem):
    if elem is None:
        return ""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_get_full_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


# ---------------------------------------------------------------------------
# SourceCredit parsing
# ---------------------------------------------------------------------------

def extract_pub_laws(source_credit):
    """Extract Pub. L. references from sourceCredit text.

    SourceCredits use en-dash (U+2013) between congress and law number:
        Pub. L. 117\u201390
    We also accept ASCII hyphen for robustness.
    """
    pattern = r"Pub\.\s*L\.\s*(\d+)[\u2013\-](\d+)"
    matches = re.findall(pattern, source_credit)
    result = []
    for congress, number in matches:
        result.append(f"Pub. L. {congress}\u2013{number}")
    return result


# ---------------------------------------------------------------------------
# Structural diffing
# ---------------------------------------------------------------------------

def compute_all_diffs(vintages, vintage_data):
    diffs = []

    # First vintage: everything is an addition
    first_vid = vintages[0]["id"]
    first_data = vintage_data[first_vid]
    first_changes = []

    for ch in sorted(first_data["chapters"]):
        first_changes.append({
            "type": "chapter_added",
            "identifier": ch,
            "attribution": None,
        })

    for sid in sorted(first_data["sections_map"].keys()):
        sec = first_data["sections_map"][sid]
        pls = extract_pub_laws(sec["source_credit"])
        first_changes.append({
            "type": "section_added",
            "identifier": sid,
            "attribution": pls[-1] if pls else None,
        })

    diffs.append({
        "from_vintage": None,
        "to_vintage": first_vid,
        "changes": first_changes,
    })

    # Consecutive pairs
    for i in range(1, len(vintages)):
        prev_vid = vintages[i - 1]["id"]
        curr_vid = vintages[i]["id"]
        prev_data = vintage_data[prev_vid]
        curr_data = vintage_data[curr_vid]

        changes = compute_diff(prev_data, curr_data)
        diffs.append({
            "from_vintage": prev_vid,
            "to_vintage": curr_vid,
            "changes": changes,
        })

    return diffs


def compute_diff(prev_data, curr_data):
    changes = []

    prev_sections = prev_data["sections_map"]
    curr_sections = curr_data["sections_map"]
    prev_chapters = prev_data["chapters"]
    curr_chapters = curr_data["chapters"]

    new_chapters = curr_chapters - prev_chapters
    for ch in sorted(new_chapters):
        changes.append({
            "type": "chapter_added",
            "identifier": ch,
            "attribution": None,
        })

    all_sids = sorted(set(list(prev_sections.keys()) + list(curr_sections.keys())))

    for sid in all_sids:
        if sid not in prev_sections and sid in curr_sections:
            pls = extract_pub_laws(curr_sections[sid]["source_credit"])
            changes.append({
                "type": "section_added",
                "identifier": sid,
                "attribution": pls[-1] if pls else None,
            })
        elif sid in prev_sections and sid in curr_sections:
            prev_sec = prev_sections[sid]
            curr_sec = curr_sections[sid]

            if curr_sec["status"] == "repealed" and prev_sec["status"] != "repealed":
                prev_pls = set(extract_pub_laws(prev_sec["source_credit"]))
                curr_pls = extract_pub_laws(curr_sec["source_credit"])
                new_pls = [pl for pl in curr_pls if pl not in prev_pls]
                changes.append({
                    "type": "section_repealed",
                    "identifier": sid,
                    "attribution": new_pls[0] if new_pls else None,
                })
            elif (curr_sec["source_credit"] != prev_sec["source_credit"] or
                  curr_sec["content_text"] != prev_sec["content_text"]):
                prev_pls = set(extract_pub_laws(prev_sec["source_credit"]))
                curr_pls = extract_pub_laws(curr_sec["source_credit"])
                new_pls = [pl for pl in curr_pls if pl not in prev_pls]
                changes.append({
                    "type": "section_amended",
                    "identifier": sid,
                    "attribution": new_pls[0] if new_pls else None,
                })

    return changes


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def build_provenance(vintages, vintage_data):
    first_appeared = {}

    for vintage in vintages:
        vid = vintage["id"]
        data = vintage_data[vid]
        for sid in data["sections_map"]:
            if sid not in first_appeared:
                first_appeared[sid] = vid

    latest_vid = vintages[-1]["id"]
    latest_data = vintage_data[latest_vid]

    provenance = {}
    for sid in sorted(latest_data["sections_map"].keys()):
        sec = latest_data["sections_map"][sid]
        provenance[sid] = {
            "heading": sec["heading"],
            "status": sec["status"],
            "public_laws": extract_pub_laws(sec["source_credit"]),
            "first_appeared": first_appeared[sid],
        }

    return provenance


# ---------------------------------------------------------------------------
# Cross-reference analysis
# ---------------------------------------------------------------------------

def build_xref_analysis(vintage_data, title_headings, title_num):
    refs = vintage_data["refs"]

    intra = 0
    inter = 0
    dangling = 0
    ref_details = []

    for ref in refs:
        target = ref["target"]
        m = re.match(r"^/us/usc/t(\d+)/s(.+)$", target)
        if not m:
            continue
        target_title = int(m.group(1))

        if target_title == title_num:
            classification = "intra_title"
            intra += 1
        elif str(target_title) in title_headings:
            classification = "inter_title"
            inter += 1
        else:
            classification = "dangling"
            dangling += 1

        ref_details.append({
            "source": ref["source"],
            "target": target,
            "link_text": ref["link_text"],
            "classification": classification,
        })

    return {
        "summary": {
            "intra_title": intra,
            "inter_title": inter,
            "dangling": dangling,
        },
        "references": ref_details,
    }


# ---------------------------------------------------------------------------
# Commit message construction
# ---------------------------------------------------------------------------

def build_commit_message(vintage, diff):
    congress = vintage["congress"]
    law_number = vintage["law_number"]

    first_line = f"Update US Code through Public Law {congress}-{law_number}"

    if not diff or not diff.get("changes"):
        return first_line

    lines = [first_line, "", "Changes:"]
    for change in diff["changes"]:
        change_type = change["type"]
        identifier = change["identifier"]
        attribution = change.get("attribution")

        if attribution:
            lines.append(f"- {change_type}: {identifier} ({attribution})")
        else:
            lines.append(f"- {change_type}: {identifier}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Git fast-import repository construction
# ---------------------------------------------------------------------------

def build_git_repo(manifest, vintage_files, diffs):
    os.makedirs(REPO_DIR, exist_ok=True)

    subprocess.run(["git", "init", REPO_DIR], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", REPO_DIR, "config", "user.email", "sync@us-code-tools.local"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", REPO_DIR, "config", "user.name", "us-code-tools"],
        check=True, capture_output=True,
    )

    vintages = manifest["vintages"]
    author_name = "us-code-tools"
    author_email = "sync@us-code-tools.local"

    stream = bytearray()

    for idx, vintage in enumerate(vintages, start=1):
        vid = vintage["id"]
        release_date = vintage["release_date"]

        dt = datetime.strptime(release_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        timestamp = int(dt.timestamp())

        diff = diffs[idx - 1]
        commit_msg = build_commit_message(vintage, diff)
        msg_bytes = commit_msg.encode("utf-8")

        stream += f"commit refs/heads/main\n".encode()
        stream += f"mark :{idx}\n".encode()
        stream += f"author {author_name} <{author_email}> {timestamp} +0000\n".encode()
        stream += f"committer {author_name} <{author_email}> {timestamp} +0000\n".encode()
        stream += f"data {len(msg_bytes)}\n".encode()
        stream += msg_bytes
        stream += b"\n"

        if idx > 1:
            stream += f"from :{idx - 1}\n".encode()

        stream += b"deleteall\n"

        files = vintage_files[vid]
        for filepath in sorted(files.keys()):
            content = files[filepath]
            content_bytes = content.encode("utf-8")
            stream += f"M 100644 inline {filepath}\n".encode()
            stream += f"data {len(content_bytes)}\n".encode()
            stream += content_bytes
            stream += b"\n"

        stream += b"\n"

    stream_path = os.path.join(OUTPUT_DIR, "fast-import.stream")
    with open(stream_path, "wb") as f:
        f.write(stream)

    proc = subprocess.run(
        ["git", "-C", REPO_DIR, "fast-import", "--quiet"],
        input=bytes(stream),
        capture_output=True,
    )
    if proc.returncode != 0:
        print(f"git fast-import failed: {proc.stderr.decode()}", file=sys.stderr)
        sys.exit(1)

    subprocess.run(
        ["git", "-C", REPO_DIR, "checkout", "main"],
        check=True, capture_output=True,
    )

    _create_tags(manifest)


def _create_tags(manifest):
    result = subprocess.run(
        ["git", "-C", REPO_DIR, "log", "--format=%H|||%s", "--reverse", "main"],
        capture_output=True, text=True, check=True,
    )

    commit_map = {}
    for line in result.stdout.strip().split("\n"):
        if "|||" in line:
            h, msg = line.split("|||", 1)
            commit_map[msg.strip()] = h.strip()

    vintages = manifest["vintages"]

    # Annual tags: last vintage per calendar year gets the tag
    year_vintage = {}
    for vintage in vintages:
        year = vintage["release_date"][:4]
        year_vintage[year] = vintage

    for year, vintage in year_vintage.items():
        subject = f"Update US Code through Public Law {vintage['congress']}-{vintage['law_number']}"
        commit_hash = commit_map.get(subject)
        if commit_hash:
            subprocess.run(
                ["git", "-C", REPO_DIR, "tag", f"annual/{year}", commit_hash],
                capture_output=True,
            )

    # Congress boundary tags
    for vintage in vintages:
        if vintage.get("congress_boundary", False):
            subject = f"Update US Code through Public Law {vintage['congress']}-{vintage['law_number']}"
            commit_hash = commit_map.get(subject)
            if commit_hash:
                subprocess.run(
                    ["git", "-C", REPO_DIR, "tag", f"congress/{vintage['congress']}", commit_hash],
                    capture_output=True,
                )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
