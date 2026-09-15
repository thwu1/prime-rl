The metrics collector daemon at `/app/collector` is in a crash loop. The watchdog (`/app/watchdog.sh`) repeatedly kills it for exceeding its 1 GB virtual memory limit, as recorded in `/var/log/collector/watchdog.log`. The collector's own log at `/var/log/collector/collector.log` has no entries from the current crash loop — only a shutdown message from the previous stable run.

Source code is at `/app/collector.c`. Endpoint configuration is at `/app/config/endpoints.conf`. Mock services can be started with `/app/start_services.sh`.

Identify and fix every bug in the collector source code and configuration that contributes to the failure cascade, including the reason the collector's logs are absent. Recompile with `gcc -o /app/collector /app/collector.c`.

Produce:

- Fixed `/app/collector.c` with all bugs resolved
- Corrected `/app/config/endpoints.conf`
- `/app/postmortem.md` — decode any anomalous numeric values observed during diagnosis, map the full causal chain from the root trigger through every amplifying factor to the observable failure mode, and evaluate the relative severity of each contributing bug
- `/app/healthcheck.sh` — an executable script accepting an optional config file path as its first argument (defaulting to `/app/config/endpoints.conf`) that probes each listed endpoint and reports which ones speak the expected length-prefixed binary protocol versus a mismatched protocol