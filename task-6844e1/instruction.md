The directory `/app/` contains a simulation of the Linux kernel's `balance_dirty_pages()` dirty page write throttling mechanism. It models two backing devices (SSD and HDD) with different write bandwidths and five concurrent writer tasks competing for dirty page capacity.

The simulation is broken in two ways. The throttle controller in `/app/throttle.py` has four unimplemented feedback control functions that define how writers are throttled. The simulation engine in `/app/simulator.py` contains three bugs — in global state accounting, per-device feedback calculations, and update ordering — that prevent convergence even with a correct controller.

Fix all issues so that `python3 /app/run.py` produces results in `/app/results/simulation.json` meeting these criteria:

- Average dirty page count over the last 200 ticks is within 10% of the setpoint (2400 pages)
- Coefficient of variation over the last 200 ticks is below 15%
- Per-BDI dirty page distribution is proportional to device write bandwidth
- All BDIs maintain nonzero dirty pages in steady state
- Global dirty accounting remains consistent (nr_dirty matches sum of per-BDI dirty counts)

Additionally produce:

- A convergence plot at `/app/results/convergence.png` using `gnuplot` with the template at `/app/plot_template.gp`
- `/app/results/analysis.json` containing: `"converged"` (bool), `"avg_dirty"` (float), `"setpoint"` (int), `"cv_pct"` (float), and `"bdi_ratio"` (float — ratio of SSD to HDD average dirty pages over the last 100 ticks)