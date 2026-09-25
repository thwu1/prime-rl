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
- the exact postrun worker whose current reviewed SHA-256 is
  `d5abdff1e89b2d4b0fa4c0e472c84db91d397180b27a18f87a0f666bded295a3`;
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
export QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION=108b713af332b6865c49c3b146f3fa2158fe790a
export QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION=d9a4eb07de3b769899c0e77eedf5da5f6c35ab61
export QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB=1579607
export QWEN_V6_PACKAGE_SELECTION_CONTRACT_SHA256=5369194fc1bea5dd72c20457a8fd1fac906144c8beb4bc20d77727fb77c8b228
export QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256=5b2ed7c5b166a6570b46d3dacff680c5ba6ff22f7e02e57e273eb442e6842b8c
export QWEN_V6_PACKAGE_POSTRUN_WORKER=/storage/home/tianhaowu/.codex/tmp/qwen_exact64_postrun_d9a4eb07d_v5.sbatch
export QWEN_V6_PACKAGE_POSTRUN_WORKER_SHA256=d5abdff1e89b2d4b0fa4c0e472c84db91d397180b27a18f87a0f666bded295a3
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
not recompute them after a failed validation. Set these four values from the
clean frozen packaging checkout:

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

After the package job completes `0:0`, verify its manifest and chunks again,
copy the whole directory through an exclusive temporary-directory rename to
the tracked path above, confirm
`git check-attr filter` does not report `lfs` for any chunk, then `git add` that
single package directory. Review the staged blob sizes and hashes before a
separate commit and push to `origin/vmvm-sandbox`.
