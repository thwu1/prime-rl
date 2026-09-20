# Kimi TB4 v20 inert deployment bundle

This source-and-gate-bound stage is deliberately non-executable until its exact
sealed deployment bundle receives independent approval. `SOURCE_BOUND` is true
for the reviewed RAM Common successor and `REGISTRY_GATE_BOUND` is true for the
terminal successful V33 gate. The source candidate itself carries no deployment
approval and must not be executed in its present form.

This bundle prepares, but does not authorize, deployment
`tianhaowu-k3-kda-tb4-eval-20260920t215000z` on `fair-cw-use2-3`.
Execution remains blocked until the gate succeeds and independent approval
creates the exact mode-0400 deployment approval required by `controller.py`.
The launcher additionally requires every sealed bundle SHA-256 and the exact
successful gate-result SHA-256 through named `EXPECTED_*` variables.

The V19 predecessor is not a V20 input. It bound the superseded evaluator at
`9d7841b36bafcd58769041925b00deba7c25ffca`; after its approval was created,
its only execute attempt failed closed with `tmux_socket` before the global
lock, owner intent, scheduler submission, or deployment existed. V20 uses a
new deployment, approval, lock, run, route, output, and artifact namespace and
lists the V19 deployment ID among the excluded predecessors. Its approval and
sealed bundle must never be reused for V20.

The launcher must be opened as file descriptor 9 and invoked through
`/proc/self/fd/9`. Once the gate binding is complete, `audit` performs source,
runtime, scheduler, QoS, model,
configuration, explain, and namespace validation without reading registry
credential variables and without submitting or cancelling jobs. `execute` is
the only submission mode and additionally requires the approval hash, the
pinned tmux ancestry, and validated registry credential file identities.
The successful gate is validated before deployment approval is read, and both
are revalidated immediately before `owner_intent.json` is published. That
intent embeds both canonical payloads and SHA-256 values. The captured gate is
passed into the held-submit adapter and validated there after every other
pre-submit check, immediately before the bounded `sbatch` call; later validation uses
the immutable captured approval and gate bindings, so moving consumed approval
pathnames cannot abort an otherwise healthy live service.

The evaluator is the detached, read-only Prime revision
`3842a596163bd00e831e3582252341cfff59881d` (tree
`4d83e506be6f647d5073de723960d6cba4ffad05`). Its pydantic-config, renderers,
and verifier components are independently required to remain detached, clean,
and at their pinned revisions; the verifier pin is
`615b1a30ee3d23cf8d835b64174229c19da887bc`. The VMVM v2 backend must have
SHA-256 `5542f78e505107b59e970929e577855900df51bf89976a9464f6833cf05ac11a`.
The plan, approval, route policy, and final ready commit all bind this fixed
evaluator, which is revalidated after readiness and immediately before the
commit section. The prior `a09a9a189` evaluator and backend are rejected. No
downstream compatibility bridge is authorized merely by this deployment;
each smoke or evaluation controller must prove that it consumes these exact
route-policy and ready-commit bindings before it may submit work.

The Python interpreter and complete standard library are extracted from the
hash-bound `python-runtime.tar` before Python starts. It contains no symlinks,
`.pth`, bytecode, site-packages, or cache directories. Python runs with
`-I -S -B`; the separately hash-bound `runtime.zip` is a pure-Python closed
import set for RAM deploy and YAML code.

The worker allocation uses `g3_lowest`, which is preemptible by the pinned
inbound QoS set and can itself preempt `normal`. The four reviewed bad worker
nodes (`g3-136-221`, `g3-136-247`, `g3-136-251`, `g3-136-253`) are excluded
only from endpoint worker submissions; coordinator and proxy submissions have
no node exclusion. The serving source is the detached, read-only RAM Common
revision `468a6e5b83ba51a8fe0389f1105f34dd18fa03f3` (tree
`bd6d81b7748c5055876100b9dc115eed8a764fe0`). Its mode-0400 bundle is bound by
SHA-256 `7aaeec5142d7d3e0fdaabebc441094e79300adb36aee370f8a397a3f356968a3`
and size 5,436,664 bytes. The source uses one private seeded auth file passed
directly to a bounded digest-pinned pull; it performs no network `podman login`
and runs only from the pulled image with `--pull=never`. Every worker rank must
publish terminal cleanup proof. Rank 0 and peers preserve validated process-group
identities, distinguish observation failure from positive absence, and retain
credential lifecycle state whenever absence is unproven. Worker EXIT cleanup or
finalization failure overrides an otherwise successful worker status, while an
absent optional cleanup hook remains a valid no-op.

The controller submits the coordinator held with an explicit `--nodes=1`,
reconciles ambiguous submission results by exact job name and identity, and
polls only unavailable, null request-TRES, held NumNodes null/`0`/`0-1`,
missing allocation-TRES, or not-yet-propagated held-reason reads in a 30-second
monotonic window (plus only the already-started scheduler RPC set). A null
request TRES and an incomplete node projection are independent typed transients
under the otherwise-exact held envelope; both must converge to exact values
before a stable sample counts. `NumCPUs` must immediately be semantic `4`/`4-4`
in primary, standby, and cleanup identity checks and is never a retryable lag.
The exact order-independent request map is `billing=4,cpu=4,mem=16G,node=1`;
only the semantic singleton forms `1`/`1-1` nodes and `4`/`4-4` CPUs are valid.
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
failure runs the pinned stop implementation for this exact v20 ID, then bounded
exact-name cancellation/drain and exact v20 namespace archive, recording a
cleanup receipt with a sanitized allowlisted error code. Readiness and
live-route files are staged, non-promoting evidence: a failed attempt retains
them and is rejected by the absence of `ready_commit.json`. No cleanup path
names, removes, or mutates an earlier generation.

Namespace freshness is checked before the global lock is created exclusively;
an existing file or symlink is never adopted. After acquisition, its pathname,
descriptor, captured inode, and stable parent identity are cross-checked; an
event check is confined to acquisition so unrelated sibling creation cannot
abort a held deployment. The second freshness pass still rejects every run,
route, output, deployment, or archived v20 namespace collision. The unique v20
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

Before launch, seal these exact source bytes without replacement, rerun the
full suite and static audit against the sealed bundle, and create the exact
mode-0400 deployment approval. The launcher must receive the V33 result SHA-256
and every sealed bundle hash explicitly. Never invoke `execute` before that
independent review and approval. Never use any artifact from an earlier
generation as a v20 readiness input.
