#!/usr/bin/env bash

pip3 install psycopg2-binary==2.9.10 -q

cd /app
python3 /solution/solver.py
