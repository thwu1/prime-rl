#!/usr/bin/env python3
"""Driver script for river network hydrological analysis.

Loads data, runs the hydrosig analysis pipeline, and writes results.
"""
import json

import networkx as nx
import pandas as pd

from hydrosig import baseflow, signatures, recession, network, accumulation


def main():
    # Load and clean network
    net_df, G, orig_count, removed = network.load_and_clean(
        '/app/data/network.csv', min_network_size=1.0
    )

    topo = list(nx.topological_sort(G))
    real_topo = [n for n in topo if n > 0]

    # Load gauge data
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

    # Per-gauge analysis
    gauge_results = {}
    for gid, info in gauges.items():
        df = info['data']
        q = df['streamflow_mm'].values
        q_series = df['streamflow_mm']
        p_series = df['precipitation_mm']
        comid = info['comid']

        gauge_results[gid] = {
            'comid': comid,
            'bfi': baseflow.bfi(q),
            'recession_k': recession.recession_constant(q),
            'flood_moments': signatures.flood_moments(
                q_series.to_frame('streamflow')
            ),
            'fdc_slope': signatures.fdc_slope(q),
            'seasonality_index': signatures.seasonality_index(q_series),
            'streamflow_elasticity': signatures.streamflow_elasticity(
                q_series, p_series
            ),
        }

    # Flow accumulation
    acc = accumulation.accumulate(G, topo, net_df)

    # Write output
    results = {
        'network': {
            'original_count': orig_count,
            'cleaned_count': len(net_df),
            'removed_comids': removed,
            'topological_order': real_topo,
        },
        'gauges': gauge_results,
        'flow_accumulation': {
            str(k): v for k, v in sorted(acc.items())
        },
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == '__main__':
    main()
