# Kimi registry pull gate v28

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
nodes. It is pinned to `g3-128-109`, the node measured by the completed V5
compute-tool diagnostic. The controller binds the exact mode-0400 private
manifest, controller result, public job result, and V5 approval by hash and
size. It independently requires all 33 primary rows to be labeled
`fresh_compute_node`, requires both nofollow path and followed-target identities
to be root-owned regular mode-0755 single-link files, reconstructs
`compute_tools.sha256` strictly from the 33 observed hashes, and requires exact
byte equality with the sealed manifest. The V5 aggregate and selected Python
identity are cross-validated. No reviewed hash from an older node is reused.
The runtime attestation applies the same nofollow and followed identity rules,
so symlinks fail explicitly. All 33 entries must match at runtime. The batch shell
starts exactly one production-shaped nested `srun` so
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
The Podman graphroot, rootless storage path, and runroot are bound to fresh
job-local directories; their exact real-path identities are checked around
every Podman operation. Descriptor-only opens scope diagnostic suppression to
the open operation and restore the probe's private stderr before any later
marker. Initial Podman preflight failures distinguish command failure,
malformed output, graphroot drift, runroot drift, driver drift, a non-cold
image, and an image-query failure. A fixed private retained-empty marker is
required before accepting any post-root operational category, and any cleanup
failure takes precedence over the operational marker. A hash-bound
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
leaving 30 seconds inside the `TERM@240` warning window. That one immutable
deadline is armed immediately when the outer batch records a signal, even
before spawn or after its child has already been reaped; child stop, cleanup,
and publication consume only the shared remaining time.
Cleanup signals are deferred while one bounded retrying scrub writer owns the
state. Result publication is likewise a single non-reentrant boundary: all
success, failure, and signal paths can write at most one public JSON line and
publish at most one immutable result before propagating the pending signal.
If the bounded TERM/KILL/reap ladder still proves the nested writer or its
process group live, cleanup is never entered. The batch emits only the distinct
`live_writer_cleanup_unproven` fail-closed result, retains the private tree for
the scheduler to isolate, and exits. The controller acts on the early marker
only after the immutable durable result and public log are both stable and
byte-identical, then requests exact-job cancellation. It publishes its final
aggregate result only after exact terminal accounting followed by a fresh,
stable absence proof for the scheduler namespace; pre-terminal absence is
never reused as that final proof.

`audit` validates sealed bytes, all three immutable V5 result artifacts, their
fresh 33-row projection, source provenance, scheduler/QoS semantics,
and fresh namespaces without reading TLS variables and without submitting or
cancelling a job. `execute` revalidates the V5 evidence before reading TLS and
again at the owner-intent boundary. It additionally requires the canonical tmux pane, two
canonicalized TLS aliases resolving to the same strict private file, and an
independently created mode-0400 approval whose canonical payload matches the
controller contract. It creates one terminal-tombstone lock, publishes an
owner intent, submits exactly one held job through a mode-0400 NUL export,
feeds the exact verified batch bytes through sealed anonymous memory on fd 0
with no positional script operand, and requires the Slurm-spooled script to
hash-bind its own executing descriptor. Slurm selects stdin only when the
script filename is omitted; a literal `-` is forbidden. A local nonzero
`sbatch` exit still receives bounded ambiguity reconciliation and is reported
only as sanitized `submission_cli_failed` if no job appears.
The compute bootstrap reports source failures in five non-overlapping safe
phases: spool identity, spool hash, bundle identity, bundle hash, or executable
manifest. A manifest mismatch remains fail-closed before TLS, credentials,
Podman, or the nested step. Its category contains only a mismatch count and a
33-bit manifest-index bitmap; observed hashes, paths, and command diagnostics
remain private. This diagnostic successor does not accept a login-host hash
mismatch until the corresponding compute identity has been independently
reviewed and allowlisted.
It requires two stable exact held reads, releases once, requires two stable
positive active reads, and never resubmits. A job that terminates between
release and those reads is handed directly to bounded terminal reconciliation;
malformed or temporarily duplicated accounting projections are retried, and
completion requires two identical fully validated terminal records. Ordinary
diagnostic failures are not canceled merely because accounting propagation is
temporarily incomplete. The first fully validated terminal observation latches
no-cancel semantics at every cancellation entry point; the controller requires
two fresh exact-name/owner queue absence reads before publishing its aggregate
result. The batch similarly executes the
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
