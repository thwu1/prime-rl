"""LABS energy function, autocorrelation, merit factor, and incremental updates."""


def autocorrelation(s, k):
    """Compute autocorrelation coefficient C_k = sum_{i=0}^{N-1-k} s[i]*s[i+k]."""
    N = len(s)
    return sum(s[i] * s[i + k] for i in range(N - k))


def energy(s):
    """Compute LABS energy E(s) = sum_{k=1}^{N-1} C_k^2."""
    N = len(s)
    return sum(autocorrelation(s, k) ** 2 for k in range(1, N))


def merit_factor(s):
    """Compute merit factor F(s) = N^2 / (2*E(s))."""
    E = energy(s)
    if E == 0:
        return float("inf")
    N = len(s)
    return N * N / (2.0 * E)


def energy_change_on_flip(s, j, C):
    """Compute change in energy when flipping position j.

    Args:
        s: current binary sequence (list of +1/-1)
        j: position to flip
        C: current autocorrelation vector [C_1, C_2, ..., C_{N-1}]

    Returns:
        (delta_E, new_C): energy change and updated autocorrelation vector
    """
    N = len(s)
    new_C = C[:]
    delta_E = 0

    for k_idx in range(N - 1):
        k = k_idx + 1
        delta_Ck = 0

        # j appears as first element in pair (j, j+k)
        if j + k < N:
            delta_Ck -= 2 * s[j] * s[j + k]

        # j appears as second element in pair (j-k, j)
        if j - k >= 0:
            delta_Ck -= 2 * s[j - k] * s[j]

        if delta_Ck != 0:
            new_Ck = C[k_idx] + delta_Ck
            delta_E += new_Ck * new_Ck - C[k_idx] * C[k_idx]
            new_C[k_idx] = new_Ck

    return delta_E, new_C
