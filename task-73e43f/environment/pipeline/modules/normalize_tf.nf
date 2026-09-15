process NORMALIZE_TF {
    tag "${sample_id}"
    publishDir "${params.outdir}/normalized", mode: 'copy'

    input:
    tuple val(sample_id), path(filtered_counts)

    output:
    tuple val(sample_id), path("${sample_id}_tf.txt")

    script:
    """
    touch ${sample_id}_tf.txt
    """
}
