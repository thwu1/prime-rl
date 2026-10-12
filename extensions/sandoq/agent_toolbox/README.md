# Sandoq agent toolbox

This is a data-only OCI image whose `/opt/prime-agents` tree can be copied or
mounted read-only into a nested task container. It intentionally has no base
image, entrypoint, package manager, credentials, or task repository.

The first compatibility probe builds the payload from canonical x86 Linux
artifacts rather than copying executables installed on a login host:

- `fbcode//3pai_tooling/opencode:opencode-binary`
- `fbcode//3pai_tooling/pi:pi-binary` plus
  `fbsource//third-party/pi-mono:pi-assets`
- the signed `fb-muse-code` RPM, until the Muse source cell is available in the
  checkout used for the build

The resulting layout is:

```text
/opt/prime-agents/opencode/opencode
/opt/prime-agents/pi/pi
/opt/prime-agents/pi/<runtime assets>
/opt/prime-agents/muse/muse
```

The image must be pinned by manifest digest. Agent credentials and model
endpoints are supplied only at runtime and must never be placed in this image.

Prepare a new context and build it with:

```bash
./prepare_context.sh /tmp/prime-agent-toolbox-context
buildah bud --format oci -t localhost/prime-agent-toolbox:probe \
  /tmp/prime-agent-toolbox-context
```

`prepare_context.sh` refuses to reuse `/usr/local/bin` agent installations. It
materializes the OpenCode and Pi source targets with Buck and verifies the Muse
RPM signature before extracting its standalone Linux executable.

## Agent-harness reverse-tunnel probe

`run_muse_rebench.py` runs Muse Code, OpenCode, or Pi inside a real SWE-rebench
task container in `oci-runner-firecracker-small`. Select the implementation
with `--harness muse|opencode|pi`. The nested container uses host networking to
reach the guest listener at
`http://127.0.0.1:8485/v1`; four parked Sandoq WebSockets carry that traffic
back to a caller-local streaming proxy. Only that proxy holds the Muse client
certificate and connects to Model API with mTLS.

The runner requires `FIRECRACKER_KEY`, `DEV_ECR_PASSWORD`, and
`PROD_ECR_PASSWORD` in its process environment. Registry credentials use a
short-lived auth file on the guest's memory-backed `/dev/shm`, which is removed
immediately after the pulls; no real model credential or client certificate is
copied into the guest or task. Invoke it from an environment containing
`sandoq-client` and `aiohttp`:

```bash
PYTHONPATH=extensions/sandoq python \
  extensions/sandoq/agent_toolbox/run_muse_rebench.py \
  --harness opencode \
  --task-json /path/to/task.json \
  --output-dir /path/to/new-output-directory
```

Capacity 429s are retried by the maintained Sandoq client with one stable
allocation request ID (recorded in `summary.json`), so elastic pool expansion
cannot create duplicate leases. The default allocation deadline matches the
client's eight-hour retry budget. The output includes the harness-native JSONL,
its code patch, the official test patch and grader log, tunnel/proxy counters,
and verified HTTP-404 session cleanup.

After running all three harnesses against the same task and prompt, build a
self-contained HTML report plus machine-readable JSON and Markdown:

```bash
python extensions/sandoq/agent_toolbox/compare_harness_trajectories.py \
  --muse-dir /path/to/muse-run \
  --opencode-dir /path/to/opencode-run \
  --pi-dir /path/to/pi-run \
  --output-dir /path/to/comparison
```

For a Pixelcloud-ready visual report, render the normalized JSON as a
self-contained, paper-style HTML document and upload it directly:

```bash
python extensions/sandoq/agent_toolbox/render_paper_report.py \
  /path/to/comparison/comparison.json \
  /path/to/comparison/trajectory-report.html
px upload /path/to/comparison/trajectory-report.html \
  --title "Muse Spark 1.3: Harness Trajectory Comparison"
```
