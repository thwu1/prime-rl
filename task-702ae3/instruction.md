Implement a solver in `/app/sedov_solver.py` that computes exact solutions to the Sedov-Taylor point-explosion problem for an ideal gas in planar (n=1), cylindrical (n=2), and spherical (n=3) geometries.

The Sedov-Taylor problem models the blast wave produced by an instantaneous release of energy into a uniform-density medium. Your solver must produce radial profiles of density, velocity, pressure, specific internal energy, and sound speed as functions of position and time, matching the reference data published by Kamm & Timmes (LA-UR-07-2849) to 4 significant figures.

## Required API

```python
class SedovSolver:
    def __init__(self, geometry, gamma, omega=0.0, eblast=0.851072, rho0=1.0):
        """
        geometry: 1=planar, 2=cylindrical, 3=spherical
        gamma: ratio of specific heats
        omega: initial density power-law exponent
        eblast: total deposited energy
        rho0: reference density

        Must expose attributes: v2, v0, eval1, eval2, alpha
        """
        ...

    def sedov_functions(self, v):
        """Returns tuple (lam, f, g, h)."""
        ...

    def compute_profiles(self, r, t):
        """
        r: numpy array of radial positions
        t: float, time > 0
        Returns dict with keys: 'position', 'density', 'velocity',
            'pressure', 'specific_internal_energy', 'sound_speed',
            'shock_position'
        """
        ...
```

## Requirements

- Correct results for all three geometries with gamma=1.4, omega=0 (standard Sedov problem), and also for gamma=5/3.
- Numerical values of exposed attributes and function outputs must agree with Kamm & Timmes reference tables.
- Profiles must be physically consistent: positive energy and sound speed inside the shock, ambient conditions outside.