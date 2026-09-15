A Nextflow DSL2 pipeline in `/app/` is designed to process text documents through a multi-stage term frequency-inverse document frequency (TF-IDF) analysis. It reads a sample sheet (`/app/data/samples.csv`) and should process each document through word counting, short-word filtering, per-document TF normalization, corpus-wide IDF computation, and cross-document TF-IDF summarization.

The pipeline has multiple interacting defects across its modules, workflow wiring, and configuration. The `NORMALIZE_TF` module (`/app/modules/normalize_tf.nf`) is a non-functional stub. No `COMPUTE_IDF` or `SUMMARIZE` modules exist. A `MERGE_ALL` module exists in the modules directory but is not the correct approach for this pipeline. The workflow in `/app/main.nf` has channel semantics issues that silently cause data loss or process failures.

Fix all issues and implement the missing components so that `nextflow run /app/main.nf` (run from `/app/`) produces correct outputs.

## Required Outputs

All outputs under `/app/results/`:

- `per_sample/{id}_wordcounts.txt` — TSV (`word\tcount`), lowercase alphabetic tokens only, sorted by count descending
- `filtered/{id}_filtered.txt` — same format, only words with `length >= params.min_length` (default: 3)
- `normalized/{id}_tf.txt` — TSV (`word\ttf`), where `tf = count / total_filtered_count_in_document` formatted to 6 decimal places, sorted by tf descending then word ascending for ties
- `doc_freq/idf.tsv` — TSV (`word\tdf\tidf`) where `df` is the number of documents containing the word and `idf = ln(N/df)` (natural log, N = total number of documents), idf formatted to 6 decimal places, sorted by idf descending then word ascending for ties
- `summary.json` — JSON with structure:

```json
{
  "num_documents": "<int: total number of documents processed>",
  "samples": {
    "<sample_id>": {
      "unique_words": "<int: number of unique words in the TF file>",
      "top_tfidf_word": "<word with highest TF-IDF score; alphabetically first if tied>",
      "top_tfidf_score": "<float: the top TF-IDF score, rounded to 6 decimal places>"
    }
  },
  "global_top_tfidf_word": "<word with highest TF-IDF score across all documents; alphabetically first if tied>"
}
```

Where `TF-IDF(word, document) = TF(word, document) * IDF(word)`.

All three documents in the sample sheet must be processed through all stages.