A 2D heat equation system on the periodic domain [0,1]^2 evolves initial conditions through two sequential diffusion phases with distinct thermal diffusivities. Phase 1 uses a known diffusivity kappa_1; Phase 2 uses an unknown diffusivity kappa_2. Both phases use explicit Euler time integration with a 5-point finite-difference Laplacian stencil on a uniform 64x64 grid. All parameters except kappa_2 are specified in `/app/config.json`.

Two experimental datasets are available:
- **Calibration experiment**: known initial condition at `/app/known_ic_b.npy` with observed final state at `/app/target_b.npy`
- **Primary experiment**: unknown initial condition with observed final state at `/app/target_a.npy`

Design and implement a complete differentiable optimization pipeline using NVIDIA Warp (CPU mode) that estimates the unknown diffusivity kappa_2 from the calibration data and recovers the unknown initial condition from the primary experiment. The implementation must use `@wp.kernel`-decorated functions for all computational kernels and `wp.Tape` for automatic differentiation through the forward simulation. Place all implementation files under `/app/`.

Required outputs:
- `/app/results/optimized_ic_a.npy` -- recovered 64x64 initial condition (NumPy array)
- `/app/results/estimated_kappa2.txt` -- estimated kappa_2 as plain-text float
- `/app/results/final_mse.txt` -- final MSE between the forward-simulated result (from recovered IC through both phases using estimated kappa_2) and target A, as plain-text float

The forward simulation from the recovered initial condition must produce a field with MSE below 1e-3 relative to target A.