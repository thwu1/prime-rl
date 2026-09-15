#!/bin/bash

pip3 install pyyaml==6.0.2 jsonschema==4.23.0 -q
cp /solution/analyzer.py /app/dioptra_analyzer.py
chmod +x /app/dioptra_analyzer.py
