#!/usr/bin/env python3
"""
Driver script: reads problem definitions from /app/problems.json,
runs the MUSCL-Hancock Godunov solver for each, and writes CSV output.

"""

import json
import os
from solver.fv_euler import solve_euler_1d


def main():
    with open('/app/problems.json') as f:
        config = json.load(f)

    gamma = config['gamma']
    os.makedirs('/app/results', exist_ok=True)

    for prob in config['problems']:
        name   = prob['name']
        xmin   = prob['domain'][0]
        xmax   = prob['domain'][1]
        x0     = prob['x0']
        left   = prob['left']
        right  = prob['right']
        t_end  = prob['t_end']
        ncells = prob['ncells']
        cfl    = prob['cfl']

        print(f"Solving '{name}' ({prob.get('description', '')}) ...")
        x, rho, u, p = solve_euler_1d(
            left, right, gamma, xmin, xmax, x0, ncells, t_end, cfl
        )

        outpath = f'/app/results/{name}.csv'
        with open(outpath, 'w') as fout:
            fout.write('x,rho,u,p\n')
            for i in range(len(x)):
                fout.write(f'{x[i]:.10f},{rho[i]:.10f},'
                           f'{u[i]:.10f},{p[i]:.10f}\n')
        print(f"  -> {outpath}  ({len(x)} cells)")

    print("All problems solved.")


if __name__ == '__main__':
    main()
