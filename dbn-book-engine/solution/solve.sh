#!/bin/bash

pip3 install zstandard==0.23.0 -q

cp /solution/reconciler.py /app/reconcile
chmod +x /app/reconcile
