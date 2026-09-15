#!/usr/bin/env python3
"""Fix all bugs in the hydrosig package and run the pipeline.

"""


def fix_baseflow():
    """Fix two bugs in baseflow.py.

    Bug 1: Forward and backward passes use (1 - alpha) instead of (1 + alpha)
    in the Lyne-Hollick filter coefficient.

    Bug 2: Missing negative baseflow clipping after filter passes.
    Baseflow (groundwater contribution) cannot physically be negative.
    """
    with open("/app/hydrosig/baseflow.py", "r") as f:
        code = f.read()

    # Fix Bug 1: filter coefficient sign in both passes
    code = code.replace(
        "0.5 * (1 - alpha) * (q[i] - q[i - 1])",
        "0.5 * (1 + alpha) * (q[i] - q[i - 1])",
    )
    code = code.replace(
        "0.5 * (1 - alpha) * (q[i] - q[i + 1])",
        "0.5 * (1 + alpha) * (q[i] - q[i + 1])",
    )

    # Fix Bug 2: add negative clipping before return in separate()
    code = code.replace(
        "    qb = qb[pad_width:-pad_width]\n    return qb",
        "    qb = qb[pad_width:-pad_width]\n    qb[qb < 0] = 0.0\n    return qb",
    )

    with open("/app/hydrosig/baseflow.py", "w") as f:
        f.write(code)
    print("Fixed baseflow.py (2 bugs)")


def fix_signatures():
    """Fix three bugs in signatures.py.

    Bug 3: Coefficient of skewness (CS) missing the n multiplier in the
    Fisher-Pearson formula numerator.

    Bug 4: Walsh-Lawler seasonality index omits abs() around monthly
    deviations, causing positive and negative deviations to cancel.

    Bug 5: Streamflow elasticity uses np.nanmean instead of np.nanmedian.
    Sankarasubramanian et al. (2001) specifies the median for robustness.
    """
    with open("/app/hydrosig/signatures.py", "r") as f:
        code = f.read()

    # Fix Bug 3: add n multiplier to CS numerator
    code = code.replace(
        "cs = float(np.sum((values - maf) ** 3) / ((n - 1) * (n - 2) * s2 ** 1.5))",
        "cs = float(n * np.sum((values - maf) ** 3) / ((n - 1) * (n - 2) * s2 ** 1.5))",
    )

    # Fix Bug 4: add abs() to Walsh-Lawler seasonality
    code = code.replace(
        "deviation_sum = (year_months - r / 12).sum()",
        "deviation_sum = (year_months - r / 12).abs().sum()",
    )

    # Fix Bug 5: mean -> median in elasticity
    code = code.replace(
        "return float(np.nanmean(ratios))",
        "return float(np.nanmedian(ratios))",
    )

    with open("/app/hydrosig/signatures.py", "w") as f:
        f.write(code)
    print("Fixed signatures.py (3 bugs)")


def fix_recession():
    """Write corrected recession.py.

    Fixes four bugs:
    Bug 6: find_segments uses <= (non-strict) instead of < (strict
            monotonic decrease). Flat periods are not recessions.
    Bug 7: find_segments has off-by-one in length check:
            (end - start) should be (end - start + 1).
    Bug 8: find_segments does not handle trailing segment at end of
            time series (segment extending to the last data point).
    Bug 9: exponential_mrc sorts segments ascending instead of
            descending by starting flow. The matching strip method
            requires building the MRC from the highest-flow segment.
    """
    code = (
        '"""Recession analysis module.\n'
        "\n"
        "Identifies recession segments in streamflow hydrographs and fits\n"
        "master recession curves to determine the baseflow recession constant K.\n"
        '"""\n'
        "import numpy as np\n"
        "from scipy import stats\n"
        "\n"
        "\n"
        "def find_segments(streamflow, min_length=15):\n"
        '    """Find consecutive strictly-decreasing flow periods.\n'
        "\n"
        "    Parameters\n"
        "    ----------\n"
        "    streamflow : array-like\n"
        "        Daily streamflow time series.\n"
        "    min_length : int\n"
        "        Minimum segment length in days.\n"
        "\n"
        "    Returns\n"
        "    -------\n"
        "    numpy.ndarray\n"
        "        (N, 2) array of (start, end) indices for each recession segment.\n"
        '    """\n'
        "    q = np.asarray(streamflow, dtype=np.float64)\n"
        "    n = len(q)\n"
        "    segments = []\n"
        "    start = None\n"
        "\n"
        "    for i in range(1, n):\n"
        "        if q[i] < q[i - 1]:\n"
        "            if start is None:\n"
        "                start = i - 1\n"
        "        else:\n"
        "            if start is not None:\n"
        "                end = i - 1\n"
        "                if (end - start + 1) >= min_length:\n"
        "                    segments.append((start, end))\n"
        "                start = None\n"
        "\n"
        "    if start is not None:\n"
        "        end = n - 1\n"
        "        if (end - start + 1) >= min_length:\n"
        "            segments.append((start, end))\n"
        "\n"
        "    if segments:\n"
        "        return np.array(segments, dtype=np.int64)\n"
        "    return np.empty((0, 2), dtype=np.int64)\n"
        "\n"
        "\n"
        "def exponential_mrc(streamflow, flow_section):\n"
        '    """Build master recession curve using matching strip method.\n'
        "\n"
        "    Sorts recession segments by starting flow (descending), then\n"
        "    sequentially fits log-linear models and shifts segments to build\n"
        "    a composite curve.\n"
        '    """\n'
        "    q = np.asarray(streamflow, dtype=np.float64)\n"
        "\n"
        "    start_values = q[flow_section[:, 0]]\n"
        "    sort_indices = np.argsort(start_values)[::-1]\n"
        "\n"
        "    first_idx = sort_indices[0]\n"
        "    s0, e0 = flow_section[first_idx]\n"
        "    mrc = np.column_stack((\n"
        "        np.arange(1, e0 - s0 + 2, dtype=np.float64),\n"
        "        q[s0:e0 + 1]\n"
        "    ))\n"
        "\n"
        "    for i in range(1, len(flow_section)):\n"
        "        seg_idx = sort_indices[i]\n"
        "        s, e = flow_section[seg_idx]\n"
        "\n"
        "        log_q = np.log(np.maximum(mrc[:, 1], 1e-10))\n"
        "        coeffs = np.polyfit(mrc[:, 0], log_q, 1)\n"
        "\n"
        "        start_val = max(start_values[seg_idx], 1e-10)\n"
        "        timeshift = (np.log(start_val) - coeffs[1]) / coeffs[0]\n"
        "\n"
        "        new_seg = np.column_stack((\n"
        "            timeshift + np.arange(1, e - s + 2, dtype=np.float64),\n"
        "            q[s:e + 1]\n"
        "        ))\n"
        "        mrc = np.vstack((mrc, new_seg))\n"
        "\n"
        "    return mrc\n"
        "\n"
        "\n"
        "def recession_constant(streamflow, min_recession_length=15):\n"
        '    """Compute recession constant K from master recession curve.\n'
        "\n"
        "    K = -slope of log(Q) vs time regression on the composite MRC.\n"
        '    """\n'
        "    q = np.asarray(streamflow, dtype=np.float64)\n"
        "    segments = find_segments(q, min_recession_length)\n"
        "\n"
        "    if len(segments) < 2:\n"
        "        return float('nan')\n"
        "\n"
        "    mrc = exponential_mrc(q, segments)\n"
        "\n"
        "    log_q = np.log(np.maximum(mrc[:, 1], 1e-10))\n"
        "    slope_val, _, _, _, _ = stats.linregress(mrc[:, 0], log_q)\n"
        "\n"
        "    return float(-slope_val)\n"
    )
    with open("/app/hydrosig/recession.py", "w") as f:
        f.write(code)
    print("Fixed recession.py (4 bugs)")


def fix_accumulation():
    """Write corrected accumulation.py.

    Fixes two bugs in the route function:
    Bug 10: Celerity exponent is 0.5 (Chezy-like) instead of 0.3
            (simplified Manning kinematic wave approximation).
    Bug 11: Missing 0.5 decay factor in exponential attenuation.
            Should be exp(-0.5 * travel_time), not exp(-travel_time).
    """
    code = (
        '"""Flow accumulation through river networks.\n'
        "\n"
        "Accumulates flow through the directed acyclic graph using\n"
        "uniform runoff and kinematic wave routing attenuation.\n"
        '"""\n'
        "import math\n"
        "\n"
        "\n"
        "def route(q_in, length_km, slope):\n"
        '    """Attenuate flow through a channel segment using kinematic wave routing.\n'
        "\n"
        "    Parameters\n"
        "    ----------\n"
        "    q_in : float\n"
        "        Incoming flow.\n"
        "    length_km : float\n"
        "        Segment length in kilometers.\n"
        "    slope : float\n"
        "        Channel slope (m/m).\n"
        "\n"
        "    Returns\n"
        "    -------\n"
        "    float\n"
        "        Attenuated (routed) flow.\n"
        '    """\n'
        "    if slope <= 0 or length_km <= 0:\n"
        "        return q_in\n"
        "    celerity = slope ** 0.3\n"
        "    travel_time_days = (length_km * 1000.0) / (celerity * 86400.0)\n"
        "    return q_in * math.exp(-0.5 * travel_time_days)\n"
        "\n"
        "\n"
        "def accumulate(G, topo_order, network_df):\n"
        '    """Accumulate flow through the network in topological order.\n'
        "\n"
        "    Each segment contributes local runoff (totdasqkm * 0.001)\n"
        "    and receives routed flow from all upstream segments.\n"
        "\n"
        "    Parameters\n"
        "    ----------\n"
        "    G : networkx.DiGraph\n"
        "        Cleaned river network graph.\n"
        "    topo_order : list\n"
        "        Topological ordering of nodes (upstream first).\n"
        "    network_df : pandas.DataFrame\n"
        "        Cleaned network data with segment properties.\n"
        "\n"
        "    Returns\n"
        "    -------\n"
        "    dict\n"
        "        {comid: accumulated_flow} for each real segment (comid > 0).\n"
        '    """\n'
        "    seg_props = {}\n"
        "    for _, row in network_df.iterrows():\n"
        "        c = int(row['comid'])\n"
        "        seg_props[c] = {\n"
        "            'lengthkm': row['lengthkm'],\n"
        "            'slope': row['slope'],\n"
        "            'totdasqkm': row['totdasqkm'],\n"
        "        }\n"
        "\n"
        "    accumulated = {}\n"
        "\n"
        "    for node in topo_order:\n"
        "        if node < 0:\n"
        "            continue\n"
        "\n"
        "        upstream_total = 0.0\n"
        "        for pred in G.predecessors(node):\n"
        "            if pred in accumulated:\n"
        "                upstream_total += accumulated[pred]\n"
        "\n"
        "        props = seg_props.get(\n"
        "            node, {'lengthkm': 0, 'slope': 0, 'totdasqkm': 0}\n"
        "        )\n"
        "        routed = route(upstream_total, props['lengthkm'], props['slope'])\n"
        "        local = props['totdasqkm'] * 0.001\n"
        "        accumulated[node] = routed + local\n"
        "\n"
        "    return accumulated\n"
    )
    with open("/app/hydrosig/accumulation.py", "w") as f:
        f.write(code)
    print("Fixed accumulation.py (2 bugs)")


if __name__ == "__main__":
    fix_baseflow()
    fix_signatures()
    fix_recession()
    fix_accumulation()
    print("All 11 bugs fixed across 4 modules.")
