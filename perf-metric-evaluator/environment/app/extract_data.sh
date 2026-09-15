#!/bin/bash
# Extract benchmark data from SQLite database to JSON format for pipeline processing
# Dependencies: sqlite3, jq

DB="/app/data/benchmark.db"
OUT="/app/data/results.json"

# Step 1: Extract config values
CONFIG=$(sqlite3 "$DB" -json "SELECT key, value FROM config" | \
  jq 'reduce .[] as $r ({}; .[$r.key] = ($r.value | tonumber))')

# Step 2: Extract tasks with human times (ordered by benchmark sequence)
TASKS=$(sqlite3 "$DB" -json "
  SELECT t.task_id, t.description, b.human_time, b.seq
  FROM tasks t
  JOIN benchmarks b ON t.task_id = b.task_id
  ORDER BY t.task_id, b.seq
" | jq '
  group_by(.task_id) | [.[] | {
    task_id: .[0].task_id,
    description: .[0].description,
    human_times: [.[] | .human_time]
  }]
')

# Step 3: Extract attempt data with per-benchmark timing measurements
# Each row is one timing measurement; grouped by attempt in jq
ATTEMPTS=$(sqlite3 "$DB" -json "
  SELECT a.task_id, a.model_id, a.attempt_num, a.correct, a.patch,
         t.model_time, b.seq
  FROM attempts a
  JOIN timings t ON a.id = t.attempt_id
  JOIN benchmarks b ON t.benchmark_id = b.id
  ORDER BY a.task_id, a.model_id, a.attempt_num, b.seq
" | jq '
  group_by([.task_id, .model_id, .attempt_num]) |
  [.[] | {
    task_id: .[0].task_id,
    model_id: .[0].model_id,
    attempt: .[0].attempt_num,
    correct: .[0].correct,
    patch: .[0].patch,
    times: [.[] | .model_time]
  }]
')

# Step 4: Assemble into the nested format expected by the pipeline
jq -n --argjson tasks "$TASKS" \
      --argjson attempts "$ATTEMPTS" \
      --argjson config "$CONFIG" '
{
  tasks: $tasks,
  model_results: (
    $attempts | group_by(.model_id) |
    reduce .[] as $mg ({};
      . + {($mg[0].model_id): (
        $mg | group_by(.task_id) |
        reduce .[] as $tg ({};
          . + {($tg[0].task_id): {
            attempts: [$tg[] | {attempt, times, correct, patch}]
          }}
        )
      )}
    )
  ),
  config: $config
}' > "$OUT"

echo "Data extracted to $OUT"
