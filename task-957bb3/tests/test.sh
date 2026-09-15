#!/bin/bash

pip3 install pytest==8.3.4 pyyaml==6.0.2 -q

# Try to install conftest for live validation tests (non-fatal if unavailable)
CONFTEST_VERSION="0.44.1"
if ! command -v conftest &>/dev/null; then
    mkdir -p /tmp/conftest-dl
    curl --fail --retry 2 -L -o /tmp/conftest-dl/conftest.tar.gz \
        "https://github.com/open-policy-agent/conftest/releases/download/v${CONFTEST_VERSION}/conftest_${CONFTEST_VERSION}_Linux_x86_64.tar.gz" 2>/dev/null && \
    tar xzf /tmp/conftest-dl/conftest.tar.gz -C /tmp/conftest-dl && \
    mv /tmp/conftest-dl/conftest /usr/local/bin/conftest && \
    chmod +x /usr/local/bin/conftest
    rm -rf /tmp/conftest-dl
fi

pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
