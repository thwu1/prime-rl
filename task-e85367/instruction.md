Implement the `MLAWithDSA` module at `/app/mla_dsa_attention.py`. This is an attention mechanism from the GLM-5 mixture-of-experts transformer architecture (released February 2026). You must research the architecture and deduce the correct internal data flow from the provided class skeleton, configuration parameters, and any available online resources.

## Starting Environment

Files in `/app/`:
- `config.py` — model configuration with all dimension and hyperparameters
- `utils.py` — provided utilities (`RMSNorm`, `apply_rotary_pos_emb`, `compute_rope_embeddings`, `make_causal_mask`); do not modify
- `skeleton.py` — class skeleton defining the complete module interface: required `nn.Linear` and `RMSNorm` attributes with exact names and shapes, `forward()` and `_compute_dsa_mask()` method signatures with parameter/return specifications, and KV cache dict schema

Your implementation must conform to the skeleton's interface exactly — all attribute names, method signatures, and documented parameter semantics.

## Required Behavior

1. **Output shape**: `forward()` returns `(output, past_key_values)` where `output` has shape `[B, S, hidden_size]` for any batch size B and sequence length S >= 1 (including S=1 single-token decode).

2. **KV cache consistency**: When `use_cache=True`, token-by-token autoregressive decoding must produce outputs matching a single full-sequence forward pass within atol=1e-4. The returned `past_key_values` dict must use keys `"key"`, `"value"`, and `"idx_key"`, with their time dimensions growing by exactly 1 each decode step.

3. **Causal masking**: Modifying a token at position t must not change any output at positions < t.

4. **Sparse selection**: `_compute_dsa_mask()` must select exactly `min(index_topk, causally_available_positions)` key positions per query position. Selected positions have mask value 0.0; unselected positions have -inf.

5. **Differentiability**: At least 7 named parameters must receive non-zero gradients through backpropagation on a sum-of-outputs loss.

6. **Training**: MSE loss against a random target must decrease by >= 10% over 10 Adam steps at lr=1e-3.

## Deliverables

1. `/app/mla_dsa_attention.py` — Complete `MLAWithDSA` class implementation.

2. `/app/mla_dsa_traced.pt` — TorchScript model of the prefill forward path (without KV cache). Must load via `torch.jit.load()`, accept exactly five positional arguments `(hidden_states, position_ids, cos, sin, attention_mask)`, and return finite deterministic outputs of shape `[B, S, hidden_size]`.

3. `/app/profile_trace.json` — Chrome-trace-format JSON from profiling the module's forward pass. Must contain a `"traceEvents"` array with >= 10 event objects, where events include a `"cat"` field.