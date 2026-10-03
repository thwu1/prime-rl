# Kimi TB4 v12b inert deployment bundle

This bundle prepares, but does not authorize, deployment
`tianhaowu-k3-kda-tb4-eval-20260920t034800z` on `fair-cw-use2-3`.
Execution remains blocked until independent approval creates the exact
mode-0400 approval document required by `controller.py` and supplies every
sealed bundle SHA-256 through the named `EXPECTED_*` variables.

The launcher must be opened as file descriptor 9 and invoked through
`/proc/self/fd/9`. `audit` performs source, runtime, scheduler, QoS, model,
configuration, explain, and namespace validation without reading registry
credential variables and without submitting or cancelling jobs. `execute` is
the only submission mode and additionally requires the approval hash, the
pinned tmux ancestry, and validated registry credential file identities.
The active approval is revalidated immediately before `owner_intent.json` is
published. That intent embeds both its canonical payload and SHA-256. Once the
intent exists, later validation uses the immutable captured approval binding;
moving the consumed approval pathname cannot abort an otherwise healthy live
service.

The Python interpreter and complete standard library are extracted from the
hash-bound `python-runtime.tar` before Python starts. It contains no symlinks,
`.pth`, bytecode, site-packages, or cache directories. Python runs with
`-I -S -B`; the separately hash-bound `runtime.zip` is a pure-Python closed
import set for RAM deploy and YAML code.

The worker allocation uses `g3_lowest`, which is preemptible by the pinned
inbound QoS set and can itself preempt `normal`. The four reviewed bad worker
nodes (`g3-136-221`, `g3-136-247`, `g3-136-251`, `g3-136-253`) are excluded
only from endpoint worker submissions; coordinator and proxy submissions have
no node exclusion. The deploy source is the sealed unified RAM revision
`0322cd43963cbad632128b8e00946a55f16a8085`.

The controller submits the coordinator held, reconciles ambiguous submission
results by exact job name and identity, and bounds convergence to 31 reads with
30 one-second waits. It retries only unavailable reads, a not-yet-propagated
held reason, or a held-only `NumNodes` projection of absent, empty, `0`, or
`0-1`. The incomplete node values are never accepted: every other identity
field plus `PENDING`, priority zero, ineligible state, and `JobHeldUser` must
already be exact, and two consecutive identical full records with
`NumNodes=1` are required before release. Any definite node mismatch,
runnable/terminal state, nonzero priority, eligibility, or other identity
drift fails immediately. A sanitized nested submission error code survives the
deploy CLI's generic RuntimeError handler.
The controller then records two identical stable reads of the initial spec.
Any signal or pre-commit
failure runs the pinned stop implementation for this exact v12b ID, then bounded
exact-name cancellation/drain and exact v12b namespace archive, recording a
cleanup receipt with a sanitized allowlisted error code. Readiness and
live-route files are staged, non-promoting evidence: a failed attempt retains
them and is rejected by the absence of `ready_commit.json`. No cleanup path
names, removes, or mutates an earlier generation.

Namespace freshness is checked before the global lock is created exclusively;
an existing file or symlink is never adopted. After acquisition, its pathname,
descriptor, captured inode, and stable parent identity are cross-checked; an
event check is confined to acquisition so unrelated sibling creation cannot
abort a held deployment. The second freshness pass still rejects every run,
route, output, deployment, or archived v12b namespace collision. The unique v12b
lock is never renamed or unlinked. Every owned exit writes a bounded terminal
commit-pending/failure/signal tombstone through the descriptor, verifies the
same inode, and closes the descriptor before success publication. A replacement
pathname is retained and fails closed; retry requires a fresh successor
namespace.

Artifact publication inside each unique mode-0700 namespace writes and fsyncs a
random private temporary file, closes it before creating the final name with a
no-overwrite hard link, verifies both names, then unlinks the closed temporary.
This preserves atomic final-name visibility without triggering NFS
silly-rename behavior; any publication failure retains its artifacts and
poisons the one-shot namespace instead of deleting an uncertain pathname.

After two stable reads of the resolved spec and a live two-route generation,
the producer writes a resolved binding and launch receipt. The readiness
producer and consumer independently re-read the live final spec and cross-bind
the route policy, initial observation, resolved binding, launch receipt, and
Slurm generation identities. Each readiness publication checks cancellation
both immediately before and immediately after publication. Both readiness
artifacts remain explicitly non-promoting. After the lock becomes a verified
terminal tombstone, a unique durable commit source binds the full artifact
graph and the tombstone SHA-256/device/inode. The no-overwrite hard link from
that source to `ready_commit.json` is the sole promotion point; both names are
retained as the same mode-0400, two-link inode. Once the final hard-link syscall
is attempted, any error is treated as commit-ambiguous and never authorizes
rollback, even if an immediate NFS lookup reports absence. Signal masking
linearizes this commit.
The bundle itself sends no model requests and submits no smoke or evaluation
jobs.

Never invoke `execute` before independent review and approval. Never use any
artifact from an earlier generation as a v12b readiness input.
