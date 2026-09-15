The directory `/app/` contains a structural analysis pipeline (`frame3d.py`) that computes elastic critical load factors for 3D beam frame buckling analysis. The pipeline currently produces incorrect results for all tested configurations.

Run `python3 /app/validate.py` to observe the current failure. The script compares the pipeline's output against a known analytical solution for a standard cantilever column.

Additional components in `/app/` that also require attention:

- `/app/octave_ref/verify_kg.m` — An independent Octave verification script. Run with `octave --no-gui --silent /app/octave_ref/verify_kg.m` to see its current state.
- `/app/process_model.py` — Reads structural models from TOML files in `/app/models/` and runs the analysis pipeline. Test with `python3 /app/process_model.py /app/models/cantilever_circular.toml`.
- `/app/reference.md` — Theoretical reference for the analysis methodology and relevant literature.

Investigate and fix all issues so the pipeline produces correct results for general 3D beam frames, including configurations with combined axial, bending, and torsional loading.