# Kimi TB4 v13 inert deployment bundle

This bundle prepares, but does not authorize, deployment
`tianhaowu-k3-kda-tb4-eval-20260920t045200z` on `fair-cw-use2-3`.
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

The controller submits the coordinator held with an explicit `--nodes=1`,
reconciles ambiguous submission results by exact job name and identity, and
polls only unavailable, null request-TRES, missing allocation-TRES,
not-yet-propagated held-reason, or narrowly incomplete node-count reads in a
30-second monotonic window (plus only the already-started scheduler RPC set).
The exact order-independent request map is `billing=4,cpu=4,mem=16G,node=1`;
only the semantic singleton forms `1`/`1-1` nodes and `4`/`4-4` CPUs are valid.
While held, node spellings missing, empty, `0`, and `0-1` are retryable but
never valid samples. CPU cardinality has no corresponding observed exception:
every non-singleton CPU spelling, including null or zero, fails immediately.
Every other static identity field remains strict; runnable/terminal state,
nonzero priority, eligibility, resource-bearing held allocation, malformed or
non-null partial TRES, or definite reason drift fail immediately. Two
consecutive identical reads of the fully held record are required before the
controller may return from submission. After the one release call, two
consecutive identical positive active records are required, including complete
singleton allocation and coherent pending eligibility or exact started
allocation TRES. A sanitized nested
submission error code survives the deploy CLI's generic RuntimeError handler.
The source-created cold standby is independently polled under the exact
`afternotok` dependency on the primary. It is accepted only after two identical
strict PENDING/Dependency records with the same exact request resources,
semantic singleton counts, and no allocated TRES; only bounded null/zero
scheduler-propagation fields retry, and cleanup applies the same stable proof
without ever releasing the standby. Cleanup binds the primary and standby
before invoking the exact deployment stop. A successful pinned stop directly
credits pre-bound IDs because its own contract includes exact queue drains and
held-job cleanup; this does not depend on a never-started job acquiring a sacct
row. Unbound IDs require two clean exact-name-and-owner queue-absence reads.
Lifecycle or identity warnings never veto the namespace-scoped stop, and a
failed stop may fallback-cancel only a strictly bound coordinator or a worker
or proxy that passes its role-specific exact cancellation predicate.
The controller then records two identical stable reads of the initial spec.
Any signal or pre-commit
failure runs the pinned stop implementation for this exact v13 ID, then bounded
exact-name cancellation/drain and exact v13 namespace archive, recording a
cleanup receipt with a sanitized allowlisted error code. Readiness and
live-route files are staged, non-promoting evidence: a failed attempt retains
them and is rejected by the absence of `ready_commit.json`. No cleanup path
names, removes, or mutates an earlier generation.

Namespace freshness is checked before the global lock is created exclusively;
an existing file or symlink is never adopted. After acquisition, its pathname,
descriptor, captured inode, and stable parent identity are cross-checked; an
event check is confined to acquisition so unrelated sibling creation cannot
abort a held deployment. The second freshness pass still rejects every run,
route, output, deployment, or archived v13 namespace collision. The unique v13
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
artifact from an earlier generation as a v13 readiness input.
