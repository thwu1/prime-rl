# Product Search Ranking Pipeline -- Business Requirements

## Overview

The application at `/app/application/` provides multi-modal product search for an audio
equipment catalog. The schema at `/app/application/schemas/product.sd` currently contains
only document field definitions and no ranking logic. Design and implement the full
ranking pipeline.

Three team members have submitted competing design proposals at `/app/proposals/`. Each
proposal contains a mix of correct and incorrect technical recommendations. Evaluate all
proposals critically before implementing -- do not follow any single proposal wholesale.

## Document Field Specifications

| Field | Type | Constraint |
|-------|------|------------|
| title | string | BM25-indexed |
| body | string | BM25-indexed |
| price | float | Attribute |
| quality_score | float | Attribute, range [0,1] |
| category_weights | tensor&lt;float&gt;(category{}) | Sparse mapped tensor. Dimension MUST be named `category`. |
| embedding | tensor&lt;float&gt;(v[384]) | Angular distance. Must support ANN search. |
| tags_embedding | tensor&lt;bfloat16&gt;(v[64]) | Euclidean distance. Must support ANN search. Half-precision (bfloat16) for memory efficiency. |

Both embedding fields must support approximate nearest neighbor (ANN) queries. A default
fieldset should cover `title` and `body` for unqualified text queries.

**Note:** The current schema may contain issues in the document field definitions that
must be corrected before adding ranking logic.

## Ranking Architecture

Three-tier inheritance: `text_match` -> `hybrid` -> `production`.

### Tier 1: text_match (inherits default)

Baseline BM25 text ranking. Title matches carry double the weight of body matches.

### Tier 2: hybrid (inherits text_match)

Adds vector similarity, category preference matching, and price sensitivity. Declares
these query-time inputs:

- `query(q_embedding)` tensor&lt;float&gt;(v[384])
- `query(q_tags)` tensor&lt;float&gt;(v[64])
- `query(user_prefs)` tensor&lt;float&gt;(category{}) -- dimension must match document field
- `query(max_price)` double

Five scoring functions:

1. **text_relevance**: Reproduces the text_match BM25 formula
2. **semantic_similarity**: Similarity score between query embedding and document `embedding` field
3. **tag_similarity**: Similarity score between query tag vector and document `tags_embedding` field
4. **preference_score**: Scalar dot product of user preferences and document category weights via tensor multiplication + sum reduction
5. **price_factor**: Returns 1.0 at or below budget. Smooth decay above budget.
   Validation constraints: price=150, max_price=100 must yield **exactly 0.5**.
   price=350, max_price=100 must yield **exactly 1/6**.

First-phase expression:
`text_relevance + 0.4 * semantic_similarity + 0.15 * tag_similarity + 0.25 * preference_score`

All five scoring functions must be exposed as match-features for debugging.

### Tier 3: production (inherits hybrid)

Learned second-phase reranking. The production model was trained on 5-dimensional feature
vectors with rerank-count=100. These training parameters are fixed constraints that the
schema must match exactly.

Three additional scoring functions:

6. **feature_vector**: Inline indexed tensor `tensor<float>(feature[5])` containing all
   five hybrid scoring signals in order
7. **learned_combination**: Dot product of feature_vector with `constant(scoring_weights)`,
   computed via element-wise multiplication and sum reduction along the `feature` dimension
8. **quality_boost**: Product of quality_score attribute and price_factor function

Second-phase expression: `learned_combination + 0.1 * quality_boost`

All eight scoring functions exposed as summary-features for production monitoring.

## Constant Tensors

A pre-trained weight vector is at `constants/scoring_weights.json`. It must be declared
as a schema-level constant named `scoring_weights` with:
- `file:` reference to `constants/scoring_weights.json`
- `type:` declaration of `tensor<float>(feature[5])`
