#!/bin/bash

set -euo pipefail

readonly setup_root=/checkpoint/ram/tianhaowu/swebench_vmvm/openhands_sdk_setup
readonly python_bin="$setup_root/.venv/bin/python"
readonly ready=/tmp/openhands-sdk-proxy.ready
readonly proxy_audit=/tmp/openhands-sdk-proxy-audit.json
readonly agent_result=/tmp/openhands-sdk-result.json
readonly agent_events=/tmp/openhands-sdk-events.json

rm -f "$ready" "$proxy_audit" "$agent_result" "$agent_events" /tmp/openhands-sdk-agent-error.json

"$python_bin" /tmp/openhands-sdk-proxy.py \
    --system-prompt /tmp/openhands-sdk-system.txt \
    --audit "$proxy_audit" \
    --ready "$ready" \
    >/tmp/openhands-sdk-proxy.log 2>&1 &
proxy_pid=$!

cleanup() {
    kill "$proxy_pid" 2>/dev/null || true
    wait "$proxy_pid" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 120); do
    if [ -s "$ready" ]; then
        break
    fi
    if ! kill -0 "$proxy_pid" 2>/dev/null; then
        tail -n 200 /tmp/openhands-sdk-proxy.log >&2
        exit 1
    fi
    sleep 0.5
done
test -s "$ready"

proxy_port=$(tr -d '[:space:]' < "$ready")
export LLM_BASE_URL="http://127.0.0.1:${proxy_port}/v1"
export LLM_API_KEY=local-parity-proxy
export LLM_TIMEOUT="$OPENHANDS_REQUEST_TIMEOUT"
export MAX_ITERATIONS="$OPENHANDS_MAX_ITERATIONS"
export LITELLM_LOG=ERROR
export LITELLM_TELEMETRY=false
export LMNR_DISABLE_TRACING=true
export LLM_NATIVE_TOOL_CALLING=true
export OPENHANDS_SUPPRESS_BANNER=1
export SECURITY_CONFIRMATION_MODE=false
export SECURITY_ENABLE_SECURITY_ANALYZER=false
export OH_PRELOAD_TOOLS=false
unset OPENHANDS_UPSTREAM_SECRET OPENHANDS_UPSTREAM_URL

cd "$OPENHANDS_WORKSPACE"
"$python_bin" /tmp/openhands-sdk-runner.py \
    --instruction /tmp/openhands-sdk-instruction.txt \
    --result "$agent_result" \
    --events "$agent_events"
