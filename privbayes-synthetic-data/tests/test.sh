#!/bin/bash

pip3 install pytest==8.3.4 pandas==2.2.3 numpy==2.1.3 scipy==1.14.1 scikit-learn==1.6.0 -q

# Run the solution with primary parameters (epsilon=1.0, 500 rows)
python3 /app/dp_synth.py \
    --input /app/data/input.csv \
    --epsilon 1.0 \
    --max-parents 2 \
    --seed 42 \
    --num-rows 500 \
    --output-desc /app/output/description.json \
    --output-csv /app/output/synthetic.csv \
    --privacy-report /app/output/privacy_report.json

# Run again with same params for determinism test
python3 /app/dp_synth.py \
    --input /app/data/input.csv \
    --epsilon 1.0 \
    --max-parents 2 \
    --seed 42 \
    --num-rows 500 \
    --output-desc /app/output/description_2.json \
    --output-csv /app/output/synthetic_2.csv \
    --privacy-report /app/output/privacy_report_2.json

# Run with different epsilon and num-rows for multi-parameter validation
python3 /app/dp_synth.py \
    --input /app/data/input.csv \
    --epsilon 0.5 \
    --max-parents 2 \
    --seed 42 \
    --num-rows 300 \
    --output-desc /app/output/description_low_eps.json \
    --output-csv /app/output/synthetic_low_eps.csv \
    --privacy-report /app/output/privacy_report_low_eps.json

# Run pytest
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
