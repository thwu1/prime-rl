# Legacy Kimi smoke timeout recovery controller v2

Status: **unarmed**. Schema 2 invalidates every v1 plan and authorization. This
source bundle creates no plan, runtime snapshot,
terminal gate, approval, launch reservation, log directory, output directory,
process, or Slurm job. Those namespaces must remain absent until a separately
reviewed execution plan names them.

This controller exists only for the legacy two-task smoke whose source revision
predates the in-tree timeout-recovery policy. It deliberately forbids the
one-task/composite path. If recovery is ever authorized, it launches both
original smoke tasks in a fresh output directory with `resume=false` and reuses
zero legacy result rows.

## Safety contract

`certify-trigger` can publish `terminal_quiescence_gate.json` only when all of
the following remain true for six samples spanning at least 120 seconds:

- the exact legacy allocation is terminal `FAILED` or `TIMEOUT`, restart count
  is zero, its allocation and every step are terminal in accounting, and no
  allocation or step remains in the live queue;
- the original writer lock is held nonblocking for the entire window and its
  device/inode/metadata identity is unchanged before, during, and after all
  artifact reads;
- one plan-bound global recovery lock is held with the writer lock through
  every fallible gate, fsync, and publication step;
- the guard-linked original run's identity, invocation, results, guard receipt,
  exact input snapshots, provenance, concurrency telemetry, task file, and
  config files are captured once under stable file descriptors; every run-local
  parser consumes only those captured bytes, so pathname swap/restore cannot
  influence eligibility; the run is fresh (`resume=false`), contains exactly two
  uniquely mapped rows in durable order (one strict clean row followed by one
  completed, single-error `harness_timeout` row), and its four durable
  attestation artifacts do not change; this shape is explicitly ineligible for
  1+1 retention and authorizes only a fresh rerun of both tasks;
- no canonical or supplemental successful smoke checkpoint exists;
- the exact current deployment generation has restart count zero, exactly two
  healthy routes, aggregate running/waiting request counts of zero, and exactly
  unchanged cumulative generation-token and successful-request counters across
  every sample;
- the detached source tree, three exact gitlinks, ignored-file absence,
  executable closure, dataset archive, runtime manifest, binaries, and TLS
  inputs all match the approved plan.

The gate is private (directory `0700`, file `0400`), canonical JSON, self-hashed,
and aggregate-only. It contains counts and hashes, never task identifiers,
endpoint addresses, trace bodies, raw errors, or scheduler records.
It is built in a private temporary sibling and appears only through an atomic
no-replace directory rename, so its canonical namespace is never partial.

`launch` requires a later independent review envelope that binds the exact
plan, gate, controller, and batch-wrapper bytes. It revalidates the complete
gate and static closure immediately before the only `sbatch` call. Submission
is held. `sbatch` reads the environment from a sealed anonymous descriptor and
the exact wrapper from stdin. Scheduler identity therefore requires literal
`Command=(null)` plus the precommitted comment, name, UID, work directory, log
paths, and resource tuple. Complete scontrol/squeue/sacct views include both
allocation and step queues, and both held confirmations are cross-bound inside
the authorization. After one release and complete activation proof, the
controller revalidates every envelope, retained descriptor, terminal gate,
deployment, captured import closure, runtime, and fresh output namespace. The
receipt and permit remain non-authoritative until a separate mode-`0400`
commit envelope is published last beside the sealed mode-`0500` reservation.

Every failure after a job ID is known enters exact-ID cancellation, including
signals and reconciliation failures. An explicit JobId, JobName, UserId,
Command, Comment, or WorkDir conflict permits zero scheduler controls. The sole
fallback permits one exact-ID cancel only for the direct `sbatch --parsable`
candidate after bounded identity unavailability. Signals are masked across each
identity observation until every detected conflict reaches the launch-lifetime
no-control latch. Success still requires empty allocation and step queues, all
accounting rows terminal, six stable terminal
views, a full-minute zero-extra-name proof, and an empty local sbatch process
group. A missing or ambiguous submission receives the full-minute proof or
remains unproven. Private
lifecycle receipts retain the exact scheduler identity needed for cleanup audit
plus aggregate field-name/count telemetry; they never contain task identifiers,
trace bodies, endpoint addresses, or raw errors. Failure receipts are immutable,
non-promoting, and retain the consumed namespace.

## Bound recovery payload

The reviewed plan must bind the exact tracked files and their raw SHA-256s:

- `kimi_smoke_timeout_recovery_control.py` (mode `0500` in the snapshot);
- `run_kimi_smoke_timeout_recovery_hardened.sbatch` (mode `0500`);
- `run_kimi_smoke_recovery.sbatch` (mode `0755`);
- `configs/eval/tb4_kimi_k3_fresh_smoke12h.toml`;
- `configs/eval/tb4_kimi_token_smoke.tasks.txt`.

The config is exactly two tasks, one rollout each, concurrency/multiplex/HTTP
pools two, VMVM, 256 Ki-token input/output/total caps, 43,200-second provider,
rollout, and VM session timeouts, retry max two for the exact four infrastructure
exception classes, model-I/O capture, exact provider JSON, and preserved
maximum-effort reasoning. The existing smoke audit must produce and fully
validate a schema-1 two-of-two checkpoint before the recovery job can succeed.

The source snapshot must be a canonical, detached, clean checkout of the final
reviewed commit with exact tree and initialized `deps/verifiers`,
`deps/renderers`, and `deps/pydantic-config` gitlinks. Its root is mode `0555`.
No ignored entry is allowed under the workflow, VMVM adapter, or those three
dependency trees. Before reviewed imports, every tracked file in those roots
and every runtime-manifest entry is captured and content-addressed. Python
source executes from captured bytes; native extensions and distribution
resources use sealed memfds; mutable path-backed distribution discovery is
disabled; and module/path/import-hook/cache state is restored exactly after
validation.

The runtime manifest is a private canonical envelope. Its root is mode `0500`,
every directory is mode `0500`, and every listed file is regular, mode `0400`,
single-link, owner 656177, and raw-hash/size exact. The set is closed: no extra
file, symlink, `__pycache__`, `.pyc`, `.pyo`, `.pth`, `sitecustomize.py`, or
`usercustomize.py` is accepted. The plan separately binds canonical Python,
uv, vacli, TLS material, and every Git/Slurm/shell/hash/tmux binary used by the
control plane. Python always starts with `-I -S -B`; reviewed import paths replace
ambient paths, and module collisions or origins outside the reviewed source,
runtime, or standard library fail closed.

## Required staging order (not authorized by this document)

1. Freeze this bundle in Git. Create a new canonical detached source snapshot,
   initialize the exact gitlinks, set the source root `0555`, set both new
   executables `0500`, and prove clean/untracked/ignored status twice.
2. Create and independently inspect a closed runtime snapshot and its
   `kimi_smoke_recovery_runtime_manifest` envelope. Record canonical binary and
   authentication hashes without printing secrets.
3. Create a fresh private `0700` approval directory containing a mode-`0400`
   `kimi_smoke_fresh_two_recovery_plan` envelope. It must name three distinct,
   absent `kimi_smoke_recovery_*` output/reservation/log paths, the exact source
   run and its six pinned artifacts, a mode-`0600` global lock, current
   deployment artifacts and route-generation hash, the source/runtime closures,
   and the exact canonical tmux pane ancestry.
4. After separate review, run only `certify-trigger` in that approved pane via
   `/usr/bin/env -i` with exactly `HOME`, `USER`, `LOGNAME`, `PATH`, `LANG`,
   `LC_ALL`, `TMUX`, and `TMUX_PANE`, using the root-owned pinned Python with
   `-I -S -B`. Do not retry a consumed trigger namespace.
5. Independently review the terminal gate and current live state. Only then
   create a mode-`0400` `kimi_smoke_fresh_two_recovery_review` envelope binding
   the exact plan, gate, controller, and batch wrapper and authorizing one
   fresh-two launch.
6. After another explicit launch approval, invoke only `launch` through the
   same canonical pane and clean environment. Do not interrupt it: held
   convergence may use the full 982-second window and activation may use 742
   seconds. Never retry a consumed reservation or job name.
7. Treat only a sealed submission receipt plus activation permit plus the
   external marker-last commit envelope as a submitted result. A failure
   receipt, partial reservation, absent commit, unknown job,
   or any mismatch has no promotion authority. A later auditor must validate
   the terminal job, exact schema-1 checkpoint, result/trace count two, source
   and runtime revalidation, and receipt chain before any downstream use.

## Current blockers

At source freeze time there is intentionally no execution plan, runtime
snapshot/manifest, terminal gate, independent approval, reservation, log, or
output namespace. The final source revision/tree and new-file hashes cannot be
placed in a plan until this commit is frozen. The legacy smoke must separately
be proven terminal and quiescent, and the current live serving generation needs
a fresh exact readiness certificate. An active request or a stale/replaced
route generation is never eligible. Therefore this bundle is not launchable as
committed.
