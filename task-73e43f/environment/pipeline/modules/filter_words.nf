process FILTER_WORDS {
    tag "${sample_id}"
    publishDir "${params.outdir}/filtered", mode: 'copy'

    input:
    tuple val(sample_id), path(counts)
    val(min_len)

    output:
    tuple val(sample_id), path("filtered.txt")

    script:
    """
    awk -F'\\t' -v min_len=${min_len} 'length(\$1) >= min_len' ${counts} > ${sample_id}_filtered.txt
    """
}
