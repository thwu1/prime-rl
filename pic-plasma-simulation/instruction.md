A 1D electrostatic Particle-in-Cell (PIC) plasma simulation framework at `/app/` is non-functional due to multiple issues spanning its build system, C kernels, Python simulation code, and visualization. The framework models collisionless plasma in normalized units (epsilon_0 = m_e = |q_e| = n_0 = 1, giving omega_p = 1) using compiled C routines for particle-grid operations and a Python layer for the simulation loop, field solves, and diagnostics.

Diagnose and fix all issues so that:

- `make` in `/app/` builds the C kernels into a loadable shared library at `/app/lib/libpic_kernels.so`
- `python3 /app/run_langmuir.py` produces `/app/output/langmuir_results.json` with measured plasma frequency within 5% of the theoretical value and momentum conservation error below 1e-6
- `python3 /app/run_two_stream.py` produces `/app/output/two_stream_results.json` with instability growth rate within 15% of the analytic cold two-stream dispersion prediction, and field energy amplification exceeding 10x
- `gnuplot /app/plot_phase_space.gp` run from `/app/` produces `/app/output/phase_space.png`