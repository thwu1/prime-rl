# sandoq extension — sandbox backend for prime-rl recipes

Route prime-rl's sandbox execution to Meta's **sandoq** service instead of Prime Intellect's.
This is a **reusable backend**, not a recipe: any recipe (math, code, later agentic) opts in and
its `SandboxEnv`/`PythonEnv` (v0) or `runtime="prime"` (v1) sandboxes run on sandoq.

## What's here

| Path | Role |
|---|---|
| [`sandoq_provider/`](sandoq_provider/README.md) | the `sandoq-client` lifecycle adapter plus the nested `oci-runner` client, with one shared installer for the v0 and v1 sandbox-client seams |
| `sitecustomize.py` | auto-installs the provider at interpreter startup (every worker/trainer/inference), lazily, when `VF_SANDBOX_PROVIDER=sandoq` |
| `enable.sh` | wires this extension into a recipe's `.runtime/prime-rl/.env` (PYTHONPATH + activate) |
| `sandbox/` | the sandoq Environment side: image (`Dockerfile.prime-rl-sandbox`), in-sandbox server (`exec_server.py`), CRD (`prime-rl-sandbox.yaml`) |
| `MAKING_SANDBOXES.md` | step-by-step: build a new sandoq sandbox image → push to ECR → land the CRD → deploy to prod |

## How it works (no prime-rl edits)

`sitecustomize.py` is imported by Python's `site` machinery at startup in **every** process on the
recipe's runtime. When `VF_SANDBOX_PROVIDER=sandoq` it installs a one-shot meta-path hook that runs
`sandoq_provider.install()` the moment the app first imports a sandbox-client seam. `install()` rebinds:
- **v0**: `verifiers.utils.threaded_sandbox_client.AsyncSandboxClient` (+ the two sync teardown sites).
- **v1**: `prime_sandboxes.AsyncSandboxClient` / `SandboxClient` / `core.APIClient` (which
  `verifiers/v1/runtimes/prime.py` imports function-locally).

Because it's a startup hook on `PYTHONPATH` (not an edit to prime-rl), it works across all env-server
workers and survives runtime regeneration. Processes that never touch sandboxes pay nothing (lazy).

Session create, lookup, renewal, deletion, and proxied-port requests all use one
pinned official `sandoq-client` and its pooled `Http` facade. OCI bearer headers
remain scoped to `/v1/exec` and `/v1/shells`; lifecycle URLs are restricted to
the client's typed lifecycle methods. Deletion is considered complete only when
the official client returns the typed session-not-found response.

The official client owns transport selection. It prefers an ambient proxy when
one is explicitly configured, otherwise selects a DNS-verified DSS3/4 AWS or
CoreWeave profile, the corp profile, or direct access. Recipe hooks do not set
proxy or certificate variables. Direct mode is expected on hosts such as
`fair-sc-3`; `fair-sc` should resolve a DSS3/4 proxy with mTLS.

`docker_image` values (e.g. `python:3.11-slim`) map to a deployed sandoq Environment via
`SANDOQ_ENV_MAP` (+ `*` fallback → `SANDOQ_DEFAULT_ENVIRONMENT`, default `ram-prime-rl-sandbox`).
When `VF_SANDBOX_PROVIDER=oci-runner`, the row's `docker_image` is instead pulled
inside a direct `eks-prod` lease of Sandoq's managed
`oci-runner-firecracker` environment and started with Podman using the
microVM's native runtime and no inner-container network. The legacy
`oci-runner` rollback path retains gVisor. Pulls launch in the background and
are polled through short authenticated requests, so Sandoq's synchronous proxy
deadline does not bound pull duration. Sandoq owns the environment image and
deployment.

## Make your recipe use sandoq

1. Include `../../extensions/sandoq/requirements.txt` from the recipe's
   `requirements.txt`, then source `../../extensions/sandoq/vault_env.sh`
   immediately before `recipe_install.sh`. This resolves the exact official
   client pin from Vault in the same transaction as the recipe dependencies;
   the discovered certificate variables are not written to the runtime `.env`.
2. In your recipe's **`install.sh`** (custom, like `aira/`), after `recipe_install.sh` runs, call:
   ```bash
   "$HERE/../../extensions/sandoq/enable.sh" "$HERE/.runtime/prime-rl"
   ```
3. In your recipe's **`.env`**, pick the Environment + keep big caches off the /home quota:
   ```bash
   export SANDOQ_BASE_URL="https://sandoq-gateway.eks-prod.cf.aws.metafb.cloud"
   export SANDOQ_DEFAULT_ENVIRONMENT="ram-prime-rl-sandbox"
   # export SANDOQ_ENV_MAP='{"python:3.11-slim":"ram-prime-rl-sandbox"}'
   ```
4. Use a sandbox env in your `rl.toml` (v0 `id=`/`PythonEnv`, or v1 `runtime={type="prime"}`).

See `recipes/sandoq_math_python/` for a complete working example.

## Configuration (env vars, read by `sandoq_provider.config`)

| Var | Default | Purpose |
|---|---|---|
| `VF_SANDBOX_PROVIDER` | `prime` | set to `sandoq` to activate (enable.sh sets it) |
| `SCENV` / `USER` | ambient | inputs used by `sandoq-client` for DNS-verified DSS3/4 profile and credential discovery |
| `HTTPS_PROXY` / `HTTP_PROXY` | unset | optional operator-owned ambient proxy; never set by recipe hooks |
| `THRIFT_TLS_CL_CERT_PATH` / `THRIFT_TLS_CL_KEY_PATH` | client-discovered | optional explicit mTLS pair consumed by `sandoq-client` |
| `SANDOQ_BASE_URL` | eks-prod cluster gateway | sandoq API base |
| `SANDOQ_DEFAULT_ENVIRONMENT` | `ram-prime-rl-sandbox` | fallback Environment name |
| `SANDOQ_ENV_MAP` | `{}` | JSON `docker_image → env` (`"*"` = fallback) |
| `SANDOQ_LEASE_DURATION` / `SANDOQ_RENEW_MARGIN` / `SANDOQ_CREATE_DEADLINE` / `SANDOQ_OWNER` | see `config.py` | lease/renew/timeout/owner |
| `OCI_RUNNER_BASE_URL` / `OCI_RUNNER_ENVIRONMENT` | direct eks-prod / `oci-runner-firecracker` | outer OCI lease |
| `OCI_RUNNER_TOKEN_FILE` | `~/.config/oci-runner/firecracker-token` | Firecracker bearer token; must be a regular mode-`0600` file |
| `OCI_RUNNER_DOCKERHUB_USERNAME` / `OCI_RUNNER_DOCKERHUB_TOKEN_FILE` | unset | authenticated Docker Hub pulls; PAT file must be mode `0600` |
| `OCI_RUNNER_REQUIRE_DOCKERHUB_AUTH` | unset | set to `1` to prohibit anonymous pull fallback |
| `OCI_RUNNER_ECR_REGISTRY` / `OCI_RUNNER_ECR_REGION` | unset / `us-east-2` | ECR pull-through and FAIR `ucloud` authentication |
| `OCI_RUNNER_ECR_AUXILIARY_REGISTRIES` | unset | Extra AWS ECR hosts to authenticate without pull-through rewriting |
| `OCI_RUNNER_ECR_CLIENT_CERT_PATH` | auto-discovered | optional FAIR x509 PEM scoped to the `ucloud` subprocess |
| `OCI_RUNNER_OBSERVABILITY` | unset | opt-in OCI stage timings and typed stage failures |
| `OCI_RUNNER_POOL_SIZE` / `OCI_RUNNER_POOL_MIN_SIZE` | `32` / `0` | job-local outer-session pool bound and prewarm target |
| `OCI_RUNNER_POOL_RENEW_INTERVAL` / `OCI_RUNNER_POOL_RENEW_WORKERS` | min(lease / 3, 10m) / `16` | bounded-parallel outer-lease renewal sweep |
| `OCI_RUNNER_SESSION_REUSE` | `1` | set to `0` for the one-outer-session-per-rollout rollback path |

## Status & scope

- **v0 agent-outside** (LLM in orchestrator, tool exec in sandbox): works today, no reverse tunnel.
  Validated end-to-end for Python tools (`recipes/sandoq_math_python`) and SWE-rebench V2 GRPO
  training (`recipes/sandoq_swerebench_v2_oci`).
- **v1 `runtime="prime"`**: the exec client seam is covered. The
  `sandoq_swerebench_v2_oci` reverse-tunnel trial also runs its mini-SWE-agent
  inside a nested Firecracker task container and routes model traffic back to
  the caller's interception server through the session's `tunnel` port.
