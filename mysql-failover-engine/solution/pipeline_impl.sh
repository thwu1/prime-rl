#!/bin/bash
# MySQL HA Failover Recovery Pipeline - Full Implementation
#

set -euo pipefail

TOPOLOGY="$1"
OUTPUT_DIR="$2"

# ---------------------------------------------------------------
# Step 1: Validate topology JSON with jq
# ---------------------------------------------------------------

CLUSTER_NAME=$(jq -r '.cluster.name // empty' "$TOPOLOGY")
if [ -z "$CLUSTER_NAME" ]; then
    echo "ERROR: Invalid topology - missing cluster.name" >&2
    exit 1
fi

INSTANCE_COUNT=$(jq '.instances | length' "$TOPOLOGY")
if [ "$INSTANCE_COUNT" -eq 0 ]; then
    echo "ERROR: No instances in topology" >&2
    exit 1
fi

# Validate required nested fields exist
jq -e '.instances[0].key.host and .instances[0].role_info and .instances[0].replication and .instances[0].gtid and .instances[0].semi_sync' "$TOPOLOGY" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Topology instances missing required fields" >&2
    exit 1
fi

# ---------------------------------------------------------------
# Step 2: Run analysis engine
# ---------------------------------------------------------------

mkdir -p "$OUTPUT_DIR"

REPORT=$(python3 /app/analyze.py "$TOPOLOGY")
echo "$REPORT" > "$OUTPUT_DIR/report.json"

# ---------------------------------------------------------------
# Step 3: Extract results with jq for downstream processing
# ---------------------------------------------------------------

RECOVERY_ATTEMPTED=$(echo "$REPORT" | jq -r '.recovery_attempted')
PROMOTED_SERVER=$(echo "$REPORT" | jq -r '.promoted_server // "null"')
IS_MASTER=$(echo "$REPORT" | jq -r '.recovery_target_is_master // "null"')

# ---------------------------------------------------------------
# Step 4: Update Consul KV for master-level recoveries
# ---------------------------------------------------------------

if [ "$RECOVERY_ATTEMPTED" = "true" ] && [ "$PROMOTED_SERVER" != "null" ] && [ "$IS_MASTER" = "true" ]; then
    PROMOTED_HOST=$(echo "$PROMOTED_SERVER" | cut -d: -f1)
    PROMOTED_PORT=$(echo "$PROMOTED_SERVER" | cut -d: -f2)

    CONSUL_VAL=$(jq -n --arg host "$PROMOTED_HOST" --argjson port "$PROMOTED_PORT" \
        '{"hostname": $host, "port": $port}')

    consul kv put "mysql/${CLUSTER_NAME}/primary" "$CONSUL_VAL"
fi

# ---------------------------------------------------------------
# Step 5: Generate HAProxy config when recovery is attempted
# ---------------------------------------------------------------

if [ "$RECOVERY_ATTEMPTED" = "true" ] && [ "$PROMOTED_SERVER" != "null" ]; then
    PROMOTED_HOST=$(echo "$PROMOTED_SERVER" | cut -d: -f1)
    PROMOTED_PORT=$(echo "$PROMOTED_SERVER" | cut -d: -f2)

    # Sanitize cluster name for HAProxy backend name (replace hyphens)
    BACKEND_NAME=$(echo "$CLUSTER_NAME" | sed 's/-/_/g')

    # Generate HAProxy config from template using sed substitution
    sed -e "s/\${CLUSTER_NAME}/${BACKEND_NAME}/g" \
        -e "s/\${PROMOTED_HOST}/${PROMOTED_HOST}/g" \
        -e "s/\${PROMOTED_PORT}/${PROMOTED_PORT}/g" \
        /app/templates/haproxy_backend.cfg.tmpl > "$OUTPUT_DIR/haproxy.cfg"

    # Validate the generated config
    if ! haproxy -c -f "$OUTPUT_DIR/haproxy.cfg" > /dev/null 2>&1; then
        echo "WARNING: Generated HAProxy config failed validation" >&2
    fi
fi

echo "Pipeline completed for cluster: $CLUSTER_NAME"
