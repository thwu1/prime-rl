A Fortran module at `/app/dust_physics.f90` implements mineral dust emission physics for GOCART-class atmospheric transport models. It provides routines for threshold friction velocity, soil moisture correction, aerodynamic drag partition, vertical-to-horizontal flux ratio, horizontal saltation flux, K14 vertical dust flux, aeolian surface roughness, moisture conversion, erodibility, soil erodibility potential, emitted dust size distribution, and a coupled per-cell emission pipeline.

The module has multiple defects. Several routines contain implementation errors contradicting the physics in their header comments. Several others are unimplemented stubs returning placeholder values. The `compute_cell_emission` subroutine—which must orchestrate the module's physics routines into a coupled pipeline producing size-resolved per-bin emission output—and the `kok2011_size_fraction` function—which must compute emitted dust mass fractions using numerical quadrature—are among the unimplemented stubs.

Fix all defects in `/app/dust_physics.f90` so that every public routine correctly implements the physics described in its header comment.

**Requirements:**

1. `make -C /app clean all` must compile without errors and produce `/app/dust_driver`.
2. Do not modify `/app/driver.f90` or `/app/Makefile`.
3. All routines must produce numerically correct results (within 0.1% relative tolerance) for test scenarios covering dry desert, moist loam, vegetated shrubland, and bedrock conditions.
4. Per-bin emission values from `compute_cell_emission` and size fractions from `kok2011_size_fraction` must match reference values. Size fractions must sum to 1.0 within 1e-4.
5. Bedrock erodibility and K14 flux must be zero. Per-bin emissions must be zero when total flux is zero. Higher soil moisture must increase the moisture correction factor.

**Build and run:**
```
cd /app && make clean all && ./dust_driver input.dat
```
