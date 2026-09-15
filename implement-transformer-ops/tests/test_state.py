"""
Tests for custom transformer operations.

Each test class targets a specific operation in ops.py.  Several tests
are marked "DNA" — they verify non-standard behaviour that is unique
to this task and cannot be satisfied by textbook implementations.

"""

import json
import math
import os
import sys

import pytest
import torch
import torch.nn.functional as F

sys.path.insert(0, "/app")


# ===================================================================
# log_softmax
# ===================================================================
class TestLogSoftmax:
    def test_sums_to_one(self):
        from ops import log_softmax
        x = torch.randn(3, 5)
        lp = log_softmax(x, dim=-1)
        assert torch.allclose(torch.exp(lp).sum(-1), torch.ones(3), atol=1e-5)

    def test_numerical_stability(self):
        from ops import log_softmax
        x = torch.tensor([[1000.0, 1001.0, 1002.0]])
        lp = log_softmax(x, dim=-1)
        assert torch.all(torch.isfinite(lp))
        assert torch.allclose(torch.exp(lp).sum(-1), torch.ones(1), atol=1e-5)

    def test_known_values(self):
        from ops import log_softmax
        x = torch.tensor([[0.0, 0.0, 0.0]])
        lp = log_softmax(x, dim=-1)
        assert torch.allclose(lp, torch.full((1, 3), -math.log(3.0)), atol=1e-5)

    def test_matches_reference(self):
        from ops import log_softmax
        torch.manual_seed(77)
        x = torch.randn(4, 6)
        result = log_softmax(x, dim=-1)
        expected = F.log_softmax(x, dim=-1)
        assert torch.allclose(result, expected, atol=1e-5)

    def test_gradient_flow(self):
        from ops import log_softmax
        x = torch.randn(2, 4, requires_grad=True)
        lp = log_softmax(x, dim=-1)
        lp.sum().backward()
        assert x.grad is not None
        assert torch.all(torch.isfinite(x.grad))


# ===================================================================
# rms_norm  — DNA: must NOT be standard LayerNorm
# ===================================================================
class TestRMSNorm:
    def test_basic(self):
        from ops import rms_norm
        x = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
        gain = torch.ones(4)
        rms_val = math.sqrt((1 + 4 + 9 + 16) / 4 + 1e-6)
        expected = x / rms_val
        result = rms_norm(x, gain, 1e-6)
        assert torch.allclose(result, expected, atol=1e-5)

    def test_gain_scaling(self):
        from ops import rms_norm
        x = torch.ones(1, 4)
        gain = torch.tensor([2.0, 3.0, 4.0, 5.0])
        result = rms_norm(x, gain, 1e-6)
        # RMS of all-ones = 1, so result = x * gain = gain
        assert torch.allclose(result, gain.unsqueeze(0), atol=1e-5)

    def test_differs_from_layer_norm_dna(self):
        """DNA: rms_norm must NOT equal LayerNorm output."""
        from ops import rms_norm
        torch.manual_seed(123)
        x = torch.randn(2, 3, 8) + 2.0  # non-zero mean
        gain = torch.ones(8)
        result = rms_norm(x, gain, 1e-6)
        ln_result = F.layer_norm(x, [8], weight=gain, eps=1e-6)
        assert not torch.allclose(result, ln_result, atol=1e-3), (
            "rms_norm must NOT produce the same output as LayerNorm"
        )

    def test_no_mean_centering_dna(self):
        """DNA: result mean should NOT be zero (unlike LayerNorm)."""
        from ops import rms_norm
        x = torch.tensor([[3.0, 3.0, 3.0, 3.0]])
        gain = torch.ones(4)
        result = rms_norm(x, gain, 1e-6)
        # RMS of [3,3,3,3] = 3.  result = [3/3, 3/3, 3/3, 3/3] = [1,1,1,1]
        # Mean = 1, NOT 0.
        assert abs(result.mean().item() - 1.0) < 1e-5, (
            "rms_norm should not center to zero mean"
        )

    def test_gradient_flow(self):
        from ops import rms_norm
        x = torch.randn(2, 4, requires_grad=True)
        gain = torch.ones(4, requires_grad=True)
        result = rms_norm(x, gain, 1e-6)
        result.sum().backward()
        assert x.grad is not None and gain.grad is not None


# ===================================================================
# scaled_dot_attention  — DNA: uses explicit tau, not sqrt(d_k)
# ===================================================================
class TestScaledDotAttention:
    def test_output_shape(self):
        from ops import scaled_dot_attention
        Q = torch.randn(2, 4, 5, 16)
        K = torch.randn(2, 4, 5, 16)
        V = torch.randn(2, 4, 5, 16)
        result = scaled_dot_attention(Q, K, V, tau=2.0)
        assert result.shape == (2, 4, 5, 16)

    def test_tau_matters_dna(self):
        """DNA: changing tau must change the output."""
        from ops import scaled_dot_attention
        torch.manual_seed(42)
        Q = torch.randn(1, 1, 4, 16)
        K = torch.randn(1, 1, 4, 16)
        V = torch.randn(1, 1, 4, 16)
        out_a = scaled_dot_attention(Q, K, V, tau=2.52)
        out_b = scaled_dot_attention(Q, K, V, tau=4.0)
        assert not torch.allclose(out_a, out_b, atol=1e-3), (
            "Different tau values must produce different outputs"
        )

    def test_correct_computation_with_custom_tau(self):
        """DNA: verify exact result with the model's tau = d_k^(1/3)."""
        from ops import scaled_dot_attention
        torch.manual_seed(99)
        d_k = 16
        tau = d_k ** (1.0 / 3.0)  # ≈ 2.5198
        Q = torch.randn(1, 1, 3, d_k)
        K = torch.randn(1, 1, 3, d_k)
        V = torch.randn(1, 1, 3, d_k)
        result = scaled_dot_attention(Q, K, V, tau=tau)
        # manual reference
        scores = torch.matmul(Q, K.transpose(-2, -1)) / tau
        weights = F.softmax(scores, dim=-1)
        expected = torch.matmul(weights, V)
        assert torch.allclose(result, expected, atol=1e-5)

    def test_mask_application(self):
        from ops import scaled_dot_attention
        Q = torch.randn(1, 1, 3, 4)
        K = torch.randn(1, 1, 3, 4)
        V = torch.tensor([[[[1.0, 0.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0, 0.0],
                            [0.0, 0.0, 1.0, 0.0]]]])
        mask = torch.tensor([[[[True, False, False],
                               [True, True, False],
                               [True, True, True]]]])
        result = scaled_dot_attention(Q, K, V, mask=mask, tau=1.0)
        # Row 0: attends only to position 0, so output ≈ V[0]
        assert torch.allclose(result[0, 0, 0], V[0, 0, 0], atol=1e-5)

    def test_different_seq_lengths(self):
        from ops import scaled_dot_attention
        Q = torch.randn(1, 2, 3, 8)
        K = torch.randn(1, 2, 5, 8)
        V = torch.randn(1, 2, 5, 8)
        result = scaled_dot_attention(Q, K, V, tau=2.0)
        assert result.shape == (1, 2, 3, 8)

    def test_gradient_flow(self):
        from ops import scaled_dot_attention
        Q = torch.randn(1, 1, 3, 8, requires_grad=True)
        K = torch.randn(1, 1, 3, 8, requires_grad=True)
        V = torch.randn(1, 1, 3, 8, requires_grad=True)
        result = scaled_dot_attention(Q, K, V, tau=2.0)
        result.sum().backward()
        assert all(t.grad is not None for t in [Q, K, V])


# ===================================================================
# sinusoidal_pe  — DNA: must respect the *base* argument
# ===================================================================
class TestSinusoidalPE:
    def test_shape(self):
        from ops import sinusoidal_pe
        pe = sinusoidal_pe(10, 64, 5000.0)
        assert pe.shape == (10, 64)

    def test_no_gradient(self):
        from ops import sinusoidal_pe
        pe = sinusoidal_pe(5, 8, 5000.0)
        assert not pe.requires_grad

    def test_position_zero(self):
        from ops import sinusoidal_pe
        pe = sinusoidal_pe(3, 4, 5000.0)
        # sin(0) = 0 for even dims, cos(0) = 1 for odd dims
        assert abs(pe[0, 0].item()) < 1e-6
        assert abs(pe[0, 2].item()) < 1e-6
        assert abs(pe[0, 1].item() - 1.0) < 1e-6
        assert abs(pe[0, 3].item() - 1.0) < 1e-6

    def test_known_values_dim0(self):
        from ops import sinusoidal_pe
        pe = sinusoidal_pe(5, 8, 5000.0)
        # pos=1, dim=0: sin(1 * 5000^(-0/8)) = sin(1)
        assert abs(pe[1, 0].item() - math.sin(1.0)) < 1e-5
        # pos=1, dim=1: cos(1 * 5000^(-0/8)) = cos(1)
        assert abs(pe[1, 1].item() - math.cos(1.0)) < 1e-5
        # pos=2, dim=0: sin(2)
        assert abs(pe[2, 0].item() - math.sin(2.0)) < 1e-5

    def test_known_values_higher_dim_dna(self):
        """DNA: verify PE values with base=5000 (not 10000)."""
        from ops import sinusoidal_pe
        pe = sinusoidal_pe(5, 8, 5000.0)
        # pos=1, dim=2 (i=1): sin(1 / 5000^(2/8))
        div = 5000.0 ** (2.0 / 8.0)
        expected_sin = math.sin(1.0 / div)
        expected_cos = math.cos(1.0 / div)
        assert abs(pe[1, 2].item() - expected_sin) < 1e-5
        assert abs(pe[1, 3].item() - expected_cos) < 1e-5

    def test_base_5000_differs_from_10000_dna(self):
        """DNA: PE(base=5000) must differ from PE(base=10000)."""
        from ops import sinusoidal_pe
        pe_5000 = sinusoidal_pe(10, 64, 5000.0)
        pe_10000 = sinusoidal_pe(10, 64, 10000.0)
        assert not torch.allclose(pe_5000, pe_10000, atol=1e-3), (
            "PE with base=5000 must differ from base=10000"
        )


# ===================================================================
# make_causal_mask  — DNA: must support sliding window
# ===================================================================
class TestCausalMask:
    def test_full_causal(self):
        from ops import make_causal_mask
        mask = make_causal_mask(4, window=0)
        assert mask.shape == (1, 1, 4, 4)
        expected = torch.tensor([
            [True, False, False, False],
            [True, True, False, False],
            [True, True, True, False],
            [True, True, True, True],
        ])
        assert torch.equal(mask.squeeze(), expected)

    def test_sliding_window_dna(self):
        """DNA: window>0 must produce a banded causal mask."""
        from ops import make_causal_mask
        mask = make_causal_mask(6, window=3)
        expected = torch.tensor([
            [True, False, False, False, False, False],
            [True, True, False, False, False, False],
            [True, True, True, False, False, False],
            [False, True, True, True, False, False],
            [False, False, True, True, True, False],
            [False, False, False, True, True, True],
        ])
        assert torch.equal(mask.squeeze(), expected), (
            "Sliding-window mask with window=3 is wrong"
        )

    def test_window_one_is_diagonal(self):
        from ops import make_causal_mask
        mask = make_causal_mask(4, window=1)
        assert torch.equal(mask.squeeze(), torch.eye(4, dtype=torch.bool))

    def test_window_ge_size_equals_full_causal(self):
        from ops import make_causal_mask
        full = make_causal_mask(5, window=0)
        big_window = make_causal_mask(5, window=5)
        assert torch.equal(full, big_window)

    def test_full_causal_differs_from_window_dna(self):
        """DNA: sliding-window mask must differ from full causal."""
        from ops import make_causal_mask
        full = make_causal_mask(10, window=0)
        windowed = make_causal_mask(10, window=5)
        assert not torch.equal(full, windowed), (
            "Sliding-window mask must differ from full causal when window < size"
        )


# ===================================================================
# compute_loss  — DNA: pad-excluded smoothing distribution
# ===================================================================
class TestComputeLoss:
    def test_basic_positive(self):
        from ops import compute_loss
        logits = torch.randn(4, 5)
        targets = torch.tensor([1, 2, 3, 4])
        loss = compute_loss(logits, targets, pad_idx=0, smooth_eps=0.0)
        assert loss.item() > 0

    def test_no_smoothing_is_nll(self):
        """With smooth_eps=0, loss must equal standard NLL."""
        from ops import compute_loss
        torch.manual_seed(42)
        logits = torch.randn(6, 5)
        targets = torch.tensor([1, 2, 3, 4, 1, 2])
        loss = compute_loss(logits, targets, pad_idx=0, smooth_eps=0.0)
        ref_lp = F.log_softmax(logits, dim=-1)
        ref_nll = -ref_lp[torch.arange(6), targets].mean()
        assert torch.allclose(loss, ref_nll, atol=1e-4)

    def test_pad_positions_ignored(self):
        from ops import compute_loss
        torch.manual_seed(7)
        logits = torch.randn(4, 5)
        targets_no_pad = torch.tensor([1, 2, 3, 4])
        targets_with_pad = torch.tensor([1, 2, 0, 0])
        l1 = compute_loss(logits, targets_no_pad, pad_idx=0, smooth_eps=0.0)
        l2 = compute_loss(logits, targets_with_pad, pad_idx=0, smooth_eps=0.0)
        assert not torch.allclose(l1, l2, atol=1e-4), (
            "Losses should differ when padding is present"
        )
        # With pad, only first 2 positions contribute
        ref_lp = F.log_softmax(logits, dim=-1)
        ref = -(ref_lp[0, 1] + ref_lp[1, 2]) / 2
        assert abs(l2.item() - ref.item()) < 1e-4

    def test_smooth_pad_exclusion_dna(self):
        """DNA: smoothing mass must be distributed over non-pad classes
        only.  If pad class is included, the loss value will differ."""
        from ops import compute_loss, log_softmax
        V = 5
        logits = torch.tensor([[10.0, 2.0, 1.0, 0.5, 0.0]])
        targets = torch.tensor([1])
        loss = compute_loss(logits, targets, pad_idx=0, smooth_eps=0.3)
        # Reference: nll + smooth over NON-pad classes
        ref_lp = F.log_softmax(logits, dim=-1)
        nll = -ref_lp[0, 1]
        smooth = -ref_lp[0, 1:].sum() / (V - 1)  # exclude pad (idx 0)
        expected = 0.7 * nll + 0.3 * smooth
        assert abs(loss.item() - expected.item()) < 1e-4, (
            f"Expected {expected.item():.4f}, got {loss.item():.4f}. "
            "Smoothing must exclude the pad class."
        )

    def test_smoothing_increases_loss(self):
        from ops import compute_loss
        logits = torch.zeros(1, 5)
        logits[0, 1] = 100.0  # very confident
        targets = torch.tensor([1])
        l0 = compute_loss(logits, targets, pad_idx=0, smooth_eps=0.0)
        l1 = compute_loss(logits, targets, pad_idx=0, smooth_eps=0.1)
        assert l1.item() > l0.item(), (
            "Smoothing should increase loss for confident predictions"
        )

    def test_gradient_flow(self):
        from ops import compute_loss
        logits = torch.randn(4, 5, requires_grad=True)
        targets = torch.tensor([1, 2, 3, 0])
        loss = compute_loss(logits, targets, pad_idx=0, smooth_eps=0.1)
        loss.backward()
        assert logits.grad is not None
        assert torch.all(torch.isfinite(logits.grad))


# ===================================================================
# Forbidden imports
# ===================================================================
class TestForbiddenImports:
    def test_no_nn_functional(self):
        with open("/app/ops.py") as f:
            lines = f.readlines()
        code_lines = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            triple = stripped.count('"""') + stripped.count("'''")
            if triple == 1:
                in_docstring = not in_docstring
                continue
            elif triple >= 2:
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            code_lines.append(line)
        code = "".join(code_lines)
        forbidden = [
            "torch.nn.functional",
            "from torch.nn import functional",
            "nn.functional",
            "torch.softmax",
            "torch.log_softmax",
            "torch.nn.LayerNorm",
            "torch.nn.MultiheadAttention",
            "F.softmax",
            "F.log_softmax",
            "F.layer_norm",
            "F.cross_entropy",
            "F.rms_norm",
        ]
        for pat in forbidden:
            assert pat not in code, f"Forbidden: '{pat}' found in ops.py"


# ===================================================================
# Integration: training convergence
# ===================================================================
class TestIntegration:
    def test_training_converges(self):
        if not os.path.exists("/app/results.json"):
            pytest.skip("results.json missing — run train.py first")
        with open("/app/results.json") as f:
            results = json.load(f)
        assert results["final_loss"] < 0.5, (
            f"Loss {results['final_loss']:.4f} >= 0.5"
        )

    def test_copy_accuracy(self):
        if not os.path.exists("/app/results.json"):
            pytest.skip("results.json missing — run train.py first")
        with open("/app/results.json") as f:
            results = json.load(f)
        assert results["copy_accuracy"] >= 0.85, (
            f"Accuracy {results['copy_accuracy']:.2%} < 85%"
        )
