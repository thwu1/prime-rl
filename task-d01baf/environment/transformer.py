"""
Attention-only transformer framework for the induction head circuit task.

Architecture
------------
- d_model = 32  (residual stream dimension)
- d_head  = 8   (attention head dimension)
- n_vocab = 8   (vocabulary size, tokens 0-7)
- n_ctx   = 16  (maximum context length)
- 2 layers, 1 attention head per layer, no MLP

Residual stream subspace layout
-------------------------------
- Dimensions  0-7 :  Content subspace  (token identity)
- Dimensions  8-15:  Positional subspace (sinusoidal encoding)
- Dimensions 16-23:  Virtual subspace   (inter-head communication channel)
- Dimensions 24-31:  Unused

Embeddings
----------
- Content embedding W_E : 8x8 orthogonal matrix (seed=42), placed in dims 0-7.
- Positional encoding   : sinusoidal with frequencies
      alpha_k = 2*pi*(k+1) / n_ctx,  k = 0,1,2,3
  placed in dims 8-15 as [cos(a0*p), sin(a0*p), cos(a1*p), sin(a1*p), ...].
- Unembedding W_U       : reads content subspace (dims 0-7), same basis as W_E.

Weight matrices (to be constructed and saved as /app/circuit_weights.npz)
-------------------------------------------------------------------------
Keys in the .npz file:
  W_Q1, W_K1, W_V1, W_O1  -- Head 1 (layer 1)
  W_Q2, W_K2, W_V2, W_O2  -- Head 2 (layer 2)

Shapes:
  W_Q, W_K, W_V : (D_HEAD, D_MODEL) = (8, 32)
  W_O           : (D_MODEL, D_HEAD) = (32, 8)

Composite matrices:
  W_OV = W_O @ W_V          (D_MODEL, D_MODEL)  -- what is read & where it is written
  W_QK = W_Q.T @ W_K        (D_MODEL, D_MODEL)  -- which tokens attend to which
"""

import numpy as np

# ── Architecture constants ─────────────────────────────────────────────
D_MODEL   = 32
D_HEAD    = 8
N_VOCAB   = 8
N_CTX     = 16
D_CONTENT = 8    # dims 0-7
D_POS     = 8    # dims 8-15
D_VIRTUAL = 8    # dims 16-23

# Positional encoding frequencies (4 pairs of cos/sin)
POS_FREQS = [2.0 * np.pi * (k + 1) / N_CTX for k in range(D_POS // 2)]


# ── Embedding helpers ──────────────────────────────────────────────────
def make_content_embedding(seed=42):
    """8x8 orthogonal matrix: row k = content direction for token k."""
    rng = np.random.RandomState(seed)
    M = rng.randn(D_CONTENT, D_CONTENT)
    Q, _ = np.linalg.qr(M)
    return Q  # (N_VOCAB, D_CONTENT)


def make_positional_encoding():
    """(N_CTX, D_POS) sinusoidal positional encoding matrix."""
    pos_embed = np.zeros((N_CTX, D_POS))
    for p in range(N_CTX):
        for k, freq in enumerate(POS_FREQS):
            pos_embed[p, 2 * k]     = np.cos(freq * p)
            pos_embed[p, 2 * k + 1] = np.sin(freq * p)
    return pos_embed


def make_embeddings():
    """
    Returns
    -------
    W_E   : (N_VOCAB, D_MODEL)  token embedding
    W_pos : (N_CTX,   D_MODEL)  positional encoding
    W_U   : (N_VOCAB, D_MODEL)  unembedding (reads content subspace)
    """
    content = make_content_embedding()       # (8, 8)
    pos     = make_positional_encoding()     # (16, 8)

    W_E = np.zeros((N_VOCAB, D_MODEL))
    W_E[:, :D_CONTENT] = content

    W_pos = np.zeros((N_CTX, D_MODEL))
    W_pos[:, D_CONTENT:D_CONTENT + D_POS] = pos

    W_U = np.zeros((N_VOCAB, D_MODEL))
    W_U[:, :D_CONTENT] = content

    return W_E, W_pos, W_U


# ── Forward pass ───────────────────────────────────────────────────────
def attention_forward(x, W_Q, W_K, W_V, W_O):
    """
    Single attention head with causal masking.

    Parameters
    ----------
    x   : (seq_len, D_MODEL)
    W_Q : (D_HEAD,  D_MODEL)
    W_K : (D_HEAD,  D_MODEL)
    W_V : (D_HEAD,  D_MODEL)
    W_O : (D_MODEL, D_HEAD)

    Returns
    -------
    output : (seq_len, D_MODEL)
    attn   : (seq_len, seq_len)  attention pattern
    """
    seq_len = x.shape[0]

    Q = x @ W_Q.T                           # (seq_len, D_HEAD)
    K = x @ W_K.T
    V = x @ W_V.T

    scores = Q @ K.T / np.sqrt(D_HEAD)      # (seq_len, seq_len)

    # causal mask
    mask = np.triu(np.ones((seq_len, seq_len), dtype=bool), k=1)
    scores[mask] = -1e9

    # softmax
    exp_s = np.exp(scores - scores.max(axis=-1, keepdims=True))
    attn  = exp_s / exp_s.sum(axis=-1, keepdims=True)

    result = attn @ V                        # (seq_len, D_HEAD)
    output = result @ W_O.T                  # (seq_len, D_MODEL)
    return output, attn


def transformer_forward(tokens, weights):
    """
    Full 2-layer attention-only transformer forward pass.

    Parameters
    ----------
    tokens  : list[int]  token ids, each in [0, N_VOCAB)
    weights : dict       keys W_Q1..W_O1, W_Q2..W_O2

    Returns
    -------
    logits : (seq_len, N_VOCAB)
    attn1  : (seq_len, seq_len)
    attn2  : (seq_len, seq_len)
    """
    W_E, W_pos, W_U = make_embeddings()
    seq_len = len(tokens)

    # embed
    x = np.zeros((seq_len, D_MODEL))
    for i, tok in enumerate(tokens):
        x[i] = W_E[tok] + W_pos[i]

    # layer 1
    out1, attn1 = attention_forward(
        x, weights['W_Q1'], weights['W_K1'],
        weights['W_V1'], weights['W_O1'])
    x = x + out1

    # layer 2
    out2, attn2 = attention_forward(
        x, weights['W_Q2'], weights['W_K2'],
        weights['W_V2'], weights['W_O2'])
    x = x + out2

    # unembed
    logits = x @ W_U.T                      # (seq_len, N_VOCAB)
    return logits, attn1, attn2


def load_weights(path='/app/circuit_weights.npz'):
    """Load weight matrices from an .npz file."""
    data = np.load(path)
    return {k: data[k] for k in data.files}


# ── Self-test ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("Transformer framework loaded.")
    print(f"  d_model={D_MODEL}  d_head={D_HEAD}  "
          f"n_vocab={N_VOCAB}  n_ctx={N_CTX}")
    print(f"  Positional frequencies: "
          f"{[round(f, 4) for f in POS_FREQS]}")

    W_E, W_pos, W_U = make_embeddings()
    print(f"  W_E  shape: {W_E.shape}")
    print(f"  W_pos shape: {W_pos.shape}")
    print(f"  W_U  shape: {W_U.shape}")

    # verify orthogonality
    C = make_content_embedding()
    gram = C @ C.T
    assert np.allclose(gram, np.eye(N_VOCAB), atol=1e-12), \
        "Content embedding is not orthogonal!"
    print("  Content embedding orthogonality verified.")
    print("\nFramework ready.  "
          "Create /app/circuit_weights.npz with weight matrices.")
