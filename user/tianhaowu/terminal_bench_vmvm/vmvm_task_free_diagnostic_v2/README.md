# VMVM V21 task-free pre-lease diagnostic v4

This is an inert, aggregate-only preflight bundle. It does not authorize a
Slurm job, create a VMVM lease, run the supervisor or a worker, read benchmark
or task data, write a candidate output, or call a model. It must remain
unlaunched until an independent reviewer freezes all six files, publishes a
separate mode-0400 authorization, proves every namespace is fresh, and approves
the canonical-pane invocation.

The v4 executable path exists only to localize the v3 allocation's generic
early failure on an x86 node. The authorization protocol is exactly:

```json
{"diagnostic_only":true,"preflight_only":true,"production_authorized":false}
```

The sealed probe CLI accepts only `--validate-batch`; worker and supervisor
arguments are not registered. The batch wrapper invokes that admission path
exactly once and exits after its post-admission read-only checks. Although the
six-file layout retains reviewed supervisor and finalizer library code, neither
is reachable from the v4 command line or wrapper.

## Read-only stages

The wrapper performs these operations, in order:

1. Validate the exact environment allowlist, fixed values, path shapes,
   digests, directory identities, and inventory counts.
2. Open and retain descriptors for the frozen bundle, source, x86 Python site,
   reservation, and output parent.
3. Classify each observed directory identity against its authorized
   device/inode/mode/owner tuple.
4. Re-hash the six-file bundle, uv, vacli, authorization, source revision/tree,
   submodules, and imported VMVM implementation.
5. Validate the sealed reservation and activation lineage.
6. Copy the already-bound probe and uv bytes into anonymous memfds, apply the
   write/grow/shrink/exec/seal seals, and execute one admission-only probe.
7. Reattest the probe and source, prove the output/receipt/scratch names remain
   absent, and hash the three private lineage artifacts.

No stage creates the output or scratch path. There is no lease, container,
supervisor, worker, snapshot, Landlock, completion, or cleanup path.

## Aggregate-only telemetry

Before any check, the wrapper duplicates its public stdout/stderr and redirects
ordinary process output to `/dev/null`. The sealed builder closes those public
descriptors before executing uv or the probe. Probe stdout/stderr is captured
and compared only to the exact admission token; it is never forwarded.

Failure output is one canonical JSON object composed only from literal,
allowlisted values. Its `stage` is one of:

```text
entry required_environment forbidden_environment fixed_environment path_shape
digest_shape identity_shape count_shape directory_open directory_identity
bundle_inventory bundle_artifacts runtime_resolution runtime_artifacts
source_attestation activation_gate executable_binding sealed_builder
probe_admission probe_response post_preflight_source namespace_freshness
lineage_hashes internal
```

The `directory_identities` object always has the fixed keys `bundle`,
`output_parent`, `reservation`, `site`, and `source`. Each value is one of
`match`, `not_checked`, `unreadable`, `device_only`, `inode_only`, `mode_only`,
`owner_only`, or `multiple`. It contains no numeric identity, pathname,
credential, exception, or child output. For example:

```json
{"code":"diagnostic_job_failed","directory_identities":{"bundle":"device_only","output_parent":"match","reservation":"match","site":"match","source":"match"},"stage":"directory_identity","state":"failed"}
```

Successful admission emits only:

```json
{"directory_identities":{"bundle":"match","output_parent":"match","reservation":"match","site":"match","source":"match"},"stage":"prelease_admission","state":"passed"}
```

NFS `st_dev` values are client-local and may differ across login and compute
hosts. V4 deliberately continues to fail closed on such a mismatch while
reporting only `device_only`; it does not weaken the reviewed identity binding.

## Descriptor and credential bindings

The external authorization binds the exact source revision/tree/gitlinks,
six bundle hashes, directory identities, x86-site manifest, uv/vacli bytes,
image, TLS file hashes, and private commitments to `X2P_ENV`, `X2P_CFG_ENV`,
and `X2P_PROXY_URL`. Credential values are consumed only inside admission and
never persisted in public telemetry. Source and site validation is read-only.

The Linux pathname-removal limitation documented for the full diagnostic is
outside this preflight: v4 creates no output or scratch tree and invokes no
removal operation. Absence checks therefore remain simple fail-closed gates.

## Fixed fresh namespaces

- source: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-a09a9a189-v21`
- output: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/vmvm_v21_task_free_preflight_a09a9a189_v4`
- receipt: the output path plus `.external-completion.json`
- reservation: the output path plus `.launch-reservation`
- logs: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/vmvm_v21_task_free_preflight_a09a9a189_v4`
- scratch: `/tmp/vmvm-v21-task-free-preflight-v4`
- job name: `vmvm-v4-preflight-` plus the authorization's 24-hex token

There is intentionally no runnable launch command here. No Slurm command was
run while preparing this bundle, and no result from it authorizes an oracle,
rollout, production evaluation, or trace generation.
