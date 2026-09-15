
"""
Flash Attention Implementation — Complete Solution

Implements blocked forward and backward passes with online softmax
for both causal and non-causal attention.
"""

import numpy as np


def flash_attention_forward(Q, K, V, block_size):
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)
    O = np.zeros((N, d), dtype=np.float64)
    L = np.zeros(N, dtype=np.float64)
    num_blocks = (N + block_size - 1) // block_size

    for i in range(num_blocks):
        i_s = i * block_size
        i_e = min(i_s + block_size, N)
        qi = Q[i_s:i_e]
        br = i_e - i_s

        mi = np.full(br, -np.inf, dtype=np.float64)
        li = np.zeros(br, dtype=np.float64)
        acc = np.zeros((br, d), dtype=np.float64)

        for j in range(num_blocks):
            j_s = j * block_size
            j_e = min(j_s + block_size, N)
            kj = K[j_s:j_e]
            vj = V[j_s:j_e]

            sij = qi @ kj.T * scale
            mij = np.max(sij, axis=1)
            pij = np.exp(sij - mij[:, None])
            lij = np.sum(pij, axis=1)

            mi_new = np.maximum(mi, mij)
            alpha = np.exp(mi - mi_new)
            beta = np.exp(mij - mi_new)
            li_new = li * alpha + lij * beta

            acc = alpha[:, None] * acc + beta[:, None] * (pij @ vj)
            mi = mi_new
            li = li_new

        O[i_s:i_e] = acc / li[:, None]
        L[i_s:i_e] = mi + np.log(li)

    return O, L


def flash_attention_causal_forward(Q, K, V, block_size):
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)
    O = np.zeros((N, d), dtype=np.float64)
    L = np.zeros(N, dtype=np.float64)
    num_blocks = (N + block_size - 1) // block_size

    for i in range(num_blocks):
        i_s = i * block_size
        i_e = min(i_s + block_size, N)
        qi = Q[i_s:i_e]
        br = i_e - i_s

        mi = np.full(br, -np.inf, dtype=np.float64)
        li = np.zeros(br, dtype=np.float64)
        acc = np.zeros((br, d), dtype=np.float64)

        for j in range(i + 1):
            j_s = j * block_size
            j_e = min(j_s + block_size, N)
            kj = K[j_s:j_e]
            vj = V[j_s:j_e]

            sij = qi @ kj.T * scale

            if i == j:
                rows = np.arange(i_s, i_e)
                cols = np.arange(j_s, j_e)
                causal_mask = rows[:, None] < cols[None, :]
                sij = np.where(causal_mask, -np.inf, sij)

            mij = np.max(sij, axis=1)
            pij = np.exp(sij - mij[:, None])
            lij = np.sum(pij, axis=1)

            mi_new = np.maximum(mi, mij)
            alpha = np.exp(mi - mi_new)
            beta = np.exp(mij - mi_new)
            li_new = li * alpha + lij * beta

            acc = alpha[:, None] * acc + beta[:, None] * (pij @ vj)
            mi = mi_new
            li = li_new

        O[i_s:i_e] = acc / li[:, None]
        L[i_s:i_e] = mi + np.log(li)

    return O, L


def flash_attention_backward(Q, K, V, O, dO, L, block_size):
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)

    dQ = np.zeros_like(Q, dtype=np.float64)
    dK = np.zeros_like(K, dtype=np.float64)
    dV = np.zeros_like(V, dtype=np.float64)

    D = np.sum(dO * O, axis=1)

    num_blocks = (N + block_size - 1) // block_size

    for i in range(num_blocks):
        i_s = i * block_size
        i_e = min(i_s + block_size, N)
        qi = Q[i_s:i_e]
        doi = dO[i_s:i_e]
        li = L[i_s:i_e]
        di = D[i_s:i_e]

        dqi = np.zeros_like(qi, dtype=np.float64)

        for j in range(num_blocks):
            j_s = j * block_size
            j_e = min(j_s + block_size, N)
            kj = K[j_s:j_e]
            vj = V[j_s:j_e]

            sij = qi @ kj.T * scale
            pij = np.exp(sij - li[:, None])

            dV[j_s:j_e] += pij.T @ doi

            dpij = doi @ vj.T
            dsij = pij * (dpij - di[:, None])

            dqi += dsij @ kj * scale
            dK[j_s:j_e] += dsij.T @ qi * scale

        dQ[i_s:i_e] = dqi

    return dQ, dK, dV


def flash_attention_causal_backward(Q, K, V, O, dO, L, block_size):
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)

    dQ = np.zeros_like(Q, dtype=np.float64)
    dK = np.zeros_like(K, dtype=np.float64)
    dV = np.zeros_like(V, dtype=np.float64)

    D = np.sum(dO * O, axis=1)

    num_blocks = (N + block_size - 1) // block_size

    for i in range(num_blocks):
        i_s = i * block_size
        i_e = min(i_s + block_size, N)
        qi = Q[i_s:i_e]
        doi = dO[i_s:i_e]
        li = L[i_s:i_e]
        di = D[i_s:i_e]

        dqi = np.zeros_like(qi, dtype=np.float64)

        for j in range(i + 1):
            j_s = j * block_size
            j_e = min(j_s + block_size, N)
            kj = K[j_s:j_e]
            vj = V[j_s:j_e]

            sij = qi @ kj.T * scale

            if i == j:
                rows = np.arange(i_s, i_e)
                cols = np.arange(j_s, j_e)
                causal_mask = rows[:, None] < cols[None, :]
                sij = np.where(causal_mask, -np.inf, sij)

            pij = np.exp(sij - li[:, None])

            dV[j_s:j_e] += pij.T @ doi

            dpij = doi @ vj.T
            dsij = pij * (dpij - di[:, None])

            dqi += dsij @ kj * scale
            dK[j_s:j_e] += dsij.T @ qi * scale

        dQ[i_s:i_e] = dqi

    return dQ, dK, dV
