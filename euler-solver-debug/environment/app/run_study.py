#!/usr/bin/env python3
"""
Grid convergence study runner.

Orchestrates the full simulation pipeline:
  1. Generate meshes at multiple resolutions using gmsh CLI
  2. Run the numerical solver at each resolution (reads gmsh .msh files)
  3. Compute exact Riemann solution for analytical reference
  4. Compute L2 errors and convergence metrics (Richardson extrapolation, GCI)
  5. Write convergence data for gnuplot
  6. Produce convergence plot with gnuplot CLI
  7. Write final results to JSON

Dependencies: gmsh (CLI), gnuplot (CLI), numpy (Python)
"""
import subprocess
import json
import numpy as np
import sys
import os

sys.path.insert(0, '/app')


def generate_mesh(N, geo_path='/app/mesh_template.geo'):
    """Generate 1D mesh with N cells using gmsh CLI.

    Must invoke gmsh to produce a .msh file that the solver can parse.
    The geo_path template accepts N via DefineConstant.
    """
    msh_path = f'/app/mesh_N{N}.msh'
    # TODO: Call gmsh CLI to generate mesh
    # - Use -setnumber to pass N to the .geo script
    # - Ensure output format is compatible with the solver's parse_msh()
    # - Handle any errors from gmsh
    raise NotImplementedError("Implement gmsh mesh generation")


def compute_l2_error(x_num, rho_num, x_exact, rho_exact):
    """Compute L2 error norm between numerical and exact density profiles.

    Interpolate exact solution onto the numerical grid, then compute
    the discrete L2 norm.
    """
    # TODO: Implement L2 error computation
    raise NotImplementedError("Implement L2 error computation")


def run_convergence_study():
    """Execute the full convergence study pipeline."""
    with open('/app/problem_config.json') as f:
        config = json.load(f)

    from euler_solver import solve
    from exact_riemann import exact_riemann

    resolutions = [100, 200, 400, 800]

    # TODO: For each resolution:
    #   1. Generate mesh with gmsh
    #   2. Run solver
    #   3. Compute L2 error against exact solution

    # TODO: Compute convergence order via Richardson extrapolation
    #   p = log(e1/e2) / log(r), where r = refinement ratio = 2

    # TODO: Compute GCI using Roache's method (Fs = 1.25)

    # TODO: Write convergence_data.dat (columns: N, L2_error) for gnuplot

    # TODO: Run gnuplot to produce /app/convergence.png

    # TODO: Write /app/results.json with all required fields

    raise NotImplementedError("Implement convergence study")


if __name__ == '__main__':
    run_convergence_study()
