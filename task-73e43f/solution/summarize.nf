process SUMMARIZE {
    publishDir "${params.outdir}", mode: 'copy'

    input:
    path(tf_files)
    path(idf_file)

    output:
    path("summary.json")

    script:
    """
    cat << 'PYEOF' > _summarize.py
import json, glob

# Read IDF values
idf_values = {}
with open("idf.tsv") as f:
    for line in f:
        parts = line.strip().split("\\t")
        if len(parts) == 3:
            idf_values[parts[0]] = float(parts[2])

samples = {}
global_tfidf = {}

for tf_file in sorted(glob.glob("*_tf.txt")):
    sample_id = tf_file.replace("_tf.txt", "")
    words_tfidf = {}
    with open(tf_file) as f:
        for line in f:
            parts = line.strip().split("\\t")
            if len(parts) == 2:
                word, tf = parts[0], float(parts[1])
                idf = idf_values.get(word, 0.0)
                tfidf = tf * idf
                words_tfidf[word] = tfidf
                if word not in global_tfidf or tfidf > global_tfidf[word]:
                    global_tfidf[word] = tfidf

    top_word = max(sorted(words_tfidf.keys()), key=lambda w: words_tfidf[w])
    samples[sample_id] = {
        "unique_words": len(words_tfidf),
        "top_tfidf_word": top_word,
        "top_tfidf_score": round(words_tfidf[top_word], 6)
    }

global_top = max(sorted(global_tfidf.keys()), key=lambda w: global_tfidf[w])

result = {
    "num_documents": len(samples),
    "samples": samples,
    "global_top_tfidf_word": global_top
}

with open("summary.json", "w") as f:
    json.dump(result, f, indent=2, sort_keys=True)
PYEOF
    python3 _summarize.py
    """
}
