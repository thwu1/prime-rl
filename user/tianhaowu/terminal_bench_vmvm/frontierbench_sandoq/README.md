# FrontierBench Sandoq launchers

All non-secret paths, endpoints, limits, and concurrency values live in
`frontierbench.env`. Secrets are referenced by owner-only files and are never
stored in Git.

Edit only `frontierbench.env` when a server, token-file path, dataset, resource
limit, timeout, provider profile, or concurrency changes. Both launchers source
that file, verify the pinned inputs, and refuse partial or dirty setups.
Oracle output directories are revision-scoped, so a new source commit cannot
silently reuse an incompatible prior run; same-revision retries resume invalid
rows in place. The env file pins the currently validated smoke output explicitly
so launcher-only follow-ups do not orphan its certificate.

From a clean `vmvm-sandbox` checkout on the login host:

```bash
# Build missing digest-pinned images in Sandoq, then submit the oracle.
bash user/tianhaowu/terminal_bench_vmvm/frontierbench_sandoq/launch_oracle.sh smoke
bash user/tianhaowu/terminal_bench_vmvm/frontierbench_sandoq/launch_oracle.sh full

# After the matching oracle finishes, run MiniSWE-Agent 2.4.6 with retained
# model I/O and reasoning. The optional second argument is smoke or full.
bash user/tianhaowu/terminal_bench_vmvm/frontierbench_sandoq/launch_model.sh qwen smoke
bash user/tianhaowu/terminal_bench_vmvm/frontierbench_sandoq/launch_model.sh qwen full
bash user/tianhaowu/terminal_bench_vmvm/frontierbench_sandoq/launch_model.sh kimi full
```

The model smoke is one oracle-passed task and exactly three MiniSWE-Agent steps.
Its timeout values are explicit in the env file and allow for the observed Kimi
latency. Full runs use the 256K context cap and retain captured model I/O,
including reasoning. The runtime buffers each guest SSE request into an exact
provider response before synthesizing SSE back to MiniSWE, retaining provider
usage and reasoning fields in the stored trace.

The staged dataset contains 294 eligible tasks. Six security-name-matched task
directories were excluded before staging and are not opened by these launchers.
The launchers fail closed on a changed dataset digest, an incomplete image
manifest, unsafe token permissions, or a dirty source checkout. Image builds
resume from exact successful receipts, retry each missing row three times, and
publish success only after the disposable build session is verified deleted.

The current Firecracker profile is qualified for 2 CPU, 4 GiB memory, and
10 GiB disk per nested task. The oracle launcher caps each agent and separate
verifier dimension independently to `min(declared, qualified limit)`, binds the
caps into the immutable run identity, and submits all 294 eligible tasks. The
285 non-Compose tasks use Sandoq; the nine Compose tasks terminate explicitly as
unsupported rather than being silently run without their services. Because 285
is above the 265-pass acceptance floor, this lane can still satisfy the 90%
corpus gate. A separate Compose-capable provider lane is required to validate
those nine tasks.
