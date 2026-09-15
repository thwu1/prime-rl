process COUNT_WORDS {
    tag "${sample_id}"
    publishDir "${params.outdir}/per_sample", mode: 'move'

    input:
    tuple val(sample_id), path(document)

    output:
    tuple val(sample_id), path("${sample_id}_wordcounts.txt")

    script:
    """
    cat ${document} | tr '[:upper:]' '[:lower:]' | tr -cs '[:alpha:]' '\\n' | \\
        grep -v '^\$' | sort | uniq -c | sort -rn | \\
        awk '{printf "%s\\t%s\\n", \$2, \$1}' > ${sample_id}_wordcounts.txt
    """
}
