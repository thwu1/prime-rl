A problem specification at `/app/problem.md` describes a 2D compressible inviscid flow consisting of a uniform supersonic stream, a stationary normal shock, and a composite vortex superimposed on the pre-shock region. Only the velocity profile of the vortex is prescribed; the thermodynamic state throughout the domain must be determined from the governing physics of compressible flow.

A Gmsh geometry script at `/app/domain.geo` defines the computational domain. Generate a mesh from this script using Gmsh, compute the complete flow state (density, velocity components, pressure, temperature, Mach number) at every mesh node and at specified probe locations, and derive domain-integrated quantities from the mesh elements.

Write three output files:

- `/app/mesh.msh` — the generated mesh in Gmsh MSH format
- `/app/solution.msh` — the mesh augmented with scalar `$NodeData` sections for each flow variable (`rho`, `u`, `v`, `p`, `T`, `mach`)
- `/app/results.json` — diagnostics in the format specified in `/app/problem.md`