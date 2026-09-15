#!/usr/bin/env bash

cd /app
mkdir -p /app/results

python3 /solution/analyzer.py

dot -Tsvg /app/results/traceability.dot -o /app/results/traceability.svg

jq '{
    failed_verifications: [.verification_verdicts[] | select(.verdict == "fail")],
    mass_violations: .mass_analysis.violations,
    power_violations: .power_analysis.power_violations,
    orphan_requirements: .orphan_requirements,
    unallocated_actions: .unallocated_actions
}' /app/results/conformance.json > /app/results/nonconformance.json
