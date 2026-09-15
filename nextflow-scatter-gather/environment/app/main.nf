#!/usr/bin/env nextflow


nextflow.enable.dsl=2

params.samplesheet = "${projectDir}/samplesheet.csv"
params.reference = "${projectDir}/reference.csv"
params.outdir = "${projectDir}/results"

/*
 * DETAILED_ANALYSIS: Process high-priority samples.
 * Computes quality-weighted mean of all measurements.
 */
process DETAILED_ANALYSIS {
    tag "${sample_id}"

    input:
    tuple val(sample_id), val(experiment), path(datafile)

    output:
    tuple val(sample_id), val(experiment), val('high'), path("${sample_id}_result.csv")

    script:
    """
    echo "TODO"
    """
}

/*
 * QUICK_ANALYSIS: Process low-priority samples.
 * Filters out low-quality measurements, computes simple mean of the rest.
 */
process QUICK_ANALYSIS {
    tag "${sample_id}"

    input:
    tuple val(sample_id), val(experiment), path(datafile)

    output:
    tuple val(sample_id), val(experiment), val('low'), path("${sample_id}_result.csv")

    script:
    """
    echo "TODO"
    """
}

/*
 * AGGREGATE_EXPERIMENT: Combine per-sample results within each experiment.
 * Computes count-weighted grand mean and sample counts.
 */
process AGGREGATE_EXPERIMENT {
    tag "${experiment}"

    input:
    tuple val(experiment), val(sample_ids), val(priorities), path(result_files)

    output:
    tuple val(experiment), path("${experiment}_aggregate.json")

    script:
    """
    echo "TODO"
    """
}

/*
 * EVALUATE_EXPERIMENT: Compare aggregated results against reference values.
 * Determines whether each experiment is within tolerance.
 */
process EVALUATE_EXPERIMENT {
    tag "${experiment}"

    input:
    tuple val(experiment), path(aggregate), val(expected_mean), val(tolerance)

    output:
    tuple val(experiment), path("${experiment}_evaluation.json")

    script:
    """
    echo "TODO"
    """
}

/*
 * GENERATE_REPORT: Collect all experiment evaluations into a single report.
 */
process GENERATE_REPORT {
    publishDir params.outdir, mode: 'copy'

    input:
    path(evaluations)

    output:
    path("report.json")

    script:
    """
    echo "TODO"
    """
}

workflow {
    // TODO: Implement the workflow according to SPEC.md
}
