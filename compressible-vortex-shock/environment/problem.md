# Compressible Vortex-Shock Interaction: Initial Condition

## Domain and Gas Model

A 2D domain [0, 1] x [0, 1] contains a calorically perfect ideal gas with:
- Ratio of specific heats: gamma = 1.4
- Specific gas constant: R = 1.0

Equation of state: p = rho * R * T

## Freestream and Shock Configuration

A uniform supersonic flow with Mach number M_s = 2.5 travels in the positive x-direction with zero transverse velocity. The upstream thermodynamic state is:

- rho_inf = 1.0
- p_inf = 1.0

A stationary normal shock is located at x_shock = 0.5. The post-shock (x > x_shock) thermodynamic state and velocity are determined by the standard normal shock jump conditions for this upstream Mach number and thermodynamic state.

## Composite Vortex

A composite vortex is superimposed on the pre-shock flow, centered at (x_c, y_c) = (0.25, 0.5) with:

- Core radius: a = 0.075
- Outer radius: b = 0.175
- Vortex Mach number: M_v = 0.8, defining the peak tangential velocity v_m = M_v * sqrt(gamma * R * T_inf)

Let r denote the distance from the vortex center. The tangential velocity profile is prescribed as:

- **Core** (r <= a): v_theta = v_m * r / a    (solid-body rotation)
- **Outer** (a < r <= b): v_theta = v_m * a * (r - b^2/r) / (a^2 - b^2)    (decays to zero at r = b)
- **External** (r > b): v_theta = 0    (no perturbation)

The velocity perturbation is added to the base flow:
- u_total = u_base - v_theta * sin(theta)
- v_total = v_base + v_theta * cos(theta)

where sin(theta) = (y - y_c)/r, cos(theta) = (x - x_c)/r.

Within the vortex (r <= b), the thermodynamic state (temperature, pressure, density) is fully determined by the prescribed velocity field and the governing equations of steady, inviscid, compressible flow. At the vortex boundary (r = b), the thermodynamic state matches the undisturbed upstream conditions continuously.

## Computational Mesh

Generate a mesh from the Gmsh geometry script `/app/domain.geo`:

```
gmsh domain.geo -2 -o mesh.msh
```

Parse the resulting mesh file to obtain node coordinates and element connectivity for field evaluation and integration.

## Required Outputs

### 1. Mesh file: `/app/mesh.msh`
The mesh generated from the geometry script, in Gmsh MSH format.

### 2. Solution file: `/app/solution.msh`
The mesh file augmented with `$NodeData` sections containing the flow solution at every mesh node. Include one scalar NodeData block for each variable: `rho`, `u`, `v`, `p`, `T`, `mach`.

### 3. Diagnostics: `/app/results.json`

```json
{
  "shock_density_ratio": <rho_d / rho_inf>,
  "shock_pressure_ratio": <p_d / p_inf>,
  "shock_temperature_ratio": <T_d / T_inf>,
  "probe_points": [
    {"x": 0.80, "y": 0.50, "rho": ..., "u": ..., "v": ..., "p": ..., "T": ..., "mach": ...},
    {"x": 0.10, "y": 0.20, "rho": ..., "u": ..., "v": ..., "p": ..., "T": ..., "mach": ...},
    {"x": 0.255, "y": 0.50, "rho": ..., "u": ..., "v": ..., "p": ..., "T": ..., "mach": ...},
    {"x": 0.32, "y": 0.50, "rho": ..., "u": ..., "v": ..., "p": ..., "T": ..., "mach": ...},
    {"x": 0.25, "y": 0.42, "rho": ..., "u": ..., "v": ..., "p": ..., "T": ..., "mach": ...},
    {"x": 0.10, "y": 0.50, "rho": ..., "u": ..., "v": ..., "p": ..., "T": ..., "mach": ...},
    {"x": 0.45, "y": 0.50, "rho": ..., "u": ..., "v": ..., "p": ..., "T": ..., "mach": ...}
  ],
  "total_mass": <integral of rho over domain, using mesh element areas>,
  "total_kinetic_energy": <integral of 0.5*rho*(u^2+v^2) over domain>,
  "max_mach": <maximum Mach number over all mesh element centroids>,
  "min_pressure": <minimum pressure over all mesh element centroids>,
  "num_nodes": <number of mesh nodes>,
  "num_elements": <number of 2D mesh elements (quads)>
}
```

## Parameters Summary

| Parameter | Value |
|-----------|-------|
| gamma     | 1.4   |
| R         | 1.0   |
| M_s       | 2.5   |
| M_v       | 0.8   |
| rho_inf   | 1.0   |
| p_inf     | 1.0   |
| x_shock   | 0.5   |
| x_c       | 0.25  |
| y_c       | 0.5   |
| a (core)  | 0.075 |
| b (outer) | 0.175 |
