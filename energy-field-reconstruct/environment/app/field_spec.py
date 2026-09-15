"""
Reference implementation for computing the energy field in Lux AI Season 3.

See game_mechanics.md for the full specification.

This module provides the forward computation: given known node parameters,
compute the energy field. The inverse problem (reconstructing node parameters
from partial observations) is what the solver must implement.
"""


import math


def compute_node_contribution(tile_x, tile_y, node_x, node_y, fn_type, a, b, c):
    """Compute the energy contribution from a single node to a single tile.

    Args:
        tile_x, tile_y: tile position (integers 0-23)
        node_x, node_y: node position (can be float during optimization)
        fn_type: 0 (sinusoidal) or 1 (rational decay)
        a, b, c: function parameters

    Returns:
        float: energy contribution (before clipping/truncation)
    """
    distance = math.sqrt((tile_x - node_x) ** 2 + (tile_y - node_y) ** 2)
    if fn_type == 0:
        return math.sin(distance * a + b) * c
    else:
        return (a / (distance + 1) + b) * c


def compute_energy_field(nodes, map_size=24):
    """Compute the complete energy field from a list of energy nodes.

    Args:
        nodes: list of dicts, each with:
            'pos': [x, y]       — node position on the map
            'fn_type': 0 or 1   — function type
            'params': [a, b, c] — function parameters
        map_size: size of the square map (default 24)

    Returns:
        list[list[int]]: map_size x map_size grid of integer energy values,
                         where result[x][y] is the energy at tile (x, y)
    """
    field = [[0.0] * map_size for _ in range(map_size)]

    for node in nodes:
        nx, ny = node['pos']
        fn_type = node['fn_type']
        a, b, c = node['params']
        for x in range(map_size):
            for y in range(map_size):
                field[x][y] += compute_node_contribution(
                    x, y, nx, ny, fn_type, a, b, c
                )

    # Clip to [-20, 20] and truncate toward zero
    for x in range(map_size):
        for y in range(map_size):
            v = max(-20.0, min(20.0, field[x][y]))
            field[x][y] = math.trunc(v)

    return field
