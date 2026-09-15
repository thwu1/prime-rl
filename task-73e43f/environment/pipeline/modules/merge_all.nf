process MERGE_ALL {
    publishDir "${params.outdir}", mode: 'copy'

    input:
    path(count_files)

    output:
    path("global_frequencies.txt")

    script:
    """
    cat ${count_files} | awk -F'\\t' '{counts[\$1] += \$2} END {for (w in counts) printf "%s\\t%d\\n", w, counts[w]}' | sort -t\$'\\t' -k2 -rn > global_frequencies.txt
    """
}
