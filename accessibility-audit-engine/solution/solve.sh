#!/bin/bash

pip3 install beautifulsoup4==4.12.3 tinycss2==1.4.0 -q

cp /solution/audit_engine.py /app/audit.py
python3 /app/audit.py /app/pages/ /app/report.json
