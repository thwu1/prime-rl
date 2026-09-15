process COMPUTE_IDF {
    publishDir "${params.outdir}/doc_freq", mode: 'copy'

    input:
    path(filtered_files)

    output:
    path("idf.tsv")

    script:
    """
    cat << 'PYEOF' > _compute_idf.py
import glob, math

doc_words = []
for f in sorted(glob.glob("*_filtered.txt")):
    words = set()
    with open(f) as fh:
        for line in fh:
            parts = line.strip().split("\\t")
            if len(parts) == 2:
                words.add(parts[0])
    doc_words.append(words)

N = len(doc_words)
all_words = set()
for dw in doc_words:
    all_words |= dw

entries = []
for word in sorted(all_words):
    df = sum(1 for dw in doc_words if word in dw)
    idf = math.log(N / df)
    entries.append((word, df, idf))

entries.sort(key=lambda e: (-e[2], e[0]))

with open("idf.tsv", "w") as out:
    for word, df, idf in entries:
        out.write(f"{word}\\t{df}\\t{idf:.6f}\\n")
PYEOF
    python3 _compute_idf.py
    """
}
