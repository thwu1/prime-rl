# Multi-Modal Product Search — Ranking System Requirements

## Overview

This Vespa application implements multi-modal product search for an audio
equipment catalog. The ranking pipeline operates in three tiers using rank
profile inheritance, progressively refining result quality through multi-phase
evaluation with increasingly expensive scoring signals.

## Document Model

Products are represented with seven fields:

| Field | Type | Purpose |
|-------|------|---------|
| `title` | `string` | Product name. BM25-indexed for text matching. |
| `body` | `string` | Product description. BM25-indexed for text matching. |
| `price` | `float` | Price in USD. Stored as an attribute for use in ranking expressions. |
| `quality_score` | `float` | Editorial quality rating in range [0, 1]. Stored as attribute. |
| `category_weights` | `tensor<float>(category{})` | Sparse mapped tensor of per-category relevance scores keyed by category name (e.g. `{"Electronics": 0.9, "Audio": 0.85}`). Stored as attribute. |
| `embedding` | `tensor<float>(v[384])` | Dense 384-dimensional text embedding. Must support approximate nearest neighbor search via HNSW graph indexing with **angular** distance metric. |
| `tags_embedding` | `tensor<bfloat16>(v[64])` | Dense 64-dimensional tag embedding stored in half-precision bfloat16 for memory efficiency. Must support approximate nearest neighbor search via HNSW graph indexing with **euclidean** distance metric. |

A default fieldset should cover both `title` and `body` for unqualified text
queries.

## Query Inputs

The `hybrid` rank profile accepts these query-time tensor/scalar inputs:

| Input | Type | Purpose |
|-------|------|---------|
| `query(q_embedding)` | `tensor<float>(v[384])` | Query text embedding for semantic similarity against `embedding` field. |
| `query(q_tags)` | `tensor<float>(v[64])` | Query tag vector for similarity against `tags_embedding` field. Note: query uses float precision; Vespa handles the type conversion during nearest neighbor computation. |
| `query(user_prefs)` | `tensor<float>(category{})` | User's category preference weights. The mapped dimension name must match the document `category_weights` field's dimension so that the tensor join produces an element-wise product (dot product), not an outer product. |
| `query(max_price)` | `double` | Maximum acceptable price for full-score pricing. |

## Constant Tensors

A pre-trained linear scoring weight vector is provided as a constant tensor:

| Constant | Type | File |
|----------|------|------|
| `scoring_weights` | `tensor<float>(feature[5])` | `constants/scoring_weights.json` |

The constant must be declared at the schema level with a `file:` reference
pointing to the provided JSON file and an explicit `type:` declaration.

## Ranking Architecture

### Tier 1: `text_match` (inherits `default`)

Baseline text-only ranking using BM25 signals. Title matches carry double the
weight of body matches.

**First-phase expression:**

    2.0 * bm25(title) + bm25(body)

### Tier 2: `hybrid` (inherits `text_match`)

Extends text matching with vector similarity, category preference matching,
and price sensitivity. Declares all query inputs listed above.

**Scoring functions:**

- `text_relevance()`: Reproduces the text matching formula:
  `2.0 * bm25(title) + bm25(body)`

- `semantic_similarity()`: Returns the field-specific closeness score between
  the query embedding and the document's `embedding` field. Must use the
  two-argument closeness form that explicitly names the field.

- `tag_similarity()`: Returns the field-specific closeness score between the
  query tag vector and the document's `tags_embedding` field. Must use the
  two-argument closeness form.

- `preference_score()`: Computes the dot product between user category
  preferences and document category weights via tensor multiplication
  followed by a sum reduction. Produces a scalar score representing
  category alignment.

- `price_factor()`: Conditional price scoring. If the product's price is at
  or below `query(max_price)`, returns 1.0 (full score). Otherwise, returns
  a decay value computed as:

      1.0 / (1.0 + (attribute(price) - query(max_price)) / 50.0)

  This ensures products above budget receive a gradually decreasing
  multiplier rather than a hard cutoff.

**First-phase expression:**

    text_relevance + 0.4 * semantic_similarity + 0.15 * tag_similarity + 0.25 * preference_score

**Match features:** Expose `text_relevance`, `semantic_similarity`,
`tag_similarity`, `preference_score`, and `price_factor` as match-features for
first-phase debugging.

### Tier 3: `production` (inherits `hybrid`)

Adds a learned second-phase reranking stage that combines all scoring signals
through a pre-trained linear model, enhanced with quality-adjusted pricing.

**Scoring functions:**

- `feature_vector()`: Constructs an inline indexed tensor of type
  `tensor<float>(feature[5])` containing the five signal values in order:
  `[text_relevance, semantic_similarity, tag_similarity, preference_score, price_factor]`.
  Uses Vespa's inline tensor literal syntax.

- `learned_combination()`: Computes the dot product between `feature_vector`
  and `constant(scoring_weights)` by multiplying element-wise and reducing
  with sum along the `feature` dimension. This produces the learned linear
  combination of all ranking signals.

- `quality_boost()`: Computes `attribute(quality_score) * price_factor`,
  giving a quality-and-price-adjusted bonus.

**Second-phase expression:**

    learned_combination + 0.1 * quality_boost

**Rerank count:** 100

**Summary features:** Expose all eight scoring functions for production
monitoring: `text_relevance`, `semantic_similarity`, `tag_similarity`,
`preference_score`, `price_factor`, `feature_vector`, `learned_combination`,
`quality_boost`.
