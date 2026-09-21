# VMVM owner-lifecycle diagnostic v3

This is an inert, task-free, one-cell diagnostic for the VMVM vacli process-owner fix. It is not a benchmark, does not open task or model data, does not authorize production use, and has not been submitted or launched.

## Exact source and runtime binding

- frozen source: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-9d7841b36`
- source commit: `9d7841b36bafcd58769041925b00deba7c25ffca`
- source tree: `7f4027723ab036b888b1baee8c0d51c962653f68`
- verifier gitlink: `615b1a30ee3d23cf8d835b64174229c19da887bc`
- renderer gitlink: `044d9e2541f6a911cacae9da353fc063911ef1f8`
- pydantic-config gitlink: `896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f`
- direct mode-`0444` `environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py` SHA-256: `13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a`
- vacli alias: `/public/fbpkgs/x86_64/vacli/stable/vacli`
- resolved vacli: `/infra/public/fbpkgs/x86_64/vacli/794/vacli`
- vacli SHA-256: `8be49a764bd0fac1a3ef2bef053ced556d18397d44642660eb8a2d22a7c235b3`
- x86-64 uv SHA-256: `ec831939765474162efb6c8c813e2b10908b26b04eaf98ac3e2972fa12d189b9`

The launcher, wrapper, probe, and finalizer each revalidate the direct backend file through an already-bound source directory descriptor with `O_NOFOLLOW`. They also attest the detached source revision/tree, the three exact gitlinks, clean tracked contents, and the absence of ignored executable Python artifacts.

## The single cell

The worker performs exactly this sequence:

1. Construct `VacliVMVMBackend` on a short-lived thread.
2. After that caller thread exits, continuously verify the initial renewer PID, process group, and `/proc` start ticks for two seconds.
3. Run fixed `printf owner-lifecycle-first` from a second short-lived thread and require the exact four-field successful result.
4. Force the existing-tunnel health check to fail once in memory, then call `restart_session()` from a third short-lived thread. This drives the real `VacliLease.restart_tunnel()` resume path without changing source bytes.
5. Require one recovery start, one recovery success, zero recovery failures, a distinct replacement PID/start-tick identity, and two total tunnel-ready/renewer observations. Verify the replacement survives its caller thread for two seconds.
6. Run fixed `printf owner-lifecycle-second` from another short-lived thread.
7. Destroy the backend, then independently prove both renewer PID/PGID identities and the worker process group remain absent continuously for a full 60-second lease TTL plus five seconds of grace.

A passing cell has exactly one lease start, two commands, one forced recovery, two tunnel-ready events, two distinct renewers, and one cleanup/release proof. Extra attempts or events invalidate the certificate.

## Filesystem and output contract

The bundle contains exactly these six entries and no `__pycache__`:

- `README.md`
- `finalize_vmvm_owner_lifecycle_v3.py`
- `launch_vmvm_owner_lifecycle_v3.py`
- `probe_vmvm_owner_lifecycle_v3.py`
- `run_vmvm_owner_lifecycle_v3.sbatch`
- `test_vmvm_owner_lifecycle_v3.py`

Before creating an authorization, remove bytecode outside this directory, verify the six-name inventory, set the directory to `0700`, set Python/sbatch executables to `0500`, set README/tests to `0400`, and record each SHA-256 plus the root identity. The launcher rejects extra entries, hardlinks, symlinks, wrong owners/modes, path replacement, or hash drift.

The worker may mutate only its descriptor-bound node-local scratch cell below `/tmp`. The supervisor binds the `/tmp` parent with a two-pass component walk and creates the fresh fixed scratch name relative to that descriptor. Both execution snapshots are created, opened, sealed, inventoried, and passed to the worker relative to held directory descriptors; the intentionally descriptor-backed `/proc/self/fd/<n>` paths are never sent through the absolute no-symlink path walker. Cleanup recursively opens entries with `O_NOFOLLOW`, accepts only same-owner single-link regular files and directories, atomically quarantines each entry with `RENAME_NOREPLACE`, verifies inode identity and inotify events, and preserves unrelated replacements. The top-level scratch directory is deliberately retained as the same empty `0700` inode on the compute node. The compute wrapper independently verifies that inode and binds SHA-256 commitments to its full descriptor identity and fixed path into the certificate and completion request. The external finalizer validates those commitments and lineage but never opens or otherwise resolves compute-local `/tmp`.

The successful output root is retained at `0500` with exactly `diagnostic_certificate.json` and `completion_request.json`, both `0400`. On a supervisor failure, the wrapper accepts only one exact allowlisted failure record; timeout, malformed, multi-line, and unknown output are normalized to `child_timeout` or `unclassified`. It combines that primary failure with independent local-scratch and descriptor-bound shared-output cleanup checks, then publishes the shared sibling `probe-failure.json` directly through the bound parent with `O_CREAT|O_EXCL|O_NOFOLLOW`. The retained `O_RDWR` descriptor is written, changed to mode `0400`, file-fsynced, fully read back, matched to the named inode, parent-fsynced, and revalidated. Signals are blocked across that complete interval. A post-create failure intentionally retains the final name for audit and retry exclusion; the writer never renames or unlinks it. This avoids filesystem-specific `RENAME_NOREPLACE` behavior and pathname cleanup races. The receipt contains only closed categories and lineage hashes; neither raw child output nor a credential value is persisted or emitted.

Public job output is one canonical aggregate line only:

```json
{"cells":1,"failure_categories":0,"passed":1,"state":"awaiting_external_completion"}
```

or, after a durably published failure receipt, one canonical safe failure line such as:

```json
{"cleanup_status":"verified","code":"diagnostic_probe_failed","failure_class":"backend_tunnel","state":"failed"}
```

Credentials, command output, PIDs, PGIDs, session material, and raw logs are never emitted into the certificate or public output.

The unused one-shot namespace is:

- output: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/vmvm_owner_lifecycle_9d7841b36_v3`
- reservation: the output path plus `.launch-reservation`
- completion receipt: the output path plus `.external-completion.json`
- probe-failure receipt: the output path plus `.probe-failure.json`
- logs: `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/vmvm_owner_lifecycle_9d7841b36_v3`
- scratch: `/tmp/tianhaowu-vmvm-owner-lifecycle-9d7841b36-v3-scratch`
- scheduler job/comment prefix: `vmvm-owner-v3-` / `vmvm-owner-v3:` followed by one fresh 24-hex token

## Sealing and timing

The wrapper binds all directories first, self-reexecutes from a sealed anonymous memfd, then copies the probe and uv into sealed anonymous memfds. Each memfd requires `F_SEAL_SEAL|F_SEAL_SHRINK|F_SEAL_GROW|F_SEAL_WRITE|F_SEAL_EXEC`; the probe and finalizer verify their own sealed descriptors before use. The uv child environment is restored to the exact authorized digest before Python starts.

The fixed bounds are:

- job: 5,400 seconds (`01:30:00`)
- batch `SIGTERM`: 600 seconds before job end
- activation gate: 600 seconds
- sealed admission: 300 seconds
- one-cell worker: 1,800 seconds
- complete supervisor: 2,700 seconds
- timeout TERM-to-KILL grace: 120 seconds for each of the two sealed-probe invocations
- finalization reserve: 600 seconds

The strict dominance check is `600 + 300 + (2 * 120) + 2700 + 600 = 4440 < 5400 - 600 = 4800`, leaving 360 seconds of margin, and the worker bound is strictly below the supervisor bound. The two kill graces cover the admission and supervisor invocations independently. The wrapper uses `timeout` with TERM and bounded KILL escalation; the probe tears down the worker process group and performs the external lease-TTL absence check on every controlled failure path.

## Authorization boundary

`launch_vmvm_owner_lifecycle_v3.py` accepts only a canonical, external `vmvm_owner_lifecycle_diagnostic_authorization_v3` document whose source, runtime, credentials, launch settings, protocol, bundle hashes, and directory identities exactly match this README and the code. It submits one held job, verifies the scheduler record, writes a sealed NUL environment, releases the hold once, and records the lineage artifacts. It never approves its own authorization.

After a successful job, `finalize_vmvm_owner_lifecycle_v3.py` must itself execute from the named sealed finalizer memfd on the canonical launcher host. It requires a separate canonical `vmvm_owner_lifecycle_external_completion_authorization_v3`, revalidates all source/runtime/bundle/submission/certificate commitments, requires the probe-failure receipt to remain absent, validates the hash-bound compute cleanup attestation without reopening compute-local scratch, and atomically creates the external completion receipt. The completion authorizer must independently bind the output root's full canonical-host identity; the compute-generated request carries its matching portable identity. Neither launcher nor finalizer is invoked by the test suite. This directory remains an inert source candidate: its frozen source reference is reproduction provenance, not launch authorization. Before any execution, an independent reviewer must rebind and approve a fresh immutable six-file bundle and authorization against the exact reviewed owner-fix source.
