#!/usr/bin/env bash

pip3 install pytest==8.3.4 pyyaml==6.0.2 actuarialmath==1.1.0 numpy==2.1.3 scipy==1.15.3 pandas==2.2.3 matplotlib==3.10.1 ipython==8.31.0 -q

cd /app
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
