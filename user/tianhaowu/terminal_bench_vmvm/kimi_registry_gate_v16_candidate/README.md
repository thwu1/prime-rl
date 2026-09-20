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

Raw command output remains in a job-local mode-0700 directory and is removed.
The shared Slurm log contains exactly one canonical, allowlisted JSON line.
The Podman graphroot and runroot are fresh job-local directories; their exact
scope is checked before the digest-pinned image is removed. Both shells retain
directory descriptors and perform cleanup through those anchors. Known raw
stdout, stderr, and TLS files retain exact descriptors through truncate, sync,
and unlink. A no-follow descriptor-relative scrubber rejects hardlinks,
symlinks, special entries, owner or device changes before recursively clearing
Podman state. Root directories are deliberately retained after verified scrub,
so name drift cannot redirect a lexical `rmdir`; drift is distinguished from a
sensitive-residue cleanup failure. Signal teardown uses one 115-second
deadline from the first escalation through process-group TERM/KILL, outer
descriptor cleanup, durable result publication, and the sole public log
write. It reserves at least five seconds for publication and clamps cleanup
to that same deadline. Signals received during cleanup are recorded and
deferred; probe cleanup is retried within one shared 90-second budget, and
completion is set only after the descriptor-bound scrub and descriptor
closure are verified.

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
