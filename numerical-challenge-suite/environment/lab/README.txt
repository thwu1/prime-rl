Numerical Experiments Workspace
===============================
This directory contains five independent computational experiments,
each producing a calibration constant for the simulation pipeline.

Directory structure:
  experiments/    - individual experiment directories
  results.json    - collected output from all experiments

Each experiment can be run independently:
    cd experiments/<name>
    python3 compute.py

Current outputs are collected in results.json.

STATUS: Some downstream simulations using these calibration values
have been producing incorrect results. The source of the errors
has not yet been identified.
