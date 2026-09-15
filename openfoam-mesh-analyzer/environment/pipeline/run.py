#!/usr/bin/env python3
"""
Main mesh analysis pipeline.

Parses an OpenFOAM blockMeshDict, computes mesh statistics,
detects block adjacency, classifies solid/fluid regions,
and solves the analytical 1D conjugate heat transfer problem.

Writes the result to /app/mesh_report.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse_blockmeshdict
from analyzer import (
    compute_cell_sizes, get_block_dimensions,
    find_adjacencies, classify_region
)
from cht_solver import solve_cht


def main():
    bmdict_path = '/app/case/system/blockMeshDict'
    params_path = '/app/case/cht_params.json'
    output_path = '/app/mesh_report.json'

    # Parse inputs
    vertices, blocks_raw = parse_blockmeshdict(bmdict_path)
    with open(params_path) as f:
        params = json.load(f)

    # Build per-block info
    block_info = []
    total_cells = 0
    for idx, b in enumerate(blocks_raw):
        dims = get_block_dimensions(b, vertices)
        nx, ny, nz = b['cells']
        tc = nx * ny * nz
        total_cells += tc

        gy = b['grading'][1]  # y-direction grading
        first_y, last_y = compute_cell_sizes(dims[1], ny, gy)

        region = classify_region(b, vertices, params['heater_region'])

        block_info.append({
            'id': idx,
            'vertices': b['vertices'],
            'cell_count': [nx, ny, nz],
            'total_cells': tc,
            'region': region,
            'first_cell_height_y': first_y,
            'last_cell_height_y': last_y,
        })

    # Adjacency
    adjacencies = find_adjacencies(blocks_raw)

    # Find solid and fluid interface blocks for CHT
    solid_block = None
    for idx, b in enumerate(blocks_raw):
        if classify_region(b, vertices, params['heater_region']) == "solid":
            solid_block = idx
            break

    fluid_interface_block = None
    if solid_block is not None:
        for adj in adjacencies:
            if solid_block in adj:
                other = adj[0] if adj[1] == solid_block else adj[1]
                v = blocks_raw[other]['vertices']
                y_vals = [vertices[vi][1] for vi in v]
                heater = params['heater_region']
                if abs(min(y_vals) - heater['y_range'][1]) < 1e-6:
                    fluid_interface_block = other
                    break

    # CHT analysis
    cht = solve_cht(params, solid_block, fluid_interface_block)

    # Assemble report
    report = {
        'num_vertices': len(vertices),
        'num_blocks': len(blocks_raw),
        'total_cells': total_cells,
        'blocks': block_info,
        'adjacency': adjacencies,
        'cht': cht,
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Mesh report written to {output_path}")
    print(f"  Vertices: {len(vertices)}")
    print(f"  Blocks:   {len(blocks_raw)}")
    print(f"  Cells:    {total_cells}")
    print(f"  Adjacencies: {len(adjacencies)}")
    if cht.get('interface_temperature_K') is not None:
        print(f"  CHT interface temp: {cht['interface_temperature_K']} K")


if __name__ == '__main__':
    main()
