# Making a new sandoq sandbox (image → server → CRD → prod)

Step-by-step to create a **new sandoq sandbox Environment** that prime-rl recipes can use as their
sandbox backend, and deploy it to **production**. The worked example is `ram-prime-rl-sandbox` (the
default this extension targets); the files referenced live in `./sandbox/`.

A sandoq sandbox Environment is three things:
1. a container **image** (runtime deps + entrypoint),
2. an in-sandbox **server** that exposes the operation surface prime-rl needs (exec / upload / jobs), and
3. an **Environment CRD** that runs a warm pool of that image and exposes its ports.

prime-rl (via this extension's `sandoq_provider`) reaches it host→sandbox over the `exec` port — no
inbound access to the pod is required for the agent-outside path.

Prereqs: a FAIR compute node with `podman` + ECR access (for build/push), and a **devserver with
fbsource + `sandoq` CLI** (via devfeature) for the prod deploy. Keep big caches off the `/home` quota
(e.g. `export UV_CACHE_DIR=/checkpoint/$USER/.cache/uv HF_HOME=/checkpoint/$USER/.cache/hf`).

---

## 1. The in-sandbox server (operation surface)

`sandbox/exec_server.py` is a FastAPI app (one persistent bash shell + a job manager) exposing exactly
what the provider maps `prime_sandboxes` onto:

| Endpoint | Maps to (prime_sandboxes) |
|---|---|
| `POST /exec {cmd,timeout}` → `{stdout,stderr,exit_code,timed_out,shell_died}` | `execute_command` |
| `POST /reset`, `GET /healthz` | shell reset / `wait_for_creation` |
| `POST /upload {path,content_b64}` , `GET /read_file?path=` | `upload_bytes`/`upload_file` , `read_file`/`download_file` |
| `POST /start_job {cmd,env?,cwd?}` , `GET /job/{id}` | `start_background_job` , `get_background_job` |

Reuse it as-is for a general-purpose Python sandbox, or extend it (add endpoints) for a new capability.
The provider falls back to base64-over-`/exec` if an endpoint is absent, so older images still work.

## 2. Build the image + push to ECR

`sandbox/Dockerfile.prime-rl-sandbox` bakes the agent-outside deps (python + numpy/sympy/scipy/pandas +
`python-is-python3` + coreutils/procps/tar) and runs `exec_server.py` (+ ttyd) via `entrypoint.sh`, with
writable `/tmp` and `/sandbox-workspace`. For a NEW sandbox, copy it and adjust the deps/entrypoint.

Follow `sandbox/build-and-push.md` for the exact podman/ECR/proxy commands. In short (on a compute node):
```bash
cd extensions/sandoq/sandbox
podman $PODMAN_STORAGE_OPTS build --network host -f Dockerfile.prime-rl-sandbox -t <name>:v1 .
ECR=588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/ram/<name>:v1
podman $PODMAN_STORAGE_OPTS tag <name>:v1 "$ECR" && podman $PODMAN_STORAGE_OPTS push "$ECR"
```
Note the pushed `image@sha256:...` (or `:tag`); the CRD must reference it byte-for-byte.

## 3. Author the Environment CRD

`sandbox/prime-rl-sandbox.yaml` is the template. For a new env, copy it and set `metadata.name`
(DNS-1123, team-prefixed, e.g. `ram-<name>`), the `image`, the ports (`exec`:8000 + `/healthz`
readinessProbe are required — the provider talks to `exec`), `minReplicas`/`maxReplicas` (≈ steady/peak
concurrent rollouts), and `resources`.

```yaml
apiVersion: sandoq.io/v1alpha1
kind: Environment
metadata:
  name: ram-<name>                 # DNS-1123, unique across the cluster
  namespace: default               # confirm with the sandoq oncall
  annotations:
    sandoq.io/oncall: autobenchmark
    # terminal-bench.io/allow-internet: "true"   # ONLY if the env must fetch at runtime (breaks determinism)
spec:
  minReplicas: 8
  maxReplicas: 256
  template:
    containers:
    - name: environment
      image: 588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/ram/<name>:v1
      workingDir: /sandbox-workspace
      ports:
      - { containerPort: 8000, name: exec,     protocol: TCP }   # -> portUrls.exec (the provider uses this)
      - { containerPort: 7681, name: terminal, protocol: TCP }   # ttyd, optional debugging
      readinessProbe:
        httpGet: { path: /healthz, port: 8000 }
        initialDelaySeconds: 1
        periodSeconds: 2
      resources:
        requests: { cpu: "2", memory: 4Gi, ephemeral-storage: 10Gi }
        limits:   { cpu: "4", memory: 8Gi, ephemeral-storage: 20Gi }
```
The `/healthz:8000` readinessProbe gates the warm pool: if the exec server isn't healthy, create-session
returns **perpetual HTTP 429 (POOL_STARVATION)** — so the probe must point at a working server.

## 4. Deploy to prod (fbsource + Conveyor — NOT `kubectl apply`)

`kubectl apply` is oncall-only/emergency. The supported path is a landed fbsource diff picked up by the
`sandoq/deploy_environments` Conveyor pipeline. From a **devserver**:
```bash
cd ~/fbsource
mkdir -p fbcode/msl_infra/sandoq/clusters/eks-prod/default
cp <path>/prime-rl-sandbox.yaml fbcode/msl_infra/sandoq/clusters/eks-prod/default/ram-<name>.yaml
sandoq env validate fbcode/msl_infra/sandoq/clusters/eks-prod/default/ram-<name>.yaml   # same check the pipeline runs
sl add fbcode/msl_infra/sandoq/clusters/eks-prod/default/ram-<name>.yaml
sl commit -m "[sandoq] add ram-<name> environment"
sl ssl                                   # verify the commit
jf submit --draft
```
In the diff summary: the image + owner, the ECR URL+tag (so reviewers can confirm it exists), and the
replica bounds. **Tag the `sandoq` oncall.** Once accepted + landed, Conveyor deploys it — that is prod.
(Do not add reviewers the user didn't provide.) Iterating the image later: push a new tag, bump
`spec.template.containers[0].image`, land the diff; the controller recycles idle warm pods.

## 5. Verify it's live

```bash
ENV=ram-<name>; BASE=https://sandoq.eks-prod.cf.aws.metafb.cloud   # direct cluster URL
# (a) warm pool present? (needs the `meta` CLI on a devserver)
meta ods.table query --obql='ods3.from(table:"sandoq") | between(start:-1h,stop:now()) | where(environment=="'"$ENV"'") | select(max(sandoq_available_pods_total))'
# (b) lease once, confirm `exec` port + /healthz, then delete — or just run the reference client:
SANDOQ_BASE="$BASE" ENVIRONMENT="$ENV" python3 sandbox/exec_client.py     # lease → exec → delete smoke test
```
If create-session 429s forever → the image lacks a healthy exec server (readinessProbe never passes):
recheck the pushed image/tag and `GET /healthz` on :8000.

**Gateway routing gotcha:** the multi-cluster gateway (`sandoq-gateway.eks-prod…`) hashes the env name to
a cluster and can mis-route a single-cluster env (we hit `→ cua-eval-v2` → 404). Use the **direct
cluster URL** if that happens; `sandbox/gateway_misroute_repro.py` reproduces/checks it for the sandoq team.

## 6. Point a recipe at the new sandbox

In the extension config (a recipe's `.env`), select the new Environment:
```bash
export SANDOQ_DEFAULT_ENVIRONMENT="ram-<name>"
# or map specific docker_image values:
# export SANDOQ_ENV_MAP='{"python:3.11-slim":"ram-<name>"}'
```
The provider maps each env's requested `docker_image` → this sandoq Environment; the recipe otherwise
runs unchanged.

## Notes
- **Determinism vs pip.** Bake deps into the image so PythonEnv's `pip install …` is a no-op offline;
  keep `allow-internet` off for RL determinism unless an env must fetch at runtime.
- **`python` on PATH.** `python-is-python3` is mandatory (code_env / PythonEnv call bare `python`).
- **Warm-pool sizing.** `minReplicas` ≈ steady-state concurrent rollouts, `maxReplicas` ≈ peak; watch
  `sandoq_session_create_rejected_total{reason}` and raise on sustained 429s.
- **Per-session serialization.** One persistent shell per session serializes concurrent `/exec`; add
  concurrent execution to `exec_server.py` if a test-heavy env needs it.
