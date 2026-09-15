A computational pipeline for single-phase Poiseuille flow exists at `/app/pipeline/`. It generates meshes via `gmsh`, solves the flow equations with a GNU Octave numerical solver, and post-processes results with Python. Currently it supports only uniform-viscosity flow.

Extend this pipeline to handle two-phase stratified flow -- two immiscible fluid layers with different viscosities sharing a planar channel. The numerical solver component must remain in Octave. Compute relative permeabilities for all viscosity ratios and saturations in `/app/config.py`, and validate the numerical method with a mesh convergence study.

Physics, governing equations, and the output schema are in `/app/problem_description.txt`. Produce `/app/results.json`.