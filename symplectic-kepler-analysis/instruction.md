A numerical integration benchmark suite in `/app/` evaluates five time-stepping methods (labeled A through E) for long-term simulation of a gravitational two-body orbit. Running `python3 /app/benchmark.py` measures convergence rates and conservation properties and writes output to `/app/results.json`.

The methods span multiple accuracy classes and include both general-purpose and structure-preserving integrators. The codebase contains defects that cause the benchmark to produce incorrect or misleading output.

In addition to auditing and correcting all defects, the benchmark must be extended:

- Implement a sixth-order symplectic integrator (`method_f`) in `/app/methods.py` by recursively applying the existing composition framework to the corrected fourth-order composed method. Include `method_f` in all benchmark convergence and conservation tests.

- Instrument the code with force-evaluation counting to measure computational cost. Produce `/app/work_precision.csv` with columns `method,force_evals_per_step,error_at_500_steps` for all six methods. The `force_evals_per_step` values must be empirically measured by wrapping the force function with a call counter, not manually computed.

- Generate a log-log convergence plot at `/app/convergence.png` using `gnuplot` (pre-installed), showing phase-space error versus step count for all six methods with individually labeled curves.

Produce corrected `/app/results.json` covering all six methods, `/app/work_precision.csv`, and `/app/convergence.png`.