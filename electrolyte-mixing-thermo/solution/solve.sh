#!/bin/bash

pip3 install pyEQL==1.5.0 -q 2>&1

cp /solution/electrolyte_engine.py /app/electrolyte_engine.py
chmod +x /app/electrolyte_engine.py
