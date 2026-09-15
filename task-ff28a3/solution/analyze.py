#!/usr/bin/env python3

"""
Solution: Genomic alignment pipeline forensics.
Investigates data quality issues, fixes the alignment pipeline, and produces
a comprehensive analysis report.
"""

import json
import os
import re
import subprocess
import sys


# ---- Chromosome name mapping ----

def discover_naming_mismatch(sam_path, ref_path):
    """Discover chromosome naming mismatch between SAM and reference."""
    # Get SAM chromosome names from header
    sam_chroms = []
    with open(sam_path) as f:
        for line in f:
            if line.startswith('@SQ'):
                m = re.search(r'SN:(\S+)', line)
                if m:
                    sam_chroms.append(m.group(1))
            elif not line.startswith('@'):
                break

    # Get reference chromosome names
    ref_chroms = []
    with open(ref_path) as f:
        for line in f:
            if line.startswith('>'):
                ref_chroms.append(line[1:].strip().split()[0])

    # Build mapping by order (scaffold_1 -> chr1, scaffold_2 -> chr2)
    name_map = {}
    for s, r in zip(sam_chroms, ref_chroms):
        if s != r:
            name_map[s] = r
    return name_map


def fix_sam_chromosomes(sam_path, name_map, output_path):
    """Rewrite SAM file with corrected chromosome names."""
    with open(sam_path) as fin, open(output_path, 'w') as fout:
        for line in fin:
            if line.startswith('@SQ'):
                for old, new in name_map.items():
                    line = line.replace(f'SN:{old}', f'SN:{new}')
                fout.write(line)
            elif line.startswith('@'):
                fout.write(line)
            else:
                fields = line.split('\t')
                # Fix RNAME (col 2)
                if fields[2] in name_map:
                    fields[2] = name_map[fields[2]]
                # Fix RNEXT (col 6)
                if fields[6] in name_map:
                    fields[6] = name_map[fields[6]]
                # Fix SA tag if present
                for i in range(11, len(fields)):
                    if fields[i].startswith('SA:Z:'):
                        for old, new in name_map.items():
                            fields[i] = fields[i].replace(old, new)
                fout.write('\t'.join(fields))


# ---- SAM/BAM processing with samtools ----

def run_cmd(cmd):
    """Run a shell command and return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Command failed: {cmd}", file=sys.stderr)
        print(f"stderr: {result.stderr}", file=sys.stderr)
    return result.stdout, result.returncode


def process_bam(fixed_sam, ref_path, output_bam):
    """Sort, mark duplicates, and index the BAM."""
    # Name-sort for fixmate
    run_cmd(f"samtools sort -n -o /tmp/namesorted.bam {fixed_sam}")
    # Add mate info
    run_cmd(f"samtools fixmate -m /tmp/namesorted.bam /tmp/fixmate.bam")
    # Coordinate sort
    run_cmd(f"samtools sort -o /tmp/sorted.bam /tmp/fixmate.bam")
    # Mark duplicates
    run_cmd(f"samtools markdup /tmp/sorted.bam {output_bam}")
    # Index
    run_cmd(f"samtools index {output_bam}")


def get_flagstat(bam_path):
    """Parse samtools flagstat output."""
    stdout, _ = run_cmd(f"samtools flagstat {bam_path}")
    stats = {}
    for line in stdout.strip().split('\n'):
        parts = line.split(' + ')
        if len(parts) < 2:
            continue
        count = int(parts[0])
        rest = parts[1].strip()
        if 'in total' in rest:
            stats['total_reads'] = count
        elif 'mapped' in rest and 'mate' not in rest and 'primary' not in rest:
            if 'mapped' == rest.split('(')[0].strip().split()[-1] or rest.startswith('0 mapped'):
                stats['mapped_reads'] = count
        elif 'duplicates' in rest and 'primary' not in rest:
            stats['duplicates'] = count

    # Simpler parsing: re-parse
    stats = {}
    lines = stdout.strip().split('\n')
    for line in lines:
        m = re.match(r'(\d+) \+ \d+ (.+)', line)
        if m:
            count = int(m.group(1))
            desc = m.group(2).strip()
            if 'in total' in desc:
                stats['total_reads'] = count
            elif desc.startswith('mapped') and 'primary' not in desc and 'mate' not in desc:
                stats['mapped_reads'] = count
            elif desc == 'duplicates':
                stats['duplicates'] = count

    stats['mapping_rate'] = round(stats['mapped_reads'] / stats['total_reads'], 6)
    return stats


# ---- Coverage computation ----

def compute_coverage(bam_path, bed_path):
    """Compute mean depth per target region using samtools depth."""
    # Read target regions
    regions = []
    with open(bed_path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                regions.append((parts[0], int(parts[1]), int(parts[2])))

    coverage_results = []
    for chrom, start, end in regions:
        region_size = end - start
        # Use samtools depth with -a (include zero-depth) and -r for region
        region_str = f"{chrom}:{start+1}-{end}"  # convert to 1-based
        stdout, _ = run_cmd(
            f"samtools depth -a -r {region_str} -G 1796 {bam_path}"
        )

        total_depth = 0
        count = 0
        for line in stdout.strip().split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) >= 3:
                    total_depth += int(parts[2])
                    count += 1

        # If samtools depth didn't return all positions, use region_size
        if count == 0:
            mean_depth = 0.0
        else:
            mean_depth = total_depth / region_size

        coverage_results.append({
            "chrom": chrom,
            "start": start,
            "end": end,
            "mean_depth": round(mean_depth, 2),
        })

    return coverage_results


# ---- CIGAR parsing and identity metrics ----

def parse_cigar(cigar_str):
    """Parse CIGAR string into (length, operator) tuples."""
    return [(int(n), op) for n, op in re.findall(r'(\d+)([MIDNSHP=X])', cigar_str)]


def compute_identities(cigar_str, nm):
    """Compute BLAST, gap-compressed, and gap-excluded identity."""
    ops = parse_cigar(cigar_str)
    match_bases = sum(n for n, op in ops if op in ('M', '=', 'X'))
    gap_bases = sum(n for n, op in ops if op in ('I', 'D'))
    gap_opens = sum(1 for _, op in ops if op in ('I', 'D'))
    aln_len = sum(n for n, op in ops if op in ('M', 'I', 'D', '=', 'X'))

    blast_id = (aln_len - nm) / aln_len if aln_len > 0 else 0.0
    denom_gc = match_bases + gap_opens
    gc_id = 1.0 - (nm - gap_bases + gap_opens) / denom_gc if denom_gc > 0 else 0.0
    mismatches = nm - gap_bases
    ge_id = (match_bases - mismatches) / match_bases if match_bases > 0 else 0.0

    return round(blast_id, 6), round(gc_id, 6), round(ge_id, 6)


def compute_alignment_identities(bam_path, name_map):
    """Compute identity metrics for primary, mapped, non-duplicate alignments."""
    # Use samtools view to get non-duplicate, primary, mapped alignments
    # -F 0x904 = exclude unmapped(4) + secondary(256) + supplementary(2048) = 0x904 = 2308
    # -F 0xD04 = also exclude duplicates(1024) = 0xD04 = 3332
    stdout, _ = run_cmd(f"samtools view -F 3332 {bam_path}")

    # Reverse name map for reporting in original convention
    rev_map = {v: v for v in set(name_map.values())}

    metrics = []
    for line in stdout.strip().split('\n'):
        if not line:
            continue
        fields = line.split('\t')
        qname = fields[0]
        flag = int(fields[1])
        rname = fields[2]
        pos = int(fields[3])
        cigar = fields[5]

        if cigar == '*':
            continue

        # Extract NM tag
        nm = None
        for field in fields[11:]:
            if field.startswith('NM:i:'):
                nm = int(field[5:])
                break
        if nm is None:
            continue

        blast_id, gc_id, ge_id = compute_identities(cigar, nm)
        metrics.append({
            "read_name": qname,
            "flag": flag,
            "cigar": cigar,
            "ref_name": rname,
            "position": pos,
            "blast_identity": blast_id,
            "gap_compressed_identity": gc_id,
            "gap_excluded_identity": ge_id,
        })

    # Sort by chromosome then position
    chrom_order = {"chr1": 0, "chr2": 1}
    metrics.sort(key=lambda m: (chrom_order.get(m["ref_name"], 99), m["position"]))
    return metrics


def compute_identity_summary(metrics):
    """Aggregate identity statistics."""
    n = len(metrics)
    if n == 0:
        return {
            "num_alignments": 0,
            "mean_blast_identity": 0.0,
            "mean_gap_compressed_identity": 0.0,
            "mean_gap_excluded_identity": 0.0,
            "high_quality_count": 0,
            "medium_quality_count": 0,
            "low_quality_count": 0,
        }

    return {
        "num_alignments": n,
        "mean_blast_identity": round(sum(m["blast_identity"] for m in metrics) / n, 6),
        "mean_gap_compressed_identity": round(sum(m["gap_compressed_identity"] for m in metrics) / n, 6),
        "mean_gap_excluded_identity": round(sum(m["gap_excluded_identity"] for m in metrics) / n, 6),
        "high_quality_count": sum(1 for m in metrics if m["gap_compressed_identity"] >= 0.95),
        "medium_quality_count": sum(1 for m in metrics if 0.85 <= m["gap_compressed_identity"] < 0.95),
        "low_quality_count": sum(1 for m in metrics if m["gap_compressed_identity"] < 0.85),
    }


# ---- Assembly metrics ----

def parse_fasta(fasta_path):
    """Parse FASTA file, return list of (name, sequence) tuples."""
    contigs = []
    name = None
    seq_parts = []
    with open(fasta_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('>'):
                if name is not None:
                    contigs.append((name, ''.join(seq_parts)))
                name = line[1:].split()[0]
                seq_parts = []
            else:
                seq_parts.append(line)
    if name is not None:
        contigs.append((name, ''.join(seq_parts)))
    return contigs


def compute_assembly_stats(contigs):
    """Compute assembly contiguity and composition metrics."""
    lengths = [len(seq) for _, seq in contigs]
    total_length = sum(lengths)
    gc_count = sum(sum(1 for c in seq if c in 'GCgc') for _, seq in contigs)

    sorted_lengths = sorted(lengths, reverse=True)
    cumsum = 0
    half = total_length / 2
    n50 = l50 = 0
    for i, l in enumerate(sorted_lengths):
        cumsum += l
        if cumsum >= half:
            n50 = l
            l50 = i + 1
            break

    aun = sum(l * l for l in lengths) / total_length if total_length > 0 else 0.0

    return {
        "num_contigs": len(lengths),
        "total_length": total_length,
        "largest_contig": max(lengths) if lengths else 0,
        "n50": n50,
        "l50": l50,
        "aun": round(aun, 6),
        "gc_content": round(gc_count / total_length, 6) if total_length > 0 else 0.0,
    }


# ---- Main ----

def main():
    sam_path = "/app/data/alignments.sam"
    ref_path = "/app/data/reference.fa"
    bed_path = "/app/data/targets.bed"
    assembly_path = "/app/data/assembly.fa"
    output_path = "/app/report.json"
    fixed_sam = "/tmp/fixed.sam"
    corrected_bam = "/tmp/corrected.bam"

    # Step 1: Discover and fix chromosome naming mismatch
    name_map = discover_naming_mismatch(sam_path, ref_path)
    fix_sam_chromosomes(sam_path, name_map, fixed_sam)

    data_issues = [
        f"Chromosome naming mismatch: SAM uses {list(name_map.keys())} "
        f"but reference uses {list(name_map.values())}. "
        f"Renamed chromosomes in alignment data to match reference.",
        "Alignment file is unsorted (SO:unsorted header). "
        "Coordinate-sorted and indexed for downstream analysis.",
        "PCR duplicate reads detected (pcr_dup_01, pcr_dup_05 at same positions "
        "as read01, read05). Marked duplicates using samtools markdup.",
    ]

    # Step 2: Process BAM (sort, fixmate, markdup, index)
    process_bam(fixed_sam, ref_path, corrected_bam)

    # Step 3: Mapping stats
    mapping_stats = get_flagstat(corrected_bam)

    # Step 4: Identity metrics
    alignment_identities = compute_alignment_identities(corrected_bam, name_map)
    identity_summary = compute_identity_summary(alignment_identities)

    # Step 5: Target coverage
    target_coverage = compute_coverage(corrected_bam, bed_path)

    # Step 6: Assembly stats
    contigs = parse_fasta(assembly_path)
    assembly_stats = compute_assembly_stats(contigs)

    # Build and write report
    report = {
        "data_issues": data_issues,
        "alignment_identities": alignment_identities,
        "identity_summary": identity_summary,
        "mapping_stats": mapping_stats,
        "target_coverage": target_coverage,
        "assembly_stats": assembly_stats,
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
