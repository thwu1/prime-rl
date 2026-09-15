#!/bin/bash

# Initialize the parameter database from SQL seed data
python3 /app/init_params.py

# Fix 5 incorrect parameter values in the database using sqlite3
sqlite3 /app/clinical_params.db "UPDATE formula_coefficients SET value = 40.0 WHERE formula = 'ag_correction' AND param = 'reference_albumin';"
sqlite3 /app/clinical_params.db "UPDATE formula_coefficients SET value = 0.6 WHERE formula = 'potassium_correction' AND param = 'factor';"
sqlite3 /app/clinical_params.db "UPDATE formula_coefficients SET value = 2.0 WHERE formula = 'met_acid_compensation' AND param = 'tolerance';"
sqlite3 /app/clinical_params.db "UPDATE formula_coefficients SET value = 0.7 WHERE formula = 'met_alk_compensation' AND param = 'coefficient';"
sqlite3 /app/clinical_params.db "UPDATE clinical_thresholds SET value = 6.0 WHERE metric = 'pco2_gap' AND boundary = 'upper';"

# Deploy the corrected engine (fixes 3 code bugs)
cp /solution/abg_assess_solution.py /app/abg_assess.py
