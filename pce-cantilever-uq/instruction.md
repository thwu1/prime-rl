A cantilever beam simulator is available at `/app/cantilever.py` with a complete problem configuration in `/app/problem_spec.json`. The configuration defines four uncertain input variables (R, E, X, Y) with normal distributions, a fixed design point (w, t), beam parameters, and a detailed output schema specifying every required result.

Create `/app/uq_pipeline.py` — a Python script that propagates the input uncertainties through the cantilever beam model and writes numerically accurate results to `/app/results.json`.

Required outputs (see the output schema in `/app/problem_spec.json` for exact structure and definitions):

- Statistical moments (mean, standard deviation) of both stress and displacement responses
- First-order and total Sobol sensitivity indices for each uncertain variable on each response
- Probability of structural failure and reliability index for two limit states: (a) stress exceeding yield strength R, and (b) normalized displacement exceeding 1.0

The script must read all parameters from `/app/problem_spec.json` — including the configuration settings that govern computational accuracy — and must adapt correctly when those parameters change. Running `python3 /app/uq_pipeline.py` must produce `/app/results.json` without any additional arguments.