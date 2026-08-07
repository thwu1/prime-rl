#!/usr/bin/env bash
#SBATCH --job-name=rsci-sft-eval-watch
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=7-00:00:00
#SBATCH --requeue
#SBATCH --signal=B:USR1@300
#SBATCH --open-mode=append
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-fixed-clock-sft-v1/watcher_%j.log
#SBATCH --error=/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-fixed-clock-sft-v1/watcher_%j.log

set -euo pipefail

requeue_before_timeout() {
  echo "received pre-timeout signal; requeueing watcher job ${SLURM_JOB_ID:?}" >&2
  scontrol requeue "$SLURM_JOB_ID"
  exit 0
}
trap requeue_before_timeout USR1

STUDY_ID=verifier_defect_fixed_clock_sft_eval_v1
EXPECTED_CHECKPOINTS=82
DEFAULT_EVAL_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-fixed-clock-sft-v1
CONTROL_TMUX_SOCKET=/tmp/codex-rsci-control-20260806.sock
CONTROL_TMUX_SESSION=codex-rsci-control-20260806
CONTROL_TMUX_WINDOW=Launcher
MATERIALIZER=user/tianhaowu/rsci/materialize_fixed_clock_sft_evals.py

usage() {
  cat <<'EOF'
usage: watch_fixed_clock_sft_eval.sbatch [--dry-run] [--eval-root PATH]

Polls all 82 checkpoint paths sealed in eval_launch_manifest.json every five
minutes. Once all STABLE markers exist, dispatches the pinned evaluator
materializer through a new pane in the designated control tmux window. If that
control socket is not reachable from the watcher allocation, records a durable
ready_waiting_for_control_dispatch state and continues polling without launch.

--dry-run validates the pinned manifest and performs one non-mutating poll. It
never opens a tmux pane or submits an evaluation.
EOF
}

DRY_RUN=false
EVAL_ROOT=$DEFAULT_EVAL_ROOT
while (( $# > 0 )); do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --eval-root)
      (( $# >= 2 )) || { usage >&2; exit 2; }
      EVAL_ROOT=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

EVAL_ROOT=$(realpath "$EVAL_ROOT")
MANIFEST="$EVAL_ROOT/eval_launch_manifest.json"
SOURCE_BOOTSTRAP="$EVAL_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh"
INTERVAL_SECONDS=300

if [[ ! -f "$MANIFEST" ]]; then
  echo "evaluation launch manifest does not exist: $MANIFEST" >&2
  exit 1
fi
if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
  echo "pinned evaluator source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
  exit 1
fi

if $DRY_RUN; then
  STATE_DIR=$(mktemp -d)
  trap 'rm -rf -- "$STATE_DIR"' EXIT
else
  STATE_DIR="$EVAL_ROOT/watcher"
  mkdir -p "$STATE_DIR"
fi

exec {LOCK_FD}>"$STATE_DIR/watcher.lock"
if ! flock -n "$LOCK_FD"; then
  echo "another fixed-clock SFT evaluation watcher holds $STATE_DIR/watcher.lock"
  exit 0
fi

source "$SOURCE_BOOTSTRAP" "$EVAL_ROOT" >/dev/null
uv run --no-sync python "$MATERIALIZER" validate --eval-root "$EVAL_ROOT" >/dev/null

MANIFEST_SHA256=$(sha256sum "$MANIFEST" | cut -d' ' -f1)
if ! jq -e \
  --arg study_id "$STUDY_ID" \
  --argjson expected "$EXPECTED_CHECKPOINTS" \
  '.study_id == $study_id
   and .evaluation_count == $expected
   and (.tasks | length) == $expected
   and ([.tasks[].task_index] == [range(0; $expected)])
   and ([.tasks[].model_path] | all(type == "string" and startswith("/")))
   and ([.tasks[].model_path] | unique | length) == $expected' \
  "$MANIFEST" >/dev/null; then
  echo "evaluation manifest does not contain the expected 82 ordered, unique checkpoint paths" >&2
  exit 1
fi
mapfile -t CHECKPOINT_PATHS < <(jq -r '.tasks[].model_path' "$MANIFEST")

atomic_json() {
  local destination=$1
  local payload=$2
  local temporary
  temporary=$(mktemp "$(dirname "$destination")/.${destination##*/}.XXXXXX")
  printf '%s\n' "$payload" >"$temporary"
  chmod 0644 "$temporary"
  mv -f "$temporary" "$destination"
}

render_status() {
  local state=$1
  local message=$2
  local stable_count=$3
  local missing_json=$4
  local pane_id=${5:-}
  local receipt_path=${6:-}
  local updated_at
  updated_at=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
  jq -n \
    --argjson schema_version 1 \
    --arg study_id "$STUDY_ID" \
    --arg state "$state" \
    --arg message "$message" \
    --arg updated_at "$updated_at" \
    --arg slurm_job_id "${SLURM_JOB_ID:-}" \
    --arg manifest_path "$MANIFEST" \
    --arg manifest_sha256 "$MANIFEST_SHA256" \
    --argjson expected "$EXPECTED_CHECKPOINTS" \
    --argjson stable "$stable_count" \
    --argjson missing "$missing_json" \
    --arg control_socket "$CONTROL_TMUX_SOCKET" \
    --arg control_session "$CONTROL_TMUX_SESSION" \
    --arg control_window "$CONTROL_TMUX_WINDOW" \
    --arg pane_id "$pane_id" \
    --arg receipt_path "$receipt_path" \
    '{
      schema_version: $schema_version,
      study_id: $study_id,
      state: $state,
      message: $message,
      updated_at: $updated_at,
      slurm_job_id: (if $slurm_job_id == "" then null else $slurm_job_id end),
      eval_launch_manifest: {
        path: $manifest_path,
        sha256: $manifest_sha256
      },
      checkpoint_readiness: {
        expected: $expected,
        stable: $stable,
        missing: ($expected - $stable),
        missing_paths: $missing
      },
      control_dispatch: {
        socket: $control_socket,
        session: $control_session,
        window: $control_window,
        pane_id: (if $pane_id == "" then null else $pane_id end)
      },
      submission_receipt: (if $receipt_path == "" then null else $receipt_path end)
    }'
}

publish_status() {
  local payload=$1
  if $DRY_RUN; then
    printf '%s\n' "$payload"
  else
    atomic_json "$STATE_DIR/status.json" "$payload"
  fi
}

fail_closed() {
  local message=$1
  local stable_count=${2:-0}
  local missing_json=${3:-[]}
  local pane_id=${4:-}
  publish_status "$(render_status fail_closed "$message" "$stable_count" "$missing_json" "$pane_id")"
  echo "$message" >&2
  exit 1
}

submission_state() {
  local intent_path="$EVAL_ROOT/submissions/submission_intent.json"
  local jobs_dir="$EVAL_ROOT/submissions/jobs"
  local receipts=()
  if [[ -d "$jobs_dir" ]]; then
    shopt -s nullglob
    receipts=("$jobs_dir"/*.json)
    shopt -u nullglob
  fi
  if [[ -e "$intent_path" && ! -f "$intent_path" ]]; then
    printf 'invalid_intent\n%s\n' "$intent_path"
  elif [[ -f "$intent_path" && ${#receipts[@]} -eq 0 ]]; then
    printf 'intent_without_receipt\n%s\n' "$intent_path"
  elif [[ ! -f "$intent_path" && ${#receipts[@]} -gt 0 ]]; then
    printf 'receipt_without_intent\n%s\n' "${receipts[0]}"
  elif (( ${#receipts[@]} > 1 )); then
    printf 'multiple_receipts\n%s\n' "$jobs_dir"
  elif [[ -f "$intent_path" && ${#receipts[@]} -eq 1 ]]; then
    printf 'submitted\n%s\n' "${receipts[0]}"
  else
    printf 'unsubmitted\n\n'
  fi
}

control_target_state() {
  local observed
  if [[ ! -S "$CONTROL_TMUX_SOCKET" ]]; then
    printf 'control tmux socket is not visible from this allocation: %s' "$CONTROL_TMUX_SOCKET"
    return 1
  fi
  if ! observed=$(tmux -S "$CONTROL_TMUX_SOCKET" display-message -p \
    -t "$CONTROL_TMUX_SESSION:$CONTROL_TMUX_WINDOW" \
    '#{session_name}\t#{window_name}' 2>&1); then
    printf 'control tmux target is unreachable: %s' "$observed"
    return 1
  fi
  if [[ "$observed" != "$CONTROL_TMUX_SESSION"$'\t'"$CONTROL_TMUX_WINDOW" ]]; then
    printf 'control tmux target identity differs: %q' "$observed"
    return 1
  fi
}

dispatch_through_control_pane() {
  local bootstrap_q eval_root_q command pane_id record
  printf -v bootstrap_q '%q' "$SOURCE_BOOTSTRAP"
  printf -v eval_root_q '%q' "$EVAL_ROOT"
  command="set -euo pipefail; set -x; source $bootstrap_q $eval_root_q; exec uv run --no-sync python $MATERIALIZER submit --eval-root $eval_root_q --max-parallel 8 --confirm-study-id $STUDY_ID"
  pane_id=$(tmux -S "$CONTROL_TMUX_SOCKET" split-window -d -P -F '#{pane_id}' \
    -t "$CONTROL_TMUX_SESSION:$CONTROL_TMUX_WINDOW" "$command")
  if [[ ! "$pane_id" =~ ^%[0-9]+$ ]]; then
    echo "tmux returned an invalid pane ID: $pane_id" >&2
    return 1
  fi
  tmux -S "$CONTROL_TMUX_SOCKET" select-pane \
    -t "$pane_id" -T rsci-fixed-clock-sft-eval || true
  record=$(jq -n \
    --argjson schema_version 1 \
    --arg study_id "$STUDY_ID" \
    --arg dispatched_at "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    --arg manifest_sha256 "$MANIFEST_SHA256" \
    --arg pane_id "$pane_id" \
    --arg socket "$CONTROL_TMUX_SOCKET" \
    --arg session "$CONTROL_TMUX_SESSION" \
    --arg window "$CONTROL_TMUX_WINDOW" \
    --arg command "$command" \
    '{
      schema_version: $schema_version,
      study_id: $study_id,
      dispatched_at: $dispatched_at,
      eval_launch_manifest_sha256: $manifest_sha256,
      pane_id: $pane_id,
      control_tmux: {socket: $socket, session: $session, window: $window},
      command: $command
    }')
  atomic_json "$STATE_DIR/control_dispatch.json" "$record" || return 1
  printf '%s\n' "$pane_id"
}

while true; do
  CURRENT_MANIFEST_SHA256=$(sha256sum "$MANIFEST" | cut -d' ' -f1)
  if [[ "$CURRENT_MANIFEST_SHA256" != "$MANIFEST_SHA256" ]]; then
    fail_closed "evaluation launch manifest bytes changed while the watcher was running"
  fi

  STABLE_COUNT=0
  MISSING_PATHS=()
  for checkpoint_path in "${CHECKPOINT_PATHS[@]}"; do
    if [[ -d "$checkpoint_path" && -f "$checkpoint_path/STABLE" ]]; then
      (( STABLE_COUNT += 1 ))
    else
      MISSING_PATHS+=("$checkpoint_path")
    fi
  done
  MISSING_JSON=$(printf '%s\n' "${MISSING_PATHS[@]}" | jq -Rsc 'split("\n") | map(select(length > 0))')

  mapfile -t SUBMISSION_STATE < <(submission_state)
  case "${SUBMISSION_STATE[0]}" in
    submitted)
      RECEIPT_PATH=${SUBMISSION_STATE[1]}
      if ! RECEIPT_JOB_ID=$(jq -er \
        --arg study_id "$STUDY_ID" \
        --arg manifest_sha256 "$MANIFEST_SHA256" \
        'select(
          .schema_version == 1
          and .study_id == $study_id
          and .eval_launch_manifest_sha256 == $manifest_sha256
          and (.array_job_id | type == "number" and . > 0 and floor == .)
        ) | .array_job_id' "$RECEIPT_PATH"); then
        fail_closed "evaluation submission receipt is malformed: $RECEIPT_PATH" \
          "$STABLE_COUNT" "$MISSING_JSON"
      fi
      if [[ "${RECEIPT_PATH##*/}" != "$RECEIPT_JOB_ID.json" ]]; then
        fail_closed "evaluation submission receipt filename differs from its job ID: $RECEIPT_PATH" \
          "$STABLE_COUNT" "$MISSING_JSON"
      fi
      publish_status "$(render_status submitted \
        "immutable evaluation submission intent and receipt are present" \
        "$STABLE_COUNT" "$MISSING_JSON" "" "$RECEIPT_PATH")"
      exit 0
      ;;
    intent_without_receipt)
      fail_closed \
        "immutable evaluation submission intent exists without a receipt: ${SUBMISSION_STATE[1]}" \
        "$STABLE_COUNT" "$MISSING_JSON"
      ;;
    receipt_without_intent)
      fail_closed \
        "evaluation submission receipt exists without its immutable intent: ${SUBMISSION_STATE[1]}" \
        "$STABLE_COUNT" "$MISSING_JSON"
      ;;
    multiple_receipts)
      fail_closed "multiple evaluation submission receipts exist: ${SUBMISSION_STATE[1]}" \
        "$STABLE_COUNT" "$MISSING_JSON"
      ;;
    invalid_intent)
      fail_closed "evaluation submission intent path is not a regular file: ${SUBMISSION_STATE[1]}" \
        "$STABLE_COUNT" "$MISSING_JSON"
      ;;
    unsubmitted)
      ;;
    *)
      fail_closed "unknown evaluation submission state: ${SUBMISSION_STATE[0]}" \
        "$STABLE_COUNT" "$MISSING_JSON"
      ;;
  esac

  if (( STABLE_COUNT < EXPECTED_CHECKPOINTS )) && \
    [[ -f "$STATE_DIR/control_dispatch.json" ]]; then
    fail_closed "a control dispatch record exists while a manifest checkpoint is not STABLE" \
      "$STABLE_COUNT" "$MISSING_JSON"
  fi

  if (( STABLE_COUNT < EXPECTED_CHECKPOINTS )); then
    STATE=watching
    $DRY_RUN && STATE=dry_run_waiting
    publish_status "$(render_status "$STATE" \
      "waiting for every manifest-declared checkpoint STABLE marker" \
      "$STABLE_COUNT" "$MISSING_JSON")"
    $DRY_RUN && exit 0
    sleep "$INTERVAL_SECONDS"
    continue
  fi

  if $DRY_RUN; then
    publish_status "$(render_status dry_run_ready \
      "all 82 checkpoints are STABLE; dry-run suppressed control dispatch" \
      "$STABLE_COUNT" "$MISSING_JSON")"
    exit 0
  fi

  DISPATCH_RECORD="$STATE_DIR/control_dispatch.json"
  if [[ -f "$DISPATCH_RECORD" ]]; then
    if ! jq -e \
      --arg study_id "$STUDY_ID" \
      --arg manifest_sha256 "$MANIFEST_SHA256" \
      --arg socket "$CONTROL_TMUX_SOCKET" \
      --arg session "$CONTROL_TMUX_SESSION" \
      --arg window "$CONTROL_TMUX_WINDOW" \
      '.schema_version == 1
       and .study_id == $study_id
       and .eval_launch_manifest_sha256 == $manifest_sha256
       and (.pane_id | type == "string" and test("^%[0-9]+$"))
       and .control_tmux == {socket: $socket, session: $session, window: $window}
       and (.command | type == "string" and length > 0)' \
      "$DISPATCH_RECORD" >/dev/null; then
      fail_closed "control dispatch record is malformed or belongs to another manifest" \
        "$STABLE_COUNT" "$MISSING_JSON"
    fi
    DISPATCH_PANE=$(jq -er '.pane_id' "$DISPATCH_RECORD")
    if ! CONTROL_ERROR=$(control_target_state); then
      fail_closed \
        "a control dispatch was recorded but its tmux target is now unreachable: $CONTROL_ERROR" \
        "$STABLE_COUNT" "$MISSING_JSON" "$DISPATCH_PANE"
    fi
    if tmux -S "$CONTROL_TMUX_SOCKET" list-panes -a -F '#{pane_id}' | grep -Fxq "$DISPATCH_PANE"; then
      publish_status "$(render_status control_dispatch_started \
        "the pinned materializer is running in the recorded control pane" \
        "$STABLE_COUNT" "$MISSING_JSON" "$DISPATCH_PANE")"
      sleep "$INTERVAL_SECONDS"
      continue
    fi
    fail_closed \
      "the recorded control pane exited without an immutable submission receipt" \
      "$STABLE_COUNT" "$MISSING_JSON" "$DISPATCH_PANE"
  fi

  if ! CONTROL_ERROR=$(control_target_state); then
    publish_status "$(render_status ready_waiting_for_control_dispatch \
      "all 82 checkpoints are STABLE, but $CONTROL_ERROR" \
      "$STABLE_COUNT" "$MISSING_JSON")"
    sleep "$INTERVAL_SECONDS"
    continue
  fi

  publish_status "$(render_status ready_dispatching \
    "all 82 checkpoints are STABLE and the exact control tmux target is reachable" \
    "$STABLE_COUNT" "$MISSING_JSON")"
  if ! DISPATCH_PANE=$(dispatch_through_control_pane); then
    fail_closed "failed to create the control tmux dispatch pane" \
      "$STABLE_COUNT" "$MISSING_JSON"
  fi
  publish_status "$(render_status control_dispatch_started \
    "the pinned evaluator materializer was dispatched through a new control pane" \
    "$STABLE_COUNT" "$MISSING_JSON" "$DISPATCH_PANE")"
  sleep "$INTERVAL_SECONDS"
done
