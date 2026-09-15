"""
Tests for the GLM-5 Multi-Latent Attention implementation and deployment pipeline.

Verifies:
  - MLA implementation correctness (shapes, numerics, gradients, architecture)
  - KV cache equivalence for autoregressive decoding
  - C RoPE extension compilation, loading, and numerical correctness
  - ONNX export validity and inference equivalence
  - Full model integration and training convergence

"""

import os
import sys

sys.path.insert(0, "/app")

import torch
import torch.nn as nn

from glm5_config import GLM5Config
from utils import RotaryEmbedding, make_causal_mask, apply_rotary_pos_emb
from mla_attention import MLAttention
from model import SimpleGLM5

SEED = 42


def get_config():
    return GLM5Config()


def make_inputs(config, batch_size=2, seq_len=16):
    torch.manual_seed(SEED)
    hidden_states = torch.randn(batch_size, seq_len, config.hidden_size)
    rotary = RotaryEmbedding(config.qk_rope_head_dim, config.rope_theta)
    position_embeddings = rotary(hidden_states)
    attention_mask = make_causal_mask(
        seq_len, seq_len, hidden_states.dtype, hidden_states.device
    )
    return hidden_states, attention_mask, position_embeddings


# ------------------------------------------------------------------ #
#  Shape tests                                                        #
# ------------------------------------------------------------------ #


class TestMLAttentionShape:
    """Output and cache shapes must match specification."""

    def test_output_shape(self):
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        hidden, mask, pos_emb = make_inputs(config)
        output, _ = attn(hidden, attention_mask=mask, position_embeddings=pos_emb)
        assert output.shape == (2, 16, config.hidden_size), (
            f"Expected (2, 16, {config.hidden_size}), got {output.shape}"
        )

    def test_cache_none_when_not_requested(self):
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        hidden, mask, pos_emb = make_inputs(config)
        _, cache = attn(
            hidden, attention_mask=mask, position_embeddings=pos_emb, use_cache=False
        )
        assert cache is None

    def test_cache_key_shape(self):
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        hidden, mask, pos_emb = make_inputs(config)
        _, cache = attn(
            hidden, attention_mask=mask, position_embeddings=pos_emb, use_cache=True
        )
        assert cache is not None
        k_cached, _ = cache
        expected = (2, config.num_attention_heads, 16, config.qk_head_dim)
        assert k_cached.shape == expected, (
            f"Key cache: expected {expected}, got {k_cached.shape}"
        )

    def test_cache_value_shape(self):
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        hidden, mask, pos_emb = make_inputs(config)
        _, cache = attn(
            hidden, attention_mask=mask, position_embeddings=pos_emb, use_cache=True
        )
        _, v_cached = cache
        expected = (2, config.num_attention_heads, 16, config.v_head_dim)
        assert v_cached.shape == expected, (
            f"Value cache: expected {expected}, got {v_cached.shape}"
        )


# ------------------------------------------------------------------ #
#  Numerical sanity tests                                             #
# ------------------------------------------------------------------ #


class TestMLAttentionNumerics:
    """Outputs must be finite, non-trivial, and differentiable."""

    def test_output_finite(self):
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        hidden, mask, pos_emb = make_inputs(config)
        output, _ = attn(hidden, attention_mask=mask, position_embeddings=pos_emb)
        assert torch.isfinite(output).all(), "Output contains NaN or Inf"

    def test_output_not_zero(self):
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        hidden, mask, pos_emb = make_inputs(config)
        output, _ = attn(hidden, attention_mask=mask, position_embeddings=pos_emb)
        assert output.abs().sum() > 0, "Output is all zeros"

    def test_gradients_flow_to_all_parameters(self):
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        hidden, mask, pos_emb = make_inputs(config)
        hidden = hidden.clone().requires_grad_(True)
        output, _ = attn(hidden, attention_mask=mask, position_embeddings=pos_emb)
        output.sum().backward()
        for name, param in attn.named_parameters():
            assert param.grad is not None, f"No gradient for: {name}"
            assert torch.isfinite(param.grad).all(), (
                f"Non-finite gradient for: {name}"
            )

    def test_gradient_flows_to_input(self):
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        hidden, mask, pos_emb = make_inputs(config)
        hidden = hidden.clone().requires_grad_(True)
        output, _ = attn(hidden, attention_mask=mask, position_embeddings=pos_emb)
        output.sum().backward()
        assert hidden.grad is not None, "No gradient for input hidden_states"


# ------------------------------------------------------------------ #
#  Architecture tests                                                 #
# ------------------------------------------------------------------ #


class TestMLAttentionArchitecture:
    """Parameter shapes must reflect MLA's LoRA compression design."""

    def test_parameter_count_range(self):
        """MLA param count should differ from standard 4*H^2 MHA."""
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        total = sum(p.numel() for p in attn.parameters())
        # Expected ~180k.  Standard MHA 4*256^2 = 262144.
        assert 150_000 < total < 250_000, (
            f"Param count {total} outside expected MLA range"
        )

    def test_has_query_compression(self):
        """Must have Linear(hidden_size, q_lora_rank)."""
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        shapes = {tuple(p.shape) for p in attn.parameters()}
        assert (config.q_lora_rank, config.hidden_size) in shapes, (
            f"Missing query compression [{config.hidden_size} -> {config.q_lora_rank}]"
        )

    def test_has_query_expansion(self):
        """Must have Linear(q_lora_rank, num_heads * qk_head_dim)."""
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        shapes = {tuple(p.shape) for p in attn.parameters()}
        out_dim = config.num_attention_heads * config.qk_head_dim
        assert (out_dim, config.q_lora_rank) in shapes, (
            f"Missing query expansion [{config.q_lora_rank} -> {out_dim}]"
        )

    def test_has_kv_compression(self):
        """Must have Linear(hidden_size, kv_lora_rank + qk_rope_head_dim)."""
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        shapes = {tuple(p.shape) for p in attn.parameters()}
        out_dim = config.kv_lora_rank + config.qk_rope_head_dim
        assert (out_dim, config.hidden_size) in shapes, (
            f"Missing KV compression [{config.hidden_size} -> {out_dim}]"
        )

    def test_has_kv_expansion(self):
        """Must have Linear(kv_lora_rank, num_heads * (qk_nope_head_dim + v_head_dim))."""
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        shapes = {tuple(p.shape) for p in attn.parameters()}
        out_dim = config.num_attention_heads * (
            config.qk_nope_head_dim + config.v_head_dim
        )
        assert (out_dim, config.kv_lora_rank) in shapes, (
            f"Missing KV expansion [{config.kv_lora_rank} -> {out_dim}]"
        )


# ------------------------------------------------------------------ #
#  KV-cache tests                                                     #
# ------------------------------------------------------------------ #


class TestKVCache:
    """KV cache must produce identical outputs to full forward."""

    def test_cache_equivalence(self):
        """Prefill + step-by-step decode must match full forward at each position."""
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        attn.eval()

        B, S = 1, 12
        torch.manual_seed(SEED + 1)
        hidden_full = torch.randn(B, S, config.hidden_size)
        rotary = RotaryEmbedding(config.qk_rope_head_dim, config.rope_theta)

        with torch.no_grad():
            # Full forward
            pos_full = rotary(hidden_full)
            mask_full = make_causal_mask(S, S, hidden_full.dtype, hidden_full.device)
            output_full, _ = attn(
                hidden_full, attention_mask=mask_full, position_embeddings=pos_full
            )

            # Prefill first 8 tokens
            prefill_len = 8
            hidden_pre = hidden_full[:, :prefill_len]
            pos_ids_pre = torch.arange(prefill_len).unsqueeze(0)
            pos_pre = rotary(hidden_pre, pos_ids_pre)
            mask_pre = make_causal_mask(
                prefill_len, prefill_len, hidden_pre.dtype, hidden_pre.device
            )
            _, cache = attn(
                hidden_pre,
                attention_mask=mask_pre,
                position_embeddings=pos_pre,
                use_cache=True,
            )

            # Decode remaining tokens one at a time
            for t in range(prefill_len, S):
                hidden_t = hidden_full[:, t : t + 1]
                past_len = cache[0].shape[2]
                pos_t = rotary(hidden_t, torch.tensor([[t]]))
                mask_t = make_causal_mask(
                    1, past_len + 1, hidden_t.dtype, hidden_t.device
                )
                output_t, cache = attn(
                    hidden_t,
                    attention_mask=mask_t,
                    position_embeddings=pos_t,
                    past_key_value=cache,
                    use_cache=True,
                )
                torch.testing.assert_close(
                    output_t[:, 0],
                    output_full[:, t],
                    atol=1e-5,
                    rtol=1e-5,
                    msg=f"Cache mismatch at position {t}",
                )

    def test_cache_grows_each_step(self):
        """Cache length must increase by exactly 1 per decode step."""
        config = get_config()
        torch.manual_seed(SEED)
        attn = MLAttention(config, layer_idx=0)
        attn.eval()

        B = 1
        torch.manual_seed(SEED + 2)
        hidden_init = torch.randn(B, 4, config.hidden_size)
        rotary = RotaryEmbedding(config.qk_rope_head_dim, config.rope_theta)

        with torch.no_grad():
            pos = rotary(hidden_init)
            mask = make_causal_mask(4, 4, hidden_init.dtype, hidden_init.device)
            _, cache = attn(
                hidden_init,
                attention_mask=mask,
                position_embeddings=pos,
                use_cache=True,
            )
            assert cache[0].shape[2] == 4

            for step in range(1, 11):
                hidden_t = torch.randn(B, 1, config.hidden_size)
                past_len = cache[0].shape[2]
                pos_t = rotary(hidden_t, torch.tensor([[past_len]]))
                mask_t = make_causal_mask(
                    1, past_len + 1, hidden_t.dtype, hidden_t.device
                )
                _, cache = attn(
                    hidden_t,
                    attention_mask=mask_t,
                    position_embeddings=pos_t,
                    past_key_value=cache,
                    use_cache=True,
                )
                expected = 4 + step
                assert cache[0].shape[2] == expected, (
                    f"Step {step}: cache length {cache[0].shape[2]}, expected {expected}"
                )


# ------------------------------------------------------------------ #
#  Full-model integration tests                                       #
# ------------------------------------------------------------------ #


class TestModelIntegration:
    """End-to-end tests with the SimpleGLM5 wrapper."""

    def test_model_forward_shapes(self):
        config = get_config()
        torch.manual_seed(SEED)
        model = SimpleGLM5(config)
        ids = torch.randint(0, config.vocab_size, (2, 16))
        loss, logits, _ = model(ids, labels=ids)
        assert logits.shape == (2, 16, config.vocab_size)
        assert loss is not None
        assert torch.isfinite(loss)

    def test_training_convergence(self):
        """Loss must drop by >= 50 % over 20 AdamW steps."""
        config = get_config()
        torch.manual_seed(SEED)
        model = SimpleGLM5(config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)

        torch.manual_seed(SEED + 10)
        ids = torch.randint(0, config.vocab_size, (4, 32))

        losses = []
        for _ in range(20):
            optimizer.zero_grad()
            loss, _, _ = model(ids, labels=ids)
            loss.backward()
            optimizer.step()
            losses.append(loss.item())

        assert losses[-1] < losses[0] * 0.5, (
            f"Insufficient convergence: {losses[0]:.4f} -> {losses[-1]:.4f}"
        )

    def test_autoregressive_generation(self):
        """Model must support multi-step KV-cached generation."""
        config = get_config()
        torch.manual_seed(SEED)
        model = SimpleGLM5(config)
        model.eval()

        ids = torch.randint(0, config.vocab_size, (1, 8))
        with torch.no_grad():
            _, logits, caches = model(ids, use_cache=True)
            for _ in range(10):
                next_tok = logits[:, -1:].argmax(dim=-1)
                _, logits, caches = model(
                    next_tok, past_key_values=caches, use_cache=True
                )
                assert logits.shape == (1, 1, config.vocab_size)


# ------------------------------------------------------------------ #
#  C RoPE extension tests                                             #
# ------------------------------------------------------------------ #


class TestCRoPEExtension:
    """Fused RoPE C library must compile, load, and compute correctly."""

    def test_shared_library_exists(self):
        """librope.so must exist at /app/lib/librope.so."""
        assert os.path.isfile("/app/lib/librope.so"), (
            "librope.so not found at /app/lib/librope.so — run 'make -C /app build'"
        )

    def test_library_loads_via_ctypes(self):
        """Must load via ctypes and export required symbols."""
        import ctypes
        lib = ctypes.cdll.LoadLibrary("/app/lib/librope.so")
        assert hasattr(lib, "rope_apply"), "Missing symbol: rope_apply"
        assert hasattr(lib, "rope_apply_batch"), "Missing symbol: rope_apply_batch"

    def test_rope_apply_single_vector(self):
        """C rope_apply must match PyTorch apply_rotary_pos_emb for a single vector."""
        import ctypes
        import numpy as np

        lib = ctypes.cdll.LoadLibrary("/app/lib/librope.so")

        dim = 16
        np.random.seed(SEED)
        x = np.random.randn(dim).astype(np.float32)
        cos_vals = np.random.randn(dim).astype(np.float32)
        sin_vals = np.random.randn(dim).astype(np.float32)
        out = np.zeros(dim, dtype=np.float32)

        c_float_p = ctypes.POINTER(ctypes.c_float)
        lib.rope_apply(
            x.ctypes.data_as(c_float_p),
            cos_vals.ctypes.data_as(c_float_p),
            sin_vals.ctypes.data_as(c_float_p),
            ctypes.c_int(dim),
            out.ctypes.data_as(c_float_p),
        )

        # Compute reference using PyTorch's rotate_half + apply formula
        x_t = torch.from_numpy(x.copy())
        cos_t = torch.from_numpy(cos_vals.copy())
        sin_t = torch.from_numpy(sin_vals.copy())

        half = dim // 2
        rotate_half_x = torch.cat([-x_t[half:], x_t[:half]])
        expected = (x_t * cos_t + rotate_half_x * sin_t).numpy()

        np.testing.assert_allclose(out, expected, atol=1e-5, rtol=1e-5)

    def test_rope_apply_batch_consistency(self):
        """Batched C rope_apply_batch must match per-element rope_apply."""
        import ctypes
        import numpy as np

        lib = ctypes.cdll.LoadLibrary("/app/lib/librope.so")

        batch_size = 4
        dim = 16
        np.random.seed(SEED + 100)
        x = np.random.randn(batch_size * dim).astype(np.float32)
        cos_vals = np.random.randn(batch_size * dim).astype(np.float32)
        sin_vals = np.random.randn(batch_size * dim).astype(np.float32)
        out_batch = np.zeros(batch_size * dim, dtype=np.float32)

        c_float_p = ctypes.POINTER(ctypes.c_float)
        lib.rope_apply_batch(
            x.ctypes.data_as(c_float_p),
            cos_vals.ctypes.data_as(c_float_p),
            sin_vals.ctypes.data_as(c_float_p),
            ctypes.c_int(batch_size),
            ctypes.c_int(dim),
            out_batch.ctypes.data_as(c_float_p),
        )

        # Compare with single-element calls
        out_single = np.zeros(batch_size * dim, dtype=np.float32)
        for i in range(batch_size):
            s, e = i * dim, (i + 1) * dim
            xi = x[s:e].copy()
            ci = cos_vals[s:e].copy()
            si = sin_vals[s:e].copy()
            oi = np.zeros(dim, dtype=np.float32)
            lib.rope_apply(
                xi.ctypes.data_as(c_float_p),
                ci.ctypes.data_as(c_float_p),
                si.ctypes.data_as(c_float_p),
                ctypes.c_int(dim),
                oi.ctypes.data_as(c_float_p),
            )
            out_single[s:e] = oi

        np.testing.assert_allclose(out_batch, out_single, atol=1e-6, rtol=1e-6)

    def test_rope_apply_in_place(self):
        """rope_apply must handle the case where out aliases x (in-place)."""
        import ctypes
        import numpy as np

        lib = ctypes.cdll.LoadLibrary("/app/lib/librope.so")

        dim = 16
        np.random.seed(SEED + 200)
        x = np.random.randn(dim).astype(np.float32)
        cos_vals = np.random.randn(dim).astype(np.float32)
        sin_vals = np.random.randn(dim).astype(np.float32)

        # Compute expected result with separate output
        out_separate = np.zeros(dim, dtype=np.float32)
        c_float_p = ctypes.POINTER(ctypes.c_float)
        lib.rope_apply(
            x.ctypes.data_as(c_float_p),
            cos_vals.ctypes.data_as(c_float_p),
            sin_vals.ctypes.data_as(c_float_p),
            ctypes.c_int(dim),
            out_separate.ctypes.data_as(c_float_p),
        )

        # Now do in-place (out = x)
        x_inplace = x.copy()
        lib.rope_apply(
            x_inplace.ctypes.data_as(c_float_p),
            cos_vals.ctypes.data_as(c_float_p),
            sin_vals.ctypes.data_as(c_float_p),
            ctypes.c_int(dim),
            x_inplace.ctypes.data_as(c_float_p),
        )

        np.testing.assert_allclose(x_inplace, out_separate, atol=1e-6, rtol=1e-6)


# ------------------------------------------------------------------ #
#  ONNX export tests                                                  #
# ------------------------------------------------------------------ #


class TestONNXExport:
    """ONNX model must be valid, support dynamic shapes, and match PyTorch."""

    def test_onnx_file_exists(self):
        """model.onnx must exist at /app/model.onnx."""
        assert os.path.isfile("/app/model.onnx"), (
            "model.onnx not found — run python3 /app/export_onnx.py"
        )

    def test_weights_file_exists(self):
        """model_weights.pt must exist for verification."""
        assert os.path.isfile("/app/model_weights.pt"), (
            "model_weights.pt not found — export_onnx.py must save weights"
        )

    def test_onnx_passes_checker(self):
        """ONNX model must pass onnx.checker.check_model validation."""
        import onnx
        model = onnx.load("/app/model.onnx")
        onnx.checker.check_model(model)

    def test_onnx_has_correct_io_names(self):
        """Model must have input 'input_ids' and output 'logits'."""
        import onnx
        model = onnx.load("/app/model.onnx")
        input_names = [inp.name for inp in model.graph.input]
        output_names = [out.name for out in model.graph.output]
        assert "input_ids" in input_names, f"Expected 'input_ids' in inputs, got {input_names}"
        assert "logits" in output_names, f"Expected 'logits' in outputs, got {output_names}"

    def test_onnx_dynamic_batch(self):
        """Must support variable batch sizes via onnxruntime."""
        import onnxruntime as ort
        import numpy as np

        session = ort.InferenceSession("/app/model.onnx")
        config = get_config()

        # batch=1
        ids1 = np.random.randint(0, config.vocab_size, (1, 8)).astype(np.int64)
        result1 = session.run(None, {"input_ids": ids1})
        assert result1[0].shape == (1, 8, config.vocab_size), (
            f"batch=1 shape mismatch: {result1[0].shape}"
        )

        # batch=3
        ids3 = np.random.randint(0, config.vocab_size, (3, 8)).astype(np.int64)
        result3 = session.run(None, {"input_ids": ids3})
        assert result3[0].shape == (3, 8, config.vocab_size), (
            f"batch=3 shape mismatch: {result3[0].shape}"
        )

    def test_onnx_dynamic_sequence(self):
        """Must support variable sequence lengths via onnxruntime."""
        import onnxruntime as ort
        import numpy as np

        session = ort.InferenceSession("/app/model.onnx")
        config = get_config()

        for seq_len in [4, 12, 20]:
            ids = np.random.randint(0, config.vocab_size, (1, seq_len)).astype(np.int64)
            result = session.run(None, {"input_ids": ids})
            assert result[0].shape == (1, seq_len, config.vocab_size), (
                f"seq={seq_len} shape mismatch: {result[0].shape}"
            )

    def test_onnx_matches_pytorch(self):
        """ONNX inference must match PyTorch within 1e-4 tolerance."""
        import onnxruntime as ort
        import numpy as np

        session = ort.InferenceSession("/app/model.onnx")

        config = get_config()
        torch.manual_seed(SEED)
        model = SimpleGLM5(config)
        weights = torch.load("/app/model_weights.pt", weights_only=True)
        model.load_state_dict(weights)
        model.eval()

        ids = np.array([[1, 2, 3, 4, 5, 6, 7, 8]], dtype=np.int64)
        with torch.no_grad():
            _, logits_pt, _ = model(torch.from_numpy(ids))

        logits_onnx = session.run(None, {"input_ids": ids})[0]

        np.testing.assert_allclose(
            logits_pt.numpy(), logits_onnx, atol=1e-4, rtol=1e-4
        )
