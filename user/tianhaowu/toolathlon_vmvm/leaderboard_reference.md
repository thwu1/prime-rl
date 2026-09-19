# Toolathlon leaderboard reference

Source: <https://toolathlon.xyz/docs/leaderboard.md>

Retrieved through VMVM on 2026-08-21 because the site is not reachable from
the normal cluster network.

## Toolathlon-Verified

The current leaderboard identifies this as the benchmark released on June 30,
2026. Its Kimi K2.6 row is:

| Model | Agent | Date | Pass@1 | Pass@3 | Pass^3 | Turns | Tool calls |
|---|---|---:|---:|---:|---:|---:|---:|
| Kimi K2.6 | Default | 2026-07-15 | 58.0 ± 4.9 | 72.2 | 41.7 | 30.8 | 42.3 |

Across three trials of 108 tasks, these rounded score metrics correspond to 188
total successful trials, 78 tasks solved at least once, and 45 tasks solved in
all three trials.

The official Toolathlon repository documents the Verified defaults as a
5,400-second timeout per task, 65,536 maximum output tokens per agent turn, and
provider-default temperature and top-p. In private-service mode its custom
model-parameter payload contains only `max_tokens`; Kimi thinking and parallel
tool-call behavior come from the endpoint and agent defaults. The live public
evaluation service reported a maximum submission concurrency of 10 workers on
2026-08-21.

## Previous Toolathlon

The archived pre-Verified leaderboard reports Kimi-K2.6 at 50.0 Pass@1 on
2026-04-21. It does not report Pass@3 or Pass^3 for that run. The official page
states that scores from the previous benchmark are not directly comparable with
Toolathlon-Verified scores.
