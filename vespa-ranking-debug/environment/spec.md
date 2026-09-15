# Product Search Hybrid Ranking -- Design Document

## System Overview

This Vespa application implements hybrid product search for an audio equipment
catalog. The ranking pipeline operates in three tiers, progressively refining
result quality through multi-phase evaluation.

## Document Model

Products are represented with the following fields:

- **title** (string): Product name, BM25-indexed for text matching
- **description** (string): Product description, BM25-indexed for text matching
- **price** (float): Product price in USD, used as an attribute for scoring
- **popularity** (float): Popularity/quality score in range 0--1
- **category_scores** (tensor<float>(category{})): Sparse mapped tensor storing
  per-category relevance scores keyed by category name (e.g. "Electronics": 0.9,
  "Audio": 0.85)
- **embedding** (tensor<float>(x[8])): Dense 8-dimensional embedding vector for
  semantic similarity. This field supports approximate nearest neighbor search
  via HNSW graph indexing with angular distance metric.

## Ranking Architecture

### Tier 1: text_search

Baseline text-only ranking using BM25 signals. Title matches are weighted more
heavily than description matches.

Formula: `bm25(title) + 0.5 * bm25(description)`

### Tier 2: hybrid

Extends text_search with two additional signals computed from document and
query tensors:

- **Vector similarity**: Measures closeness between the query embedding and
  the document embedding. Uses Vespa's field-specific closeness rank feature
  to obtain the similarity score from the nearest neighbor computation over
  the embedding field.

- **Category boosting**: Computes a dot product between the user's category
  interest weights (a query tensor) and the document's per-category relevance
  scores. For this computation to produce meaningful results, the query tensor
  and document tensor must share the same mapped dimension so that Vespa's
  tensor join operation matches corresponding cells element-wise rather than
  producing an outer product.

The first-phase expression linearly combines all three signals:
`text_score + 0.3 * vector_score + 0.2 * category_boost`

### Tier 3: full_ranking

Adds a second-phase reranking step that incorporates price and popularity:

- **price_adjustment**: An inverse price scaling factor that produces values
  in (0, 1]. A free item ($0) gets an adjustment of 1.0, a $100 item gets
  0.5, and a $200 item gets approximately 0.333. The formula is designed so
  that expensive items receive a smaller multiplier.

- **freshness_score**: Uses the document's popularity attribute as a quality
  proxy.

- **combined_score**: Enhances the first-phase hybrid score by adding
  `0.15 * freshness_score * price_adjustment` -- this boosts popular,
  reasonably-priced items.

All intermediate scoring functions are exposed via summary-features for
production monitoring and debugging. Each summary-feature entry must
reference an actually-defined function by its exact name.
