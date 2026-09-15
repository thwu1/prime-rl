#!/bin/bash

pip3 install numpy==2.1.3 -q
pip3 install h5py==3.12.1 pytest==8.3.4 scikit-learn==1.5.2 -q

cd /app
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
