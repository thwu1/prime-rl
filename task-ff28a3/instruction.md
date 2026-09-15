A bioinformatics analyst abandoned a sequencing analysis workspace at `/app/data/` after encountering persistent errors. The directory contains alignment data, a reference genome, target regions, assembly contigs, and the analyst's notes. Genomic analysis command-line tools are available in the environment, but several of the data files have integrity or consistency problems that must be identified and resolved before any valid results can be produced.

Investigate the workspace, diagnose all data quality problems, and produce a validated analysis report at `/app/report.json` with the following sections:

- **`data_issues`**: Array of strings, each describing a distinct data quality problem you discovered and how it was resolved.

- **`alignment_identities`**: For each non-redundant primary mapped alignment (excluding secondary, supplementary, unmapped, and duplicate records), report: `read_name`, `flag`, `cigar`, `ref_name` (using the reference genome's chromosome naming), `position`, `blast_identity`, `gap_compressed_identity`, `gap_excluded_identity`. All identity values rounded to 6 decimal places. Entries ordered by genomic coordinate.

- **`identity_summary`**: `num_alignments`, `mean_blast_identity`, `mean_gap_compressed_identity`, `mean_gap_excluded_identity` (6 dp), and quality tier counts by gap-compressed identity: `high_quality_count` (>= 0.95), `medium_quality_count` ([0.85, 0.95)), `low_quality_count` (< 0.85).

- **`mapping_stats`**: From a correctly processed BAM: `total_reads` (int), `mapped_reads` (int), `duplicates` (int), `mapping_rate` (float, 6 dp).

- **`target_coverage`**: Mean read depth across each interval in the BED file, computed from the corrected, deduplicated alignment. Array of `{"chrom", "start", "end", "mean_depth"}` (mean_depth rounded to 2 dp). Positions with zero coverage within each interval must be included in the mean calculation.

- **`assembly_stats`**: `num_contigs`, `total_length`, `largest_contig`, `n50`, `l50`, `aun` (6 dp), `gc_content` (6 dp).