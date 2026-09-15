#!/bin/bash

cp /solution/pipeline.py /app/pipeline.py
cp /solution/fhir_transform.jq /app/fhir_transform.jq
python3 /app/pipeline.py
