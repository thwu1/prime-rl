#!/usr/bin/env bash
# Run INSIDE a VMVM VM. Expects /tmp/tasks.txt to exist.
set -u
ok=0; miss=0; err=0
total=$(wc -l < /tmp/tasks.txt)
while IFS= read -r task; do
    [ -z "$task" ] && continue
    code=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time 5 \
        "http://vmvm-registry.fbinfra.net/v2/terminal_bench/${task}/manifests/latest" \
        -H "Accept: application/vnd.oci.image.manifest.v1+json")
    if [ "$code" = "200" ]; then
        ok=$((ok + 1))
    elif [ "$code" = "404" ]; then
        miss=$((miss + 1))
        echo "MISSING: $task"
    else
        err=$((err + 1))
        echo "ERROR_${code}: $task"
    fi
    n=$((ok + miss + err))
    if [ $((n % 500)) -eq 0 ]; then
        echo "... checked $n/$total (ok=$ok miss=$miss err=$err)"
    fi
done < /tmp/tasks.txt
echo ""
echo "=== VERIFY: ok=$ok missing=$miss errors=$err total=$((ok+miss+err)) ==="
