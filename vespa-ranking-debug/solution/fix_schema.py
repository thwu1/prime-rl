#!/usr/bin/env python3
"""
Fix all bugs in the Vespa product search schema.

The schema at /app/application/schemas/product.sd has 5 bugs in its ranking
pipeline that prevent correct operation.  This script identifies and fixes
each one by applying targeted text replacements.

Bugs fixed:
  1. embedding field missing '| index' in indexing pipeline (HNSW won't build)
  2. query(user_cats) tensor dimension 'c{}' doesn't match document field's
     'category{}' dimension (join produces outer product instead of dot product)
  3. closeness(embedding) should be closeness(field, embedding) for field-based
     similarity computation
  4. price_adjustment has operator-precedence bug: '1 / 1 + ...' evaluates as
     (1/1) + ... instead of 1 / (1 + ...)
  5. summary-features references 'price_adjustement' (typo) instead of
     'price_adjustment'
"""

import re
import sys

SCHEMA_PATH = "/app/application/schemas/product.sd"


def main():
    with open(SCHEMA_PATH) as f:
        schema = f.read()

    original = schema

    # -----------------------------------------------------------------------
    # Bug 1: embedding field needs 'index' in indexing pipeline for HNSW.
    # The field has 'attribute { distance-metric: angular }' which implies
    # it should support nearestNeighbor queries, but without '| index' in
    # the indexing statement HNSW is never built.
    # -----------------------------------------------------------------------
    schema = schema.replace(
        "indexing: summary | attribute\n            attribute {\n                distance-metric:",
        "indexing: summary | attribute | index\n            attribute {\n                distance-metric:",
    )

    # -----------------------------------------------------------------------
    # Bug 2: tensor dimension name mismatch.
    # The document field category_scores uses dimension 'category{}' but the
    # query input user_cats declares dimension 'c{}'.  Vespa's tensor join
    # matches cells by dimension name, so mismatched names produce an outer
    # product (rank-2 tensor) instead of an element-wise product.
    # -----------------------------------------------------------------------
    schema = schema.replace(
        "tensor<float>(c{})",
        "tensor<float>(category{})",
    )

    # -----------------------------------------------------------------------
    # Bug 3: closeness rank feature needs field-specific two-argument form.
    # closeness(embedding) is ambiguous; closeness(field, embedding)
    # explicitly binds to the document field used by nearestNeighbor.
    # -----------------------------------------------------------------------
    schema = schema.replace(
        "closeness(embedding)",
        "closeness(field, embedding)",
    )

    # -----------------------------------------------------------------------
    # Bug 4: operator precedence in price_adjustment.
    # '1 / 1 + attribute(price) / 100' evaluates as:
    #   (1/1) + (attribute(price)/100) = 1 + price/100
    # Correct form: '1 / (1 + attribute(price) / 100)'
    # -----------------------------------------------------------------------
    schema = schema.replace(
        "1 / 1 + attribute(price) / 100",
        "1 / (1 + attribute(price) / 100)",
    )

    # -----------------------------------------------------------------------
    # Bug 5: typo in summary-features — 'adjustement' vs 'adjustment'.
    # Vespa resolves summary-feature names to defined functions; a misspelled
    # name causes a deployment error.
    # -----------------------------------------------------------------------
    schema = schema.replace(
        "price_adjustement",
        "price_adjustment",
    )

    if schema == original:
        print("WARNING: no changes made — schema may already be fixed", file=sys.stderr)
    else:
        with open(SCHEMA_PATH, "w") as f:
            f.write(schema)
        print(f"Fixed schema written to {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
