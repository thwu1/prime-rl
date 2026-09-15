`/app/config/problems.json` defines three 1D Riemann problems for the compressible Euler equations. Two use a single ratio of specific heats (gamma), and one — `multigamma` — uses **different gamma values on each side of the initial discontinuity** (gamma_left=1.4, gamma_right=1.6667), modelling a material interface between a diatomic and a monatomic-like gas.

Implement a first-order finite volume Godunov solver using the HLLC approximate Riemann solver. For the multi-material problem the solver must track gamma as a cell quantity advected with the flow (using the HLLC contact-wave speed for upwinding) and use the local gamma for all thermodynamic calculations (sound speed, energy ↔ pressure conversion). Also implement an exact Riemann solver supporting different left/right gamma values (Newton iteration for the star-region pressure with gamma-dependent pressure functions on each side) for computing reference solutions.

Required outputs in `/app/results/`:

- `blast.csv`, `contact.csv` — columns: `x,density,velocity,pressure,energy`
- `multigamma.csv` — columns: `x,density,velocity,pressure,energy,gamma`
- `errors.json` — L1 density error norms vs exact solution: `{"blast": <float>, "contact": <float>, "multigamma": <float>}`
- `convergence.json` — grid convergence on the `blast` problem: `{"resolutions": [...], "errors": [...], "rate": <float>}` where `rate` is the convergence order from least-squares fit of log(error) vs log(dx)

Energy is total specific energy: E = p/(rho*(gamma-1)) + 0.5*u^2, using the local cell gamma.