#!/bin/bash

pip3 install requests==2.32.3 -q

cp /solution/reconcile.py /app/reconcile.py
cd /app
python3 reconcile.py
