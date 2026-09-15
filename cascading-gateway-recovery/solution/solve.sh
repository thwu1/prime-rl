#!/bin/bash
set -e

echo "=== Step 1: Fix corrupted database config ==="
python3 /solution/fix_database.py

echo "=== Step 2: Deploy fixed gateway worker ==="
cp /solution/gateway_worker_fixed.py /app/services/gateway_worker.py

echo "=== Step 3: Deploy fixed config pusher ==="
cp /solution/config_pusher_fixed.py /app/services/config_pusher.py

echo "=== Step 4: Deploy fixed monitor ==="
cp /solution/monitor_fixed.py /app/services/monitor.py

echo "=== Step 5: Remove stale health cache ==="
rm -f /app/data/health_cache.json

echo "=== Step 6: Fix supervisord config (remove HOTFIX_MODE) ==="
sed -i 's/,HOTFIX_MODE="lenient"//' /app/config/supervisord.conf

echo "=== Step 7: Stop any existing services ==="
if [ -f /tmp/supervisord.pid ] && kill -0 "$(cat /tmp/supervisord.pid)" 2>/dev/null; then
    supervisorctl -c /app/config/supervisord.conf shutdown 2>/dev/null || true
    sleep 2
fi
pkill -f haproxy 2>/dev/null || true
pkill -f gateway_worker 2>/dev/null || true
sleep 1

echo "=== Step 8: Start supervisord ==="
supervisord -c /app/config/supervisord.conf
sleep 3

echo "=== Step 9: Start HAProxy ==="
haproxy -f /app/config/haproxy.cfg -D
sleep 2

echo "=== Step 10: Verify system health ==="
echo "Checking workers..."
for port in 8081 8082 8083; do
    STATUS=$(curl -s --max-time 3 "http://localhost:${port}/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','FAIL'))" 2>/dev/null || echo "UNREACHABLE")
    echo "  Worker ${port}: ${STATUS}"
done

echo "Checking load balancer..."
LB_RESP=$(curl -s --max-time 3 "http://localhost:80/api/v1/users")
echo "  HAProxy response: ${LB_RESP}"

echo "Checking config validation..."
VALIDATE_RESULT=$(python3 /app/services/config_pusher.py --validate '{"name":"test","rules":null}' 2>&1 || true)
echo "  Null rules validation: ${VALIDATE_RESULT}"

echo "Checking monitor..."
MONITOR_RESP=$(python3 /app/services/monitor.py --check 2>/dev/null)
echo "  Monitor: ${MONITOR_RESP}"

echo ""
echo "=== Recovery complete ==="
