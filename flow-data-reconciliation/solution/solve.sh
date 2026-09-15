#!/bin/bash

pip3 install --break-system-packages numpy==2.1.3 scipy==1.14.1 -q 2>&1 || \
    python3 -m pip install --break-system-packages numpy==2.1.3 scipy==1.14.1 -q 2>&1

cd /app && python3 /solution/reconcile.py
