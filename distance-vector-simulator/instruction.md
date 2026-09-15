`/app/dv_router.py` is a distance vector routing daemon that reads `/app/topology.json` (a 7-node network with 8 topology events: link cost changes, node crashes, node revivals) and produces routing tables plus per-phase convergence history.

The daemon has multiple interacting bugs affecting route computation, loop prevention, tie-breaking, and topology-change handling. The symptoms: wrong convergence round counts and incorrect intermediate routing tables at certain phases, though some final costs may appear correct by coincidence.

Reference output from a correct deployment is at `/app/reference/`.

Fix `/app/dv_router.py` so `python3 /app/dv_router.py` writes:
- `/app/routing_tables.json` — correct final routing tables
- `/app/convergence_log.json` — accurate per-phase convergence with correct round counts

Format: entries are `[cost, next_hop]`. Unreachable destinations: `[9999, null]`. Self-routes: `[0, "<node>"]`.