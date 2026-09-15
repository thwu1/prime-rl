"""Memory-efficient attention module backed by C shared library."""
import attention


def flash_attention_forward(Q, K, V, block_size):
    return attention.forward(Q, K, V, block_size)


def flash_attention_causal_forward(Q, K, V, block_size):
    return attention.causal_forward(Q, K, V, block_size)


def flash_attention_backward(Q, K, V, O, dO, L, block_size):
    return attention.backward(Q, K, V, O, dO, L, block_size)


def flash_attention_causal_backward(Q, K, V, O, dO, L, block_size):
    return attention.causal_backward(Q, K, V, O, dO, L, block_size)
