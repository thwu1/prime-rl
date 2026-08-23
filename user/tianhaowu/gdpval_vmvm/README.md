# GDPval v2 on VMVM

This folder runs the public 220-task `openai/gdpval` suite with the Artificial
Analysis Stirrup agent contract, a VMVM code sandbox, Nemotron 3 Super as the
policy, and Kimi K2.6 as the multimodal judge.

## What this result means

The official Artificial Analysis value for
`nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16`, captured on 2026-08-22, is
**698.06 Elo / 9.903 normalized points** (often displayed as 700 Elo):

- [Artificial Analysis model page](https://artificialanalysis.ai/models/nvidia-nemotron-3-super-120b-a12b)
- [Immutable 2026-08-22 score capture](https://github.com/TabNahida/AInsights/blob/e45e3eac0cf0fa69f4cf9e14e2e45fbd347f00be/ArtificialAnalysis/artificialanalysis_raw_scores_wide.csv)
- [Artificial Analysis methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking#gdpval-aa)

An exact public rerun is not possible. The pinned public dataset includes human
expert deliverables for 185 of 220 tasks, but Artificial Analysis does not
publish the complete multi-model reference set, comparison graph, sampled judge
outcomes, exact sandbox image, or Nemotron parser plugin used for the reported
run. Its Elo is also refit as new models enter the comparison graph. This runner
therefore labels every result as a **Kimi-judged surrogate** and never claims
official parity.

## Pinned public protocol

- GDPval dataset revision `11e7900cdcac61bc4daf59e65feb238acda98fbf`
- GDPval asset mirror
  [`ycm824632241/benchmark-8.13`](https://github.com/ycm824632241/benchmark-8.13/tree/ab55c6be877d2da8d7016e809cbfc9cab2ed1e90)
  at commit `ab55c6be877d2da8d7016e809cbfc9cab2ed1e90`, tasks tree
  `2a76ef74c516bbebca41150458ab5bb06983a2d1`, and checked-in manifest SHA-256
  `3df5445b1d3a321b9c3c2b7abc418a273d189149e0e966cfc6e0a8604ba38b91`
- Nemotron checkpoint revision `d51eab0d1f979ebc26b546e634a04f450d99158e`,
  served by vLLM `0.22.0` with a 262,144-token context window
- [NVIDIA Gym recipe](https://github.com/NVIDIA-NeMo/Gym/tree/57c15a22f8b82d3d859b71468fe3329f4e2093b4/benchmarks/gdpval)
  `57c15a22f8b82d3d859b71468fe3329f4e2093b4`
- [Experimental NVIDIA Kimi judge overlay](https://github.com/NVIDIA-NeMo/Gym/pull/2046)
  `13e181aa1779809457d1abbf47ab209d8d0f5ab3`
- [Artificial Analysis Stirrup v0.1.12](https://github.com/ArtificialAnalysis/Stirrup/tree/3e988e5a1729cea37e6484e5cab2ab0f9eae4ffb)
- 250 agent turns; Nemotron temperature 1.0, top-p 0.95, reasoning enabled
- NeMo's dynamic-token behavior is preserved: reasoning-only or otherwise
  empty choices count as turns, and Stirrup supplies its normal continuation
  message instead of resampling the same model request
- Kimi PDF/Office rendering at 150 DPI, at most 30 pages per file, extracted text included
- Each references/A/B section is capped at 18 visual blocks and 20,000 emitted
  text characters after per-file rendering, with deterministic fair allocation
  across files and an explicit marker whenever either cap applies
- Generated Office PDF sidecars are used for rendering but not emitted a second
  time as duplicate judge inputs
- Four judge calls per task; pairwise mode alternates submission position and uses the last
  `BOXED[A]`, `BOXED[B]`, or `BOXED[TIE]` verdict
- Nested artifacts are traversed recursively; PDF and Office pages are supplied
  to Kimi as extracted text plus 150-DPI PNGs

NVIDIA Gym normally uses a sampled GPT-5.5 / Gemini 3.1 Pro / Claude Opus 4.8
panel. Its Kimi configuration is a separate local-judge overlay and is the basis
for this runner's judge path. Kimi does not support this benchmark's audio/video,
PSD, or STEP artifacts, so the default run excludes those tasks rather than
silently judging filenames. Combined with missing public expert deliverables,
its denominator is 178/220. Every exclusion is recorded, including STEP files
nested in an otherwise supported ZIP archive and one pinned 32-MiB gold ZIP
whose source bytes have no central directory.

As of 2026-08-22, the Kimi overlay's PR is still open and does not publish a
Nemotron 3 Super score or raw judgement artifact. The calibration screenshot in
that PR uses MiniMax M3 for other models. Consequently, the referenceable Super
target remains the separately cited Artificial Analysis snapshot; a score from
this runner must be reported as its own pinned Kimi-surrogate experiment.

The open Kimi overlay emits each preconverted Office document twice: once under
the Office filename and again as its generated sibling PDF. This runner uses the
sibling PDF as the Office rendering source without emitting it as a second
deliverable. It then applies a reproducible context-safety policy independently
to the references, submission A, and submission B sections. Each file is first
rendered at the unchanged 150 DPI and 30-page per-file limit; the section then
retains at most 18 visual blocks by deterministic round-robin allocation across
files and at most 20,000 total text characters by deterministic fair sharing.
The text budget includes file labels and the explicit cap notice, so truncation
is never silent. macOS ZIP metadata (`__MACOSX`, AppleDouble `._*`, and
`.DS_Store`) is ignored before rendering. Text and source artifacts, including
Terraform and CSS, are decoded with visible replacement markers for invalid
UTF-8 bytes rather than aborting the evaluation. PDFMiner uses positional
ordering (`boxes_flow=None`) so repeated rendering and audit reconstruct the
same extracted-text sequence, including forms with overlapping labels.
Two pinned public reference DOCX files contain redacted external hyperlink
relationships whose empty OOXML elements are missing their closing `/>`.
LibreOffice cannot open those packages even though their ZIP checksums pass.
The renderer repairs only those malformed relationship elements in its
temporary conversion copy; the cached benchmark files and their recorded hashes
remain unchanged.

These limits are pinned in TOML and included in the semantic configuration,
judge identity, and audited request hashes. On the previously failing 54-page
case, the capped request measured 178,186 input tokens; together with Kimi's
65,535-token output allowance it totals 243,721, below the 262,144-token context
window. The configured values may be tightened, but validation rejects values
above these measured-safe maxima.

The official-style NVIDIA sandbox definition is
[`gdpval.def`](https://github.com/NVIDIA-NeMo/Gym/blob/57c15a22f8b82d3d859b71468fe3329f4e2093b4/responses_api_agents/stirrup_agent/containers/gdpval.def).
It includes LibreOffice, Chromium, Poppler, Tesseract, Pandoc, TeX, audio/video,
geospatial, document, and scientific tooling. The runtime probe fails closed if
the selected VM image cannot render Office artifacts; the generic cached VMVM
image is not an acceptable substitute.

[`Dockerfile.sandbox`](./Dockerfile.sandbox) is a direct Docker translation of
that pinned definition. It uses the immutable `python:3.13-bookworm` base index
`sha256:62eafe52c91cad83c2c74e630bfde917da8c253673e695665d454def84fc9a13`
and produces the validated runtime image
`docker.io/tianhao0122/optimbench-tb@sha256:31aa69a13dee68d525e49748d937f9a26b05e24aff769f5348b83902f34014df`.
The image is 4,684,311,365 bytes compressed and 11,641,680,258 bytes after a
fresh pull. Its command/font/TeX/import checks and a real LibreOffice DOCX-to-PDF
render passed in a clean VM; the captured `pip freeze` has SHA-256
`a7600f936030214eec6d9cd9546599f9d75ff4c891a2e9d583af97e2518bd29e`.

## Install and validate

```bash
uv sync --project user/tianhaowu/gdpval_vmvm
uv run --project user/tianhaowu/gdpval_vmvm python \
  user/tianhaowu/gdpval_vmvm/run_eval.py \
  user/tianhaowu/gdpval_vmvm/nemotron_super_kimi.toml --dry-run
```

Prepare the pinned catalog and the default 178-task asset selection:

```bash
uv run --project user/tianhaowu/gdpval_vmvm python \
  user/tianhaowu/gdpval_vmvm/run_eval.py \
  user/tianhaowu/gdpval_vmvm/nemotron_super_kimi.toml --prepare-only
```

Preparation downloads only the selected eligible tasks to the host cache. It
uses commit-pinned raw GitHub blobs plus GitHub's anonymous Git-LFS batch API,
then verifies byte length, SHA-256, ordinary Git blob IDs, and ZIP structure.
The default 178-task comparison requires 447 assets (443 ordinary blobs and four
LFS ZIPs, about 147 MB). `--task-id` and `--limit` restrict preparation to the
matching selection. `--dry-run` performs no downloads and reports whether that
selection is already complete and verified. The batch entrypoint performs this
preparation before starting its VMVM preflight lease. A smoke launched with
`GDPVAL_TASK_ID` also uses that task's reference input for the render preflight.

Validate the live endpoints before dispatching work:

```bash
uv run --project user/tianhaowu/gdpval_vmvm python \
  user/tianhaowu/gdpval_vmvm/probe_runtime.py \
  user/tianhaowu/gdpval_vmvm/nemotron_super_kimi.toml --endpoints-only
```

The full probe must run from a CPU Slurm allocation; `run_eval.sbatch` does this
automatically. The interactive Codex container cannot expose VMVM's reverse SSH
tunnel reliably. The probe checks a real Nemotron tool call, a real Kimi image answer, the
official image's required command/font and Python import-smoke surface,
verified host-cache staging, and Office-to-PDF rendering. Its content-addressed
output is bound to the config fingerprint, deployment identities, server
version, model metadata, and OCI image. `run_eval.sbatch` runs it automatically; set
`GDPVAL_SKIP_RUNTIME_PROBE=1` only for a judge-only resume whose candidate and
rendered-reference caches are already complete. That path still performs a
fresh Kimi text-and-vision probe before resuming the persisted judgements.

Task assets are cached and verified on the CPU host before any evaluation lease,
then uploaded into the VM under their original catalog paths and verified again
inside the container. The pinned GitHub transport is public, so the checked-in
configuration does not require `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN`. API keys
are read only from configured environment variables or endpoint-info files;
they are never stored in the run directory. The canonical pinned NeMo Gym
configuration does not require a search API key, but the checked-in configs set
`tools.require_brave_search = true` to expose the `web_search` capability used
by the UniPat Kimi-K3 SFT trajectories. Export `BRAVE_API_KEY` in the launch
environment; never write it into TOML, logs, or result metadata. This is an
explicit SFT-compatibility extension to the public no-search recipe, and the
preflight and run metadata record that capability.

The checked-in configs also set `tools.sft_compatibility_aliases = true`.
Canonical `run_shell`, `/workspace`, and `finish.reason` remain supported. The
compatibility surface additionally exposes `code_exec` through the same sandbox
executor, maps `/home/user` to `/workspace` alongside the existing
`/working_dir` alias, and accepts `finish.summary` as an alias for
`finish.reason`. Conflicting `summary` and `reason` values are rejected; a
matching pair is canonicalized to `reason`. Submitted `/home/user` paths are
resolved against `/workspace` for validation, rendering, and artifact capture.
Compatibility mode keeps the canonical prompt and `/workspace` working
directory unchanged. It sets `HOME=/home/user`, so absolute paths learned from
the SFT data address the same files through the symlink while relative commands
retain the official GDPval behavior. Set the flag to `false` to expose only the
canonical interface.

Slurm CPU nodes inherit HTTP proxy variables whose node-local proxy address is
not reachable there. The checked-in configs therefore pin
`tools.web_fetch_trust_env = false`. The worker applies that setting only to its
managed Stirrup HTTP client; it does not unset process-wide proxy variables that
other transports may need. The full preflight uses the same provider to fetch
`https://example.com/`, checks stable extracted body text, and records the names
but not the values of proxy variables present in the CPU-node environment.
With search enabled, it performs a real Brave query and verifies that both
`fetch_web_page` and `web_search` are exposed. A config that disables search
instead verifies that an ambient Brave key cannot enable it. In both modes, the
probe confirms that malformed model-supplied URLs become failed tool results
rather than aborting the rollout. Dispatch and audit reject a preflight without
this semantic evidence. This narrow malformed-URL handling follows the
corresponding fix on Stirrup main while retaining the pinned v0.1.12 agent
protocol.

The mirror has an exact structural match to the pinned v2 catalog: all 220
prompt strings, 261 reference-file mappings, and 248 public-gold mappings agree.
Its two available independent GitHub comparators are older dataset snapshots:
they byte-confirm 160 current reference files, while 101 current-v2 references
and all public gold files lack an independent Hugging Face hash confirmation.
Accordingly, the manifest provides immutable reproducible transport, but this
runner does not claim those remaining mirror bytes were independently certified
against Hugging Face.

Inline `policy.api_key` and `judge.api_key` TOML fields are rejected because the
configuration is snapshotted for provenance.

The policy deployment is pinned to `policy.slurm_job_id`, and the judge is
pinned to `judge.proxy_jobid` from its endpoint-info file. Endpoint resolution
checks that those runtime IDs agree with `deployment_id`, the live Slurm job
name or proxy-info record, and the resolved URL. `GDPVAL_POLICY_JOB_ID`,
`GDPVAL_POLICY_BASE_URL`, `GDPVAL_JUDGE_BASE_URL`, and their CLI equivalents may
only restate that same pinned deployment; a mismatch fails before probing or
dispatch. Preflight artifacts, endpoint-session rows, run metadata, and audit
output retain these public IDs but never endpoint API keys.

The originally investigated community image was 16.1 GB compressed and carried
unrelated vLLM/PyTorch/FlashInfer layers; its pull exceeded VMVM's 50 GiB writable
store. The clean image above follows NVIDIA's pinned GDPval definition, omits
those unrelated GPU-serving layers, and fits the standard VMVM tier. The
specialized `repo_rlef` preload tier returned `No healthy containers` in two
bounded probes, so the checked-in configuration uses an ordinary immutable
Docker Hub pull (`preload_image = false`).

The configured Kimi endpoint passed production-shaped text and blue-PNG vision
probes. The replacement Nemotron deployment likewise passed text, reasoning,
and forced-tool-call probes and is bound to its exact job, model revision, and
vLLM version in the configuration.

## Run

The checked-in config uses Kimi pairwise scoring against the available public
human-expert deliverables, anchored at Elo 1000. This is a referenceable local
subset score, not the official AA v2 Elo:

```bash
sbatch user/tianhaowu/gdpval_vmvm/run_eval.sbatch
```

The batch wrapper resolves the original submitted script from Slurm's `Command`
field because `BASH_SOURCE[0]` points at Slurm's spool copy inside a running job.
Set `GDPVAL_RUNNER_DIR` only when intentionally overriding that submitted path.

Smoke one task first:

```bash
GDPVAL_LIMIT=1 GDPVAL_WORKERS=1 \
GDPVAL_OUTPUT_DIR=/checkpoint/ram/tianhaowu/gdpval_vmvm/smoke \
sbatch user/tianhaowu/gdpval_vmvm/run_eval.sbatch
```

For comparisons against other model runs, copy
`nemotron_super_kimi_comparison.example.toml` and populate its external
`[[references]]` directory. Reference Elo anchors are explicit; the runner will
not invent one. Candidate artifacts are persisted before judging, so a judge
outage resumes the same immutable candidate instead of resampling the policy.
All available `repeat_*` directories for an external reference are judged and
their raw votes are pooled.

When a judge rendering or protocol change alters the semantic fingerprint, do
not edit or resume the old output directory. Import its persisted candidates
into a new scoring run:

```bash
uv run --project user/tianhaowu/gdpval_vmvm python \
  user/tianhaowu/gdpval_vmvm/run_eval.py \
  user/tianhaowu/gdpval_vmvm/nemotron_super_kimi.toml \
  --output-dir /checkpoint/ram/tianhaowu/gdpval_vmvm/smoke-rescored \
  --candidate-source-run /checkpoint/ram/tianhaowu/gdpval_vmvm/smoke-20260822 \
  --limit 1 --workers 1 --preflight-file NEW_PREFLIGHT.json
```

The source run must be idle and use the same generation-relevant source,
benchmark, policy, tools, runtime, rollout implementation, and VMVM backend.
Its catalog must include the preparation sidecar; the runner verifies the
pinned dataset revision and parquet digest, catalog digest and release shape,
transport, and asset-mirror identity, then snapshots and hash-binds that
sidecar in both runs and the import bundle. Source preflight acceptance uses
only generation evidence (policy, tools, scoped web fetch, sandbox, and asset
cache), so judge-only probe fields and preflight schema additions do not
invalidate an otherwise generation-compatible candidate.
The runner copies each matching artifact directory atomically. It retains the
source `candidate.json` in a hash-bound receipt, changes only the copied
candidate's run fingerprint and import envelope, and preserves its artifact
manifest and aggregate digest. The new judge starts with a fresh endpoint
session and journal. By default, any planned candidate missing from the source
is an error; pass `--missing-candidate-policy generate` only when genuinely
absent candidates should be generated. A source mismatch or corrupt existing
candidate is always fatal and is never treated as permission to resample. The
frozen source-missing set remains in run metadata after those absent candidates
are generated, so later resumes preserve the same import provenance.

Enabling Brave search or changing the policy-facing compatibility aliases is a
generation change, not a judge-only migration. The complete `[tools]` table is
included in the semantic and generation fingerprints. Keep an older output
directory frozen and start a new one with regenerated candidates; resume and
candidate import from the earlier no-search/tool-contract fingerprint are
intentionally rejected.

## Recovery and audit contract

- Only VMVM `broken_pipe` is transparently recovered in place, using
  `restart_session()` followed by `recover_last()`; an uncertain stateful command
  is never resent.
- A confirmed lost VM/container before candidate persistence gets a fresh
  rollout attempt. Model failures and the official task wall-clock are terminal
  and are never resampled. Because AA does not publish how those failures enter
  its pairwise graph, this runner records reward zero but withholds headline Elo
  instead of silently dropping them. Judge timeouts, connection failures,
  408/409/429 responses, and 5xx responses retry only the judge; other 4xx
  responses remain deterministic fatal errors.
- `results.jsonl` and `attempts.jsonl` are append-only and fsynced. Resume checks
  a semantic config/source fingerprint and contiguous safe retry chains. Every
  retry or fatal row records whether the failure belongs to the policy or judge
  endpoint. A judge-retry row also binds the canonical candidate directory and
  aggregate digest; a missing, corrupt, relocated, or changed candidate is fatal
  before import recovery or dispatch can regenerate it.
- A malformed final JSONL record is repaired only under the single-writer lock,
  with before/after hashes retained; corruption before the final record remains
  fatal. Recovered stdout and kill-shaped worker summaries are written atomically,
  and orphaned durable worker results are reconciled before dispatch so a
  coordinator crash cannot resample a terminal model outcome.
- Judge-protocol migrations use a new output directory and
  `--candidate-source-run`. The frozen source bundle, original candidate
  manifests, generation fingerprint, import receipts, and new scorer
  fingerprint are retained and independently checked by the audit. The source
  run is never modified.
- Candidate files, raw judge calls, source/config snapshots, the pinned asset
  manifest, catalog provenance sidecar, verified cache provenance,
  implementation hashes, endpoint-session records, the preflight artifact, and
  a deterministic implementation archive are retained.
- One process owns an output directory via `.writer.lock`; Slurm requeue is disabled.
- Headline Elo and its task-clustered sandwich interval are withheld unless every
  planned comparison completed; any partial estimate is explicitly labeled as
  completed-comparisons-only.

The official AA v2 setup uses balanced then Elo-informed sampling, a human
anchor at Elo 1000, randomized blinded A/B comparisons, and one sampled member
of its frontier judge panel per comparison. NVIDIA's closest public recipe uses
45 tasks against all available anchors, then all 220 tasks against the nearest
four anchors. Reproducing that recipe requires generating and pinning those
reference-model deliverables; the public human-only configuration cannot be
numerically compared with the official 698.06 Elo.

Audit a completed or interrupted run with the implementation archived inside
that run (replace `OUTPUT_DIR` in both positions):

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=OUTPUT_DIR/implementation/user/tianhaowu/gdpval_vmvm \
uv run --project user/tianhaowu/gdpval_vmvm --no-sync python -B \
  OUTPUT_DIR/implementation/user/tianhaowu/gdpval_vmvm/audit.py OUTPUT_DIR
```
