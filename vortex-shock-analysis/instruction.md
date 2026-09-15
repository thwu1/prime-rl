The Python module `/app/ci2_init.py` exports a function `flow_state(x, y)` that returns the local pressure, temperature, and velocity vector for a 2D compressible inviscid flow in the domain [0,1]x[0,1]. The flow contains a stationary discontinuity and an embedded rotational structure upstream.

Analyze the provided function to understand the flow physics it encodes. Use Gmsh (Python API) to generate a 2D computational mesh of the domain with at least 160,000 nodes and save the mesh to `/app/results/mesh.msh`. Evaluate the flow state across the domain, reconstruct all thermodynamic and kinematic quantities that are not directly returned by the function, and compute the diagnostics specified in `/app/output_format.json`.

Write all results to `/app/results/analysis.json`.