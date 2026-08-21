#!/bin/bash

set -euo pipefail

readonly setup_root=/checkpoint/ram/tianhaowu/swebench_vmvm/openhands_setup
readonly openhands_dir="$setup_root/OpenHands"
readonly output_dir=/tmp/openhands-eval
readonly metrics_path=/tmp/nemo-gym-metrics.json

export PATH="$setup_root/miniforge3/bin:$openhands_dir/.venv/bin:$PATH"
export PYTHONPATH="$openhands_dir${PYTHONPATH:+:$PYTHONPATH}"
export VIRTUAL_ENV="$openhands_dir/.venv"
export POETRY_VIRTUALENVS_IN_PROJECT=true
export POETRY_VIRTUALENVS_CREATE=false
export POETRY_VIRTUALENVS_PATH="$openhands_dir"
export RUNTIME=local
export EVAL_DISABLE_FILE_STORE=true
export NEMO_GYM_METRICS_FPATH="$metrics_path"
export NEMO_GYM_MODEL_SERVER_NAME=policy_model
export NEMO_GYM_CONFIG_DICT='{}'
export TMUX_MEMORY_LIMIT="$OPENHANDS_MEMORY_LIMIT_MB"
export COMMAND_EXEC_TIMEOUT="$OPENHANDS_COMMAND_TIMEOUT"
export USE_HINT_TEXT=false
export LOG_LEVEL=CRITICAL
export DEBUG=false
export DEBUG_LLM=false
export DEBUG_RUNTIME=false
export LOG_TO_FILE=false
export LOG_ALL_EVENTS=false

printf '{}\n' > "$metrics_path"
rm -rf "$output_dir"
mkdir -p "$output_dir"
export TMUX_TMPDIR=/tmp
unset TMUX

git config --global --add safe.directory "$openhands_dir"
cd "$openhands_dir"
./evaluation/benchmarks/swe_bench/scripts/run_infer.sh \
    llm.model \
    "$OPENHANDS_COMMIT" \
    "$OPENHANDS_AGENT_CLASS" \
    0 \
    "$OPENHANDS_MAX_ITERATIONS" \
    1 \
    princeton-nlp/SWE-bench_Verified \
    test \
    "$output_dir" \
    "$OPENHANDS_INSTANCE_ID" \
    /tmp/swebench-instance.jsonl \
    /tmp/openhands-config.toml

"$openhands_dir/.venv/bin/python" /tmp/apply-openhands-patch.py \
    "$output_dir" \
    "$OPENHANDS_INSTANCE_ID" \
    /tmp/swebench-instance.jsonl \
    /tmp/openhands-patch.json
