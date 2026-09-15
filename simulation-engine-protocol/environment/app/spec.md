# Simulation Engine Behavioral Specification v2.1.0

Based on the `ros-simulation/simulation_interfaces` ROS 2 standard.

## Engine Lifecycle

The engine starts in state `NO_WORLD`. The primary lifecycle:

    NO_WORLD → load_world → STOPPED → set_simulation_state(PLAYING) → PLAYING

## State Machine

Valid simulation states: `STOPPED(0)`, `PLAYING(1)`, `PAUSED(2)`, `QUITTING(3)`, `NO_WORLD(4)`, `LOADING_WORLD(5)`.

### Transitions via `set_simulation_state`

Only `STOPPED`, `PLAYING`, and `PAUSED` are valid target states.

| Current            | Target          | Result code                  |
|--------------------|-----------------|------------------------------|
| NO_WORLD           | any             | INCORRECT_STATE (3)          |
| LOADING_WORLD      | any             | INCORRECT_STATE (3)          |
| STOPPED            | PLAYING         | OK (1)                       |
| STOPPED            | PAUSED          | INCORRECT_TRANSITION (103)   |
| PLAYING            | PAUSED          | OK (1)                       |
| PLAYING            | STOPPED         | OK (1)                       |
| PAUSED             | PLAYING         | OK (1)                       |
| PAUSED             | STOPPED         | OK (1)                       |
| any                | same as current | ALREADY_IN_TARGET_STATE (101)|
| any (world loaded) | QUITTING        | INCORRECT_TRANSITION (103)   |
| any (world loaded) | NO_WORLD        | INCORRECT_TRANSITION (103)   |
| any (world loaded) | LOADING_WORLD   | INCORRECT_TRANSITION (103)   |

### State constraints for other operations

- **Entity operations** (spawn, delete, get/set state/info, get entities): require world loaded (state is STOPPED, PLAYING, or PAUSED).
- **step_simulation**: requires `PAUSED` only.
- **reset_simulation**: requires world loaded (STOPPED, PLAYING, or PAUSED).
- **load_world**: requires `NO_WORLD`.
- **unload_world**: requires world loaded (STOPPED, PLAYING, or PAUSED). Transitions to NO_WORLD and clears all entities and simulation time.

## Entity Management

### Spawning

Validation order:
1. World must be loaded → `INCORRECT_STATE (3)`
2. Name must not be empty → `NAME_INVALID (102)`
3. Resource must have non-empty `uri` or `resource_string` → `NO_RESOURCE (104)`
4. If name already exists and `allow_renaming=False` → `NAME_NOT_UNIQUE (101)`
5. If name already exists and `allow_renaming=True` → append `_0`, `_1`, `_2`, ... until a unique name is found

On success:
- Entity is created with the provided `initial_pose` as its initial state (default pose if None).
- Entity starts with default `EntityInfo` (category=OBJECT, description="", tags=[]).
- The engine must store the entity's initial state for later reset operations.

### Batch Spawning (spawn_entities)

- Processes each request sequentially; successful spawns persist even if later ones fail.
- Returns per-entity `SpawnResult` objects.
- Overall result: `OK (1)` if all succeed, `ENTITIES_SPAWN_FAILED (150)` if any fail.

### Deleting

- Entity must exist → `NOT_FOUND (2)` if not.

### Entity Filtering (get_entities)

All filter criteria are ANDed together. Empty/default criteria match all entities.

- **filter** (string): entity name must contain this substring (case-sensitive).
- **categories**: entity's category must be in the provided list.
- **tags**:
  - `FILTER_MODE_ANY (0)`: entity must have at least one of the filter tags.
  - `FILTER_MODE_ALL (1)`: entity must have all of the filter tags.
- **bounds**:
  - `TYPE_EMPTY (0)`: matches all.
  - `TYPE_BOX (1)`: entity's pose position must lie within the AABB defined by `points[0]` (min corner) and `points[1]` (max corner), inclusive on all axes.

### SetEntityState

- `set_pose`, `set_twist`, `set_acceleration` booleans control which fields are updated.
- Only specified fields are modified; others retain their current values.

## Simulation Time

- Tracked as `(seconds: int, nanoseconds: int)`.
- Each simulation step advances time by **1,000,000 nanoseconds** (1 ms).
- Nanoseconds wrap at 1,000,000,000 (increment seconds).
- `step_simulation(steps=N)` advances N steps.
- The current simulation time is reflected in the `header` field of `EntityState` returned by `get_entity_state`.

## Reset Scopes (bitwise flags)

- `SCOPE_DEFAULT (0)`: treated identically to `SCOPE_ALL (255)`.
- `SCOPE_TIME (1)`: reset simulation time to `(0, 0)`.
- `SCOPE_STATE (2)`: restore all entities to their initial spawn state (pose, twist, acceleration).
- `SCOPE_SPAWNED (4)`: remove all spawned entities.
- `SCOPE_ALL (255)`: apply all scope flags.
- Scopes combine with bitwise OR (e.g., `scope=3` means `TIME | STATE`).
- Reset does **not** change the simulation state (PAUSED stays PAUSED, etc.).

## Feature Reporting

`get_simulator_features` must report all features the engine supports. Required features:

    SPAWNING, DELETING, ENTITY_TAGS, ENTITY_CATEGORIES,
    ENTITY_STATE_GETTING, ENTITY_STATE_SETTING,
    ENTITY_INFO_GETTING, ENTITY_INFO_SETTING,
    SIMULATION_RESET, SIMULATION_RESET_TIME,
    SIMULATION_RESET_STATE, SIMULATION_RESET_SPAWNED,
    SIMULATION_STATE_GETTING, SIMULATION_STATE_SETTING,
    SIMULATION_STATE_PAUSE,
    STEP_SIMULATION_SINGLE, STEP_SIMULATION_MULTIPLE,
    WORLD_LOADING, WORLD_UNLOADING, WORLD_INFO_GETTING,
    SPAWNING_ENTITIES

`spawn_formats` must include: `["sdf", "urdf"]`
