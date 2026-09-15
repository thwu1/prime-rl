A C++ simulation of a planar double pendulum (two rigid rods connected by pin joints under gravity) is provided at `/app/sim/`. The project is built with CMake and depends on the Eigen3 linear algebra library. A known-correct Python reference implementation of the same physical system is at `/app/reference/pendulum_ref.py` (no external dependencies).

The simulation currently fails to build. Even after build issues are resolved, the simulation produces physically incorrect results: constraint violations grow unboundedly, energy behavior is wrong, and the integration accuracy is lower than it should be.

Debug and fix all issues in `/app/sim/` so the simulation builds, runs, and produces physically correct results. Write a final trajectory to `/app/results/trajectory.csv`.

Correctness criteria:

- Position-level constraint violations must stay below 1e-6 throughout the simulation
- With `rho_inf=1.0`, relative energy drift must stay under 1% over 2 seconds of simulation
- With `rho_inf < 1.0`, total energy must decrease over time (numerical dissipation)
- Final joint angles at t=1.0 must match the Python reference within 0.01 radians
- The integrator must exhibit second-order convergence in step size

After building in `/app/sim/build/`, the binary accepts positional arguments:

    ./sim theta1 theta2 omega1 omega2 rho_inf h t_end output_file

Angles are in radians; `theta = -pi/2` is the hanging equilibrium. The Python reference accepts the same arguments:

    python3 /app/reference/pendulum_ref.py theta1 theta2 omega1 omega2 t_end output.csv