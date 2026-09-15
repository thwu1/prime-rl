#!/usr/bin/env python3
"""SAM alignment identity filter with gap-compressed identity.

"""
import sys
import json
import re
import argparse
from collections import defaultdict


def parse_cigar(cigar_str):
    """Parse CIGAR string into list of (length, operation) tuples."""
    if cigar_str == "*":
        return []
    return [(int(m.group(1)), m.group(2))
            for m in re.finditer(r"(\d+)([MIDNSHP=X])", cigar_str)]


def compute_identities(cigar_ops, nm_tag):
    """Compute BLAST, gap-compressed, and gap-excluded identity metrics.

    For =/X CIGARs, matches and mismatches are derived directly from the
    operators and the NM tag is verified (corrected if wrong).
    For M CIGARs, the NM tag is required to split M positions into matches
    and mismatches.

    Returns (blast_id, gc_id, gap_excluded_id, nm_was_corrected).
    """
    has_extended = any(op in ("=", "X") for _, op in cigar_ops)

    i_total = sum(length for length, op in cigar_ops if op == "I")
    d_total = sum(length for length, op in cigar_ops if op == "D")
    gap_opens = sum(1 for _, op in cigar_ops if op in ("I", "D"))
    gap_total = i_total + d_total

    nm_was_corrected = False

    if has_extended:
        matches = sum(length for length, op in cigar_ops if op == "=")
        mismatches = sum(length for length, op in cigar_ops if op == "X")
        m_total = matches + mismatches
        correct_nm = mismatches + i_total + d_total
        if nm_tag != correct_nm:
            nm_was_corrected = True
        # Use CIGAR-derived values regardless of NM tag
    else:
        m_total = sum(length for length, op in cigar_ops if op == "M")
        mismatches = nm_tag - gap_total
        matches = m_total - mismatches

    alignment_length = m_total + i_total + d_total

    if alignment_length == 0:
        return 0.0, 0.0, 0.0, False

    # BLAST identity: matches / alignment_length
    blast_id = matches / alignment_length

    # Gap-compressed identity: 1 - (mismatches + gap_opens) / (m_total + gap_opens)
    gc_denom = m_total + gap_opens
    gc_id = 1.0 - (mismatches + gap_opens) / gc_denom if gc_denom > 0 else 0.0

    # Gap-excluded identity: matches / (matches + mismatches)
    ge_denom = matches + mismatches
    gap_excluded_id = matches / ge_denom if ge_denom > 0 else 0.0

    return blast_id, gc_id, gap_excluded_id, nm_was_corrected


def main():
    parser = argparse.ArgumentParser(
        description="Filter SAM alignments by gap-compressed identity")
    parser.add_argument("sam_file", help="Input SAM file")
    parser.add_argument("--min-gc-identity", type=float, default=0.90,
                        help="Minimum gap-compressed identity threshold")
    parser.add_argument("--report", required=True,
                        help="Output JSON statistics report path")
    args = parser.parse_args()

    header_lines = []
    records = []

    with open(args.sam_file) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("@"):
                header_lines.append(line)
                continue
            fields = line.split("\t")
            if len(fields) < 11:
                continue

            qname = fields[0]
            flag = int(fields[1])
            rname = fields[2]
            cigar = fields[5]

            nm = None
            sa_tag = None
            for tag in fields[11:]:
                if tag.startswith("NM:i:"):
                    nm = int(tag[5:])
                elif tag.startswith("SA:Z:"):
                    sa_tag = tag[5:]

            records.append({
                "qname": qname,
                "flag": flag,
                "rname": rname,
                "cigar": cigar,
                "nm": nm,
                "sa_tag": sa_tag,
                "line": line,
            })

    # Classify records by flag type
    supplementary_qnames = set()
    sa_qnames = set()
    primary = []
    supplementary_count = 0
    secondary_count = 0
    unmapped_count = 0

    for rec in records:
        flag = rec["flag"]
        if flag & 0x800:
            supplementary_count += 1
            supplementary_qnames.add(rec["qname"])
        elif flag & 0x100:
            secondary_count += 1
        elif flag & 0x4:
            unmapped_count += 1
        else:
            primary.append(rec)
            if rec["sa_tag"]:
                sa_qnames.add(rec["qname"])

    chimeric_qnames = supplementary_qnames | sa_qnames

    # Process primary alignments
    nm_corrections = 0
    read_results = {}
    per_ref = defaultdict(lambda: {
        "blast": [], "gc": [], "ge": [],
        "passed": 0, "failed": 0
    })
    passed_lines = []

    for rec in primary:
        cigar_ops = parse_cigar(rec["cigar"])
        if not cigar_ops or rec["nm"] is None:
            continue

        blast_id, gc_id, ge_id, nm_corrected = compute_identities(
            cigar_ops, rec["nm"])
        if nm_corrected:
            nm_corrections += 1

        passed = gc_id >= args.min_gc_identity

        read_results[rec["qname"]] = {
            "blast_identity": round(blast_id, 6),
            "gc_identity": round(gc_id, 6),
            "gap_excluded_identity": round(ge_id, 6),
            "passed": passed,
            "nm_corrected": nm_corrected,
            "is_chimeric": rec["qname"] in chimeric_qnames,
        }

        ref = rec["rname"]
        per_ref[ref]["blast"].append(blast_id)
        per_ref[ref]["gc"].append(gc_id)
        per_ref[ref]["ge"].append(ge_id)
        if passed:
            per_ref[ref]["passed"] += 1
            passed_lines.append(rec["line"])
        else:
            per_ref[ref]["failed"] += 1

    # Build per-reference statistics
    per_reference = {}
    for ref in sorted(per_ref):
        d = per_ref[ref]
        n = len(d["blast"])
        per_reference[ref] = {
            "count": n,
            "mean_blast_identity": round(sum(d["blast"]) / n, 6),
            "mean_gc_identity": round(sum(d["gc"]) / n, 6),
            "mean_gap_excluded_identity": round(sum(d["ge"]) / n, 6),
            "passed": d["passed"],
            "failed": d["failed"],
        }

    total_passed = sum(d["passed"] for d in per_ref.values())
    total_failed = sum(d["failed"] for d in per_ref.values())

    report = {
        "total_records": len(records),
        "primary_alignments": len(primary),
        "supplementary_alignments": supplementary_count,
        "secondary_alignments": secondary_count,
        "unmapped": unmapped_count,
        "passed_filter": total_passed,
        "failed_filter": total_failed,
        "nm_corrections": nm_corrections,
        "reads": read_results,
        "per_reference": per_reference,
    }

    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)

    # Write filtered SAM to stdout
    for hl in header_lines:
        print(hl)
    for line in passed_lines:
        print(line)


if __name__ == "__main__":
    main()
