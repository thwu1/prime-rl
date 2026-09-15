A genome sequencing pipeline has deposited k-mer observation data in `/app/data/`. The dataset manifest at `/app/data/manifest.yaml` describes the available data sources, their storage formats, and field semantics.

The data is distributed across three storage backends: a SQLite database containing observations and pipeline configuration metadata, an AES-encrypted binary overflow partition whose decryption credentials are stored in the database's parameter tables, and supplementary observations in Apache Parquet columnar format. The pipeline's error-correction stage was interrupted, so the dataset contains both genuine genomic k-mers and spurious k-mers from uncorrected sequencing errors.

Reconstruct the genome's contiguous sequences (contigs) from the reliable k-mers and produce assembly quality metrics. Write two output files:

1. `/app/output/contigs.txt` — one assembled contig per line, sorted lexicographically
2. `/app/output/stats.json` — JSON object with integer-valued keys: `num_contigs`, `total_bases`, `largest_contig`, `n50`