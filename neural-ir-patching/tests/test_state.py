
"""Tests for the Neural IR Activation Patching Analysis Framework."""

import sys
import os
import json
import math

sys.path.insert(0, "/app")

import torch
import pytest


# ============================================================
# Test data fixtures
# ============================================================

PRED_1 = torch.tensor([[3.0, 1.0, 2.0, 0.5]])
LABELS_1 = torch.tensor([[3.0, 1.0, 2.0, 0.0]])

PRED_2 = torch.tensor([[1.5, 2.5, 0.5, 3.5], [2.0, 1.0, 3.0, 0.0]])
LABELS_2 = torch.tensor([[1.0, 3.0, 0.0, 2.0], [2.0, 1.0, 3.0, 0.0]])

ATOL = 1e-3


# ============================================================
# Loss function tests
# ============================================================


class TestApproxNDCG:
    def test_single_batch(self):
        from framework.losses import ApproxNDCGLoss

        loss_fn = ApproxNDCGLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_1, LABELS_1)
        assert abs(result.item() - 0.1825973988) < ATOL, f"Expected ~0.1826, got {result.item()}"

    def test_multi_batch(self):
        from framework.losses import ApproxNDCGLoss

        loss_fn = ApproxNDCGLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_2, LABELS_2)
        assert abs(result.item() - 0.2067274451) < ATOL, f"Expected ~0.2067, got {result.item()}"


class TestApproxMRR:
    def test_single_batch(self):
        from framework.losses import ApproxMRRLoss

        loss_fn = ApproxMRRLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_1, LABELS_1)
        assert abs(result.item() - 0.3169410229) < ATOL, f"Expected ~0.3169, got {result.item()}"

    def test_multi_batch(self):
        from framework.losses import ApproxMRRLoss

        loss_fn = ApproxMRRLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_2, LABELS_2)
        assert abs(result.item() - 0.3034126759) < ATOL, f"Expected ~0.3034, got {result.item()}"


class TestListNet:
    def test_single_batch(self):
        from framework.losses import ListNetLoss

        loss_fn = ListNetLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_1, LABELS_1)
        assert abs(result.item() - 0.9520914529) < ATOL, f"Expected ~0.9521, got {result.item()}"

    def test_multi_batch(self):
        from framework.losses import ListNetLoss

        loss_fn = ListNetLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_2, LABELS_2)
        assert abs(result.item() - 1.1510526849) < ATOL, f"Expected ~1.1511, got {result.item()}"


class TestRankNet:
    def test_single_batch(self):
        from framework.losses import RankNetLoss

        loss_fn = RankNetLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_1, LABELS_1)
        assert abs(result.item() - 0.2513052304) < ATOL, f"Expected ~0.2513, got {result.item()}"

    def test_multi_batch(self):
        from framework.losses import RankNetLoss

        loss_fn = RankNetLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_2, LABELS_2)
        assert abs(result.item() - 0.2903714060) < ATOL, f"Expected ~0.2904, got {result.item()}"


class TestKLDivergence:
    def test_single_batch(self):
        from framework.losses import KLDivergenceLoss

        loss_fn = KLDivergenceLoss(temperature=1.0, reduction="batchmean")
        result = loss_fn(PRED_1, LABELS_1)
        assert abs(result.item() - 0.0045544890) < ATOL, f"Expected ~0.0046, got {result.item()}"

    def test_multi_batch(self):
        from framework.losses import KLDivergenceLoss

        loss_fn = KLDivergenceLoss(temperature=1.0, reduction="batchmean")
        result = loss_fn(PRED_2, LABELS_2)
        assert abs(result.item() - 0.2035157209) < ATOL, f"Expected ~0.2035, got {result.item()}"


class TestMarginMSE:
    def test_single_batch(self):
        from framework.losses import MarginMSELoss

        loss_fn = MarginMSELoss(reduction="mean")
        result = loss_fn(PRED_1, LABELS_1)
        assert abs(result.item() - 0.0833333333) < ATOL, f"Expected ~0.0833, got {result.item()}"

    def test_multi_batch(self):
        from framework.losses import MarginMSELoss

        loss_fn = MarginMSELoss(reduction="mean")
        result = loss_fn(PRED_2, LABELS_2)
        assert abs(result.item() - 0.3333333333) < ATOL, f"Expected ~0.3333, got {result.item()}"


class TestContrastive:
    def test_single_batch(self):
        from framework.losses import ContrastiveLoss

        loss_fn = ContrastiveLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_1, LABELS_1)
        assert abs(result.item() - 0.4607734892) < ATOL, f"Expected ~0.4608, got {result.item()}"

    def test_multi_batch(self):
        from framework.losses import ContrastiveLoss

        loss_fn = ContrastiveLoss(temperature=1.0, reduction="mean")
        result = loss_fn(PRED_2, LABELS_2)
        assert abs(result.item() - 0.9401896986) < ATOL, f"Expected ~0.9402, got {result.item()}"


class TestLossRegistration:
    def test_all_registered(self):
        from framework.base import LOSS_REGISTRY

        # Import losses module to trigger registration
        import framework.losses  # noqa: F401

        expected_keys = [
            "approx_ndcg",
            "approx_mrr",
            "listnet",
            "ranknet",
            "kl_div",
            "margin_mse",
            "contrastive",
        ]
        for key in expected_keys:
            assert key in LOSS_REGISTRY, f"Loss '{key}' not found in registry"


# ============================================================
# Patching metric tests
# ============================================================


class TestPatchingMetrics:
    def test_linear_rank_function_scalar(self):
        from framework.patching import linear_rank_function

        # patching fully restores clean -> effect = 0
        result = linear_rank_function(0.85, 0.85, 0.35)
        assert abs(result - 0.0) < 1e-6

        # patching has no effect -> effect = 1
        result = linear_rank_function(0.35, 0.85, 0.35)
        assert abs(result - 1.0) < 1e-6

        # partial restoration
        result = linear_rank_function(0.60, 0.85, 0.35)
        expected = (0.60 - 0.85) / (0.35 - 0.85)  # 0.5
        assert abs(result - expected) < 1e-6

    def test_compute_patching_effects(self):
        from framework.patching import compute_patching_effects

        scores = [[0.5, 0.7], [0.3, 0.9]]
        clean = 0.8523
        corrupted = 0.3147

        effects = compute_patching_effects(scores, clean, corrupted)

        # Verify shape
        assert len(effects) == 2
        assert len(effects[0]) == 2

        # Verify values
        expected_00 = (0.5 - 0.8523) / (0.3147 - 0.8523)
        expected_11 = (0.9 - 0.8523) / (0.3147 - 0.8523)
        assert abs(effects[0][0] - expected_00) < 1e-6
        assert abs(effects[1][1] - expected_11) < 1e-6

    def test_identify_top_k_critical(self):
        from framework.patching import identify_top_k_critical

        # 2D effects: smallest absolute value = most critical
        effects = [[0.5, -0.01, 0.8], [0.02, 0.9, -0.03]]
        top3 = identify_top_k_critical(effects, k=3)
        # Expected order by |effect|: (0,1)=0.01, (1,0)=0.02, (1,2)=0.03
        assert top3[0] == (0, 1)
        assert top3[1] == (1, 0)
        assert top3[2] == (1, 2)

    def test_identify_top_k_critical_3d(self):
        from framework.patching import identify_top_k_critical

        effects = [[[0.5, 0.001], [-0.9, 0.3]], [[0.002, -0.8], [0.7, 0.003]]]
        top3 = identify_top_k_critical(effects, k=3)
        assert top3[0] == (0, 0, 1)  # 0.001
        assert top3[1] == (1, 0, 0)  # 0.002
        assert top3[2] == (1, 1, 1)  # 0.003


# ============================================================
# Evaluation metrics tests
# ============================================================


class TestNDCGAtK:
    def test_imperfect_ranking(self):
        from framework.metrics import RankingMetrics

        # pred=[3.0, 1.0, 2.0, 0.5], labels=[0, 3, 1, 2]
        # Sorted by pred desc: [0, 2, 1, 3] -> labels [0, 1, 3, 2]
        preds = [3.0, 1.0, 2.0, 0.5]
        labels = [0, 3, 1, 2]
        result = RankingMetrics.ndcg_at_k(preds, labels, 3)
        assert abs(result - 0.4397979811) < ATOL, f"Expected ~0.4398, got {result}"

    def test_perfect_ranking(self):
        from framework.metrics import RankingMetrics

        preds = [4.0, 3.0, 2.0, 1.0]
        labels = [3, 2, 1, 0]
        result = RankingMetrics.ndcg_at_k(preds, labels, 3)
        assert abs(result - 1.0) < ATOL, f"Expected 1.0, got {result}"

    def test_all_irrelevant(self):
        from framework.metrics import RankingMetrics

        preds = [3.0, 2.0, 1.0]
        labels = [0, 0, 0]
        result = RankingMetrics.ndcg_at_k(preds, labels, 3)
        assert abs(result - 0.0) < ATOL, f"Expected 0.0, got {result}"

    def test_k_larger_than_list(self):
        from framework.metrics import RankingMetrics

        preds = [2.0, 1.0]
        labels = [1, 3]
        result_k10 = RankingMetrics.ndcg_at_k(preds, labels, 10)
        result_k2 = RankingMetrics.ndcg_at_k(preds, labels, 2)
        assert abs(result_k10 - result_k2) < ATOL


class TestAveragePrecisionAtK:
    def test_imperfect_ranking(self):
        from framework.metrics import RankingMetrics

        # pred=[3.0, 1.0, 2.0, 0.5], labels=[0, 3, 1, 2]
        # Sorted labels: [0, 1, 3, 2]. R=3, k=3
        # rank 1: irrel, rank 2: rel (prec=1/2), rank 3: rel (prec=2/3)
        # AP@3 = (0.5 + 0.6667) / min(3,3) = 1.1667/3
        preds = [3.0, 1.0, 2.0, 0.5]
        labels = [0, 3, 1, 2]
        result = RankingMetrics.average_precision_at_k(preds, labels, 3)
        assert abs(result - 0.3888888889) < ATOL, f"Expected ~0.3889, got {result}"

    def test_perfect_ranking(self):
        from framework.metrics import RankingMetrics

        preds = [4.0, 3.0, 2.0, 1.0]
        labels = [3, 2, 1, 0]
        result = RankingMetrics.average_precision_at_k(preds, labels, 3)
        assert abs(result - 1.0) < ATOL, f"Expected 1.0, got {result}"

    def test_all_irrelevant(self):
        from framework.metrics import RankingMetrics

        preds = [3.0, 2.0, 1.0]
        labels = [0, 0, 0]
        result = RankingMetrics.average_precision_at_k(preds, labels, 3)
        assert abs(result - 0.0) < ATOL, f"Expected 0.0, got {result}"

    def test_k_cutoff(self):
        from framework.metrics import RankingMetrics

        # pred=[3.0, 1.0, 2.0, 0.5], labels=[0, 3, 1, 2]
        # Sorted labels: [0, 1, 3, 2]. k=2: rank 1 irrel, rank 2 rel (prec=0.5)
        # R=3, AP@2 = 0.5/min(3,2) = 0.25
        preds = [3.0, 1.0, 2.0, 0.5]
        labels = [0, 3, 1, 2]
        result = RankingMetrics.average_precision_at_k(preds, labels, 2)
        assert abs(result - 0.25) < ATOL, f"Expected 0.25, got {result}"


class TestReciprocalRank:
    def test_first_position(self):
        from framework.metrics import RankingMetrics

        preds = [3.0, 1.0, 2.0]
        labels = [1, 0, 0]
        result = RankingMetrics.reciprocal_rank(preds, labels)
        assert abs(result - 1.0) < ATOL

    def test_second_position(self):
        from framework.metrics import RankingMetrics

        # pred=[3.0, 1.0, 2.0, 0.5], labels=[0, 3, 1, 2]
        # Sorted: labels [0, 1, 3, 2]. First rel at rank 2 -> RR=0.5
        preds = [3.0, 1.0, 2.0, 0.5]
        labels = [0, 3, 1, 2]
        result = RankingMetrics.reciprocal_rank(preds, labels)
        assert abs(result - 0.5) < ATOL

    def test_no_relevant(self):
        from framework.metrics import RankingMetrics

        preds = [3.0, 2.0, 1.0]
        labels = [0, 0, 0]
        result = RankingMetrics.reciprocal_rank(preds, labels)
        assert abs(result - 0.0) < ATOL


class TestEvaluateQueries:
    def test_multi_query(self):
        from framework.metrics import RankingMetrics

        queries = [
            {"predictions": [4.0, 3.0, 2.0, 1.0], "labels": [3, 2, 1, 0]},
            {"predictions": [3.0, 1.0, 2.0, 0.5], "labels": [0, 3, 1, 2]},
        ]
        result = RankingMetrics.evaluate_queries(queries, k=3)
        assert "ndcg" in result
        assert "map" in result
        assert "mrr" in result
        # First query: perfect, second: imperfect
        expected_ndcg = (1.0 + 0.4397979811) / 2
        expected_map = (1.0 + 0.3888888889) / 2
        expected_mrr = (1.0 + 0.5) / 2
        assert abs(result["ndcg"] - expected_ndcg) < ATOL
        assert abs(result["map"] - expected_map) < ATOL
        assert abs(result["mrr"] - expected_mrr) < ATOL


# ============================================================
# Report tests
# ============================================================


class TestReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        report_path = "/app/output/report.json"
        assert os.path.exists(report_path), f"Report not found at {report_path}"
        with open(report_path) as f:
            self.report = json.load(f)

    def test_report_structure(self):
        assert "patching_analysis" in self.report
        assert "loss_evaluation" in self.report
        assert "evaluation_metrics" in self.report
        assert "block" in self.report["patching_analysis"]
        assert "head" in self.report["patching_analysis"]
        assert "top_5_critical" in self.report["patching_analysis"]["block"]
        assert "component_importance" in self.report["patching_analysis"]["block"]
        assert "most_critical_layer" in self.report["patching_analysis"]["block"]
        assert "most_critical_position" in self.report["patching_analysis"]["block"]
        assert "top_5_critical" in self.report["patching_analysis"]["head"]
        assert "mean_abs_effect" in self.report["patching_analysis"]["head"]

    def test_block_top5_critical(self):
        top5 = self.report["patching_analysis"]["block"]["top_5_critical"]
        assert len(top5) == 5
        # First critical component should be (1, 0, 1) = attn_out, layer 0, position 1
        assert top5[0] == [1, 0, 1], f"Expected [1, 0, 1], got {top5[0]}"
        # Second should be (1, 5, 17)
        assert top5[1] == [1, 5, 17], f"Expected [1, 5, 17], got {top5[1]}"

    def test_head_top5_critical(self):
        top5 = self.report["patching_analysis"]["head"]["top_5_critical"]
        assert len(top5) == 5
        # First critical head should be (4, 3)
        assert top5[0] == [4, 3], f"Expected [4, 3], got {top5[0]}"
        # Second should be (2, 1)
        assert top5[1] == [2, 1], f"Expected [2, 1], got {top5[1]}"

    def test_component_importance(self):
        ci = self.report["patching_analysis"]["block"]["component_importance"]
        assert abs(ci["resid_pre"] - 0.5002) < ATOL
        assert abs(ci["attn_out"] - 0.4444) < ATOL
        assert abs(ci["mlp_out"] - 0.4817) < ATOL

    def test_most_critical_layer_and_position(self):
        block = self.report["patching_analysis"]["block"]
        assert block["most_critical_layer"] == 4
        assert block["most_critical_position"] == 4

    def test_head_mean_abs_effect(self):
        mae = self.report["patching_analysis"]["head"]["mean_abs_effect"]
        assert abs(mae - 0.5145) < ATOL

    def test_loss_approx_ndcg(self):
        val = self.report["loss_evaluation"]["approx_ndcg"]
        assert abs(val - 0.2319672704) < ATOL

    def test_loss_approx_mrr(self):
        val = self.report["loss_evaluation"]["approx_mrr"]
        assert abs(val - 0.4370570183) < ATOL

    def test_loss_listnet(self):
        val = self.report["loss_evaluation"]["listnet"]
        assert abs(val - 1.2272557020) < ATOL

    def test_eval_metrics_structure(self):
        em = self.report["evaluation_metrics"]
        assert "ndcg" in em
        assert "map" in em
        assert "mrr" in em

    def test_eval_ndcg(self):
        val = self.report["evaluation_metrics"]["ndcg"]
        assert abs(val - 0.3641750859) < ATOL, f"Expected ~0.3642, got {val}"

    def test_eval_map(self):
        val = self.report["evaluation_metrics"]["map"]
        assert abs(val - 0.5370370370) < ATOL, f"Expected ~0.5370, got {val}"

    def test_eval_mrr(self):
        val = self.report["evaluation_metrics"]["mrr"]
        assert abs(val - 0.8333333333) < ATOL, f"Expected ~0.8333, got {val}"
