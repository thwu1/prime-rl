#!/usr/bin/env python3
"""BAM alignment quality audit solution.

Uses samtools CLI for BAM I/O and Python for identity metric computation.
Produces audit_report.json and filtered.bam.

"""
import json
import re
import subprocess
import os


def parse_cigar(cigar_str):
    """Parse CIGAR string into list of (length, operation) tuples."""
    return [(int(x), op) for x, op in re.findall(r"(\d+)([MIDNSHP=X])", cigar_str)]


def compute_identities(cigar_ops, nm_tag):
    """Compute BLAST, gap-compressed, and gap-excluded identity metrics.

    Returns (blast_id, gc_id, gx_id, corrected_nm, nm_was_corrected).
    """
    op_set = set(op for _, op in cigar_ops)
    uses_extended = "=" in op_set or "X" in op_set

    if uses_extended:
        matches = sum(l for l, op in cigar_ops if op == "=")
        mismatches = sum(l for l, op in cigar_ops if op == "X")
        ins_bases = sum(l for l, op in cigar_ops if op == "I")
        del_bases = sum(l for l, op in cigar_ops if op == "D")

        correct_nm = mismatches + ins_bases + del_bases
        nm_corrected = nm_tag != correct_nm

        m_equiv = matches + mismatches
        aln_len = m_equiv + ins_bases + del_bases
        gap_opens = sum(1 for _, op in cigar_ops if op in ("I", "D"))

        blast_id = matches / aln_len if aln_len > 0 else 0.0
        gc_id = matches / (m_equiv + gap_opens) if (m_equiv + gap_opens) > 0 else 0.0
        gx_id = matches / m_equiv if m_equiv > 0 else 0.0

        return blast_id, gc_id, gx_id, correct_nm, nm_corrected
    else:
        m_total = sum(l for l, op in cigar_ops if op == "M")
        ins_bases = sum(l for l, op in cigar_ops if op == "I")
        del_bases = sum(l for l, op in cigar_ops if op == "D")

        gap_bases = ins_bases + del_bases
        mismatches = nm_tag - gap_bases
        matches = m_total - mismatches

        gap_opens = sum(1 for _, op in cigar_ops if op in ("I", "D"))
        aln_len = m_total + ins_bases + del_bases

        blast_id = matches / aln_len if aln_len > 0 else 0.0
        gc_id = matches / (m_total + gap_opens) if (m_total + gap_opens) > 0 else 0.0
        gx_id = matches / m_total if m_total > 0 else 0.0

        return blast_id, gc_id, gx_id, nm_tag, False


def main():
    # Extract SAM text from BAM using samtools
    result = subprocess.run(
        ["samtools", "view", "-h", "/app/alignments.bam"],
        capture_output=True, text=True, check=True,
    )

    lines = result.stdout.strip().split("\n")
    header_lines = [l for l in lines if l.startswith("@")]
    record_lines = [l for l in lines if l and not l.startswith("@")]

    # First pass: identify chimeric reads (SA tag or supplementary flag)
    sa_reads = set()
    supplementary_reads = set()

    for line in record_lines:
        fields = line.split("\t")
        qname = fields[0]
        flag = int(fields[1])

        if flag & 0x800:
            supplementary_reads.add(qname)

        for f in fields[11:]:
            if f.startswith("SA:Z:"):
                sa_reads.add(qname)

    chimeric_reads = sa_reads | supplementary_reads

    # Second pass: compute metrics for primary alignments
    total = len(record_lines)
    primary_count = 0
    supplementary_count = 0
    secondary_count = 0
    unmapped_count = 0
    nm_corrections = 0
    passed_count = 0
    failed_count = 0

    reads = {}
    per_ref = {}
    filtered_records = []

    for line in record_lines:
        fields = line.split("\t")
        qname = fields[0]
        flag = int(fields[1])
        rname = fields[2]
        cigar_str = fields[5]

        # Classify by flag
        if flag & 0x4:
            unmapped_count += 1
            continue
        if flag & 0x800:
            supplementary_count += 1
            continue
        if flag & 0x100:
            secondary_count += 1
            continue

        # Primary alignment
        primary_count += 1

        # Extract NM tag
        nm_tag = None
        for f in fields[11:]:
            if f.startswith("NM:i:"):
                nm_tag = int(f.split(":")[2])

        # Parse CIGAR and compute identities
        cigar_ops = parse_cigar(cigar_str)
        blast_id, gc_id, gx_id, corrected_nm, nm_corrected = compute_identities(
            cigar_ops, nm_tag
        )

        if nm_corrected:
            nm_corrections += 1

        passed = gc_id >= 0.90

        if passed:
            passed_count += 1
            # Build the output record, correcting NM if needed
            if nm_corrected:
                new_fields = list(fields)
                for i in range(11, len(new_fields)):
                    if new_fields[i].startswith("NM:i:"):
                        new_fields[i] = f"NM:i:{corrected_nm}"
                filtered_records.append("\t".join(new_fields))
            else:
                filtered_records.append(line)
        else:
            failed_count += 1

        reads[qname] = {
            "blast_identity": blast_id,
            "gc_identity": gc_id,
            "gap_excluded_identity": gx_id,
            "passed": passed,
            "nm_corrected": nm_corrected,
            "is_chimeric": qname in chimeric_reads,
        }

        # Accumulate per-reference stats
        if rname not in per_ref:
            per_ref[rname] = {
                "count": 0,
                "blast_sum": 0.0,
                "gc_sum": 0.0,
                "gx_sum": 0.0,
                "passed": 0,
                "failed": 0,
            }
        per_ref[rname]["count"] += 1
        per_ref[rname]["blast_sum"] += blast_id
        per_ref[rname]["gc_sum"] += gc_id
        per_ref[rname]["gx_sum"] += gx_id
        if passed:
            per_ref[rname]["passed"] += 1
        else:
            per_ref[rname]["failed"] += 1

    # Compute per-reference averages
    per_reference = {}
    for ref, data in per_ref.items():
        n = data["count"]
        per_reference[ref] = {
            "count": n,
            "mean_blast_identity": data["blast_sum"] / n,
            "mean_gc_identity": data["gc_sum"] / n,
            "mean_gap_excluded_identity": data["gx_sum"] / n,
            "passed": data["passed"],
            "failed": data["failed"],
        }

    # Write audit report
    report = {
        "total_records": total,
        "primary_alignments": primary_count,
        "supplementary_alignments": supplementary_count,
        "secondary_alignments": secondary_count,
        "unmapped": unmapped_count,
        "passed_filter": passed_count,
        "failed_filter": failed_count,
        "nm_corrections": nm_corrections,
        "reads": reads,
        "per_reference": per_reference,
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    # Write filtered SAM to temp file
    with open("/tmp/filtered.sam", "w") as f:
        for h in header_lines:
            f.write(h + "\n")
        for r in filtered_records:
            f.write(r + "\n")

    # Convert to sorted, indexed BAM using samtools
    subprocess.run(
        ["samtools", "view", "-bS", "/tmp/filtered.sam", "-o", "/tmp/filtered_unsorted.bam"],
        check=True,
    )
    subprocess.run(
        ["samtools", "sort", "/tmp/filtered_unsorted.bam", "-o", "/app/filtered.bam"],
        check=True,
    )
    subprocess.run(["samtools", "index", "/app/filtered.bam"], check=True)

    # Cleanup
    os.remove("/tmp/filtered.sam")
    os.remove("/tmp/filtered_unsorted.bam")

    print("Audit complete. Outputs: /app/audit_report.json, /app/filtered.bam")


if __name__ == "__main__":
    main()
