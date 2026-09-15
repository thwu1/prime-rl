"""Magnitude-frequency distribution discretization."""


def discretize_mfd(mfd):
    """Discretize an MFD specification into (magnitude, rate) pairs."""
    if mfd["type"] == "GR":
        return _discretize_gr(mfd)
    elif mfd["type"] == "INCR":
        return list(zip(mfd["magnitudes"], mfd["rates"]))
    return []


def _discretize_gr(mfd):
    """Discretize a Gutenberg-Richter distribution into magnitude bins.

    Generates centered magnitude bins spanning from mMin to mMax
    with spacing dMag. The incremental rate for each bin is the
    difference in cumulative rates across the bin width.
    """
    a = mfd["a"]
    b = mfd["b"]
    m_min = mfd["mMin"]
    m_max = mfd["mMax"]
    dm = mfd["dMag"]

    pairs = []
    m = m_min + dm / 2.0
    while m < m_max - dm / 2.0 + 1e-6:
        rate = 10.0 ** (a - b * m) - 10.0 ** (a - b * (m + dm))
        pairs.append((round(m, 2), rate))
        m += dm
    return pairs
