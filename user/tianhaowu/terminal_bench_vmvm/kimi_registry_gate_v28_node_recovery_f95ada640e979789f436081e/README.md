# Kimi registry gate v28 node-local private-root recovery

This directory is an inert, source-only verifier for the one possible retained
probe-private root from failed Kimi registry gate v28 job `1760071`. It has no
scheduler or authorization-creation entrypoint and has not been installed,
authorized, submitted, or run. Operational use remains held pending independent
source review, a separately reviewed node-pinned held-job envelope, and a fresh
mode-`0400` authorization.

The sole target namespace is the exact anchored `/tmp` basename pattern
`k3-registry-pull-v28.1760071.0.[A-Za-z0-9]{6}` on `g3-154-095`. The helper
requires a stable enumeration containing zero or one match. Zero matches means
the root is already absent and returns verified without mutation only when the
authorization also binds an absent root; a stale non-null binding fails closed.
More than one match is ambiguous and always retains every match. A single match
must equal the authorization's exact basename, absolute path, device, inode,
mount ID, mode, owner, and initial link count. The top-level root itself is never
removed: a successful recovery leaves that same inode empty and mode `0700`.

The authorization binds two byte-identical complete terminal accounting reads
for job `1760071`, followed by queue absence. Each read must identify
`k3-reg-pull-153000-v28`, owner `tianhaowu`, `ram/g3/g3_lowest`, node
`g3-154-095`, the exact one-node/four-CPU/one-GPU/16-GiB TRES contract,
`FAILED 3:0`, elapsed `00:00:28`, time limit `00:30:00`, and the original
`k3-reg-pull-v28:<24 hex>` comment. The future envelope—not this helper—must
perform those read-only scheduler observations before constructing the exact
authorization.

The same authorization binds the complete closed launch lineage:

- gate source commit/tree/subtree:
  `4d7b256fdce51a3d2a0dd7f336e18a927dd768ef` /
  `572b4bd1fd2db7deab150374398a9760a7ebf719` /
  `8196764b93e052b4d897eb05cf1e98a123e2003a`;
- approval-control commit/tree/subtree:
  `f7e5498e86d1ad524d2a05a2af1ccbefe2511c17` /
  `bbe987e4856d4edb03bac27b3fb3c9ff10dce73d` /
  `e96599e760ff3bfcb52069edaf760e82dcdfd1f5`;
- all ten frozen bundle hashes, RAM source revision/tree/bundle identity, and
  the consumed approval SHA-256;
- the exact run namespace and deterministic held-identity submission record for
  job `1760071`;
- the exact v28 public log path and SHA-256, whose fixed safe category is
  `podman_info_runroot`;
- absence of the failed batch's durable `job_result.json`; and
- the exact terminal lock path and SHA-256, whose fixed terminal category is
  `file_identity`.

No private log, TLS file, registry material, task, model, trace, or dynamic
error is read or emitted by this helper. The authorization carries only
reviewed hashes, fixed public categories, scheduler identity, and the node-local
root identity. Public output is one bounded canonical JSON record containing
only closed enum values.

Before any mutation, the helper performs two stable tree inventories under an
inotify mutation watch and a full same-UID quiescence interval. The inventory
collects the root plus every directory, regular file, and Unix socket by
device/inode/type/mode/owner/link-count/size/mount-ID. Symlinks, hardlinks,
FIFOs, devices, foreign owners, excessive depth/count, cross-device entries,
and mount-ID changes are rejected. `/proc/self/mountinfo` is parsed independently
before mutation and rejects the root itself or any descendant mount, including
same-device bind mounts. Every recursive open repeats the device and mount-ID
boundary checks, so cleanup never crosses a mount.

The owner scan checks every accessible same-UID process's `cwd`, `root`, and
descriptor table against every collected directory and leaf identity.
Filesystem Unix sockets are additionally mapped through `/proc/net/unix` to
owning socket descriptors. It does not read process command lines or
environments. A same-UID process that cannot be inspected makes quiescence
unverified; only process disappearance is ignored. No process is signaled or
terminated.

Recovery uses only retained directory and leaf descriptors. Regular files are
mode-normalized through their retained descriptors, truncated, fsynced, and
then detached; sockets are never opened as streams. Each entry is moved to an
unpredictable quarantine basename with `RENAME_NOREPLACE`, and exact inotify
move/delete events plus descriptor/name identity are required before and after
unlink. Directories are normalized before their current identity is captured,
avoiding stale-mode comparisons. On a pre-unlink failure, an exact retained
quarantine is restored only if the original name remains absent. Replacement
objects are never unlinked.

The eventual envelope must be a fresh one-shot held job pinned to
`g3-154-095`. It must independently bind its own scheduler identity twice while
held, release once, pass only the retained helper and authorization descriptors
plus the minimal Slurm host variables, inherit-block `HUP`, `INT`, and `TERM`,
and capture exactly one bounded record. It must not pass TLS, registry, task,
model, dataset, trace, or proxy variables. This directory deliberately omits
that envelope and any scheduler command.

The filesystem, mount, process-owner, socket-owner, and scrub primitives are
parameterized and covered independently so a future recovery can reuse their
implementation. The constants, authorization token, lineage, root pattern,
node, job identity, and result namespace in this directory are v28-only. Every
later recovery must be a separate exact source freeze and must not broaden or
reuse this verifier's authorization.
