# Kimi TB4 multi-provider certification

`kimi_tb4_provider_split.py` provides a fail-closed certification and merge
path for the 66-case Terminal-Bench 4 evaluation. A companion materializer
binds the two concrete configs and selectors; neither tool submits a job. The
large lane is the direct-Kimi VMVM runtime and must produce the signed capacity
evidence described below.

## Trust boundary

The checked-in Sandoq image map contains 66 immutable image pairs but no
resource requests. It is therefore not a valid selector input by itself. The
split tool accepts one private, independently reviewed composite manifest whose
SHA-256 is supplied on every invocation. The manifest has this exact shape:

```json
{
  "schema_version": 2,
  "kind": "terminal-bench-4-image-resource-manifest",
  "source": {
    "dataset_archive_sha256": "<canonical digest>",
    "dataset_content_sha256": "<canonical digest>",
    "image_manifest_sha256": "<canonical digest>",
    "task_file_sha256": "<canonical digest>"
  },
  "entries": [
    {
      "task_id": "<opaque identifier>",
      "images": {
        "agent": "<repository>@sha256:<digest>",
        "verifier": "<repository>@sha256:<digest>"
      },
      "agent_resources": {
        "cpu_count": 1,
        "memory_bytes": 1,
        "disk_bytes": 1,
        "gpu_count": 0
      },
      "verifier_resources": {
        "cpu_count": 1,
        "memory_bytes": 1,
        "disk_bytes": 1,
        "gpu_count": 0
      },
      "verifier_mode": "shared",
      "runtime_requirements": {
        "compose": false
      }
    }
  ]
}
```

The real manifest must be canonical JSON with exactly 66 unique entries. Do
not publish it or its generated selectors. The tool derives membership only
from entry order, the two resource records, and the Compose capability bit
derived from conventional files in each canonical task's `environment/`
directory. The final canonical dataset-tree digest binds those file-presence
decisions. It does not accept hand-written include/exclude lists.

The deterministic partition must be exactly:

- 31 non-Compose CPU tasks fitting the legacy Sandoq envelope at multiplier 1:
  at most 8 CPUs, 8 GiB outer memory with 2 GiB headroom, and 100 GiB free disk
  with 5 GiB headroom.
- 32 remaining CPU tasks for a large VMVM provider at multiplier 2. This lane
  includes all 11 Compose tasks; four of those otherwise fit the legacy
  resource envelope, while seven already require the large lane by resources.
- 3 GPU tasks represented by deterministic unsupported outcomes.

Sandoq is explicitly treated as not Compose-capable. Any Compose task in its
selector, cardinality change, overlap, missing entry, mutable image reference,
or resource request exceeding the large-provider minimum fails closed.

## Private materialization

Use a new mode-0700 parent and a destination that does not exist:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/kimi_tb4_provider_split.py materialize \
  --manifest /private/tb4-image-resources.json \
  --manifest-sha256 '<reviewed-sha256>' \
  --output /private/kimi-tb4-partition
```

The output directory contains three mode-0600 selectors, an aggregate partition
receipt, and a canonical `.complete.json` marker written last. That marker is
the sole publication authority on filesystems without atomic no-replace rename.
Standard output contains counts only, never task identifiers, paths, or
membership digests.

## Large-provider capacity receipt

The large-provider run requires a canonical JSON Ed25519 envelope. Its payload
is bound to the exact composite manifest, derived selector, eval identity, and
complete provider environment identity. The signed payload must attest:

- resource multiplier 2;
- at least 32 actual CPUs;
- at least 36 GiB outer memory;
- at least 105 GiB available disk;
- measurement method `in-runtime-cgroup-and-statvfs-v1`.

The server-scoped PEM public key is pinned to SHA-256
`c5c6b7d6476b78bffe56666ca353ad71b9f3a11cd9a8219cabb5a81c43f95857`.
Supplying a receipt and its own unreviewed key is not approval. The receipt's
environment object must byte-for-byte match the runtime, environment, and
provider-source fields in the run's immutable eval identity. It also binds the
exact invocation and VMVM lifecycle nonce. Its fixed eight-day interval covers
the seven-day launcher wall plus certification grace; delayed verification is
allowed, while future-issued or malformed-duration evidence is rejected.
Capacity request and receipt payloads require their private completion markers.

## Certification and merge

The launch-plan tool may also emit a `kimi-direct-tb4-diagnostic` plan so score
reproduction can proceed without waiting for a smoke checkpoint. That identity
records no smoke artifact and is deliberately ineligible for provider
certification or trace-rollout unlock. Only `kimi-direct-tb4` with the exact
bound passing smoke checkpoint can enter the certified merge below.

Run each CPU partition at pass@1 with the Kimi max-reasoning, 256K context, and
captured model-I/O contract. The legacy partition must use Sandoq with resource
multiplier 1. The large partition must use the direct-Kimi VMVM runtime with
multiplier 2 and carry the signed capacity receipt. Ordinary checkpoint-backed
TB4 identities are not treated as equivalent to direct Kimi.

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/kimi_tb4_provider_split.py certify \
  --role legacy_sandoq \
  --run-dir /private/legacy-run \
  --manifest /private/tb4-image-resources.json \
  --manifest-sha256 '<reviewed-sha256>' \
  --partition-dir /private/kimi-tb4-partition \
  --output /private/legacy-certificate.json

uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/kimi_tb4_provider_split.py certify \
  --role large_provider \
  --run-dir /private/large-run \
  --manifest /private/tb4-image-resources.json \
  --manifest-sha256 '<reviewed-sha256>' \
  --partition-dir /private/kimi-tb4-partition \
  --capacity-receipt /private/capacity.json \
  --capacity-receipt-sha256 '<reviewed-receipt-sha256>' \
  --capacity-public-key /private/capacity-authority.pem \
  --capacity-public-key-sha256 '<reviewed-key-sha256>' \
  --output /private/large-certificate.json
```

Certification obtains the run writer lock, validates the repository's saved
eval identity and referenced inputs, checks exact selector coverage, and audits
every CPU trace for completion, binary score, retained reasoning, request-graph
equivalence, and exact provider model-I/O. It also requires complete Sandoq pool
cleanup or complete VMVM lifecycle/cleanup receipt coverage.

Merge reopens both runs and repeats certification. It refuses stale or forged
summary certificates, mismatched providers, duplicate trace IDs, missing rows,
different model/deployment/source contracts, or an untrusted capacity key.

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/kimi_tb4_provider_split.py merge \
  --manifest /private/tb4-image-resources.json \
  --manifest-sha256 '<reviewed-sha256>' \
  --partition-dir /private/kimi-tb4-partition \
  --legacy-certificate /private/legacy-certificate.json \
  --legacy-certificate-sha256 '<reviewed-sha256>' \
  --large-certificate /private/large-certificate.json \
  --large-certificate-sha256 '<reviewed-sha256>' \
  --trusted-capacity-key-sha256 '<reviewed-key-sha256>' \
  --output /private/kimi-tb4-union
```

The private union contains canonical-order `results.jsonl` and an aggregate
certificate. Its score is always reported over denominator 66: the 63 CPU
outcomes plus three deterministic GPU-unsupported outcomes. A 63-task CPU-only
score is never labeled as the full TB4 pass@1 result. As in the existing Kimi
TB4 certificate, the combined CPU pass rate must remain in the independently
reviewed 4%–22% reproduction band.
