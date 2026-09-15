#!/bin/bash

pip3 install beautifulsoup4==4.12.3 -q

cp /solution/audit.py /app/audit.py
python3 /app/audit.py /app/pages/ /app/report.json
