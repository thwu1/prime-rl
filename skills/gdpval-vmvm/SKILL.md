---
name: gdpval-vmvm
description: Prepare, launch, resume, audit, and interpret GDPval v2 evaluations using Stirrup, VMVM, Nemotron 3 Super, and a Kimi K2.6 multimodal judge. Use for GDPval-AA protocol provenance, Kimi rubric or pairwise scoring, immutable candidate recovery, and distinguishing local surrogate scores from Artificial Analysis results.
---

# GDPval v2 on VMVM

The standalone workflow lives in `user/tianhaowu/gdpval_vmvm/`. Read its
README and the lower-level `skills/vmvm-runtime/SKILL.md` before changing the
runner:

```bash
sed -n '1,260p' user/tianhaowu/gdpval_vmvm/README.md
```

## Provenance boundary

Pin the public dataset, NVIDIA Gym recipe, Kimi overlay, Stirrup version, OCI
image digest, prompts, and implementation hashes. The 2026-08-22 Artificial
Analysis snapshot for Nemotron 3 Super is 698.06 Elo / 9.903 normalized points.
Do not claim exact official reproduction: the public dataset has human-expert
deliverables for 185/220 tasks, while AA's complete multi-model reference set,
comparison graph, sampled frontier-panel judgements, exact sandbox, and
Nemotron parser plugin are not public. A Kimi-judged result is a local surrogate.
The Kimi overlay is an open experimental NVIDIA PR and publishes no Nemotron 3
Super result or raw judge artifact; do not attribute a local Kimi score to
NVIDIA or Artificial Analysis.

The open overlay emits preconverted Office files twice, once through the Office
entry and again through its sibling PDF. Keep
`judge.deduplicate_office_pdf_sidecars = true`: the PDF remains the rendering
source, but duplicate visual/text blocks are omitted. Also keep
`judge.max_visual_blocks_per_section = 18` and
`judge.max_text_characters_per_section = 20000`. Render each file at the
unchanged 150 DPI and 30-page limit before applying these independent caps to
references, submission A, and submission B. Allocation must remain deterministic
and fair across files, and every capped section must include an explicit notice.
The 54-visual-block stress case measured 178,186 input tokens; with the pinned
65,535 output tokens it totals 243,721 under Kimi K2.6's 262,144-token context.
The config, judge identity, and audited request hashes carry these knobs. Report
the sidecar deduplication and section caps as compatibility corrections; they are
not byte-for-byte behavior of the open PR. Skip `__MACOSX`, AppleDouble `._*`,
and `.DS_Store` members when expanding ZIPs, after checking the member path for
traversal. Treat Terraform and CSS as text, and decode text artifacts with a
visible replacement notice for invalid UTF-8 bytes instead of aborting. Extract
PDF text with `LAParams(boxes_flow=None)`; the default PDFMiner layout analysis
can reorder overlapping form labels between calls and break exact request-hash
replay.
Two pinned reference DOCX files have redacted external-hyperlink relationship
elements missing `/>`. Repair only that exact OOXML pattern in the temporary
LibreOffice conversion copy; preserve and hash the original asset bytes.

Match NeMo's dynamic-token client on policy responses: do not resample a choice
merely because it has no final content or tool call. Preserve reasoning-only and
fully empty choices as turns so Stirrup can add its normal continuation message.

## Setup and launch

```bash
uv sync --project user/tianhaowu/gdpval_vmvm
uv run --project user/tianhaowu/gdpval_vmvm python \
  user/tianhaowu/gdpval_vmvm/run_eval.py \
  user/tianhaowu/gdpval_vmvm/nemotron_super_kimi.toml --dry-run
```

Prepare the pinned catalog and host-side asset cache, then smoke one task:

```bash
uv run --project user/tianhaowu/gdpval_vmvm python \
  user/tianhaowu/gdpval_vmvm/run_eval.py \
  user/tianhaowu/gdpval_vmvm/nemotron_super_kimi.toml --prepare-only

GDPVAL_LIMIT=1 GDPVAL_WORKERS=1 \
GDPVAL_OUTPUT_DIR=/checkpoint/ram/tianhaowu/gdpval_vmvm/smoke \
sbatch user/tianhaowu/gdpval_vmvm/run_eval.sbatch
```

The default transport pins `ycm824632241/benchmark-8.13` at commit
`ab55c6be877d2da8d7016e809cbfc9cab2ed1e90`, tasks tree
`2a76ef74c516bbebca41150458ab5bb06983a2d1`, and manifest SHA-256
`3df5445b1d3a321b9c3c2b7abc418a273d189149e0e966cfc6e0a8604ba38b91`.
It fetches ordinary files through commit-pinned raw GitHub URLs and LFS files
through the anonymous Git-LFS batch API. Files are size/hash checked in the host
cache, uploaded under their original catalog paths, and checked again inside the
VM. ZIP structure is also checked before dispatch. The default 178-task
selection is 447 files and about 147 MB. The STEP-in-ZIP task and the truncated
32-MiB gold ZIP task are excluded explicitly. `--dry-run`
reports readiness without downloading; `--task-id` and `--limit` restrict the
prepared selection. Treat a successful HTTP status as insufficient: raw GitHub
responses can truncate, so retry size/hash mismatches and publish to the cache
only after verification succeeds.

The mirror structurally matches all 220 prompts, 261 reference files, and 248
public gold files in the pinned catalog. Older independent GitHub snapshots
byte-confirm only 160 current reference files; 101 current-v2 references and all
gold files lack an independent Hugging Face hash confirmation. Preserve that
caveat in reports even though the checked-in manifest makes transport itself
immutable and reproducible.

The pinned public NeMo Gym recipe does not require a search key. The checked-in
configs intentionally set `tools.require_brave_search = true` as an
SFT-compatibility extension because the UniPat Kimi-K3 trajectories include
`web_search`. Export `BRAVE_API_KEY` in the launch environment and never place
it in TOML or retained artifacts. Preflight must exercise the provider and run
metadata must record the added capability. A separate no-search config may set
the flag to false; in that mode an ambient Brave key must not silently enable
search. The pinned GitHub asset transport requires no `HF_TOKEN` or
`HUGGING_FACE_HUB_TOKEN`.

Keep the policy-facing SFT compatibility aliases narrow and explicit. With
`tools.sft_compatibility_aliases = true`, `code_exec` and canonical `run_shell`
must use the same sandbox executor, `/home/user` must resolve to `/workspace`
alongside the existing `/working_dir` alias, and `finish.summary` may alias
canonical `finish.reason`. Conflicting values must fail; matching values are
canonicalized to `reason`. Resolve submitted `/home/user` paths against
`/workspace` for validation, rendering, and artifact capture. The canonical
interface remains available alongside the aliases.

Keep `tools.web_fetch_trust_env = false` on Slurm CPU nodes. Their inherited
HTTP(S) proxy points to a node-local address that is unreachable from the CPU
allocation. The runner uses a scoped Stirrup `httpx.AsyncClient` with this
setting and leaves the process environment unchanged for unrelated transports.
The full preflight must semantically fetch `https://example.com/` through that
same provider and retain the proxy-variable names (never their values); dispatch
and audit require the successful fetch record. With search enabled, it must run
a real Brave query and verify the `fetch_web_page` and `web_search` tool set. In
no-search mode it must instead prove that an ambient Brave key cannot enable
search. It must always verify that an invalid model-supplied URL is returned as
a failed tool result instead of terminating the rollout. This is a narrow
backport of Stirrup main's URL validation around the pinned v0.1.12 provider.

The checked-in configuration uses Kimi pairwise scoring against the pinned
dataset's public human-expert deliverables at Elo 1000. It excludes missing-gold
and Kimi-invisible audio/video, PSD, and STEP tasks, plus the truncated
`PrivateCrypMixV2.zip`, yielding a documented 178/220 subset. Office files must
be rendered in the VM before teardown and the Kimi endpoint must pass the PNG
multimodal probe. Use the comparison example for additional model-reference
directories, with every anchor explicit.

Validate endpoints independently from the sandbox before a smoke run:

```bash
uv run --project user/tianhaowu/gdpval_vmvm python \
  user/tianhaowu/gdpval_vmvm/probe_runtime.py \
  user/tianhaowu/gdpval_vmvm/nemotron_super_kimi.toml --endpoints-only
```

Then run the full probe without `--endpoints-only`. A valid GDPval image must
match the pinned NVIDIA dependency surface and include LibreOffice; do not fall
back to VMVM's generic `code_exec:full` image merely because it starts. The
checked-in image is a Docker translation of NVIDIA Gym's pinned `gdpval.def`:
`docker.io/tianhao0122/optimbench-tb@sha256:31aa69a13dee68d525e49748d937f9a26b05e24aff769f5348b83902f34014df`.
It was freshly pulled and validated at 11.64 GB unpacked, so use the standard
VMVM tier with `preload_image = false` while `repo_rlef` reports no healthy
containers. Its Dockerfile, base-image pins, package-freeze hash, and image
digest are retained for provenance. The successful full-preflight JSON is
content-addressed inside the run and must match the config fingerprint,
deployment IDs, Nemotron context/server version, and OCI image. A fresh dispatch
also verifies that endpoint metadata did not change after the preflight. Keep
`policy.slurm_job_id` and `judge.proxy_jobid` explicit. Their deployment IDs
must encode those values; resolution must confirm the live Slurm job name,
node, and URL plus the judge proxy-info ID, model, and URL. Environment or CLI
overrides may only restate the same deployment. Preflight, endpoint sessions,
and run metadata retain these public runtime IDs but never API keys.
Set `GDPVAL_TASK_ID` on a smoke run to render that task's input during the full
preflight. `GDPVAL_SKIP_RUNTIME_PROBE=1` is only for a judge-only resume with complete
cached candidates/rendered inputs and a prior full preflight; the batch script
still runs a fresh Kimi text-and-vision probe.

If judge rendering or protocol code changes, its semantic fingerprint changes
and the old output directory must remain frozen. Import persisted candidates
into a new run instead:

```bash
uv run --project user/tianhaowu/gdpval_vmvm python \
  user/tianhaowu/gdpval_vmvm/run_eval.py \
  user/tianhaowu/gdpval_vmvm/nemotron_super_kimi.toml \
  --output-dir NEW_OUTPUT \
  --candidate-source-run OLD_OUTPUT \
  --limit 1 --workers 1 --preflight-file NEW_PREFLIGHT.json
```

The default missing-candidate policy is `error`. Use
`--missing-candidate-policy generate` only to generate candidates that are
genuinely absent from the source; a corrupt or incompatible persisted candidate
is always fatal. The import requires equal generation fingerprints across the
source, benchmark, policy, tools, runtime, rollout code, dependencies, sandbox,
and VMVM backend. The prepared catalog's provenance sidecar is mandatory: its
dataset revision, parquet and catalog digests, release shape, transport, and
asset-mirror identity are verified, snapshotted, and hash-bound into the run
plan, metadata, and source bundle. Source preflight validation intentionally
uses only generation evidence (policy, tools, scoped web fetch, sandbox, and
asset cache); judge-only probe fields and later preflight schema additions do
not invalidate a generation-compatible candidate. The import copies candidates
atomically, retains each original
`candidate.json` in a hash-bound receipt plus a content-addressed source bundle under
`candidate_imports/`, and gives the copied marker only the new scorer
fingerprint and an import receipt. Audit must validate that chain without
depending on the original source directory. Keep the source-missing set frozen
across resumes even after the target run generates those absent candidates;
validate the generated target candidate separately instead of removing its key
from source provenance.

Search capability, tool schemas, path aliases, and policy prompt changes are
generation-relevant. The complete `[tools]` table is included in the semantic
and generation fingerprints. Such a migration requires a fresh output directory
and regenerated candidates; do not use `--candidate-source-run` to import from
an older no-search or pre-alias run.

Run VMVM probes and evaluations from a CPU Slurm allocation. The interactive
Codex container cannot expose the VM lease's SSH tunnel even when allocation
succeeds; `run_eval.sbatch` already provides the required CPU-node context.

## Recovery invariants

- Transparently recover only VMVM `broken_pipe`, using `restart_session()` then
  `recover_last()`. Never resend an uncertain stateful command.
- Retry a full rollout only when VM/container state was confirmed lost before
  a candidate was durably persisted.
- A persisted candidate is immutable. Judge transport recovery retries only the
  judge against that exact candidate. Every judge-retry worker result and attempt
  row must retain its canonical candidate path and aggregate SHA-256. Validate
  that binding before candidate import recovery, resume, and every dispatch;
  missing, corrupt, relocated, or changed candidates are fatal rather than
  permission to regenerate. Treat timeouts, connection failures, 408/409/429,
  and 5xx responses as transport failures; deterministic other 4xx responses
  remain fatal.
- A judge-protocol migration uses a new output directory and an explicit
  `--candidate-source-run`; never rewrite the source run or bypass generation
  fingerprint validation.
- Model-call retry exhaustion and the official task wall-clock are terminal and
  never resampled. Record reward zero, but withhold headline Elo because the
  public AA protocol does not define how such failures enter its private
  pairwise graph. Deterministic configuration, schema, auth, and
  malformed-protocol errors are fatal.
- Resume requires the same semantic fingerprint, snapshots, unique
  `(task_id, trial)` results, and contiguous safe attempt chains.
- Repair only a malformed final JSONL record while holding the output lock (or
  owning the per-task judge journal), and retain the recovery record. Reconcile
  an orphaned atomic worker result before dispatch so terminal outcomes are not
  resampled after a coordinator crash. Retry and fatal rows must also state their
  `failure_role` (`policy` or `judge`), and recovered stdout or kill-shaped
  summaries must be written atomically before the attempt row.
- Keep one writer per output directory and retain `.writer.lock`, candidate
  manifests, judge-call journals, worker logs, and implementation archives.

## Audit

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=OUTPUT_DIR/implementation/user/tianhaowu/gdpval_vmvm \
uv run --project user/tianhaowu/gdpval_vmvm --no-sync python -B \
  OUTPUT_DIR/implementation/user/tianhaowu/gdpval_vmvm/audit.py OUTPUT_DIR
```

Report the scoring mode, exact model and judge endpoint identities, source
pins, candidate/reference hashes, valid/invalid judge trials, raw pooled battle
counts, Elo anchors, calculated Elo, normalized score, and the official
snapshot only as a separately labeled comparison target.
