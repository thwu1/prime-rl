A SUSY search for direct top squark pair production (T2tt simplified model) requires a full statistical analysis and exclusion limit. The analysis requirements are described in `/app/specification.md`. Monte Carlo event samples are at `/app/data/signal.root` and `/app/data/background.root` (ROOT TTrees named `events`). Physics parameters and calibration constants are in `/app/data/config.json`.

Produce:

- `/app/workspace.json` — a pyhf HistFactory workspace (loadable by `pyhf.Workspace()`) encoding the complete statistical model with signal and control region channels, signal and background samples, systematic uncertainties, and Asimov background-only observations
- `/app/results.json` — CLs hypothesis test results at signal strength μ=1 and the expected 95% CL upper limit on μ