Build a supersonic external-compression inlet performance analyzer at `/app/inlet_solver.py` that reads analysis cases from `/app/inlet_config.json` and thermodynamic data from `/app/gas_data.json`, then writes computed results to `/app/results.json`.

## Inlet Model

The inlet consists of N planar compression ramps, each producing an oblique shock wave, followed by a terminal normal shock at the cowl lip. Upstream flow is characterized by Mach number, static temperature, and static pressure. Each ramp deflects the flow by a specified angle, generating a weak oblique shock. The terminal normal shock decelerates the flow to subsonic speed. The primary performance metric is total pressure recovery: the ratio of total (stagnation) pressure after all shocks to the freestream total pressure.

## Gas Models

Two gas models must be supported:

- **Calorically perfect gas (CPG)**: constant specific heat ratio gamma. All shock relations have closed-form expressions.
- **Thermally perfect gas (TPG)**: specific heat at constant pressure varies with temperature via NASA 7-coefficient polynomial (Cp/R = a1 + a2*T + a3*T^2 + a4*T^3 + a5*T^4, with enthalpy and entropy integration constants a6 and a7). Gas data for individual species and mixture definitions are in `/app/gas_data.json`. For mixtures, compute mixture-averaged properties using mole-fraction-weighted molecular weight and mass-fraction-weighted specific heats. The TPG model requires iterative solution of the conservation equations across each shock.

## Required Capabilities

1. Solve the oblique shock theta-beta-Mach relation for the weak shock angle given upstream Mach and flow deflection angle
2. Compute all property ratios across each oblique shock (pressure, temperature, density, total pressure) and the downstream Mach number
3. Track flow properties sequentially through multiple ramps
4. Apply a terminal normal shock and compute its property ratios
5. For optimization cases (`"optimize": true`), find ramp angles maximizing total pressure recovery subject to a fixed total deflection angle
6. Support both CPG and TPG gas models

## Output Format

Write `/app/results.json` as:

```json
{
  "<case_name>": {
    "oblique_shocks": [
      {
        "ramp_angle_deg": <float>,
        "shock_angle_deg": <float>,
        "upstream_mach": <float>,
        "downstream_mach": <float>,
        "pressure_ratio": <float>,
        "temperature_ratio": <float>,
        "density_ratio": <float>,
        "total_pressure_ratio": <float>
      }
    ],
    "terminal_normal_shock": {
      "upstream_mach": <float>,
      "downstream_mach": <float>,
      "pressure_ratio": <float>,
      "temperature_ratio": <float>,
      "density_ratio": <float>,
      "total_pressure_ratio": <float>
    },
    "overall_total_pressure_recovery": <float>,
    "optimized_ramp_angles_deg": [<float>, ...]
  }
}
```

The `optimized_ramp_angles_deg` field is only required for optimization cases. All property ratios are downstream/upstream (e.g., P2/P1).