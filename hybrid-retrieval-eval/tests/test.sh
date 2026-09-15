#!/bin/bash

pip3 install pytest==8.3.4 pytrec-eval-terrier==0.5.6 numpy==2.1.3 huggingface_hub==0.24.0 pandas==2.2.2 pyarrow==17.0.0 -q

RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?
echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
