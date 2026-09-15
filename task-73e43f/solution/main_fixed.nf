#!/usr/bin/env nextflow

include { COUNT_WORDS } from './modules/count_words'
include { FILTER_WORDS } from './modules/filter_words'
include { NORMALIZE_TF } from './modules/normalize_tf'
include { COMPUTE_IDF } from './modules/compute_idf'
include { SUMMARIZE } from './modules/summarize'

workflow {
    Channel.fromPath(params.samples)
        .splitCsv(header: true)
        .map { row -> tuple(row.sample_id, file(row.file_path)) }
        .set { samples_ch }

    min_len = Channel.value(params.min_length)

    COUNT_WORDS(samples_ch)
    FILTER_WORDS(COUNT_WORDS.out, min_len)

    // Diamond: FILTER_WORDS.out forks to both NORMALIZE_TF and COMPUTE_IDF
    NORMALIZE_TF(FILTER_WORDS.out)
    COMPUTE_IDF(FILTER_WORDS.out.map { it[1] }.collect())

    // Converge: SUMMARIZE takes per-sample TF files + global IDF
    SUMMARIZE(NORMALIZE_TF.out.map { it[1] }.collect(), COMPUTE_IDF.out)
}
