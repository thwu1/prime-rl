#!/bin/bash

pip3 install pytest==8.3.4 networkx==3.4.2 numpy==2.1.3 -q

cd /app
make clean
make

cd /
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
