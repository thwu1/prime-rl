# Kimi registry direct-pull gate v32

This candidate derives byte-for-byte from reviewed V30 commit
`a7ae446d908e54e8449d4468c24002a14f30207f` before the V32 namespace and
source-binding barrier were added. It remains bound to the completed V5
compute-tool evidence and pinned to `g3-128-185`. V32 is bound to reviewed RAM
Common successor `468a6e5b83ba51a8fe0389f1105f34dd18fa03f3`, which adds fail-closed
rank-0 process-group cleanup proof, early-signal coverage, cleanup-status
propagation, and correct optional-hook handling on top of the direct-pull
implementation.

`SOURCE_BOUND` is true. The source root, revision, tree, immutable bundle,
bundle size, and all four launch-critical file hashes are exact. The pending
plan is awaiting independent approval and remains non-launch-eligible until
that separate approval is created after sealed-byte review.

With the corrected RAM Common successor independently reviewed and rendered,
the gate exists only to prove the compute-side registry path: mint one private
credential with explicit text output, seed and verify one isolated auth file,
perform exactly one guarded digest-pinned pull, attest the pulled image, remove
it, and scrub all private state. It does not run a task, model, endpoint,
sandbox, evaluator, or container.

The probe first requires isolated `podman info` and proves the target image is
absent from its fresh job-local store. It performs exactly one
`ucloud ... --outform text` mint and conservatively accepts only a single-line,
safe-character credential between 2 KiB and 16 KiB. It seeds a mode-0600,
single-link auth file, binds that file by inode identity and SHA-256, and makes
one guarded offline `podman login --get-login` lookup that must return the
fixed username. This lookup performs no network login. The gate then performs
exactly one guarded `podman pull` of the sealed digest-pinned reference with an
explicit auth file, `--platform linux/arm64`, and `--tls-verify=true`. There is
no network login, retry, or backoff.

After a successful pull, one local inspect must prove the exact digest,
`linux/arm64` identity, and the exact canonical repository-plus-digest member
(an alias carrying the same digest is not sufficient). The image is forcibly
removed and its absence is proved even when inspection fails. Credential,
command, inspect, and storage state are descriptor-bound, kept private, and
scrubbed. Success is accepted only for the exact expected five-field JSON;
every other result is blocked under a fixed, safe, allowlisted category covering the
mint, token shape, auth file, guard stage, HTTP/authentication, TLS/proxy,
transport/timeout, image/platform/storage/identity/removal, cleanup, and
lifecycle phases. Raw credentials, command output, and error text are never
published.

The gate requests one node, one task, one GPU, four CPUs, 16 GiB, and 30
minutes on `g3/g3_lowest` under account `ram`, excluding the four reviewed bad
nodes. It is pinned to `g3-128-185`, the node measured by the completed V5
compute-tool diagnostic. The controller binds the exact mode-0400 private
manifest, controller result, public job result, and V5 approval by hash and
size. It independently requires all 33 primary rows to be labeled
`fresh_compute_node`, requires both nofollow path and followed-target identities
to be root-owned regular mode-0755 single-link files, reconstructs
`compute_tools.sha256` strictly from the 33 observed hashes, and requires exact
byte equality with the sealed manifest. The V5 aggregate and selected Python
identity are cross-validated. No reviewed hash from an older node is reused.
The runtime attestation applies the same nofollow and followed identity rules,
so symlinks fail explicitly. All 33 entries must match at runtime. The batch
shell starts exactly one production-shaped nested `srun` so the normal task
prolog applies. The probe sources only the sealed cleanup and auth-file helper
definitions; it does not invoke the production retry loop. Its only registry
network operation is the single guarded pull, and its only post-pull image
operations are the exact local inspect, forced removal, and absence check. It
never calls `container_run`, `podman run`, GPU enumeration, a checkpoint, a
model, an endpoint, a sandbox, a task, or an evaluator.

Raw lookup and pull output is written only to private helper-managed temporary
files; the inspect/state file is descriptor-retained. Every retained sensitive
regular file is truncated and fsynced through its descriptor, then unlinked
relative to its retained parent directory only after the named entry is
re-proved to be that inode; nlink zero is proved before close. A moved
inode is still scrubbed but its replacement is never removed and the gate fails
closed as retained drift. The empty batch root and the probe's empty directory
skeleton are retained, so cleanup never performs a pathname `rmdir`.
The shared Slurm log contains exactly one canonical, allowlisted JSON line.
The Podman graphroot, rootless storage path, and runroot are bound to fresh
job-local directories; their exact real-path identities are checked around
every Podman operation. Descriptor-only opens scope diagnostic suppression to
the open operation and restore the probe's private stderr before any later
marker. Initial Podman preflight failures distinguish command failure,
malformed output, graphroot drift, runroot drift, and driver drift. A fixed
private retained-empty marker is
required before accepting any post-root operational category, and any cleanup
failure takes precedence over the operational marker. A hash-bound guard
reached through a retained descriptor repeats those checks immediately before
and after the offline auth-file lookup and the sole digest-pinned pull. The
guard permits only those two exact argument vectors, verifies the seeded auth
file's identity and hash around each child, and emits only fixed
`precondition`, `child`, and `postcondition` markers into the private
diagnostic stream. The probe
retains descriptors for every top-level private directory, globally preflights
all cleanup targets before mutation, rejects hardlinks, special files,
cross-device entries, and mount-table entries (including same-device bind
mounts), and scrubs through those anchors even if a name moves. Each directory
manifest is rechecked immediately at its mutation boundary. The no-follow
scrubber globally preflights all supplied directory graphs before mutation and
rejects symlinks, special entries, hardlinks, and device crossings.

The cleanup trust boundary is the fresh mode-0700 job-local tree after all
supervised Podman children have exited or been reaped. A descriptor-bound,
fsynced armed/quiesced handshake surrounds every Podman storage operation; if
quiescence cannot be proved, cleanup refuses to mutate the tree. No concurrent
writer is authorized inside it. The signal handler also requires that positive
quiescence proof after stopping and waiting for its tracked timeout; it retains
auth, raw output, and storage if a descendant may have survived. A hostile
process running as the same uid is outside the
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
fresh 33-row projection, source provenance, scheduler/QoS semantics, and fresh
namespaces without reading TLS variables and without submitting or cancelling
a job. `execute`
first enforces the same source barrier, then revalidates the V5 evidence before reading TLS and
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
remain private. The login host is derived only from the sealed digest-pinned
target and must match the fixed ECR host shape.
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

The rendered source fields bind the immutable `468a6e5` source root and bundle,
and `probe_registry_gate.sh` independently checks the same revision and tree.
Regenerate `pending.json` after every candidate-byte change, rerun the complete
offline suite and bound audit, and independently review the exact sealed bytes.
Do not create an approval or invoke `execute` until that review is complete.
This direct-pull gate is not a Kimi deployment authorization.
