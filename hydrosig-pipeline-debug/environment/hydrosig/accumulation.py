"""Flow accumulation through river networks.

Accumulates flow through the directed acyclic graph using
uniform runoff and kinematic wave routing attenuation.
"""
import math


def route(q_in, length_km, slope):
    """Attenuate flow through a channel segment using kinematic wave routing.

    Parameters
    ----------
    q_in : float
        Incoming flow.
    length_km : float
        Segment length in kilometers.
    slope : float
        Channel slope (m/m).

    Returns
    -------
    float
        Attenuated (routed) flow.
    """
    if slope <= 0 or length_km <= 0:
        return q_in
    celerity = slope ** 0.5
    travel_time_days = (length_km * 1000.0) / (celerity * 86400.0)
    return q_in * math.exp(-travel_time_days)


def accumulate(G, topo_order, network_df):
    """Accumulate flow through the network in topological order.

    Each segment contributes local runoff (totdasqkm * 0.001)
    and receives routed flow from all upstream segments.

    Parameters
    ----------
    G : networkx.DiGraph
        Cleaned river network graph.
    topo_order : list
        Topological ordering of nodes (upstream first).
    network_df : pandas.DataFrame
        Cleaned network data with segment properties.

    Returns
    -------
    dict
        {comid: accumulated_flow} for each real segment (comid > 0).
    """
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

        props = seg_props.get(
            node, {'lengthkm': 0, 'slope': 0, 'totdasqkm': 0}
        )
        routed = route(upstream_total, props['lengthkm'], props['slope'])
        local = props['totdasqkm'] * 0.001
        accumulated[node] = routed + local

    return accumulated
