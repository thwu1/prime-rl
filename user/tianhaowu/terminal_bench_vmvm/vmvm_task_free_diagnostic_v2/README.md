# VMVM V21 task-free pre-lease diagnostic v7

This is an inert, aggregate-only preflight bundle. It does not authorize a
Slurm job, create a VMVM lease, run the supervisor or a worker, read benchmark
or task data, write a candidate output, or call a model. It must remain
unlaunched until an independent reviewer freezes all six files, publishes a
separate mode-0400 authorization, proves every namespace is fresh, and approves
the canonical-pane invocation.

The v7 executable path exists only to verify the diagnosed v6 cross-host NFS
identity failure on an x86 node. V6 proved the export-file repair: all required
environment values arrived, then all five directory comparisons reported only
`device_only`. No uv, probe, or VMVM lease was reached. V7 retains exactly one
sealed `--export-file` and no `--export=NONE`. NFS `st_dev` is local
to each client, so v7 retains the complete login-side device/inode/mode/owner
binding and adds a separately authorized batch tuple of inode/mode/owner.
Only the device may vary. Every path remains fixed, absolute, canonical, and
symlink-free. Each directory is opened component-by-component from a held root
descriptor with `openat(O_NOFOLLOW)`, and a second anchored walk must reproduce
the complete ancestor chain before the leaf descriptor is admitted. The batch
wrapper re-executes its exact bound bytes with those five directory descriptors
inherited, so it never checks a pathname and then reopens it. All existing
content, Git, inventory, authorization, and receipt hashes remain mandatory.
The authorization protocol is exactly:

```json
{"diagnostic_only":true,"directory_identity_policy":{"batch_fields":["inode","mode","owner_uid"],"cross_host_variance":["device"],"launcher_fields":["device","inode","mode","owner_uid"],"path_binding":"absolute_anchored_openat_nofollow"},"preflight_only":true,"production_authorized":false}
```

The sealed probe CLI accepts only `--validate-batch`; worker and supervisor
arguments are not registered. The batch wrapper invokes that admission path
exactly once and exits after its post-admission read-only checks. Although the
six-file layout retains reviewed supervisor and finalizer library code, neither
is reachable from the v7 command line or wrapper.

## Read-only stages

The wrapper performs these operations, in order:

1. Validate the exact environment allowlist, fixed values, path shapes,
   digests, directory identities, and inventory counts.
2. Open and retain descriptors for the frozen bundle, source, x86 Python site,
   reservation, and output parent.
3. Classify each observed directory identity against its full launcher tuple,
   then require its separately bound portable inode/mode/owner tuple exactly.
4. Re-hash the six-file bundle, uv, vacli, authorization, source revision/tree,
   submodules, and imported VMVM implementation.
5. Validate the sealed reservation and activation lineage.
6. Copy the already-bound probe and uv bytes into anonymous memfds, apply the
   write/grow/shrink/exec/seal seals, and execute one admission-only probe
   through the fixed uv child-environment sanitizer.
7. Reattest the probe and source, prove the output/receipt/scratch names remain
   absent, and hash the three private lineage artifacts.

No stage creates the output or scratch path. There is no lease, container,
supervisor, worker, snapshot, Landlock, completion, or cleanup path.

## Aggregate-only telemetry

Before any check, the wrapper duplicates its public stdout/stderr and redirects
ordinary process output to `/dev/null`. The sealed builder closes those public
descriptors before executing uv or the probe. Probe stdout/stderr is captured
and compared only to the exact admission token; it is never forwarded.

The outer and persisted environments forbid bare `UV` and every `UV_*` name
except the authorized `UV_BIN_X86_64`. The pinned uv executable is expected to
introduce exactly three fields in its child: `UV=/memfd:vmvm-uv-v2 (deleted)`,
`UV_RUN_RECURSION_DEPTH=1`, and `PATH=/usr/local/bin:/usr/bin:/bin`. A Python
trampoline between uv and the probe validates that exact tuple, removes `UV`
and `UV_RUN_RECURSION_DEPTH`, restores `PATH=/usr/bin:/bin`, and compares a
SHA-256 commitment over the entire restored environment with the pre-uv
environment. Missing, changed, or additional uv mutations fail closed before
the probe. The trampoline then re-executes the selected interpreter through
`/proc/self/exe` with the sealed probe descriptor.

Failure output is one canonical JSON object composed only from literal,
allowlisted values. At `required_environment`, it reports the complete missing
and empty classifications as lists of names drawn from the wrapper's fixed
62-name allowlist. It never reports values, lengths, hashes, or shell errors:

```json
{"code":"diagnostic_job_failed","required_environment":{"empty":["X2P_ENV"],"missing":["SLURM_EXPORT_ENV"]},"stage":"required_environment","state":"failed"}
```

Its `stage` is one of:

```text
entry required_environment forbidden_environment fixed_environment path_shape
digest_shape identity_shape count_shape directory_open directory_identity
bundle_inventory bundle_artifacts runtime_resolution runtime_artifacts
source_attestation activation_gate executable_binding sealed_builder
uv_sanitizer uv_environment uv_probe_exec probe_admission probe_response
post_preflight_source namespace_freshness
lineage_hashes internal
```

After required-environment admission, the `directory_identities` object has the fixed keys `bundle`,
`output_parent`, `reservation`, `site`, and `source`. Each value is one of
`match`, `not_checked`, `unreadable`, `device_only`, `inode_only`, `mode_only`,
`owner_only`, or `multiple`. It contains no numeric identity, pathname,
credential, exception, or child output. For example:

```json
{"code":"diagnostic_job_failed","directory_identities":{"bundle":"match","output_parent":"match","reservation":"match","site":"match","source":"inode_only"},"stage":"directory_identity","state":"failed"}
```

Successful admission emits only:

```json
{"directory_identities":{"bundle":"device_only","output_parent":"device_only","reservation":"device_only","site":"device_only","source":"device_only"},"stage":"prelease_admission","state":"passed"}
```

NFS `st_dev` values are client-local and may differ across login and compute
hosts. V7 permits that difference only when every portable tuple and all
content/provenance checks pass. Inode, mode, owner, path, or content drift still
fails closed, while telemetry continues to expose only the allowlisted class.

## Descriptor and credential bindings

The external authorization binds the exact source revision/tree/gitlinks,
six bundle hashes, full and portable directory identities, the explicit
cross-host identity policy, x86-site manifest, uv/vacli bytes,
image, TLS file hashes, and private commitments to `X2P_ENV`, `X2P_CFG_ENV`,
and `X2P_PROXY_URL`. Credential values are consumed only inside admission and
never persisted in public telemetry. Source and site validation is read-only.

The Linux pathname-removal limitation documented for the full diagnostic is
outside this preflight: v7 creates no output or scratch tree and invokes no
removal operation. Absence checks therefore remain simple fail-closed gates.

## Fixed fresh namespaces

- source: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-a09a9a189-v21`
- output: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/vmvm_v21_task_free_preflight_a09a9a189_v7_portable_identity`
- receipt: the output path plus `.external-completion.json`
- reservation: the output path plus `.launch-reservation`
- logs: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/vmvm_v21_task_free_preflight_a09a9a189_v7_portable_identity`
- scratch: `/tmp/vmvm-v21-task-free-preflight-v7-portable-identity`
- job name: `vmvm-v7-preflight-` plus the authorization's 24-hex token

There is intentionally no runnable launch command here. No Slurm command was
run while preparing this bundle, and no result from it authorizes an oracle,
rollout, production evaluation, or trace generation.
