`/app/massim_spec.md` defines the complete rules and configuration format for a MASSim "Agents Assemble" grid-world simulation. The following data files are also present:

- `/app/conf/` — Server match configuration (hierarchical, with the entry point at `/app/conf/config.json`)
- `/app/scenario.json` — Initial world state
- `/app/action_log.json` — Recorded agent actions for 10 simulation steps

Build a system that faithfully replays this recorded simulation — implementing the full game mechanics from the specification — and produces the following artifacts:

**`/app/resolved_config.json`** — The match configuration fully resolved into a single self-contained JSON document. No unresolved file references may remain.

**`/app/replay.db`** — SQLite database recording the complete simulation state at every step:
- `agent_states(step INT, agent_name TEXT, x INT, y INT, energy INT, role TEXT, deactivated INT, num_attachments INT)`
- `block_states(step INT, block_id TEXT, block_type TEXT, x INT, y INT)`
- `action_results(step INT, agent_name TEXT, action TEXT, params TEXT, result TEXT)`
- `norm_violations(step INT, agent_name TEXT, norm_name TEXT)`
- `scores(step INT, team TEXT, score INT)`

**`/app/results.json`** — `{"teams": {"<team>": <final_score>}, "steps_played": <N>}`