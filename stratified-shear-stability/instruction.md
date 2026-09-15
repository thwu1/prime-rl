Compute the linear stability diagram for a stratified parallel shear flow. The base state has velocity profile U(z) = tanh(z) and buoyancy profile B(z) = Ri * tanh(z) on a truncated domain z in [-L, L], where Ri is the bulk Richardson number and the squared buoyancy frequency is N^2(z) = dB/dz = Ri * sech^2(z).

The governing equation for the perturbation streamfunction psi_hat(z) with horizontal wavenumber k and complex phase speed c is the Taylor-Goldstein equation:

    (U - c) * (psi_hat'' - k^2 * psi_hat) - U'' * psi_hat + N^2 / (U - c) * psi_hat = 0

with boundary conditions psi_hat = 0 at z = +/- L. The temporal growth rate of each mode is sigma(k) = k * Im(c). Note the equation depends nonlinearly on the eigenvalue c through the (U - c) denominator.

Read the flow parameters from `/app/config.json` and produce three output files:

1. `/app/results/growth_rates.csv` — First column header `k`, remaining column headers `Ri_0.00`, `Ri_0.05`, ..., `Ri_0.25` (one per Richardson number). Each row gives the wavenumber k and the maximum temporal growth rate sigma(k) for each Ri.

2. `/app/results/max_growth.csv` — Three columns with headers `Ri`, `sigma_max`, `k_max`. Each row gives a Richardson number, its maximum growth rate over all wavenumbers, and the wavenumber at which that maximum occurs.

3. `/app/results/critical_ri.txt` — A single floating-point number: the smallest Richardson number from the configured list for which sigma_max < 1e-3 (i.e., the flow is effectively stable). Write it to 3 decimal places.