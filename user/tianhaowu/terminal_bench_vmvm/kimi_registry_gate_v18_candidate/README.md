# Kimi registry pull gate v17

This inert bundle is a one-shot, task-free admission gate for RAM Common
revision `b1f0aa6c1aabcad9182d85a694faaa2eaa3d0f6e`. It exists only to prove that
the production registry state machine can mint a private credential, pass the
same generated auth file explicitly to `podman login` and `podman pull`, pull
the exact Kimi image digest, verify `linux/arm64`, and remove all private and
image state.

That revision includes fixed secret-safe permanent subclasses for Podman exit
125 (`local-storage`, `local-userns`, `local-lock`, `local-runtime`,
`local-path`, and `local-permission`). The probe first requires isolated
`podman info` to succeed, then preserves the worker's exact safe login or pull
class in its durable result. It never publishes raw Podman diagnostics.

The gate requests one node, one task, one GPU, four CPUs, 16 GiB, and 30
minutes on `g3/g3_lowest` under account `ram`, excluding the four reviewed bad
nodes. The batch shell starts exactly one production-shaped nested `srun` so
the normal task prolog applies. The probe sources the sealed worker and invokes
only `_container_registry_arm_cleanup`, `_container_registry_login`,
`_container_registry_pull`, and `_container_registry_disarm_cleanup`. It never
calls `container_run`, `podman run`, GPU enumeration, a checkpoint, a model, an
endpoint, a sandbox, a task, or an evaluator.

Raw command output is written only through two descriptor-retained files. Every
private regular file is truncated and fsynced through its retained descriptor,
then unlinked relative to its retained parent directory only after the named
entry is re-proved to be that inode; nlink zero is proved before close. A moved
inode is still scrubbed but its replacement is never removed and the gate fails
closed as retained drift. The empty batch root and the probe's empty directory
skeleton are retained, so cleanup never performs a pathname `rmdir`.
The shared Slurm log contains exactly one canonical, allowlisted JSON line.
The Podman graphroot and runroot are fresh job-local directories; their exact
real-path identities are checked around every Podman operation. A hash-bound
guard reached through a retained descriptor repeats those checks immediately
before and after every individual production login and pull retry. The probe
retains descriptors for every top-level private directory, globally preflights
all cleanup targets before mutation, rejects hardlinks, special files,
cross-device entries, and mount-table entries (including same-device bind
mounts), and scrubs through those anchors even if a name moves. Each directory
manifest is rechecked immediately at its mutation boundary. The no-follow
scrubber globally preflights all supplied directory graphs before mutation and
rejects symlinks, special entries, hardlinks, and device crossings.

The cleanup trust boundary is the fresh mode-0700 job-local tree after all
supervised Podman children have exited or been reaped. No concurrent writer is
authorized inside it. A hostile process running as the same uid is outside the
gate's authorization model; observed replacement still fails closed, but shell
path traversal cannot provide kernel-enforced inode-conditional unlink against
such an attacker. The per-attempt guard independently gives a Podman child two
seconds after TERM, verifies its `/proc` identity before KILL, and positively
waits/reaps it within a declared three-second bound. Signal teardown includes
that bound and allows 125 seconds for the complete probe fallback,
escalates the nested step after 160 seconds, and bounds batch cleanup plus
publication to 45 seconds. The total declared teardown bound is 210 seconds,
leaving 30 seconds inside the `TERM@240` warning window.
Cleanup signals are deferred while one bounded retrying scrub writer owns the
state. Result publication is likewise a single non-reentrant boundary: all
success, failure, and signal paths can write at most one public JSON line and
publish at most one immutable result before propagating the pending signal.

`audit` validates sealed bytes, source provenance, scheduler/QoS semantics,
and fresh namespaces without reading TLS variables and without submitting or
cancelling a job. `execute` additionally requires the canonical tmux pane, two
canonicalized TLS aliases resolving to the same strict private file, and an
independently created mode-0400 approval whose canonical payload matches the
controller contract. It creates one terminal-tombstone lock, publishes an
owner intent, submits exactly one held job through a mode-0400 NUL export,
feeds the exact verified batch bytes through sealed anonymous memory, and
requires the Slurm-spooled script to hash-bind its own executing descriptor.
It requires two stable exact held reads, releases once, requires two stable
positive active reads, and never resubmits. The batch similarly executes the
reviewed classifier and probe through bound descriptors. It copies the
descriptor-bound scrubber into its private local tree; the probe accepts only
that canonical local path and binds its exact inode and hash before execution.
The probe likewise binds the worker, credential helper, TLS material, and
executable manifest before use.
Malformed submit output is treated as an ambiguous submission and always
enters bounded exact-name reconciliation. A sole name-discovered ID is retained
as a cancellation candidate before strict held-state sampling; cancellation
still requires the exact owner/name/comment envelope and never trusts discovery
alone.
The approval is logically consumed when owner intent is published; the
namespace and lock are intentionally single-use on success, failure, or signal.

Do not create an approval or invoke `execute` until the sealed bundle has an
independent exact-byte review. This gate is diagnostic only and is not a Kimi
deployment authorization.
