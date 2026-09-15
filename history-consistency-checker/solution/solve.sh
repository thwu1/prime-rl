#!/bin/bash

cp /solution/checker.py /app/checker.py
cp /solution/audit.sh /app/audit.sh
chmod +x /app/checker.py /app/audit.sh
bash /app/audit.sh
