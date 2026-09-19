# Terminal-Bench on VMVM

This directory contains the Prime-RL v1 Harbor adapter and operational scripts
for the 2,538 `mobius-tb/*` tasks and official Terminal-Bench 4.0.0. The
runtime is `VMVMRuntime`, which uses the hardened `vmvm_tb_v2`
vacli transport (lease retries, SSH reconnection, binary-safe transfers, and
bounded command output).

The VMVM backend defaults to `/public/fbpkgs/x86_64/vacli/stable/vacli`.
The moving `latest` build was rejected because its x2p helper fails with a
GLIBC-version error on part of the heterogeneous `cpu_x86` fleet. Override
`VACLI_BIN` only for a canary that has passed `probe_vmvm.sbatch`.

Correctness invariants:

- An infrastructure failure is never converted into reward zero.
- Shared-verifier tasks retry the whole rollout after `SandboxError` or
  `TunnelError`; verifier code cannot replay a model command.
- Separate-verifier tasks capture artifact bytes once and may retry only a
  fresh verifier VMVM against those identical bytes.
- Image tags are immutable corpus revisions, never `latest`.
- Oracle and rollout outputs have one writer and are durable while a run is in
  progress.
- Compose tasks run the declared sidecars inside the same VMVM lease. Artifact
  collection addresses the declared service, and the exact captured bytes are
  replayed into a fresh verifier VMVM.
- Oracle validity is determined by the task verifier. A nonzero reference
  script status is retained as a warning because some separate-mode scripts
  emit the correct artifact before an optional self-check that needs
  verifier-only code.

## Pinned inputs

- Mobius corpus: Prime-RL commit `ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366`
  (2,538 immediate child task directories, including the validated fixture
  repairs on top of corpus commit `9b6988a3faf0f58f8f6719abef51c60dc257586c`).
- TB4: `harbor-framework/terminal-bench` commit
  `452bf305c6daa62fc59061d22133a7cbc7c1572e` (`v4.0.0`, 66 tasks) and its
  official prebuilt release archive SHA-256
  `6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e`.
- Harbor harness: `0.14.0`.
- mini-swe-agent harness: `2.2.8`.

## One-time CPU setup

The login node is ARM64 and `cpu_x86` nodes are x86_64. Do not reuse
`~/.local/bin/uv` on compute nodes. Install the official x86 uv binary under
`~/.local/x86_64/bin`, then stage target-platform dependencies from the
networked login host:

```bash
bash user/tianhaowu/terminal_bench_vmvm/stage_x86_dependencies.sh
bash user/tianhaowu/terminal_bench_vmvm/fetch_tb4.sh
```

The dependency target defaults to
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64`. Slurm jobs add
the local source trees ahead of it in `PYTHONPATH`, so code edits take effect
without rebuilding that layer. The route gate runs the `serve_api_v2` status
module with its compute-node Python rather than executing `serve.sh`, whose
checkout virtualenv may have been materialized for the ARM64 login node.

`vmvm-sandbox` intentionally does not check out the 2,538 task directories.
Materialize the pinned repaired corpus as a detached worktree instead:

```bash
git fetch origin feat/tb4-vmvm-pipeline
git worktree add --detach \
  /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 \
  ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366
```

The checked-in password-protected `tb_tasks.zip` matches the original corpus,
but not the later validated fixture repairs, so it is not the production
dataset source.

## Build images

First resolve the already-published Mobius images to immutable Docker Hub
digests. The resolver pages the public tag API, requires a Linux/amd64 image,
and verifies all 2,538 task slugs:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/resolve_dockerhub_images.py \
  --dataset-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 \
  --output /checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json \
  --require-all
```

The images currently live in `docker.io/tianhao0122/optimbench-tb`. The
taskset consumes the generated manifest and therefore pulls `tag@sha256`
rather than mutable tags. If coverage is incomplete, generate the deterministic
VMVM rebuild plan:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/prepare_build_plan.py \
  --dataset-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 \
  --output /checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_plan.jsonl \
  --image-prefix vmvm-registry.fbinfra.net/terminal_bench \
  --image-tag mobius-9b6988a3faf0

```

TB4 uses its official release bundle rather than rebuilding images. Its task
files point to digest-pinned Docker Hub images for the agent, verifier, and
sidecars.

Submit rebuilds, if any, as Slurm state changes from
`swebench_vmvm:Launcher.0`:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "sbatch --parsable --export=ALL,BUILD_PLAN=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_plan.tsv user/tianhaowu/terminal_bench_vmvm/build_images_vmvm.sbatch" C-m
```

Each worker holds one VMVM lease and builds its deterministic slice. Per-image
status files make the operation resumable without concurrent append races.
Audit before validation:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/audit_builds.py \
  --plan /checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_plan.jsonl \
  --require-all
```

## Oracle validation

Smoke one task first by putting its directory slug in a text file and setting
the `TASK_FILE{,_SHA256}` pair. Then run the full set:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_full_oracle_public_<commit>_v1 DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 DATASET_REVISION=ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366 IMAGE_MANIFEST=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json IMAGE_MANIFEST_SHA256=118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009 ORACLE_SOLUTION_NETWORK_MODE=public MAX_CONCURRENT=8 VACLI_LEASE_RETRIES=20 VACLI_MAX_CONCURRENT_LEASES=4 VACLI_MAX_PULL_RETRIES=20 VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600 VACLI_CONTAINER_PRIVILEGED=1 TIMEOUT_MULTIPLIER=2 RESOURCE_MULTIPLIER=2 MINIMUM_PASS_RATE=0.9 MINIMUM_VALID=2500 sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch" C-m
```

`run_oracle.py` writes one atomic JSON result per task plus `results.jsonl` and
`summary.json`. Before any row can be reused, it verifies an immutable
`run_identity.json` that binds the clean dataset revision (or official archive
and extracted-tree digest), ordered task selection, task/image manifests,
source and runtime pins, network semantics, execution settings, and acceptance
thresholds. Initial provenance is write-once and later invocations are recorded
separately. A resumed invocation skips existing terminal results unless
`RERUN_INVALID=1`; any missing or mismatched identity requires a fresh output
directory. The full-corpus acceptance gate is at least 90% and at least 2,500
valid tasks; task failures must be debugged separately from VMVM infrastructure
failures. Promotion accepts any number of ordinary resumes but at most one
`RERUN_INVALID=1` recovery invocation, and binds the strictly validated
invocation history into the promotion receipt. Invocation records require
canonical unique Slurm job IDs and strictly increasing timestamps. Promotion
takes the same exclusive `.writer.lock`, so it rejects a live oracle or resume
rather than reading a changing result set.

Run `export_oracle_tasks.py` once without `--apply` and review its aggregate
counts and hashes. The identical apply invocation must include a fresh
`--receipt /checkpoint/.../oracle_promotion_<commit>.json` path outside the Git
worktree. Apply mode atomically updates the approved 2,500-task manifest and
its configured hashes, then publishes a mode-0444, self-hashed receipt binding
the final oracle artifacts, immutable run identity, acceptance thresholds,
dataset/image/runtime pins, selected manifest, and updated configs. An existing
receipt path fails closed; it is never overwritten.

Strict oracle validation applies the declared agent policy to `solve.sh` and
is the default. Some legacy reference solutions download build dependencies
despite declaring agent `no-network`. For corpus qualification only, set
`ORACLE_SOLUTION_NETWORK_MODE=public`: this leaves the trusted image startup
and reference solution on the setup bridge, records the override in immutable
run semantics and task/summary provenance, then activates the declared policy
before artifact collection and verification. It never changes model rollouts.
Report this compatibility result separately from the strict-policy result, and
use a fresh output directory when changing modes.

The adapter resolves Harbor's environment, agent, and verifier network policy
with Harbor 0.14.0 precedence. For `no-network`, trusted dependency staging
finishes first; immediately before untrusted agent or verifier execution, VMVM
moves all workload containers onto a private internal IPv4 network. Compose
aliases remain available, while a subnet-scoped firewall permits only internal
DNS and the main container's active reverse-tunnel port and rejects the gateway
proxy and other host traffic. Unknown modes, allowlists, IPv6, residual public
attachments, and attempts to relax an active policy fail closed.

Shared offline verifiers prefetch their declared dependencies before any agent
phase even when the agent itself is public. Prefetch accepts wheels only
(`--only-binary=:all:`), so package build hooks cannot execute during trusted
setup; source-only requirements fail closed. Cached controller archives are
read-only and tied to the taskset lifetime, per-runtime references are removed
on every terminal path, and evaluator shutdown deterministically deletes the
cache. Hidden tests are staged only after verifier network isolation; sandbox
wheelhouse copies are removed after use. A cleanup failure aborts an otherwise
successful prefetch or restore; after a primary failure or cancellation, it is
logged without replacing that primary outcome.

An oracle-only source-wheel recovery path is available for an independently
reviewed, digest-pinned exception set. It remains disabled unless
`ORACLE_SOURCE_WHEEL_POLICY` and `ORACLE_SOURCE_WHEEL_POLICY_SHA256` are both
set. Each policy entry binds an exact requirement set, target image digest,
observed `pip`/`setuptools`/`wheel` versions, one source distribution, its
complete binary-wheel closure, and every input and output filename, size, and
SHA-256. The adapter tries the ordinary wheel-only path first and consults the
policy only for a narrowly classified binary-unavailable result; Compose tasks
and non-oracle setup reject the policy.

The recovery builder downloads only the policy's credential-free HTTPS
artifacts, verifies them, then activates `no-network` before executing any
source build. It creates a fresh no-system-site Python environment, installs
the exact hash-pinned build-tool and full transitive build-dependency wheel
closure offline with `--no-index --no-deps`, and attests every local
distribution, location, and installed-file manifest. Dependency discovery
parses the pinned legacy metadata as text and never imports or executes it.
Supported sources must have exactly one direct, unaliased `setup(...)` or
`setuptools.setup(...)` invocation after its matching module-scope import. The
invocation must be the final module statement. Unrelated legacy metadata
computation may remain only within a positive grammar for literals,
source-relative metadata reads, fixed string/path transforms, static package
discovery, and explicit Python version guards. Resource contexts, URL fetches,
archive extraction, `Extension`, `ext_modules`, and `cffi_modules` are rejected
rather than executing or interpreting build helpers. Explicit package names
must be dotted Python identifiers. Every read-bearing path, `package_dir`, and
package-data path must be one exact, non-expanding source-relative value without
parent components, URI schemes, backslashes, or glob syntax. Every archive
member must be inside the one canonical `PKG-INFO` root; `MANIFEST.in`,
pre-generated egg-info/SOURCES metadata, sibling members, and symlinks fail
closed before parsing or extraction. Automatic manifest inclusion is disabled.
`setup.cfg` accepts only reviewed metadata,
package, entry-point, requirement, and deterministic wheel/egg options; it
applies the same package/path confinement and rejects custom build keywords.
Local metadata reader helpers must match that grammar and be used exactly once as
`long_description`; arbitrary imports, assignments, helper calls, side effects,
and dynamic non-dependency keywords fail closed. The sole local-import form is
the direct, unaliased source-package import used only for `__author__`,
`__doc__`, `__email__`, or `__version__`. Each accessed value must be a unique
static string or module docstring in the package initializer. The build runner
preloads those values in an inert synthetic module, so it never executes that
initializer. The exact legacy
`sys.argv[-1] == "publish"` release branch is statically known to be unreachable
under the fixed `bdist_wheel` argv; every other process-launch or exit call is
rejected. Setup aliases, reflected or additional setup references,
branching/looping selection of the setup call, `**kwargs`, dynamic
`setup_requires`, and `cmdclass`/`distclass` controls also fail closed. Metadata
helper parameter annotations and function type parameters are rejected because
evaluating either can execute package-controlled expressions. Literal
`setup_requires` from the direct call or deterministic
`setup.cfg` `[options]` configuration, together with `build-system.requires`
from a setuptools-backed `pyproject.toml`, is included in the exact transitive
closure. `setup.cfg` rejects defaults, dynamic `attr:`/`file:`/`find:`
directives, and all command aliases.
Only the `build-system` `pyproject.toml` table and setuptools backend are
supported; duplicate declarations, in-tree or alternate backends, and
ambiguity fail closed. Static-parser rejection is reported only as the stable
aggregate code `source_build_metadata_unsupported`; private parser details are
not emitted. The setup
backend runs directly under the venv Python's real `-I -S` isolated/no-site
mode after network isolation, rather than through a pip child that could lose
the isolated flag. It manually adds only the attested venv-local site roots, so
`.pth` and customization modules are never processed. The build runner
independently rechecks the canonical archive root and forbidden inclusion
metadata, extracts only that root, and normalizes every extracted file and
directory mtime to the fixed `SOURCE_DATE_EPOCH`. The build also binds timezone,
locale, `HOME`, `TMPDIR`, work directory, and umask controls. Its fixed
`PATH` contains only the attested venv's `bin`
directory, so backend children that invoke `python3` or a build-dependency
console entry point cannot select an ambient executable or mask an undeclared
tool with a base-image command. The attested setuptools backend and site roots
precede the source root on `sys.path`, and a source-local `setuptools.py` or
`setuptools/` tree fails closed. It
reattests the complete environment after the backend returns and rejects any
mutation. It creates a deterministic archive and proves an offline
`--no-index --no-deps` install in a clean target VM with the same immutable
image and runtime fingerprint. A process-wide
semaphore limits this exceptional builder path to one VMVM lease while normal
oracle concurrency continues.

The runnable policy must first be discovered and proven from the private,
digest-pinned probe input through `run_source_wheel_proof_clean_env.sbatch`,
which invokes the canonical `run_source_wheel_proof.sbatch` launcher. The probe
input
is intentionally incomplete: it binds the target images, exact requirement
sets, source URLs, sizes, hashes, and corpus provenance, but it does not claim
target toolchains, binary closure artifacts, or output-wheel hashes. Keep it as
a regular mode-0600 file in a mode-0700 directory and provide its independently
computed SHA-256. Regenerate it deterministically as the six-entry subset
accepted by the reviewed static grammar; do not carry the excluded dynamic-SCM,
native-extension, or CFFI forms into the proof. The launch approval must
separately require exactly six entries and pin the canonical JSON digest of the
complete `missing_required_evidence` list. Use a new mode-0700 proof output
directory.
After independently reviewing the reducer at the same frozen source revision,
create that subset without hand-selecting an entry:

```bash
umask 077
/path/to/pinned/uv run \
  --project /path/to/clean-reviewed-checkout/user/tianhaowu/terminal_bench_vmvm \
  --frozen python \
  /path/to/clean-reviewed-checkout/user/tianhaowu/terminal_bench_vmvm/reduce_source_wheel_probe_input.py \
  --input /path/to/private/nine-entry-probe.json \
  --input-sha256 <independently-reviewed-nine-entry-sha256> \
  --output-dir /path/to/new-private-six-entry-reduction
```

The reducer strict-loads the digest-pinned canonical input, fetches each
distinct source once from its already pinned credential-free HTTPS host,
checks exact size and SHA-256, and applies the production static grammar. It
publishes only if exactly six entries pass and exactly three fail, preserving
the retained entry objects, order, and all non-entry envelope fields. Its new
directory is mode 0700; `probe_inputs.private.json` and
`reduction_receipt.json` are mode 0600. Stdout and the receipt contain only
aggregate counts, grammar identifiers, hashes, and stable failure codes. Review
and hash both files independently before using the reduced input; never expose
task names, package names, URLs, parser errors, or artifact bodies.

Initialize `deps/verifiers`, `deps/renderers`, and `deps/pydantic-config` at
their recorded gitlinks in that checkout; the launcher rejects absent, moved,
or dirty dependency worktrees.

Each input entry starts exactly three fresh VMVMs from the same image: two
disposable builders and one clean install target. The first builder downloads
and validates the pinned source, enters `no-network`, and builds a resolver
seed. The second builder uses only that wheel as the source candidate while it
discovers the platform-specific wheel-only dependency closure; every selected
HTTPS artifact is downloaded, hash-checked, and metadata-checked before that
builder is isolated. Both builders then produce and validate the complete
closure offline in separately created no-system-site environments. Each
environment attests its exact build-tool and transitive dependency wheels,
local distribution locations, import path, installed-file manifests, and full
venv `bin` inventory. The real setup backend runs under isolated/no-site Python
with only those attested site roots ahead of the source root and the fixed build
environment, a venv-only child-process `PATH`, work directory, and umask, then
must reproduce the pre-build environment
attestation. Each wheel is validated byte-by-byte as an exact, comment-free ZIP
envelope of unique normalized regular-file paths. Central and local headers,
raw names, flags, offsets, and record extents must agree and exactly cover the
archive; extra fields, orphan bytes, signature records, special modes, and
ambiguous encodings or paths fail closed. Both builders must emit the same
complete wheel filename set, byte-identical complete raw ZIP wheels, and a byte-identical
deterministically packed wheelhouse. The schema-bound semantic digest, with only
the local and central DOS time/date fields zeroed, is retained as supplementary
evidence and cannot authorize a raw mismatch. The common exact wheelhouse is the policy
artifact installed in the already-isolated clean target for its offline closure
check.

The launcher defaults to two entries and six live VMVMs; three entries and nine
VMVMs are hard caps. It emits only aggregate counts, hashes, and stable error
codes. Before any proof completes it publishes a non-runnable candidate and an
atomic checkpoint. A mode-0700 journal publishes immutable, hash-chained
mode-0400 intent, start-result, lease-identity-hash, and stop-result records
around every VMVM start. Resume fails closed if those records are incomplete or
cannot account exactly for every completed entry, so retried or indeterminate
starts cannot be hidden by the 18-start certificate. Only after every entry
passes and a second source/tool validation succeeds does it write an immutable
`post_run_validation.json` receipt bound to the exact state and journal head.
It then writes `finalization.json`, reconciles the proof certificate, and
publishes the runnable `source_wheel_policy.json` last. A complete state without
that validation receipt cannot resume into publication. Receipt-only,
finalization-only, proof-only, and policy-only crash states are deterministic to
recover.

`run_identity.json` binds the source-build-environment and wheel-semantic-digest
schema versions, exact raw-wheel/wheelhouse equality, the supplementary
two-field timestamp normalization, and every forbidden ZIP feature. The
candidate names raw and semantic wheel equality, venv-only child execution, and static configuration parsing as
required proofs before work starts. Any contract or schema change therefore
changes the run identity and requires a fresh output directory; it cannot resume
or finalize an older raw-byte proof.

The launch approval also pins the canonical in-allocation clean wrapper and
launcher bytes, exact inspection host, exact `uv`, Python, and vacli
executables, the complete Python stdlib/runtime manifest, the staged
site-packages manifest, and the VMVM backend sources. Generate the aggregate
hash candidates on the target x86 runtime with
`inspect_source_wheel_proof_environment.py`, review them independently, and
pass the approved values explicitly. Submit from tmux through a fresh `env -i`
allowlist. The launcher rejects Bash startup hooks, exported functions,
dynamic-loader controls, and Python or uv environment injection. It starts the
pinned Python with `-I -S -B`; the stdlib-only bootstrap validates the source,
tools, stdlib, site packages, and every effective import root before adding
those roots to `sys.path`. It never processes `.pth`, `sitecustomize`, or
`usercustomize`.
The proof rehashes every execution binding and revalidates the source commit,
tree, three clean submodule gitlinks, and VMVM sources after all leases stop but
before finalization. The certificate binds every approved digest and distinct
role-keyed hashes derived from vacli's real session identity; container IDs,
runtime names, and raw lease identifiers are never accepted or printed.
The inspector accepts explicit paths for `--project-dir`, `--clean-wrapper`,
`--launcher`, `--uv`, `--python`, `--python-stdlib`, `--site-packages`,
`--vacli`, and `--vmvm-source`. Its canonical receipt emits the exact
`invocation_host` alongside only canonical hashes. Invoke it with the exact
pinned Python as `-I -S -B`, save stdout as a regular mode-0600 file in a
private directory, and review and hash that file externally. Pass the file and
digest as `SOURCE_WHEEL_PROOF_INSPECTION_RECEIPT{,_SHA256}`, copy its reviewed
host into `SOURCE_WHEEL_PROOF_EXPECTED_HOST`, and copy its hashes into the
other `SOURCE_WHEEL_PROOF_*_SHA256` inputs; never derive those inputs inside
the proof launch. Pin `sbatch --nodelist` to that same host. The bootstrap
requires the receipt's bytes to be the canonical schema for that host and
those exact hashes. The expected/observed host, receipt digest, and all
inspection hashes are bound together in `run_identity.json` and revalidated
before and after leases. Submit with the exact `--wrap` form below.
The tracked wrapper
self-hashes in the allocation, validates the required inputs and TLS files, and
then uses a second `/usr/bin/env -i` to remove loader variables injected by
Slurm before invoking the canonical launcher. Submit-side `env -i` alone is not
a sufficient clean-environment boundary. Passing either tracked file directly
to `sbatch` is forbidden because Slurm executes a spool copy, which fails the
canonical-origin check.

```bash
umask 077
/usr/bin/env -i PATH=/usr/bin:/bin /path/to/pinned/python -I -S -B \
  /path/to/clean-reviewed-checkout/user/tianhaowu/terminal_bench_vmvm/inspect_source_wheel_proof_environment.py \
  --project-dir /path/to/clean-reviewed-checkout \
  --clean-wrapper /path/to/clean-reviewed-checkout/user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof_clean_env.sbatch \
  --launcher /path/to/clean-reviewed-checkout/user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof.sbatch \
  --uv /path/to/pinned/uv \
  --python /path/to/pinned/python \
  --python-stdlib /path/to/pinned/python-stdlib \
  --site-packages /path/to/pinned/site-packages \
  --vacli /path/to/pinned/vacli \
  --vmvm-source /path/to/clean-reviewed-checkout/environments/vmvm_tb_v2/vmvm_tb_v2/_vacli \
  > /path/to/private/reviewed-environment-inspection.json
/usr/bin/sha256sum /path/to/private/reviewed-environment-inspection.json
```

```bash
tmux new-session -d -s source-wheel-proof
tmux send-keys -t source-wheel-proof \
  "/usr/bin/env -i PATH=/usr/bin:/bin HOME=/storage/home/tianhaowu USER=tianhaowu LOGNAME=tianhaowu PROJECT_DIR=/path/to/clean-reviewed-checkout SOURCE_WHEEL_PROOF_INSPECTION_RECEIPT=/path/to/private/reviewed-environment-inspection.json SOURCE_WHEEL_PROOF_INSPECTION_RECEIPT_SHA256=<reviewed-receipt-sha256> SOURCE_WHEEL_PROOF_INPUT=/path/to/private/probe-input.json SOURCE_WHEEL_PROOF_INPUT_SHA256=<independently-reviewed-input-sha256> SOURCE_WHEEL_PROOF_EXPECTED_ENTRY_COUNT=6 SOURCE_WHEEL_PROOF_MISSING_EVIDENCE_SHA256=<reviewed-canonical-list-sha256> SOURCE_WHEEL_PROOF_OUTPUT_DIR=/path/to/new-private-proof-directory SOURCE_WHEEL_PROOF_BASE_RUNTIME_REVISION=ceb9356c98c72e51568e7bb4658a540cb1492254 SOURCE_WHEEL_PROOF_SOURCE_REVISION=<reviewed-full-utility-commit> SOURCE_WHEEL_PROOF_EXPECTED_HOST=<reviewed-inspector-host> SOURCE_WHEEL_PROOF_CLEAN_WRAPPER_SHA256=<reviewed-clean-wrapper-sha256> SOURCE_WHEEL_PROOF_LAUNCHER_SHA256=<reviewed-launcher-sha256> SOURCE_WHEEL_PROOF_UV_SHA256=<reviewed-uv-sha256> SOURCE_WHEEL_PROOF_PYTHON_SHA256=<reviewed-python-sha256> SOURCE_WHEEL_PROOF_PYTHON_RUNTIME_MANIFEST_SHA256=<reviewed-runtime-manifest-sha256> SOURCE_WHEEL_PROOF_SITE_PACKAGES_MANIFEST_SHA256=<reviewed-site-manifest-sha256> SOURCE_WHEEL_PROOF_VMVM_TB_V2_SHA256=<reviewed-vmvm-source-sha256> SOURCE_WHEEL_PROOF_VACLI_BINARY_SHA256=<reviewed-vacli-sha256> SOURCE_WHEEL_PROOF_MAX_CONCURRENT_ENTRIES=2 PYTHON_BIN_X86_64=/path/to/pinned/python PYTHON_STDLIB_X86_64=/path/to/pinned/python-stdlib PYTHON_SITE_X86_64=/path/to/pinned/site-packages UV_BIN_X86_64=/path/to/pinned/uv VACLI_BIN=/path/to/pinned/vacli VACLI_LEASE_RETRIES=1 VACLI_MAX_CONCURRENT_LEASES=6 VACLI_MAX_PULL_RETRIES=20 VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600 VACLI_CONTAINER_PRIVILEGED=1 VMVM_TENANT_ID=async_2347641 VMVM_LEASE_TTL=60s THRIFT_TLS_CL_CERT_PATH=/path/to/trusted/client.crt THRIFT_TLS_CL_KEY_PATH=/path/to/trusted/client.key /usr/bin/sbatch --parsable --export=ALL --job-name=tb-wheel-proof --partition=cpu_x86 --nodelist=<reviewed-inspector-host> --qos=cpu_x86_lowest --account=ram --time=12:00:00 --nodes=1 --ntasks=1 --cpus-per-task=6 --mem=12G --no-requeue --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/source_wheel_proof_%j.log --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/source_wheel_proof_%j.log --wrap='exec /bin/bash --noprofile --norc /path/to/clean-reviewed-checkout/user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof_clean_env.sbatch'" C-m
```

For an interrupted proof, review and hash `proof_state.json` externally, then
repeat the same launch with
`SOURCE_WHEEL_PROOF_STATE_SHA256=<reviewed-state-sha256>`. Do not infer this
value from an unreviewed output directory. The resume path revalidates every
completed entry and skips it only when the immutable attempt journal ends at an
entry boundary. Any unmatched or failed start requires a fresh output
directory. A complete six-entry proof therefore contains six clean-target
validations, twelve source builds, and exactly 18 proof runtime starts.

A fresh oracle creates a mode-0400 `source_wheel_attestations.json` and
content-addressed `source_wheel_cache/` beside its results only after acquiring
the writer lock. Publications are atomic and include the policy, runtime,
network/build contract, source, wheel, closure, and archive digests. Every
source-recovered result row names the attestation entry it consumed. Any resume,
including `RERUN_INVALID=1`, must additionally pass the previously reviewed
manifest digest as `ORACLE_SOURCE_WHEEL_ATTESTATION_SHA256`; a missing, changed,
or orphaned artifact fails closed.

For a promotable repair canary, supply the policy digest and exact nonzero
attestation count independently to the audit controller as
`ORACLE_AUDIT_SOURCE_WHEEL_POLICY_SHA256` and
`ORACLE_AUDIT_SOURCE_WHEEL_ATTESTATIONS`. Pass the same pair to
`export_oracle_tasks.py` as `--expected-source-wheel-policy-sha256` and
`--expected-source-wheel-attestations`. The audit requires exact policy and
manifest hashes, a one-to-one manifest/archive count, and equality between the
attested entries and the union referenced by result rows. Promotion rehashes
all wheelhouses and carries the recovery digests into the immutable receipt and
final launch certificate. Never promote from values inferred only from the run
itself.

The old Mobius images do not contain every test-only package named by their
verifier scripts. The adapter extracts only literal exact
`name[extras]==version` pins from direct `pip install` commands in
`tests/test.sh` and prefetches the full merged requirement set before the
untrusted phase. The sole compatibility exception normalizes bare `pytest` to
the adapter's existing `pytest==8.3.4` pin. Other dynamic, URL, local-path,
unpinned, environment-marked, conflicting, and option-dependent specifications
fail closed rather than being replayed with different semantics. Offline
restoration re-probes the full dependency closure, runs as harness root without
`--ignore-installed`, and is revalidated from the task shell.

After materializing corpus revision `ac1f30b9a`, revalidate the 42 repaired
fixtures before consuming the prior 2,500-task manifest:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/validate/mobius_repaired_tasks.txt TASK_FILE_SHA256=8d7d9377a9bbe6ade2fba7cc0730647d8be82402e225f95ad864a2218647563c OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_repairs_identity_<commit>_v1 DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 DATASET_REVISION=ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366 IMAGE_MANIFEST=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json IMAGE_MANIFEST_SHA256=118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009 ORACLE_SOLUTION_NETWORK_MODE=public MAX_CONCURRENT=8 VACLI_LEASE_RETRIES=20 VACLI_MAX_CONCURRENT_LEASES=4 VACLI_MAX_PULL_RETRIES=20 VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600 VACLI_CONTAINER_PRIVILEGED=1 TIMEOUT_MULTIPLIER=2 RESOURCE_MULTIPLIER=2 MINIMUM_PASS_RATE=0.9 MINIMUM_VALID=41 sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch" C-m
```

Require all 42 canary rows to be terminal, at least 41 valid, and zero
infrastructure, timeout, generic-error, or cleanup failures before submitting
the full run.

### Repair-canary audit controller

Never invoke `audit_oracle_repair_canary.py` directly for a promotable repair.
Use `run_oracle_repair_canary_audit.sbatch` from the established
`swebench_vmvm:Launcher.0` pane. The controller requires two distinct,
detached, clean checkouts: the exact reviewed source checkout that produced the
completed full oracle, and the exact frozen execution checkout that produced
the repair canary. Both verifier submodules must be initialized and detached at
their recorded gitlinks.

The caller derives each checkout's Prime-RL commit, verifier gitlink, and
deterministic VMVM source digest directly from Git and checked-out bytes. It
passes all six values explicitly to the auditor, binds the controller and
auditor scripts to the execution commit, and repeats every checkout and input
check after the audit. The auditor writes only to a private staging directory;
the caller publishes the mode-0600 certificate without overwrite only after
that second check succeeds. Neither expected provenance tuple is derived from
`run_identity.json`.

Do not submit the launcher file directly with `sbatch`: Slurm would execute a
spool copy, and the exact-origin check intentionally rejects that copy. Submit
explicit resources and a wrap command that executes the canonical launcher in
place. After replacing every placeholder with a new canonical path and the two
independently reviewed full commit IDs, type this only through the launcher
pane:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd <detached-execution-checkout> && umask 077 && env ORACLE_AUDIT_SOURCE_PROJECT_DIR=<detached-source-checkout> ORACLE_AUDIT_SOURCE_REVISION=<source-commit> ORACLE_AUDIT_EXECUTION_PROJECT_DIR=<detached-execution-checkout> ORACLE_AUDIT_EXECUTION_REVISION=<execution-commit> ORACLE_AUDIT_SOURCE_DIR=<completed-source-oracle> ORACLE_AUDIT_BUILDER_RECEIPT=<private-builder-receipt> ORACLE_AUDIT_TASK_FILE=<private-task-file> ORACLE_AUDIT_CANARY_DIR=<completed-canary> ORACLE_AUDIT_RUNTIME_ROOT=<private-runtime-root> ORACLE_AUDIT_RUNTIME_DIR=<fresh-private-runtime-dir> ORACLE_AUDIT_CERTIFICATE_ROOT=<private-certificate-root> ORACLE_AUDIT_CERTIFICATE=<fresh-certificate-path> sbatch --parsable --export=ALL --dependency=afterany:<canary-job-id> --job-name=oracle-repair-audit --partition=cpu_x86 --qos=cpu_x86_lowest --account=ram --time=00:30:00 --nodes=1 --ntasks=1 --cpus-per-task=2 --mem=4G --no-requeue --output=<private-log-root>/oracle_repair_audit_%j.log --error=<private-log-root>/oracle_repair_audit_%j.log --wrap='exec /bin/bash <detached-execution-checkout>/user/tianhaowu/terminal_bench_vmvm/run_oracle_repair_canary_audit.sbatch'" C-m
```

The task file and builder receipt must already be regular mode-0600 files.
Runtime logs, the controller attestation, staged certificate, summary, and
published certificate are also mode 0600. A pre-existing runtime or certificate
path, an active oracle writer, a moved or dirty checkout, a missing verifier
gitlink, any VMVM digest drift, or any source/canary provenance mismatch fails
closed without publishing the requested certificate.

Validate TB4 with its official digest-pinned images and Compose sidecars by
setting `USE_DECLARED_IMAGES=1` and `ENABLE_COMPOSE=1`:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "sbatch --parsable --export=ALL,DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks,USE_DECLARED_IMAGES=1,ENABLE_COMPOSE=1,MAX_CONCURRENT=8 user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch" C-m
```

For the exact standard TB4 path, the launcher binds the official release
archive SHA-256 and verifies that every extracted task path, type, mode, size,
file byte, and symlink target matches its `tasks/` payload before loading any
task. Other non-Git datasets must supply an explicit
`DATASET_ARCHIVE{,_SHA256}` pair.

The model-facing TB4 inputs remain byte-for-byte official. Oracle-only setup
applies one compatibility constraint for `cad-model`: `build123d==0.10.0`
allows newer `ocp_gordon` releases that require an incompatible OCP ABI, so the
reference run pins the last compatible `ocp_gordon==0.1.18`. This constraint is
not injected into agent rollouts or verifier containers.

## TB4 pass@1

After `fetch_tb4.sh` verifies the prebuilt release, wait for every intended
route to be healthy, zero routes to be unhealthy, and a clean per-route
semantic plus state-reuse soak. The vulnerable, unallocated
`tianhaowu-k3-tb24-nocache-20260916` deployment was archived on 2026-09-16.
Its replacement, `tianhaowu-k3-kda-tb1-low-20260916`, uses the digest-pinned
ARM64 fix from RAM PR `#285` together with `PIECEWISE` graphs. It starts at one
route on the cluster-default `g3_lowest` QoS so TB4 can qualify the patched
runtime and VMVM capacity before any scale-up; never treat `/health` alone as
readiness.
Sticky headers make backend affinity observable. The patched deployment keeps
prefix caching enabled and begins with rollout concurrency four on its one
route. VMVM lease creation remains capped at two until a clean post-fix smoke
and full TB4 run qualify a higher rate.

Run every command from one clean detached source snapshot. The combined Kimi
interceptor/verifier revision must be the exact `deps/verifiers` gitlink of
that reviewed superproject commit. `run_kimi_tb4_gate.sbatch` has no embedded
source hash: its caller must set `EVAL_EXPECTED_PRIME_RL_REVISION` to the full
40-hex commit of `PROJECT_DIR`, and both the wrapper and `run_eval.sbatch`
fail closed if the clean checkout differs. First submit the approved two-task
transcript smoke. `INFERENCE_READINESS_CHECKPOINT_SHA256` is the external file
SHA-256 of the completed readiness JSON, not its embedded deployment-spec
digest.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD EVAL_EXPECTED_PRIME_RL_REVISION=<commit> EVAL_RUN_ROLE=smoke EVAL_DEPLOYMENT_ID=tianhaowu-k3-kda-tb1-low-20260916 EVAL_EXPECTED_MODEL=Kimi-K3 EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_token_smoke.tasks.txt EVAL_APPROVED_TASK_FILE_SHA256=ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83 EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_approved_smoke.toml EVAL_DATASET_ARCHIVE=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/terminal-bench-prebuilt-v4.0.0.tar.gz EVAL_DATASET_ARCHIVE_SHA256=6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e EVAL_DATASET_CONTENT_SHA256=564a42a4e2ce0a5efd23758656e4e419b3566a36234dfc09bae1029bc15326b2 INFERENCE_DEPLOYMENT_SPEC=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/spec.yaml INFERENCE_DEPLOYMENT_SPEC_SHA256=<readiness-bound-spec-sha256> INFERENCE_READINESS_CHECKPOINT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/gates/k3_kda_tb1_low_readiness_v1.json INFERENCE_READINESS_CHECKPOINT_SHA256=<passed-readiness-file-sha256> INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json INFERENCE_PROXY_INFO_SHA256=<readiness-bound-proxy-info-sha256> OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_smoke_v1 VACLI_MAX_CONCURRENT_LEASES=2 sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m

tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD RESULTS_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_smoke_v1 SMOKE_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_token_smoke.tasks.txt SMOKE_TASK_FILE_SHA256=ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83 SMOKE_EXPECTED_TRACES=2 sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/run_trace_smoke_audit.sbatch" C-m
```

After that audit publishes `smoke_checkpoint.json`, hash the file and launch
the full 66-task pass@1 run with the same passed readiness artifact:

If the standard checkpoint already exists, a post-run exact-provider audit can
publish a separate immutable certificate without replacing it by setting
`SMOKE_REQUIRE_EXACT_PROVIDER_JSON=1` and a safe basename such as
`SMOKE_CHECKPOINT_NAME=smoke_checkpoint_exact_provider.json`. Alternate names
are rejected unless the exact-provider gate is enabled, and an existing
alternate target is never reused or overwritten.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD EVAL_EXPECTED_PRIME_RL_REVISION=<commit> EVAL_RUN_ROLE=tb4 EVAL_DEPLOYMENT_ID=tianhaowu-k3-kda-tb1-low-20260916 EVAL_EXPECTED_MODEL=Kimi-K3 EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt EVAL_APPROVED_TASK_FILE_SHA256=9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892 EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_max_miniswe.toml EVAL_DATASET_ARCHIVE=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/terminal-bench-prebuilt-v4.0.0.tar.gz EVAL_DATASET_ARCHIVE_SHA256=6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e EVAL_DATASET_CONTENT_SHA256=564a42a4e2ce0a5efd23758656e4e419b3566a36234dfc09bae1029bc15326b2 INFERENCE_DEPLOYMENT_SPEC=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/spec.yaml INFERENCE_DEPLOYMENT_SPEC_SHA256=<readiness-bound-spec-sha256> INFERENCE_READINESS_CHECKPOINT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/gates/k3_kda_tb1_low_readiness_v1.json INFERENCE_READINESS_CHECKPOINT_SHA256=<passed-readiness-file-sha256> INFERENCE_SMOKE_CHECKPOINT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_smoke_v1/smoke_checkpoint.json INFERENCE_SMOKE_CHECKPOINT_SHA256=<smoke-checkpoint-file-sha256> INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json INFERENCE_PROXY_INFO_SHA256=<readiness-bound-proxy-info-sha256> OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v3 VACLI_MAX_CONCURRENT_LEASES=2 sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m

tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD RESULTS_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v3 sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/run_tb4_audit.sbatch" C-m
```

If only the backend worker generation rotates before launch, a completed
schema-1 smoke may be qualified for the new generation without changing or
relabeling that smoke. While the source generation is still live, preserve its
exact generated `proxy_litellm_config.yaml` as a private mode-0600 snapshot;
its SHA-256 must equal the policy digest embedded in the eventual smoke
certificate. The snapshot contains credentials and must never be printed,
committed, or placed in training artifacts. First pass a fresh readiness gate
for the replacement workers, then publish a separate schema-2 bridge:

```bash
python user/tianhaowu/terminal_bench_vmvm/create_smoke_generation_bridge.py \
  --output /path/to/write-once/smoke_generation_bridge.json \
  --source-smoke-checkpoint /path/to/source-smoke/smoke_checkpoint.json \
  --source-smoke-checkpoint-sha256 <source-smoke-file-sha256> \
  --source-proxy-config-snapshot /path/to/private/source-proxy-config.yaml \
  --deployment-id <deployment-id> \
  --deployment-spec /path/to/deployment/spec.yaml \
  --deployment-spec-sha256 <exact-spec-sha256> \
  --target-readiness-checkpoint /path/to/fresh-readiness.json \
  --target-readiness-checkpoint-sha256 <fresh-readiness-file-sha256> \
  --proxy-info /path/to/deployment/proxy_info.json \
  --proxy-info-sha256 <unchanged-proxy-info-sha256>
```

Use the resulting file and its external SHA-256 as
`INFERENCE_SMOKE_CHECKPOINT` and `INFERENCE_SMOKE_CHECKPOINT_SHA256`. The
bridge is accepted only when the deployment ID, spec path/hash, model,
coordinator incarnation, proxy incarnation, proxy-info path/hash, endpoint
authority, and parsed proxy policy remain exact. It also snapshots the target
generated config privately and proves the source and target configs are
canonical-equal after replacing only the route `api_base` values; every other
setting and secret must be byte-semantically equal, and both route URL sets
must hash to their readiness generations. The source and target route sets
must differ, so this mechanism cannot certify a proxy, coordinator, policy,
model, or deployment rotation. It recursively revalidates the source
schema-1 smoke, its identity, configuration, results hashes, guard receipt,
single non-resume invocation, and evaluator/model-I/O/tool/thinking contract.

The fresh bridge probe reuses readiness's sticky representative session for
every target backend. On each backend it sends `reasoning_effort=max`, both
thinking flags, and an actual function-tool call followed by its tool result;
both responses must report the exact model and nonempty reasoning. The bridge
stores only request/response SHA-256 values and aggregate pass facts, never
messages, reasoning, tool arguments, endpoint URLs, or credentials. The file
is mode 0444, self-hashed, and write-once; both credential-bearing config
snapshots remain separate mode-0600 files referenced only by path and SHA-256.
A changed source artifact, duplicate key, type mismatch, missing backend,
non-route proxy-config change, or proxy-info rotation fails closed.
Every shard still performs its own fresh route guard against the target
generation. Cross-generation resume remains forbidden: restart an interrupted
shard in a new output directory with a newly validated bridge and guard.

Every real launch through `run_eval.sbatch` requires
`EVAL_RUN_ROLE`, `EVAL_DEPLOYMENT_ID`, `EVAL_EXPECTED_MODEL`, an exact
deployment spec and passed readiness artifact, one dataset authority, and an
external approved task file with its lowercase SHA-256. TB4 and Mobius also
require the externally hashed smoke checkpoint; Mobius additionally requires
the externally hashed launch certificate. Every Kimi role also requires
`EVAL_EXPECTED_PRIME_RL_REVISION` and rejects an omitted, malformed, or
nonmatching source commit. Every role must supply the exact
deployment-local `INFERENCE_PROXY_INFO` path and
`INFERENCE_PROXY_INFO_SHA256` established by readiness. The launcher snapshots all mutable
inputs and publishes a self-hashed `eval_run_identity.json` before any model
call. It binds source/runtime pins, dataset authority, deployment gates,
pass@1/max-reasoning/256K/capture settings, task count and digest, and effective
execution concurrency. Readiness also binds each positive Slurm endpoint job
ID, worker start time, and SHA-256 digest of its backend API base, plus the
coordinator job/start-time incarnation and proxy job/first-ready stamp. Status
must use schema v4, the proxy job must match `proxy_info.json`, and coordinator
ticks must strictly advance between same-incarnation readiness observations
and across the semantic probe. The semantic probe must observe exactly those
backend digests, and the waiter rechecks the same serving generation after the probe.
`run_eval.sbatch` checks that generation before model traffic, every 10 seconds
while the evaluator is alive, requires tick progress within 30 seconds, and
checks once after it exits; a route change, preemption, stalled coordinator,
surviving child process, or guard termination signal kills and waits for the
entire evaluator process group. Before spawning, the guard removes any stale
`route_guard_success.json`. Only a zero exit followed by the final route check
and stable hashes of `eval_run_identity.json`, `eval_invocations.jsonl`, and
`results.jsonl` publishes a fresh atomic mode-0600 receipt. Smoke and TB4
certification require and rehash that exact receipt chain. Guarded Kimi smoke,
TB4, and Mobius runs reject every nonempty `RESUME_DIR`; an interrupted run
requires a fresh output directory and a new single-invocation receipt.
Exact `--dry-run` is the sole approval-free mode and exits before task loading.
The checked-in full-TB4 manifest is shared by the Kimi and Qwen configs despite
its historical filename.

The compute job reads `url` and `api_key` from the hash-pinned proxy file without
putting the key in the config, submission command, or provenance file. It binds
the resolved proxy path, full-file hash, and a secret-free authority digest to
readiness and every downstream certificate. A proxy rotation therefore requires
a fresh readiness gate; do not substitute a new hash in a smoke, TB4, or Mobius
command. Direct/base-URL, inference-job, and shared-gateway deployment overrides
are rejected for this workflow. `INFERENCE_PROXY_URL` remains available only as
a transport proxy when the bound HTTPS ingress requires it.

The deployment spec must set integer `spec.proxy.config.request_timeout: 43200`
and integer `num_retries: 0`. Readiness independently parses the generated
`proxy_litellm_config.yaml`, requires the same values, and records only those
values plus the full-file SHA-256 and path—never its URL or key. Both YAML
documents are parsed semantically with duplicate keys, aliases, merge keys,
quoted numeric values, tags, and non-integer values rejected. The evaluator
guard revalidates that file throughout the run. Kimi configs use exactly
43,200 seconds for the evaluator client, mini-swe-agent model client, and
proxy, with an exact 120-second connect timeout. Setup/finalize/scoring are
exactly 3,600/3,600/21,600 seconds. The approved TB4 smoke uses the exact
rollout/session pair 28,800/32,400 seconds; full TB4, the capacity smoke, and
Mobius production use exactly 36,000/43,200 seconds. No intermediate or mixed
pair is launchable.

A narrowly scoped timeout recovery is available only after a guarded two-task
smoke has stopped writing and published its success receipt. Run
`smoke_timeout_recovery.py select` against the externally hash-pinned original
two-task manifest, the hash-pinned `tb4_kimi_k3_recovery12h.toml` template, and
the exact clean `PROJECT_DIR` recorded by the source run. The selector
materializes `config.toml` with the derived one-task file path and digest before
snapshotting, so `snapshot_eval_inputs.py` and `validate_task_approval.py`
validate the same one-task approval. It accepts exactly one strictly audited
clean trace plus either one absent row or one literal `harness_timeout` row. It
rejects every other error, infrastructure stop, duplicate, extra row, ambiguous
task, or normalized provider response. The selector atomically creates a
mode-0700 namespace containing a mode-0400 one-line approval and a mode-0444
self-hashed attestation; its stdout and errors contain aggregate counts and
digests only.
The attestation requires the recovery source to have the exact same Prime-RL,
Verifiers, Renderers, and VMVM revisions as the original run. It also binds a
per-file SHA-256 map and aggregate digest for the workflow Python/shell/Slurm
code and VMVM Python package. If the original source predates this recovery
policy, the one-task path is intentionally ineligible and the fresh-two path is
required.

Launch the reviewed `run_kimi_smoke_recovery.sbatch` from the authorized Slurm
launcher with `KIMI_SMOKE_RECOVERY_MODE=one`, the selection path, and a fresh
`OUTPUT_DIR` equal to the attested `<selection-namespace>/run`. The wrapper
uses the attested `<selection-namespace>/config.toml`, never the unmodified
template. `RESUME_DIR`
must be absent, not merely empty. This lane uses
`tb4_kimi_k3_recovery12h.toml`: one task, one rollout/HTTP/VMVM slot, 262,144
tokens, 43,200-second evaluator/model/rollout/session limits, and a 48-hour
Slurm envelope. After the one-task schema-1 certificate passes, the wrapper
creates a separate fresh composite namespace. Its schema-3 certificate retains
both source identities and route-guard receipts, requires identical
deployment/spec/readiness/endpoint/route-generation/proxy bindings and
compatible evaluator/dataset contracts, re-audits both traces with clean-stop
and exact-provider requirements, proves a disjoint 1+1 union, and orders rows
exactly as the original manifest. It never fabricates a route receipt for the
composite.

If selection is not uniquely eligible, use the same wrapper with
`KIMI_SMOKE_RECOVERY_MODE=fresh-two` and a new output directory. The fallback
`tb4_kimi_k3_fresh_smoke12h.toml` reruns both pinned tasks with two aligned
rollout/HTTP/VMVM slots and the same 12-hour limits. Neither path reuses or
modifies the incomplete run.

Selection is a read-only operation on the completed source run. Supply a new
namespace outside both run directories:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/smoke_timeout_recovery.py select \
  --source-run-dir /path/to/completed-two-task-run \
  --original-task-file /path/to/pinned-two-task-manifest \
  --original-task-file-sha256 <two-task-manifest-sha256> \
  --recovery-config-template user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_recovery12h.toml \
  --recovery-config-template-sha256 <template-sha256> \
  --recovery-project-root "$PWD" \
  --namespace /path/to/new-selection-namespace
```

The subsequent Slurm submission must execute
`run_kimi_smoke_recovery.sbatch` from that same clean project root and bind the
same `EVAL_EXPECTED_PRIME_RL_REVISION`; the wrapper rejects a copied launcher,
changed policy closure, mismatched VMVM settings, changed route artifacts, an
existing run/composite path, or any `RESUME_DIR` entry.

The policy file is scoped to its readiness generation: a deliberate resize may
rewrite both live policy files, so the sharded TB4 finalizer privately snapshots
two canonical allowlisted records: one binds the historical spec hash and typed
policy, and one binds the original generated-file hash and typed policy. Raw
spec or generated-config bytes are never retained. Post-resize readiness binds
the new live files.
This timeout is selected from the exact requested model: unrelated/Qwen
readiness remains pinned to its existing 7,200-second policy and cannot be
cross-certified against a Kimi artifact.

The default config is `configs/eval/tb4_kimi_k3_max_miniswe.toml`: 66 tasks,
pass@1, mini-swe-agent, `reasoning_effort=max`, one VMVM per rollout, and a
256 Ki-token total context cap. It uses rollout concurrency four and an HTTP
connection/keepalive pool of four. Keep vacli lease bring-up bounded at two
for this qualification run. All 11 TB4 tasks that declare Docker Compose
sidecars use the compose-capable VMVM path;
they are not skipped or downgraded to a single-container approximation. The
current VMVM tenant is CPU-only, so the three TB4 GPU tasks are rejected
explicitly instead of being run under a silently incorrect CPU sandbox; the
exact VMVM subset is therefore 63 tasks.

The Kimi configs explicitly give mini-swe-agent 10 total attempts for each
provider call. If all of those attempts fail, approved smoke, full TB4, and
Mobius retry the whole rollout exactly twice and only for `ProviderError`,
`SandboxError`, `TunnelError`, or the base `InterceptionError`; broad
`HarnessError` retries are forbidden. The transparent `EvalClient` itself does
not own a retry loop, and LiteLLM must keep `num_retries=0`; these harness-level
attempts do not authorize hidden proxy retries. The legacy 65K token-only
diagnostic config keeps its narrower retry set and is intentionally rejected by
the production run-identity contract; use the approved smoke config for gates.

The evaluator and oracle are network-bound CPU controllers; their checked-in
Slurm defaults request `cpu_x86`, 8 CPUs, 16 GiB, and no GPUs. Rollout
concurrency does not require one controller CPU per sandbox.

### Two-worker direct fallback

When the 24-route RAM deployment is unavailable, the checked-in direct-worker
fallback keeps every trajectory on one engine by construction. It is one
pass@1 evaluation split into two disjoint 33-task manifests, not two attempts
of the same tasks:

- `tb4_kimi_k3_direct_a.toml` uses `http://g3-138-137:32317/v1`, four rollout
  slots, and task-manifest SHA-256
  `d0f7c0297a82edf79f3e966ffd830fb418ea90c9faa7c4f3d288d5c7bacd1365`;
- `tb4_kimi_k3_direct_b.toml` uses `http://g3-146-243:32499/v1`, four rollout
  slots, and task-manifest SHA-256
  `485c1a038efc72a4eddf4928758c74d31827ebb7624108cee63e503df0fa02ec`.

The manifests contain 33 unique tasks each, have no overlap, cover all 66 TB4
tasks, and distribute the three CPU-unsupported GPU tasks as one plus two. The
supported tasks were greedily balanced using the completed TB4 oracle runtime.
Direct worker access requires all proxy environment variables to be unset;
`run_eval.sbatch` already does this. Do not set `INFERENCE_PROXY_URL` or put
these URLs behind round-robin routing. `OPENAI_API_KEY=EMPTY` is accepted.

The first full attempt used 16 rollouts per worker (32 aggregate). Jobs
`1733765` and `1733766` produced 19 tunnel-exposure failures and five Compose
failures; 11 of the first 13 rows were errors. They were canceled, as was
dependent merge `1733767`. Treat all three `_v1` directories as diagnostic and
do not resume or merge them. The measured fallback limit is now four rollouts
per worker (eight aggregate) and two concurrent lease bring-ups per controller
(four aggregate).

The pinned ports are not currently live, so there is no authorized direct
fallback launch command. If they are restored, each worker must first receive
its own externally hashed deployment-spec, readiness, and transcript-smoke
artifacts and then use the same `EVAL_RUN_ROLE=tb4` identity ceremony as the
primary route. Canceled `_v1`/`_v2` artifacts are not resume inputs.

Each shard remains its own single-invocation evaluator output. Never resume a
partial shard; restart it in a fresh output directory after revalidating its
worker. After both finish, publish a separate, audit-only combined artifact:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/combine_tb4_shards.py \
  --shard-a-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_direct_a_v3 \
  --shard-b-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_direct_b_v3 \
  --output-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_direct_combined_v3 \
  --dataset-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks
```

The combiner takes both evaluator writer locks, validates the committed and
snapshotted task/config hashes, exact worker URLs, matching code revisions,
33-row shard membership, and cross-shard trace IDs. It then runs the strict
66-task TB4 reasoning/model-I/O/KDA/score audit in a temporary directory and
atomically publishes `results.jsonl`, `checkpoint.json`, and
`merge_manifest.json` only when every check passes. The combined directory is
not resumable because task indices are local to each shard; rerun any failed
source shard in a fresh directory instead.

### Qwen 16-worker direct fallback

The shared Qwen proxy has a shorter upstream request deadline than the Qwen
evaluation client. `run_qwen_direct_eval.sbatch` bypasses it by starting a
loopback-only `vllm-router` from the 16 pinned worker metadata files under
`shared_qwen38_2p4t/endpoints`. The launcher requires the exact deployment spec
and endpoint-bundle hashes, probes `/health` and `/v1/models` on every worker,
and refuses to start until the local router reports all 16 workers active. It
does not read `proxy_info.json` or accept a real API key.

The router dependency is an isolated optional group and must not be added to
the live evaluator dependency directory. Once no active evaluation depends on
that directory, stage it at its separate versioned path:

```bash
bash user/tianhaowu/terminal_bench_vmvm/stage_qwen_direct_router.sh
```

The router uses consistent hashing on the rollout's `X-Session-ID`, disables
router retries, and sets its request deadline above the evaluator's
7,200-second deadline. Smoke and TB4 admit at most eight requests with no
overflow queue. Mobius runs 64 evaluator rollouts with a 32-request provider
admission cap and a 32-request router queue. The direct launcher requires
multiplexing to equal rollout concurrency and binds both HTTP pools to the
provider admission cap. `run_qwen_direct_eval.sbatch` forces
`VACLI_MAX_CONCURRENT_LEASES=2`; the lower-level driver defaults to eight only
when invoked directly. Do not run either alongside another VMVM evaluation if
that would exceed the intended aggregate VMVM lease-start concurrency.

The full 66-task TB4 set and 2,500-task oracle-valid Mobius production set,
including all task categories, are approved for the direct Qwen route. The
checked-in launch inputs are:

- `tb4_qwen_token_smoke.toml`: two tasks from
  `tb4_qwen_token_smoke.tasks.txt`, SHA-256
  `4ae515a77f33746ecb598ab6c670612265bd1ef726eb6ca7f16cc81f5e191c25`;
- `tb4_qwen_a95b_miniswe.toml`: all 66 TB4 tasks from
  `tb4_qwen_a95b_miniswe.tasks.txt`, SHA-256
  `9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892`;
- `mobius_qwen_a95b_2500.toml`: the 2,500 oracle-valid Mobius tasks from
  `mobius_valid_tasks_2500.txt`, SHA-256
  `d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`.

The smoke uses two slots and TB4 uses eight. Mobius uses 64 rollout/multiplex
slots with 32 HTTP/provider slots and a 32-request router queue. Every config
retains captured model I/O and thinking content, permits 32,768 output tokens
per model call, and keeps the 262,144-token full-context cap plus the extended
VMVM timeouts.
The direct launcher still requires the selected manifest path and exact digest
to be supplied independently through `DIRECT_QWEN_APPROVED_TASK_FILE` and
`DIRECT_QWEN_APPROVED_TASK_FILE_SHA256`. `EVAL_CONFIG` must select that same
hash using `task_file` plus `task_file_sha256` while omitting inline `tasks`.
The launcher hashes both files without printing or otherwise exposing their
contents.

After an approved run is terminal, first invoke `direct_qwen_workers.py
--audit-run-dir RUN_DIR`; it validates the non-secret worker manifest, saved
loopback URL, config snapshot, and credential-free provenance without opening
the results file. Then invoke `audit_traces.py` with both
`--expected-task-file APPROVED_ALLOWLIST` and the approved expected count. Both
commands emit summaries only; do not print result rows. Resume only through
`run_qwen_direct_eval.sbatch`, which reuses the snapshotted endpoint set and
local port and fails if the live metadata no longer exactly matches.

## Transcript capture gate

Never request provider log probabilities in this workflow. RAM issue `#279`
records a Kimi Rust-frontend crash (`token_ranks must be >=1`) when a request
asks for logprobs. All checked-in eval configs therefore omit `logprobs`,
`prompt_logprobs`, `top_logprobs`, and `return_token_ids` entirely. The
chat-completions dialect still preserves assistant response content, tool calls,
`reasoning_content`, and provider usage. These are durable text transcripts for
offline retokenization/processing, not directly consumable token-level on-policy
samples; original sampling log probabilities cannot be reconstructed offline.

This request-side rule contains the worker-wide dispatcher outage but does not
by itself cure silent KDA state-reuse corruption. The active stock-image
fallback disables prefix caching so cache hits cannot create a one-token first
chunk and serializes each backend with `max-num-seqs=1`; it also disables the
Rust frontend and uses `PIECEWISE` CUDA graphs. This is an operational
workaround, not the source-level fix from vLLM PR `#51483`, so a green
`/health` still requires a clean state-reuse semantic soak over every route.

After verifying the frozen isolation and PIECEWISE settings, run the
standalone semantic snapshot and sticky-route gate before the two-task smoke.
It reads the proxy URL, key, served model, and sticky/Redis metadata directly
from `proxy_info.json`, never includes the key in its JSON output, and uses only
the Python standard library. Each discovery request gets a unique session value in both
`X-LiteLLM-Session-ID` and `X-Session-ID`; the probe then repeats one stable
session sequentially per backend and requires `x-litellm-model-api-base` to
remain fixed.

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/probe_inference_routes.py \
  --proxy-info /checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb24-nocache-20260916/proxy_info.json \
  --proxy-info-sha256 <full-proxy-info-file-sha256> \
  --deployment-id tianhaowu-k3-tb24-nocache-20260916 \
  --deployment-spec /checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb24-nocache-20260916/spec.yaml \
  --model Kimi-K3 \
  --expected-routes 24 \
  --requests 192 \
  --repeats 3 \
  --concurrency 24 \
  --health-timeout 30 \
  --timeout 300 \
  --max-tokens 4096 \
  --require-reasoning \
  --pretty
```

Set `--expected-routes` to the deployment's intended ready-route count, not
merely its current observed count. The command requires the model-specific
health response to report exactly that many healthy routes and zero unhealthy
routes before and after the requests. It also requires an exact observed route
count, shared-affinity metadata, no hidden LiteLLM retries, an exact marker with
a normal stop, and stable backend headers for the repeated sessions. It then
runs serial raw-completion predecessor/one-token-target cycles on every
discovered backend and fails if routing changes, the target prompt or response
is not exactly one token, corruption appears, or deterministic target output
depends on predecessor state. Neither request dialect sends `logprobs`,
`prompt_logprobs`, `top_logprobs`, or `return_token_ids`; the summary never
contains response text, credentials, or the raw URL; it reports only the
secret-free endpoint-authority digest. `--allow-unverified-affinity` and
`--skip-health` exist
for diagnosis only and must not be used for the production readiness gate.

The Kimi production config uses the committed, portable oracle-qualified
manifest at
`configs/eval/mobius_valid_tasks_2500.txt` (49,334 bytes, 2,500 lines,
SHA-256
`d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`).
Do not launch it directly after TB4. First publish the final oracle promotion
receipt, resize the same deployment to exactly 24 ready routes, pass a fresh
readiness/state-reuse gate, and certify a trace-capacity smoke whose configured
rollout, multiplex, and HTTP-pool concurrency are aligned at 24 while effective
lease-start concurrency remains four. The evaluator also publishes a mode-0400,
aggregate-only `concurrency_telemetry.json`. Certification requires the observed overlap of
completed trace lifecycles to reach configured rollout concurrency and the
observed peak of vacli lease-start semaphore holders to reach configured
lease-start concurrency; configured limits alone are not capacity evidence.
Submit the post-resize waiter with `EXPECTED_ROUTES=24`. The launch certificate
requires exactly one route for legacy schema-1 and sharded schema-2 TB4
checkpoints. A multi-generation schema-3 TB4 checkpoint may use exactly one or
two routes. These bounds are fixed by schema and have no CLI override. The
post-resize readiness/spec route count must be strictly larger than the TB4
route count and cover the production rollout concurrency. The certificate also
rejects a post-resize spec identical to the TB4 spec, a readiness/spec
route-count mismatch, or misaligned production and capacity-smoke steady-state
concurrency knobs.
The checked-in capacity-smoke config exercises the already validated 42-case
Mobius repair set at 24 active rollouts and four lease starts:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD EVAL_EXPECTED_PRIME_RL_REVISION=<commit> EVAL_RUN_ROLE=smoke EVAL_DEPLOYMENT_ID=tianhaowu-k3-kda-tb1-low-20260916 EVAL_EXPECTED_MODEL=Kimi-K3 EVAL_DATASET_REVISION=ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366 EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/validate/mobius_repaired_tasks.txt EVAL_APPROVED_TASK_FILE_SHA256=8d7d9377a9bbe6ade2fba7cc0730647d8be82402e225f95ad864a2218647563c EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_kimi_k3_capacity_smoke.toml INFERENCE_DEPLOYMENT_SPEC=/path/to/post-resize-spec.yaml INFERENCE_DEPLOYMENT_SPEC_SHA256=<post-resize-spec-sha256> INFERENCE_READINESS_CHECKPOINT=/path/to/post-resize-readiness.json INFERENCE_READINESS_CHECKPOINT_SHA256=<post-resize-readiness-file-sha256> INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json INFERENCE_PROXY_INFO_SHA256=<post-resize-readiness-bound-proxy-info-sha256> OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/mobius_kimi_k3_capacity_smoke_v1 VACLI_MAX_CONCURRENT_LEASES=4 sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m

tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD RESULTS_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/mobius_kimi_k3_capacity_smoke_v1 SMOKE_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/validate/mobius_repaired_tasks.txt SMOKE_TASK_FILE_SHA256=8d7d9377a9bbe6ade2fba7cc0730647d8be82402e225f95ad864a2218647563c SMOKE_EXPECTED_TRACES=42 SMOKE_REQUIRED_ROLLOUT_CONCURRENCY=24 SMOKE_REQUIRED_LEASE_START_CONCURRENCY=4 sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/run_trace_smoke_audit.sbatch" C-m
```

Then create one write-once launch certificate outside the Git worktree:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/mobius_launch_certificate.py create \
  --tb4-checkpoint /path/to/tb4-run/checkpoint.json \
  --tb4-checkpoint-sha256 <tb4-checkpoint-file-sha256> \
  --oracle-receipt /path/to/oracle-promotion-receipt.json \
  --oracle-receipt-sha256 <oracle-receipt-file-sha256> \
  --readiness-checkpoint /path/to/post-resize-readiness.json \
  --readiness-checkpoint-sha256 <post-resize-readiness-file-sha256> \
  --capacity-smoke-checkpoint /path/to/capacity-smoke/smoke_checkpoint.json \
  --capacity-smoke-checkpoint-sha256 <capacity-smoke-file-sha256> \
  --deployment-id tianhaowu-k3-kda-tb1-low-20260916 \
  --deployment-spec /path/to/post-resize-spec.yaml \
  --deployment-spec-sha256 <post-resize-spec-sha256> \
  --deployment-proxy-info /checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json \
  --deployment-proxy-info-sha256 <post-resize-readiness-bound-proxy-info-sha256> \
  --production-config user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_kimi_k3_max_2500.toml \
  --approved-manifest user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt \
  --approved-manifest-sha256 d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b \
  --requested-lease-start-concurrency 4 \
  --output /checkpoint/ram/tianhaowu/terminal_bench_vmvm/gates/mobius_launch_<commit>.json
```

The certificate reconstructs and rehashes every linked gate and run identity,
including the capacity smoke's write-once concurrency telemetry and its measured
peaks;
it accepts the oracle execution commit only as an ancestor of the clean
production commit while requiring exact Verifiers and VMVM source pins. Its
TB4 gate is fixed at 66 total/63 CPU-supported tasks, four active rollouts, two
lease starts, and a supported pass rate from 4% through 22%. The production
launcher revalidates the complete certificate against its live inputs before
creating an output directory or contacting inference.

Mobius launch does not accept `EVAL_MODEL`, `INFERENCE_BASE_URL`,
`INFERENCE_JOB_ID`, or shared-gateway deployment overrides. It requires the
deployment-local `proxy_info.json` in the same exact directory as the
certificate-bound `spec.yaml`, and requires `EVAL_EXPECTED_MODEL=Kimi-K3`.
The launch validator also requires the exact post-resize readiness and capacity
smoke paths and file hashes embedded in the certificate; a different but valid
checkpoint cannot be substituted.

Launch from the same clean detached source path used to create the certificate:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD EVAL_EXPECTED_PRIME_RL_REVISION=<commit> EVAL_RUN_ROLE=mobius EVAL_DEPLOYMENT_ID=tianhaowu-k3-kda-tb1-low-20260916 EVAL_EXPECTED_MODEL=Kimi-K3 EVAL_DATASET_REVISION=ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366 EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt EVAL_APPROVED_TASK_FILE_SHA256=d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_kimi_k3_max_2500.toml INFERENCE_DEPLOYMENT_SPEC=/path/to/post-resize-spec.yaml INFERENCE_DEPLOYMENT_SPEC_SHA256=<post-resize-spec-sha256> INFERENCE_READINESS_CHECKPOINT=/path/to/post-resize-readiness.json INFERENCE_READINESS_CHECKPOINT_SHA256=<post-resize-readiness-file-sha256> INFERENCE_SMOKE_CHECKPOINT=/path/to/capacity-smoke/smoke_checkpoint.json INFERENCE_SMOKE_CHECKPOINT_SHA256=<capacity-smoke-file-sha256> EVAL_PROMOTION_CERTIFICATE=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/gates/mobius_launch_<commit>.json EVAL_PROMOTION_CERTIFICATE_SHA256=<launch-certificate-file-sha256> INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json INFERENCE_PROXY_INFO_SHA256=<post-resize-readiness-bound-proxy-info-sha256> OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/mobius_kimi_k3_max_2500_transcript_v2 VACLI_MAX_CONCURRENT_LEASES=4 sbatch --parsable --time=7-00:00:00 \$PWD/user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

The checked-in production point is 24 active rollouts and four simultaneous
lease starts. Launch it only after the deployment has exactly 24 ready routes
and the capacity smoke has measured all 24 active rollouts plus four concurrent
lease starts. Keep `VACLI_MAX_CONCURRENT_LEASES=4` explicit for both runs. The
oracle-only 64/32 result does not qualify model
trace generation: it has no per-rollout model-interception tunnel or Compose
sidecars.

Interrupted guarded Kimi evals remain diagnostic evidence only. Do not reuse
their partial rows: `run_eval.sbatch` rejects nonempty `RESUME_DIR` before it
can mutate identity or invocation metadata. Revalidate readiness and restart
in a fresh output directory. The guard receipt requires exactly one invocation
record with `resume=false`, the matching role and identity digest, and a
canonical positive Slurm job ID.
The saved config is replayed verbatim and successful traces are retained. New
runs snapshot the source config, task list, and image manifest under
`OUTPUT_DIR/inputs/`, record SHA-256 digests in `inputs/manifest.json`, and point
the resolved run config at those immutable copies. Large configs set
`retain_traces=false`: every trace is appended durably and then released from
RAM, and the CLI does not duplicate the full JSONL into the Slurm log.

The Kimi Mobius config additionally requires the dataset worktree to be clean
at exact commit `ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366`, the task manifest to
have SHA-256 `d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`,
and the image manifest to have SHA-256
`118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009`.
Task loading fails before any model call if the checkout is moved or dirty, or
if either manifest differs.

Before consuming any run, execute:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/audit_traces.py \
  /path/to/results.jsonl \
  --expected-task-file /path/to/oracle_passed_tasks.txt \
  --expected-count 2500 \
  --aggregate-only \
  --require-reasoning \
  --require-exact-provider-json \
  --model-io-contract kimi-k3-max
```

Transcript audit is the default. It rejects missing/duplicate tasks, rollout
errors, missing sampled response content/tool calls, missing reasoning, invalid
or absent provider usage, malformed parent graphs, and any provider-reported
turn over 262,144 total tokens. When model-I/O capture is required, it also
normalizes every captured chat request and proves that its message list exactly
matches the persisted root-to-parent graph path, including historical reasoning,
tool calls, and tool results. `--require-token-data` remains an explicit
legacy/diagnostic mode for traces that intentionally contain exact token IDs,
masks, and sampling logprobs. Scale only after the default gate passes on a
fresh smoke run and after measuring stable VMVM lease concurrency.

The Kimi contract checks each hash-verified request for the chat-completions
route, exact `Kimi-K3` model, `reasoning_effort=max`, and exactly the two
required thinking flags. It also requires the parsed provider response model to
be `Kimi-K3`. This proves that max reasoning was requested; provider-side proof
that it was honored would require server attestation.

For every captured model turn, the audit reparses exact chat-completion JSON or
the normalized streamed response through Verifiers' own response models and
requires the resulting assistant message, reasoning details, tool calls,
provider state, finish reason, and normalized usage to equal the persisted
assistant node. Hash-valid but unrelated response payloads therefore fail the
gate. Audit output contains stable problem codes and aggregate counts only,
never response text.
`--require-exact-provider-json` additionally rejects normalized streamed
responses with the stable aggregate code
`normalized_stream_response_disallowed`; omit it only when normalized capture
is intentionally acceptable.

A tool-call turn without flattened reasoning is exempt only when provider usage
reports a valid zero reasoning-token count, or when exact provider JSON contains
an explicit empty reasoning marker and the reconstructed request enabled and
preserved thinking. Missing or null markers, counters in fields Verifiers does
not consume, normalized responses without a zero counter, and mismatched tool
calls fail closed.

Because this workflow intentionally omits token IDs, the previous response's
provider usage is used as the conservative best-known size when clamping the
next generation budget. Exact token arrays remain authoritative whenever they
are present. New tool output can still increase the next prompt beyond that
known prefix, so the provider usage returned for every response remains the
final fail-closed check: a turn above 262,144 tokens is rejected before graph
commit and cannot enter the retained training corpus.

## SFT export

`results.jsonl` is the immutable source transcript, not a directly loadable SFT
dataset. After the evaluation is terminal, export either reward-one traces or
all scored outcomes explicitly:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/export_sft.py \
  /path/to/eval/results.jsonl \
  --output-dir /path/to/new/sft-dataset \
  --selection pass-only \
  --expected-count 2500 \
  --require-exact-provider-json
```

The exporter accepts an image manifest only when the resolved taskset path and
digest, input-manifest record, and run-local snapshot are all present and agree.
Runs that do not declare one must omit both taskset fields, the manifest entry,
and the snapshot file.

For a migrated Qwen run, create its final routing-epoch index only after the
last evaluator job is terminal, then consume it explicitly:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/export_sft.py \
  /path/to/migrated-run/results.jsonl \
  --output-dir /path/to/new/sft-dataset \
  --selection pass-only \
  --expected-count 2500 \
  --routing-epoch-index /path/to/private-sidecars/qwen_router_epochs.jsonl
```

For a production routing-epoch-3 run, use the terminal finalizer instead of
issuing those two commands independently. It requires explicit, disjoint
source and output boundaries; an exact clean Prime-RL revision; the expected
source provenance digest; the terminal row count; selection; and split policy.
It refuses relative, symlinked, broad, overlapping, or default paths, held
writer/router locks, an existing output, nonterminal recorded jobs, and any
routing/provenance mismatch. It creates the routing index in a private staging
directory, passes that exact index to `export_sft.py`, retains it in the
published corpus, and never writes to the source run. The complete corpus is
published only after all repository, provenance, and artifact checks pass.
Child output is captured and reduced to aggregate counts, hashes, or stable
error codes.

Submit from a clean detached x86-capable source snapshot at the finalizer's
exact commit. The source/output root directories must already exist. Replace
the angle-bracketed values with audited literal values; do not use command
substitution in the submission command:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "sbatch --dependency=afterok:PRODUCER_JOB_ID --export=ALL,FINALIZER_PROJECT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-FINALIZER_SHA,FINALIZER_EXPECTED_REVISION=FINALIZER_REVISION_40_HEX,FINALIZER_SOURCE_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals,FINALIZER_SOURCE_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/EPOCH_3_RUN,FINALIZER_EXPECTED_PROVENANCE_SHA256=PROVENANCE_SHA256_64_HEX,FINALIZER_OUTPUT_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft,FINALIZER_OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/FINAL_EXPORT,FINALIZER_EXPECTED_COUNT=2500,FINALIZER_SELECTION=pass-only,FINALIZER_VALIDATION_PERMYRIAD=500,FINALIZER_SPLIT_SALT=terminal-bench-vmvm-sft-v1 /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-FINALIZER_SHA/user/tianhaowu/terminal_bench_vmvm/finalize_qwen_sft.sbatch" C-m
```

Slurm copies the wrapper at submission and `afterok` prevents it from starting
before the evaluator succeeds. The finalizer independently requires every job
recorded in the source provenance to be terminal, rechecks the clean code
revision and provenance digest between stages, and never overwrites an index or
dataset. A partial failure after index publication therefore requires an
explicit aggregate audit before any operator chooses a new output path; do not
blindly rerun or remove artifacts.

### Qwen missing/error repair chain

Do not resume a terminal production Qwen source in place to repair missing or
errored rows. Use `run_qwen_repair_chain.sbatch` from a clean detached checkout
at the exact controller revision. The controller derives the approved task file
only from the immutable source snapshot, requires its externally supplied
SHA-256 and exactly 2,500 opaque entries, and uses the pinned resume planner to
select missing/error indices plus scored passes that fail the exact SFT
trainability audit. Scored failures are retained in the original source and
are not regenerated. A decode-failing final fragment without a newline remains
in the immutable source digest but is omitted from the logical row stream and
left owed; complete malformed rows fail closed, while a valid final JSON object
remains a logical row even without a newline. The chain performs no semantic
task inspection, classification, or name-based filtering.

The controller creates a fresh schema-3 direct run inside a private runtime
directory, with 64 rollout sessions, a 32-request provider/router cap, a
32-request queue, and a 262,144-token total context cap. It invokes
`run_qwen_direct_eval.sbatch` as a shell program in the controller's existing
allocation; it never submits a child Slurm job. The original and repair sources
are hash-checked before and after every subsequent stage. Pass-only original
and repair exports are published atomically, then `merge_qwen_sft.py` publishes
the final corpus atomically after proving the exports are disjoint and bound to
the same split contract. Repair traces are name/index-bound to the evaluator
order of the approved repair universe. The controller passes the exact
post-finalization manifest and complete tree digests for both exports to the
merger, which rejects later mutation and any repair task outside the selected
union; every selected strict-invalid pass must still be replaced. Existing
runtime or output paths are always rejected.
The repair export keeps mode-0600 copies of the selection manifest and repair
attestation beside the four base SFT artifacts; the merger requires both
copies to be byte-identical to the externally hash-pinned inputs and binds
their digests into the merged manifest.

If the planner finds zero owed rows, the controller publishes only the original
pass-only export and returns `finalized_without_repair`; the repair and merged
destinations remain absent. Otherwise success is `merged`, and all three export
directories are present. A failed intermediate stage can leave an attested
original or repair export, but never a final merged directory; use fresh paths
for another attempt and do not delete or overwrite the evidence.

All child stdout and stderr are retained under the private runtime directory as
mode-0600 logs. Scheduler output contains only aggregate counts, SHA-256 values,
and stable error codes. It never forwards task identifiers, prompts, trace rows,
model responses, reasoning, tool payloads, or child errors.

Submit only through `swebench_vmvm:Launcher.0`, after replacing every uppercase
placeholder with an audited literal. Use `afterany` because a terminal producer
may legitimately contain the missing/error rows that this chain repairs. The
three roots must already exist and must be absolute, pairwise-disjoint, narrow
boundaries; every attempt and output directory must be new.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "sbatch --parsable --dependency=afterany:PRODUCER_JOB_ID --export=ALL,QWEN_CHAIN_PROJECT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-CONTROLLER_SHA,QWEN_CHAIN_EXPECTED_REVISION=CONTROLLER_REVISION_40_HEX,QWEN_CHAIN_SOURCE_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals,QWEN_CHAIN_SOURCE_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/ORIGINAL_RUN,QWEN_CHAIN_APPROVED_TASK_FILE_SHA256=APPROVAL_SHA256_64_HEX,QWEN_CHAIN_EXPECTED_PROVENANCE_SHA256=PROVENANCE_SHA256_64_HEX,QWEN_CHAIN_RUNTIME_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/repair-runtime,QWEN_CHAIN_RUNTIME_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/repair-runtime/ATTEMPT,QWEN_CHAIN_OUTPUT_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft,QWEN_CHAIN_ORIGINAL_EXPORT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/ORIGINAL_EXPORT,QWEN_CHAIN_REPAIR_EXPORT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/REPAIR_EXPORT,QWEN_CHAIN_MERGED_OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/MERGED_EXPORT,QWEN_CHAIN_VALIDATION_PERMYRIAD=500,QWEN_CHAIN_SPLIT_SALT=terminal-bench-vmvm-sft-v1 /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-CONTROLLER_SHA/user/tianhaowu/terminal_bench_vmvm/run_qwen_repair_chain.sbatch" C-m
```

With that option, the exporter requires an exact one-to-one row-hash mapping,
binds the full results, index, policy transition, active router manifest, and
transition-anchored epoch-1 hash list. For a schema-3 admission run it also
validates the complete cap-32 transition chain and binds the admission
certificate plus the epoch-2 lineage. Each epoch label is checked against the
anchored lineage before any output is published. Every emitted SFT row and the
aggregate manifest carry its routing epoch. Omit the option for a non-migrated
run; no routing-epoch field is then added.

Use `--selection all-outcomes` only when failed trajectories are intentionally
part of the training recipe. The exporter refuses held evaluator or
direct-router locks, an existing output, provenance drift, and malformed or
errored source structure. Every row is still covered by source/index identity,
duplicate, error-list, completion, reward, and stop-condition validation.
Error rows are counted and excluded. Under `pass-only`, scored failures are
also counted and excluded before the strict trainability audit; only traces
eligible for the output corpus can therefore block it for missing reasoning,
model I/O, or usage. `all-outcomes` applies that strict audit to both passing
and failing scored traces. Selected traces fail closed on request or response
hash corruption and any provider-reported sequence over 262,144 tokens. The
exporter also requires every captured chat request to match the persisted graph
prompt, then validates each retained assistant message, finish reason, and usage
against the captured provider response. Only the exact `/chat/completions`
route is accepted. Assistant `content` may be absent when Verifiers'
`exclude_none` serializer omits it. Unknown message fields/content parts,
non-null `provider_state` or `reasoning_details`, and sampled finish reasons
other than `stop` or `tool_calls` are rejected because the current SFT renderer
cannot preserve those states faithfully. Tool definitions require the
canonical OpenAI `type="function"` envelope and null-free JSON Schema values.
Tool-call arguments must be duplicate-free, finite, null-free JSON objects.
The loader removes only null padding introduced by Arrow's cross-row struct
widening.

One output row represents one unique sampled assistant node and its root-to-node
message path. This preserves every genuine generation exactly once even when a
trace branches; expanding every leaf would duplicate shared-prefix targets.
Prior messages are explicitly non-trainable and prior assistant reasoning is
retained verbatim. The final assistant is the sole trainable message. Every
sampled assistant keeps its authentic `reasoning_content` and `finish_reason`;
the row records source-versus-retained fidelity counts, while content and tool
calls are retained as before. Verifiers' compact tool calls are normalized to
OpenAI function-call objects, and the stable tool schema comes from
integrity-checked captured requests.

The output is atomically published as `train/train.jsonl`,
`validation/train.jsonl`, `task-split.json`,
`target-rendering-contract.json`, and `manifest.json`, plus the validated
routing-index sidecar when one is supplied. The immutable rendering contract
pins the Nemotron Super tokenizer revision, renderer repository revision, and
the exact `nemotron-3` settings that preserve all historical thinking; export,
finalization, and merge reject a changed contract. Task identity is the
SHA-256 of the taskset ID, dataset revision, and explicit approved
task slug separated by NUL bytes; changing a run-local task index does not
change its split. The manifest binds the raw results, resolved and source
configs, approved task snapshot, image snapshot, input manifest, launcher
provenance, exporter source, and every output artifact. Console output contains
aggregate counts and hashes only.

The exported messages are intended for offline retokenization by the target SFT
renderer. They do not recreate teacher token IDs or sampling log probabilities,
which were deliberately not requested from the evaluation endpoint.

Before training format-v3 output, run the rendering preflight from the exact
clean, detached Prime-RL revision that will launch the trainer:

```bash
uv run python user/tianhaowu/terminal_bench_vmvm/preflight_sft.py \
  --export-root /absolute/path/to/corpus \
  --expected-manifest-sha256 MANIFEST_SHA256 \
  --project-dir /absolute/path/to/prime-rl \
  --expected-project-revision PRIME_RL_COMMIT \
  --no-expected-require-exact-provider-json \
  --tokenizer-snapshot-path /absolute/path/to/tokenizer-snapshot \
  --expected-tokenizer-snapshot-sha256 TOKENIZER_TREE_SHA256 \
  --output /absolute/path/to/corpus/sft-render-preflight.json
```

The command renders every row, verifies that retained reasoning changes the
token stream and target reasoning changes trainable tokens, proves the loss
mask matches the selected assistant's renderer attribution, and rejects a
rendered row over 262,144 tokens. It records only aggregate counts and hashes.
For a hermetic preflight, the two tokenizer-snapshot arguments are mandatory as
a pair. The path must be absolute, normalized, canonical, and owned by the
current user. Its root and every subdirectory must be mode 0500; every file
must be a mode-0400, single-link regular file; symlinks and other file types are
rejected. The attestation records the target contract's exact repository and
revision plus a deterministic sorted full-tree fingerprint. The tokenizer is
loaded from that path with `local_files_only=true` and
`trust_remote_code=false`; its fingerprint is checked before and after loading,
after rendering, and immediately before publication. No model weight snapshot
or differently sourced tokenizer may be substituted for the revision-bound
tokenizer-only snapshot.

Use `--expected-require-exact-provider-json` for a strict export; the explicit
negative form above is required for a permissive export. The expectation and
the export's exact source-validation policy are bound into the attestation.
Pin the resulting file and digest in every format-v3 train or validation data
block with `preflight_attestation` and
`preflight_attestation_sha256`. The trainer rehashes the attestation, export
manifest and all declared artifacts, then independently rerenders every row and
rechecks the Prime-RL revision, loader sources, renderer gitlink,
rendering/tokenization dependency versions, tokenizer revision, renderer
config, loss mask, data path, and sequence length before model setup.
Format-v3 rows are also rejected in the dataset loader unless this startup gate
has succeeded. When the attestation contains a tokenizer snapshot, every
trainer rank rehashes it around the actual local-only tokenizer load. The target
tokenizer block still uses the repository and revision metadata from
`target-rendering-contract.json`, with `trust_remote_code = false`; the bound
attestation supplies the canonical local load path. The renderer block must
exactly match its `renderer.config` object.

```toml
[tokenizer]
name = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
revision = "d51eab0d1f979ebc26b546e634a04f450d99158e"
trust_remote_code = false

[data]
type = "sft"
name = "/absolute/path/to/corpus/train"
seq_len = 262144
pack_function = "fixed_stack"
preflight_attestation = "/absolute/path/to/corpus/sft-render-preflight.json"
preflight_attestation_sha256 = "PREFLIGHT_SHA256"
```
