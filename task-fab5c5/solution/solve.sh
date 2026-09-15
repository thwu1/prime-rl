#!/bin/bash

set -e

# Apply all fixes to the cascading configuration failure
python3 /solution/fix_system.py

# Verify fixes work
echo ""
echo "=== Verification ==="

echo "Testing feature generator against all shards..."
for shard in /app/db/shards/shard_*.db; do
    output=$(python3 /app/generator/generate.py "$shard")
    echo "  $output"
done

echo ""
echo "Testing proxy with valid feature file..."
python3 -c "
import sys
sys.path.insert(0, '/app')
from proxy.server import ProxyServer
server = ProxyServer()
server.initialize()
result = server.handle_request({'user_agent_entropy': 0.5, 'request_rate_1m': 10})
assert result['status'] == 200, f'Proxy returned unexpected status: {result}'
print('  Proxy test: OK (status 200)')
"

echo ""
echo "Testing proxy resilience with oversized feature file..."
python3 -c "
import json, sys, os
sys.path.insert(0, '/app')

oversized = {
    'version': 2, 'generated_at': '2025-11-18T12:00:00', 'shard_source': 'test',
    'features': [{'name': f'f_{i}', 'type': 'Float64', 'enabled': True, 'weight': 1.0} for i in range(250)],
    'feature_count': 250
}
os.makedirs('/app/features', exist_ok=True)
with open('/app/features/bot_features.json', 'w') as f:
    json.dump(oversized, f)

from proxy.server import ProxyServer
server = ProxyServer()
try:
    server.initialize()
    result = server.handle_request({'user_agent_entropy': 0.5})
    print(f'  Proxy resilience test: OK (handled gracefully, status {result[\"status\"]})')
except SystemExit:
    print('  FAILED: Proxy crashed with SystemExit')
    sys.exit(1)
"

# Regenerate correct feature file
python3 /app/generator/generate.py /app/db/shards/shard_0.db > /dev/null

echo ""
echo "Testing cfctl config validate..."
python3 /app/cfctl config validate /app/features/bot_features.json

echo ""
echo "Running cfctl verify..."
python3 /app/cfctl verify

echo ""
echo "=== All verifications passed ==="
