#!/bin/bash

# Deploy the correct reference processor
cp /solution/fhir_transaction.py /app/processor.py

# Deploy the validation toolkit
mkdir -p /app/validation
cp /solution/check_references.sh /app/validation/check_references.sh
cp /solution/check_status_codes.sh /app/validation/check_status_codes.sh
cp /solution/check_versioning.sh /app/validation/check_versioning.sh
cp /solution/diff_processors.sh /app/validation/diff_processors.sh
chmod +x /app/validation/*.sh

# Run the reference processor to generate conformant output
python3 /app/processor.py \
  --bundle /app/data/transaction_bundle.json \
  --state-dir /app/data/server_state \
  --output-dir /app/output \
  --base-url http://fhir.example.org

# Run the conformance evaluation to generate the comparative report
python3 /solution/evaluate_processors.py
