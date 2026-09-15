#!/bin/bash

pip3 install fhirpathpy==2.2.1 -q

cp /solution/fhir_processor.py /app/fhir_engine.py
cp /solution/validate_output.py /app/validate_output.py
