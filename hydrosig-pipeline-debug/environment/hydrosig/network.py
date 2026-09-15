"""NHDPlus river network topology processing.

Handles loading, cleaning, DAG construction, and topological sorting
of NHDPlus-style flowline datasets.
"""
import networkx as nx
import numpy as np
import pandas as pd


def load_and_clean(filepath, min_network_size=1.0):
    """Load NHDPlus CSV and clean the network.

    Cleaning steps applied in order:
    1. Remove coastline features (fcode=56600)
    2. Handle divergent paths (divergence=2 -> fromnode=NaN)
    3. Derive missing tocomid from node topology
    4. Remove tiny terminal networks (totdasqkm < threshold)
    5. Remove isolated components (keep largest WCC)

    Parameters
    ----------
    filepath : str
        Path to NHDPlus-style CSV.
    min_network_size : float
        Minimum drainage area (sq km) for terminal segments.

    Returns
    -------
    tuple
        (cleaned_df, graph, original_count, removed_comids)
    """
    df = pd.read_csv(filepath)
    original_count = len(df)
    removed = []

    # Remove coastline features
    coastline_mask = df['fcode'] == 56600
    removed.extend(df.loc[coastline_mask, 'comid'].astype(int).tolist())
    df = df[~coastline_mask].copy()

    # Handle divergent paths
    df.loc[df['divergence'] == 2, 'fromnode'] = np.nan

    # Derive missing tocomid from node topology
    valid_from = df.dropna(subset=['fromnode'])
    fromnode_to_comid = dict(zip(
        valid_from['fromnode'].astype(int),
        valid_from['comid'].astype(int)
    ))

    df['tocomid'] = pd.to_numeric(df['tocomid'], errors='coerce')

    for idx in df.index:
        tocomid_val = df.at[idx, 'tocomid']
        is_terminal = df.at[idx, 'terminalfl'] == 1
        comid = int(df.at[idx, 'comid'])
        tonode = df.at[idx, 'tonode']

        if pd.isna(tocomid_val) or tocomid_val == 0:
            if is_terminal:
                df.at[idx, 'tocomid'] = -comid
            elif not pd.isna(tonode) and int(tonode) in fromnode_to_comid:
                df.at[idx, 'tocomid'] = fromnode_to_comid[int(tonode)]
            else:
                df.at[idx, 'tocomid'] = -comid

    # Remove tiny terminal networks
    terminal_tiny = df[
        (df['terminalfl'] == 1) & (df['totdasqkm'] < min_network_size)
    ]
    tiny_tpa = terminal_tiny['terminalpa'].unique()
    tiny_mask = df['terminalpa'].isin(tiny_tpa)
    removed.extend(df.loc[tiny_mask, 'comid'].astype(int).tolist())
    df = df[~tiny_mask].copy()

    # Remove isolated components (keep largest WCC)
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
