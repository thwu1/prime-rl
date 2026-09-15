# Ranking Pipeline Design -- Proposal B
**Author:** Morgan Chen, ML Platform Engineer
**Date:** 2024-11-15

## Document Field Assessment

Several issues need correction:

1. **HNSW indexing**: The current pipeline `summary | attribute` is insufficient for ANN
   queries. The `distance-metric` declaration only configures *how* distance is computed,
   not *whether* an HNSW graph is built. You MUST add `| index` to the indexing pipeline
   for both embedding fields to trigger HNSW graph construction. Without this, nearest
   neighbor queries will fall back to exact (brute-force) search or fail silently.

2. **tags_embedding precision**: Keep the current `float` cell type. While bfloat16 saves
   memory, it introduces quantization noise that degrades recall by 3-5% on our 64-dim
   tag vectors. The memory savings are minimal at 64 dimensions (only ~128 bytes per doc),
   so the precision tradeoff is not worth it.

3. **tags_embedding distance metric**: Change from `euclidean` to `angular`. Tag vectors
   represent semantic categories where direction matters more than magnitude. Angular
   distance normalizes for vector length, giving more stable similarity scores across
   tags with different frequency distributions.

4. **Dimension naming**: Vespa tensor joins match dimensions **by name**, not by position.
   The document field `category_weights` must use the same dimension name as the query
   input `user_prefs`. If they differ, Vespa produces an outer product instead of an
   element-wise product, yielding a tensor result instead of a scalar. Rename the
   document dimension from `cat` to `category` and use `category` for the query input.

5. **Fieldset**: Add `fieldset default` for title and body.

## closeness() Syntax

With multiple embedding fields in a schema, the single-argument `closeness(fieldname)`
form is ambiguous -- Vespa cannot determine which field's nearest neighbor computation
to use. You must use the two-argument form `closeness(field, fieldname)` to explicitly
identify the target field. This is not legacy syntax; it is the required form for
multi-field schemas.

## Rank Profiles

### text_match

```
rank-profile text_match inherits default {
    first-phase {
        expression: 2.0 * bm25(title) + bm25(body)
    }
}
```

### hybrid

```
rank-profile hybrid inherits text_match {
    inputs {
        query(q_embedding) tensor<float>(v[384])
        query(q_tags) tensor<float>(v[64])
        query(user_prefs) tensor<float>(category{})
        query(max_price) double
    }

    function text_relevance() {
        expression: 2.0 * bm25(title) + bm25(body)
    }

    function semantic_similarity() {
        expression: closeness(field, embedding)
    }

    function tag_similarity() {
        expression: closeness(field, tags_embedding)
    }

    function preference_score() {
        expression: reduce(query(user_prefs) * attribute(category_weights), sum)
    }

    function price_factor() {
        expression: if(attribute(price) <= query(max_price), 1.0, 1 / 1 + (attribute(price) - query(max_price)) / 50.0)
    }

    first-phase {
        expression: text_relevance + 0.4 * semantic_similarity + 0.15 * tag_similarity + 0.25 * preference_score
    }

    match-features {
        text_relevance
        semantic_similarity
        tag_similarity
        preference_score
        price_factor
    }
}
```

### production

```
rank-profile production inherits hybrid {

    function feature_vector() {
        expression: tensor<float>(feature[5]):[text_relevance, semantic_similarity, tag_similarity, preference_score, price_factor]
    }

    function learned_combination() {
        expression: reduce(feature_vector * constant(scoring_weights), sum, feature)
    }

    function quality_boost() {
        expression: attribute(quality_score) * price_factor
    }

    second-phase {
        expression: learned_combination + 0.1 * quality_boost
        rerank-count: 100
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

## Constant

```
constant scoring_weights {
    file: constants/scoring_weights.json
    type: tensor<float>(feature[5])
}
```
