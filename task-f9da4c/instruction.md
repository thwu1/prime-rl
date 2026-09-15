Reference temperature measurements from a thermal system are stored in `/app/data/measurements.h5` (HDF5 format — inspect the file's group and dataset structure). A compiled C shared library implementing the known but incomplete physics model is at `/app/lib/thermal_model.so` with its API documented in `/app/lib/thermal_model.h`. System parameters are in `/app/config.yaml`.

The provided model significantly deviates from the measured temperature trajectory. Determine what physics the model is missing, build a corrected model that accurately reproduces the measurements and generalizes beyond the observed window, and recover an interpretable analytical equation for the missing physics.

Write results to `/app/results/`:

- `predictions_train.csv` — header `t,T_pot_pred`, training range, at least 50 points, MSE vs. reference < 0.01 K²
- `predictions_test.csv` — header `t,T_pot_pred`, extrapolation range, at least 50 points, MSE vs. ground truth < 0.5 K²
- `training_loss.txt` — MSE on training data as a single floating-point number (must be < 0.01)
- `conservation_check.txt` — energy balance residual magnitude (single float, must be < 1.0)
- `recovered_equation.txt` — the discovered missing coupling law with numerical coefficients