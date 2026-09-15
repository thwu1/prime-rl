LABS Optimization Framework - Reference Data
=============================================

This directory contains reference materials for the LABS (Low Autocorrelation
Binary Sequences) optimization framework project.

Files:
  spec.json        - Mathematical specification: problem definition, Hamiltonian
                     interaction index formulas, counterdiabatic schedule
                     parameters, symmetry group, incremental energy updates
  reference.db     - SQLite database with validation data
  known_optima.csv - Quick-reference table of known optimal LABS energies
  README.txt       - This file

SQLite database tables (reference.db):
  known_optima              - Optimal energies and merit factors by sequence length N
  interaction_counts        - G2/G4 set sizes and Gamma1 values for N=4..10
  g2_exact                  - Exact 2-body interaction index sets for small N (JSON)
  g4_exact                  - Exact 4-body interaction index sets for small N (JSON)
  theta_reference           - Reference theta parameter values at specific (N,t,dt,T)
  gamma2_reference          - Reference Gamma2 values at specific (N, lambda)
  energy_examples           - Known sequence/energy pairs for validation
  autocorrelation_examples  - Individual autocorrelation coefficient C_k values

Query example:
  sqlite3 /app/data/reference.db "SELECT * FROM known_optima;"
  sqlite3 /app/data/reference.db "SELECT * FROM interaction_counts;"
  sqlite3 /app/data/reference.db "SELECT pairs_json FROM g2_exact WHERE N=5;"
