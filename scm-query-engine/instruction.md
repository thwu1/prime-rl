A causal inference analysis workspace is at `/app/`. The causal graph structure is defined in `/app/graph.yaml` with node attributes `visible` (boolean) and `num_values` (int), plus a list of directed edges. Mechanism definitions are in `/app/mechanisms.py`. Query and analysis task specifications are in `/app/queries.yaml`. The required output database schema is at `/app/schema.sql`.

The SCM infrastructure in `/app/causal_lib/` (`scm.py`, `variable.py`) has two modules with incomplete implementations:

**`/app/causal_lib/query_engine.py`** — `QueryEngine` class with `evaluate_ate` and `evaluate_ctf_te` methods for interventional and counterfactual causal effect estimation using Monte Carlo simulation.

**`/app/causal_lib/graph_analysis.py`** — Four functions: `build_mutilated_graph` (DAG modification for causal reasoning), `is_d_separated` (conditional independence testing in directed graphs), `extract_latent_projection` (hidden variable projection to ADMG), `find_backdoor_adjustment` (covariate adjustment set identification).

Complete these modules, then build `/app/run_pipeline.py` — a pipeline that loads the graph from `/app/graph.yaml`, constructs the SCM with the provided mechanisms, executes all queries from `/app/queries.yaml`, performs graph analysis (d-separation, latent projection, backdoor adjustment), writes all results to `/app/results.db` conforming to `/app/schema.sql`, and generates the ADMG as `/app/admg.dot` in Graphviz DOT format using pydot with directed edges and bidirected edges (using `dir=both`).

Mathematical specifications for all causal quantities are in `/app/specifications.md`. Run the pipeline after implementation to produce the output files.