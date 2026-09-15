"""
Tests for the attention module implementation.

"""

import sys

sys.path.insert(0, "/app")

import pytest
import torch

from config import GLM5Config
from mla_dsa import MLADSAAttention


@pytest.fixture
def config():
    return GLM5Config()


@pytest.fixture
def model(config):
    torch.manual_seed(42)
    m = MLADSAAttention(config)
    m.eval()
    return m


# ---------------------------------------------------------------------------
# Output shape tests
# ---------------------------------------------------------------------------


class TestOutputShape:
    def test_prefill_output_shape(self, model, config):
        """Output shape matches input for prefill."""
        torch.manual_seed(100)
        bsz, seq_len = 2, 32
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0).expand(bsz, -1)

        with torch.no_grad():
            output, attn, cache = model(hidden, pos)

        assert output.shape == (bsz, seq_len, config.hidden_size)
        assert attn.shape == (bsz, config.num_attention_heads, seq_len, seq_len)
        assert cache is None

    def test_decode_output_shape(self, model, config):
        """Output shape correct for single-token decode with cache."""
        torch.manual_seed(101)
        bsz = 2
        prefill_len = 10

        hidden = torch.randn(bsz, prefill_len, config.hidden_size)
        pos = torch.arange(prefill_len).unsqueeze(0).expand(bsz, -1)

        with torch.no_grad():
            _, _, cache = model(hidden, pos, use_cache=True)

        decode_hidden = torch.randn(bsz, 1, config.hidden_size)
        decode_pos = torch.full((bsz, 1), prefill_len, dtype=torch.long)

        with torch.no_grad():
            output, attn, cache2 = model(
                decode_hidden, decode_pos, past_key_values=cache, use_cache=True
            )

        assert output.shape == (bsz, 1, config.hidden_size)
        assert attn.shape == (bsz, config.num_attention_heads, 1, prefill_len + 1)
        assert cache2 is not None
        assert cache2[0].shape[2] == prefill_len + 1


# ---------------------------------------------------------------------------
# Causal masking tests
# ---------------------------------------------------------------------------


class TestCausalMasking:
    def test_future_independence(self, model, config):
        """Changing a future token must not affect earlier outputs."""
        torch.manual_seed(200)
        bsz, seq_len = 1, 8
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0)

        with torch.no_grad():
            out1, _, _ = model(hidden, pos)

        modified = hidden.clone()
        modified[:, -1, :] = torch.randn(config.hidden_size)

        # Fresh model to reset any internal caches
        torch.manual_seed(42)
        model2 = MLADSAAttention(config)
        model2.load_state_dict(model.state_dict())
        model2.eval()

        with torch.no_grad():
            out2, _, _ = model2(modified, pos)

        # Positions 0..6 must be identical
        torch.testing.assert_close(out1[:, :-1], out2[:, :-1], atol=1e-6, rtol=1e-6)

    def test_attend_only_past(self, model, config):
        """Attention weights for future positions must be zero."""
        torch.manual_seed(201)
        bsz, seq_len = 1, 8
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0)

        with torch.no_grad():
            _, attn, _ = model(hidden, pos)

        for i in range(seq_len):
            for j in range(i + 1, seq_len):
                assert (attn[0, :, i, j] < 1e-9).all(), (
                    f"Position {i} attending to future position {j}"
                )


# ---------------------------------------------------------------------------
# DSA tests
# ---------------------------------------------------------------------------


class TestDSA:
    def test_sparsity_at_last_position(self, model, config):
        """When active, DSA limits attention to index_topk positions."""
        torch.manual_seed(300)
        bsz, seq_len = 1, 32
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0)

        with torch.no_grad():
            _, attn, _ = model(hidden, pos)

        last_pos = seq_len - 1
        for h in range(config.num_attention_heads):
            nonzero = (attn[0, h, last_pos, :] > 1e-9).sum().item()
            assert nonzero <= config.index_topk, (
                f"Head {h}: {nonzero} positions attended, expected <= {config.index_topk}"
            )
            assert nonzero >= 1, f"Head {h}: no positions attended"

    def test_no_dsa_for_short_sequences(self, model, config):
        """DSA should not restrict attention for sequences <= index_topk."""
        torch.manual_seed(301)
        bsz, seq_len = 1, config.index_topk
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0)

        with torch.no_grad():
            _, attn, _ = model(hidden, pos)

        last_pos = seq_len - 1
        for h in range(config.num_attention_heads):
            nonzero = (attn[0, h, last_pos, :] > 1e-9).sum().item()
            assert nonzero == seq_len, (
                f"Head {h}: {nonzero}/{seq_len} positions attended "
                f"(DSA should be inactive)"
            )


# ---------------------------------------------------------------------------
# KV cache tests
# ---------------------------------------------------------------------------


class TestKVCache:
    def test_cache_growth(self, model, config):
        """KV cache must grow by 1 each decode step."""
        torch.manual_seed(400)
        bsz = 1
        prefill_len = 8

        hidden = torch.randn(bsz, prefill_len, config.hidden_size)
        pos = torch.arange(prefill_len).unsqueeze(0)

        with torch.no_grad():
            _, _, cache = model(hidden, pos, use_cache=True)

        assert cache is not None
        assert cache[0].shape[2] == prefill_len
        assert cache[1].shape[2] == prefill_len

        for step in range(5):
            new_hidden = torch.randn(bsz, 1, config.hidden_size)
            new_pos = torch.tensor([[prefill_len + step]])

            with torch.no_grad():
                _, _, cache = model(
                    new_hidden, new_pos, past_key_values=cache, use_cache=True
                )

            expected_len = prefill_len + step + 1
            assert cache[0].shape[2] == expected_len, (
                f"Step {step}: key cache length {cache[0].shape[2]}, "
                f"expected {expected_len}"
            )
            assert cache[1].shape[2] == expected_len

    def test_cache_head_dims(self, model, config):
        """Cached keys and values must have correct head dimensions."""
        torch.manual_seed(401)
        bsz, seq_len = 2, 6
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0).expand(bsz, -1)

        with torch.no_grad():
            _, _, cache = model(hidden, pos, use_cache=True)

        k, v = cache
        assert k.shape == (
            bsz, config.num_attention_heads, seq_len, config.qk_head_dim
        )
        assert v.shape == (
            bsz, config.num_attention_heads, seq_len, config.v_head_dim
        )


# ---------------------------------------------------------------------------
# Prefill-decode consistency
# ---------------------------------------------------------------------------


class TestPrefillDecodeConsistency:
    def test_last_position_match(self, config):
        """Full prefill and split prefill+decode must give same last-position output."""
        torch.manual_seed(42)
        model1 = MLADSAAttention(config)
        model1.eval()

        bsz = 1
        seq_len = 24
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0)

        # Full prefill
        with torch.no_grad():
            full_out, _, _ = model1(hidden, pos)
        last_full = full_out[:, -1:, :]

        # Split: prefill all-but-last, then decode last
        torch.manual_seed(42)
        model2 = MLADSAAttention(config)
        model2.eval()

        with torch.no_grad():
            _, _, cache = model2(hidden[:, :-1], pos[:, :-1], use_cache=True)
            decode_out, _, _ = model2(
                hidden[:, -1:], pos[:, -1:], past_key_values=cache, use_cache=True
            )

        torch.testing.assert_close(last_full, decode_out, atol=1e-5, rtol=1e-5)


# ---------------------------------------------------------------------------
# Gradient flow
# ---------------------------------------------------------------------------


class TestGradientFlow:
    def test_mla_gradients(self, config):
        """All MLA parameters must receive non-zero gradients."""
        torch.manual_seed(500)
        model = MLADSAAttention(config)
        model.train()

        bsz, seq_len = 2, 8
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0).expand(bsz, -1)

        output, _, _ = model(hidden, pos)
        loss = output.sum()
        loss.backward()

        mla_params = [
            "q_a_proj",
            "q_a_layernorm",
            "q_b_proj",
            "kv_a_proj_with_mqa",
            "kv_a_layernorm",
            "kv_b_proj",
            "o_proj",
        ]
        for name, param in model.named_parameters():
            if any(mp in name for mp in mla_params):
                assert param.grad is not None, f"No gradient for {name}"
                assert param.grad.abs().sum() > 0, f"Zero gradient for {name}"


# ---------------------------------------------------------------------------
# Training convergence
# ---------------------------------------------------------------------------


class TestTrainingConvergence:
    def test_loss_decreases(self, config):
        """Loss must decrease over training steps."""
        torch.manual_seed(600)
        model = MLADSAAttention(config)
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

        bsz, seq_len = 4, 12
        hidden = torch.randn(bsz, seq_len, config.hidden_size)
        target = torch.randn(bsz, seq_len, config.hidden_size)
        pos = torch.arange(seq_len).unsqueeze(0).expand(bsz, -1)

        losses = []
        for _ in range(30):
            output, _, _ = model(hidden, pos)
            loss = ((output - target) ** 2).mean()
            losses.append(loss.item())
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        assert losses[-1] < losses[0] * 0.5, (
            f"Loss did not decrease enough: {losses[0]:.4f} -> {losses[-1]:.4f}"
        )
