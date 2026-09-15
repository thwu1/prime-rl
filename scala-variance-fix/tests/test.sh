#!/bin/bash

set +e

# Install scala-cli if not present
if ! command -v scala-cli &> /dev/null; then
    echo "Installing scala-cli..."
    curl -sSfL "https://github.com/VirtusLab/scala-cli/releases/latest/download/scala-cli-x86_64-pc-linux.gz" \
        -o /tmp/sc.gz
    gzip -d /tmp/sc.gz && chmod +x /tmp/sc && mv /tmp/sc /usr/local/bin/scala-cli
fi

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run pytest
RESULT=0
pytest /tests/test_state.py -v || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
