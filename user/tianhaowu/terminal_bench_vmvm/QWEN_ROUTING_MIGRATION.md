# Qwen direct-router routing epochs

The schema-2 direct Qwen launcher uses `consistent_hash` with exactly the
`x-session-id` request-ID header. Schema-1 outputs used `round_robin` and did not
record a request-ID header. The new launcher rejects them before starting a
router or evaluator.

Changing the policy does not alter an already durable trace's own identity.
Verifiers retains good rows and creates a new trace ID for every missing or
errored rollout it reruns. A same-directory policy switch is nevertheless not
safe as a run-level artifact: one manifest would falsely describe rows produced
under two routing policies, and resume atomically filters and reorders the
retained rows before appending replacements.

Prefer finishing or resuming a schema-1 run with its pinned legacy code. Start a
fresh schema-2 output for an affinity run. If keeping legacy good rows is worth
the mixed routing epochs, `migrate_qwen_router_affinity.py` implements this
fail-closed protocol:

1. Require the source Slurm job to be terminal and both writer locks to be
   acquirable. Audit the source with its pinned code. Never migrate a live
   directory.
2. Reflink or copy the complete source into a new, exclusively created output
   directory. Keep the source immutable. Verify the copy against hashes of
   `config.toml`, `inputs/manifest.json`, `provenance.txt`,
   `direct_workers.json`, and `results.jsonl`.
3. Use the pinned Verifiers resume planner to construct the exact retained-row
   byte sequence without printing task IDs or trace content. Record its SHA-256,
   byte length, retained-row count, and aggregate owed-rollout count. Atomically
   install that sequence in the child directory before any new model request.
   Preserve the original `inputs/source_config.toml` as
   `inputs/source_config.epoch-1.toml`; rewrite the active source config and
   saved config to child-local task/image snapshots, then update the input
   manifest's source/snapshot records and source-config digest consistently.
4. Preserve the old manifest as `direct_workers.epoch-1.json`. Generate a new
   schema-2 active manifest and a separate transition certificate that bind the
   old-manifest hash, unchanged deployment spec and worker-bundle hashes, and
   epoch 2's exact `consistent_hash` / `x-session-id` contract.
5. Append the certificate hash and child-manifest routing contract to the child
   provenance. Resume only the cloned child; the normal launcher appends its new
   Slurm job ID and repeats the manifest digest and routing contract.
6. At the initial boundary, the validator requires the exact certified retained
   byte sequence. Verifiers deliberately rewrites retained rows into task-index
   order on every resume, so later validation uses the certificate's ordered
   per-row SHA-256 list and requires every epoch-1 row exactly once. Run the
   `label` command after the final job; its row-hash join emits a durable
   per-result routing-epoch index even after such reordering. Do not issue a
   homogeneous-routing certificate for this child.

The transition certificate should contain exactly these logical records:

```text
schema_version = 1
kind = "qwen-direct-router-policy-transition"
source = { canonical_path, slurm_job_id, prime_rl, verifiers, renderers,
           config_sha256, source_config_sha256, inputs_manifest_sha256, provenance_sha256,
           results_sha256, results_size_bytes, direct_workers_sha256 }
resume_plan = { retained_results_sha256, retained_results_size_bytes,
                retained_row_count, owed_rollout_count,
                epoch1_row_hashes_sha256 }
from_router = { manifest_schema_version = 1, policy = "round_robin",
                request_id_headers = [] }
to_router = { manifest_schema_version, policy = "consistent_hash",
              request_id_headers = ["x-session-id"], spec_sha256,
              endpoint_bundle_sha256, direct_workers_sha256 }
child = { canonical_path, routing_epoch = 2, config_sha256,
          source_config_sha256, inputs_manifest_sha256 }
```

All hashes are lowercase SHA-256 over exact file bytes. Paths are canonical.
Reject extra or missing keys, changed task approval/config hashes, changed
worker identity, a nonempty destination, an active source lock, or any mismatch
after the copy. The tool never modifies the source directory.

```bash
python user/tianhaowu/terminal_bench_vmvm/migrate_qwen_router_affinity.py migrate \
  --source-dir /path/to/terminal-schema1-output \
  --output-dir /new/path/to/affinity-epoch2-output

python user/tianhaowu/terminal_bench_vmvm/migrate_qwen_router_affinity.py label \
  --run-dir /new/path/to/affinity-epoch2-output
```

Both commands are wait-free: they fail if any recorded Slurm job is live or
either writer lock is held. `label` writes only row number, row SHA-256, and
routing epoch; it never emits task IDs or trace content.
