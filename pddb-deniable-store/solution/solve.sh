#!/bin/bash

pip3 install pycryptodome==3.21.0 -q
cp /solution/pddb_complete.py /app/pddb.py
cp /solution/verify_export.sh /app/verify_export.sh
chmod +x /app/verify_export.sh
