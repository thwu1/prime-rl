Four FDS (Fire Dynamics Simulator) solid-phase simulation cases in `/app/cases/` model 1D transient heat conduction through a slab. Corresponding numerical output (temperature histories at monitoring locations through the slab depth) is in `/app/data/` as CSV files. Operational parameters are in `/app/config.json`.

Build `/app/verify.py` that independently verifies each simulation's numerical accuracy against the exact analytical solution for the boundary-value problem specified in each FDS input file, then produces:

- `/app/verification_report.json` with top-level keys `cases` (dict keyed by case name), `tolerance` (float), `overall_status` ("PASS"/"FAIL"), `pass_count` (int), `fail_count` (int). Each case entry must contain: `biot_number` (float), `eigenvalues` (first 5, list of floats), `max_absolute_error` (float), `max_relative_error` (float), `status` ("PASS" when max relative error of temperature departure from the initial condition remains below the configured threshold, "FAIL" otherwise), and `device_errors` (dict keyed by device ID, each with `max_absolute_error` and `max_relative_error`).

- `/app/plots/` directory containing one PNG per case (e.g. `case_a.png`) generated with gnuplot, overlaying simulation data (points) and analytical solution (lines) for every monitored location over time.

Execute: `python3 /app/verify.py`