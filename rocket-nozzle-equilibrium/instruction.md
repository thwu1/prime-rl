Implement a chemical equilibrium rocket nozzle performance calculator for a LOX/LH2 bipropellant system. The calculator must predict combustion chamber conditions, nozzle throat conditions, and exhaust performance at multiple supersonic exit area ratios, matching NASA RP-1311 published reference data.

**Inputs** (pre-loaded in `/app/`):

- `/app/thermo_data.json` — NASA 7-coefficient thermodynamic polynomial data for 8 gaseous species in the H/O system (H, H2, O, O2, OH, H2O, HO2, H2O2). Includes molecular weights, elemental composition, and polynomial coefficients for two temperature ranges.
- `/app/problem.json` — Problem specification: fuel/oxidizer properties (enthalpies, compositions, molecular weights), oxidizer-to-fuel mass ratio, chamber pressure, and three supersonic exit area ratios.

**Required output**: `/app/results.json` with this exact structure:

```json
{
  "chamber": {
    "temperature_K": <float>,
    "pressure_bar": <float>,
    "mole_fractions": {"H": <float>, "H2": <float>, "O": <float>, "O2": <float>, "OH": <float>, "H2O": <float>, "HO2": <float>, "H2O2": <float>}
  },
  "throat": {
    "temperature_K": <float>,
    "pressure_bar": <float>,
    "velocity_m_per_s": <float>
  },
  "c_star_m_per_s": <float>,
  "exit_conditions": [
    {"area_ratio": <int>, "temperature_K": <float>, "pressure_bar": <float>, "mach_number": <float>, "isp_m_per_s": <float>, "ivac_m_per_s": <float>, "cf": <float>}
  ]
}
```

The `exit_conditions` array must contain one entry per area ratio from `problem.json`, in the same order, with `area_ratio` matching the integer value exactly. All eight species must participate. Nozzle expansion uses equilibrium (shifting) composition.

**Tolerance requirements** — values are compared to NASA RP-1311 Example 8 reference data:

| Quantity | Tolerance |
|---|---|
| Chamber temperature | 1.5% relative |
| Chamber pressure | 0.1% relative |
| Chamber mole fractions (H2, H2O) | 0.015 absolute |
| Chamber mole fractions (OH, H) | 0.008 absolute |
| Characteristic velocity c* | 1.5% relative |
| Throat temperature | 1.5% relative |
| Throat pressure | 3% relative |
| Throat velocity | 1.5% relative |
| Exit Isp | 1.5% relative |
| Exit Ivac | 1.5% relative |
| Exit CF | 2.5% relative |
| Exit Mach number | 3% relative |
| Exit temperature | 2% relative |

**Physical consistency requirements** — in addition to accuracy, results must satisfy:

- Isp must strictly increase across exit conditions (ascending area ratio order).
- CF must strictly increase across exit conditions.
- Exit temperature must strictly decrease across exit conditions.
- CF must equal Isp / c* within 0.5% relative for each exit condition.
- Throat velocity must be positive.
- Throat temperature must be less than chamber temperature.
- All chamber mole fractions must sum to 1.0 within 0.01 absolute.
