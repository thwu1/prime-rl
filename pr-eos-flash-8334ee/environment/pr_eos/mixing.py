"""Van der Waals one-fluid mixing rules for PR EOS.

"""
import math
from .pure import pr_pure_a_alpha_b


def mix_params(T, Tcs, Pcs, omegas, zs, kijs):
    """Compute mixture a_alpha, b, cross-term matrix, and pure b values."""
    N = len(zs)
    a_alphas_pure = []
    bs = []
    for i in range(N):
        aa_i, b_i = pr_pure_a_alpha_b(Tcs[i], Pcs[i], omegas[i], T)
        a_alphas_pure.append(aa_i)
        bs.append(b_i)

    # Cross a_alpha with binary interaction parameters
    a_alpha_ijs = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(i, N):
            val = math.sqrt(a_alphas_pure[i] * a_alphas_pure[j]) * (1.0 + kijs[i][j])
            a_alpha_ijs[i][j] = val
            a_alpha_ijs[j][i] = val

    a_alpha_mix = sum(
        zs[i] * zs[j] * a_alpha_ijs[i][j]
        for i in range(N) for j in range(N)
    )

    b_mix = sum(zs[i] * bs[i] for i in range(N))

    return a_alpha_mix, b_mix, a_alpha_ijs, bs
