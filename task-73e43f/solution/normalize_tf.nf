process NORMALIZE_TF {
    tag "${sample_id}"
    publishDir "${params.outdir}/normalized", mode: 'copy'

    input:
    tuple val(sample_id), path(filtered_counts)

    output:
    tuple val(sample_id), path("${sample_id}_tf.txt")

    script:
    """
    awk -F'\\t' '
      { words[\$1] = \$2; sum += \$2 }
      END { for (w in words) printf "%s\\t%.6f\\n", w, words[w]/sum }
    ' ${filtered_counts} | sort -t\$'\\t' -k2,2rn -k1,1 > ${sample_id}_tf.txt
    """
}
