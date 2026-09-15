# nekRS .par File Reference

nekRS is a GPU-accelerated spectral element Navier-Stokes solver. Its primary
configuration uses `.par` files with an INI-like format extended with
mathematical expressions, compound parameters, and named scalar sections.

## Format Syntax

- **Sections**: `[SECTION NAME]` — names may contain spaces
- **Key-value pairs**: `key = value` — split on the *first* `=` only
- **Comments**: lines starting with `#`; inline comments preceded by whitespace + `#`
- **Values** can be:
  - Strings: `tombo2`, `endTime`, `zeroDirichlet`
  - Numbers: `7`, `1.0`, `1e-06`, `6.0e-3`
  - Mathematical expressions: `sqrt(7/1e8)`, `1/19000`, `1/sqrt(7*1e8)`, `5/7000`
  - Compound parameters: `targetCFL=4.0+max=0.05+initial=1e-3`
    Sub-parameters are separated by `+` and each is either a flag (`hpfrt`) or `subkey=subvalue`
  - Comma-separated lists: `zeroDirichlet, zeroNeumann`

## Standard Sections

### [GENERAL]

| Key | Type | Description |
|-----|------|-------------|
| polynomialOrder | integer | Polynomial order N for SEM; valid range [1, 15] |
| stopAt | string | `endTime` or `numSteps` |
| endTime | float | Simulation end time |
| numSteps | integer | Number of time steps |
| dt | float or compound | Time step; compound: `targetCFL=X+max=Y+initial=Z` |
| timeStepper | string | BDF/EXT order: `tombo1`, `tombo2`, or `tombo3` |
| advectionSubCyclingSteps | integer | Sub-cycling steps for advection |
| checkpointControl | string | `simulationTime` or `timeStep` |
| checkpointInterval | float | Checkpoint frequency |
| regularization | compound | `hpfrt + nModes=N + scalingCoeff=C` where C typically 1–20 (valid range [0.5, 50]) |
| scalars | string | Comma-separated list of scalar field names (e.g., `TEMPERATURE`, `K, TAU`) |
| constFlowRate | compound | `meanVelocity=V + direction=D` where D must be `X`, `Y`, or `Z` |
| userSections | string | Comma-separated list of user-defined section names |

### [PROBLEMTYPE]

| Key | Type | Description |
|-----|------|-------------|
| equation | string | `navierStokes` (default), `stokes`, `navierStokes+variableViscosity`, `navierStokes+lowMachCompressible` |

### [FLUID VELOCITY]

| Key | Type | Description |
|-----|------|-------------|
| boundaryTypeMap | list | Comma-separated boundary condition types |
| viscosity | expression | Kinematic viscosity (must evaluate to > 0) |
| rho | expression | Density (must evaluate to > 0) |
| residualTol | float | Iterative solver tolerance |

### [FLUID PRESSURE]

| Key | Type | Description |
|-----|------|-------------|
| residualTol | float | Pressure solver tolerance |

### [SCALAR \<NAME\>]

One section per scalar declared in `[GENERAL] scalars`. The section name must
match exactly: if `scalars = TEMPERATURE`, the section must be `[SCALAR TEMPERATURE]`.

| Key | Type | Description |
|-----|------|-------------|
| boundaryTypeMap | list | Comma-separated boundary condition types |
| diffusionCoeff | expression | Scalar diffusivity (must evaluate to > 0) |
| transportCoeff | expression | Transport coefficient (typically rho*cp) |
| residualTol | float | Solver tolerance |
| mesh | string | `fluid` (default) or `fluid+solid` (for conjugate heat transfer) |
| diffusionCoeffSolid | expression | **Required** when `mesh = fluid+solid` |
| transportCoeffSolid | expression | **Required** when `mesh = fluid+solid` |

### User-defined sections (e.g., [CASEDATA])

Arbitrary key-value pairs for case-specific parameters. Declared via
`userSections` in [GENERAL].

## Valid Boundary Condition Types

`zeroDirichlet`, `udfDirichlet`, `zeroNeumann`, `udfNeumann`, `udfRobin`,
`none`, `symmetry`, `inlet`, `outlet`

## Physics Types and Non-Dimensionalization

### rbc — Rayleigh-Benard Convection
- **Detection**: Has a temperature scalar (name in {TEMPERATURE, TEMP, T}),
  no K/TAU scalars, no `constFlowRate`, scalar does not use solid mesh
- **Non-dim**: `viscosity = sqrt(Pr/Ra)`, `diffusionCoeff = 1/sqrt(Ra*Pr)`
  - **Pr** = viscosity / diffusionCoeff
  - **Ra** = 1 / (viscosity × diffusionCoeff)

### rans_ktau — RANS k-tau Turbulence Model
- **Detection**: Scalars list includes both `K` and `TAU` (case-insensitive)
- **Requirement**: `[PROBLEMTYPE] equation` must contain `variableViscosity`
- **Non-dim**: `Re = 1 / viscosity`

### cht — Conjugate Heat Transfer
- **Detection**: A temperature scalar section contains `mesh = fluid+solid`
- **Requirements**: That scalar section must also define `diffusionCoeffSolid`
  and `transportCoeffSolid`
- **Non-dim**:
  - **Re** = 1 / viscosity
  - **Pr** = viscosity / diffusionCoeff
  - **conductivity_ratio** = diffusionCoeffSolid / diffusionCoeff

### pipe_flow — Periodic Pipe/Channel with Constant Flow Rate
- **Detection**: Has `constFlowRate` in [GENERAL], no K/TAU scalars,
  no temperature scalar with solid mesh
- **Non-dim**: `Re = 1 / viscosity`
- Extract `flow_direction` from `constFlowRate` compound parameter

### channel_flow — Simple Channel (fallback)
- **Detection**: No scalars declared, no constFlowRate
- **Non-dim**: `Re = 1 / viscosity`

### generic — Unrecognized
- Fallback when none of the above patterns match

**Detection priority**: rans_ktau > cht > pipe_flow > rbc > channel_flow > generic

## Validation Error Codes

The analyzer must detect and report these error conditions:

| Code | Condition |
|------|-----------|
| `MISSING_SCALAR_SECTION` | A name in `scalars` has no matching `[SCALAR <NAME>]` section |
| `EXPRESSION_ERROR` | A numeric field's expression cannot be evaluated (syntax error, division by zero, sqrt of negative, etc.) |
| `INVALID_TIMESTEPPER` | `timeStepper` is not `tombo1`, `tombo2`, or `tombo3` |
| `MISSING_VARIABLE_VISCOSITY` | K+TAU scalars present but `equation` does not contain `variableViscosity` |
| `NEGATIVE_PROPERTY` | `viscosity`, `rho`, `diffusionCoeff`, or `transportCoeff` evaluates to ≤ 0 |
| `MISSING_SOLID_DIFFUSION` | Scalar with `mesh=fluid+solid` is missing `diffusionCoeffSolid` |
| `MISSING_SOLID_TRANSPORT` | Scalar with `mesh=fluid+solid` is missing `transportCoeffSolid` |
| `INVALID_POLYNOMIAL_ORDER` | `polynomialOrder` outside [1, 15] |
| `INVALID_FLOW_DIRECTION` | `constFlowRate` direction is not `X`, `Y`, or `Z` |
| `SCALING_COEFF_OUT_OF_RANGE` | `regularization` scalingCoeff outside [0.5, 50] |

## Output Format

The analyzer outputs JSON to stdout:

```json
{
  "physics_type": "<detected type>",
  "polynomial_order": <int>,
  "time_stepper": "<string>",
  "nondim_params": {
    "<param_name>": <value>,
    ...
  },
  "material_props": {
    "<prop_name>": <float>,
    ...
  },
  "boundary_conditions": {
    "<field_name>": ["<bc1>", "<bc2>", ...],
    ...
  },
  "errors": [
    {
      "code": "<ERROR_CODE>",
      "message": "<human-readable description>",
      "section": "<section name>",
      "key": "<key name>"
    },
    ...
  ],
  "valid": <true|false>
}
```

`valid` is `true` only when `errors` is empty.
`nondim_params` keys depend on physics type (see above).
`material_props` contains evaluated values of viscosity, rho, diffusionCoeff, transportCoeff, and solid variants when present.
`boundary_conditions` maps field names (lowercase) to their BC type lists.
