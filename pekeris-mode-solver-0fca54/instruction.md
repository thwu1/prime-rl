A Fortran Pekeris waveguide normal-mode solver in `/app/` must be made to compile and produce physically correct results. The program computes trapped acoustic modes and transmission loss in a two-layer ocean waveguide (isovelocity water over a fluid half-space).

The source is split across multiple Fortran files with module dependencies. Running `make` in `/app/` must produce the `pekeris_solver` executable without errors. Running `./pekeris_solver` reads the default `waveguide.cfg`; running `./pekeris_solver <config>` reads an alternate configuration file.

The executable must produce four output files in the working directory:

`modes.dat` — first line `# num_modes N`, then per mode: index, horizontal wavenumber kr (1/m), phase speed (m/s), group speed (m/s), attenuation (1/m). Modes ordered by descending kr.

`tl_incoherent.dat` — header line, then per range point: range (km), incoherent transmission loss (dB).

`tl_coherent.dat` — header line, then per range point: range (km), coherent transmission loss (dB) using far-field cylindrical spreading.

`pressure_field.dat` — header line, then for each receiver depth from 1 m to water_depth in 1 m steps at each range point: depth (m), range (km), coherent TL (dB).

The program currently fails to build. Once build issues are resolved, multiple physics and numerical errors produce incorrect results across eigenvalues, group velocities, and transmission loss. The pressure field computation is incomplete.

Correctness criteria (verified by automated tests):

- All trapped modes found for any valid Pekeris configuration
- Horizontal wavenumber relative error < 10⁻⁶ against reference eigenvalue solver
- Group velocities within 0.1% relative error, in (0, c_water), decreasing with mode order
- Incoherent TL within 0.5 dB of reference modal sum
- Coherent TL within 0.5 dB, oscillates around incoherent TL
- Pressure field TL within 1.0 dB at sampled depth-range grid points; at receiver depth must match coherent TL
- All outputs correct under both default and alternate waveguide configurations
