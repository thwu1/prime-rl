#!/usr/bin/env python3
"""
Construct weight matrices for a 2-layer induction head circuit via
K-composition.

Head 1 (layer 1) — Previous-token head
  QK: Rotated sinusoidal positional encodings to attend to position i-1.
  OV: Copies content embedding (dims 0-7) to virtual subspace (dims 16-23).

Head 2 (layer 2) — Induction head via K-composition
  QK: Query reads content (dims 0-7), Key reads virtual (dims 16-23).
      After Head 1, virtual(j) = content(token_{j-1}), so Head 2 at
      position i attends to j where token_{j-1} == token_i.
  OV: Copies content (dims 0-7) of the attended token → dims 0-7 for
      unembedding.

"""

import numpy as np
import sys

sys.path.insert(0, '/app')
from transformer import (
    D_MODEL, D_HEAD, N_VOCAB, N_CTX,
    D_CONTENT, D_POS, D_VIRTUAL,
    POS_FREQS, make_content_embedding, transformer_forward,
)


def build_head1():
    """Previous-token head using sinusoidal rotation trick."""
    s = 3.0  # scale factor for sharp attention

    # ── W_K1: extract positional dims 8-15 ─────────────────────────
    W_K = np.zeros((D_HEAD, D_MODEL))
    for k in range(D_POS // 2):               # 4 frequency pairs
        W_K[2 * k,     D_CONTENT + 2 * k]     = s   # cos component
        W_K[2 * k + 1, D_CONTENT + 2 * k + 1] = s   # sin component

    # ── W_Q1: extract positional dims with rotation by -alpha_k ────
    #   This encodes "position i-1" so that Q_i · K_{i-1} is maximal.
    #
    #   cos(alpha*(i-1)) = cos(alpha)*cos(alpha*i) + sin(alpha)*sin(alpha*i)
    #   sin(alpha*(i-1)) = -sin(alpha)*cos(alpha*i) + cos(alpha)*sin(alpha*i)
    W_Q = np.zeros((D_HEAD, D_MODEL))
    for k, freq in enumerate(POS_FREQS):
        c  = np.cos(freq)
        sn = np.sin(freq)
        # row 2k:   cos component of rotated position
        W_Q[2 * k,     D_CONTENT + 2 * k]     = s * c
        W_Q[2 * k,     D_CONTENT + 2 * k + 1] = s * sn
        # row 2k+1: sin component of rotated position
        W_Q[2 * k + 1, D_CONTENT + 2 * k]     = -s * sn
        W_Q[2 * k + 1, D_CONTENT + 2 * k + 1] = s * c

    # ── W_V1: read content subspace (dims 0-7) ────────────────────
    W_V = np.zeros((D_HEAD, D_MODEL))
    for k in range(D_HEAD):
        W_V[k, k] = 1.0

    # ── W_O1: write to virtual subspace (dims 16-23) ──────────────
    W_O = np.zeros((D_MODEL, D_HEAD))
    for k in range(D_HEAD):
        W_O[D_CONTENT + D_POS + k, k] = 1.0

    return W_Q, W_K, W_V, W_O


def build_head2():
    """Induction head via K-composition with Head 1."""
    s = 5.0  # scale factor for sharp attention

    # ── W_Q2: read content subspace (dims 0-7) ────────────────────
    W_Q = np.zeros((D_HEAD, D_MODEL))
    for k in range(D_HEAD):
        W_Q[k, k] = s

    # ── W_K2: read virtual subspace (dims 16-23) ──────────────────
    #   After Head 1, virtual(j) = content(token_{j-1}).
    W_K = np.zeros((D_HEAD, D_MODEL))
    for k in range(D_HEAD):
        W_K[k, D_CONTENT + D_POS + k] = s

    # ── W_V2: read content subspace (dims 0-7) ────────────────────
    W_V = np.zeros((D_HEAD, D_MODEL))
    for k in range(D_HEAD):
        W_V[k, k] = 1.0

    # ── W_O2: write to content subspace (dims 0-7) ────────────────
    W_O = np.zeros((D_MODEL, D_HEAD))
    for k in range(D_HEAD):
        W_O[k, k] = 1.0

    return W_Q, W_K, W_V, W_O


def main():
    W_Q1, W_K1, W_V1, W_O1 = build_head1()
    W_Q2, W_K2, W_V2, W_O2 = build_head2()

    np.savez('/app/circuit_weights.npz',
             W_Q1=W_Q1, W_K1=W_K1, W_V1=W_V1, W_O1=W_O1,
             W_Q2=W_Q2, W_K2=W_K2, W_V2=W_V2, W_O2=W_O2)

    print("Weights saved to /app/circuit_weights.npz")

    # ── Quick verification ─────────────────────────────────────────
    w = dict(W_Q1=W_Q1, W_K1=W_K1, W_V1=W_V1, W_O1=W_O1,
             W_Q2=W_Q2, W_K2=W_K2, W_V2=W_V2, W_O2=W_O2)

    tokens = [0, 1, 2, 3, 5, 2, 3]
    logits, attn1, attn2 = transformer_forward(tokens, w)

    print("\nHead 1 attention (previous token):")
    for i in range(1, len(tokens)):
        best = int(np.argmax(attn1[i, :i + 1]))
        print(f"  pos {i} (tok {tokens[i]}): "
              f"attend pos {best}  weight={attn1[i, best]:.4f}")

    print("\nHead 2 attention (induction):")
    for i in range(1, len(tokens)):
        best = int(np.argmax(attn2[i, :i + 1]))
        print(f"  pos {i} (tok {tokens[i]}): "
              f"attend pos {best}  weight={attn2[i, best]:.4f}")

    print("\nLogits at pos 5 (second occurrence of token 2):")
    for k in range(N_VOCAB):
        print(f"  token {k}: {logits[5, k]:.4f}")
    print(f"  argmax = {int(np.argmax(logits[5]))}")


if __name__ == '__main__':
    main()
