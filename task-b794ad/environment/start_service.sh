#!/bin/bash
cd /app
nohup python3 /app/server.py > /var/log/waf/server.log 2>&1 &
echo $! > /tmp/waf_server.pid
echo "WAF query service started on http://localhost:5000"
echo "Endpoints:"
echo "  POST /query  - JSON body: {\"where\": \"<clause>\"}"
echo "  GET  /health - Health check"
echo "Logs: /var/log/waf/requests.jsonl"
