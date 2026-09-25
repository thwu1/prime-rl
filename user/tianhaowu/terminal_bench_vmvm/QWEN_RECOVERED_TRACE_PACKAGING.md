# Qwen recovered unfiltered trace packaging

`package_qwen_recovered_unfiltered_traces.sh` packages the certified canonical
2,499-row Qwen union produced by `qwen_2499_error_retry_supersession.py`. It is
separate from `package_qwen_unfiltered_traces.sh`: the older tool packages the
original VMVM stream plus its Sandoq continuation, while this tool packages the
post-recovery canonical union and its complete certificate chain.

The packager never prints task identifiers, prompts, responses, reasoning, or
raw errors. Its stdout is limited to aggregate counts and SHA-256 values. It
does not parse the raw result rows; the postrun receipt is responsible for the
2,499-row identity, outcome, model-I/O, and reasoning audit.

## Required evidence

Do not launch packaging until the postrun job has completed successfully and
published the mode-0600 result, certificate, manifest, and receipt artifacts
below. The separately reviewed postrun worker is mode 0500. The previous
package manifest is accepted as mode 0644 from an ordinary clean Git checkout
or mode 0600 from a private materialization; its exact digest is pinned either
way.

- recovered `results.jsonl`, `merge_manifest.json`, and
  `qwen_2499_recovered_results_certificate.json`;
- predecessor `qwen_2499_error_retry_run_certificate.json`;
- `qwen_2499_error_retry_superseding_certificate.json`;
- `postrun_receipt-src108b713af-v6.json`;
- the exact failed-complete recovery postrun worker rendered from the reviewed
  frozen revision, with its literal SHA-256 recorded before launch;
- the previous package manifest, SHA-256
  `5ab6b9482d7eff98aea424546592fc5a61e3af11bae9c4ea11f48f4774cb0ac2`.

The packager requires independent SHA-256 pins for every generated artifact.
It validates exact certificate schemas and code hashes, both 64-row outcome
partitions, the 2,499-row recovered outcome equation, replacement counts,
reasoning/model-I/O capture counters, source job, selection contract, canonical
task-file digest, postprocessor revision, and predecessor revision. Inputs,
the packager, the Slurm worker, and the clean frozen checkout are checked again
after archive generation to catch concurrent mutation.

## Deterministic output

The tar stream has normalized owner, group, mode, timestamps, ordering, and PAX
metadata. Production uses zstd level 19, one compression thread, and a 31-bit
long-distance window; the manifest records the actual configured level. It is
split into 95,000,000-byte ordinary Git
blobs, which is strictly below 100,000,000 bytes. Before publication the tool
verifies:

- every chunk hash and size;
- concatenated archive size and SHA-256;
- zstd integrity using `--long=31`;
- the exact seven-member archive inventory;
- every source artifact is unchanged.

The checkpoint package destination is
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/exports/qwen-2499-recovered-unfiltered-108b713af-v6`.
After review, copy it to the distinct tracked path
`user/tianhaowu/terminal_bench_vmvm/trace_packages/qwen-2499-recovered-unfiltered-108b713af-v6`.
Never overwrite or reuse either path.

## Launch

First commit and freeze this packager, its Slurm worker, launcher, and tests.
Use that clean frozen checkout for `QWEN_V6_PACKAGE_PROJECT_DIR`; use literal
40-hex and 64-hex identities, not branch names. Configure the remaining
variables as follows:

```bash
export QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION=RECOVERY_REVISION_40_HEX
export QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION=RECOVERY_REVISION_40_HEX
export QWEN_V6_PACKAGE_EXPECTED_RETRY_MODULE_SHA256=8117cf9709e6747046052a465c6ffe8bc0f80c6825dfb6157823af611d1fa1ed
export QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_EXPORTER_SHA256=d6386bc08eec676ec1e48913aca37e934cf65c90dabbd0fa99ee5221d5118fbb
export QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_EXPORTER_SHA256=d6386bc08eec676ec1e48913aca37e934cf65c90dabbd0fa99ee5221d5118fbb
export QWEN_V6_PACKAGE_EXPECTED_SUPERSESSION_MODULE_SHA256=SUPERSESSION_MODULE_SHA256_64_HEX
export QWEN_V6_PACKAGE_EXPECTED_AUDIT_TRACES_SHA256=7b20a4e600cdff8213b9be322029087962e700df87dd06f1c702cb4278970ad3
export QWEN_V6_PACKAGE_EXPECTED_VERIFIER_REVISION=3df6efa9e9f6bdc8a013df7759a03074aec79111
export QWEN_V6_PACKAGE_EXPECTED_RENDERER_REVISION=044d9e2541f6a911cacae9da353fc063911ef1f8
export QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_ID=qwen3-a95b-direct-medium
export QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_SHA256=c83833ac8950a17a1d9e7a65ac1fe8f585376a838e4737ce92b20c8eaa4ab777
export QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB=1579607
export QWEN_V6_PACKAGE_SELECTION_CONTRACT_SHA256=5369194fc1bea5dd72c20457a8fd1fac906144c8beb4bc20d77727fb77c8b228
export QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256=5b2ed7c5b166a6570b46d3dacff680c5ba6ff22f7e02e57e273eb442e6842b8c
export QWEN_V6_PACKAGE_POSTRUN_WORKER=/storage/home/tianhaowu/.codex/tmp/qwen_failed_complete_1579607_postrun_v1.sbatch
export QWEN_V6_PACKAGE_POSTRUN_WORKER_SHA256=POSTRUN_WORKER_SHA256_64_HEX
export QWEN_V6_PACKAGE_UNFILTERED_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/qwen-2499-error-retry-20260925-v5/merged-unfiltered-src108b713af-v6
export QWEN_V6_PACKAGE_RETRY_CERTIFICATE=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/qwen-2499-error-retry-cpu131165-8101-srcd9a4eb07d-c64-medium-v5/qwen_2499_error_retry_run_certificate.json
export QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/qwen-2499-error-retry-cpu131165-8101-srcd9a4eb07d-c64-medium-v5/qwen_2499_error_retry_superseding_certificate.json
export QWEN_V6_PACKAGE_POSTRUN_RECEIPT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/qwen-2499-error-retry-20260925-v5/postrun_receipt-src108b713af-v6.json
export QWEN_V6_PACKAGE_PREVIOUS_MANIFEST=/storage/home/tianhaowu/prime-kimi-buffered-capture/user/tianhaowu/terminal_bench_vmvm/trace_packages/qwen-2499-unfiltered-1ae8855f-v1/manifest.json
export QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256=5ab6b9482d7eff98aea424546592fc5a61e3af11bae9c4ea11f48f4774cb0ac2
export QWEN_V6_PACKAGE_OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/exports/qwen-2499-recovered-unfiltered-108b713af-v6
export QWEN_V6_PACKAGE_JOBID_FILE=/storage/home/tianhaowu/.codex/tmp/qwen_recovered_unfiltered_v6_package.jobid
export QWEN_V6_PACKAGE_CHUNK_BYTES=95000000
export QWEN_V6_PACKAGE_ZSTD_LEVEL=19
```

After the postrun job has succeeded, pin every generated artifact without
opening `results.jsonl`:

```bash
export QWEN_V6_PACKAGE_EXPECTED_RESULTS_SHA256=$(sha256sum "$QWEN_V6_PACKAGE_UNFILTERED_DIR/results.jsonl" | awk '{print $1}')
export QWEN_V6_PACKAGE_EXPECTED_RECOVERED_CERTIFICATE_SHA256=$(sha256sum "$QWEN_V6_PACKAGE_UNFILTERED_DIR/qwen_2499_recovered_results_certificate.json" | awk '{print $1}')
export QWEN_V6_PACKAGE_EXPECTED_MERGE_MANIFEST_SHA256=$(sha256sum "$QWEN_V6_PACKAGE_UNFILTERED_DIR/merge_manifest.json" | awk '{print $1}')
export QWEN_V6_PACKAGE_EXPECTED_RETRY_CERTIFICATE_SHA256=$(sha256sum "$QWEN_V6_PACKAGE_RETRY_CERTIFICATE" | awk '{print $1}')
export QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256=$(sha256sum "$QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE" | awk '{print $1}')
export QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256=$(sha256sum "$QWEN_V6_PACKAGE_POSTRUN_RECEIPT" | awk '{print $1}')
```

Record those six literal digests in the launch receipt before submission; do
not recompute them after a failed validation. Replace every `_40_HEX` and
`_64_HEX` placeholder above from the same clean frozen recovery checkout and
rendered postrun worker. Set these four values from the clean frozen packaging
checkout:

```bash
export QWEN_V6_PACKAGE_PROJECT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-qwen-package-PACKAGE_REVISION_PREFIX
export QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION=PACKAGE_REVISION_40_HEX
export QWEN_V6_PACKAGE_PACKAGER_SHA256=PACKAGER_SHA256_64_HEX
export QWEN_V6_PACKAGE_WORKER_SHA256=WORKER_SHA256_64_HEX
```

All Slurm submission must occur in `swebench_vmvm:Launcher.0`. Pass the numeric
postrun job ID; the launcher atomically reserves its job-ID receipt, uses an
`afterok` dependency, validates the optional numeric settings before building
the export list, and exports only the explicit package variables. It supplies
`QWEN_V6_PACKAGE_POSTRUN_JOB_ID` itself:

```bash
bash "$QWEN_V6_PACKAGE_PROJECT_DIR/user/tianhaowu/terminal_bench_vmvm/launch_qwen_recovered_unfiltered_trace_package.sh" POSTRUN_JOB_ID
```

## Publish

Use `publish_qwen_recovered_unfiltered_trace_package.sh` only after the chain
watcher reports `stage=chain,state=completed`. The publisher independently
checks that state, the mode-0600 package job receipt, Slurm completion, job
name, and submitted worker hash. It then validates the complete manifest
lineage, every streamed archive member hash and size, canonical tar
member-padding and termination with no trailing bytes, zstd integrity, chunk hashes, and the
deterministic contiguous chunk sequence without printing archive contents. Every
nonfinal chunk must be exactly 95,000,000 bytes; the final chunk must be
nonempty and no larger than that bound.

The caller must pin every identity rather than relying on a mutable branch or
recomputing values after validation. In particular, set:

- `QWEN_PUBLISH_REPOSITORY`, `QWEN_PUBLISH_SOURCE`, and
  `QWEN_PUBLISH_TARGET_RELATIVE`;
- `QWEN_PUBLISH_WATCHER_STATE` and
  `QWEN_PUBLISH_PACKAGE_JOBID_FILE`;
- the durable, private `QWEN_PUBLISH_TRANSACTION_DIR`;
- `QWEN_PUBLISH_EXPECTED_REMOTE_HEAD` and
  `QWEN_PUBLISH_EXPECTED_REMOTE_URL`;
- the package project revision, packager hash, package worker hash, streaming
  archive-verifier hash, source and postrun jobs, postrun worker hash,
  postprocessor and predecessor revisions;
- the selection, canonical-task, predecessor-manifest, results, certificate,
  merge-manifest, postrun-receipt, package-manifest, and README SHA-256 values;
- `QWEN_PUBLISH_COMMIT_MESSAGE`.

Pass the exact package job ID as the sole argument:

```bash
bash user/tianhaowu/terminal_bench_vmvm/publish_qwen_recovered_unfiltered_trace_package.sh PACKAGE_JOB_ID
```

The repository must be clean and its `HEAD` must equal both the pinned head and
the live `origin/vmvm-sandbox` head. Fetch and push URLs must each be unique and
equal the pinned URL. Production requires the self-contained absolute URL
`https://github.com/thwu1/prime-rl.git`; cwd-dependent relative and scp-style
URLs are rejected. The publisher holds a repository-wide lock, builds the
commit in a persistent isolated bare transaction, bypasses Git filters, and
disables client hooks. The main worktree, index, and `HEAD` stay unchanged.
After another remote-race check, it pushes to the literal pinned URL with the
explicit non-force refspec
`RECOVERY_COMMIT:refs/heads/vmvm-sandbox`, then verifies the
remote head, tree, blob hashes, and blob sizes.

The transaction receipt is atomically updated before the push. On restart, the
publisher checks whether the remote accepted the exact transaction commit and
finishes idempotently without pushing again. A failed or interrupted push is
accepted only if a fresh remote query proves that exact commit is the branch
head; every ambiguous outcome fails closed while retaining the transaction for
audit and retry.
