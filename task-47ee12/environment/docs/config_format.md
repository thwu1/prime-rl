# KernelCI Pipeline Configuration Format

## Overview

The pipeline configuration file (`pipeline.yaml`) defines the infrastructure
components used by KernelCI's Maestro orchestrator to coordinate kernel builds
and tests across distributed labs.

## Top-Level Sections

### `api`
Maps named API endpoints to their URLs. Each entry has a `url` field.

### `storage`
Defines artifact storage backends. Each entry has:
- `storage_type`: Either `ssh` or `backend`
- For `ssh` type: `host` (required), `port`, `base_url`
- For `backend` type: `base_url` (required), `api_url` (optional)

When both `base_url` and `api_url` are specified for a `backend` storage,
they should reference the same environment (both staging or both production).

### `runtimes`
Defines test execution environments. Each entry has a `lab_type`:

#### `lava` (LAVA hardware labs)
- `url` (required): LAVA lab API endpoint
- `priority_min`, `priority_max`: Job priority range. `priority_min` must
  be less than or equal to `priority_max`. Overlapping ranges between labs
  can cause scheduling ambiguity.
- `notify.callback.token`: Token DESCRIPTION (not the secret value) used in
  LAVA job definitions for callback authentication. See "Token Semantics" below.
- `rules.tree`: List of kernel tree names to accept/reject
  - Plain name (e.g., `mainline`): include this tree
  - Prefixed with `!` (e.g., `!android`): exclude this tree
  - A tree cannot be both included and excluded in the same lab.
- `disable_queue_limit`: Boolean. When true, disables queue depth checking
  against the lab's API. This is a safety mechanism — disabling it means
  jobs can be submitted without limit, risking lab overload.

#### `kubernetes`
- `context`: Kubernetes cluster context name or list of context names

#### `docker`
- `env_file`, `user`, `volumes`: Docker runtime configuration

#### `shell`
- No additional required fields

## YAML Merge Keys

The configuration uses YAML merge keys (`<<: *anchor-name`) to share common
settings between similar runtimes. When a runtime uses a merge key:
- Keys explicitly defined in the runtime override merged values
- Keys NOT explicitly defined are inherited from the anchor source
- Nested structures (like `notify.callback`) are inherited as a whole unit
- This can cause unintended sharing of security-critical fields

## Token Semantics

The `notify.callback.token` field contains a token DESCRIPTION (name), not the
actual secret. LAVA's callback behavior:
- If the token name matches an existing LAVA token: the callback sends the
  token's secret value
- If the token name does NOT match: LAVA sends the description string itself
  as the callback authentication value

This means the token description effectively becomes a shared secret if no
matching LAVA token exists. Labs sharing the same token description will
authenticate callbacks identically, which may not be intended when runtimes
are independently administered.

## Priority Scheduling

When multiple LAVA labs have overlapping priority ranges, the Maestro scheduler
may dispatch jobs to any of the overlapping labs. If those labs have different
tree filtering rules, a job may be accepted by one lab but rejected by another,
leading to inconsistent test coverage.
