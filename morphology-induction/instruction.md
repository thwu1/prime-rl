An extraterrestrial microorganism's genome has been sequenced and its protein products identified by mass spectrometry. The organism uses a non-standard genetic code: its DNA-to-protein translation differs from Earth's universal code in multiple codon assignments, and two context-dependent translation rules modify amino acid output based on nucleotide context at codon boundaries.

Experimental data is distributed across four heterogeneous sources linked by gene ID and batch ID:

- `/app/data/genome_sequences.fasta.gz` — Gzip-compressed FASTA-format DNA coding sequences (5'-to-3' coding strand, A/T/G/C). Headers contain gene ID, organism, sample type (`characterized` or `uncharacterized`), and sequencing batch ID.
- `/app/data/proteomics.db` — SQLite database with tables `samples` (gene metadata: organism, sample type, batch), `mass_spec_results` (protein identifications with confidence scores and instrument IDs), `instrument_calibrations` (calibration records with validity dates), and `run_instrument_assignments` (which instruments were used in which runs). Some genes have multiple mass-spec results at different confidence levels; not all are reliable.
- `/app/data/experiment_metadata.xml` — XML document describing sequencing runs with nested quality-control elements (`<quality_control>` containing `<qc_passed>` text nodes), an instrument registry with calibration status, and analysis notes. Run IDs are stored as `id` attributes on `<run>` elements under `<sequencing_runs>`.
- `/app/data/batch_reports.tar.gz` — Gzip-compressed tar archive containing per-batch QC report files in JSON format. Each report has deeply nested `qc_metrics` with sub-objects for read quality, contamination screening, coverage, and library complexity, plus an `overall_qc` field. The batch reports must corroborate the XML validation status — a run is valid only if both the XML `qc_passed` element reads `true` AND the corresponding batch report's `overall_qc` is `PASS`.

A gene's data is usable only if: (1) the gene is from the xenobiont organism (not the E. coli control), (2) the gene's batch appears in a sequencing run validated in both the XML and the batch report, and (3) the mass-spec protein is the highest-confidence result for that gene from a calibrated instrument. Characterized xenobiont genes from validated runs, paired with their highest-confidence mass-spec protein, form the training set. Uncharacterized xenobiont genes from validated runs need translation.

Note: some protein sequences are longer than the codon count suggests, and some amino acids differ from naive codon-table predictions — both effects arise from the two context-dependent rules.

Recover the complete alien codon table (all 64 triplet-to-amino-acid mappings, `*` for stop) and the two context-dependent translation rules. Translate all uncharacterized xenobiont sequences from validated runs.

Write translated proteins (one per line, in gene-ID order) to `/app/results/translated.txt`.
Write the codon table as tab-separated `codon\tamino_acid` rows (64 rows, no header, sorted alphabetically) to `/app/results/codon_table.tsv`.