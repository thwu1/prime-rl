#!/usr/bin/env python3

"""
Multi-stage NIST CDF election data validation pipeline.

Stage 1: Convert three CDF JSON files to a merged XML representation
Stage 2: Write and compile ISO Schematron rules for cross-CDF referential integrity
Stage 3: Execute Schematron against merged XML, parse SVRL output
Stage 4: Compute vote tallies from CVR records, compare with ERR aggregates
Stage 5: Produce consolidated JSON validation report
"""

import json
import os
import re
import shutil
from collections import defaultdict

from lxml import etree
from lxml.isoschematron import Schematron

DATA_DIR = "/app/data"
SVRL_NS = "http://purl.oclc.org/dsdl/svrl"


def load_json(name):
    with open(os.path.join(DATA_DIR, name)) as f:
        return json.load(f)


def unwrap(data):
    """Remove top-level CDF type wrapper (e.g., 'BallotDefinition.BallotDefinition')."""
    if len(data) == 1:
        key = next(iter(data))
        if "." in key:
            return data[key]
    return data


def get_text(name_obj):
    """Extract text content from a NIST CDF InternationalizedText object."""
    if isinstance(name_obj, dict):
        texts = name_obj.get("Text", [])
        if texts and isinstance(texts, list):
            return texts[0].get("Content", "")
    return str(name_obj) if name_obj else ""


# ── Stage 1: JSON → Merged XML ──────────────────────────────────────

def build_merged_xml(bd_raw, cvr_raw, err_raw):
    """Convert three CDF JSON files into a unified XML document."""
    bd = unwrap(bd_raw)
    cvr = unwrap(cvr_raw)
    err = unwrap(err_raw)

    root = etree.Element("election-data")

    # ── Ballot Definition ──
    bd_elem = etree.SubElement(root, "ballot-definition")
    election = bd.get("Election", [{}])[0]

    # Contests and selections
    for contest in election.get("Contest", []):
        c = etree.SubElement(bd_elem, "contest")
        c.set("id", contest["@id"])
        c.set("name", contest.get("Name", ""))
        c.set("votes-allowed", str(contest.get("VotesAllowed", 1)))
        c.set("type", contest.get("@type", "").rsplit(".", 1)[-1])

        for sel in contest.get("ContestSelection", []):
            s = etree.SubElement(c, "selection")
            s.set("id", sel["@id"])
            if sel.get("IsWriteIn"):
                s.set("is-write-in", "true")
            for cand_id in sel.get("CandidateIds", []):
                cr = etree.SubElement(s, "candidate-ref")
                cr.set("candidate-id", cand_id)
            if "Selection" in sel:
                sel_text = get_text(sel["Selection"])
                if sel_text:
                    s.set("selection-text", sel_text)

    # GpUnits
    for gpu in bd.get("GpUnit", []):
        g = etree.SubElement(bd_elem, "gpunit")
        g.set("id", gpu["@id"])
        g.set("name", get_text(gpu.get("Name", "")))
        g.set("type", gpu.get("Type", ""))

    # Parties
    for party in bd.get("Party", []):
        p = etree.SubElement(bd_elem, "party")
        p.set("id", party["@id"])
        p.set("name", get_text(party.get("Name", "")))

    # Candidates
    for cand in bd.get("Candidate", []):
        ca = etree.SubElement(bd_elem, "candidate")
        ca.set("id", cand["@id"])
        ca.set("name", get_text(cand.get("BallotName", "")))
        if cand.get("PartyId"):
            ca.set("party-id", cand["PartyId"])

    # Ballot Styles
    for bs in election.get("BallotStyle", []):
        bs_elem = etree.SubElement(bd_elem, "ballot-style")
        bs_elem.set("id", bs["@id"])
        gpu_ids = bs.get("GpUnitIds", [])
        if gpu_ids:
            bs_elem.set("gpunit-ids", " ".join(gpu_ids))
        for oc in bs.get("OrderedContent", []):
            oc_elem = etree.SubElement(bs_elem, "ordered-contest")
            oc_elem.set("contest-id", oc.get("ContestId", ""))

    # ── Cast Vote Records ──
    cvr_elem = etree.SubElement(root, "cast-vote-records")

    for record in cvr.get("CVR", []):
        r = etree.SubElement(cvr_elem, "cvr")
        r.set("unique-id", record.get("UniqueId", ""))
        r.set("ballot-style-id", record.get("BallotStyleId", ""))
        r.set("gpunit-id", record.get("BallotStyleUnitId", ""))

        snap_id = record.get("CurrentSnapshotId", "")
        for snapshot in record.get("CVRSnapshot", []):
            if snapshot.get("@id") != snap_id:
                continue
            for cvr_contest in snapshot.get("CVRContest", []):
                cv = etree.SubElement(r, "contest-vote")
                cv.set("contest-id", cvr_contest.get("ContestId", ""))

                for cvr_sel in cvr_contest.get("CVRContestSelection", []):
                    sv = etree.SubElement(cv, "selection-vote")
                    sv.set("selection-id", cvr_sel.get("ContestSelectionId", ""))
                    positions = cvr_sel.get("SelectionPosition", [])
                    total_votes = sum(
                        p.get("NumberVotes", 0)
                        for p in positions
                        if p.get("HasIndication") == "yes"
                    )
                    sv.set("votes", str(total_votes))

    # ── Election Results ──
    err_elem = etree.SubElement(root, "election-results")

    for election_data in err.get("Election", []):
        for contest in election_data.get("Contest", []):
            rc = etree.SubElement(err_elem, "result-contest")
            rc.set("id", contest["@id"])
            rc.set("name", contest.get("Name", ""))

            for sel in contest.get("ContestSelection", []):
                rs = etree.SubElement(rc, "result-selection")
                rs.set("id", sel.get("@id", ""))

                for cand_id in sel.get("CandidateIds", []):
                    cr = etree.SubElement(rs, "candidate-ref")
                    cr.set("candidate-id", cand_id)

                for vc in sel.get("VoteCounts", []):
                    vc_elem = etree.SubElement(rs, "vote-count")
                    vc_elem.set("count", str(vc.get("Count", 0)))
                    vc_elem.set("gpunit-id", vc.get("GpUnitId", ""))
                    vc_elem.set("type", vc.get("Type", ""))

    # ERR Parties
    for party in err.get("Party", []):
        rp = etree.SubElement(err_elem, "result-party")
        rp.set("id", party["@id"])
        rp.set("name", get_text(party.get("Name", "")))

    return root


# ── Stage 2: Write Schematron rules ──────────────────────────────────

def write_schematron():
    """Copy the cross-CDF Schematron rules to /app/."""
    src = "/solution/cross_cdf_rules.sch"
    dst = "/app/cross_cdf_rules.sch"
    shutil.copy2(src, dst)
    return dst


# ── Stage 3: Execute Schematron and parse SVRL ───────────────────────

def run_schematron(xml_path, sch_path):
    """Compile Schematron, validate merged XML, parse SVRL failed assertions."""
    sch_doc = etree.parse(sch_path)
    schematron = Schematron(sch_doc, store_report=True)

    xml_doc = etree.parse(xml_path)
    is_valid = schematron.validate(xml_doc)

    violations = []
    if not is_valid:
        report = schematron.validation_report
        if report is not None:
            for failed in report.findall(f".//{{{SVRL_NS}}}failed-assert"):
                text = failed.findtext(f"{{{SVRL_NS}}}text", "").strip()
                location = failed.get("location", "")
                violation = parse_svrl_assertion(text, location)
                if violation:
                    violations.append(violation)
        else:
            print("  WARNING: validation_report is None despite is_valid=False")

    return violations


def parse_svrl_assertion(text, location):
    """Convert an SVRL failed-assert into a structured violation record."""
    text_lower = text.lower()

    # Determine source file from SVRL location XPath
    if "cast-vote-records" in location:
        source = "cvr.json"
    elif "election-results" in location:
        source = "err.json"
    else:
        source = "unknown"

    # Extract the primary entity ID from assertion text
    id_match = re.search(r"'([^']+)'", text)
    entity_id = id_match.group(1) if id_match else ""

    # Classify violation type from assertion text
    if "contestid" in text_lower and "selection" not in text_lower:
        vtype = "undefined_contest"
    elif "contestselectionid" in text_lower or "selectionid" in text_lower:
        vtype = "undefined_contest_selection"
    elif "gpunit" in text_lower:
        vtype = "undefined_gpunit"
    elif "partyid" in text_lower:
        vtype = "undefined_party"
    elif "candidateid" in text_lower:
        vtype = "undefined_candidate"
    else:
        vtype = "referential_integrity"

    return {
        "violation_type": vtype,
        "source_file": source,
        "entity_id": entity_id,
        "description": text,
    }


# ── Stage 4: Vote tally reconciliation ──────────────────────────────

def compute_tally_violations(cvr_raw, err_raw, bd_raw):
    """Tally CVR votes and compare against ERR aggregate totals."""
    bd = unwrap(bd_raw)
    cvr = unwrap(cvr_raw)
    err = unwrap(err_raw)

    # Extract BD-defined entity sets
    bd_contests = set()
    bd_selections = set()
    election = bd.get("Election", [{}])[0]
    for contest in election.get("Contest", []):
        bd_contests.add(contest["@id"])
        for sel in contest.get("ContestSelection", []):
            bd_selections.add(sel["@id"])

    # Tally CVR votes (only for BD-defined entities)
    tallies = defaultdict(lambda: defaultdict(int))
    for record in cvr.get("CVR", []):
        snap_id = record.get("CurrentSnapshotId", "")
        for snapshot in record.get("CVRSnapshot", []):
            if snapshot.get("@id") != snap_id:
                continue
            for cvr_contest in snapshot.get("CVRContest", []):
                cid = cvr_contest.get("ContestId", "")
                if cid not in bd_contests:
                    continue
                for cvr_sel in cvr_contest.get("CVRContestSelection", []):
                    sid = cvr_sel.get("ContestSelectionId", "")
                    if sid not in bd_selections:
                        continue
                    for pos in cvr_sel.get("SelectionPosition", []):
                        if pos.get("HasIndication") == "yes":
                            tallies[cid][sid] += pos.get("NumberVotes", 1)

    # Compare with ERR aggregate totals
    violations = []
    for election_data in err.get("Election", []):
        for contest in election_data.get("Contest", []):
            cid = contest["@id"]
            if cid not in bd_contests:
                continue
            for sel in contest.get("ContestSelection", []):
                sid = sel.get("@id", "")
                if sid not in bd_selections:
                    continue
                for vc in sel.get("VoteCounts", []):
                    if vc.get("Type") == "total":
                        err_count = vc.get("Count", 0)
                        cvr_count = tallies.get(cid, {}).get(sid, 0)
                        if err_count != cvr_count:
                            violations.append({
                                "violation_type": "vote_count_mismatch",
                                "source_file": "err.json",
                                "entity_id": sid,
                                "description": (
                                    f"ERR reports {err_count} total votes for "
                                    f"'{sid}' in contest '{cid}' but CVR tally "
                                    f"is {cvr_count} "
                                    f"(discrepancy: {err_count - cvr_count:+d})"
                                ),
                            })

    return violations


# ── Stage 5: Consolidate report ──────────────────────────────────────

def main():
    bd_raw = load_json("bd.json")
    cvr_raw = load_json("cvr.json")
    err_raw = load_json("err.json")

    # Stage 1: Build merged XML
    print("Stage 1: Converting CDF JSON to merged XML...")
    xml_root = build_merged_xml(bd_raw, cvr_raw, err_raw)
    xml_path = "/app/merged.xml"
    xml_tree = etree.ElementTree(xml_root)
    xml_tree.write(
        xml_path,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    )
    xml_size = os.path.getsize(xml_path)
    print(f"  Wrote {xml_path} ({xml_size} bytes)")

    # Stage 2: Write Schematron rules
    print("Stage 2: Writing cross-CDF Schematron rules...")
    sch_path = write_schematron()
    print(f"  Wrote {sch_path}")

    # Stage 3: Run Schematron validation
    print("Stage 3: Compiling and executing Schematron...")
    ref_violations = run_schematron(xml_path, sch_path)
    print(f"  SVRL: {len(ref_violations)} referential integrity violation(s)")

    # Stage 4: Vote tally reconciliation
    print("Stage 4: Computing vote tally reconciliation...")
    tally_violations = compute_tally_violations(cvr_raw, err_raw, bd_raw)
    print(f"  Found {len(tally_violations)} tally mismatch(es)")

    # Stage 5: Consolidate
    all_violations = ref_violations + tally_violations
    report = {"violations": all_violations}

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nConsolidated report: {len(all_violations)} violation(s)")
    for v in all_violations:
        print(f"  [{v['violation_type']}] {v['entity_id']}: {v['description']}")


if __name__ == "__main__":
    main()
