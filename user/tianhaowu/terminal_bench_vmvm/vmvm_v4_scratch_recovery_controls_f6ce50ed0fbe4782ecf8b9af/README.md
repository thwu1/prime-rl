# VMVM lifecycle v4 scratch-recovery controls

This directory is a source-only, inert candidate for recovering the retained
VMVM lifecycle v4 scratch root on `cpu-140-255`. It has not been frozen,
installed, authorized, or submitted. Its token is
`f6ce50ed0fbe4782ecf8b9af`.

The candidate binds:

- integration base `bf22bf5c6228da3efd14e8279ca61d9ab64c6116`, tree
  `0c29f9985332e20865b1696f4b90d96512cfdcf1`;
- hardened recovery subtree `64cbc0a1c180b29b2b0a85820a8e3031f0437fda` and helper SHA-256
  `faf05cc04b15c0193d575c6cb1a946bd7677966497e4db53db6abf53c97a6840`;
- failed job `1760059`, terminal `FAILED 2:0` on `cpu-140-255`, and failure
  receipt SHA-256 `d99b126b71913a59304e9cc8af400dee09ac84901a0f4dad52eef18111824ae2`;
- v4 source `ea035668d4b43d1bf8fe588ca4469a2b7a46c5a3` / tree
  `9ed4462ca48f288608fccfeb79dadae23b6470c8` and frozen evaluator
  `9d7841b36bafcd58769041925b00deba7c25ffca` / tree
  `7f4027723ab036b888b1baee8c0d51c962653f68`.

## Mandatory sequence

1. An independent reviewer records the final control commit, tree, subtree,
   and file hashes. `freeze_controls.py audit-source` verifies those exact Git
   objects and performs no write or scheduler call.
2. Only after review, `freeze_controls.py install` may exclusively create the
   fresh bundle. It copies bytes from the reviewed Git object database, writes
   a canonical manifest, fsyncs the files and directory, and seals the bundle
   mode `0555`. A partial mode-`0700` bundle is retained and is never reusable.
3. `control.py preflight` is a zero-submit phase. It validates the installed
   bundle and tool bytes, proves every artifact/job/log namespace fresh, and
   requires two byte-identical `sacct` views plus `squeue` absence for old job
   `1760059`. It publishes one private mode-`0400` preflight receipt.
4. `authorize-audit` creates a distinct mode-`0400` audit authorization. The
   audit launcher submits exactly one held, exclusive, one-CPU job pinned to
   `cpu-140-255`, verifies two byte-identical full held identities, and releases
   that exact job once. The job has no task, dataset, model, endpoint, TLS, X2P,
   or cloud environment.
5. The audit job is read-only. It retains the exact helper and authorization
   descriptors, classifies the named root as absent or as one exact directory
   identity, inventories through retained no-follow descriptors, and performs
   two separated same-UID owner/reference scans. It never calls ControlMaster
   exit, chmod, unlink, rename, rmdir, or the helper recovery path. Its private
   mode-`0400` receipt commits the root identity and inventory digest; public
   output is one bounded classification.
6. Only after the audit job is stably `COMPLETED 0:0` and absent from `squeue`,
   `authorize-recover` may create a fresh recovery authorization embedding the
   exact canonical audit receipt and SHA-256. A different held job is then
   submitted, checked twice, and released once. It re-proves the same root
   state, inventory commitment, and quiescence before mutation. An absent root
   remains an audited no-op. A present root is recovered only through the exact
   descriptor-loaded reviewed helper and is moved intact to the authorized
   quarantine name. That durable parent-directory-fsynced move is the commit
   point. If execution is interrupted after it, the node controller reopens the
   quarantine and accepts it only when the target is absent and the root inode,
   mode, owner, mount ID, inventory class, and full inventory commitment still
   exactly match the audit receipt; it then finishes the same receipt without a
   second mutation.

The helper never sends a ControlMaster command through a mutable pathname.
Any live same-UID process or socket reference makes recovery fail closed; only
already-stale sockets are eligible for the intact root move. Audit and recovery
keep parent/root watches through their last state check. Pending handled signals
are rejected immediately before the move; once the durable move commits, those
signals remain blocked and cannot veto a truthful recovery receipt or terminal
success record. A post-move exception triggers a fresh exact quarantine proof
before finalization.

Linux provides no rename operation conditioned on a previously retained source
inode. Therefore the authority boundary requires an independently controlled,
quiescent allocation with no hostile same-UID namespace writer. A same-UID swap
in the final check-to-rename window can move the substitute to quarantine, but
the controller never unlinks, truncates, or recursively modifies that tree; the
post-move identity mismatch fails closed and preserves every byte for review.

Both jobs run from the frozen shared bundle, outside the target `/tmp` tree.
The batch binder opens controller, helper, and authorization with
`O_NOFOLLOW`, verifies mode/UID/link count/hash and named-vs-FD identity, closes
unrelated descriptors, and retains the three descriptors through the child.
The export file contains only the fixed allowlist. After `sbatch` returns its
retained descriptor is overwritten, truncated to zero, and fsynced. Its private
mode-`0700` directory and empty mode-`0400` file are intentionally retained so
cleanup never unlinks or removes a pathname that a same-UID race could replace.
No `--export=NONE` is combined with `--export-file`.

Every public record is fixed-schema and bounded. Root identities, inventory
commitments, accounting bytes, job IDs, paths, hashes, and diagnostic details
remain in owner-only receipts and are never copied to public output. Any
unsupported inode, mount crossing, owner, identity drift, scheduler ambiguity,
or publication failure fails closed and preserves the target.

## Review state

Status: **HOLD**. Do not run either freezer mode or any control action until an
independent reviewer approves the final commit/tree/subtree and exact hashes.
After installation, separately review the manifest and static-preflight
receipt. After audit, separately review the audit receipt before creating the
recovery authorization. Each authorization and reservation namespace is
single-use. A pre-commit failed attempt consumes it; an exact committed
quarantine can only finalize the already-authorized transaction and cannot
authorize a different root or inventory.

The eventual retained-FD operator invocation must set only
`EXPECTED_VMVM_V4_RECOVERY_MANIFEST_SHA256` plus the fixed non-secret runtime
environment and execute the reviewed installed `control.py` from its retained
mode-`0500` descriptor. Direct pathname invocation is not authorized.

Every operation also requires `VMVM_V4_RECOVERY_CONTROL_SHA256` to equal the
independently reviewed hash of that retained descriptor. Subsequent boundaries
require independently supplied hashes rather than rediscovering authority from
the candidate itself: `EXPECTED_VMVM_V4_PREFLIGHT_SHA256` for authorization and
launch, `EXPECTED_VMVM_V4_AUDIT_AUTH_SHA256` for audit launch and recovery-auth
creation, `EXPECTED_VMVM_V4_AUDIT_RECEIPT_SHA256` for recovery-auth creation and
recovery launch, and `EXPECTED_VMVM_V4_RECOVERY_AUTH_SHA256` for recovery launch.
The node wrapper converts only the selected authorization hash to the private
`VMVM_V4_RECOVERY_AUTH_SHA256` child field; no other ambient value survives its
clean-environment handoff.
