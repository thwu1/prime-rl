The environment at `/app/` contains:

- `/app/units/` — Five systemd `.service` files that fail to achieve the runtime behavior described in their header comments, due to misuse of systemd's ExecStart command-line syntax.
- `/app/specs/output_format.txt` — Output format specification for the tokenizer.
- `/app/bin/argv_inspector.sh` — Prints received arguments for manual testing.

Produce two deliverables:

## 1. `/app/sd_tokenize.sh`

An executable shell script that tokenizes systemd `ExecStart=`, `ExecStartPre=`, and `ExecStartPost=` directives according to systemd.service(5) and systemd.syntax(7) semantics.

**Input:** A file path argument (or stdin if no argument) containing `Environment=` and `Exec*=` directives, one per line.

**Output:** Per the specification in `/app/specs/output_format.txt`. The tokenizer must correctly handle all behaviors described in that specification, including variable expansion, quoting, prefix detection, command path resolution, and line continuation.

## 2. `/app/fixed/`

Corrected versions of all five service files from `/app/units/`. Each original file has header comments describing the intended runtime behavior. The services currently fail to produce that behavior because their `Exec*=` directives violate systemd's documented command-line parsing rules.

Diagnose each service against systemd's ExecStart parsing semantics, fix all violations, and ensure each corrected service achieves its stated intended behavior.

**Required files in `/app/fixed/`:**

`data-pipeline.service`, `app-server.service`, `deploy-hook.service`, `multi-step.service`, `healthcheck.service`

**Success criteria:**

- Every fixed service passes `systemd-analyze --user verify` without parsing errors.
- Every `Exec*=` directive uses only constructs that systemd's command-line parser supports.
- Intended runtime behavior from each original file's header comments is preserved.
- Any executable helper scripts needed by fixed services are placed in `/app/fixed/scripts/`. The healthcheck service must reference a wrapper script (filename contains `health`, extension `.sh`) from `/app/fixed/scripts/`.
