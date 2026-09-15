
"""
Tests for MLAWithDSA implementation.
Validates correctness of Multi-Latent Attention with Dynamic Sparse Attention,
plus TorchScript export and profiler trace deliverables.
"""

import torch
import torch.nn.functional as F
import sys
import os
import json

sys.path.insert(0, "/app")

from config import CONFIG
from utils import compute_rope_embeddings, make_causal_mask


def _load_module():
    from mla_dsa_attention import MLAWithDSA

    return MLAWithDSA(CONFIG, layer_idx=0)


class TestMLADSAOutputShape:
    def test_output_shape_basic(self):
        torch.manual_seed(7)
        module = _load_module()
        B, S = 2, 16
        hidden = torch.randn(B, S, CONFIG["hidden_size"])
        pos_ids = torch.arange(S).unsqueeze(0).expand(B, -1)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        output, _ = module(hidden, pos_ids, cos, sin, attention_mask=mask)

        assert output.shape == (
            B,
            S,
            CONFIG["hidden_size"],
        ), f"Expected shape {(B, S, CONFIG['hidden_size'])}, got {output.shape}"

    def test_output_shape_single_token(self):
        torch.manual_seed(8)
        module = _load_module()
        B, S = 1, 1
        hidden = torch.randn(B, S, CONFIG["hidden_size"])
        pos_ids = torch.zeros(B, S, dtype=torch.long)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        output, _ = module(hidden, pos_ids, cos, sin, attention_mask=mask)
        assert output.shape == (B, S, CONFIG["hidden_size"])


class TestKVCacheConsistency:
    def test_autoregressive_matches_full_forward(self):
        """Autoregressive token-by-token decode with KV cache must produce
        the same output as a single full-sequence forward pass."""
        torch.manual_seed(42)
        module = _load_module()
        module.eval()

        # S <= index_topk ensures DSA always selects all causally-visible
        # positions, avoiding top-k ranking instability from float32 precision
        # differences between batch and single-token computation.
        B, S = 1, 8
        hidden = torch.randn(B, S, CONFIG["hidden_size"])
        pos_ids = torch.arange(S).unsqueeze(0)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        with torch.no_grad():
            output_full, _ = module(hidden, pos_ids, cos, sin, attention_mask=mask)

        # Token-by-token with KV cache
        past_kv = None
        outputs_auto = []
        with torch.no_grad():
            for t in range(S):
                h_t = hidden[:, t : t + 1, :]
                p_t = torch.tensor([[t]])
                c_t, s_t = compute_rope_embeddings(p_t, CONFIG)
                m_t = make_causal_mask(1, t, h_t.dtype, h_t.device)
                out_t, past_kv = module(
                    h_t,
                    p_t,
                    c_t,
                    s_t,
                    attention_mask=m_t,
                    past_key_values=past_kv,
                    use_cache=True,
                )
                outputs_auto.append(out_t)

        output_auto = torch.cat(outputs_auto, dim=1)
        max_diff = (output_full - output_auto).abs().max().item()
        assert torch.allclose(output_full, output_auto, atol=1e-4), (
            f"KV cache decode diverges from full forward. Max diff: {max_diff:.6e}"
        )

    def test_cache_shapes_grow_correctly(self):
        """Verify that cached tensors have correct shapes after each step."""
        torch.manual_seed(55)
        module = _load_module()
        module.eval()

        B = 1
        past_kv = None

        with torch.no_grad():
            for t in range(6):
                h_t = torch.randn(B, 1, CONFIG["hidden_size"])
                p_t = torch.tensor([[t]])
                c_t, s_t = compute_rope_embeddings(p_t, CONFIG)
                m_t = make_causal_mask(1, t, h_t.dtype, h_t.device)
                _, past_kv = module(
                    h_t,
                    p_t,
                    c_t,
                    s_t,
                    attention_mask=m_t,
                    past_key_values=past_kv,
                    use_cache=True,
                )

                expected_t = t + 1
                assert past_kv["key"].shape[2] == expected_t, (
                    f"Step {t}: key cache T={past_kv['key'].shape[2]}, expected {expected_t}"
                )
                assert past_kv["value"].shape[2] == expected_t
                assert past_kv["idx_key"].shape[1] == expected_t


class TestCausalMasking:
    def test_future_token_does_not_affect_past(self):
        """Modifying a future token must not change outputs at earlier positions."""
        torch.manual_seed(123)
        module = _load_module()
        module.eval()

        B, S = 1, 16
        hidden = torch.randn(B, S, CONFIG["hidden_size"])
        pos_ids = torch.arange(S).unsqueeze(0)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        with torch.no_grad():
            output1, _ = module(hidden, pos_ids, cos, sin, attention_mask=mask)

        # Modify token at position 10
        hidden2 = hidden.clone()
        hidden2[:, 10, :] = torch.randn(CONFIG["hidden_size"])

        with torch.no_grad():
            output2, _ = module(hidden2, pos_ids, cos, sin, attention_mask=mask)

        # Positions 0..9 must be unaffected
        assert torch.allclose(output1[:, :10, :], output2[:, :10, :], atol=1e-6), (
            "Causal violation: changing future token affected past output"
        )


class TestDSASparseSelection:
    def test_topk_count_per_position(self):
        """Each query position must select exactly min(topk, available_positions)
        tokens through the DSA indexer."""
        torch.manual_seed(0)
        module = _load_module()
        module.eval()

        B, S = 1, 20
        hidden = torch.randn(B, S, CONFIG["hidden_size"])
        pos_ids = torch.arange(S).unsqueeze(0)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        with torch.no_grad():
            q_comp = module.q_a_layernorm(module.q_a_proj(hidden))
            dsa_mask, _ = module._compute_dsa_mask(
                q_comp, hidden, cos, sin, mask, None, False
            )

        # dsa_mask: [B, 1, S, S]
        dsa_squeezed = dsa_mask.squeeze(1)  # [B, S, S]

        for t in range(S):
            available = t + 1  # positions 0..t are causally visible
            expected = min(CONFIG["index_topk"], available)
            # Count positions in causal range that are selected (mask == 0)
            row = dsa_squeezed[0, t, :available]
            num_selected = (row == 0.0).sum().item()
            assert num_selected == expected, (
                f"Position {t}: expected {expected} selected, got {num_selected}"
            )


class TestGradientFlow:
    def test_mla_parameters_receive_gradients(self):
        """MLA projection parameters must receive non-zero gradients.
        DSA indexer parameters don't receive gradients through discrete top-k,
        which is expected behavior."""
        torch.manual_seed(77)
        module = _load_module()

        B, S = 1, 8
        hidden = torch.randn(B, S, CONFIG["hidden_size"], requires_grad=True)
        pos_ids = torch.arange(S).unsqueeze(0)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        output, _ = module(hidden, pos_ids, cos, sin, attention_mask=mask)
        loss = output.sum()
        loss.backward()

        # Input must receive gradient
        assert hidden.grad is not None and hidden.grad.abs().sum() > 0, (
            "No gradient flowing to input"
        )

        # MLA projection parameters must receive gradients
        params_with_grad = 0
        for name, param in module.named_parameters():
            if param.grad is not None and param.grad.abs().sum() > 0:
                params_with_grad += 1

        # At least 7 parameter groups (all MLA projections + norms) should have gradients
        assert params_with_grad >= 7, (
            f"Only {params_with_grad} params got gradients, expected at least 7"
        )


class TestTrainingConvergence:
    def test_loss_decreases(self):
        """MSE loss must decrease over 10 Adam optimization steps,
        verifying the module supports end-to-end training."""
        torch.manual_seed(99)
        module = _load_module()
        module.train()

        B, S = 2, 10
        hidden = torch.randn(B, S, CONFIG["hidden_size"])
        target = torch.randn(B, S, CONFIG["hidden_size"])
        pos_ids = torch.arange(S).unsqueeze(0).expand(B, -1)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        optimizer = torch.optim.Adam(module.parameters(), lr=1e-3)

        losses = []
        for _ in range(10):
            optimizer.zero_grad()
            output, _ = module(hidden, pos_ids, cos, sin, attention_mask=mask)
            loss = F.mse_loss(output, target)
            loss.backward()
            optimizer.step()
            losses.append(loss.item())

        assert losses[-1] < losses[0] * 0.9, (
            f"Loss didn't decrease sufficiently: {losses[0]:.6f} -> {losses[-1]:.6f}"
        )


class TestTorchScriptExport:
    def test_traced_model_exists(self):
        """Traced model file must exist at the expected path."""
        assert os.path.exists("/app/mla_dsa_traced.pt"), (
            "Traced model not found at /app/mla_dsa_traced.pt"
        )

    def test_traced_model_produces_valid_output(self):
        """Traced model must load and produce finite output of correct shape."""
        torch.manual_seed(33)
        traced = torch.jit.load("/app/mla_dsa_traced.pt")

        B, S = 2, 16
        hidden = torch.randn(B, S, CONFIG["hidden_size"])
        pos_ids = torch.arange(S).unsqueeze(0).expand(B, -1)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        with torch.no_grad():
            result = traced(hidden, pos_ids, cos, sin, mask)

        # Handle both tuple and tensor returns from the traced model
        if isinstance(result, tuple):
            output = result[0]
        else:
            output = result

        assert output.shape == (B, S, CONFIG["hidden_size"]), (
            f"Traced output shape {output.shape} != expected {(B, S, CONFIG['hidden_size'])}"
        )
        assert torch.isfinite(output).all(), (
            "Traced model output contains non-finite values"
        )

    def test_traced_model_deterministic(self):
        """Traced model must be deterministic — same input yields same output."""
        torch.manual_seed(55)
        traced = torch.jit.load("/app/mla_dsa_traced.pt")

        B, S = 1, 12
        hidden = torch.randn(B, S, CONFIG["hidden_size"])
        pos_ids = torch.arange(S).unsqueeze(0)
        cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
        mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

        with torch.no_grad():
            r1 = traced(hidden, pos_ids, cos, sin, mask)
            r2 = traced(hidden, pos_ids, cos, sin, mask)

        o1 = r1[0] if isinstance(r1, tuple) else r1
        o2 = r2[0] if isinstance(r2, tuple) else r2

        assert torch.allclose(o1, o2), "Traced model is not deterministic"


class TestProfileTrace:
    def test_profile_trace_exists(self):
        """Chrome trace file must exist at the expected path."""
        assert os.path.exists("/app/profile_trace.json"), (
            "Profile trace not found at /app/profile_trace.json"
        )

    def test_profile_trace_valid_format(self):
        """Profile trace must be valid Chrome trace format with meaningful events."""
        with open("/app/profile_trace.json") as f:
            trace = json.load(f)

        assert "traceEvents" in trace, (
            "Profile trace missing 'traceEvents' — not a valid Chrome trace"
        )
        events = trace["traceEvents"]
        assert len(events) >= 10, (
            f"Profile trace has only {len(events)} events, expected >= 10 "
            "for profiling an attention module forward pass"
        )

        # Real torch.profiler traces contain events with category and phase fields
        events_with_cat = [
            e for e in events
            if isinstance(e, dict) and "cat" in e
        ]
        assert len(events_with_cat) > 0, (
            "Profile events missing 'cat' field — not a valid torch.profiler trace"
        )
