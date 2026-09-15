#!/bin/bash

set -e

###############################################################################
# Fix Bug 1: params.outdir is never defined, so publishDir paths resolve to
# "null/per_sample" etc. Add the outdir parameter to nextflow.config.
###############################################################################
sed -i '/min_length/a\    outdir     = "${projectDir}/results"' /app/nextflow.config

###############################################################################
# Fix Bug 2: publishDir mode 'move' removes files from the work directory.
# Downstream processes reference files via work-dir paths, so they get
# "file not found" errors. Change to 'copy' to preserve originals.
###############################################################################
sed -i "s/mode: 'move'/mode: 'copy'/" /app/modules/count_words.nf

###############################################################################
# Fix Bug 3: Output declaration says path("filtered.txt") but the script
# writes ${sample_id}_filtered.txt. Nextflow can't find the declared output.
###############################################################################
sed -i 's/path("filtered\.txt")/path("${sample_id}_filtered.txt")/' /app/modules/filter_words.nf

###############################################################################
# Fix Bug 4 (Channel.of→Channel.value) + Bug 5 (.map{it[1]} stripping
# sample_id before NORMALIZE_TF) + Bug 6 (missing COMPUTE_IDF/SUMMARIZE):
# Replace main.nf with corrected version that:
#   - Uses Channel.value() for broadcast parameter
#   - Passes full tuple to NORMALIZE_TF
#   - Forks FILTER_WORDS.out to both NORMALIZE_TF and COMPUTE_IDF
#   - Wires SUMMARIZE with collected TF files + IDF file
###############################################################################
cp /solution/main_fixed.nf /app/main.nf

###############################################################################
# Implement NORMALIZE_TF: compute term frequency (count/total) per word
# in filtered documents, output 6 decimal places, sorted by tf desc then
# word asc for ties.
###############################################################################
cp /solution/normalize_tf.nf /app/modules/normalize_tf.nf

###############################################################################
# Create COMPUTE_IDF module: reads all collected filtered documents, computes
# document frequency and IDF = ln(N/df) for each word, outputs sorted TSV.
###############################################################################
cp /solution/compute_idf.nf /app/modules/compute_idf.nf

###############################################################################
# Create SUMMARIZE module: reads all TF files + IDF file, computes TF-IDF
# per word per document, finds top TF-IDF words per sample and globally,
# outputs summary.json.
###############################################################################
cp /solution/summarize.nf /app/modules/summarize.nf

###############################################################################
# Clean any previous runs and execute the fixed pipeline
###############################################################################
rm -rf /app/.nextflow /app/work /app/results /app/null
cd /app && nextflow run main.nf -ansi-log false
