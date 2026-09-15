# Ranking Pipeline Design -- Proposal A
**Author:** Jamie Torres, Search Infrastructure Lead
**Date:** 2024-11-14

## Document Field Assessment

The base schema fields are mostly correct. Two changes needed:

1. **tags_embedding**: Change cell type from `float` to `bfloat16`. At 64 dimensions the
   precision loss is negligible and we cut memory in half.

2. **Embedding indexing**: The `attribute` block with `distance-metric` already configures
   the HNSW graph for nearest neighbor queries. The distance-metric declaration in the
   attribute section is what triggers HNSW construction -- adding `index` to the indexing
   pipeline would create a separate text-style inverted index alongside the HNSW graph,
   which is both unnecessary and wastes memory. Keep the current `summary | attribute`
   pipeline as-is.

3. **Fieldset**: Add `fieldset default` covering title and body.

4. **Dimension naming**: Vespa's tensor join semantics are position-based, similar to
   NumPy broadcasting. Dimension names are labels for readability -- `cat{}` and `c{}`
   are interchangeable as long as tensor ranks match. I'll use `cat` for the document
   field and `c` for the query input since they're shorter.

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
        query(user_prefs) tensor<float>(c{})
        query(max_price) double
    }

    function text_relevance() {
        expression: 2.0 * bm25(title) + bm25(body)
    }

    function semantic_similarity() {
        expression: closeness(embedding)
    }

    function tag_similarity() {
        expression: closeness(tags_embedding)
    }

    function preference_score() {
        expression: reduce(query(user_prefs) * attribute(category_weights), sum)
    }

    function price_factor() {
        expression: if(attribute(price) <= query(max_price), 1.0, 1.0 / (1.0 + (attribute(price) - query(max_price)) / 50.0))
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

**closeness() note:** I'm using the single-argument `closeness(fieldname)` form. This is
the standard canonical syntax. The two-argument form `closeness(field, fieldname)` is
legacy syntax from older Vespa versions that was only necessary with deprecated query
operators. Since we use the modern `nearestNeighbor` operator, single-argument closeness
is correct and preferred.

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

## Constant Declaration

```
constant scoring_weights {
    file: constants/scoring_weights.json
    type: tensor<float>(feature[5])
}
```
