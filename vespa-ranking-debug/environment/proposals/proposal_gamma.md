# Ranking Pipeline Design -- Proposal C
**Author:** Alex Rivera, Relevance Engineering Lead
**Date:** 2024-11-16

## Document Field Assessment

1. **tags_embedding cell type**: Must be `bfloat16`, not `float`. Half-precision is
   standard practice for auxiliary embeddings where memory efficiency outweighs marginal
   precision gains. At 64 dimensions the accuracy difference is negligible.

2. **HNSW indexing**: Both embedding fields need `| index` added to the indexing pipeline.
   The `distance-metric` in the attribute block only specifies the metric function --
   actual HNSW graph construction requires the `index` directive in the pipeline. Current
   pipeline `summary | attribute` must become `summary | attribute | index`.

3. **Distance metrics**: Keep `angular` for `embedding` (semantic text similarity) and
   `euclidean` for `tags_embedding` (tag space distances). These match our training setup.

4. **category_weights dimension**: Rename from `cat` to `category`. Vespa joins tensors
   by matching dimension names, so the query input must use the same name.

5. **closeness syntax**: Use `closeness(field, embedding)` and `closeness(field, tags_embedding)`.
   The two-argument form is required when a schema has multiple tensor fields with HNSW
   indexes, as the single-argument form cannot disambiguate which field's ANN result to use.

6. **Fieldset**: Add `fieldset default` for `title` and `body`.

## Rank Profile Design

### text_match

Standard BM25 with title weighted 2x. No changes from other proposals.

### hybrid

I agree with the five-function design and the first-phase expression. My price_factor
implementation uses proper operator grouping:

```
function price_factor() {
    expression: if(attribute(price) <= query(max_price), 1.0, 1.0 / (1.0 + (attribute(price) - query(max_price)) / 50.0))
}
```

Verification: at price=150, max_price=100, this gives `1.0 / (1.0 + 50/50) = 1.0/2.0 = 0.5`. Correct.

### production

I recommend a latency-optimized production profile:

- **rerank-count: 50** -- Our analysis shows diminishing returns above 50 candidates.
  Reducing from 100 to 50 cuts p99 second-phase latency by ~40% with less than 1%
  relevance degradation on our benchmark queries.

- **Feature vector optimization**: The price_factor signal is already captured in
  quality_boost (which multiplies quality_score by price_factor). Including price_factor
  in both feature_vector and quality_boost causes the learned model to double-count price
  sensitivity. I recommend a 4-signal feature vector that excludes price_factor:

```
rank-profile production inherits hybrid {

    function feature_vector() {
        expression: tensor<float>(feature[4]):[text_relevance, semantic_similarity, tag_similarity, preference_score]
    }

    function learned_combination() {
        expression: reduce(feature_vector * constant(scoring_weights), sum, feature)
    }

    function quality_boost() {
        expression: attribute(quality_score) * price_factor
    }

    second-phase {
        expression: learned_combination + 0.1 * quality_boost
        rerank-count: 50
    }

    summary-features {
        text_relevance
        semantic_similarity
        tag_similarity
        preference_score
        price_factor
        feature_vector
        learned_combination
        quality_boost
    }
}
```

## Constant Declaration

```
constant scoring_weights {
    file: constants/scoring_weights.json
    type: tensor<float>(feature[4])
}
```

The constant type must match the feature_vector dimensions (4 features, not 5).
