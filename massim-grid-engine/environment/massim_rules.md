# MASSim "Agents Assemble" — Game Rules Specification


## 1. Grid

The environment is a rectangular grid of dimensions `width × height`. The
coordinate system uses **x** increasing eastward (right) and **y** increasing
southward (down). The grid is **toroidal**: it wraps both horizontally and
vertically. Moving off the east edge places the entity on the west edge, and
similarly for north/south.

### Manhattan distance on a torus

For two positions `(x1,y1)` and `(x2,y2)`:

```
dx = min(|x1 - x2|, width  - |x1 - x2|)
dy = min(|y1 - y2|, height - |y1 - y2|)
distance = dx + dy
```

## 2. Things (entities that occupy cells)

| Kind       | Blocks passage? | Notes |
|------------|-----------------|-------|
| Entity     | Yes             | Agent-controlled. Has a team, role, energy, position. |
| Block      | Yes             | Has a block type (e.g. `b0`, `b1`). Can be attached and connected. |
| Obstacle   | Yes             | Cannot be connected; can be attached and moved or cleared. |
| Dispenser  | **No**          | Produces blocks of a specific type via the `request` action. |
| Marker     | **No**          | Marks cells (e.g. for clear events). |

A cell is **blocked** if it contains an entity, block, or obstacle.
Dispensers and markers do **not** block.

## 3. Roles

Each role defines:

- **vision**: perception radius (Manhattan distance)
- **actions**: list of allowed action types
- **speed**: array indexed by number of attached things. `speed[i]` = max
  cells the agent can move per step when carrying `i` things. If the number of
  attached things ≥ length of the array, use the **last** element.
- **clear** properties: `chance` (success probability 0–1) and `maxDistance`

The first configured role is the default. All other roles inherit the default
role's actions in addition to their own.

## 4. Attachments

Attachments form a bidirectional graph. When agent A attaches thing T:

- A direct edge A ↔ T is created.
- All things transitively reachable from A through attachment edges are
  considered "attached" to A.

When an agent moves, all transitively attached things move with it.
When an agent rotates, all transitively attached **non-agent** things rotate.

Direct attachments can be broken with `detach` (agent ↔ thing) or `disconnect`
(thing ↔ thing).

## 5. Actions

All actions can fail with: `failed_random` (random chance), `failed_status`
(agent deactivated), `failed_role` (role doesn't permit action),
`unknown_action`.

### 5.1 skip
Always succeeds (barring random fail).

### 5.2 move
Parameters: one or more directions from `{n, s, e, w}`.

- Number of directions actually traversed ≤ `speed[num_attached_things]`.
- Each move shifts the agent **and all attached things** by one cell.
- If any entity in the moving group would collide with a non-moving entity/
  block/obstacle, that step is blocked.
- **Failure codes**: `failed_parameter` (bad direction), `failed_path` (first
  move blocked), `partial_success` (first move OK but a later one blocked).

### 5.3 attach
Parameters: direction `{n, s, e, w}`.

Attaches a thing (block, obstacle, or friendly entity) in the adjacent cell to
the agent. Creates a bidirectional attachment edge.

**Failure codes**: `failed_parameter`, `failed_target` (nothing there),
`failed_blocked` (already attached to opponent), `failed` (too many things).

### 5.4 detach
Parameters: direction `{n, s, e, w}`.

Breaks the direct attachment between the agent and the thing in the specified
adjacent cell.

**Failure codes**: `failed_parameter`, `failed_target` (nothing attached there).

### 5.5 rotate
Parameters: `cw` or `ccw`.

Rotates the agent and all transitively attached **non-agent** things 90° around
the agent's position.

Coordinate transform (relative to agent):
- **CW**:  `(dx, dy) → (−dy, dx)`
- **CCW**: `(dx, dy) → (dy, −dx)`

When computing relative deltas on the toroidal grid, normalise: if `dx >
width/2`, subtract `width`; if `dx < −width/2`, add `width`; same for `dy`
with `height`.

New absolute positions are wrapped via the torus.

**Collision check**: Every rotated thing's destination must be free (not
occupied by any non-rotating entity, and no two rotating things may land on the
same cell, and no rotating thing may land on the agent's cell).

**Failure codes**: `failed_parameter`, `failed` (collision, or agent is
attached to another agent).

### 5.6 request
Parameters: direction `{n, s, e, w}`.

Request a block from an adjacent dispenser. A new block of the dispenser's
type appears at the dispenser's cell.

**Failure codes**: `failed_parameter`, `failed_target` (no dispenser),
`failed_blocked` (cell occupied by entity/block/obstacle).

### 5.7 submit
Parameters: task name.

Submit attached blocks to complete a task. Requirements:

1. The task must exist and the current step ≤ deadline.
2. The agent must be in a **goal zone** (Manhattan distance to zone center ≤
   zone radius).
3. For each requirement `(rx, ry, type)` in the task, there must be a
   transitively attached block at absolute position
   `wrap(agent_x + rx, agent_y + ry)` with the matching block type.

On success, the team's score increases by the task's reward.

**Failure codes**: `failed_parameter`, `failed_target` (task doesn't exist or
past deadline), `failed` (not in goal zone, or blocks don't match).

### 5.8 clear
Parameters: relative x, relative y (integers).

Costs energy. Removes blocks and obstacles at the target cell, severing their
attachment edges. Fails if agent's energy < cost or target is out of the role's
`maxDistance`.

**Failure codes**: `failed_parameter`, `failed_resources`, `failed_location`,
`failed_target`, `failed_random`.

### 5.9 adopt
Parameters: role name.

Agent adopts a new role. Must be in a **role zone**.

**Failure codes**: `failed_parameter`, `failed_location`.

### 5.10 connect
**Simultaneous action** — two agents of the same team must both execute
`connect` in the same step, each specifying the partner agent and the relative
coordinates of the block they want to connect.

The two specified blocks must be adjacent (Manhattan distance 1). Both blocks
must already be attached to their respective agents (directly or transitively).
On success, a direct attachment edge is created between the two blocks,
merging the attachment trees.

**Failure codes**: `failed_parameter`, `failed_partner`, `failed_target`,
`failed`.

### 5.11 disconnect
Parameters: x1, y1, x2, y2 (relative integer coords of two attached things).

Breaks the direct attachment between the two specified things.

### 5.12 survey
Gathers information. (Simplified: always succeeds.)

## 6. Norms

Norms are rules that constrain agent behaviour during a time window
`[start, until]`. Violations incur energy penalties.

### 6.1 Carry (individual level)

Limits the number of **attachable things** an agent may carry (total
transitive attachment count). The `quantity` field is the maximum allowed.
Agents with more than `quantity` things attached are in violation.

### 6.2 Adopt (team level)

Limits how many agents per team may use a given role. The `quantity` field is
the maximum allowed per team. If a team has more agents in the specified role
than `quantity`, **all** agents of that role in that team are considered in
violation (not just the excess).

## 7. Energy

- Each agent starts with `max_energy`.
- Agents recharge `step_recharge` energy per step (capped at `max_energy`).
- Norm violations and clear actions drain energy.
- When energy reaches **0**, the agent is **deactivated**:
  - All direct attachments are severed.
  - Actions return `failed_status` for `deactivated_duration` steps.
  - After reactivation, energy is set to `refresh_energy`.

## 8. Goal Zones and Role Zones

A zone is defined by a center `(cx, cy)` and a radius. A position is inside a
zone if its toroidal Manhattan distance to the center ≤ radius.
