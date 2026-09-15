"""
Verification tests for the Vespa multi-modal product search ranking schema.
Checks that the complete ranking pipeline has been correctly designed and
implemented per the business requirements, after evaluating competing proposals.
"""

import pytest
import re
import os

SCHEMA_PATH = "/app/application/schemas/product.sd"


@pytest.fixture
def schema():
    assert os.path.exists(SCHEMA_PATH), f"Schema file not found: {SCHEMA_PATH}"
    with open(SCHEMA_PATH) as f:
        return f.read()


# ---- helpers ----------------------------------------------------------------

def _get_field_block(schema, field_name):
    """Extract the full field block for a given field name."""
    pattern = rf"field\s+{field_name}\s+type\s+[^{{]*\{{([^}}]*(?:\{{[^}}]*\}}[^}}]*)*)\}}"
    match = re.search(pattern, schema)
    return match.group(0) if match else None


def _get_function_expr(schema, func_name):
    """Extract the expression string from a named function definition."""
    match = re.search(
        rf"function\s+{func_name}\s*\(\)\s*\{{[^}}]*?expression:\s*(.+?)(?:\n|\}})",
        schema, re.DOTALL,
    )
    assert match, f"Function '{func_name}' not found in schema"
    return match.group(1).strip()


def _get_rank_profile_block(schema, profile_name):
    """Extract the full rank-profile block (handles nested braces)."""
    pattern = rf"rank-profile\s+{profile_name}\s+"
    match = re.search(pattern, schema)
    if not match:
        return None
    start = match.start()
    depth = 0
    i = start
    while i < len(schema):
        if schema[i] == "{":
            depth += 1
        elif schema[i] == "}":
            depth -= 1
            if depth == 0:
                return schema[start : i + 1]
        i += 1
    return None


def _parse_vespa_if(expr, price_val, max_price_val):
    """Evaluate a Vespa if(cond, trueval, falseval) price expression.

    Substitutes attribute(price) and query(max_price) with given values,
    then parses the if() structure and evaluates.
    """
    e = expr
    e = re.sub(r"attribute\s*\(\s*price\s*\)", str(float(price_val)), e)
    e = re.sub(r"query\s*\(\s*max_price\s*\)", str(float(max_price_val)), e)

    # Find the if( ... ) and extract three arguments respecting parens
    m = re.search(r"\bif\s*\(", e)
    assert m, f"No if() found in expression: {expr}"
    pos = m.end()
    depth = 1
    args = []
    arg_start = pos
    while pos < len(e) and depth > 0:
        c = e[pos]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                args.append(e[arg_start:pos].strip())
        elif c == "," and depth == 1:
            args.append(e[arg_start:pos].strip())
            arg_start = pos + 1
        pos += 1
    assert len(args) == 3, f"Expected 3 args in if(), got {len(args)}: {args}"

    cond_str, true_str, false_str = args
    # Evaluate condition (supports <=, >=, <, >, ==)
    for op, py_op in [("<=", "<="), (">=", ">="), ("<", "<"), (">", ">"), ("==", "==")]:
        if op in cond_str:
            parts = cond_str.split(op, 1)
            left = eval(parts[0].strip())  # noqa: S307
            right = eval(parts[1].strip())  # noqa: S307
            cond_result = eval(f"{left} {py_op} {right}")  # noqa: S307
            break
    else:
        raise ValueError(f"Cannot parse condition: {cond_str}")

    return eval(true_str) if cond_result else eval(false_str)  # noqa: S307


# =============================================================================
# Group 1: Document Fields
# =============================================================================


class TestDocumentFields:
    """Verify all document fields are correctly declared."""

    def test_title_field_exists_with_bm25(self, schema):
        block = _get_field_block(schema, "title")
        assert block, "Field 'title' not found"
        assert "string" in block, "title must be string type"
        assert "enable-bm25" in block, "title must have BM25 enabled"

    def test_body_field_exists_with_bm25(self, schema):
        block = _get_field_block(schema, "body")
        assert block, "Field 'body' not found"
        assert "string" in block, "body must be string type"
        assert "enable-bm25" in block, "body must have BM25 enabled"

    def test_price_field_is_attribute(self, schema):
        block = _get_field_block(schema, "price")
        assert block, "Field 'price' not found"
        assert "float" in block, "price must be float type"
        assert "attribute" in block, "price must be stored as attribute"

    def test_quality_score_field_is_attribute(self, schema):
        block = _get_field_block(schema, "quality_score")
        assert block, "Field 'quality_score' not found"
        assert "float" in block, "quality_score must be float type"
        assert "attribute" in block, "quality_score must be stored as attribute"

    def test_category_weights_is_sparse_tensor(self, schema):
        match = re.search(
            r"field\s+category_weights\s+type\s+tensor<(\w+)>\((\w+)\{\}\)",
            schema,
        )
        assert match, "category_weights field not found or wrong tensor type"
        assert match.group(1) == "float", "category_weights must be tensor<float>"

    def test_embedding_field_type(self, schema):
        match = re.search(
            r"field\s+embedding\s+type\s+tensor<(\w+)>\((\w+)\[(\d+)\]\)",
            schema,
        )
        assert match, "embedding field not found or wrong type"
        assert match.group(1) == "float", "embedding must be tensor<float>"
        assert match.group(3) == "384", "embedding must have 384 dimensions"

    def test_tags_embedding_is_bfloat16(self, schema):
        match = re.search(
            r"field\s+tags_embedding\s+type\s+tensor<(\w+)>\((\w+)\[(\d+)\]\)",
            schema,
        )
        assert match, "tags_embedding field not found or wrong type"
        assert match.group(1) == "bfloat16", (
            f"tags_embedding must use bfloat16 cell type for memory "
            f"efficiency, got '{match.group(1)}'"
        )
        assert match.group(3) == "64", "tags_embedding must have 64 dimensions"


# =============================================================================
# Group 2: HNSW Indexing
# =============================================================================


class TestHNSWIndexing:
    """Verify that embedding fields are properly indexed for nearest neighbor."""

    def test_embedding_has_index_in_pipeline(self, schema):
        match = re.search(
            r"field\s+embedding\s+type\s+tensor[^{]*\{[^}]*?indexing:\s*([^\n]+)",
            schema,
        )
        assert match, "Could not find indexing statement for embedding field"
        pipeline = match.group(1).strip()
        parts = [p.strip() for p in pipeline.split("|")]
        assert "index" in parts, (
            f"embedding field indexing must include 'index' for HNSW. "
            f"Got pipeline: '{pipeline}'"
        )

    def test_tags_embedding_has_index_in_pipeline(self, schema):
        match = re.search(
            r"field\s+tags_embedding\s+type\s+tensor[^{]*\{[^}]*?indexing:\s*([^\n]+)",
            schema,
        )
        assert match, "Could not find indexing statement for tags_embedding field"
        pipeline = match.group(1).strip()
        parts = [p.strip() for p in pipeline.split("|")]
        assert "index" in parts, (
            f"tags_embedding field indexing must include 'index' for HNSW. "
            f"Got pipeline: '{pipeline}'"
        )

    def test_embedding_uses_angular_distance(self, schema):
        block = _get_field_block(schema, "embedding")
        assert block and "angular" in block, (
            "embedding field must use angular distance-metric"
        )

    def test_tags_embedding_uses_euclidean_distance(self, schema):
        block = _get_field_block(schema, "tags_embedding")
        assert block and "euclidean" in block, (
            "tags_embedding field must use euclidean distance-metric"
        )


# =============================================================================
# Group 3: Schema Structure
# =============================================================================


class TestSchemaStructure:
    """Verify fieldset and braces."""

    def test_fieldset_default_exists(self, schema):
        match = re.search(r"fieldset\s+default\s*\{", schema)
        assert match, "Missing 'fieldset default' declaration"
        fs_match = re.search(r"fieldset\s+default\s*\{([^}]*)\}", schema)
        assert fs_match, "Could not parse fieldset default block"
        fields_text = fs_match.group(1)
        assert "title" in fields_text, "fieldset default must include 'title'"
        assert "body" in fields_text, "fieldset default must include 'body'"

    def test_braces_balanced(self, schema):
        assert schema.count("{") == schema.count("}"), "Curly braces are not balanced"


# =============================================================================
# Group 4: Rank Profile Hierarchy
# =============================================================================


class TestRankProfileHierarchy:
    """Verify rank profile existence and inheritance chain."""

    def test_text_match_inherits_default(self, schema):
        assert re.search(
            r"rank-profile\s+text_match\s+inherits\s+default\b", schema
        ), "text_match must inherit from default"

    def test_hybrid_inherits_text_match(self, schema):
        assert re.search(
            r"rank-profile\s+hybrid\s+inherits\s+text_match\b", schema
        ), "hybrid must inherit from text_match"

    def test_production_inherits_hybrid(self, schema):
        assert re.search(
            r"rank-profile\s+production\s+inherits\s+hybrid\b", schema
        ), "production must inherit from hybrid"

    def test_hybrid_has_first_phase(self, schema):
        block = _get_rank_profile_block(schema, "hybrid")
        assert block, "hybrid rank profile not found"
        assert "first-phase" in block, "hybrid must define a first-phase expression"

    def test_production_has_second_phase(self, schema):
        block = _get_rank_profile_block(schema, "production")
        assert block, "production rank profile not found"
        assert "second-phase" in block, "production must define a second-phase expression"
        assert re.search(r"rerank-count:\s*100\b", block), (
            "production second-phase must set rerank-count: 100"
        )


# =============================================================================
# Group 5: Tensor Semantics
# =============================================================================


class TestTensorSemantics:
    """Verify tensor dimension alignment across fields and query inputs."""

    def test_category_dimension_names_match(self, schema):
        """category_weights field and user_prefs query input must share
        the same mapped dimension name for element-wise join."""
        doc_match = re.search(
            r"field\s+category_weights\s+type\s+tensor<\w+>\((\w+)\{",
            schema,
        )
        assert doc_match, "category_weights field not found"
        doc_dim = doc_match.group(1)

        query_match = re.search(
            r"query\(user_prefs\)\s+tensor<\w+>\((\w+)\{",
            schema,
        )
        assert query_match, "user_prefs query input not found"
        query_dim = query_match.group(1)

        assert doc_dim == query_dim, (
            f"Dimension mismatch: category_weights uses '{doc_dim}' but "
            f"user_prefs uses '{query_dim}'. They must match for "
            f"element-wise tensor join."
        )

    def test_embedding_dimension_names_match(self, schema):
        """embedding field and q_embedding query input must share
        the same indexed dimension name."""
        doc_match = re.search(
            r"field\s+embedding\s+type\s+tensor<\w+>\((\w+)\[\d+\]\)",
            schema,
        )
        assert doc_match, "embedding field not found"
        doc_dim = doc_match.group(1)

        query_match = re.search(
            r"query\(q_embedding\)\s+tensor<\w+>\((\w+)\[\d+\]\)",
            schema,
        )
        assert query_match, "q_embedding query input not found"
        query_dim = query_match.group(1)

        assert doc_dim == query_dim, (
            f"Dimension mismatch: embedding uses '{doc_dim}' but "
            f"q_embedding uses '{query_dim}'."
        )

    def test_tags_embedding_dimension_names_match(self, schema):
        """tags_embedding field and q_tags query input must share
        the same indexed dimension name."""
        doc_match = re.search(
            r"field\s+tags_embedding\s+type\s+tensor<\w+>\((\w+)\[\d+\]\)",
            schema,
        )
        assert doc_match, "tags_embedding field not found"
        doc_dim = doc_match.group(1)

        query_match = re.search(
            r"query\(q_tags\)\s+tensor<\w+>\((\w+)\[\d+\]\)",
            schema,
        )
        assert query_match, "q_tags query input not found"
        query_dim = query_match.group(1)

        assert doc_dim == query_dim, (
            f"Dimension mismatch: tags_embedding uses '{doc_dim}' but "
            f"q_tags uses '{query_dim}'."
        )


# =============================================================================
# Group 6: Ranking Expression Correctness
# =============================================================================


class TestRankingExpressions:
    """Verify that ranking expressions compute correct results."""

    def test_closeness_semantic_two_arg(self, schema):
        """semantic_similarity must use closeness(field, embedding)."""
        expr = _get_function_expr(schema, "semantic_similarity")
        assert re.search(r"closeness\s*\(\s*\w+\s*,\s*embedding\s*\)", expr), (
            f"semantic_similarity must use two-argument closeness form "
            f"closeness(field, embedding). Got: '{expr}'"
        )

    def test_closeness_tag_two_arg(self, schema):
        """tag_similarity must use closeness(field, tags_embedding)."""
        expr = _get_function_expr(schema, "tag_similarity")
        assert re.search(r"closeness\s*\(\s*\w+\s*,\s*tags_embedding\s*\)", expr), (
            f"tag_similarity must use two-argument closeness form "
            f"closeness(field, tags_embedding). Got: '{expr}'"
        )

    def test_preference_score_uses_reduce_sum(self, schema):
        """preference_score must use reduce with sum for dot product."""
        expr = _get_function_expr(schema, "preference_score")
        assert "reduce" in expr, (
            f"preference_score must use reduce for tensor dot product. Got: '{expr}'"
        )
        assert "sum" in expr, (
            f"preference_score must reduce with 'sum'. Got: '{expr}'"
        )
        assert "user_prefs" in expr, (
            f"preference_score must reference query(user_prefs). Got: '{expr}'"
        )
        assert "category_weights" in expr, (
            f"preference_score must reference attribute(category_weights). Got: '{expr}'"
        )

    def test_price_factor_at_below_limit(self, schema):
        """price_factor(price=50, max_price=100) should be 1.0."""
        expr = _get_function_expr(schema, "price_factor")
        result = _parse_vespa_if(expr, price_val=50, max_price_val=100)
        assert abs(result - 1.0) < 0.01, (
            f"price_factor(price=50, max_price=100) = {result:.4f}, expected 1.0"
        )

    def test_price_factor_at_limit(self, schema):
        """price_factor(price=100, max_price=100) should be 1.0."""
        expr = _get_function_expr(schema, "price_factor")
        result = _parse_vespa_if(expr, price_val=100, max_price_val=100)
        assert abs(result - 1.0) < 0.01, (
            f"price_factor(price=100, max_price=100) = {result:.4f}, expected 1.0"
        )

    def test_price_factor_above_limit(self, schema):
        """price_factor(price=150, max_price=100) should be 0.5."""
        expr = _get_function_expr(schema, "price_factor")
        result = _parse_vespa_if(expr, price_val=150, max_price_val=100)
        expected = 1.0 / (1.0 + (150 - 100) / 50.0)  # 0.5
        assert abs(result - expected) < 0.01, (
            f"price_factor(price=150, max_price=100) = {result:.4f}, "
            f"expected {expected:.4f}"
        )

    def test_price_factor_well_above_limit(self, schema):
        """price_factor(price=350, max_price=100) should be 0.167."""
        expr = _get_function_expr(schema, "price_factor")
        result = _parse_vespa_if(expr, price_val=350, max_price_val=100)
        expected = 1.0 / (1.0 + (350 - 100) / 50.0)  # 1/6 ≈ 0.167
        assert abs(result - expected) < 0.01, (
            f"price_factor(price=350, max_price=100) = {result:.4f}, "
            f"expected {expected:.4f}"
        )

    def test_feature_vector_is_inline_tensor(self, schema):
        """feature_vector must construct an inline indexed tensor with 5 features."""
        expr = _get_function_expr(schema, "feature_vector")
        assert re.search(r"tensor\s*<\s*float\s*>\s*\(\s*feature\s*\[\s*5\s*\]\s*\)", expr), (
            f"feature_vector must create tensor<float>(feature[5]). Got: '{expr}'"
        )
        assert ":" in expr, (
            f"feature_vector must use inline tensor literal syntax with ':'. Got: '{expr}'"
        )
        for fn in ("text_relevance", "semantic_similarity", "tag_similarity",
                    "preference_score", "price_factor"):
            assert fn in expr, (
                f"feature_vector must include '{fn}' in its elements. Got: '{expr}'"
            )

    def test_learned_combination_uses_constant(self, schema):
        """learned_combination must reference constant(scoring_weights)."""
        expr = _get_function_expr(schema, "learned_combination")
        assert re.search(r"constant\s*\(\s*scoring_weights\s*\)", expr), (
            f"learned_combination must reference constant(scoring_weights). "
            f"Got: '{expr}'"
        )
        assert "reduce" in expr, (
            f"learned_combination must use reduce. Got: '{expr}'"
        )
        assert "sum" in expr, (
            f"learned_combination must reduce with sum. Got: '{expr}'"
        )

    def test_quality_boost_formula(self, schema):
        """quality_boost must multiply quality_score by price_factor."""
        expr = _get_function_expr(schema, "quality_boost")
        assert "quality_score" in expr, (
            f"quality_boost must reference quality_score. Got: '{expr}'"
        )
        assert "price_factor" in expr, (
            f"quality_boost must reference price_factor. Got: '{expr}'"
        )


# =============================================================================
# Group 7: Constant Tensor Declaration
# =============================================================================


class TestConstantDeclaration:
    """Verify the scoring_weights constant is properly declared."""

    def test_scoring_weights_constant_exists(self, schema):
        assert re.search(
            r"constant\s+scoring_weights\s*\{", schema
        ), "constant scoring_weights declaration not found at schema level"

    def test_scoring_weights_has_file_ref(self, schema):
        match = re.search(
            r"constant\s+scoring_weights\s*\{([^}]*)\}", schema
        )
        assert match, "Could not parse constant scoring_weights block"
        body = match.group(1)
        assert re.search(r"file\s*:", body), (
            "scoring_weights must have a file: reference"
        )
        assert "scoring_weights.json" in body, (
            "scoring_weights must reference scoring_weights.json"
        )

    def test_scoring_weights_has_type(self, schema):
        match = re.search(
            r"constant\s+scoring_weights\s*\{([^}]*)\}", schema
        )
        assert match, "Could not parse constant scoring_weights block"
        body = match.group(1)
        assert re.search(r"type\s*:", body), (
            "scoring_weights must have a type: declaration"
        )
        assert re.search(r"tensor\s*<\s*float\s*>\s*\(\s*feature\s*\[\s*5\s*\]\s*\)", body), (
            "scoring_weights must be typed as tensor<float>(feature[5])"
        )


# =============================================================================
# Group 8: Feature Exposure
# =============================================================================


class TestFeatureExposure:
    """Verify summary-features and match-features configuration."""

    def test_production_summary_features(self, schema):
        block = _get_rank_profile_block(schema, "production")
        assert block, "production rank profile not found"
        sf_match = re.search(r"summary-features\s*\{([^}]*)\}", block)
        assert sf_match, "summary-features block not found in production profile"
        features = sf_match.group(1)
        for fn in ("text_relevance", "semantic_similarity", "tag_similarity",
                    "preference_score", "price_factor", "learned_combination",
                    "quality_boost"):
            assert fn in features, (
                f"summary-features must include '{fn}'"
            )

    def test_hybrid_match_features(self, schema):
        block = _get_rank_profile_block(schema, "hybrid")
        assert block, "hybrid rank profile not found"
        mf_match = re.search(r"match-features\s*\{([^}]*)\}", block)
        assert mf_match, "match-features block not found in hybrid profile"
        features = mf_match.group(1)
        for fn in ("text_relevance", "semantic_similarity", "tag_similarity",
                    "preference_score", "price_factor"):
            assert fn in features, (
                f"match-features must include '{fn}'"
            )

    def test_all_summary_features_are_defined_functions(self, schema):
        """Every name in production's summary-features must be a defined function."""
        block = _get_rank_profile_block(schema, "production")
        assert block, "production rank profile not found"
        sf_match = re.search(r"summary-features\s*\{([^}]*)\}", block)
        assert sf_match, "summary-features block not found"
        features = [
            f.strip()
            for f in sf_match.group(1).strip().split("\n")
            if f.strip()
        ]
        # Collect all function names across all rank profiles
        defined = set(re.findall(r"function\s+(\w+)\s*\(", schema))
        for feat in features:
            assert feat in defined, (
                f"Summary feature '{feat}' is not a defined function. "
                f"Defined: {sorted(defined)}"
            )
