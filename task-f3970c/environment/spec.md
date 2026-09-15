# Discourse Docker Configuration Resolver — Specification

## Overview

The resolver takes a container configuration name and resolves the full
configuration by compositing YAML template files according to the Discourse
Docker launcher's merging algorithm. It outputs the resolved configuration
as a JSON document.

## Resolution Algorithm

### 1. Load Configuration

Load the container definition YAML from `containers/<config_name>.yml`.

### 2. Extract Template References

Read the `templates` list from the container definition. Each entry is a
relative path to a template YAML file (e.g., `templates/postgres.template.yml`).

### 3. Merge Order

Layers are applied in this order:

1. Each template, in the order listed in the `templates` array
2. The container definition itself, applied **last**

This gives the container definition the highest priority — its values
override any values set by templates. Within templates, later templates
override earlier ones for dict-merged fields.

### 4. Merging Rules by Field

For each layer (template or container config), merge its fields into the
accumulated result using these strategies:

#### `env` — Dict merge with substitution
Later values override earlier values for the same key. The `{{config}}`
placeholder in values is replaced with the config name (e.g., if config
name is `app`, then `"{{config}}_discourse"` becomes `"app_discourse"`).
All values are converted to strings.

#### `labels` — Dict merge with substitution
Later values override earlier values for the same key. The `{{config}}`
placeholder in values is replaced with the config name, just as with env.
All values are converted to strings.

#### `expose` — List append
Entries from each layer are appended to the accumulated list. Deduplication
is performed later when generating port arguments.

#### `volumes` — List append
Volume entries are accumulated from all layers.

#### `links` — List append
Link entries are accumulated from all layers.

#### `hooks` — Merge by name, concatenate commands
Hooks are keyed by hook name (e.g., `after_code`, `after_postgres`). When
multiple layers define the same hook name, the command lists are
**concatenated** — commands from the later layer are appended after
commands from the earlier layer. Commands from earlier layers appear first.
Hooks with different names coexist independently.

#### `params` — Dict merge
Later values override earlier values for the same key.

### 5. Port Argument Generation

Convert the accumulated `expose` list to Docker port arguments:

- Entries containing `:` become `-p` flags (port publishing):
  - Two-part `host:container` → `-p host:container`
  - Three-part `ip:host:container` → `-p ip:host:container`
- Entries without `:` become `--expose` flags (expose without publishing)
- Duplicate entries are removed while preserving first-occurrence order

### 6. Hostname Computation

If the resolved env contains `DOCKER_USE_HOSTNAME` set to the string
`"true"`, the hostname is the value of `DISCOURSE_HOSTNAME` from the
resolved env.

Otherwise, the hostname is `<machine_hostname>-<config_name>`, where
`machine_hostname` is the short hostname of the host machine (or the
value passed via `--hostname`).

In **all cases**, underscores (`_`) in the resulting hostname are replaced
with hyphens (`-`). Docker container hostnames cannot contain underscores.

### 7. MAC Address Computation

The MAC address is computed deterministically from the hostname:

1. Compute the MD5 hash of the hostname string with a trailing newline
   character appended (matching the behavior of `echo $hostname | md5sum`)
2. Take the hex digest
3. Format as `02:XX:XX:XX:XX:XX` using consecutive 2-character pairs from
   positions 0-1, 2-3, 4-5, 6-7, 8-9 of the hex digest

### 8. Top-Level Fields (Config Only)

The following fields are read **only** from the container definition file,
not merged from templates:

- `docker_args` — Additional Docker run arguments (string, default: `""`)
- `boot_command` — Container boot command (string, default: `/sbin/boot`)
- `run_image` — Docker image to run (string, default: `local_discourse/<config_name>`)
- `base_image` — Base image for bootstrapping (string, default: `discourse/base:2.0.20260521-0047`)

### 9. Bundled Plugin Detection

Scan all hook exec command lists for `git clone` URLs that reference
plugins from the bundled plugins list. A plugin is considered referenced
if any command string contains `github.com/discourse/<plugin_name>`
(this matches regardless of `.git` suffix or other trailing characters).

Report all detected bundled plugins as a sorted list of unique names.

## Output Format

The resolver outputs a JSON object with these keys:

| Key                | Type     | Description                                   |
|--------------------|----------|-----------------------------------------------|
| `base_image`       | string   | Base image for bootstrapping                  |
| `boot_command`     | string   | Container boot command                        |
| `bundled_plugins`  | string[] | Detected bundled plugin names (sorted)        |
| `docker_args`      | string   | Additional Docker arguments                   |
| `env`              | object   | Resolved environment variables                |
| `expose`           | string[] | All expose entries (before dedup)             |
| `hooks`            | object   | Hook name → command list arrays               |
| `hostname`         | string   | Computed container hostname                   |
| `labels`           | object   | Resolved labels                               |
| `links`            | array    | Accumulated link definitions                  |
| `mac_address`      | string   | Computed MAC address                          |
| `params`           | object   | Merged parameters                             |
| `port_args`        | string[] | Docker port argument strings (deduplicated)   |
| `run_image`        | string   | Docker image to run                           |
| `volume_args`      | string[] | Docker -v argument strings                    |
| `volumes`          | array    | Raw accumulated volume definitions            |
