The directory `/app/` contains a reference genome (`reference.fa`, pre-indexed), a SAM file of read alignments (`alignments.sam`) with NM (edit distance) tags, a pipeline specification (`pipeline_config.yaml`), and documentation under `docs/` defining the mathematical formulas for three sequence identity metrics and the auN contiguity statistic.

Some alignments have incorrect NM tags. Build a pipeline that recomputes the correct NM for every mapped alignment by walking each CIGAR string against the reference sequence, computes three identity metrics using the formulas in `docs/identity_metrics.md`, filters alignments by quality, and produces the three output files described below — all written to `/app/`.

## Output 1: `/app/identity_report.tsv`

Tab-separated file with a header row and one row per mapped alignment, sorted lexicographically by `read_name`. The header and columns must be exactly:

| Column | Type | Description |
|--------|------|-------------|
| `read_name` | string | Read identifier from the SAM |
| `blast_identity` | float, 6 decimal places | BLAST identity as defined in `docs/identity_metrics.md` |
| `gap_compressed_identity` | float, 6 decimal places | Gap-compressed identity as defined in `docs/identity_metrics.md` |
| `gap_excluded_identity` | float, 6 decimal places | Gap-excluded identity as defined in `docs/identity_metrics.md` |
| `original_nm` | int | NM tag value from the input SAM |
| `correct_nm` | int | NM recomputed by walking the CIGAR against the reference |
| `nm_is_correct` | string | `true` if original NM equals recomputed NM, otherwise `false` |

All identity metrics must be computed using the recomputed (correct) NM, not the original tag value.

## Output 2: `/app/corrected.bam` and `/app/corrected.bam.bai`

A coordinate-sorted, indexed BAM containing only alignments whose gap-compressed identity is >= 0.85. Every retained alignment's NM tag must be replaced with the recomputed correct value.

## Output 3: `/app/summary.json`

A JSON object with these exact keys:

| Key | Type | Description |
|-----|------|-------------|
| `total_alignments` | int | Count of all mapped alignments |
| `alignments_with_incorrect_nm` | int | Count where original NM != recomputed NM |
| `mean_blast_identity` | float, 6 decimal places | Arithmetic mean of BLAST identity over all alignments |
| `mean_gap_compressed_identity` | float, 6 decimal places | Arithmetic mean of gap-compressed identity over all alignments |
| `mean_gap_excluded_identity` | float, 6 decimal places | Arithmetic mean of gap-excluded identity over all alignments |
| `alignments_passing_filter` | int | Count of alignments passing the gc >= 0.85 filter |
| `alignment_aun` | float | auN computed on aligned lengths of passing alignments only (see `docs/aun_metric.md`) |