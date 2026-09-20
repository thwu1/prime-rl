# VMVM lifecycle v4 node-local scratch recovery candidate

This directory is an inert, task-free recovery verifier for the retained v4
scratch directory on `cpu-140-255`. It has not been installed, authorized,
submitted, or executed. It must not be used until its exact committed bytes are
independently reviewed and a separate mode-`0400` authorization binds the live
root identity.

The only target is:

- node: `cpu-140-255`
- scratch: `/tmp/tianhaowu-vmvm-owner-lifecycle-9d7841b36-v4-scratch`
- failed diagnostic job: `1760059`, terminal `FAILED`, exit `2:0`
- v4 source commit/tree: `ea035668d4b43d1bf8fe588ca4469a2b7a46c5a3` / `9ed4462ca48f288608fccfeb79dadae23b6470c8`
- v4 failure receipt SHA-256: `d99b126b71913a59304e9cc8af400dee09ac84901a0f4dad52eef18111824ae2`
- frozen evaluator commit/tree: `9d7841b36bafcd58769041925b00deba7c25ffca` / `7f4027723ab036b888b1baee8c0d51c962653f68`
- backend SHA-256: `13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a`

The helper has two modes. `audit` validates the exact authorized root and
classifies its inventory without mutation. `recover` never sends a command to
a mutable ControlMaster socket path and never recursively deletes any object.
It requires no same-UID process to reference the authorized root or any
retained directory or leaf through its command line, file descriptors,
working directory, process root, or Unix-socket object. It then atomically
moves the entire authorized root, with all bytes intact, to the separately
authorized fresh quarantine
`/tmp/tianhaowu-vmvm-owner-lifecycle-9d7841b36-v4-scratch-quarantine-7d204ee4a313968c25bfbda7`.
The original target name must be absent and the quarantine name must bind the
same retained mode-`0700` directory inode before success is reported.
The parent directory is fsynced after the rename, making that intact move the
irreversible commit point. The paired controller can resume only that exact
authorized state: target absent, quarantine present, and root identity plus the
complete inventory commitment unchanged from the audit. Handled signals after
the commit cannot turn the truthful terminal result into a failure.

Only same-owner, single-link regular files, Unix sockets, and directories are
supported. The helper binds the mount ID of the root and every retained entry;
the root itself and all descendants must remain on the root parent's mount.
Symlinks, hardlinks, nested mount boundaries, FIFOs, devices, unknown entries,
identity drift, concurrent directory events, live owners, or incomplete move
proof return a closed failure category without deleting any bytes. A same-UID
name substitution can at most cause an unrelated tree to be moved to the fresh
quarantine before the retained-inode mismatch is detected; it is never
unlinked, truncated, or recursively modified. Linux has no rename primitive
conditioned on a retained source inode, so execution requires an independently
controlled, quiescent allocation with no hostile same-UID namespace writer. An
exact committed quarantine may be revalidated and finalized; any mismatched
move consumes the target and quarantine namespaces and requires independent
inspection before another action.
Same-UID hostile processes are outside the kernel boundary available to this
helper; inotify, retained descriptors, unpredictable quarantine names, and
two-pass owner scans detect accidental/concurrent churn, but execution still
requires a quiescent, independently controlled allocation.

The authorization is canonical JSON supplied through a retained descriptor in
`VMVM_V4_RECOVERY_AUTH_FD`. It binds the exact full root
device/inode/mode/mount-ID/uid, exact quarantine path, mode, node, failed-job
lineage, v4 bundle hashes, frozen source, and fresh token
`7d204ee4a313968c25bfbda7`. Its SHA-256 is supplied only in
`VMVM_V4_RECOVERY_AUTH_SHA256`. The helper itself must be opened with
`O_NOFOLLOW`, retained for its entire lifetime, and invoked as
`/usr/bin/python3.12 -I -S -B /proc/self/fd/<fd> audit|recover`; its reviewed
hash is supplied only in `EXPECTED_VMVM_V4_RECOVERY_HELPER_SHA256`.

The eventual scheduler envelope must use a fresh held singleton job explicitly
pinned to `cpu-140-255`, validate two stable full held-identity reads before one
release, pass only the two descriptor/hash controls plus required Slurm identity,
and capture exactly one bounded canonical record. It must not forward TLS,
X2P, model, dataset, or task variables. This source deliberately contains no
submission entrypoint so review cannot accidentally mutate the scheduler.
The envelope must inherit-block `HUP`, `INT`, and `TERM`; the helper keeps them
blocked through its bounded quiescence, quarantine move, descriptor close, and
terminal write, then exits with no post-commit signal window. The controller
rejects a pending handled signal immediately before mutation and ignores one
that arrives only after the move has committed.

Public output has exactly five fixed fields and contains no paths, names,
counts, process identities, errors, hashes, or contents. Example successful
recovery:

```json
{"artifact_type":"vmvm_v4_scratch_recovery_result_v1","cleanup_status":"quarantined","inventory_class":"mixed_supported","owner_state":"absent","state":"quarantined"}
```
