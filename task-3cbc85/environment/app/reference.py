"""Reference implementation for scaled dot-product attention."""

import numpy as np


def scaled_dot_product_attention(Q, K, V, n_valid):
    """Scaled dot-product attention with causal masking.

    Args:
        Q: query vector (d_k,)
        K: key cache (seq_len, d_k)
        V: value cache (seq_len, d_k)
        n_valid: number of valid positions (causal mask zeros out i >= n_valid)

    Returns:
        output vector (d_k,)
    """
    d_k = len(Q)
    scores = K @ Q / np.sqrt(d_k)
    scores[n_valid:] = float('-inf')
    m = np.max(scores)
    exp_scores = np.exp(scores - m)
    attn = exp_scores / np.sum(exp_scores)
    return attn @ V
