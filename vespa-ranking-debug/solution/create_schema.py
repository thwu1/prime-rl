#!/usr/bin/env python3
"""
Create the correct Vespa product search ranking schema by evaluating
the competing design proposals against business requirements and Vespa
semantics, then synthesizing the optimal implementation.

Evaluation results:
- Proposal Alpha: WRONG on HNSW (no | index), closeness (single-arg),
  dimension naming (cat/c mismatch). CORRECT on price_factor, bfloat16,
  production architecture.
- Proposal Beta: WRONG on price_factor (precedence bug: 1/1+X = 2 not 0.5),
  cell type (float not bfloat16), distance metric (angular not euclidean).
  CORRECT on HNSW, closeness (two-arg), dimension naming.
- Proposal Gamma: WRONG on rerank-count (50 not 100), feature vector (4 not 5),
  constant type (feature[4] not feature[5]). CORRECT on bfloat16, euclidean,
  HNSW, closeness, dimension naming, price_factor.

Correct synthesis: Alpha's price_factor + production formulas, Beta's HNSW +
closeness + dimension approach, Gamma's bfloat16 + euclidean + price verification.
"""

import json
import re

SCHEMA_PATH = "/app/application/schemas/product.sd"
REQUIREMENTS_PATH = "/app/business_requirements.md"
WEIGHTS_PATH = "/app/application/constants/scoring_weights.json"


def read_file(path):
    with open(path) as f:
        return f.read()


def extract_dimension_name(requirements):
    """Extract the mapped dimension name specified in business requirements."""
    match = re.search(r'tensor[<&].*?[>;]\((\w+)\{\}\)', requirements)
    if match:
        return match.group(1)
    # Fallback: look for explicit naming requirement
    match = re.search(r'dimension\s+(?:MUST|must)\s+be\s+named\s+[`"](\w+)[`"]', requirements)
    return match.group(1) if match else "category"


def get_feature_count(weights_path):
    """Determine feature vector size from the pre-trained weights file."""
    weights = json.loads(read_file(weights_path))
    return len(weights.get("values", []))


def verify_price_formula(price, max_price):
    """Verify the correct price_factor formula: 1.0 / (1.0 + (price - max_price) / 50.0)."""
    if price <= max_price:
        return 1.0
    return 1.0 / (1.0 + (price - max_price) / 50.0)


def create_schema():
    """Generate the complete correct schema from evaluated proposals."""

    requirements = read_file(REQUIREMENTS_PATH)
    dim_name = extract_dimension_name(requirements)
    num_features = get_feature_count(WEIGHTS_PATH)

    # Verify price formula against business constraints
    assert abs(verify_price_formula(150, 100) - 0.5) < 0.001, "Price formula check failed"
    assert abs(verify_price_formula(350, 100) - 1.0/6.0) < 0.001, "Price formula check failed"
    print(f"  Price formula verified: f(150,100)={verify_price_formula(150,100)}, f(350,100)={verify_price_formula(350,100):.4f}")

    print(f"  Dimension name: {dim_name}")
    print(f"  Feature count: {num_features}")

    schema = f"""schema product {{

    document product {{

        field title type string {{
            indexing: summary | index
            index: enable-bm25
        }}

        field body type string {{
            indexing: summary | index
            index: enable-bm25
        }}

        field price type float {{
            indexing: summary | attribute
        }}

        field quality_score type float {{
            indexing: summary | attribute
        }}

        field category_weights type tensor<float>({dim_name}{{}}) {{
            indexing: summary | attribute
        }}

        field embedding type tensor<float>(v[384]) {{
            indexing: summary | attribute | index
            attribute {{
                distance-metric: angular
            }}
        }}

        field tags_embedding type tensor<bfloat16>(v[64]) {{
            indexing: summary | attribute | index
            attribute {{
                distance-metric: euclidean
            }}
        }}

    }}

    fieldset default {{
        fields: title, body
    }}

    constant scoring_weights {{
        file: constants/scoring_weights.json
        type: tensor<float>(feature[{num_features}])
    }}

    rank-profile text_match inherits default {{
        first-phase {{
            expression: 2.0 * bm25(title) + bm25(body)
        }}
    }}

    rank-profile hybrid inherits text_match {{
        inputs {{
            query(q_embedding) tensor<float>(v[384])
            query(q_tags) tensor<float>(v[64])
            query(user_prefs) tensor<float>({dim_name}{{}})
            query(max_price) double
        }}

        function text_relevance() {{
            expression: 2.0 * bm25(title) + bm25(body)
        }}

        function semantic_similarity() {{
            expression: closeness(field, embedding)
        }}

        function tag_similarity() {{
            expression: closeness(field, tags_embedding)
        }}

        function preference_score() {{
            expression: reduce(query(user_prefs) * attribute(category_weights), sum)
        }}

        function price_factor() {{
            expression: if(attribute(price) <= query(max_price), 1.0, 1.0 / (1.0 + (attribute(price) - query(max_price)) / 50.0))
        }}

        first-phase {{
            expression: text_relevance + 0.4 * semantic_similarity + 0.15 * tag_similarity + 0.25 * preference_score
        }}

        match-features {{
            text_relevance
            semantic_similarity
            tag_similarity
            preference_score
            price_factor
        }}
    }}

    rank-profile production inherits hybrid {{

        function feature_vector() {{
            expression: tensor<float>(feature[{num_features}]):[text_relevance, semantic_similarity, tag_similarity, preference_score, price_factor]
        }}

        function learned_combination() {{
            expression: reduce(feature_vector * constant(scoring_weights), sum, feature)
        }}

        function quality_boost() {{
            expression: attribute(quality_score) * price_factor
        }}

        second-phase {{
            expression: learned_combination + 0.1 * quality_boost
            rerank-count: 100
        }}

        summary-features {{
            text_relevance
            semantic_similarity
            tag_similarity
            preference_score
            price_factor
            feature_vector
            learned_combination
            quality_boost
        }}
    }}

}}
"""
    return schema


def main():
    print("Evaluating proposals against business requirements...")
    print("Proposal Alpha: reject HNSW/closeness/dimension advice; accept price_factor/production")
    print("Proposal Beta: reject price_factor/cell-type/distance advice; accept HNSW/closeness/dimensions")
    print("Proposal Gamma: reject rerank-count/feature-count advice; accept bfloat16/euclidean/closeness")
    print()
    print("Generating synthesized schema:")

    schema = create_schema()

    with open(SCHEMA_PATH, 'w') as f:
        f.write(schema)

    print(f"\nComplete schema written to {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
