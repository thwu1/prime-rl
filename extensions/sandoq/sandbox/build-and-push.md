# Build & Push: `ubuntu-terminal` image → Cloud Foundation dev ECR

A concrete, tested runbook for building the container image from the `Dockerfile`
and pushing it to the SandoQ dev registry. Commands below are the ones that
**actually worked** on a FAIR compute node (they diverge from the generic SandoQ
runbook — see notes).

Files in this directory:

| File | Purpose |
|---|---|
| `Dockerfile` | Recipe for the **image** (what you build + push). Builds **both** servers. |
| `exec_server.py` | Structured exec API (FastAPI): `POST /exec` → `{stdout,stderr,exit_code,…}`. |
| `entrypoint.sh` | Launches `ttyd` (:7681) **and** the exec API (:8000) in one container. |
| `ubuntu-terminal.yaml` | SandoQ **Environment CRD** — the *deploy* manifest (not used by build/push). |
| `sandoq_test.sh` | Leases a session via the API (bash). |
| `exec_client.py` | Leases a session and drives `/exec` end-to-end (pure-stdlib python). |
| `build-and-push.md` | This runbook. |

Concrete values used here (change the **TEAM** / oncall if yours differ):

| Thing | Value |
|---|---|
| Team prefix | `ram` |
| ECR account | `588845226011` (Cloud Foundation **dev** registry) |
| Region | `us-east-2` |
| Image ref | `588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/ram/ubuntu-terminal:v2` (v1 = terminal-only; v2 adds the exec API) |
| Build host | inside CPU slurm job (compute node) |

---

## Why are there two files? (Dockerfile vs YAML)

They do **completely different jobs** and are used at **different times**:

- **`Dockerfile` → builds the image.** It's the recipe: base OS + packages +
  entrypoint. `podman build` turns it into an image, and `podman push` uploads
  that image to ECR. **Build and push only ever touch the Dockerfile.**

- **`ubuntu-terminal.yaml` (the Environment CRD) → runs the image.** It's the
  *deployment* descriptor that SandoQ reads **later** (validate + deploy step) to
  actually run your pushed image as a service: how many replicas, CPU/memory,
  and — crucially — **which container port to expose through the gateway proxy**.
  It is **not** consumed during build or push.

The one link between them is the **`image:` field** in the YAML, which must be
**byte-for-byte equal** to the tag you push:

```
# Dockerfile  --build+push-->  588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/ram/ubuntu-terminal:v2
#                                                        ▲
#                                                        │ must match exactly
# ubuntu-terminal.yaml:  spec.template.containers[0].image: ─┘
```

So: you could build+push with no YAML at all — but then nothing would run it.
The YAML is "needed" because pushing an image only *stores* it; the CRD is what
makes SandoQ pull that image and serve it. Our v2 image runs **two** servers, so
the CRD exposes **two** ports: `ttyd` on `7681` (name `terminal` → `portUrls.terminal`,
human browser terminal) and the exec API on `8000` (name `exec` → `portUrls.exec`,
structured JSON for scripts/agents).

---

## Prerequisites

- A CPU slurm job you can exec into (`srun --jobid <ID> --pty bash`).
- System `podman` at `/usr/bin/podman` (a conda/`~/.local` podman 5.x will break — VFS/cgroups mismatch).
- `ucloud` + `aws` CLIs on the node.
- Entitlement to the **`SSOContainerRegistryReadWrite`** role in account `588845226011`
  (everyone has `…ReadOnly` = pull; you need `…ReadWrite` to push).

---

## Step 0 — open a shell in the job

Everything must run in **one shell** (the podman-storage and ECR-token env vars
have to persist across build → auth → push).

```bash
srun --jobid 8598333 --pty bash
# if "step creation temporarily disabled": add --overlap
# srun --jobid 8598333 --overlap --pty bash
```

## Step 1 — configure podman for the compute node

NFS home can't back overlay/pivot_root, so point podman at `/var/slurm-tmp` with
the VFS driver. Paste as a block:

```bash
export PODMAN_STORAGE_DIR="/var/slurm-tmp/podman-$USER"
mkdir -p "$PODMAN_STORAGE_DIR"/{storage,run,run-xdg,docker-config}
chmod 700 "$PODMAN_STORAGE_DIR"
export PODMAN_STORAGE_OPTS="--storage-driver vfs --root $PODMAN_STORAGE_DIR/storage --runroot $PODMAN_STORAGE_DIR/run"
export XDG_RUNTIME_DIR="$PODMAN_STORAGE_DIR/run-xdg"; chmod 700 "$XDG_RUNTIME_DIR"
export CONTAINERS_CONF="$PODMAN_STORAGE_DIR/containers.conf"
printf '[containers]\npidns = "host"\ndefault_sysctls = []\nkeyring = false\n' > "$CONTAINERS_CONF"
# avoid broken credHelpers in ~/.docker/config.json on compute nodes
export DOCKER_CONFIG="$PODMAN_STORAGE_DIR/docker-config"
[ -f "$DOCKER_CONFIG/config.json" ] || echo '{}' > "$DOCKER_CONFIG/config.json"
```

`$PODMAN_STORAGE_OPTS` is prepended to **every** podman command below.

## Step 2 — verify architecture (must match the target cluster = amd64)

```bash
uname -m        # want x86_64
```

If this is `aarch64`, the resulting image is arm64 and **won't schedule on an
amd64 cluster** (eks-dev/eks-prod) — build on an x86_64 node instead.

## Step 3 — build the image from the Dockerfile

```bash
cd /storage/home/kulikov/sandoq_ubuntu_terminal
podman $PODMAN_STORAGE_OPTS build --network host -t ubuntu-terminal:v2 .
```

If the `FROM ubuntu:22.04` pull or `apt-get` fails with **network** errors, retry
through the proxy:

```bash
with-proxy podman $PODMAN_STORAGE_OPTS build --network host \
  --build-arg HTTP_PROXY --build-arg HTTPS_PROXY --build-arg http_proxy --build-arg https_proxy \
  -t ubuntu-terminal:v2 .
```

Confirm the built image's arch is amd64:

```bash
podman $PODMAN_STORAGE_OPTS image inspect ubuntu-terminal:v2 --format '{{.Architecture}}'
```

## Step 4 — authenticate to ECR with the **write** role

> This is the part that differs most from the generic runbook. On this host
> `ucloud ecr get-credentials` only mints the **read-only** token and has no
> `--role`. The write role comes from **`ucloud aws get-credentials`**, where the
> account is a **positional** argument (not `--account`).

```bash
# assume the ReadWrite role and load temp AWS creds into the shell env
eval "$(ucloud aws get-credentials --role SSOContainerRegistryReadWrite 588845226011)"

# exchange those creds for a 12h ECR token and log podman in
aws ecr get-login-password --region us-east-2 \
  | podman $PODMAN_STORAGE_OPTS login -u AWS --password-stdin \
    588845226011.dkr.ecr.us-east-2.amazonaws.com
```

Expect `Login Succeeded!`. Token is valid ~12h; re-run this block on a later
`401`/`denied`.

<details>
<summary>Alternative: a scratch AWS profile via <code>credential_process</code></summary>

```bash
cat > "$PODMAN_STORAGE_DIR/aws-config-rw" <<'EOF'
[profile ecr-rw]
credential_process = ucloud aws get-credentials --role SSOContainerRegistryReadWrite 588845226011
region = us-east-2
EOF
AWS_CONFIG_FILE="$PODMAN_STORAGE_DIR/aws-config-rw" AWS_PROFILE=ecr-rw \
  aws ecr get-login-password --region us-east-2 \
  | podman $PODMAN_STORAGE_OPTS login -u AWS --password-stdin \
    588845226011.dkr.ecr.us-east-2.amazonaws.com
```
</details>

## Step 5 — tag for ECR and push

The repo under `msl_infra/` is auto-created on first push.

```bash
ECR=588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/ram/ubuntu-terminal:v2
podman $PODMAN_STORAGE_OPTS tag ubuntu-terminal:v2 "$ECR"
podman $PODMAN_STORAGE_OPTS push "$ECR"
```

Success looks like:

```
Copying blob ... done
Copying config ... done
Writing manifest to image destination
Storing signature
```

## Step 6 — verify it landed in ECR

```bash
aws ecr describe-images \
  --repository-name msl_infra/ram/ubuntu-terminal --region us-east-2 \
  --query 'imageDetails[].{tags:imageTags,pushed:imagePushedAt}' --output table
```

The image ref is now ready to reference from `ubuntu-terminal.yaml` for the
validate + deploy phase.

---

## What the v2 image runs

The v2 image starts **two** servers via `entrypoint.sh` (under `tini`):

- **ttyd** on `:7681` → `portUrls.terminal` — interactive browser terminal.
- **exec API** on `:8000` → `portUrls.exec` — `exec_server.py`, structured JSON.

They are **independent bash sessions** (separate cwd/env) that share the pod's
filesystem/network. The CRD declares both ports plus a `readinessProbe` on
`/healthz:8000`, so SandoQ only serves a pod once the exec API is live.

## Step 7 — redeploy after an image change

Pushing a new image does **not** update running pods by itself. Re-apply the CRD;
the controller's reconciler sees the new image digest and **recycles** the warm
pool to it (idle pods are replaced). Deploy mechanism is the open question — your
`kubectl` context or the SandoQ oncall:

```bash
sandoq env validate ubuntu-terminal.yaml            # if the CLI is present
kubectl --context <cluster> apply -f ubuntu-terminal.yaml
```

## Exec API — structured command execution

Endpoints (relative to `portUrls.exec`, which ends in `/`):

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `exec` | `{"cmd":"…","timeout":60}` | `{stdout, stderr, exit_code, duration_s, timed_out, shell_died}` |
| POST | `reset` | — | `{"status":"reset"}` (fresh shell) |
| GET | `healthz` | — | `{"status":"ok","shell_alive":true}` |

State (cwd, env) **persists across calls** — one persistent bash per session.
Commands are serialized (one at a time); for parallelism, lease more sessions.

Manual test (after a lease; `$BODY` is the create-session response):

```bash
EXEC=$(echo "$BODY" | jq -r '.portUrls.exec')
curl -sS "${EXEC}healthz"; echo
curl -sS -X POST "${EXEC}exec" -H 'Content-Type: application/json' \
  -d '{"cmd":"cd /tmp && echo hi > f.txt && ls -l f.txt"}' | jq .
curl -sS -X POST "${EXEC}exec" -H 'Content-Type: application/json' \
  -d '{"cmd":"pwd && cat f.txt"}' | jq .        # state persisted
```

Or run the end-to-end client (lease → exec ×3 → delete; pure stdlib):

```bash
python3 exec_client.py
# target another env/cluster via env vars:
BASE=https://sandoq.eks-prod.cf.aws.metafb.cloud ENVIRONMENT=ram-ubuntu-terminal python3 exec_client.py
```

Security: the exec API is **unauthenticated** — the session lease is the boundary
(same model as ttyd's empty token). `exit` inside a command kills the shell
(`shell_died:true`), which then respawns; `set -e` persists — use `reset` to clear.

---

## Troubleshooting (errors we actually hit)

| Symptom | Cause | Fix |
|---|---|---|
| `ODS3 SDK ... Failed to obtain region 'DEVICE_REGION'` + `Connection refused` | `ucloud` telemetry flushing on process teardown (fbwhoami not populated on compute nodes) | Harmless noise on **stderr**. Ignore, or append `2>/dev/null` to the `ucloud` call. |
| `podman login` prints `Password:` then `inappropriate ioctl for device` | The piped token was **empty** (the `get-credentials` command errored and its output was hidden by `2>/dev/null`), so podman fell back to an interactive prompt with no TTY | Run the credential command **without** `2>/dev/null` to see the real error; make sure it emits creds/token before piping. |
| `denied: User: .../SSOContainerRegistryReadOnly/... not authorized ... ecr:InitiateLayerUpload` | Logged in with the **read-only** role | Use `ucloud aws get-credentials --role SSOContainerRegistryReadWrite 588845226011` (Step 4). |
| `ucloud ecr get-credentials ... -r ...` produces nothing | `-r/--role` is **not** a flag on `ecr get-credentials` | Role selection lives on `ucloud aws get-credentials`. |
| `error: unexpected argument '--account' found` | `get-credentials` takes the account as a **positional** arg | `ucloud aws get-credentials --role <ROLE> 588845226011` (no `--account`). |
| `Found podman at ~/.local/... instead of /usr/bin/podman` | conda/user podman 5.x on PATH | `export PATH=/usr/bin:$PATH` (or remove it). |
| `/exec` returns `shell_died:true, exit_code:null` | the command ran `exit` or crashed bash | expected — the shell auto-respawns; re-send the command. |
| `/exec` returns `timed_out:true` | command exceeded `timeout` | expected — shell was killed+respawned; raise `timeout` or fix the command. |
| exec URL 404 / connection refused right after lease | pod not ready yet | rely on the `readinessProbe`, or poll `GET /healthz` before `/exec`. |

## Re-auth quick reference

```bash
eval "$(ucloud aws get-credentials --role SSOContainerRegistryReadWrite 588845226011)"
aws ecr get-login-password --region us-east-2 | podman $PODMAN_STORAGE_OPTS login -u AWS --password-stdin \
  588845226011.dkr.ecr.us-east-2.amazonaws.com
```
