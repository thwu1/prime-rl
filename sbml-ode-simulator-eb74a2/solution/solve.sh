#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

cp /solution/sbml_sim.py /app/sbml_sim.py

cd /app

# Run simulator on all 4 cases
for case in case_001 case_002 case_003 case_004; do
    python3 /app/sbml_sim.py \
        /app/models/${case}/model.xml \
        /app/models/${case}/settings.txt \
        /app/output_${case}.csv
done

# Generate conformance report
python3 /solution/generate_report.py
