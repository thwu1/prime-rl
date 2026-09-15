A partially implemented railway simulation package at `/app/rail_sim/` must pass all tests:

    cd /app && pytest /tests/test_state.py -v

The existing code has defects and is missing components. Reference source is at `/app/flatland_src/`. Transition rules, JSON schemas, and the SQLite trace schema are in `/app/SCHEMA.md`.

## Required Package Modules

**`rail_sim.states`** — `TrainState(IntEnum)` with values WAITING=0 through DONE=6. Helper methods: `is_malfunction_state()`, `is_off_map_state()`, `is_on_map_state()`. `StateTransitionSignals` dataclass with 7 boolean fields defaulting to False.

**`rail_sim.speed_counter`** — `SpeedCounter(speed: float, max_speed: float)`. Properties: `speed`, `max_speed`, `distance` (Fraction), `is_cell_entry` (bool). Methods: `step(speed=None)`, `is_cell_exit(speed) -> bool`, `reset()`.

**`rail_sim.state_machine`** — `TrainStateMachine(initial_state=TrainState.WAITING)`. Methods: `set_transition_signals(signals)`, `step()`, `reset()`, `update_if_reached(position, targets)`. Properties: `state`, `previous_state`.

**`rail_sim.motion_check`** — `MotionCheck()`. Methods: `add_agent(handle, current_pos, desired_pos)`, `find_conflicts()`, `check_motion(handle, pos) -> bool`.

**`rail_sim.simulator`** — Action constants: DO_NOTHING=0, MOVE_LEFT=1, MOVE_FORWARD=2, MOVE_RIGHT=3, STOP_MOVING=4. `StepSimulator().simulate(scenario) -> list[dict]`. CLI: `python3 -m rail_sim.simulator <scenario.json>` outputs JSON array to stdout. With `--trace-db <path>`: additionally writes to SQLite.

**`rail_sim.trace`** — `write_trace(db_path, results)`.

## Required Makefile

Create `/app/Makefile` with these targets:

- `make simulate SCENARIO=<path>` — invokes the simulation CLI, prints JSON to stdout
- `make trace SCENARIO=<path> DB=<path>` — invokes the simulation CLI with `--trace-db`, prints JSON to stdout
- `make summary DB=<path>` — queries the trace database using the `sqlite3` CLI and transforms the result with `jq` to produce a JSON object on stdout: `{"total_steps": <int>, "agents": <int>, "final_states": {"<handle>": <state_int>}}` where `total_steps` is the maximum step number, `agents` is the distinct agent count, and `final_states` maps each agent handle (string key) to its state at the last recorded step
- `make lint-scenario SCENARIO=<path>` — validates that the scenario JSON contains the required top-level keys (`agents`, `actions`, `max_steps`) using `jq`; exits 0 if valid, non-zero otherwise

The `summary` and `lint-scenario` targets must use `sqlite3` and `jq` CLI tools directly, not Python.
