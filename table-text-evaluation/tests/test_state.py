"""Tests for table-text relatedness evaluation pipeline.

"""
import sys
import os
import json
import csv
import math

import pytest

sys.path.insert(0, "/app")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Module API existence
# ═══════════════════════════════════════════════════════════════════════════════
class TestPipelineModule:
    def test_module_importable(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("pipeline", "/app/pipeline.py")
        assert spec is not None, "/app/pipeline.py not found"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        required = [
            "load_data",
            "serialize_table",
            "compute_precision_at_k",
            "compute_recall_at_k",
            "compute_f1_at_k",
            "compute_ndcg_at_k",
            "compute_reciprocal_rank",
            "compute_average_precision",
            "reciprocal_rank_fusion",
            "create_grouped_folds",
            "compute_bm25_scores",
            "optimize_rrf_weights",
        ]
        for name in required:
            assert hasattr(module, name), f"Missing function: {name}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Precision@k
# ═══════════════════════════════════════════════════════════════════════════════
class TestPrecisionAtK:
    def test_basic(self):
        from pipeline import compute_precision_at_k

        rel = [1, 0, 1, 0, 1, 0]
        assert abs(compute_precision_at_k(rel, 1) - 1.0) < 1e-6
        assert abs(compute_precision_at_k(rel, 3) - 2 / 3) < 1e-6
        assert abs(compute_precision_at_k(rel, 5) - 3 / 5) < 1e-6
        assert abs(compute_precision_at_k(rel, 6) - 3 / 6) < 1e-6

    def test_all_relevant(self):
        from pipeline import compute_precision_at_k

        assert abs(compute_precision_at_k([1, 1, 1], 3) - 1.0) < 1e-6

    def test_none_relevant(self):
        from pipeline import compute_precision_at_k

        assert abs(compute_precision_at_k([0, 0, 0], 3) - 0.0) < 1e-6

    def test_k_exceeds_length(self):
        from pipeline import compute_precision_at_k

        # k=5 but only 3 items -> missing positions are irrelevant -> P@5 = 2/5
        assert abs(compute_precision_at_k([1, 0, 1], 5) - 2 / 5) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Recall@k
# ═══════════════════════════════════════════════════════════════════════════════
class TestRecallAtK:
    def test_basic(self):
        from pipeline import compute_recall_at_k

        rel = [1, 0, 1, 0, 1, 0]
        assert abs(compute_recall_at_k(rel, 1, 3) - 1 / 3) < 1e-6
        assert abs(compute_recall_at_k(rel, 3, 3) - 2 / 3) < 1e-6
        assert abs(compute_recall_at_k(rel, 5, 3) - 1.0) < 1e-6
        assert abs(compute_recall_at_k(rel, 6, 3) - 1.0) < 1e-6

    def test_zero_relevant(self):
        from pipeline import compute_recall_at_k

        assert compute_recall_at_k([0, 0, 0], 3, 0) == 0.0

    def test_k_exceeds_length(self):
        from pipeline import compute_recall_at_k

        # Only found 2 out of 3 relevant within the returned results
        assert abs(compute_recall_at_k([1, 0, 1], 5, 3) - 2 / 3) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 4. F1@k
# ═══════════════════════════════════════════════════════════════════════════════
class TestF1AtK:
    def test_basic(self):
        from pipeline import compute_f1_at_k

        rel = [1, 0, 1, 0, 1, 0]
        # F1@1: P=1, R=1/3 -> F1 = 2*(1*1/3)/(1+1/3) = (2/3)/(4/3) = 0.5
        assert abs(compute_f1_at_k(rel, 1, 3) - 0.5) < 1e-6
        # F1@3: P=2/3, R=2/3 -> F1 = 2/3
        assert abs(compute_f1_at_k(rel, 3, 3) - 2 / 3) < 1e-6
        # F1@5: P=3/5, R=1 -> F1 = 2*(3/5*1)/(3/5+1) = (6/5)/(8/5) = 0.75
        assert abs(compute_f1_at_k(rel, 5, 3) - 0.75) < 1e-6

    def test_zero_both(self):
        from pipeline import compute_f1_at_k

        assert compute_f1_at_k([0, 0, 0], 3, 0) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. NDCG@k
# ═══════════════════════════════════════════════════════════════════════════════
class TestNDCGAtK:
    def test_at_k3(self):
        from pipeline import compute_ndcg_at_k

        rel = [1, 0, 1, 0, 1, 0]
        # DCG@3 = 1/log2(2) + 0/log2(3) + 1/log2(4) = 1.0 + 0 + 0.5 = 1.5
        # IDCG@3 = 1/log2(2) + 1/log2(3) + 1/log2(4) = 1.0 + 0.63093 + 0.5 = 2.13093
        expected = 1.5 / (1.0 + 1.0 / math.log2(3) + 0.5)
        assert abs(compute_ndcg_at_k(rel, 3, 3) - expected) < 1e-4

    def test_at_k5(self):
        from pipeline import compute_ndcg_at_k

        rel = [1, 0, 1, 0, 1, 0]
        dcg5 = 1.0 + 0.5 + 1.0 / math.log2(6)
        idcg3 = 1.0 + 1.0 / math.log2(3) + 0.5
        expected = dcg5 / idcg3
        assert abs(compute_ndcg_at_k(rel, 5, 3) - expected) < 1e-4

    def test_perfect_ranking(self):
        from pipeline import compute_ndcg_at_k

        # All relevant items at top -> NDCG = 1.0
        assert abs(compute_ndcg_at_k([1, 1, 1, 0, 0, 0], 3, 3) - 1.0) < 1e-6

    def test_zero_relevant(self):
        from pipeline import compute_ndcg_at_k

        assert compute_ndcg_at_k([0, 0, 0], 3, 0) == 0.0

    def test_single_relevant(self):
        from pipeline import compute_ndcg_at_k

        # Single relevant item at position 3 (index 2)
        # DCG@3 = 0 + 0 + 1/log2(4) = 0.5
        # IDCG@3 = 1/log2(2) = 1.0 (only 1 relevant, so IDCG uses min(3,1)=1 position)
        assert abs(compute_ndcg_at_k([0, 0, 1], 3, 1) - 0.5 / 1.0) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Reciprocal Rank (for MRR)
# ═══════════════════════════════════════════════════════════════════════════════
class TestReciprocalRank:
    def test_first_position(self):
        from pipeline import compute_reciprocal_rank

        assert abs(compute_reciprocal_rank([1, 0, 0]) - 1.0) < 1e-6

    def test_third_position(self):
        from pipeline import compute_reciprocal_rank

        assert abs(compute_reciprocal_rank([0, 0, 1, 0]) - 1 / 3) < 1e-6

    def test_fourth_position(self):
        from pipeline import compute_reciprocal_rank

        assert abs(compute_reciprocal_rank([0, 0, 0, 1]) - 1 / 4) < 1e-6

    def test_no_relevant(self):
        from pipeline import compute_reciprocal_rank

        assert compute_reciprocal_rank([0, 0, 0, 0]) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Average Precision
# ═══════════════════════════════════════════════════════════════════════════════
class TestAveragePrecision:
    def test_perfect(self):
        from pipeline import compute_average_precision

        # All relevant at top: AP = (1/1 + 2/2 + 3/3) / 3 = 1.0
        assert abs(compute_average_precision([1, 1, 1, 0, 0]) - 1.0) < 1e-6

    def test_basic(self):
        from pipeline import compute_average_precision

        # [1, 0, 1, 0, 1]: 3 relevant
        # AP = (1/1 + 2/3 + 3/5) / 3
        expected = (1.0 + 2.0 / 3 + 3.0 / 5) / 3
        assert abs(compute_average_precision([1, 0, 1, 0, 1]) - expected) < 1e-6

    def test_worst_ranking(self):
        from pipeline import compute_average_precision

        # All relevant at bottom: [0, 0, 1, 1, 1]
        # AP = (1/3 + 2/4 + 3/5) / 3
        expected = (1.0 / 3 + 2.0 / 4 + 3.0 / 5) / 3
        assert abs(compute_average_precision([0, 0, 1, 1, 1]) - expected) < 1e-6

    def test_no_relevant(self):
        from pipeline import compute_average_precision

        assert compute_average_precision([0, 0, 0]) == 0.0

    def test_single_relevant_top(self):
        from pipeline import compute_average_precision

        # [1, 0, 0]: AP = (1/1) / 1 = 1.0
        assert abs(compute_average_precision([1, 0, 0]) - 1.0) < 1e-6

    def test_single_relevant_bottom(self):
        from pipeline import compute_average_precision

        # [0, 0, 1]: AP = (1/3) / 1 = 1/3
        assert abs(compute_average_precision([0, 0, 1]) - 1.0 / 3) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Reciprocal Rank Fusion (standard)
# ═══════════════════════════════════════════════════════════════════════════════
class TestRRF:
    def test_exact_scores(self):
        from pipeline import reciprocal_rank_fusion

        rankings = {
            "ranker_a": ["d1", "d2", "d3", "d4"],
            "ranker_b": ["d3", "d1", "d4", "d2"],
        }
        result = reciprocal_rank_fusion(rankings, k_rrf=60)
        # d1: 1/(60+1) + 1/(60+2) = 1/61 + 1/62
        assert abs(result["d1"] - (1 / 61 + 1 / 62)) < 1e-10
        # d3: 1/(60+3) + 1/(60+1) = 1/63 + 1/61
        assert abs(result["d3"] - (1 / 63 + 1 / 61)) < 1e-10
        # d2: 1/(60+2) + 1/(60+4) = 1/62 + 1/64
        assert abs(result["d2"] - (1 / 62 + 1 / 64)) < 1e-10
        # d4: 1/(60+4) + 1/(60+3) = 1/64 + 1/63
        assert abs(result["d4"] - (1 / 64 + 1 / 63)) < 1e-10

    def test_ranking_order(self):
        from pipeline import reciprocal_rank_fusion

        rankings = {
            "ranker_a": ["d1", "d2", "d3", "d4"],
            "ranker_b": ["d3", "d1", "d4", "d2"],
        }
        result = reciprocal_rank_fusion(rankings, k_rrf=60)
        # d1 > d3 > d2 > d4
        assert result["d1"] > result["d3"]
        assert result["d3"] > result["d2"]
        assert result["d2"] > result["d4"]

    def test_single_ranker(self):
        from pipeline import reciprocal_rank_fusion

        rankings = {"only": ["a", "b", "c"]}
        result = reciprocal_rank_fusion(rankings, k_rrf=60)
        assert result["a"] > result["b"] > result["c"]


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Weighted Reciprocal Rank Fusion
# ═══════════════════════════════════════════════════════════════════════════════
class TestWeightedRRF:
    def test_uniform_matches_standard(self):
        from pipeline import reciprocal_rank_fusion

        rankings = {
            "a": ["d1", "d2", "d3"],
            "b": ["d3", "d1", "d2"],
        }
        uniform = reciprocal_rank_fusion(rankings, k_rrf=60, weights={"a": 1.0, "b": 1.0})
        standard = reciprocal_rank_fusion(rankings, k_rrf=60)
        for d in ["d1", "d2", "d3"]:
            assert abs(uniform[d] - standard[d]) < 1e-10

    def test_weight_effect(self):
        from pipeline import reciprocal_rank_fusion

        rankings = {
            "a": ["d1", "d2"],
            "b": ["d2", "d1"],
        }
        # Heavy weight on a -> d1 wins (ranked first by a)
        result_a = reciprocal_rank_fusion(rankings, k_rrf=60, weights={"a": 10.0, "b": 1.0})
        assert result_a["d1"] > result_a["d2"]

        # Heavy weight on b -> d2 wins (ranked first by b)
        result_b = reciprocal_rank_fusion(rankings, k_rrf=60, weights={"a": 1.0, "b": 10.0})
        assert result_b["d2"] > result_b["d1"]

    def test_zero_weight(self):
        from pipeline import reciprocal_rank_fusion

        rankings = {
            "a": ["d1", "d2"],
            "b": ["d2", "d1"],
        }
        result = reciprocal_rank_fusion(rankings, k_rrf=60, weights={"a": 1.0, "b": 0.0})
        # Only method a contributes
        assert abs(result["d1"] - 1 / (60 + 1)) < 1e-10
        assert abs(result["d2"] - 1 / (60 + 2)) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Table serialization
# ═══════════════════════════════════════════════════════════════════════════════
class TestTableSerialization:
    def test_preserves_content(self):
        from pipeline import serialize_table

        table = {
            "id": "test123",
            "title": "Test Table",
            "header": ["Name", "Value", "Category"],
            "rows": [["Alice", "100", "A"], ["Bob", "200", "B"]],
        }
        result = serialize_table(table)
        assert isinstance(result, str)
        for expected in ["Test Table", "Alice", "Bob", "100", "200", "Name", "Value", "Category"]:
            assert expected in result, f"'{expected}' not found in serialized table"

    def test_empty_table(self):
        from pipeline import serialize_table

        table = {"id": "empty", "title": "", "header": [], "rows": []}
        result = serialize_table(table)
        assert isinstance(result, str)

    def test_returns_string(self):
        from pipeline import serialize_table

        table = {
            "id": "x",
            "title": "T",
            "header": ["H"],
            "rows": [["v"]],
        }
        assert isinstance(serialize_table(table), str)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Grouped fold creation
# ═══════════════════════════════════════════════════════════════════════════════
class TestGroupedFolds:
    def test_no_leakage(self):
        import pandas as pd
        from pipeline import create_grouped_folds

        pairs = pd.DataFrame(
            {
                "text_id": ["t1", "t1", "t2", "t2", "t3", "t3", "t4", "t4", "t5", "t5",
                            "t6", "t6", "t7", "t7", "t8", "t8", "t9", "t9", "t10", "t10"],
                "table_id": [f"a{i}" for i in range(20)],
                "label": [1, 0] * 10,
            }
        )
        folds = create_grouped_folds(pairs, n_folds=5)
        assert len(folds) == 5
        for train_idx, val_idx in folds:
            train_tids = set(pairs.iloc[train_idx]["text_id"])
            val_tids = set(pairs.iloc[val_idx]["text_id"])
            overlap = train_tids & val_tids
            assert len(overlap) == 0, f"Data leakage: text_ids {overlap} in both train and val"

    def test_all_indices_covered(self):
        import pandas as pd
        from pipeline import create_grouped_folds

        pairs = pd.DataFrame(
            {
                "text_id": ["t1", "t1", "t2", "t2", "t3", "t3", "t4", "t4", "t5", "t5"],
                "table_id": [f"a{i}" for i in range(10)],
                "label": [1, 0] * 5,
            }
        )
        folds = create_grouped_folds(pairs, n_folds=5)
        all_val = []
        for _, val_idx in folds:
            all_val.extend(val_idx)
        assert sorted(all_val) == list(range(10)), "Not all indices appear in validation across folds"

    def test_deterministic(self):
        import pandas as pd
        from pipeline import create_grouped_folds

        pairs = pd.DataFrame(
            {
                "text_id": ["t1", "t2", "t3", "t4", "t5"],
                "table_id": ["a1", "a2", "a3", "a4", "a5"],
                "label": [1, 0, 1, 0, 1],
            }
        )
        folds1 = create_grouped_folds(pairs, n_folds=5)
        folds2 = create_grouped_folds(pairs, n_folds=5)
        for (t1, v1), (t2, v2) in zip(folds1, folds2):
            assert t1 == t2 and v1 == v2, "create_grouped_folds is not deterministic"

    def test_sorted_round_robin(self):
        """Verify fold assignment follows sorted text_id round-robin order."""
        import pandas as pd
        from pipeline import create_grouped_folds

        # text_ids appear in non-sorted order: t5, t3, t1, t4, t2
        pairs = pd.DataFrame(
            {
                "text_id": ["t5", "t5", "t3", "t3", "t1", "t1", "t4", "t4", "t2", "t2"],
                "table_id": [f"x{i}" for i in range(10)],
                "label": [1, 0] * 5,
            }
        )
        folds = create_grouped_folds(pairs, n_folds=5)

        # Sorted text_ids: t1, t2, t3, t4, t5
        # Round-robin: t1->fold0, t2->fold1, t3->fold2, t4->fold3, t5->fold4
        expected = {"t1": 0, "t2": 1, "t3": 2, "t4": 3, "t5": 4}

        for fold_idx, (train_idx, val_idx) in enumerate(folds):
            val_tids = set(pairs.iloc[val_idx]["text_id"])
            expected_tids = {tid for tid, f in expected.items() if f == fold_idx}
            assert val_tids == expected_tids, \
                f"Fold {fold_idx}: expected text_ids {expected_tids}, got {val_tids}"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. BM25 scoring
# ═══════════════════════════════════════════════════════════════════════════════
class TestBM25:
    def test_positive_overlap(self):
        """Matching terms produce positive score."""
        import pandas as pd
        from pipeline import compute_bm25_scores

        tables_ser = {"t1": "alpha beta gamma"}
        texts_dict = {"q1": {"text_id": "q1", "text": "alpha beta", "url": ""}}
        tables_dict = {"t1": {"id": "t1"}}
        pairs = pd.DataFrame({"text_id": ["q1"], "table_id": ["t1"], "label": [1]})
        scores = compute_bm25_scores(tables_ser, pairs, texts_dict, tables_dict)
        assert scores[("q1", "t1")] > 0

    def test_zero_overlap(self):
        """No shared terms produce zero score."""
        import pandas as pd
        from pipeline import compute_bm25_scores

        tables_ser = {"t1": "alpha beta gamma"}
        texts_dict = {"q1": {"text_id": "q1", "text": "delta epsilon", "url": ""}}
        tables_dict = {"t1": {"id": "t1"}}
        pairs = pd.DataFrame({"text_id": ["q1"], "table_id": ["t1"], "label": [1]})
        scores = compute_bm25_scores(tables_ser, pairs, texts_dict, tables_dict)
        assert scores[("q1", "t1")] == 0.0

    def test_robertson_idf(self):
        """Robertson IDF: term in all docs still contributes positive score.

        Naive IDF log(N/n) gives 0 when n=N, but Robertson IDF
        log((N-n+0.5)/(n+0.5)+1) is always positive.
        """
        import pandas as pd
        from pipeline import compute_bm25_scores

        # "common" appears in all 2 docs
        tables_ser = {"t1": "common rare_a", "t2": "common rare_b"}
        texts_dict = {"q1": {"text_id": "q1", "text": "common", "url": ""}}
        tables_dict = {"t1": {"id": "t1"}, "t2": {"id": "t2"}}
        pairs = pd.DataFrame({"text_id": ["q1"], "table_id": ["t1"], "label": [1]})
        scores = compute_bm25_scores(tables_ser, pairs, texts_dict, tables_dict)
        # With Robertson IDF: log((2-2+0.5)/(2+0.5)+1) = log(1.2) > 0
        # With naive IDF: log(2/2) = 0 -> BM25 = 0 (WRONG)
        assert scores[("q1", "t1")] > 0

    def test_ordering(self):
        """Doc with more matching terms scores higher."""
        import pandas as pd
        from pipeline import compute_bm25_scores

        tables_ser = {"t1": "alpha beta gamma delta", "t2": "alpha epsilon zeta"}
        texts_dict = {"q1": {"text_id": "q1", "text": "alpha beta gamma", "url": ""}}
        tables_dict = {"t1": {"id": "t1"}, "t2": {"id": "t2"}}
        pairs = pd.DataFrame({
            "text_id": ["q1", "q1"], "table_id": ["t1", "t2"], "label": [1, 0]
        })
        scores = compute_bm25_scores(tables_ser, pairs, texts_dict, tables_dict)
        assert scores[("q1", "t1")] > scores[("q1", "t2")]


# ═══════════════════════════════════════════════════════════════════════════════
# 13. optimize_rrf_weights
# ═══════════════════════════════════════════════════════════════════════════════
class TestOptimizeWeights:
    def test_returns_dict(self):
        import pandas as pd
        from pipeline import optimize_rrf_weights

        method_scores = {
            "method_a": {
                ("t1", "d1"): 0.8, ("t1", "d2"): 0.2,
                ("t2", "d1"): 0.3, ("t2", "d2"): 0.9,
            },
            "method_b": {
                ("t1", "d1"): 0.5, ("t1", "d2"): 0.6,
                ("t2", "d1"): 0.7, ("t2", "d2"): 0.4,
            },
        }
        pairs_df = pd.DataFrame({
            "text_id": ["t1", "t1", "t2", "t2"],
            "table_id": ["d1", "d2", "d1", "d2"],
            "label": [1, 0, 0, 1],
        })
        folds = [([0, 1], [2, 3]), ([2, 3], [0, 1])]

        result = optimize_rrf_weights(method_scores, pairs_df, folds)

        assert isinstance(result, dict)
        assert set(result.keys()) == {"method_a", "method_b"}
        assert all(isinstance(v, (int, float)) for v in result.values())
        assert all(v >= 0 for v in result.values())
        assert any(v > 0 for v in result.values())

    def test_finds_better_weights(self):
        """When one method is clearly better, it should be weighted higher."""
        import pandas as pd
        from pipeline import optimize_rrf_weights

        # method_a perfectly predicts relevance (high score for relevant items)
        # method_b is anti-correlated (high score for non-relevant items)
        method_scores = {
            "method_a": {
                ("t1", "d1"): 1.0, ("t1", "d2"): 0.0, ("t1", "d3"): 0.0, ("t1", "d4"): 0.0,
                ("t2", "d5"): 1.0, ("t2", "d6"): 0.0, ("t2", "d7"): 0.0, ("t2", "d8"): 0.0,
                ("t3", "d9"): 1.0, ("t3", "d10"): 0.0, ("t3", "d11"): 0.0, ("t3", "d12"): 0.0,
                ("t4", "d13"): 1.0, ("t4", "d14"): 0.0, ("t4", "d15"): 0.0, ("t4", "d16"): 0.0,
            },
            "method_b": {
                ("t1", "d1"): 0.0, ("t1", "d2"): 1.0, ("t1", "d3"): 0.5, ("t1", "d4"): 0.3,
                ("t2", "d5"): 0.0, ("t2", "d6"): 1.0, ("t2", "d7"): 0.5, ("t2", "d8"): 0.3,
                ("t3", "d9"): 0.0, ("t3", "d10"): 1.0, ("t3", "d11"): 0.5, ("t3", "d12"): 0.3,
                ("t4", "d13"): 0.0, ("t4", "d14"): 1.0, ("t4", "d15"): 0.5, ("t4", "d16"): 0.3,
            },
        }
        pairs_df = pd.DataFrame({
            "text_id": ["t1"] * 4 + ["t2"] * 4 + ["t3"] * 4 + ["t4"] * 4,
            "table_id": [f"d{i}" for i in range(1, 17)],
            "label": [1, 0, 0, 0] * 4,
        })
        folds = [
            (list(range(0, 8)), list(range(8, 16))),
            (list(range(8, 16)), list(range(0, 8))),
        ]

        result = optimize_rrf_weights(method_scores, pairs_df, folds, k_eval=1)
        assert result["method_a"] >= result["method_b"]


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Output file format: metrics.json
# ═══════════════════════════════════════════════════════════════════════════════
class TestOutputMetrics:
    def test_file_exists(self):
        assert os.path.exists("/app/output/metrics.json"), "metrics.json not found"

    def test_required_keys(self):
        with open("/app/output/metrics.json") as f:
            metrics = json.load(f)
        required = [
            "p_at_5", "r_at_5", "f1_at_5", "ndcg_at_5",
            "p_at_10", "r_at_10", "f1_at_10", "ndcg_at_10",
            "p_at_20", "r_at_20", "f1_at_20", "ndcg_at_20",
            "mrr", "map", "best_threshold",
        ]
        for key in required:
            assert key in metrics, f"Missing key in metrics.json: {key}"
            assert isinstance(metrics[key], (int, float)), f"{key} should be numeric, got {type(metrics[key])}"

    def test_metrics_in_valid_range(self):
        with open("/app/output/metrics.json") as f:
            metrics = json.load(f)
        for key in ["p_at_5", "r_at_5", "f1_at_5", "ndcg_at_5",
                     "p_at_10", "r_at_10", "f1_at_10", "ndcg_at_10",
                     "p_at_20", "r_at_20", "f1_at_20", "ndcg_at_20",
                     "mrr", "map"]:
            assert 0 <= metrics[key] <= 1, f"{key}={metrics[key]} not in [0,1]"


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Output file format: predictions.csv
# ═══════════════════════════════════════════════════════════════════════════════
class TestOutputPredictions:
    def test_file_exists(self):
        assert os.path.exists("/app/output/predictions.csv"), "predictions.csv not found"

    def test_columns(self):
        with open("/app/output/predictions.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) > 0, "predictions.csv is empty"
        assert "text_id" in rows[0], "Missing column: text_id"
        assert "table_id" in rows[0], "Missing column: table_id"
        assert "score" in rows[0], "Missing column: score"


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Output file format: config.json
# ═══════════════════════════════════════════════════════════════════════════════
class TestOutputConfig:
    def test_file_exists(self):
        assert os.path.exists("/app/output/config.json"), "config.json not found"

    def test_required_keys(self):
        with open("/app/output/config.json") as f:
            config = json.load(f)
        for key in ["methods", "weights", "threshold", "n_folds", "k_values"]:
            assert key in config, f"Missing key in config.json: {key}"
        assert isinstance(config["methods"], list)
        assert isinstance(config["weights"], dict)
        assert isinstance(config["threshold"], (int, float))
        assert isinstance(config["n_folds"], int)
        assert isinstance(config["k_values"], list)

    def test_includes_bm25(self):
        with open("/app/output/config.json") as f:
            config = json.load(f)
        assert "bm25" in config["methods"], "config.json methods should include bm25"


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Output file format: comparison.json
# ═══════════════════════════════════════════════════════════════════════════════
class TestComparisonOutput:
    def test_file_exists(self):
        assert os.path.exists("/app/output/comparison.json"), "comparison.json not found"

    def test_structure(self):
        with open("/app/output/comparison.json") as f:
            data = json.load(f)
        for section in ["uniform", "optimized"]:
            assert section in data, f"Missing section: {section}"
            assert "weights" in data[section], f"Missing weights in {section}"
            assert "metrics" in data[section], f"Missing metrics in {section}"
            assert isinstance(data[section]["weights"], dict)
            assert isinstance(data[section]["metrics"], dict)
            for metric in ["f1_at_10", "map", "ndcg_at_10"]:
                assert metric in data[section]["metrics"], \
                    f"Missing {metric} in {section}.metrics"
                val = data[section]["metrics"][metric]
                assert isinstance(val, (int, float))
                assert 0 <= val <= 1, f"{section}.metrics.{metric}={val} not in [0,1]"

    def test_uniform_weights_equal(self):
        """Uniform weights should all be 1.0."""
        with open("/app/output/comparison.json") as f:
            data = json.load(f)
        for w in data["uniform"]["weights"].values():
            assert abs(w - 1.0) < 1e-6

    def test_methods_present(self):
        """All 4 methods should be in weights."""
        with open("/app/output/comparison.json") as f:
            data = json.load(f)
        expected_methods = {"url_matching", "entity_overlap", "tfidf_cosine", "bm25"}
        assert set(data["uniform"]["weights"].keys()) == expected_methods
        assert set(data["optimized"]["weights"].keys()) == expected_methods


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Predictions coverage and score range
# ═══════════════════════════════════════════════════════════════════════════════
class TestPredictionsCoverage:
    def test_all_pairs_covered(self):
        with open("/app/data/pairs.csv") as f:
            expected = set()
            for row in csv.DictReader(f):
                expected.add((row["text_id"], row["table_id"]))
        with open("/app/output/predictions.csv") as f:
            actual = set()
            for row in csv.DictReader(f):
                actual.add((row["text_id"], row["table_id"]))
        missing = expected - actual
        assert len(missing) == 0, f"Missing {len(missing)} pairs in predictions.csv"

    def test_scores_in_range(self):
        with open("/app/output/predictions.csv") as f:
            for row in csv.DictReader(f):
                score = float(row["score"])
                assert 0 <= score <= 1, f"Score {score} out of [0,1] range for pair ({row['text_id']}, {row['table_id']})"


# ═══════════════════════════════════════════════════════════════════════════════
# 19. Macro averaging correctness
# ═══════════════════════════════════════════════════════════════════════════════
class TestMacroAveraging:
    def test_macro_precision(self):
        from pipeline import compute_precision_at_k

        # Two queries with same P@3 = 2/3
        q1 = [1, 0, 1, 0, 1, 0]  # P@3 = 2/3
        q2 = [1, 1, 0, 0]  # P@3 = 2/3
        macro = (compute_precision_at_k(q1, 3) + compute_precision_at_k(q2, 3)) / 2
        assert abs(macro - 2 / 3) < 1e-6

    def test_macro_recall_differs(self):
        from pipeline import compute_recall_at_k

        # Two queries with different R@3
        q1 = [1, 0, 1, 0, 1, 0]  # R@3 = 2/3 (3 relevant total)
        q2 = [1, 1, 0, 0]  # R@3 = 2/2 = 1.0 (2 relevant total)
        macro = (compute_recall_at_k(q1, 3, 3) + compute_recall_at_k(q2, 3, 2)) / 2
        assert abs(macro - 5 / 6) < 1e-6

    def test_macro_f1(self):
        from pipeline import compute_f1_at_k

        q1 = [1, 0, 1, 0, 1, 0]  # F1@3: P=2/3, R=2/3 -> F1=2/3
        q2 = [1, 1, 0, 0]  # F1@3: P=2/3, R=1.0 -> F1=2*(2/3)/(5/3) = 4/5
        f1_q1 = compute_f1_at_k(q1, 3, 3)
        f1_q2 = compute_f1_at_k(q2, 3, 2)
        macro = (f1_q1 + f1_q2) / 2
        expected = (2 / 3 + 4 / 5) / 2  # = (10/15 + 12/15)/2 = 22/30 = 11/15
        assert abs(macro - expected) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 20. Data loading contract
# ═══════════════════════════════════════════════════════════════════════════════
class TestLoadDataContract:
    def test_returns_correct_types(self):
        from pipeline import load_data
        import pandas as pd

        tables, texts, pairs = load_data("/app/data")
        assert isinstance(tables, dict), "tables_by_id should be a dict"
        assert isinstance(texts, dict), "texts_by_id should be a dict"
        assert isinstance(pairs, pd.DataFrame), "pairs_df should be a DataFrame"

    def test_pairs_has_correct_columns(self):
        from pipeline import load_data

        _, _, pairs = load_data("/app/data")
        assert "text_id" in pairs.columns, "pairs_df missing 'text_id' column"
        assert "table_id" in pairs.columns, "pairs_df missing 'table_id' column"
        assert "label" in pairs.columns, "pairs_df missing 'label' column"

    def test_label_is_integer(self):
        from pipeline import load_data

        _, _, pairs = load_data("/app/data")
        assert pairs["label"].dtype in ("int64", "int32", "int"), \
            f"label column should be integer, got {pairs['label'].dtype}"
