A synthetic gravity survey has been conducted over a 4 km x 4 km area. The observed vertical gravitational acceleration data is at `/app/observed_data.csv` (columns: x, y, z, gz_mgal). The model space configuration is at `/app/model_config.json`, defining a 3D grid of right-rectangular prisms that discretizes the subsurface volume.

Recover the subsurface density contrast distribution from the observed gravity data. The model consists of 256 prisms (8 x 8 x 4 grid), each with an unknown density contrast (kg/m³). The gravitational field produced by your recovered density model must closely match the observed data.

Constraints:
- You may NOT use any external geophysics libraries (no harmonica, choclo, fatiando, SimPEG, etc.). Implement all gravity computations from first principles.
- The RMS misfit between your predicted gravity and the observed data must be below 0.15 mGal.
- Your gravity forward model must be physically correct — consistent with analytical solutions for known prism configurations within 0.1% relative error.
- Recovered density contrasts must be within a physically plausible range (magnitude < 2000 kg/m³).

Prism IDs are assigned by iterating easting (outer), then northing (middle), then depth (inner), starting from 0. Each prism has boundaries [west, east, south, north, bottom, top] in meters. The z-axis is positive upward; prism bottoms are more negative than tops.

Write the following output files:
- `/app/results/recovered_densities.csv` with columns: prism_id, x_center, y_center, z_center, density_kg_m3
- `/app/results/predicted_gravity.csv` with columns: x, y, z, gz_predicted_mgal
- `/app/results/inversion_summary.json` containing: `{"rms_misfit_mgal": <float>, "regularization_lambda": <float>, "n_prisms": <int>, "n_observations": <int>}`