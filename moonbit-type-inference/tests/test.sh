#!/usr/bin/env bash

export PATH="/root/.moon/bin:${PATH}"

# Install moon toolchain if not present, using Python tarfile to avoid
# container chmod failures.
if ! command -v moon &> /dev/null; then
    echo "Installing MoonBit toolchain..."
    mkdir -p /root/.moon/bin /root/.moon/lib
    curl -fsSL "https://cli.moonbitlang.com/binaries/latest/moonbit-linux-x86_64.tar.gz" -o /tmp/moonbit.tar.gz
    python3 -c "import tarfile; tarfile.open('/tmp/moonbit.tar.gz').extractall('/root/.moon', filter='data')"
    rm -f /tmp/moonbit.tar.gz
    find /root/.moon/bin -type f -exec chmod +x {} +
    find /root/.moon/bin/internal -type f -exec chmod +x {} + 2>/dev/null || true
    curl -fsSL "https://cli.moonbitlang.com/cores/core-latest.tar.gz" -o /tmp/core.tar.gz
    python3 -c "import tarfile; tarfile.open('/tmp/core.tar.gz').extractall('/root/.moon/lib', filter='data')"
    rm -f /tmp/core.tar.gz
    PATH="/root/.moon/bin:${PATH}" /root/.moon/bin/moon -C /root/.moon/lib/core bundle --warn-list -a --all
    PATH="/root/.moon/bin:${PATH}" /root/.moon/bin/moon -C /root/.moon/lib/core bundle --warn-list -a --target wasm-gc --quiet
    export PATH="/root/.moon/bin:${PATH}"
fi

pip3 install pytest==8.3.4 -q

# Restore original test file to prevent tampering
cp /opt/original_tests/hm_wbtest.mbt /app/hm_wbtest.mbt

# Run pytest
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
