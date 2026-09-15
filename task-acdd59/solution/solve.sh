#!/bin/bash

pip3 install lark==1.2.2 -q

cd /app
python3 /solution/imp_interpreter.py

# Validate output against schema
check-jsonschema --schemafile /app/schema/output_schema.json /app/results.json
