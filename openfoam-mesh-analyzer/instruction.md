A mesh analysis pipeline at `/app/pipeline/` parses an OpenFOAM `blockMeshDict` for a 6-block conjugate heat transfer case and writes `/app/mesh_report.json`. The pipeline has bugs in its parser, mesh analyzer, and thermal solver modules that produce incorrect output.

The pipeline modules:
- `/app/pipeline/parser.py` — OpenFOAM dictionary parser handling C/C++ comments, nested lists, and multi-grading syntax where a mesh direction is subdivided into independently-graded segments: `((lengthFraction cellFraction expansionRatio)...)`
- `/app/pipeline/analyzer.py` — cell size computation from geometric grading formulas, block adjacency detection via shared-face topology, and solid/fluid region classification
- `/app/pipeline/cht_solver.py` — analytical 1D steady-state heat equation solver with volumetric generation, adiabatic bottom wall, and convective top interface
- `/app/pipeline/run.py` — orchestrator (correct, do not modify)

Case data is at `/app/case/system/blockMeshDict` and `/app/case/cht_params.json`. Run the pipeline with `python3 /app/pipeline/run.py` and validate with `python3 /app/validate.py`.

Fix all bugs in `parser.py`, `analyzer.py`, and `cht_solver.py` so that `python3 /app/validate.py` passes every check. Do not modify `validate.py`, `run.py`, or the case input files.