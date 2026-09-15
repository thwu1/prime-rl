#!/bin/bash

# No set -e: we need graceful fallbacks for external tool downloads

pip3 install pyyaml==6.0.2 -q

# Step 1: Run the main analyzer — generates all outputs including fallback trivy/conftest JSON
python3 /solution/analyzer.py
ANALYZER_EXIT=$?
if [ $ANALYZER_EXIT -ne 0 ]; then
    echo "ERROR: analyzer.py failed with exit code $ANALYZER_EXIT"
    exit 1
fi

# Step 2: Try real trivy scan (replaces Python-generated fallback if successful)
TRIVY_VERSION="0.49.1"
TRIVY_INSTALLED=false
if ! command -v trivy &>/dev/null; then
    mkdir -p /tmp/trivy-dl
    if curl --fail --retry 2 -L -o /tmp/trivy-dl/trivy.tar.gz \
        "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" 2>/dev/null; then
        tar xzf /tmp/trivy-dl/trivy.tar.gz -C /tmp/trivy-dl 2>/dev/null
        if [ -f /tmp/trivy-dl/trivy ]; then
            mv /tmp/trivy-dl/trivy /usr/local/bin/trivy
            chmod +x /usr/local/bin/trivy
            TRIVY_INSTALLED=true
        fi
    fi
    rm -rf /tmp/trivy-dl
else
    TRIVY_INSTALLED=true
fi

if [ "$TRIVY_INSTALLED" = true ]; then
    echo "[+] Running trivy config scan..."
    trivy config --format json --exit-code 0 /app/cluster-state/ > /app/results/trivy-scan/current-state.json 2>/dev/null || true
    echo "[+] Trivy scan complete"
else
    echo "[*] Trivy unavailable; using Python-generated misconfiguration analysis"
fi

# Step 3: Try real conftest validation (replaces Python-generated fallback if successful)
CONFTEST_VERSION="0.44.1"
CONFTEST_INSTALLED=false
if ! command -v conftest &>/dev/null; then
    mkdir -p /tmp/conftest-dl
    if curl --fail --retry 2 -L -o /tmp/conftest-dl/conftest.tar.gz \
        "https://github.com/open-policy-agent/conftest/releases/download/v${CONFTEST_VERSION}/conftest_${CONFTEST_VERSION}_Linux_x86_64.tar.gz" 2>/dev/null; then
        tar xzf /tmp/conftest-dl/conftest.tar.gz -C /tmp/conftest-dl 2>/dev/null
        if [ -f /tmp/conftest-dl/conftest ]; then
            mv /tmp/conftest-dl/conftest /usr/local/bin/conftest
            chmod +x /usr/local/bin/conftest
            CONFTEST_INSTALLED=true
        fi
    fi
    rm -rf /tmp/conftest-dl
else
    CONFTEST_INSTALLED=true
fi

if [ "$CONFTEST_INSTALLED" = true ]; then
    echo "[+] Running conftest validation..."
    conftest test \
        -p /app/results/policies/ \
        --output json \
        /app/results/remediation/webapp-rbac.yaml \
        /app/results/remediation/audit-policy.yaml \
        /app/results/remediation/network-policy.yaml \
        > /app/results/conftest-results.json 2>/dev/null || true
    echo "[+] Conftest validation complete"
else
    echo "[*] Conftest unavailable; using Python-generated policy validation results"
fi

echo "Solution complete. Files written to /app/results/"
