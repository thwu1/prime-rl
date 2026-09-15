"""LABS Hamiltonian interaction index computation."""

from math import floor


def get_interactions(N):
    """Compute G2 (2-body) and G4 (4-body) interaction index sets.

    From the Trotterized counterdiabatic unitary, using 0-indexed positions:
    - G2: pairs [i, i+k] for i=0..N-3, k=1..floor((N-1-i)/2)
    - G4: quadruples [i, i+t, i+k, i+k+t] for i=0..N-4,
           t=1..floor((N-2-i)/2), k=t+1..N-1-i-t

    Returns:
        (G2, G4): tuple of lists of index lists
    """
    G2 = []
    G4 = []

    for i in range(N - 2):
        for k in range(1, floor((N - 1 - i) / 2) + 1):
            G2.append([i, i + k])

    for i in range(N - 3):
        for t in range(1, floor((N - 2 - i) / 2) + 1):
            for k in range(t + 1, N - 1 - i - t + 1):
                G4.append([i, i + t, i + k, i + k + t])

    return G2, G4


def topology_overlaps(G2, G4):
    """Compute topology overlap invariants.

    I_22: self-overlap of G2 (equals |G2| since all sets are distinct)
    I_44: self-overlap of G4 (equals |G4|)
    I_24: cross-overlap (0, since 2-element and 4-element sets can't match)

    Returns:
        dict with keys '22', '24', '44'
    """
    return {"22": len(G2), "44": len(G4), "24": 0}
