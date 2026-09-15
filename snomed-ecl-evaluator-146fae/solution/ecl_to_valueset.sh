#!/usr/bin/env bash

set -e

# Parse arguments — accept same interface as ecl-eval
EXPR=""
for arg in "$@"; do
    if [ "$arg" != "--json" ]; then
        EXPR="$arg"
    fi
done

if [ -z "$EXPR" ]; then
    echo "Usage: ecl-to-valueset <ecl-expression>" >&2
    exit 1
fi

# Compute SHA-256 hex digest of the ECL expression using sha256sum
HASH=$(printf '%s' "$EXPR" | sha256sum | cut -d' ' -f1)

# Run ecl-eval --json and transform through jq to FHIR R4 ValueSet format
/app/ecl-eval --json "$EXPR" | jq --arg hash "$HASH" '{
  resourceType: "ValueSet",
  status: "active",
  expansion: {
    identifier: ("urn:sha256:" + $hash),
    timestamp: "2024-01-01T00:00:00Z",
    total: .total,
    contains: [.expansion[] | {
      system: "http://snomed.info/sct",
      code: .conceptId,
      display: .display
    }]
  }
}'
