#!/usr/bin/env python3

"""Process a TOML model file and run 3D frame buckling analysis."""
import sys
import os
import json
import tomllib
import numpy as np
from frame3d import elastic_critical_load_analysis


def load_model(path):
    """Load a structural model from a TOML file."""
    with open(path, 'rb') as f:
        model = tomllib.load(f)

    node_list = model['geometry']['nodes']
    node_coords = np.array(node_list, dtype=float)

    section = model['section']
    local_z = np.array(section.get('local_z', [0.0, 0.0, 1.0]))

    element_pairs = model['connectivity']['elements']
    elements = []
    for ni, nj in element_pairs:
        elements.append({
            'node_i': ni,
            'node_j': nj,
            'E': section['E'],
            'nu': section['nu'],
            'A': section['A'],
            'I_y': section['I_y'],
            'I_z': section['I_z'],
            'J': section['J'],
            'I_rho': section['I_rho'],
            'local_z': local_z.copy(),
        })

    bcs = {}
    for bc in model['boundary_conditions']:
        bcs[bc['node']] = bc['fixed']

    loads = {}
    for ld in model['loads']:
        loads[ld['node']] = ld['values']

    return node_coords, elements, bcs, loads


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <model.toml>")
        sys.exit(1)

    model_path = sys.argv[1]
    node_coords, elements, bcs, loads = load_model(model_path)

    lam, mode = elastic_critical_load_analysis(
        node_coords=node_coords,
        elements=elements,
        boundary_conditions=bcs,
        nodal_loads=loads,
    )

    result = {
        'critical_load_factor': float(lam),
        'mode_shape': mode.tolist(),
        'n_nodes': int(node_coords.shape[0]),
        'n_elements': len(elements),
    }

    os.makedirs('/app/results', exist_ok=True)
    base = os.path.splitext(os.path.basename(model_path))[0]
    output_path = f'/app/results/{base}_result.json'
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Critical load factor: {lam:.6e}")
    print(f"Results written to: {output_path}")


if __name__ == '__main__':
    main()
