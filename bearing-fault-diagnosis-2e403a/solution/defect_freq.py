"""Rolling-element bearing defect frequency computation."""

import math


def compute_defect_frequencies(bearing_params, shaft_hz):
    """Compute BPFO, BPFI, BSF, and FTF from bearing geometry and shaft speed.

    Parameters
    ----------
    bearing_params : dict
        Keys: rd (roller diameter), pd (pitch diameter), ne (int, number of
        rolling elements), ca_deg (contact angle in degrees), outer_fixed (bool).
    shaft_hz : float
        Shaft rotational frequency in Hz.

    Returns
    -------
    dict  with keys BPFO, BPFI, BSF, FTF  (all in Hz).
    """
    rd = bearing_params["rd"]
    pd = bearing_params["pd"]
    ne = bearing_params["ne"]
    ca_deg = bearing_params["ca_deg"]
    outer_fixed = bearing_params.get("outer_fixed", True)

    ca_rad = math.radians(ca_deg)
    ratio = rd / pd
    cs = math.cos(ca_rad)

    bpfo = 0.5 * ne * shaft_hz * (1.0 - ratio * cs)
    bpfi = 0.5 * ne * shaft_hz * (1.0 + ratio * cs)
    bsf = (pd / rd) * shaft_hz * (1.0 - (ratio * cs) ** 2)

    if outer_fixed:
        ftf = 0.5 * shaft_hz * (1.0 - ratio * cs)
    else:
        ftf = 0.5 * shaft_hz * (1.0 + ratio * cs)

    return {"BPFO": bpfo, "BPFI": bpfi, "BSF": bsf, "FTF": ftf}
