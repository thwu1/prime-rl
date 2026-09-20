# Kimi registry pull gate v16

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

Raw command output is written only through two descriptor-retained files; their
exact inodes are truncated before their descriptors are closed. Their names and
the scrubbed batch root are retained, so no cleanup unlink can hit a replacement.
The shared Slurm log contains exactly one canonical, allowlisted JSON line.
The Podman graphroot and runroot are fresh job-local directories; their exact
real-path identities are checked around every Podman operation. A hash-bound
guard reached through a retained descriptor repeats those checks immediately
before and after every individual production login and pull retry. The probe
retains descriptors for every top-level private directory, globally preflights
all cleanup targets before mutation, rejects hardlinks, special files,
cross-device entries, and mount-table entries (including same-device bind
mounts), and scrubs through those anchors even if a name moves. Each directory
manifest is rechecked immediately at its mutation boundary. Both shells retain
verified scrubbed roots; neither performs pathname `rmdir`.

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
reviewed classifier and probe through bound descriptors; the probe binds the
worker, credential helper, TLS material, and executable manifest before use.
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
