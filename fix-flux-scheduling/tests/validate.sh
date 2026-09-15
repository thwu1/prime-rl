#!/bin/bash

# This script runs INSIDE a Flux instance started with --test-size=8.
# It first applies the agent's config dynamically, then submits test jobs
# and captures results for pytest validation.

RESULTS=/tmp/flux-results
mkdir -p "$RESULTS"

# Step 1: Apply the agent's fixed config to the running test instance
python3 /tests/apply_config.py /app/fixed-config/ 2>&1 | tee "$RESULTS/apply_config.log"
apply_rc=${PIPESTATUS[0]}
echo "$apply_rc" > "$RESULTS/apply_config_rc.txt"

if [ "$apply_rc" -ne 0 ]; then
    echo "APPLY_FAILED" > "$RESULTS/queue_status.txt"
    echo "1" > "$RESULTS/queue_status_rc.txt"
    echo "Configuration application failed with exit code $apply_rc"
    exit 1
fi

# Ensure queues are started and enabled (belt and suspenders)
flux queue start --all 2>/dev/null || true
flux queue enable --all 2>/dev/null || true

# Give the scheduler time to fully initialize
sleep 2

# Step 2: Queue status
flux queue status > "$RESULTS/queue_status.txt" 2>&1
echo $? > "$RESULTS/queue_status_rc.txt"
echo "Queue status:"
cat "$RESULTS/queue_status.txt"

# Step 3: Resource listing (informational + verification)
echo "Resource list (all states):"
flux resource list -o "{properties} {nnodes} {nodelist}" --state=all 2>&1 | tee "$RESULTS/resource_list.txt"

echo "Free resources:"
flux resource list -s free -o "{properties} {nnodes} {nodelist}" 2>&1 | tee "$RESULTS/free_resources.txt"

flux resource list -s free -no "{nnodes}" > "$RESULTS/free_node_count.txt" 2>&1

# NOTE: All job submissions use -t (time limit) to stay within the queue's
# policy.limits.duration.  debug=30m, batch=8h, gpu=4h.  We use -t 5m which
# is valid for all queues.

# Step 4: Submit a single debug job and capture allocated R
echo "Submitting debug job..."
debug_id=$(flux submit -q debug -t 5m -n1 true 2>"$RESULTS/debug_submit_err.txt")
submit_rc=$?
if [ $submit_rc -eq 0 ] && [ -n "$debug_id" ]; then
    if flux job wait-event -t 120 "$debug_id" clean >/dev/null 2>&1; then
        flux job info "$debug_id" R > "$RESULTS/debug_R.json" 2>&1
        echo "  debug job $debug_id completed"
    else
        echo "SUBMIT_FAILED" > "$RESULTS/debug_R.json"
        echo "  debug job $debug_id timed out"
    fi
else
    echo "SUBMIT_FAILED" > "$RESULTS/debug_R.json"
    echo "  debug job SUBMIT_FAILED (rc=$submit_rc): $(cat $RESULTS/debug_submit_err.txt 2>/dev/null)"
fi

# Step 5: Submit a single batch job and capture allocated R
echo "Submitting batch job..."
batch_id=$(flux submit -q batch -t 5m -n1 true 2>"$RESULTS/batch_submit_err.txt")
submit_rc=$?
if [ $submit_rc -eq 0 ] && [ -n "$batch_id" ]; then
    if flux job wait-event -t 120 "$batch_id" clean >/dev/null 2>&1; then
        flux job info "$batch_id" R > "$RESULTS/batch_R.json" 2>&1
        echo "  batch job $batch_id completed"
    else
        echo "SUBMIT_FAILED" > "$RESULTS/batch_R.json"
        echo "  batch job $batch_id timed out"
    fi
else
    echo "SUBMIT_FAILED" > "$RESULTS/batch_R.json"
    echo "  batch job SUBMIT_FAILED (rc=$submit_rc): $(cat $RESULTS/batch_submit_err.txt 2>/dev/null)"
fi

# Step 6: Submit a single gpu job and capture allocated R
echo "Submitting gpu job..."
gpu_id=$(flux submit -q gpu -t 5m -n1 true 2>"$RESULTS/gpu_submit_err.txt")
submit_rc=$?
if [ $submit_rc -eq 0 ] && [ -n "$gpu_id" ]; then
    if flux job wait-event -t 120 "$gpu_id" clean >/dev/null 2>&1; then
        flux job info "$gpu_id" R > "$RESULTS/gpu_R.json" 2>&1
        echo "  gpu job $gpu_id completed"
    else
        echo "SUBMIT_FAILED" > "$RESULTS/gpu_R.json"
        echo "  gpu job $gpu_id timed out"
    fi
else
    echo "SUBMIT_FAILED" > "$RESULTS/gpu_R.json"
    echo "  gpu job SUBMIT_FAILED (rc=$submit_rc): $(cat $RESULTS/gpu_submit_err.txt 2>/dev/null)"
fi

# Step 7: Submit a job without specifying queue (should default to batch)
echo "Submitting default queue job..."
default_id=$(flux submit -t 5m -n1 true 2>"$RESULTS/default_submit_err.txt")
submit_rc=$?
if [ $submit_rc -eq 0 ] && [ -n "$default_id" ]; then
    if flux job wait-event -t 120 "$default_id" clean >/dev/null 2>&1; then
        flux job info "$default_id" jobspec > "$RESULTS/default_jobspec.json" 2>&1
        flux job info "$default_id" R > "$RESULTS/default_R.json" 2>&1
        echo "  default job $default_id completed"
    else
        echo "SUBMIT_FAILED" > "$RESULTS/default_jobspec.json"
        echo "SUBMIT_FAILED" > "$RESULTS/default_R.json"
        echo "  default job $default_id timed out"
    fi
else
    echo "SUBMIT_FAILED" > "$RESULTS/default_jobspec.json"
    echo "SUBMIT_FAILED" > "$RESULTS/default_R.json"
    echo "  default job SUBMIT_FAILED (rc=$submit_rc): $(cat $RESULTS/default_submit_err.txt 2>/dev/null)"
fi

# Step 8: Queue independence: disable debug, verify batch still works
echo "Testing queue independence..."
flux queue disable debug 2>/dev/null
batch_test_id=$(flux submit -q batch -t 5m -n1 true 2>/dev/null)
echo $? > "$RESULTS/batch_after_debug_disable_rc.txt"
if [ -n "$batch_test_id" ]; then
    flux job wait-event -t 120 "$batch_test_id" clean >/dev/null 2>&1
fi
flux queue enable debug 2>/dev/null

# Step 9: Multi-node tests: verify all nodes in each group are available
# Debug: need both nodes (N=2)
echo "Submitting multi-node jobs..."
debug_multi_id=$(flux submit -q debug -t 5m -N2 -n2 true 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$debug_multi_id" ]; then
    flux job wait-event -t 120 "$debug_multi_id" clean >/dev/null 2>&1
    echo $? > "$RESULTS/debug_multi_rc.txt"
    flux job info "$debug_multi_id" R > "$RESULTS/debug_multi_R.json" 2>&1
else
    echo "1" > "$RESULTS/debug_multi_rc.txt"
fi

# Batch: need all 4 nodes (N=4)
batch_multi_id=$(flux submit -q batch -t 5m -N4 -n4 true 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$batch_multi_id" ]; then
    flux job wait-event -t 120 "$batch_multi_id" clean >/dev/null 2>&1
    echo $? > "$RESULTS/batch_multi_rc.txt"
    flux job info "$batch_multi_id" R > "$RESULTS/batch_multi_R.json" 2>&1
else
    echo "1" > "$RESULTS/batch_multi_rc.txt"
fi

# GPU: need both nodes (N=2)
gpu_multi_id=$(flux submit -q gpu -t 5m -N2 -n2 true 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$gpu_multi_id" ]; then
    flux job wait-event -t 120 "$gpu_multi_id" clean >/dev/null 2>&1
    echo $? > "$RESULTS/gpu_multi_rc.txt"
    flux job info "$gpu_multi_id" R > "$RESULTS/gpu_multi_R.json" 2>&1
else
    echo "1" > "$RESULTS/gpu_multi_rc.txt"
fi

# Step 10: Multiple single-task jobs to verify consistent isolation
echo "Submitting repeated jobs for consistency check..."
> "$RESULTS/debug_R_repeat.jsonl"
for i in 1 2 3 4 5; do
    did=$(flux submit -q debug -t 5m -n1 true 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$did" ]; then
        flux job wait-event -t 120 "$did" clean >/dev/null 2>&1
        flux job info "$did" R >> "$RESULTS/debug_R_repeat.jsonl" 2>&1
    fi
done

> "$RESULTS/batch_R_repeat.jsonl"
for i in 1 2 3 4 5; do
    bid=$(flux submit -q batch -t 5m -n1 true 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$bid" ]; then
        flux job wait-event -t 120 "$bid" clean >/dev/null 2>&1
        flux job info "$bid" R >> "$RESULTS/batch_R_repeat.jsonl" 2>&1
    fi
done

echo "Validation script complete."
