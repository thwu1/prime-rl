A process supervisor at `/app/src/supervisor.c` caused a catastrophic production incident: during a deployment on host prod-web-037, every user process was killed simultaneously — sshd, cron, monitoring, rsyslog, all application workers. Only init (pid 1) and the supervisor itself survived. The host required out-of-band console access to recover. In preceding weeks, operators had observed intermittent multi-second hangs during high worker churn.

The artifacts in `/app/` include the supervisor source, build system, a cleanup script (`/app/scripts/cleanup.sh`) separately flagged for catastrophic data loss potential, and investigation logs under `/app/logs/` (incident timeline, postmortem notes, syslog excerpt, partial strace capture). Some logged hypotheses may be incomplete or misleading.

Your job is to conduct a full forensic investigation: identify every bug in the supervisor that contributed to the incident or degraded reliability, fix them all, and harden the cleanup script. The fixed supervisor must compile with `gcc -Wall -Wextra -Werror` and run correctly.

Produce:

- `/app/src/supervisor.c` — all bugs fixed, production-safe, compiles cleanly
- `/app/scripts/cleanup.sh` — hardened against all failure modes that could cause unintended data loss
- `/app/analysis/strace_fixed.log` — strace capture of the fixed supervisor demonstrating correct lifecycle (starting workers, handling SIGTERM, clean shutdown without the catastrophic failure mode)
- `/app/analysis/root_cause.md` — root cause analysis documenting every bug, how each contributed to the incident, syscall-level evidence, and the fix applied