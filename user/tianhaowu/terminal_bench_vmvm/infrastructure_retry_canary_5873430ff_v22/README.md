# Infrastructure retry canary V22

V22 is a fresh, non-resumable replacement for the rejected prior candidate. It keeps
the 19-entry opaque selection contract (15 retry candidates and four controls),
requires all controls plus at least six candidate recoveries, and never promotes
or unions results automatically.

V21's one permitted submission completed all 19 entries but produced no valid
rows because its private batch export omitted the complete X2P transport tuple.
The later task-free diagnostic also proved that this cluster ignores a sealed
export file when `--export=NONE` is supplied alongside `--export-file`. V22
therefore writes one complete, private, NUL-delimited export file and passes it
with exactly one `--export-file` option and no `--export`/`--export=NONE`
option. The `sbatch` client itself runs under the fixed minimal clean
environment, so no ambient caller variable supplements the file.

The canonical launcher environment must contain nonempty `X2P_ENV`,
`X2P_CFG_ENV`, and `X2P_PROXY_URL` together or admission fails before any
namespace is reserved. Their exact UTF-8 values are copied only into the
mode-0400 private export file; the job authorization, launch intent, submission
or failure receipt, and audit records contain only separately computed SHA-256
commitments. The batch wrapper checks all three values against those commitments
before task or source access. It never places the proxy value in argv, a
per-task `.env`, logs, receipts, or public output. The public tests exercise
missing members, empty and malformed values, value/hash drift, export-option
conflicts, and value non-leakage.

V22 also requires the one exact reviewed `UV_BIN_X86_64` path and rejects every
other `UV_*` name. It checks the exact approved `PYTHON_BIN_X86_64`,
`PYTHON_SITE_X86_64`, `TZ`, `SLURM_EXPORT_ENV`, common locale/user variables,
and rejects unexpected Git, loader, Bash-function, and Python-control inputs.
The public test passes the launcher's complete generated export through the
actual batch environment/TLS/X2P gate and reaches the admission-wait boundary;
mutations of each audited field fail at that gate. The post-permit receipt
program is executed with a synthetic sealed authorization, permit, environment,
and submission receipt, and every Python heredoc's argv contract is checked for
exact arity and unique targets.

Before the oracle wrapper starts, failures emit only one fixed JSON object with
`code=job_binding_failed` and an allowlisted coarse stage. Stage telemetry never
contains environment values, credential paths or hashes, task identifiers,
backend addresses, exception text, or command output.

V22 is bound to the fresh detached build-input snapshot
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-5873430ff-v22`
at commit `5873430ffbabc32672368c7df74f56023865d2b5`, tree
`e7d9d5a8cf4ca06b9ff6496ea4318154c6fcd730`, and the exact pydantic-config,
renderers, and verifiers gitlinks recorded by that tree. In particular, the
verifier gitlink is exactly
`615b1a30ee3d23cf8d835b64174229c19da887bc`, whose VMVM runtime routes the
initial work-directory creation through bounded exact-once recovery. V22
therefore exercises the repaired startup path together with the existing
fail-closed VMVM error handling instead of inheriting the older 63dc snapshot.
It does not use or modify any prior source snapshot. The frozen V1 selection
algorithm is executed from its original exact bytes, but V22 explicitly
rebinds every execution-source path, commit/tree, gitlink, VMVM aggregate, and
pinned source-file value to the fresh snapshot. The selection, authorization,
intent, submission, batch-admission, and audit chains all check the explicit
verifier revision and VMVM aggregate in addition to the source commit and tree.

The artifact root is a closed exact-nine-file surface: one mode-0400 packaging
snapshot and eight mode-0500 reviewed text artifacts, all regular, single-link,
owner-bound files in a canonical mode-0700 directory. The generator, launcher,
and auditor independently perform anchored, stable directory-FD inventory
checks at entry and again at their last applicable trust boundary. Any extra
file, directory, symlink, cache, missing entry, mode/link/owner mismatch, root
replacement, or inventory change fails closed. Public Ruff review must use
`ruff check --isolated --no-cache`; cache-producing review commands make the
bundle ineligible rather than silently extending its inventory.

The selection generator keeps `-I -S -B` isolation and does not expose an
ambient site directory or the fallback `pip` package. It loads packaging 26.3
from the mode-0400 local wheel snapshot in this directory. The snapshot binds
the upstream wheel SHA-256, exact raw size, a canonical 29-member manifest
digest, and every importable Python member. A restricted in-memory loader
rejects unmanifested `packaging.*` imports, verifies exact virtual origins,
executes only bytes captured from the hash-bound wheel, performs a
Requirement/marker semantic probe, and restores `sys.modules`, `sys.path`,
`sys.meta_path`, and `sys.path_importer_cache` on every exit. The snapshot is
revalidated after module use; no wheel member is extracted and no source-tree
bytecode is read or written. Import failures have distinct aggregate-only codes
for the packaging, source-wheels, exporter, builder, and auditor stages.

The launcher submits exactly once with `sbatch --hold`. While the allocation is
held it requires at least two consecutive, full scheduler identity snapshots
that also prove user hold, no start, no node allocation, and no job steps. Only
then may it publish the precomputed mode-0400 job authorization. Release is
attempted exactly once and reconciled from scheduler state without retry. Held
polling spans its full 982-second monotonic bound even when queries return
immediately; a two-second rate cap and a conservative deadline-derived
493-iteration fail-safe prevent either fast-query truncation or an unbounded
loop. Activation uses the same design for its full 742-second bound and a
derived 373-iteration fail-safe. Every multi-query poll caps each scheduler
query to its shared remaining budget. The batch admission wait is 900 seconds,
which strictly exceeds the 20-second release-call bound plus the 742-second
activation bound and 30 seconds of publication slack. The job is still held
during the longer held gate, so the batch-side admission timer has not started.

Held and activation receipts use `deadline_poll_v1` aggregate telemetry. They
record mismatch-field occurrence counts and final mismatch names, plus safe
categories—not raw scheduler values—for `NumNodes`, `NodeList`, and
`BatchHost`. Held accounting distinguishes unavailable, absent, mismatched
shape, and exact observations. In the held-only `scontrol` record, the one-node
request must be rendered exactly as `NumNodes=1-1` and `NodeList` must be
omitted or have an exactly empty value. Literal null tokens, assigned node
names, other ranges, and all other values are rejected while held. After
release, activation remains strictly separate: it requires exact `NumNodes=1`
and a non-null, syntactically valid assigned `NodeList`; the held representation
cannot satisfy activation.

The batch wrapper performs no source, cache, VMVM, task, or output setup until a
separately precommitted activation permit exists and the reservation is sealed
mode 0500. It validates the authorization, activation permit, final submission
receipt, immutable export environment, exact allocation identity, and exact
reservation shape before entering the oracle wrapper.
The receipt and permit are prepared under blocked termination signals; the
mode-0500 transition is the explicit admission commit point. The reservation
directory is fsynced after that transition and in-memory committed state is set
before signals are restored. No post-commit error may cancel the job, reopen the
reservation, or add a failure certificate.

Every failure, signal, or other `BaseException` after a job may exist recovers
the unique submission, cancels the exact job, and requires stable queue absence,
a terminal allocation, and terminal job steps before publishing an ordinary
failure. If that proof cannot be obtained, the only permitted terminal status is
`cancellation_unconfirmed`; the activation permit is never a valid success
surface in that state.
Cancellation retries transient identity reads and normally proves the exact job
ID/name/user tuple before cancellation. If those reads stay unavailable, only a
candidate returned directly by the sole trusted `sbatch` call (optionally also
confirmed by name lookup) may receive one exact-ID `scancel`; a name-only or
unbound candidate never does. The launcher then requires the full terminal
proof, otherwise it seals `cancellation_unconfirmed`. Failure receipts retain
only allowlisted held/release/cancellation poll counts, timing, state classes,
candidate provenance, and mismatch field names.
Missing or empty identity fields are classified as incomplete and retried; they
are not treated as proof of a conflicting allocation. `UserId` must equal
`tianhaowu(656177)` exactly. Any observed nonempty `JobId`, `JobName`, or
`UserId` that conflicts with the expected value is monotonic across held-state,
activation, and cleanup polling: later matching observations cannot authorize
the job or erase the conflict, and no later release or cancellation control is
allowed. The pre-cancellation snapshot explicitly distinguishes an identity
conflict, unavailable/incomplete identity, an active exact identity, and a
fully terminal exact identity. A conflict appearing after initial identity
proof but before `scancel` therefore produces zero cancellation calls and seals
`cancellation_unconfirmed`.

Direct `sbatch` provenance is also monotonic. A candidate returned by the sole
`sbatch` call remains direct when later name lookups confirm it; repeated lookup
cannot downgrade `sbatch_and_name` to `name_lookup`. This preserves the narrowly
approved one-shot exact-ID cancellation fallback when every identity read is
unavailable or incomplete, while an explicit conflict always overrides that
fallback.

Cancellation identity polling is deadline-driven for 180 seconds and terminal
allocation/all-step proof for 300 seconds, each with a two-second rate cap and a
deadline-derived fail-safe. Failure telemetry retains only occurrence counts,
final mismatch names, state classes, and timings; it never retains raw
scheduler values beyond the already-authorized job identity.

V22 additionally requires the canonical launcher pane to supply exactly
`THRIFT_TLS_CL_CERT_PATH` and `THRIFT_TLS_CL_KEY_PATH`. The launcher rejects an
otherwise extra or missing outer variable and opens each raw absolute caller
path first with `O_NOFOLLOW`, so a final symlink is never accepted. An
intermediate-directory alias is permitted only after the held descriptor yields
a canonical target that is reopened through a held canonical-parent descriptor
and proven to be the same inode. The target must be a regular file owned by uid
656177 with mode 0500, one link, and exact size 5580. Both variables may resolve
to the same target and digest only when the descriptor bytes form exactly two
`CERTIFICATE` PEM blocks and one unencrypted `RSA PRIVATE KEY` PEM block, with no
other non-whitespace data. Generic PKCS#8 `PRIVATE KEY`, `EC PRIVATE KEY`,
`ENCRYPTED PRIVATE KEY`, partial, extra, mixed, mislabeled, and malformed blocks
all fail closed. Two different files retain the prior distinct-inode and
distinct-digest rule.

The launcher hashes through stable descriptors, retains both descriptors and
their canonical-parent bindings, and reopens both the raw alias and canonical
target during the final identity/hash/PEM recheck immediately before the sole
`sbatch`. It exports the canonical stable target—not the caller alias—for each
Thrift variable. Those paths and credential digests exist only in the mode-0400
private Slurm export file. Public intent, authorization, activation,
submission/failure, stdout, and post-run artifacts contain neither credential
path nor credential digest; they bind only the whole private environment-file
hash. The batch wrapper repeats a no-output `python -I -S -B`
descriptor/canonical-parent/path/hash/PEM validation under an exact nine-variable
`env -i` before waiting for admission and again immediately before entering the
hash-pinned oracle wrapper. Both required Thrift path variables remain exported
to `vacli`; the private expected-digest variables are retained only as admission
bindings.

The post-run auditor accepts only the V22 success shape and binds the job
authorization, activation permit, submission receipt, selection, scheduler
identity, and final output hashes. It still requires exact `COMPLETED 0:0`, all
19 result rows, all four controls valid, at least six candidate recoveries, and
does not authorize promotion.

All generator, launcher, and auditor invocations require separate exact-hash
review and canonical tmux ancestry. No artifact in this directory is an
authorization to run a private validation, submit a job, audit a run, or promote
results.

The public suite includes a gated real-input regression that invokes the exact
generator entrypoint with `--validate-inputs-only` under the sanitized
`-I -S -B` environment. It is skipped unless an independent reviewer explicitly
sets `RUN_V22_REAL_INPUT_REGRESSION=1` from the canonical one-shot pane; the
subprocess receives only the generator's production allowlist. This keeps a
newly frozen V22 unconsumed while still making the previously missed import
closure reproducible before approval.

A second reviewer-gated test exercises the actual two TLS files without
creating a selection, reservation, log, audit, or output namespace and without
querying Slurm. It is skipped unless the reviewer supplies the two existing
credential variables through an outer `env -i` and sets
`RUN_V22_TLS_REAL_INPUT_REGRESSION=1`. The nested isolated probe emits only
`credentials=2`, `private_fields=4`, and a fixed success state. It never prints
or records paths, digests, metadata beyond those counts, or file contents. This
test is a pre-execution review gate, not authorization to run the generator or
launcher.
