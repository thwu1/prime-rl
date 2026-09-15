# BM25 Scoring Specification

## Parameters

- `k1 = 1.2`
- `b = 0.75`

## Formulas

**IDF (Inverse Document Frequency):**

```
IDF(t) = ln((N - df(t) + 0.5) / (df(t) + 0.5) + 1)
```

where `N` = total number of documents, `df(t)` = number of documents containing term `t`, and `ln` is the natural logarithm.

**Term score:**

```
BM25(t, d) = IDF(t) * (tf(t,d) * (k1 + 1)) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
```

where `tf(t,d)` = number of occurrences of term `t` in document `d`, `|d|` = total number of tokens in document `d`, `avgdl` = average document length across all documents.

**Query score:**

```
score(q, d) = SUM of BM25(t, d) for each unique term t in query q
```

The query score is a disjunctive sum: a document only needs to contain _any_ query term to receive a nonzero score.

## Tokenization

- Convert text to lowercase
- Split on whitespace (no stemming, no stopword removal, no punctuation handling)
- Deduplicate query terms: each unique term contributes once to the score

## Tie-breaking

When ranking results, sort by:
1. Score descending (higher is better)
2. Document ID ascending (lower ID first for ties)

## Corpus Format

The corpus is at `/app/corpus.jsonl`. Each line is a JSON object:

```json
{"id": 0, "text": "the quick brown fox"}
```

`id` is a non-negative integer. `text` is the document content to tokenize and index.
