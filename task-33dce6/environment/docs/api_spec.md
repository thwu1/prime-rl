# GameEngine API Specification

## Class: `GameEngine`

### Constructor

```python
GameEngine(config: dict, initial_state: dict)
```

Initialize a game engine from a configuration and initial world state.

#### `config` format

```json
{
  "grid": {"width": 20, "height": 20},
  "roles": [
    {
      "name": "default",
      "vision": 5,
      "actions": ["skip", "move", "rotate", "adopt", "request", "attach", "detach",
                   "connect", "disconnect", "submit", "clear", "survey"],
      "speed": [2, 1, 0],
      "clear": {"chance": 1.0, "maxDistance": 2}
    }
  ],
  "maxEnergy": 100,
  "stepRecharge": 1,
  "clearEnergyCost": 2,
  "deactivatedDuration": 10,
  "refreshEnergy": 50,
  "clearDamage": [32, 16, 8, 4, 2, 1],
  "attachLimit": 10,
  "steps": 500,
  "randomFail": 0
}
```

- **grid**: width and height of the toroidal grid
- **roles**: list of role definitions
  - **name**: role identifier
  - **vision**: Manhattan-distance vision radius
  - **actions**: list of action types the role may use
  - **speed**: array where index *i* is max moves per step when *i* things are attached; if attached count >= len(speed), use last value
  - **clear**: chance (0-1) of clear success, maxDistance for clear range (entities can only be damaged if maxDistance > 1)
- **maxEnergy**: initial and maximum energy
- **stepRecharge**: energy recharged per step (for eligible agents)
- **clearEnergyCost**: energy cost for a clear action
- **deactivatedDuration**: number of steps an agent stays deactivated
- **refreshEnergy**: energy restored when reactivating after deactivation
- **clearDamage**: array where index *i* is damage dealt to an entity at Manhattan distance *i* from the clearing agent; if distance >= len(array), use last value
- **attachLimit**: max number of things in a connected attachment component
- **steps**: total simulation steps
- **randomFail**: always 0 in tests (no random action failures)

#### `initial_state` format

```json
{
  "agents": [
    {"name": "agentA0", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}
  ],
  "blocks": [
    {"x": 3, "y": 5, "type": "b0"}
  ],
  "dispensers": [
    {"x": 10, "y": 10, "type": "b0"}
  ],
  "obstacles": [
    {"x": 7, "y": 7}
  ],
  "tasks": [
    {"name": "task1", "deadline": 200, "reward": 30,
     "requirements": [{"x": 0, "y": 1, "type": "b0"}]}
  ],
  "norms": [
    {"name": "n1", "start": 0, "until": 100, "level": "individual",
     "requirements": [{"type": "block", "name": "any", "quantity": 1}],
     "punishment": 10}
  ],
  "goalZones": [[2, 2], [2, 3]],
  "roleZones": [[15, 15], [15, 16]]
}
```

- **agents**: initial agent states (name, team, position, role, energy)
- **blocks**: initial blocks on the grid (position, block type)
- **dispensers**: dispensers (position, block type they produce)
- **obstacles**: obstacles (position)
- **tasks**: active tasks (name, deadline step, reward points, requirements as relative positions with block types)
- **norms**: active norms. Carry norms (`type: "block"`, `name: "any"`) set max attachable things per agent. Adopt norms (`type: "role"`, `name: "<roleName>"`) set max agents per role per team. `punishment` is energy lost per step of violation.
- **goalZones**: list of [x, y] positions that are goal zone cells
- **roleZones**: list of [x, y] positions that are role zone cells

---

### `step(actions: dict) -> dict`

Process one simulation step.

**actions**: `{agent_name: {"type": action_type, "p": [param1, param2, ...]}}`. Agents not in the dict implicitly perform `"skip"`. All parameters are strings.

**returns**: `{agent_name: {"result": result_code}}` for every agent.

Result codes: `"success"`, `"failed_parameter"`, `"failed_path"`, `"failed_target"`, `"failed_blocked"`, `"failed_resources"`, `"failed_location"`, `"failed_role"`, `"failed_status"`, `"failed_partner"`, `"failed"`, `"partial_success"`, `"unknown_action"`.

#### Action processing order (deterministic)

Actions are processed in this fixed order. Within each action type, agents are processed in alphabetical order by name:

1. skip
2. adopt
3. survey
4. clear
5. request
6. attach
7. detach
8. disconnect
9. rotate
10. connect (both partners processed together)
11. move
12. submit

#### End-of-step processing (after all actions)

1. **Norm enforcement**: for each active norm (where `start <= current_step <= until`), check violations and apply energy penalties. Agents whose energy is depleted are deactivated. Consult the norms reference traces for exact enforcement mechanics.
2. **Deactivation and energy management**: manage deactivation counters and energy recharge. Agents reactivate with `refreshEnergy` when their deactivation counter expires. Energy recharge (`stepRecharge`, capped at `maxEnergy`) occurs for eligible agents each step. Consult the energy reference traces for lifecycle details.
3. **Increment step counter**.

---

### `get_agent(name: str) -> dict`

Returns agent state:

```python
{
    "name": str,
    "team": str,
    "x": int,
    "y": int,
    "role": str,
    "energy": int,
    "deactivated": bool,
    "deactivated_steps": int,
    "attached": [[rx, ry], ...]  # relative positions of all attached things
}
```

`attached` lists the relative positions (from the agent) of every thing directly or indirectly attached to the agent (blocks, obstacles, other agents). Uses shortest-path relative coordinates on the torus.

---

### `get_score(team: str) -> int`

Returns the team's current score (sum of rewards from submitted tasks).

---

### `get_step() -> int`

Returns current step number. Starts at 0, incremented at end of each `step()` call.

---

### `get_things_at(x: int, y: int) -> list`

Returns list of things at the absolute grid position:

```python
[
    {"type": "entity", "details": "<team>"},
    {"type": "block", "details": "<block_type>"},
    {"type": "dispenser", "details": "<block_type>"},
    {"type": "obstacle", "details": ""},
    ...
]
```

---

### `get_blocks() -> list`

Returns all blocks currently on the grid:

```python
[
    {"x": int, "y": int, "type": str, "attached_to": str | None},
    ...
]
```

`attached_to` is the name of an agent in the block's connected component, or `None` if unattached.

---

## Grid Mechanics

- The grid is a torus: coordinates wrap modulo width (x-axis) and height (y-axis).
- Manhattan distance on the torus: `min(|dx|, width-|dx|) + min(|dy|, height-|dy|)`.
- X-axis goes east (right), Y-axis goes south (down).
- Directions: `n` = (0,-1), `s` = (0,+1), `e` = (+1,0), `w` = (-1,0).

## Rotation

- The agent's attached things rotate 90° around the agent's position.
- The coordinate system has X increasing eastward and Y increasing southward.
- For exact rotation transform behavior, query the reference database or analyze `/app/replays/replay_rotation.json`.

## Attachment Model

- Attachments form an undirected graph. Agents, blocks, and obstacles are nodes.
- `attach` creates an edge between the agent and an adjacent thing.
- `detach` removes the edge between the agent and an adjacent attached thing.
- `connect` creates an edge between two blocks belonging to different agents' components.
- `disconnect` removes an edge between two attached things in the agent's component.
- A "connected component" is all nodes reachable through attachment edges.
- Movement speed depends on `len(component) - 1` (number of attached things, excluding the agent).
- When an agent moves, the entire component translates by the same delta.
- When an agent is deactivated, all its attachment edges are removed.
