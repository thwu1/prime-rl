#!/usr/bin/env python3
"""River network hydrological analysis pipeline.


Processes NHDPlus-like river network data, computes hydrological
signatures at gauge locations, and accumulates flow through the network.
"""
import json
import math

import networkx as nx
import numpy as np
import pandas as pd
from scipy import stats


# ====================================================================
# 1. Network Processing
# ====================================================================

def load_and_clean_network(filepath, min_network_size=1.0):
    """Load network CSV and clean according to NHDPlus conventions."""
    df = pd.read_csv(filepath)
    original_count = len(df)
    removed = []

    # Step 1: Remove coastline features (fcode == 56600)
    coastline_mask = df['fcode'] == 56600
    removed.extend(df.loc[coastline_mask, 'comid'].astype(int).tolist())
    df = df[~coastline_mask].copy()

    # Step 2: Handle divergent paths (divergence == 2 -> fromnode = NaN)
    df.loc[df['divergence'] == 2, 'fromnode'] = np.nan

    # Step 3: Derive missing tocomid from node topology
    # Build lookup: fromnode -> comid (only for non-NaN fromnodes)
    valid_from = df.dropna(subset=['fromnode'])
    fromnode_to_comid = dict(zip(
        valid_from['fromnode'].astype(int),
        valid_from['comid'].astype(int)
    ))

    # Convert tocomid column to numeric, coercing empty strings to NaN
    df['tocomid'] = pd.to_numeric(df['tocomid'], errors='coerce')

    for idx in df.index:
        tocomid_val = df.at[idx, 'tocomid']
        is_terminal = df.at[idx, 'terminalfl'] == 1
        comid = int(df.at[idx, 'comid'])
        tonode = df.at[idx, 'tonode']

        if pd.isna(tocomid_val) or tocomid_val == 0:
            if is_terminal and (pd.isna(tocomid_val) or tocomid_val == 0):
                df.at[idx, 'tocomid'] = -comid
            elif not pd.isna(tonode) and int(tonode) in fromnode_to_comid:
                df.at[idx, 'tocomid'] = fromnode_to_comid[int(tonode)]
            else:
                df.at[idx, 'tocomid'] = -comid

    # Step 4: Remove tiny terminal networks
    terminal_tiny = df[(df['terminalfl'] == 1) & (df['totdasqkm'] < min_network_size)]
    tiny_tpa = terminal_tiny['terminalpa'].unique()
    tiny_mask = df['terminalpa'].isin(tiny_tpa)
    removed.extend(df.loc[tiny_mask, 'comid'].astype(int).tolist())
    df = df[~tiny_mask].copy()

    # Step 5: Build graph and remove isolated components
    G = nx.DiGraph()
    for _, row in df.iterrows():
        c = int(row['comid'])
        tc = int(row['tocomid'])
        G.add_edge(c, tc,
                   lengthkm=row['lengthkm'],
                   slope=row['slope'],
                   totdasqkm=row['totdasqkm'])

    components = list(nx.weakly_connected_components(G))
    largest = max(components, key=len)

    real_comids = set(df['comid'].astype(int))
    isolated = [c for c in real_comids if c not in largest]
    removed.extend(isolated)

    df = df[df['comid'].astype(int).isin(largest)].copy()

    # Rebuild clean graph
    G_clean = nx.DiGraph()
    for _, row in df.iterrows():
        c = int(row['comid'])
        tc = int(row['tocomid'])
        G_clean.add_edge(c, tc,
                         lengthkm=row['lengthkm'],
                         slope=row['slope'],
                         totdasqkm=row['totdasqkm'])

    return df, G_clean, original_count, sorted(set(removed))


# ====================================================================
# 2. Baseflow Separation (Lyne-Hollick Filter)
# ====================================================================

def lh_forward_pass(q, alpha):
    """Forward pass of the Lyne-Hollick filter."""
    n = len(q)
    qf = np.zeros(n, dtype=np.float64)
    qf[0] = q[0] - np.min(q)
    for i in range(1, n):
        qf[i] = alpha * qf[i - 1] + 0.5 * (1.0 + alpha) * (q[i] - q[i - 1])
    qb = np.where(qf > 0, q - qf, q)
    return qb


def lh_backward_pass(q, alpha):
    """Backward pass of the Lyne-Hollick filter."""
    n = len(q)
    qf = np.zeros(n, dtype=np.float64)
    qf[-1] = q[-1] - np.min(q)
    for i in range(n - 2, -1, -1):
        qf[i] = alpha * qf[i + 1] + 0.5 * (1.0 + alpha) * (q[i] - q[i + 1])
    qb = np.where(qf > 0, q - qf, q)
    return qb


def baseflow_separation(discharge, alpha=0.925, n_passes=3, pad_width=10):
    """Extract baseflow using multi-pass Lyne-Hollick filter."""
    q = np.asarray(discharge, dtype=np.float64).copy()
    q = np.pad(q, pad_width, mode='edge')

    qb = lh_forward_pass(q, alpha)
    extra_passes = round(0.5 * (n_passes - 1))
    for _ in range(extra_passes):
        qb = lh_forward_pass(lh_backward_pass(qb, alpha), alpha)

    qb = qb[pad_width:-pad_width]
    qb[qb < 0] = 0.0
    return qb


def compute_bfi(discharge, alpha=0.925, n_passes=3, pad_width=10):
    """Compute Baseflow Index."""
    q = np.asarray(discharge, dtype=np.float64)
    total = np.sum(q)
    if total < 1e-6:
        return 0.0
    qb = baseflow_separation(q, alpha, n_passes, pad_width)
    return float(np.sum(qb) / total)


# ====================================================================
# 3. Recession Analysis
# ====================================================================

def find_recession_segments(streamflow, min_length=15):
    """Identify recession segments (consecutive decreasing flow)."""
    q = np.asarray(streamflow, dtype=np.float64)
    n = len(q)
    segments = []
    start = None

    for i in range(1, n):
        if q[i] < q[i - 1]:
            if start is None:
                start = i - 1
        else:
            if start is not None:
                end = i - 1
                if (end - start + 1) >= min_length:
                    segments.append((start, end))
                start = None

    if start is not None:
        end = n - 1
        if (end - start + 1) >= min_length:
            segments.append((start, end))

    if segments:
        return np.array(segments, dtype=np.int64)
    return np.empty((0, 2), dtype=np.int64)


def exponential_mrc(streamflow, flow_section):
    """Build master recession curve using exponential matching strip."""
    q = np.asarray(streamflow, dtype=np.float64)

    start_values = q[flow_section[:, 0]]
    sort_indices = np.argsort(start_values)[::-1]

    # Start with highest-flow segment
    first_idx = sort_indices[0]
    s0, e0 = flow_section[first_idx]
    mrc = np.column_stack((
        np.arange(1, e0 - s0 + 2, dtype=np.float64),
        q[s0:e0 + 1]
    ))

    for i in range(1, len(flow_section)):
        seg_idx = sort_indices[i]
        s, e = flow_section[seg_idx]

        # Fit current MRC
        log_q = np.log(np.maximum(mrc[:, 1], 1e-10))
        coeffs = np.polyfit(mrc[:, 0], log_q, 1)

        # Time shift for new segment
        start_val = max(start_values[seg_idx], 1e-10)
        timeshift = (np.log(start_val) - coeffs[1]) / coeffs[0]

        new_seg = np.column_stack((
            timeshift + np.arange(1, e - s + 2, dtype=np.float64),
            q[s:e + 1]
        ))
        mrc = np.vstack((mrc, new_seg))

    return mrc


def compute_recession_k(streamflow, min_recession_length=15):
    """Compute baseflow recession constant K."""
    q = np.asarray(streamflow, dtype=np.float64)
    segments = find_recession_segments(q, min_recession_length)

    if len(segments) < 2:
        return float('nan')

    mrc = exponential_mrc(q, segments)

    log_q = np.log(np.maximum(mrc[:, 1], 1e-10))
    slope_val, _, _, _, _ = stats.linregress(mrc[:, 0], log_q)

    return float(-slope_val)


# ====================================================================
# 4. Hydrological Signatures
# ====================================================================

def flood_moments(q_df):
    """Compute flood moments: MAF, CV, CS."""
    annual_max = q_df.resample('YE').max()
    maf = float(annual_max.mean().iloc[0])

    n = len(q_df)
    values = q_df.iloc[:, 0].values
    s2 = np.sum((values - maf) ** 2) / (n - 1)
    cv = float(np.sqrt(s2) / maf)
    cs = float(n * np.sum((values - maf) ** 3) / ((n - 1) * (n - 2) * s2 ** 1.5))

    return {'MAF': maf, 'CV': cv, 'CS': cs}


def fdc_slope(discharge, bins=(33, 67)):
    """Compute FDC slope between percentile bins (log-transformed)."""
    q = np.asarray(discharge, dtype=np.float64)
    q_log = np.log(np.clip(q, 1e-3, None))
    percentiles = np.percentile(q_log, list(bins))
    return float(np.diff(percentiles)[0] / (np.diff(bins)[0] / 100.0))


def seasonality_index_walsh(q_series):
    """Compute Walsh & Lawler (1981) seasonality index."""
    annual = q_series.resample('YE').sum()
    monthly = q_series.resample('ME').sum()

    si_values = []
    for year_end in annual.index:
        r = annual.loc[year_end]
        if r < 1e-6:
            continue
        year_months = monthly[monthly.index.year == year_end.year]
        deviation = (year_months - r / 12.0).abs().sum()
        si_values.append(float(deviation / r))

    return float(np.mean(si_values)) if si_values else 0.0


def streamflow_elasticity(q_series, p_series):
    """Compute streamflow elasticity (Sankarasubramanian et al., 2001)."""
    q_annual = q_series.resample('YE').mean()
    p_annual = p_series.resample('YE').mean()
    dq = q_annual.diff()
    dp = p_annual.diff()
    ratios = dq / dp * p_annual / q_annual
    return float(np.nanmedian(ratios))


# ====================================================================
# 5. Flow Accumulation
# ====================================================================

def route_flow(q_in, length_km, slope):
    """Route mean flow through a segment (kinematic wave attenuation)."""
    if slope <= 0 or length_km <= 0:
        return q_in
    celerity = slope ** 0.3
    travel_time_days = (length_km * 1000.0) / (celerity * 86400.0)
    return q_in * math.exp(-0.5 * travel_time_days)


def accumulate_flow(G, topo_order, network_df):
    """Accumulate flow through the network using uniform runoff."""
    seg_props = {}
    for _, row in network_df.iterrows():
        c = int(row['comid'])
        seg_props[c] = {
            'lengthkm': row['lengthkm'],
            'slope': row['slope'],
            'totdasqkm': row['totdasqkm'],
        }

    accumulated = {}

    for node in topo_order:
        if node < 0:
            continue

        upstream_total = 0.0
        for pred in G.predecessors(node):
            if pred in accumulated:
                upstream_total += accumulated[pred]

        props = seg_props.get(node, {'lengthkm': 0, 'slope': 0, 'totdasqkm': 0})
        routed = route_flow(upstream_total, props['lengthkm'], props['slope'])
        local = props['totdasqkm'] * 0.001
        accumulated[node] = routed + local

    return accumulated


# ====================================================================
# 6. Main Pipeline
# ====================================================================

def main():
    # --- Network ---
    network_df, G, original_count, removed = load_and_clean_network(
        '/app/data/network.csv', min_network_size=1.0
    )

    topo = list(nx.topological_sort(G))
    real_topo = [n for n in topo if n > 0]

    # --- Gauge data ---
    gauge_locs = pd.read_csv('/app/data/gauge_locations.csv')
    gauges = {}
    for _, row in gauge_locs.iterrows():
        gid = row['gauge_id']
        comid = int(row['comid'])
        df = pd.read_csv(
            f'/app/data/gauges/{gid}.csv',
            parse_dates=['date'],
            index_col='date'
        )
        gauges[gid] = {'comid': comid, 'data': df}

    # --- Per-gauge analysis ---
    gauge_results = {}
    for gid, info in gauges.items():
        df = info['data']
        q = df['streamflow_mm'].values
        q_series = df['streamflow_mm']
        p_series = df['precipitation_mm']
        comid = info['comid']

        bfi = compute_bfi(q)
        rec_k = compute_recession_k(q)
        q_df = q_series.to_frame('streamflow')
        fm = flood_moments(q_df)
        fdc = fdc_slope(q)
        si = seasonality_index_walsh(q_series)
        se = streamflow_elasticity(q_series, p_series)

        gauge_results[gid] = {
            'comid': comid,
            'bfi': bfi,
            'recession_k': rec_k,
            'flood_moments': fm,
            'fdc_slope': fdc,
            'seasonality_index': si,
            'streamflow_elasticity': se,
        }

    # --- Flow accumulation ---
    accumulated = accumulate_flow(G, topo, network_df)

    # --- Output ---
    results = {
        'network': {
            'original_count': original_count,
            'cleaned_count': len(network_df),
            'removed_comids': removed,
            'topological_order': real_topo,
        },
        'gauges': gauge_results,
        'flow_accumulation': {str(k): v for k, v in sorted(accumulated.items())},
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Pipeline complete. Results written to /app/results.json")


if __name__ == '__main__':
    main()
