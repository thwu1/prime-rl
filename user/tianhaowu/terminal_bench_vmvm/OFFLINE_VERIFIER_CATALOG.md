# Offline verifier dependency catalog

The Sandoq no-network path must never resolve, download, or build verifier
dependencies during an evaluation. It accepts a private catalog only after an
exhaustive static preflight.

## Private inputs

Build the materialization plan with
`materialization_plan_payload(...)`. Each `ExpectedTaskBinding` must identify:

- the private task key;
- `shared-agent` or `separate-verifier`;
- the immutable image that will actually receive the verifier dependency
  overlay (the agent image for shared mode, `task.verifier_image` for separate
  mode);
- the ordered, exact verifier requirements.

The empty tuple is a valid exact requirement set. It is covered by a sealed
image-inventory attestation with an empty reachable closure; it never causes a
builder request.

Do not substitute the agent image for a separate verifier image. The binding
digest covers the runtime role, exact image, and ordered requirement-set
digest. `CatalogIdentity.expected_task_count` and
`CatalogIdentity.binding_plan_sha256` bind the complete canonical binding set,
so a ramp subset cannot claim the production selection identity.

The plan, its parent directory, the work root, and the output catalog are
private. Roots are mode 0700. JSON, archive, request, response, and receipt
files are regular single-link files with mode 0400 or 0600. Symlinks and
catalog roots that overlap the source checkout or dataset are rejected.

The plan binds the exact worker executable and worker-runtime attestation,
the names of explicitly inherited environment variables, concurrency and
timeouts, dataset and selection identities, image manifest, requirement
extractor, inventory probe, toolchain allowlist, and source-build policy. It
contains no mutable artifact paths. The identity also pins the source-only
consumer implementation. Launch with `PYTHONDONTWRITEBYTECODE=1`/`python -B`;
an adjacent `__pycache__` or any implementation hash drift fails closed.
Source hashing traverses no-follow directory descriptors, retains each
ancestor and leaf identity through the read, reopens the final pathname, and
checks for bytecode both before and after hashing.

Binary wheels are not implicitly trusted. Every binary wheel carries an
approved policy record binding distribution, version, filename, size, SHA-256,
source-URL digest, and immutable index-snapshot digest. The identity commits
the exact binary-policy allowlist. Source-built wheels instead require an
approved source attestation and exact approved toolchain.

Plan creation computes `binding_plan_sha256(...)`,
`catalog_consumer_code_sha256()`, `materializer_controller_code_sha256()`,
`worker_environment_sha256(...)`, and
`worker_recovery_scope_sha256(...)` from the frozen inputs. The plan accepts
the exact approved binary-artifact, source-attestation, and toolchain digest
allowlists; no allowlist is inferred from worker output.

## Worker protocol

The materializer invokes one absolute executable without a shell:

```text
WORKER --request PATH --request-sha256 HEX --response PATH --artifact-dir PATH
```

Requests and responses are canonical JSON. The request hash is the job key,
so completed jobs resume without rerunning. A response becomes reusable only
after the controller observes exit status zero, proves process-group
extinction, validates the full response/lifecycle, and writes a private
completion seal binding request and response hashes plus worker/runtime
identity. A response left by nonzero exit, timeout, cancellation, or invalid
lifecycle has no completion seal and is never accepted from cache. A worker
must create the response atomically and must not write task, requirement,
image, or credential data to stdout or stderr. Those streams are discarded by
the materializer.

Every response has these outer fields:

```text
schema_version, protocol_version, operation, request_sha256,
worker_executable_sha256, worker_runtime_sha256, status, lifecycle, result
```

`status` is `complete`. `lifecycle` must report the expected network class,
`process_cleanup_verified=true`, and `cleanup_verified=true`.
`session_started=true` is required for probe/build/validate and false for the
control-plane recovery operation. Missing or false cleanup evidence invalidates
the job. Cancellation and timeout terminate and reap the worker process group;
a pinned Sandoq worker must additionally finish sandbox deletion and verify the
provider cleanup receipt before publishing its response.
For every started session, `lifecycle.provider_cleanup` binds the request,
recovery scope, private session digest, durable-WAL entry, authoritative
provider cleanup receipt, pinned receipt verifier, and terminal `deleted`
state. Recovery responses likewise bind their WAL snapshot and aggregate
recovery receipt to the same scope and verifier.

The operations are:

1. `recover`: before any new lease, replay the durable provider WAL and drain,
   retire, or delete every orphan from an abnormal prior worker exit. The
   response must prove zero remaining sessions and verified cleanup receipts.
2. `probe`: start a clean immutable dependency-runtime image with nested task
   networking disabled. Return the full installed distribution inventory,
   exact reachable closure when satisfied, marker environment, supported wheel
   tags, runtime fingerprint, and the approved probe attestation.
3. `build`: use a separate trusted network-enabled builder. Return a
   deterministic `wheelhouse.tar`, full wheel inventory, full reachable
   closure, compatibility evidence, exact toolchain evidence, binary/source
   origin for every wheel, and approved source-build attestation hashes. The
   approved source-build policy must require independent reproducibility and a
   clean offline install. A discovery build may be shared only when every
   wheel is universal; otherwise the materializer requests an image-bound
   build for each exact image.
4. `validate`: start a new clean exact-image runtime with networking disabled,
   upload the sealed archive, install into an isolated target with
   `PIP_NO_INDEX=1`, `--no-index`, `--no-deps`, and `--require-hashes`, and run
   the supplied closure probe. Return observed archive/wheel-inventory hashes,
   exact requirements-file, pip argv and environment hashes, install exit
   status, closure-probe code/control/argv hashes, probe exit/status hash,
   observed inventory/closure hashes, and zero missing or unexpected
   distributions. Identical validation contracts are deduplicated before
   scheduling so they cannot race on one content-addressed job directory.

For production Sandoq probe and validation operations, the worker must use the
pinned host-side runtime with `mode=oci-runner`, `network_access=false`,
`host_tunnel=none`, `expected_environment=oci-runner-firecracker`, an absolute
private ECR token path, and provider `OCI_RUNNER_TASK_NETWORK=none`. A trusted
network builder must run in a separate process/configuration; it must never
enable networking in the task runtime.

The inherited worker configuration is a redacted canonical commitment and is
revalidated before cache lookup. Production requires
`VF_SANDBOX_PROVIDER=sandoq`,
`OCI_RUNNER_ENVIRONMENT=oci-runner-firecracker`,
`OCI_RUNNER_TASK_NETWORK=none`, and a scoped `SANDOQ_OWNER`. Recovery is
restricted to the digest of that owner plus environment. Direct secret values
are forbidden. Immutable credential files are copied into the private work
root and resealed; the ECR token remains at one canonical owned mode-0600 path
so it can rotate atomically. Each request binds a redacted rotation-generation
audit from a separately pinned rotator metadata file. The audit must match the
current token inode and metadata, have a heartbeat no more than five minutes
old, and retain at least ten minutes of expiry margin. This prevents cached
evidence from crossing rotations without pinning an expiring token.

The worker must shield Sandoq deletion from SIGTERM/SIGINT and persist every
lease transition to the provider WAL before acknowledging it. Killing the
local worker process is not cleanup proof: after any abnormal exit, the next
materializer invocation always runs `recover` before retrying cached work.
The controller additionally holds kernel `flock` locks for the materialization
epoch, publication, and each job; these locks are released by process death and
cannot become stale sentinels. Each local worker is armed with Linux
parent-death signaling and recorded in a private PID/start-time/process-group
WAL. Spawn is cancellation-shielded until the PID is known. Cancellation,
timeout, SIGINT, and SIGTERM perform shielded TERM/KILL, prove process-group
extinction, drain sibling jobs, then obtain a scoped provider recovery receipt
before returning failure. Repeated cancellation is recorded but cannot detach
or re-cancel cleanup already in progress; it is propagated only after that
cleanup and recovery finish. Local process cleanup and a second WAL scan must
succeed before provider recovery may claim zero sessions. A cleanup failure is
reported as infrastructure failure even when cancellation triggered it.
Startup kills every WAL-bound stale local group whose leader PID and start time
still match. A live group with an absent or changed leader is ambiguous and
fails closed without signalling it.

The worker executable is copied alone into the private work root, sealed mode
0500, rehashed, and executed from a verified open file descriptor. `PYTHONPATH`
is not inherited; the worker must be self-contained apart from its pinned
runtime. Environment
inheritance is an explicit allowlist of non-secret provider settings and
credential file-path variables. Direct bearer, API key, cloud access key,
password, token, or secret values are rejected.
For immutable credentials, the private environment commitment binds the
no-follow ancestor chain, leaf identity, and content digest; a staged copy must
match all three even if a pathname is swapped and later restored.

## Materialization

Run the module (or the thin script beside this file) after the pinned worker
and credentials are available:

```text
PYTHONDONTWRITEBYTECODE=1 python -B -m terminal_bench_vmvm.offline_verifier_catalog_materializer \
  --plan /absolute/private/plan/catalog-plan.json \
  --plan-sha256 HEX \
  --worker /absolute/pinned/sandoq-catalog-worker \
  --work-root /absolute/private/resumable-work \
  --output-root /absolute/private/new-catalog \
  --project-root /absolute/frozen/prime-source \
  --dataset-root /absolute/frozen/dataset
```

The work root is resumable by content-addressed request hash. Publishing uses
an exclusive lock, a private staging directory, canonical JSON, deterministic
USTAR archives, bottom-up directory fsync, and Linux
`renameat2(RENAME_NOREPLACE)`. Retained output-parent and staging descriptors
bind their device/inode identities from creation through rename. Publication
validates the exact expected tree (including `launch.json`), rejects extra or
aliased entries, renames relative to the retained parent descriptor, and then
reopens and revalidates the final tree before the parent fsync. The
materializer also reopens the staged catalog and runs the same exhaustive
consumer preflight before publication.

The private `launch.json` records the catalog digest needed by the evaluation
configuration. Standard output contains only the contract version and
aggregate counts. It contains no paths or task, image, requirement, binding,
entry, artifact, or catalog hashes.

## Evaluation consumption

Load the catalog with its exact private digest and both protected roots. Build
all expected bindings from the frozen taskset, selecting the real dependency
runtime image according to verifier mode. Call `preflight(...,
expected_task_count=2499)` before creating any evaluator or sandbox.

The 2/8/24/64 execution ramps still preflight the full canonical 2499-binding
plan against the production catalog. Only after that succeeds may the ramp
driver select its sealed stage subset and call `resolve(...)` for those tasks.
Do not pass the ramp subset as `expected_tasks` and do not weaken exact-set
preflight. A separately sealed subset catalog is acceptable only as a distinct
artifact with its own private identity and launch certificate; it is not the
production catalog.

After a clean runtime starts, collect its compatibility fingerprint and call
`resolve(...)` with the same task key, runtime role, image, and ordered
requirements. An image-inventory plan must be revalidated with the closure
probe. A wheelhouse plan may first probe the image, but the sealed wheelhouse
remains its guaranteed fallback. Before scoring, install the complete archive
offline into an isolated target and run the closure probe. Any drift, missing
coverage, unexpected package, incompatible wheel, unapproved source/toolchain,
mutable file, or unverified cleanup is an infrastructure failure, never a
reward-zero task result.

All runtime archive, wheel, request, site, bootstrap, script, and probe-control
paths must be distinct descendants of
`/tmp/terminal-bench-offline-verifier/<per-runtime-nonce>/`. The helper APIs
reject `/`, system directories, parent traversal, repeated-slash aliases,
all ASCII C0 control characters and DEL, equal paths, and
ancestor/descendant aliases.
