#!/bin/bash

pip3 install pytest==8.3.4 -q

export PYTHONPATH=/app:${PYTHONPATH:-}

cp /solution/optimizer_impl.py /app/optimize.py
