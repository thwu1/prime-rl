A BAM file at `/app/alignments.bam` (with `.bai` index) and reference genome at `/app/reference.fa` (with `.fai` index) contain alignment data with suspected integrity issues: some records carry incorrect NM (edit-distance) tags. The dataset uses both basic-CIGAR (M) and extended-CIGAR (=/X) conventions.

Produce:

**`/app/audit_report.json`** with this schema:

```json
{
  "total_records": int,
  "primary_alignments": int,
  "supplementary_alignments": int,
  "secondary_alignments": int,
  "unmapped": int,
  "passed_filter": int,
  "failed_filter": int,
  "nm_corrections": int,
  "reads": {
    "<qname>": {
      "blast_identity": float,
      "gc_identity": float,
      "gap_excluded_identity": float,
      "passed": bool,
      "nm_corrected": bool,
      "is_chimeric": bool
    }
  },
  "per_reference": {
    "<rname>": {
      "count": int,
      "mean_blast_identity": float,
      "mean_gc_identity": float,
      "mean_gap_excluded_identity": float,
      "passed": int,
      "failed": int
    }
  }
}
```

Assess only primary alignments. For extended-CIGAR records, verify NM tags against CIGAR-derived edit distance and flag any corrections. Detect chimeric reads via SA tags and supplementary flags. The quality filter uses gap-compressed identity with a threshold of 0.90 (inclusive).

**`/app/filtered.bam`** — Coordinate-sorted, indexed BAM (index at `/app/filtered.bam.bai`) containing only passing primary alignments, with corrected NM tags where applicable.