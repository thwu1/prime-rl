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

## Provider admission epoch 3

The cap-16 affinity run cannot be edited in place. After every recorded source
job is terminal, submit the migration on x86 so the pinned Verifiers planner
and its native dependencies are available. Do not run it on the aarch64 login
host:

```bash
sbatch --export=ALL,SOURCE_DIR=/path/to/epoch-2-run,OUTPUT_DIR=/new/path/to/epoch-3-cap32-run \
  user/tianhaowu/terminal_bench_vmvm/migrate_qwen_router_admission.sbatch
```

This command calls the pinned Verifiers resume planner with the exact saved
selection, one rollout, no group scoring, no exact-token requirement, and no
shuffle. It installs only planner-approved non-error rows. It archives the
epoch-2 manifest, configs, input manifest, and provenance, retains the complete
epoch-1-to-2 policy certificate, and adds an admission certificate binding
those bytes, the ordered row lineage, and the 16/48 to 32/32 transition. The
source is never modified. The migration refuses a dirty workflow worktree, so
`migration_prime_rl` identifies the exact committed implementation that
created the child. Production cap-16 resume is rejected by the new launcher,
and incomplete publications remain marked and unlaunchable.

Run the real router/client gate on an x86 controller before cutover:

```bash
sbatch user/tianhaowu/terminal_bench_vmvm/smoke_qwen_router_affinity.sbatch
```

The gate uses the pinned vllm-router and the real Verifiers EvalClient loaded
from the production TOML. Sixty-four simultaneous calls are held by local stub
workers; exactly 32 must reach the backends before release, none may fail, and
session affinity must remain stable.

Observe cap 32 for at least 10 minutes and 256 completed provider requests.
Promote it only while all 16 workers remain healthy, non-2xx responses stay
below 1% and within 0.5 percentage points of baseline, preemptions remain zero,
backend waiting p95 stays at most two, KV-cache p95/max stay below 60%/75%,
prefix-cache hits stay at least 75% and within 10 points of baseline, TTFT p95
stays below twice baseline, and generation throughput improves at least 20%.
Any health loss, preemption, sustained queue growth, or threshold violation is
a failback signal. Cancel the epoch-3 writer and preserve it for diagnosis.
The new launcher intentionally rejects production cap 16, so resume the
immutable epoch-2 source only from an isolated worktree pinned to its recorded
`prime_rl` revision (the current source records
`9aa9dd80e8e455d45ec058563ffddaf8a51b4966`), after re-running that revision's
manifest audit. Never use the schema-3 branch for this rollback, and never
merge or overwrite the two result files manually.

## Terminal epoch-3 SFT finalization

After the final epoch-3 evaluator succeeds, submit
`finalize_qwen_sft.sbatch` as an `afterok` dependency from a clean detached
snapshot of its exact committed revision. The wrapper accepts no positional
arguments and has no source or output defaults. Its required environment binds
the code revision, disjoint source/output roots and destinations, exact source
provenance digest, expected row count, selection, and deterministic split
policy.

The finalizer requires x86_64 and a clean source tree with its required runtime
submodules initialized at the pinned gitlinks. It
fails if either source lock is held, any provenance-recorded job is nonterminal,
the run is not validated routing epoch 3, the routing index or SFT output
already exists, or any code, source, lineage, count, or digest changes. It then
runs the `label` command followed by `export_sft.py --routing-epoch-index` and
prints only aggregate counts and hashes. See the SFT export section in
`README.md` for the complete `afterok` submission template.
