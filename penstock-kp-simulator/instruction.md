The Modelica source files in `/app/modelica_sources/` define a hydropower waterway library. Port the relevant physics models to `/app/waterway.py` by studying the governing equations, numerical methods, and boundary conditions in those files.

The sources may contain inconsistencies (e.g., derivative formulas not matching the parent function). Your implementation must satisfy the requirements below.

**Run tests:** `cd /app && python3 -m pytest /tests/test_state.py -v`

**Required API in `/app/waterway.py`:**

`darcy_friction(Re, D, eps)` -> `float`. Friction factor with regime boundaries at Re = 2100 and Re = 2300, matching the Modelica definitions. Re <= 0 returns 0.0. The transition zone must be both value-continuous and derivative-continuous at both regime boundaries. Higher roughness at constant Re yields higher friction in turbulent regime.

`friction_force(v, D, L, rho, mu, eps)` -> `float`. Pipe friction force matching `Friction.mo`. Same sign as `v`; reverses sign exactly when velocity reverses.

`class ElasticPenstock` -- Finite-volume simulator for the coupled pressure-mass-flow-rate system in the Modelica penstock model.

Constructor: `ElasticPenstock(L, H, D_i, D_o=D_i, N=20, rho=999.65, mu=1.3076e-3, beta=4.5e-10, beta_total=1/(rho*1e6), p_eps=0.0, p_a=0.0, g=9.81, theta=1.3)`. All parameters stored as instance attributes with matching names.

`simulate(t_end, dt, p_inlet_func, mdot_outlet_func, Vdot_0=0.0)` -- Time-stepping simulation. BCs: inlet pressure from `p_inlet_func(t)`, outlet mass flow from `mdot_outlet_func(t)`. Initialize with hydrostatic pressure gradient and uniform mass flow from `Vdot_0`. Returns `dict` with keys `times` `[T+1]`, `pressures` `[T+1, N]`, `flows` `[T+1, N]`.

Penstock acceptance (horizontal H=0, N=10, beta_total=1e-9):
- Steady state: pressure drift < 5% of initial when BCs match initial conditions
- Valve closure peak pressure within [70%, 150%] of the analytical pressure rise for instantaneous flow stoppage
- Inlet deviation < 15% of initial before half the wave traversal time; outlet deviation > 10% of initial after 1.2x the traversal time
- Total mass deviation < 10%

`gate_discharge(gate_type, a, h_0, h_2, b, g=9.81, rho=999.65, r=None, h_h=None)` -> `float` (m^3/s). Gate volume flow from the Modelica gate model. `gate_type`: `'sluice'` or `'radial'`. Automatically switches between free-flow and backed-up regimes based on downstream level. Backed-up flow always produces less discharge than free flow. Radial gates require `r` (arm radius) and `h_h` (hinge height).

`francis_power(mdot, omega, R_1, R_2, w_1, alpha1_deg, beta2_deg, D_i, rho)` -> `float` (watts). Shaft power from the Modelica Francis turbine model. Zero mass flow yields zero power.
