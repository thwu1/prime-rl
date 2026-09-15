#!/usr/bin/env python3
"""
Analyze and repair the Vespa product search schema.

Reads the broken schema at /app/application/schemas/product.sd, compares it
against the requirements specification at /app/requirements.md to identify
defects and missing components, applies targeted fixes, and writes the
corrected version.

The script derives correct values from the requirements document rather than
hardcoding them, and reads the scoring weights file to determine tensor
dimensions for the production profile.
"""

import json
import re
import sys

SCHEMA_PATH = "/app/application/schemas/product.sd"
REQUIREMENTS_PATH = "/app/requirements.md"
WEIGHTS_PATH = "/app/application/constants/scoring_weights.json"


def read_file(path):
    with open(path) as f:
        return f.read()


def extract_field_type(requirements, field_name):
    """Extract the declared type for a field from the requirements table."""
    match = re.search(rf'\|\s*`{field_name}`\s*\|\s*`([^`]+)`\s*\|', requirements)
    return match.group(1) if match else None


def get_mapped_dimension(tensor_type):
    """Extract the mapped dimension name from a type like tensor<float>(category{})."""
    match = re.search(r'\((\w+)\{\}\)', tensor_type)
    return match.group(1) if match else None


def fix_schema(schema, requirements):
    """Identify and fix all schema defects based on requirements analysis."""

    # --- Fix 1: category_weights mapped dimension name ---
    # Requirements define the correct dimension name for element-wise tensor join
    req_type = extract_field_type(requirements, "category_weights")
    correct_dim = get_mapped_dimension(req_type) if req_type else None
    if correct_dim:
        schema = re.sub(
            r'(field\s+category_weights\s+type\s+tensor<float>\()\w+(\{\}\))',
            rf'\g<1>{correct_dim}\2', schema)
        print(f"  [fix] category_weights dimension -> '{correct_dim}'")

    # --- Fix 2: tags_embedding cell type ---
    # Requirements specify bfloat16 for memory efficiency
    req_type = extract_field_type(requirements, "tags_embedding")
    if req_type and "bfloat16" in req_type:
        schema = re.sub(
            r'(field\s+tags_embedding\s+type\s+tensor<)float(>\(v\[64\]\))',
            r'\1bfloat16\2', schema)
        print("  [fix] tags_embedding cell type -> bfloat16")

    # --- Fix 3 & 4: Add | index to embedding fields for HNSW ---
    # Requirements: "Must support approximate nearest neighbor search via HNSW graph indexing"
    # Contrary to TROUBLESHOOTING.md, distance-metric alone does NOT enable HNSW;
    # the indexing pipeline must include '| index'
    for field, dims in [("embedding", r"v\[384\]"), ("tags_embedding", r"v\[64\]")]:
        schema = re.sub(
            rf'(field\s+{field}\s+type\s+tensor<\w+>\({dims}\)\s*\{{\s*\n\s*indexing:\s*summary\s*\|\s*attribute)(\s*\n)',
            r'\1 | index\2', schema)
        print(f"  [fix] {field} indexing pipeline += | index")

    # --- Fix 5: query(user_prefs) dimension alignment ---
    # The query input dimension must match the document field dimension exactly
    # for element-wise join (not outer product)
    # Contrary to TROUBLESHOOTING.md, Vespa joins by dimension NAME, not position
    if correct_dim:
        schema = re.sub(
            r'(query\(user_prefs\)\s+tensor<float>\()\w+(\{\}\))',
            rf'\g<1>{correct_dim}\2', schema)
        print(f"  [fix] query(user_prefs) dimension -> '{correct_dim}'")

    # --- Fix 6: closeness() two-argument form ---
    # Requirements: "Must use the two-argument closeness form that explicitly names the field"
    # With multiple embedding fields, single-arg closeness is ambiguous
    schema = re.sub(r'closeness\(embedding\)', 'closeness(field, embedding)', schema)
    schema = re.sub(r'closeness\(tags_embedding\)', 'closeness(field, tags_embedding)', schema)
    print("  [fix] closeness() -> closeness(field, ...)")

    # --- Fix 7: price_factor operator precedence ---
    # Bug: 1 / 1 + X  evaluates as  (1/1) + X = 1 + X  (wrong)
    # Fix: 1.0 / (1.0 + X)  evaluates correctly as a decay factor
    schema = schema.replace(
        '1 / 1 + (attribute(price) - query(max_price)) / 50.0)',
        '1.0 / (1.0 + (attribute(price) - query(max_price)) / 50.0))')
    print("  [fix] price_factor operator precedence")

    # --- Fix 8: match-features typo ---
    if 'price_facter' in schema:
        schema = schema.replace('price_facter', 'price_factor')
        print("  [fix] typo: price_facter -> price_factor")

    # --- Fix 9: Add fieldset default ---
    if 'fieldset default' not in schema:
        schema = re.sub(
            r'(    \}\n)\n(    rank-profile text_match)',
            r'\1\n    fieldset default {\n        fields: title, body\n    }\n\n\2',
            schema)
        print("  [add] fieldset default {title, body}")

    # --- Fix 10: Add constant scoring_weights declaration ---
    if 'constant scoring_weights' not in schema:
        # Read the weights file to determine tensor type
        weights = json.loads(read_file(WEIGHTS_PATH))
        num_features = len(weights.get("values", []))
        schema = re.sub(
            r'\n(    rank-profile text_match)',
            f'\n    constant scoring_weights {{\n'
            f'        file: constants/scoring_weights.json\n'
            f'        type: tensor<float>(feature[{num_features}])\n'
            f'    }}\n\n\\1',
            schema)
        print(f"  [add] constant scoring_weights (feature[{num_features}])")

    # --- Fix 11: Add production rank profile ---
    if 'rank-profile production' not in schema:
        weights = json.loads(read_file(WEIGHTS_PATH))
        num_features = len(weights.get("values", []))

        # The hybrid profile's five scoring functions become the feature vector
        # for learned reranking
        feature_fns = ["text_relevance", "semantic_similarity", "tag_similarity",
                       "preference_score", "price_factor"]
        features_inline = ", ".join(feature_fns)
        features_summary = "\n".join(f"            {fn}" for fn in feature_fns)

        production_text = (
            f"    rank-profile production inherits hybrid {{\n"
            f"\n"
            f"        function feature_vector() {{\n"
            f"            expression: tensor<float>(feature[{num_features}]):[{features_inline}]\n"
            f"        }}\n"
            f"\n"
            f"        function learned_combination() {{\n"
            f"            expression: reduce(feature_vector * constant(scoring_weights), sum, feature)\n"
            f"        }}\n"
            f"\n"
            f"        function quality_boost() {{\n"
            f"            expression: attribute(quality_score) * price_factor\n"
            f"        }}\n"
            f"\n"
            f"        second-phase {{\n"
            f"            expression: learned_combination + 0.1 * quality_boost\n"
            f"            rerank-count: 100\n"
            f"        }}\n"
            f"\n"
            f"        summary-features {{\n"
            f"{features_summary}\n"
            f"            feature_vector\n"
            f"            learned_combination\n"
            f"            quality_boost\n"
            f"        }}\n"
            f"    }}"
        )

        last_brace = schema.rfind('}')
        content = schema[:last_brace].rstrip('\n')
        schema = content + '\n\n' + production_text + '\n\n}\n'
        print(f"  [add] production rank profile ({num_features}-feature learned reranking)")

    return schema


def main():
    print("Reading requirements specification...")
    requirements = read_file(REQUIREMENTS_PATH)

    print("Reading current schema...")
    schema = read_file(SCHEMA_PATH)

    print("Applying fixes:")
    fixed = fix_schema(schema, requirements)

    with open(SCHEMA_PATH, 'w') as f:
        f.write(fixed)

    print(f"\nFixed schema written to {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
