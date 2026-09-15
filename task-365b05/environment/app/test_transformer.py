
import math
import sys

sys.path.insert(0, "/app")

import numpy as np
import pytest
import torch
import torch.nn.functional as F
from torch.nn.utils.clip_grad import clip_grad_norm_

from transformer import (
    AdamW,
    TransformerLM,
    cross_entropy,
    get_cosine_schedule,
    gradient_clipping,
    rms_norm,
    rope,
    scaled_dot_product_attention,
    silu,
    softmax,
)


# ---------------------------------------------------------------------------
# softmax
# ---------------------------------------------------------------------------
class TestSoftmax:
    def test_correctness(self):
        torch.manual_seed(42)
        x = torch.randn(3, 5)
        result = softmax(x, dim=-1)
        expected = F.softmax(x, dim=-1)
        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-6
        )

    def test_numerical_stability(self):
        torch.manual_seed(42)
        x = torch.randn(3, 5)
        expected = F.softmax(x, dim=-1)
        result = softmax(x + 1000.0, dim=-1)
        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-5
        )

    def test_dim0(self):
        torch.manual_seed(42)
        x = torch.randn(4, 3)
        result = softmax(x, dim=0)
        expected = F.softmax(x, dim=0)
        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-6
        )


# ---------------------------------------------------------------------------
# cross-entropy
# ---------------------------------------------------------------------------
class TestCrossEntropy:
    def test_correctness(self):
        torch.manual_seed(42)
        logits = torch.randn(8, 10)
        targets = torch.randint(0, 10, (8,))
        result = cross_entropy(logits, targets)
        expected = F.cross_entropy(logits, targets)
        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-5
        )

    def test_numerical_stability(self):
        torch.manual_seed(42)
        logits = torch.randn(8, 10)
        targets = torch.randint(0, 10, (8,))
        large_logits = 1000.0 * logits
        result = cross_entropy(large_logits, targets)
        expected = F.cross_entropy(large_logits, targets)
        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-4
        )


# ---------------------------------------------------------------------------
# SiLU
# ---------------------------------------------------------------------------
class TestSiLU:
    def test_matches_pytorch(self):
        x = torch.tensor(
            [
                [0.2352, 0.9259, 0.5189, 0.4725, 0.9730],
                [0.7581, 0.9692, 0.2129, 0.9345, 0.0149],
            ]
        )
        result = silu(x)
        expected = F.silu(x)
        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-6
        )


# ---------------------------------------------------------------------------
# RMSNorm
# ---------------------------------------------------------------------------
class TestRMSNorm:
    def test_unit_rms(self):
        """After RMSNorm with unit weights, RMS of each vector should be ~1."""
        torch.manual_seed(42)
        d_model = 64
        x = torch.randn(2, 8, d_model)
        weight = torch.ones(d_model)
        result = rms_norm(x, weight, eps=1e-5)
        rms_vals = torch.sqrt(torch.mean(result ** 2, dim=-1))
        np.testing.assert_allclose(
            rms_vals.detach().numpy(),
            np.ones_like(rms_vals.detach().numpy()),
            atol=1e-4,
        )

    def test_shape_preservation(self):
        torch.manual_seed(42)
        x = torch.randn(3, 4, 32)
        weight = torch.ones(32)
        result = rms_norm(x, weight)
        assert result.shape == x.shape

    def test_weight_scaling(self):
        """Doubling the weight should double the output."""
        torch.manual_seed(42)
        d_model = 16
        x = torch.randn(2, 4, d_model)
        w1 = torch.ones(d_model)
        w2 = 2.0 * torch.ones(d_model)
        r1 = rms_norm(x, w1)
        r2 = rms_norm(x, w2)
        np.testing.assert_allclose(
            (r1 * 2).detach().numpy(), r2.detach().numpy(), atol=1e-5
        )


# ---------------------------------------------------------------------------
# RoPE
# ---------------------------------------------------------------------------
class TestRoPE:
    def test_correctness(self):
        """Compare against a loop-based reference implementation."""
        torch.manual_seed(42)
        d_k = 16
        batch_size = 2
        seq_len = 4
        theta = 10000.0

        x = torch.randn(batch_size, seq_len, d_k)
        positions = torch.arange(seq_len).unsqueeze(0).expand(batch_size, -1)

        result = rope(x, positions, theta, d_k)

        expected = torch.zeros_like(x)
        for b in range(batch_size):
            for s in range(seq_len):
                m = positions[b, s].item()
                for i in range(d_k // 2):
                    freq = 1.0 / (theta ** (2.0 * i / d_k))
                    angle = m * freq
                    cos_a = math.cos(angle)
                    sin_a = math.sin(angle)
                    expected[b, s, 2 * i] = (
                        x[b, s, 2 * i] * cos_a - x[b, s, 2 * i + 1] * sin_a
                    )
                    expected[b, s, 2 * i + 1] = (
                        x[b, s, 2 * i] * sin_a + x[b, s, 2 * i + 1] * cos_a
                    )

        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-5
        )

    def test_norm_preservation(self):
        """Rotation preserves the L2 norm of each vector."""
        torch.manual_seed(42)
        d_k = 32
        x = torch.randn(4, 8, d_k)
        positions = torch.arange(8).unsqueeze(0).expand(4, -1)
        result = rope(x, positions, 10000.0, d_k)
        in_norms = torch.norm(x, dim=-1)
        out_norms = torch.norm(result, dim=-1)
        np.testing.assert_allclose(
            in_norms.detach().numpy(), out_norms.detach().numpy(), atol=1e-5
        )

    def test_position_zero_identity(self):
        """At position 0, all rotation angles are 0; RoPE is identity."""
        torch.manual_seed(42)
        d_k = 16
        x = torch.randn(1, 1, d_k)
        positions = torch.zeros(1, 1, dtype=torch.long)
        result = rope(x, positions, 10000.0, d_k)
        np.testing.assert_allclose(
            result.detach().numpy(), x.detach().numpy(), atol=1e-6
        )


# ---------------------------------------------------------------------------
# Scaled Dot-Product Attention
# ---------------------------------------------------------------------------
class TestSDPA:
    def test_without_mask(self):
        torch.manual_seed(42)
        batch, seq, d_k = 2, 4, 8
        Q = torch.randn(batch, seq, d_k)
        K = torch.randn(batch, seq, d_k)
        V = torch.randn(batch, seq, d_k)

        result = scaled_dot_product_attention(Q, K, V)

        scores = torch.bmm(Q, K.transpose(-2, -1)) / math.sqrt(d_k)
        weights = F.softmax(scores, dim=-1)
        expected = torch.bmm(weights, V)

        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-5
        )

    def test_with_causal_mask(self):
        torch.manual_seed(42)
        batch, seq, d_k = 2, 6, 8
        Q = torch.randn(batch, seq, d_k)
        K = torch.randn(batch, seq, d_k)
        V = torch.randn(batch, seq, d_k)

        mask = torch.triu(torch.ones(seq, seq, dtype=torch.bool), diagonal=1)
        result = scaled_dot_product_attention(Q, K, V, mask=mask)

        scores = torch.bmm(Q, K.transpose(-2, -1)) / math.sqrt(d_k)
        scores = scores.masked_fill(mask, float("-inf"))
        weights = F.softmax(scores, dim=-1)
        expected = torch.bmm(weights, V)

        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-5
        )

    def test_4d_input(self):
        """Test with (batch, heads, seq, d_k) shape."""
        torch.manual_seed(42)
        batch, heads, seq, d_k = 2, 4, 6, 8
        Q = torch.randn(batch, heads, seq, d_k)
        K = torch.randn(batch, heads, seq, d_k)
        V = torch.randn(batch, heads, seq, d_k)

        result = scaled_dot_product_attention(Q, K, V)

        scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(d_k)
        weights = F.softmax(scores, dim=-1)
        expected = torch.matmul(weights, V)

        np.testing.assert_allclose(
            result.detach().numpy(), expected.detach().numpy(), atol=1e-5
        )


# ---------------------------------------------------------------------------
# TransformerLM
# ---------------------------------------------------------------------------
class TestTransformerLM:
    @staticmethod
    def _make_model(seed=42):
        torch.manual_seed(seed)
        return TransformerLM(
            vocab_size=50,
            context_length=16,
            d_model=32,
            num_layers=2,
            num_heads=4,
            d_ff=64,
            theta=10000.0,
        )

    def test_output_shape(self):
        model = self._make_model()
        x = torch.randint(0, 50, (2, 8))
        with torch.no_grad():
            logits = model(x)
        assert logits.shape == (2, 8, 50), f"Expected (2, 8, 50), got {logits.shape}"

    def test_causal_masking(self):
        """Changing future tokens must not affect past outputs."""
        model = self._make_model()
        x1 = torch.tensor([[1, 2, 3, 4, 5, 6, 7, 8]])
        x2 = torch.tensor([[1, 2, 3, 4, 5, 6, 7, 0]])  # last token differs

        with torch.no_grad():
            out1 = model(x1)
            out2 = model(x2)

        # Positions 0-6 must be identical (they cannot see position 7)
        np.testing.assert_allclose(
            out1[0, :7].detach().numpy(),
            out2[0, :7].detach().numpy(),
            atol=1e-5,
        )
        # Position 7 must differ (it sees itself)
        assert not np.allclose(
            out1[0, 7].detach().numpy(),
            out2[0, 7].detach().numpy(),
            atol=1e-3,
        )

    def test_gradient_flow(self):
        """All parameters must receive non-zero gradients."""
        model = self._make_model()
        x = torch.randint(0, 50, (2, 4))
        targets = torch.randint(0, 50, (2, 4))

        logits = model(x)
        loss = F.cross_entropy(logits.reshape(-1, 50), targets.reshape(-1))
        loss.backward()

        for name, param in model.named_parameters():
            assert param.grad is not None, f"No gradient for {name}"
            assert param.grad.abs().sum() > 0, f"Zero gradient for {name}"


# ---------------------------------------------------------------------------
# AdamW
# ---------------------------------------------------------------------------
class TestAdamW:
    def test_matches_pytorch(self):
        """Our AdamW must match torch.optim.AdamW after 1000 steps."""
        torch.manual_seed(42)
        initial_weight = torch.randn(2, 3)

        # --- our implementation ---
        m1 = torch.nn.Linear(3, 2, bias=False)
        m1.weight.data.copy_(initial_weight)
        opt1 = AdamW(
            m1.parameters(),
            lr=1e-3, weight_decay=0.01, betas=(0.9, 0.999), eps=1e-8,
        )
        torch.manual_seed(100)
        for _ in range(1000):
            x = torch.rand(3)
            opt1.zero_grad()
            y_hat = m1(x)
            y = torch.tensor([x[0] + x[1], -x[2]])
            loss = ((y - y_hat) ** 2).sum()
            loss.backward()
            opt1.step()

        # --- PyTorch reference ---
        m2 = torch.nn.Linear(3, 2, bias=False)
        m2.weight.data.copy_(initial_weight)
        opt2 = torch.optim.AdamW(
            m2.parameters(),
            lr=1e-3, weight_decay=0.01, betas=(0.9, 0.999), eps=1e-8,
        )
        torch.manual_seed(100)
        for _ in range(1000):
            x = torch.rand(3)
            opt2.zero_grad()
            y_hat = m2(x)
            y = torch.tensor([x[0] + x[1], -x[2]])
            loss = ((y - y_hat) ** 2).sum()
            loss.backward()
            opt2.step()

        np.testing.assert_allclose(
            m1.weight.detach().numpy(),
            m2.weight.detach().numpy(),
            atol=1e-4,
        )


# ---------------------------------------------------------------------------
# Cosine LR schedule
# ---------------------------------------------------------------------------
class TestCosineSchedule:
    def test_known_values(self):
        max_lr = 1.0
        min_lr = 0.1
        warmup = 7
        cycle = 21

        expected = [
            0.0,
            0.14285714285714285,
            0.2857142857142857,
            0.42857142857142855,
            0.5714285714285714,
            0.7142857142857143,
            0.8571428571428571,
            1.0,
            0.9887175604818206,
            0.9554359905560885,
            0.9018241671106134,
            0.8305704108364301,
            0.7452476826029011,
            0.6501344202803414,
            0.55,
            0.44986557971965857,
            0.3547523173970989,
            0.26942958916356996,
            0.19817583288938662,
            0.14456400944391146,
            0.11128243951817937,
            0.1,
            0.1,
            0.1,
            0.1,
        ]

        actual = [
            get_cosine_schedule(it, max_lr, min_lr, warmup, cycle) for it in range(25)
        ]
        np.testing.assert_allclose(np.array(actual), np.array(expected), atol=1e-10)


# ---------------------------------------------------------------------------
# Gradient clipping
# ---------------------------------------------------------------------------
class TestGradientClipping:
    def test_matches_pytorch(self):
        torch.manual_seed(42)
        tensors = [torch.randn(5, 5) for _ in range(6)]
        max_norm = 1e-2

        # PyTorch reference
        t_ref = [torch.nn.Parameter(t.clone()) for t in tensors]
        t_ref[-1].requires_grad_(False)
        loss_ref = torch.cat(t_ref).sum()
        loss_ref.backward()
        clip_grad_norm_(t_ref, max_norm)
        ref_grads = [t.grad.clone() for t in t_ref if t.grad is not None]

        # Our implementation
        t_ours = [torch.nn.Parameter(t.clone()) for t in tensors]
        t_ours[-1].requires_grad_(False)
        loss_ours = torch.cat(t_ours).sum()
        loss_ours.backward()
        gradient_clipping(t_ours, max_norm)
        our_grads = [t.grad.clone() for t in t_ours if t.grad is not None]

        assert len(ref_grads) == len(our_grads)
        for ref, ours in zip(ref_grads, our_grads):
            np.testing.assert_allclose(
                ours.detach().numpy(), ref.detach().numpy(), atol=1e-6
            )


# ---------------------------------------------------------------------------
# Integration: training convergence
# ---------------------------------------------------------------------------
class TestIntegration:
    def test_training_convergence(self):
        """The model must overfit on a tiny fixed batch (loss decreases >= 40%)."""
        torch.manual_seed(42)
        vocab_size = 50
        context_length = 8

        model = TransformerLM(
            vocab_size=vocab_size,
            context_length=context_length,
            d_model=32,
            num_layers=1,
            num_heads=2,
            d_ff=64,
            theta=10000.0,
        )
        optimizer = AdamW(
            model.parameters(),
            lr=1e-3, weight_decay=0.0, betas=(0.9, 0.999), eps=1e-8,
        )

        torch.manual_seed(0)
        x = torch.randint(0, vocab_size, (4, context_length))
        targets = torch.randint(0, vocab_size, (4, context_length))

        initial_loss = None
        final_loss = None
        for step in range(300):
            optimizer.zero_grad()
            logits = model(x)
            loss = cross_entropy(logits.reshape(-1, vocab_size), targets.reshape(-1))
            assert not math.isnan(loss.item()), f"NaN loss at step {step}"
            loss.backward()
            optimizer.step()

            if step == 0:
                initial_loss = loss.item()
            if step == 299:
                final_loss = loss.item()

        assert final_loss < initial_loss * 0.6, (
            f"Loss did not decrease enough: {initial_loss:.4f} -> {final_loss:.4f} "
            f"(ratio {final_loss / initial_loss:.3f}, need < 0.6)"
        )
