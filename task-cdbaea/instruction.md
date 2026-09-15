Implement a numerical solver for the 1D compressible Navier-Stokes equations in `/app/solver.py`. The solver will be evaluated against reference solutions from the PDEBench dataset (up to 1024 spatial points).

## PDE System

The 1D compressible Navier-Stokes equations on the periodic domain x in [-1, 1]:

- Continuity: d_t(rho) + d_x(rho * v) = 0
- Momentum: rho * (d_t(v) + v * d_x(v)) = -d_x(p) + eta * d_xx(v) + (zeta + eta/3) * d_x(d_x(v))
- Energy: d_t[epsilon + rho*v^2/2] + d_x[(epsilon + p + rho*v^2/2)*v - v*sigma'] = 0

where rho is mass density, v is velocity, p is gas pressure, epsilon = p/(Gamma - 1) is internal energy with Gamma = 5/3, and sigma' = (zeta + 4*eta/3) * d_x(v) is the viscous stress tensor. Parameters: eta = zeta = 0.1.

## Solver Interface

The function in `/app/solver.py` must have signature:

```python
def solver(Vx0, density0, pressure0, t_coordinate, eta, zeta):
    # Vx0: np.ndarray [batch_size, N] - initial velocity
    # density0: np.ndarray [batch_size, N] - initial density
    # pressure0: np.ndarray [batch_size, N] - initial pressure
    # t_coordinate: np.ndarray [T+1] - time points starting at t=0
    # eta: float - shear viscosity
    # zeta: float - bulk viscosity
    # Returns: (Vx_pred, density_pred, pressure_pred) each [batch_size, T+1, N]
```

## Evaluation

An evaluator at `/app/evaluator.py` downloads the reference HDF5 dataset from HuggingFace, runs your solver on test instances, and computes the aggregate nRMSE across velocity, density, and pressure fields.

Run: `cd /app && python3 evaluator.py`

A smaller development dataset for faster iteration can be fetched by passing `--dev`.

**Pass criterion**: nRMSE < 0.05