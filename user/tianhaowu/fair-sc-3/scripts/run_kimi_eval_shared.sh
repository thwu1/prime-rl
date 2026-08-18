#!/bin/bash
# Config-driven eval of a model on vmvm-tb-v2 against an EXISTING (shared) OpenAI-compatible
# router. Unlike run_tb_eval.sh, there is NO deployment step — vf-eval points straight at a
# running endpoint (e.g. the shared Kimi-K2.6 LiteLLM router). See configs/eval/kimi_k26_12k_shared.toml
#
# MUST run on a CPU compute node (the vacli VM sandbox cannot be leased from the login node).
# Usage: bash run_kimi_eval_shared.sh <eval_config.toml>
set -uo pipefail
cd "$HOME/prime-rl"
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb:$HOME/prime-rl/environments/vmvm_tb_v1:$HOME/prime-rl/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1
export VACLI_LEASE_RETRIES=20 VACLI_MAX_PULL_RETRIES=10
# Internal cluster IPs (router + VM backends) are not proxy-routable.
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

[ $# -ge 1 ] || { echo "usage: $0 <eval_config.toml>" >&2; exit 2; }
CFG=$1

PARSED=$(uv run --no-sync python - "$CFG" <<'PY'
import sys, json, tomllib
c = tomllib.load(open(sys.argv[1], "rb"))
r, e = c["router"], c["eval"]
print("API_BASE\t"   + r["api_base"])
print("MODEL\t"      + r["model"])
print("API_KEY\t"    + r["api_key"])
print("STICKY\t"     + r.get("sticky_header", "x-litellm-session-id"))
print("OUTPUT_DIR\t" + e["output_dir"])
print("MAXC\t"       + str(e.get("max_concurrent", 256)))
print("ROLLOUTS\t"   + str(e.get("rollouts_per_example", 1)))
print("NREQ\t"       + str(e.get("n", -1)))
print("SAMPLING\t"   + e["sampling"])
for env in e["env"]:
    ea = json.loads(env["env_args"]); ea["dataset_path"] = env["dataset_path"]
    print("ENV\t" + "\t".join([env["vf_env"], env["dataset_path"], json.dumps(ea)]))
PY
)
[ -n "$PARSED" ] || { echo "failed to parse $CFG"; exit 1; }
get(){ echo "$PARSED" | awk -F'\t' -v k="$1" '$1==k{print substr($0,length(k)+2);exit}'; }

API_BASE=$(get API_BASE); MODEL=$(get MODEL); API_KEY=$(get API_KEY); STICKY=$(get STICKY)
OUTPUT_DIR=$(get OUTPUT_DIR); MAXC=$(get MAXC); ROLLOUTS=$(get ROLLOUTS); NREQ=$(get NREQ); SAMPLING=$(get SAMPLING)
export OPENAI_API_KEY="$API_KEY"
mkdir -p "$OUTPUT_DIR"

RC=0
while IFS=$'\t' read -r _ VF_ENV DATASET ENV_ARGS; do
  N=$NREQ; [ "$N" = "-1" ] && N=$(wc -l < "$DATASET")
  echo "=== vf-eval $VF_ENV | model=$MODEL router=$API_BASE | n=$N rollouts=$ROLLOUTS maxc=$MAXC -> $OUTPUT_DIR ==="
  uv run --no-sync vf-eval "$VF_ENV" \
    -m "$MODEL" \
    --api-base-url "$API_BASE" --api-key-var OPENAI_API_KEY \
    --api-client-type openai_chat_completions \
    --header-from-state "${STICKY}: trajectory_id" \
    -n "$N" --rollouts-per-example "$ROLLOUTS" --max-concurrent "$MAXC" \
    --sampling-args "$SAMPLING" \
    --env-args "$ENV_ARGS" \
    --state-columns turn_timings,tb_outcome,tb_error_class,tb_error_detail,infra_events,tb_test_output,tb_message,tb_exit_code,tb_report \
    --output-dir "$OUTPUT_DIR" \
    --save-results --disable-tui --env-dir-path environments || RC=1
done < <(echo "$PARSED" | awk -F'\t' '$1=="ENV"')
echo "=== done (rc=$RC) ==="
exit "$RC"
