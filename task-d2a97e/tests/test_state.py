
"""Tests verifying the UnifiedNormalizer and evaluation report.

Tests check that:
1. UnifiedNormalizer exists with required interface
2. GA matches full-batch for unweighted variable-length sequences
3. GA matches full-batch for weighted variable-length sequences
4. Model weights are identical after GA vs full-batch training
5. Multi-step training trajectories remain consistent
6. Evaluation report correctly classifies existing strategies
"""

import sys
import torch
import copy
import json
import os

sys.path.insert(0, "/opt/ga_bench")

from model import SmallCausalLM
from dataset import create_dataset, collate_sequences
from trainer import Trainer


def _load_unified():
    """Load the UnifiedNormalizer from normalizers.py."""
    import importlib
    import normalizers
    importlib.reload(normalizers)

    assert hasattr(normalizers, "UnifiedNormalizer"), (
        "normalizers.py must contain a class named 'UnifiedNormalizer'"
    )
    return normalizers.UnifiedNormalizer


def _make_model():
    return SmallCausalLM(vocab_size=512, dim=96, hidden_dim=192, n_layers=2)


class TestUnifiedNormalizerExists:

    def test_class_exists(self):
        UnifiedNormalizer = _load_unified()
        assert UnifiedNormalizer is not None

    def test_has_required_methods(self):
        UnifiedNormalizer = _load_unified()
        n = UnifiedNormalizer()
        assert hasattr(n, "prepare"), "must have prepare()"
        assert hasattr(n, "compute_loss"), "must have compute_loss()"
        assert hasattr(n, "aggregate"), "must have aggregate()"


class TestUnifiedUnweighted:
    """UnifiedNormalizer must match full-batch for unweighted variable-length."""

    def test_ga2_variable(self):
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(42)
        model = _make_model()
        seqs = create_dataset(8, 512, 10, 80, seed=42)
        batch = collate_sequences(seqs)

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.01)
        loss_fb = trainer_fb.train_step_full_batch(batch)

        trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=2,
                             normalizer=UnifiedNormalizer())
        loss_ga = trainer_ga.train_step_ga(batch)

        assert abs(loss_fb - loss_ga) < 1e-5, (
            f"GA=2 unweighted: fb={loss_fb:.8f}, ga={loss_ga:.8f}, "
            f"diff={abs(loss_fb - loss_ga):.2e}"
        )

    def test_ga4_variable(self):
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(123)
        model = _make_model()
        seqs = create_dataset(16, 512, 15, 100, seed=123)
        batch = collate_sequences(seqs)

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.01)
        loss_fb = trainer_fb.train_step_full_batch(batch)

        trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=4,
                             normalizer=UnifiedNormalizer())
        loss_ga = trainer_ga.train_step_ga(batch)

        assert abs(loss_fb - loss_ga) < 1e-5, (
            f"GA=4 unweighted: fb={loss_fb:.8f}, ga={loss_ga:.8f}"
        )

    def test_ga8_variable(self):
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(999)
        model = _make_model()
        seqs = create_dataset(24, 512, 5, 120, seed=999)
        batch = collate_sequences(seqs)

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.01)
        loss_fb = trainer_fb.train_step_full_batch(batch)

        trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=8,
                             normalizer=UnifiedNormalizer())
        loss_ga = trainer_ga.train_step_ga(batch)

        assert abs(loss_fb - loss_ga) < 1e-5, (
            f"GA=8 unweighted: fb={loss_fb:.8f}, ga={loss_ga:.8f}"
        )


class TestUnifiedWeighted:
    """UnifiedNormalizer must match full-batch for weighted variable-length."""

    def test_ga2_weighted(self):
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(42)
        model = _make_model()
        seqs = create_dataset(8, 512, 10, 80, seed=42,
                              importance_weights=True,
                              prompt_weight=0.1, completion_weight=1.0)
        batch = collate_sequences(seqs)

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.01)
        loss_fb = trainer_fb.train_step_full_batch(batch)

        trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=2,
                             normalizer=UnifiedNormalizer())
        loss_ga = trainer_ga.train_step_ga(batch)

        assert abs(loss_fb - loss_ga) < 1e-5, (
            f"GA=2 weighted: fb={loss_fb:.8f}, ga={loss_ga:.8f}, "
            f"diff={abs(loss_fb - loss_ga):.2e}"
        )

    def test_ga4_weighted(self):
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(123)
        model = _make_model()
        seqs = create_dataset(16, 512, 15, 100, seed=123,
                              importance_weights=True,
                              prompt_weight=0.2, completion_weight=1.0)
        batch = collate_sequences(seqs)

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.01)
        loss_fb = trainer_fb.train_step_full_batch(batch)

        trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=4,
                             normalizer=UnifiedNormalizer())
        loss_ga = trainer_ga.train_step_ga(batch)

        assert abs(loss_fb - loss_ga) < 1e-5, (
            f"GA=4 weighted: fb={loss_fb:.8f}, ga={loss_ga:.8f}"
        )

    def test_ga4_weighted_extreme_ratio(self):
        """Extreme prompt/completion weight ratio."""
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(31415)
        model = _make_model()
        seqs = create_dataset(8, 512, 5, 200, seed=31415,
                              importance_weights=True,
                              prompt_weight=0.01, completion_weight=5.0)
        batch = collate_sequences(seqs)

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.01)
        loss_fb = trainer_fb.train_step_full_batch(batch)

        trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=4,
                             normalizer=UnifiedNormalizer())
        loss_ga = trainer_ga.train_step_ga(batch)

        assert abs(loss_fb - loss_ga) < 1e-4, (
            f"GA=4 extreme weights: fb={loss_fb:.8f}, ga={loss_ga:.8f}"
        )


class TestWeightEquivalence:
    """Model weights after GA must match full-batch."""

    def test_weights_match_unweighted(self):
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(42)
        model = _make_model()
        seqs = create_dataset(12, 512, 20, 60, seed=42)
        batch = collate_sequences(seqs)

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.01)
        trainer_fb.train_step_full_batch(batch)

        trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=4,
                             normalizer=UnifiedNormalizer())
        trainer_ga.train_step_ga(batch)

        for (name, p_fb), (_, p_ga) in zip(
            model_fb.named_parameters(), model_ga.named_parameters()
        ):
            diff = (p_fb - p_ga).abs().max().item()
            assert diff < 1e-5, f"Weight mismatch '{name}': {diff:.2e}"

    def test_weights_match_weighted(self):
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(42)
        model = _make_model()
        seqs = create_dataset(12, 512, 20, 60, seed=42,
                              importance_weights=True)
        batch = collate_sequences(seqs)

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.01)
        trainer_fb.train_step_full_batch(batch)

        trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=4,
                             normalizer=UnifiedNormalizer())
        trainer_ga.train_step_ga(batch)

        for (name, p_fb), (_, p_ga) in zip(
            model_fb.named_parameters(), model_ga.named_parameters()
        ):
            diff = (p_fb - p_ga).abs().max().item()
            assert diff < 1e-5, f"Weight mismatch '{name}': {diff:.2e}"

    def test_multi_step_trajectory(self):
        """Multiple training steps should produce identical loss trajectories."""
        UnifiedNormalizer = _load_unified()
        torch.manual_seed(7)
        model = _make_model()

        batches = []
        for i in range(3):
            seqs = create_dataset(8, 512, 10, 80, seed=100 + i,
                                  importance_weights=True)
            batches.append(collate_sequences(seqs))

        model_fb = copy.deepcopy(model)
        model_ga = copy.deepcopy(model)

        trainer_fb = Trainer(model_fb, lr=0.005)
        trainer_ga = Trainer(model_ga, lr=0.005, ga_steps=2,
                             normalizer=UnifiedNormalizer())

        for step, batch in enumerate(batches):
            loss_fb = trainer_fb.train_step_full_batch(batch)
            loss_ga = trainer_ga.train_step_ga(batch)

            assert abs(loss_fb - loss_ga) < 1e-5, (
                f"Trajectory diverged at step {step}: "
                f"fb={loss_fb:.8f}, ga={loss_ga:.8f}"
            )


class TestEvaluationReport:
    """Verify the evaluation report is correct and complete."""

    def test_report_exists(self):
        assert os.path.exists("/opt/ga_bench/evaluation_report.json"), (
            "evaluation_report.json not found at /opt/ga_bench/evaluation_report.json"
        )

    def test_report_structure(self):
        with open("/opt/ga_bench/evaluation_report.json") as f:
            report = json.load(f)

        assert "strategy_evaluations" in report
        evals = report["strategy_evaluations"]
        assert isinstance(evals, list)
        assert len(evals) >= 4, "Must evaluate all 4 strategies"

        for ev in evals:
            assert "strategy" in ev, "Each eval must name the strategy"

    def test_report_identifies_naive_failure(self):
        with open("/opt/ga_bench/evaluation_report.json") as f:
            report = json.load(f)

        evals = {e["strategy"]: e for e in report["strategy_evaluations"]}
        assert "naive_mean_scaling" in evals

        naive = evals["naive_mean_scaling"]
        eval_text = json.dumps(naive).lower()
        assert any(w in eval_text for w in [
            "fail", "incorrect", "wrong", "false"
        ]), (
            "Report must identify naive_mean_scaling as incorrect "
            "for variable lengths"
        )

    def test_report_identifies_global_token_weighted_failure(self):
        with open("/opt/ga_bench/evaluation_report.json") as f:
            report = json.load(f)

        evals = {e["strategy"]: e for e in report["strategy_evaluations"]}
        assert "global_token_count" in evals

        gtc = evals["global_token_count"]
        eval_text = json.dumps(gtc).lower()
        has_correct = any(w in eval_text for w in [
            "correct", "pass", "true", "works"
        ])
        has_failure = any(w in eval_text for w in [
            "fail", "incorrect", "wrong", "false", "ignore", "weight"
        ])
        assert has_correct and has_failure, (
            "Report must note global_token_count works unweighted "
            "but fails weighted"
        )

    def test_report_has_unified_description(self):
        with open("/opt/ga_bench/evaluation_report.json") as f:
            report = json.load(f)

        assert any(k in report for k in [
            "unified_strategy_description",
            "unified_description",
            "correct_strategy",
            "solution_description",
        ]), "Report must describe the unified strategy"

    def test_report_has_mathematical_justification(self):
        with open("/opt/ga_bench/evaluation_report.json") as f:
            report = json.load(f)

        report_text = json.dumps(report).lower()
        math_indicators = [
            "sum", "total", "token", "weight", "normali",
            "denominator", "fraction", "n_total", "w_total",
        ]
        found = sum(1 for w in math_indicators if w in report_text)
        assert found >= 3, (
            "Report must include mathematical justification "
            "with relevant normalization terms"
        )
