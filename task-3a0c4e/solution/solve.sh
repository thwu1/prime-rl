#!/bin/bash

pip3 install redis==5.0.3 -q

redis-server --daemonize yes --save "" --appendonly no
sleep 0.5

cp /solution/mvcc_solution.py /app/mvcc.py

cd /app
python3 -m pytest /tests/test_state.py -v
