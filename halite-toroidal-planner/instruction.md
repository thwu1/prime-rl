Recorded replays of a resource-collection game are stored under `/app/replays/`. Each replay directory contains `metadata.json` (grid dimensions and game constants), sequential `turn_NNN.json` snapshots (full board state including halite grid, ship positions/cargo, player halite, structures), and `commands_NNN.json` files (commands executed between consecutive states). A high-level game overview is at `/app/overview.md` — it is intentionally incomplete. The replays are the ground truth for the precise mechanics you must reverse-engineer.

The game is played on a toroidal grid. Ships move in cardinal directions or stay still. Movement costs halite from the ship's cargo based on the cell's halite content. Staying still mines halite from the cell. Ships deposit cargo at friendly structures (shipyard/dropoffs). Collisions destroy ships. An "inspiration" mechanic provides mining bonuses near enemy ships. The exact formulas — extraction rates, rounding behavior, movement cost calculations, inspiration activation/bonus, collision cargo resolution, spawn costs, dropoff construction costs, turn phase ordering — are encoded in the game constants and must be deduced from the replay data.

## Deliverables

**`/app/simulator.py`** — A `GameState` class that reproduces every recorded state transition exactly. It must support:

- `GameState(width, height, halite_grid, players, constants)` — constructor from initial turn data
- `GameState.from_scenario(path)` — class method to construct from a scenario JSON file
- `state.step(commands)` — advance one turn given a dict mapping player_id to command list; returns a new `GameState`
- `state.get_cell_halite(x, y)`, `state.get_player_halite(pid)`, `state.get_ships(pid)`, `state.get_dropoffs(pid)`, `state.get_shipyard(pid)` — state accessors

Ships are dicts with keys `id`, `x`, `y`, `halite`. Dropoffs/shipyards are dicts with `x`, `y`. Commands are strings: `"o"` (stay/mine), `"n"`, `"s"`, `"e"`, `"w"` (move), `"g <ship_id>"` (spawn), `"c <ship_id>"` (construct dropoff).

Every cell halite value, ship position/cargo, and player halite total must match the recorded replays after stepping through all turns with the recorded commands.

**`/app/planner.py`** — A `plan(scenario_path)` function that returns a list of command lists (one per turn) for player 0, maximizing net halite collection across the scenarios in `/app/scenarios/`. Each scenario JSON specifies a starting state, turn limit, and target halite gain. The planner must avoid destroying friendly ships through self-collision and meet or exceed the target gains.