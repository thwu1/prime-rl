#!/bin/bash


cd /app

# Phase 1: Analysis, SARIF generation, exploits, fixes, and reports
python3 /solution/solver.py

# Phase 2: Capture DNS exfiltration by instrumenting the backdoor module
# Monkey-patch dns.resolve to intercept outbound queries, trigger backdoor
# with canary env var, and log intercepted queries to dns_exfil_log.json
node /solution/intercept_dns.js

echo "Done. All deliverables generated."
