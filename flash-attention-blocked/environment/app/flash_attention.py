"""Memory-efficient attention module.

Must expose four functions backed by the C shared library:
  flash_attention_forward, flash_attention_causal_forward,
  flash_attention_backward, flash_attention_causal_backward

Q, K, V are 2D float64 NumPy arrays of shape (N, d).
"""


def flash_attention_forward(Q, K, V, block_size):
    raise NotImplementedError


def flash_attention_causal_forward(Q, K, V, block_size):
    raise NotImplementedError


def flash_attention_backward(Q, K, V, O, dO, L, block_size):
    raise NotImplementedError


def flash_attention_causal_backward(Q, K, V, O, dO, L, block_size):
    raise NotImplementedError
