# VMVM V21 task-free transport diagnostic v2

This is an inert, aggregate-only diagnostic bundle. It does not authorize a
Slurm job, create a VMVM lease, read benchmark/task data, or call a model. It
must remain unlaunched until an independent reviewer freezes all six files,
publishes a separate mode-0400 launch authorization, confirms every proposed
namespace is fresh, and approves the canonical-pane invocation. No result from
this diagnostic authorizes an oracle, rollout, or production trace generation.

## Failure boundary being tested

V21 produced 19 infrastructure-error rows and zero valid rows. All 95 attempts
reached lease, tunnel, SSH, container, and FIFO setup before the first
post-construction work-directory command returned `rc255/truncated`. The sealed
V21 environment omitted `X2P_ENV` and `X2P_CFG_ENV`; an earlier successful
task-free smoke inherited them. This diagnostic treats `X2P_ENV`,
`X2P_CFG_ENV`, and `X2P_PROXY_URL` as one authorization-bound private tuple:
the absent cells receive none of the three and the present cells receive all
three. At source revision
`a09a9a189697034e23b776fdbfccb369522c469d`, backend construction/FIFO probing
and `VMVMRuntime.start()`'s raw first `mkdir` also cross a transient-thread
boundary. Normal runtime commands instead use bounded exact-once recovery.

The diagnostic preserves all six original stages: direct lease/tunnel/SSH; backend
construction plus a raw or bounded-recovery first command on the constructing
thread; the same two command variants after a thread handoff; and the exact
`VMVMRuntime.start()`, no-op command, and stop contract.

## Counterbalanced design and retry parity

Every stage is repeated in four adjacent X2P pairs using the fixed ABBA order:

```
absent,present
present,absent
present,absent
absent,present
```

That is 48 sequential task-free cells at concurrency one. Both modes occupy
each ordinal position twice. Every cell has the same ceiling of two fresh
lease attempts, one image-pull attempt per lease, five exact-once transport
recovery attempts where the selected command mode permits recovery, and an
1800-second child deadline. An X2P effect is classified only at the construction
boundary: a cell must reach the allowlisted `backend_ready` phase after lease,
tunnel, SSH, and backend or runtime construction. At least three of four paired
construction contrasts must agree with zero reversals. End-to-end pass/fail
contrasts remain separate descriptive output, so a later command failure cannot
be mislabeled as an X2P construction effect. The raw/recovery and
same/cross-thread axes remain separate.

Each result contains only allowlisted state plus aggregate metadata: lease
attempts and ceiling, transport-recovery attempts and ceiling, phase counters,
last phase, elapsed milliseconds, pair/order coordinates, and release status.
Raw stdout/stderr, ports, addresses, lease responses, credentials, and exception
text never enter the public certificate.

## Release proof, including timeouts

Cleanup is not equated with a child process merely exiting. Instrumented lease
objects track every initial and resumed renewer process. Before each process
creation they append and fsync an operation-start record to a supervisor-owned
descriptor; after creation they append its PID, separate PGID, and process-start
identity. This journal remains readable by the supervisor even if the worker is
killed or emits an invalid result. After cleanup, a cell waits one complete
60-second lease TTL plus a five-second grace interval and proves every tracked
PID and process group remains absent. A timeout, malformed result, incomplete
journal operation, missing cleanup timestamp, live renewer, excess lease
attempt, or otherwise unverifiable lifecycle fails closed and prevents a
candidate certificate. The supervisor independently performs the full
PID/PGID absence interval even for a structurally valid successful child and
aborts before starting the next matrix cell on any unverified result or cleanup
failure. Each per-cell scratch directory (including vacli logs) and the final
snapshot scratch tree are deleted without ignored errors, and absence is
verified before publication. When a backend constructor raises after its audited
rollback cleaned every attempted lease, the original constructor failure class
is retained instead of being overwritten with `cleanup_failed`.

## Descriptor and content bindings

The external launch authorization binds:

- exact source revision/tree/gitlinks plus source-root device/inode/mode/owner;
- default index flags and exact HEAD/index/blob equality for every tracked file
  in the imported VMVM source and all three imported submodules;
- all six bundle paths and hashes plus bundle-root device/inode/mode/owner;
- the x86 site root's device/inode/mode/owner and a sorted recursive manifest
  over every directory and regular file (relative path, mode, owner, size, and
  content hash);
- the exact uv/vacli binaries, image, TLS file hashes, and private commitments
  to all three X2P values;
- the ABBA schedule, repetitions, retry ceilings, timeout, and all CLI paths;
- output parent, output, reservation, scratch, log, and external-receipt paths.

The launcher holds open descriptors for source, bundle, x86 site, output parent,
and reservation. Reservation files are created relative to the held dirfd; the
writer lock and receipts stay on that same inode. Wrapper bytes are submitted
through stdin. The batch wrapper matches every authorized device/inode tuple,
opens the probe from the bundle dirfd, and invokes it as `/proc/self/fd/N`.
The Python preflight rejects pathname invocation: the probe, source, site, and
output parent must all arrive as inherited `/proc/self/fd/N` descriptors. Before
the first cell, the supervisor copies the fully attested imported source and
the authorized x86 site into a private, read-only execution snapshot. It
verifies both copied content manifests against the held inputs, reattests the
originals, and gives worker children only held descriptors for those snapshots.
Both snapshot manifests are checked immediately before and after every child
and recorded in the certificate. A mutate-then-restore race against either
original input therefore cannot change executed bytes. The finalizer also
validates every semantic field of the original launch authorization and
re-hashes the exact six-file bundle, including its own authorized path and
bytes, before accepting a completion authorization.

## Two-party completion

The batch creates only a candidate output containing
`diagnostic_certificate.json` and `completion_request.json`. Both files become
mode 0400, the output directory becomes mode 0500, and stdout reports
`awaiting_external_completion`. The batch never creates a completion receipt.

After the allocation is terminal, an independent reviewer must publish a
separate mode-0400 completion authorization binding the terminal scheduler
observation, candidate directory identity and inventory hash, certificate and
request hashes, original launch-authorization path/file/body hashes, sealed
reservation identity, submission-receipt and held-job-authorization hashes,
exact cluster/job/name lineage, and receipt path. Only
`finalize_vmvm_task_free_v2.py` consumes it. The finalizer reopens and re-hashes
the launch authorization, reservation lineage, and sealed output by dirfd;
cross-checks all hashes and job identities; independently recomputes result,
failure, retry/phase, construction-contrast, outcome-contrast, and causal
aggregates from all 48 stage rows; and writes
`<output>.external-completion.json` outside the output directory with `O_EXCL`.
Its returned SHA-256 is the external completion hash. Without that receipt, the
diagnostic is not complete.

## Fixed fresh namespaces

- source: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-a09a9a189-v21`
- output: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/vmvm_v21_task_free_ab_a09a9a189_v2`
- receipt: the output path plus `.external-completion.json`
- reservation: the output path plus `.launch-reservation`
- logs: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/vmvm_v21_task_free_ab_a09a9a189_v2`
- scratch: `/tmp/vmvm-v21-task-free-ab-v2`

There is intentionally no runnable launch command here. External authorization
must provide exact frozen hashes and private credential bindings. This bundle
contains no task identifier, dataset path, model endpoint, or production
authorization, and no Slurm command was run while preparing it. In particular,
the launch gate requires `X2P_ENV`, `X2P_CFG_ENV`, and `X2P_PROXY_URL` together;
an environment missing any member (including the currently absent proxy value)
is not launchable.
