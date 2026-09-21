# Sandoq sandbox provider

This package lets Prime-RL environments execute tools in Sandoq sandboxes
without changing Prime-RL or Verifiers.

It supports two transports:

| Provider value | Use case |
|---|---|
| `sandoq` | Existing recipes that use a deployed Sandoq environment such as `ram-prime-rl-sandbox` |
| `oci-runner` | Coding tasks that provide a different OCI image for each dataset row |

The legacy `sandoq` transport remains the default for existing Sandoq recipes.
The OCI transport is used only when a recipe explicitly sets
`VF_SANDBOX_PROVIDER=oci-runner`.

## OCI-runner in plain language

Each rollout receives its own isolated nested sandbox:

1. A job-local broker lends one of the configured logical slots from Sandoq's
   managed `oci-runner` environment. Lease creation, bootstrap admission, and
   final deletion each have independent concurrency bounds.
2. It reads the task's image name from the sandbox request.
3. The provider resolves Docker Hub references through the configured ECR
   pull-through cache, authenticates Podman with a short-lived credential,
   launches the pull in the background inside the outer session, and polls its
   status with short authenticated requests. Direct Docker Hub authentication
   remains available as a rollback path.
4. Podman starts one nested container with the task's verified CPU,
   memory/swap, and PID limits. Firecracker normally uses Podman's native
   runtime with networking disabled. An agent-inside rollout explicitly selects
   `OCI_RUNNER_TASK_NETWORK=host` so the nested container shares the guest
   loopback and can reach the Sandoq reverse tunnel. The legacy `oci-runner`
   rollback path retains gVisor `runsc` and its existing network setup.
   Disk is admitted with 5 GiB headroom and measured, but is not described as a
   hard quota under `vfs`.
5. The runner starts one managed Bash through its persistent-shell API. Trusted
   recipe bootstrap establishes its cwd, environment, and Conda activation;
   model commands run in contained child Bash processes.
6. The official task tests run against the final repository state.
7. The broker deletes the shell and nested container, verifies assignment files
   are gone, and returns the outer session to the pool. On final drain it deletes
   every outer session and confirms HTTP 404.

Different rollouts never share an active outer slot or writable nested
container. Four parallel rollouts occupy four distinct slots. A recycled slot
retains only its bounded image cache; failed cleanup poisons and deletes it.
The broker also retires a clean outer after a bounded number of assignments so
storage, process, and runtime state cannot accumulate for the full training run.

## Commands and files

Outer Sandoq lease lifecycle calls are serialized through a process-scoped
`SandoqGatewayAdapter`, which owns one official `SandoqClient` on a dedicated
asyncio loop thread. Generic exec traffic, OCI command and managed-shell
traffic, and pool cleanup use that same client's pooled public `Http` facade.
The adapter returns HTTP status/body pairs to preserve caller-specific timeout,
poisoning, retry, redaction, and cleanup decisions.

Transport selection and CA fallback remain inside `sandoq-client`. The adapter
uses only public `Http.proxy_url` and `Http.ssl_context` properties for redacted
preflight diagnostics; it does not mutate client transport globals or export
runtime proxy and certificate settings.

The model sees a normal `bash` tool. A command such as:

```bash
pytest tests/test_example.py
```

is sent to `/v1/exec` as
`{"command":["bash","-c",command],"shellId":...}`. A child command can modify
the filesystem and launch normal child processes, but its `cd`, exports,
functions, aliases, traps, and shell options end with that call. Only trusted
recipe bootstrap may use direct argv to establish managed cwd, environment, and
Conda state. Sandoq's `workdir` and `env` fields carry recipe-managed values;
rollout tools start in the validated `OCI_EXPECTED_WORKDIR` supplied by the
recipe (default `/testbed` for V1). HTTP 502/503/504 responses make the command
outcome unknown, so the assignment is poisoned and the command is never
replayed. A terminal 404/410 is also never replayed except for the narrowly
attested long-Kimi missing-managed-shell recovery described below. Only a
transport failure proven not to have sent the request is otherwise eligible
for a bounded replay.

Trusted transfer steps and recipe status probes are explicitly idempotent, but
they still retry only failures classified as pre-delivery. Exhaustion raises
`OCIRunnerTransientGatewayError` with the operation, status, attempts, timings,
and eventual cleanup result. Ambiguous transport failures and terminal HTTP
responses are never replayed.

Managed shells have a documented idle TTL of 1,800 seconds. The provider does
not send speculative keepalives.  For the sealed long-Kimi lease profile, a
definitive shell-command HTTP 404/410 is recoverable only when both outer health
and the authenticated shell inventory remain HTTP 200 and that inventory proves
the old shell ID absent.  The pool broker serializes recovery with commands and
release, creates one replacement shell, restores the validated workdir, records
the transition durably, and permits exactly one replay of the rejected command.
Ambiguous transport failures, timeouts, and 5xx responses are never recovered or
replayed by this path. The shell binding/replacement WAL records are emitted only
for that closed long-Kimi profile, leaving the standard/Qwen WAL byte contract
unchanged.

Uploads and downloads use the authenticated outer command server and the shared
mount:

```text
Prime-RL process
  -> outer /home/runner/shared
  -> nested /shared
  -> requested path inside the task container
```

Podman performs the image pull and container lifecycle. It is not being used as
an HTTP client.

Image pulls use fire-and-poll rather than holding one `/v1/exec` request open:
the launch call returns immediately, the outer runner writes an atomic return
code when Podman finishes, and the provider polls that file every two seconds.
Each assignment proceeds as soon as its own image is ready; there is no global
pool barrier. Pull, ECR fallback, digest inspection, nested startup, and
validation share `OCI_RUNNER_PULL_TIMEOUT`; recursive fallback receives the
same deadline. Each registry source gets at most one retry after typed transient
exhaustion, and every gateway timeout and retry sleep is clamped to the shared
deadline.

## Configuration

A recipe activates the OCI transport with:

```bash
export VF_SANDBOX_PROVIDER="oci-runner"
export OCI_RUNNER_ENVIRONMENT="oci-runner-firecracker"
export OCI_RUNNER_TOKEN_FILE="$HOME/.config/oci-runner/firecracker-token"
export OCI_RUNNER_DOCKERHUB_USERNAME="<docker-hub-user>"
export OCI_RUNNER_DOCKERHUB_TOKEN_FILE="$HOME/.config/oci-runner/dockerhub-token"
export OCI_RUNNER_REQUIRE_DOCKERHUB_AUTH="1"

# Docker Hub pull-through via Cloud Foundation production ECR.
export OCI_RUNNER_USE_ECR="1" # filtered recipe default; set 0 for Docker Hub rollback
export OCI_RUNNER_ECR_REGISTRY="168653207203.dkr.ecr.us-east-2.amazonaws.com"
export OCI_RUNNER_ECR_REGION="us-east-2"
export OCI_RUNNER_ECR_PULL_THROUGH_PREFIX="pt_dockerio"
# Authenticate this immutable toolbox image without rewriting its reference.
export OCI_RUNNER_ECR_AUXILIARY_REGISTRIES="588845226011.dkr.ecr.us-east-2.amazonaws.com"
```

The bearer token must be stored outside the repository:

```bash
chmod 0600 "$OCI_RUNNER_TOKEN_FILE"
chmod 0600 "$OCI_RUNNER_DOCKERHUB_TOKEN_FILE"
```

| Variable | Default | Purpose |
|---|---|---|
| `OCI_RUNNER_BASE_URL` | Direct Sandoq EKS production endpoint | Outer session API |
| `OCI_RUNNER_ENVIRONMENT` | `oci-runner-firecracker` | Firecracker environment to lease; set `oci-runner` for rollback |
| `OCI_RUNNER_LEASE_DURATION` | `1h` | Outer session lease |
| `OCI_RUNNER_TOKEN_FILE` | `~/.config/oci-runner/firecracker-token` | Rotatable Firecracker bearer-token file; use the legacy token file when rolling back |
| `OCI_RUNNER_DOCKERHUB_USERNAME` | unset | Docker Hub user or service account |
| `OCI_RUNNER_DOCKERHUB_TOKEN_FILE` | unset | Mode-`0600` Docker Hub PAT file on the Prime-RL host |
| `OCI_RUNNER_REQUIRE_DOCKERHUB_AUTH` | unset | Set to `1` to fail before pulling rather than use anonymous Docker Hub access |
| `OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK` | `1` | Set to `0` to fail closed on an ECR pull-through upstream-auth failure instead of trying Docker Hub directly |
| `OCI_RUNNER_PODMAN_IGNORE_CHOWN_ERRORS` | unset | Set to `1` for rootless Podman to detect its `vfs`/`overlay` driver and squash image ownership outside its UID/GID map |
| `OCI_RUNNER_USE_ECR` | recipe-specific | Filtered-recipe switch; defaults to `1` there and `0` rolls back to Docker Hub |
| `OCI_RUNNER_ECR_REGISTRY` | unset | ECR hostname; enables Docker Hub reference rewriting and ECR authentication |
| `OCI_RUNNER_ECR_REGION` | `us-east-2` | Region passed to `ucloud ecr get-credentials` |
| `OCI_RUNNER_ECR_PULL_THROUGH_PREFIX` | `pt_dockerio` | ECR pull-through repository prefix |
| `OCI_RUNNER_ECR_AUXILIARY_REGISTRIES` | unset | Comma-separated AWS ECR hosts authenticated in addition to the pull-through registry; references are never rewritten |
| `OCI_RUNNER_ECR_TOKEN_FILE` | unset | Optional mode-`0600` short-lived password file when `ucloud` cannot use workload identity |
| `OCI_RUNNER_ECR_CLIENT_CERT_PATH` | auto | Optional FAIR x509 PEM path passed as both Thrift cert/key variables only to `ucloud` |
| `OCI_RUNNER_ECR_UCLOUD` | `ucloud` | FAIR-native credential executable |
| `OCI_RUNNER_ECR_REFRESH_INTERVAL` | `4h` | In-memory credential refresh interval; must be shorter than ECR's 12-hour expiry |
| `OCI_RUNNER_CREATE_DEADLINE` | `300s` (`30m` in the recipe) | Overall lease and command-server readiness deadline; individual OCI exec requests remain below the proxy ceiling |
| `OCI_RUNNER_PULL_TIMEOUT` | `1200s` | Overall background image-pull and nested-startup timeout |
| `OCI_RUNNER_PULL_POLL_MAX_ERRORS` | `10` | Consecutive transient status-poll errors tolerated after a pull has launched |
| `OCI_RUNNER_EXEC_TIMEOUT_CEILING` | `270` | Maximum blocking OCI exec request, below the 300-second Sandoq proxy deadline |
| `OCI_RUNNER_REQUIRE_RESOURCE_LIMITS` | unset (`1` in the recipe) | Fail closed if Podman does not apply requested CPU, memory/swap, and PID controls |
| `OCI_RUNNER_TASK_PIDS_LIMIT` | `512` | Nested task-container PID ceiling |
| `OCI_RUNNER_TASK_NETWORK` | `none` | Firecracker nested network mode: `none` normally, or `host` when an in-container harness must reach the guest loopback reverse tunnel |
| `SANDOQ_TUNNEL_HTTPS_PROXY` | auto-detected | Optional reverse-tunnel proxy override; normally the official Sandoq client selects the host's proxy and mTLS profile |
| `OCI_RUNNER_OBSERVABILITY` | unset | Set to `1` for stage timings and typed stage failures |
| `OCI_RUNNER_POOL_SIZE` | `32` | Maximum outer sessions owned by the job broker |
| `OCI_RUNNER_POOL_MIN_SIZE` | `0` | Outer sessions to prewarm; production sets `512` |
| `OCI_RUNNER_POOL_SOCKET` | job-scoped path under `/tmp` | Mode-0700 broker Unix socket |
| `OCI_RUNNER_POOL_WAL` | `$PRIME_RL_OUTPUT_DIR/control/oci_pool_$SLURM_JOB_ID.wal.jsonl` when an output directory exists | Shared durable `outer_created`/`outer_deleted` recovery log; only the Unix socket stays node-local |
| `OCI_RUNNER_SESSION_REUSE` | `1` | Set to `0` to restore one outer lease per rollout |
| `OCI_RUNNER_POOL_DRAIN_TIMEOUT` | `240` | Seconds to stop admission, drain active assignments, and verify deletion before preserving incomplete work in the WAL |
| `OCI_RUNNER_POOL_CREATE_WORKERS` | `8` | Maximum concurrent outer-session creates while reconciling toward the warm target |
| `OCI_RUNNER_POOL_BOOTSTRAP_WORKERS` | `8` | Maximum acquired assignments that have not completed nested-container validation |
| `OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE` | `8` | Per-image subset of the global bootstrap limit |
| `OCI_RUNNER_POOL_DRAIN_WORKERS` | `32` | Maximum concurrent verified outer-session deletions during recovery and drain |
| `OCI_RUNNER_POOL_RENEW_INTERVAL` | min(lease / 3, 10m) | Interval between bounded-parallel outer-lease renewal sweeps |
| `OCI_RUNNER_POOL_RENEW_WORKERS` | `16` | Maximum concurrent outer-lease renewal requests |
| `OCI_RUNNER_POOL_MAX_REUSE_COUNT` | `6` | Clean assignments allowed before the outer session is deleted, verified by HTTP 404, and replaced |
| `OCI_RUNNER_POOL_REUSE_JITTER` | `2` | Per-slot reuse threshold jitter; the default samples uniformly from four through eight |
| `OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES` | `2` | Most recently used task images retained per idle outer slot; older unused images are removed after cleanup |
| `OCI_RUNNER_SECRET_CACHE_TTL` | `5s` | Maximum age of a validated in-memory token-file value before permission and rotation revalidation |
| `OCI_EXPECTED_WORKDIR` | `/testbed` | Trusted recipe-selected absolute nested workdir; normalized and validated before a lease |

The pool broker normally obtains one ECR password per configured registry with
`ucloud`, keeps each only in memory, and refreshes it every four hours under the broker lock. For that
subprocess only, it prefers `OCI_RUNNER_ECR_CLIENT_CERT_PATH`, preserves a
complete existing `THRIFT_TLS_CL_CERT_PATH`/`THRIFT_TLS_CL_KEY_PATH` pair, or
discovers `/var/facebook/credentials/<user>/x509/<user>.pem`. It never changes
the provider process environment or shell setup. Token files use a short,
permission-checked in-memory cache and observe atomic rotation after its TTL.
Every assignment receives generation/source/reuse/age
metadata and its assigned runner performs a fresh login through
`--password-stdin`; pulls use the explicit
`/home/runner/.config/containers/ecr-auth.json` file. Credentials cross the
authenticated Sandoq command API only as scoped environment values. Passwords
are not placed in commands, metadata, event logs, or rollout records.

Outer-lease renewal is separate from managed-shell activity. The broker renews
all live outer sessions in bounded parallel sweeps. Recovery-critical lifecycle
records live in the durable output-local WAL; only the Unix socket is node-local.
Non-secret `pool_events.jsonl` telemetry is batched by one background writer and
never blocks lease assignment. Clients use
persistent framed Unix-socket connections and FIFO acquisition tickets. It does
not send commands or keepalives to managed shells.

ECR credentials and cache retention are independent: registry login passwords
expire after 12 hours, while Cloud Foundation's default pull-through cache
lifecycle is approximately three days. A warm cache still requires ECR
authentication. When the ECR pull-through service specifically reports broken
upstream-registry authentication, the provider falls back to the original
Docker Hub reference with its configured auth file and tags the resolved image
under the ECR reference. Other pull errors still fail closed.

## Image validation

Before exposing `bash` to the model, the provider checks:

- the requested image was pulled successfully;
- ECR or Docker Hub authentication succeeded for the selected pull source;
- the image has a valid resolved SHA-256 digest;
- the nested container started with `runsc`;
- authenticated `GET /v1/shells` returned HTTP 200;
- a shell was created for `task` and initialized at the recipe-managed workdir;
- Bash is available for contained command execution;
- the managed workdir and shared mount exist;
- the repository HEAD matches the expected base commit when the recipe supplies
  one.

The environment can record the following non-secret metadata in a rollout:

- assignment, real outer-session, slot, and generation IDs;
- reuse count and pool wait;
- requested image;
- resolved OCI digest;
- unpacked image size reported by Podman;
- nested-container readiness;
- background pull mode, job ID, status, poll count, exit code, direct-registry
  fallback, and rootless ownership mode;
- shell ID, shell generation, managed-shell recovery count, shell-start time,
  shell failure status, assignment poisoning, and
  `shell_command_mode=contained_bash`.

With `OCI_RUNNER_OBSERVABILITY=1`, metadata also contains `oci_timings` for
pool wait, command-server readiness, authentication, registry authentication, image pull,
digest inspection, nested-container start, container validation, total sandbox
readiness, shell start, and nested recycle. Readiness and cleanup
failures raise `OCIRunnerStageError`, an `APIError` subclass with `stage`,
`timings`, and retry-attempt context. Trusted idempotent exhaustion uses the
more specific `OCIRunnerTransientGatewayError`.

## Cleanup guarantees

Cleanup happens for:

- normal rollout completion;
- image-pull or nested-startup failure;
- rollout cancellation;
- speculative rollouts stopped during trainer shutdown;
- process termination through SIGTERM.

Per-rollout cleanup is complete only after the shell, `task` container, and
assignment-specific shared files are absent. Final job cleanup is complete only
after all outer endpoints return HTTP 404 and the broker writes its drain
marker. HTTP 404/410 shell loss, unexpected shell responses, and uncertain
transport failures poison the assignment without replaying its command. The
broker deletes that outer session instead of returning it to the idle pool.

## Package layout

| File | Responsibility |
|---|---|
| `gateway.py` | Process-scoped official-client loop, lifecycle calls, renewal results, typed-404 deletion verification, and shutdown |
| `oci_client.py` | OCI lease orchestration, authentication, Podman bootstrap, exec, file staging, metadata, and cleanup |
| `pool.py` | Job-local slot broker, lease renewal, heartbeats, recycle, LRU image bounds, and final drain |
| `client.py` | Generic Sandoq sandbox facade and proxied-port command helpers |
| `sync_client.py` | Synchronous teardown used during shutdown |
| `registry.py` | Process-local session connection and cleanup state |
| `__init__.py` | Installs the selected transport into Prime-RL/Verifiers sandbox seams |
| `config.py` | Sandoq and OCI provider configuration |
| `tunnel.py` | Session-specific reverse tunnel: parked WebSockets to the Sandoq gateway forwarding guest traffic into a caller-local interception server |

## Example and scope

`recipes/sandoq_swerebench_v2_oci` is the production multi-task GRPO recipe. It
includes the event ledger, official task scoring, capacity probes, and
after-run acceptance gates used to validate rollout and cleanup behavior.
