A GROMACS alchemical free energy perturbation pipeline at `/app/` computes the solvation free energy of methanol in water via thermodynamic integration with Bennett Acceptance Ratio (BAR) analysis. The setup includes a pre-equilibrated methanol-in-water system, a self-contained OPLS-AA/SPC topology, an MDP template for 11 lambda windows, and a shell script to run the pipeline.

The pipeline is broken. Multiple bugs across `/app/fep.mdp` (the MDP template) and `/app/run_fep.sh` (the run script) prevent the calculation from executing correctly and/or produce physically meaningless results. Some bugs cause immediate failures; others are silent and yield wrong free energies.

Identify and fix all issues, execute the corrected free energy calculation across all lambda windows, perform BAR analysis using `gmx bar`, and write the computed solvation free energy (in kJ/mol, a single floating-point number) to `/app/result.txt`.

Relevant files:
- `/app/system.gro` — Energy-minimized methanol in SPC water (coordinates)
- `/app/topol.top` — Self-contained topology with OPLS-AA parameters and SPC water
- `/app/fep.mdp` — FEP MDP template (contains bugs)
- `/app/run_fep.sh` — Pipeline script (contains a bug)