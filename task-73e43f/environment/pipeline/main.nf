#!/usr/bin/env nextflow

include { COUNT_WORDS } from './modules/count_words'
include { FILTER_WORDS } from './modules/filter_words'
include { NORMALIZE_TF } from './modules/normalize_tf'

workflow {
    // Parse sample sheet: extract (sample_id, file_path) tuples
    Channel.fromPath(params.samples)
        .splitCsv(header: true)
        .map { row -> tuple(row.sample_id, file(row.file_path)) }
        .set { samples_ch }

    // Minimum word length threshold
    min_len = Channel.of(params.min_length)

    // Stage 1: Count word frequencies per document
    COUNT_WORDS(samples_ch)

    // Stage 2: Filter words below minimum length
    FILTER_WORDS(COUNT_WORDS.out, min_len)

    // Extract just file paths for downstream processing
    filtered_ch = FILTER_WORDS.out.map { it[1] }

    // Stage 3: Normalize term frequencies
    NORMALIZE_TF(filtered_ch)

    // Stage 4-5: Compute IDF and generate TF-IDF summary report
    // TODO: Create and wire COMPUTE_IDF and SUMMARIZE processes
    NORMALIZE_TF.out.collect()
}
