# MASSim Scenario: Agents Assemble

## Environment

The environment is a rectangular grid. The grid loops horizontally and vertically (torus), i.e. if an agent moves off the right edge, it appears on the left side. The x-axis goes from left to right (eastwards) and the y-axis from top to bottom (southwards).

Each cell of the grid contains up to one thing that may collide with other things, i.e. agents, blocks and obstacles. Dispensers and markers do not collide.

### Entity/Agent

Each agent controls one entity in the simulation. Agents do not know their absolute positioning. They only know their current *role*, their *energy* level and whether they are currently deactivated. They perceive all things within their vision radius (Manhattan distance).

#### Energy

Each agent starts with the same energy level and automatically recharges a fixed amount per step. Agents can lose energy through clear actions/events, violating norms, etc. Once energy reaches 0, the agent gets deactivated for a fixed number of steps.

#### Deactivated agents

If an agent becomes deactivated, it **loses all of its attachments** and remains inactive for a fixed configurable number of steps. All its actions will result in `failed_status`. After the deactivation period, the agent gains a certain preconfigured energy level (`refreshEnergy`).

#### Vision range

Agents perceive everything within a Manhattan distance of *r* around them, where *r* is determined by their current role.

### Things

- **Entities**: Each agent controls an entity. Entities can move and attach things.
- **Blocks**: Building blocks with a specific type. Agents pick up blocks and arrange them into patterns.
- **Obstacles**: Block passage. Can be attached and moved, or removed by clear actions. Cannot be connected.
- **Dispensers**: Each dispenser produces a specific kind of block via the `request` action.
- **Markers**: Mark cells (e.g., for clear events). Do not block.

### Zones

- **Goal zones**: Agents must be on a goal cell to use `submit`.
- **Role zones**: Agents must be on a role cell to use `adopt`.

## Actions

In each step, an agent executes exactly one action. All parameters are strings.

### skip

Does nothing. Always successful.

### move

Moves the agent in specified directions. Multiple directions can be given if the agent's speed allows.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0-* | direction | One of {n,s,e,w} |

| Failure Code | Reason |
|---|---|
| failed_parameter | No parameters or invalid direction |
| failed_path | First move was blocked |
| partial_success | First step worked but a later move was blocked |

Speed is determined by the agent's role and number of attached things. `speed[n]` gives max moves when *n* things are attached. If *n* >= len(speed), use last value. All things in the agent's connected component move together.

### attach

Attaches an adjacent thing (entity, block, obstacle) to the agent.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0 | direction | One of {n,s,e,w} |

| Failure Code | Reason |
|---|---|
| failed_parameter | Not a direction |
| failed_target | Nothing to attach |
| failed_blocked | Thing attached to opponent agent |
| failed | Too many things attached (attachLimit) |

### detach

Detaches a thing from the agent. Only removes the direct edge.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0 | direction | One of {n,s,e,w} |

| Failure Code | Reason |
|---|---|
| failed_parameter | Not a direction |
| failed_target | No attachment in that direction |
| failed | Thing exists but not attached to agent |

### rotate

Rotates all attached things 90° around the agent. The grid coordinate system has X increasing eastward and Y increasing southward. For the exact coordinate transform applied by clockwise and counter-clockwise rotation, consult the rotation reference traces (`/app/replays/replay_rotation.json` or query `/app/reference.db`).

| # | Parameter | Meaning |
|---|-----------|---------|
| 0 | direction | One of {cw, ccw} |

| Failure Code | Reason |
|---|---|
| failed_parameter | Not a rotation direction |
| failed | Target position blocked, or agent attached to another agent |

### connect

Two agents connect blocks attached to them. Both must execute `connect` in the same step, naming each other and specifying their own block's relative coordinates.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0 | agent | Partner agent name |
| 1 | x | X coordinate of own block (relative) |
| 2 | y | Y coordinate of own block (relative) |

The two specified blocks must be adjacent (Manhattan distance 1). After success, the blocks are connected and the attachment graphs of both agents merge into a single connected component.

| Failure Code | Reason |
|---|---|
| failed_parameter | Partner not valid or coords not integers |
| failed_partner | Partner action not connect or wrong params |
| failed_target | Block not at position or not attached |
| failed | Blocks not adjacent, already connected, or exceeds attachLimit |

### disconnect

Disconnects two attachments in the agent's component.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0/1 | x1/y1 | Relative coords of first attachment |
| 2/3 | x2/y2 | Relative coords of second attachment |

| Failure Code | Reason |
|---|---|
| failed_parameter | Invalid coords |
| failed_target | Not attachments of agent or not directly attached to each other |

### request

Requests a block from an adjacent dispenser. Block appears at the dispenser's cell.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0 | direction | One of {n,s,e,w} |

| Failure Code | Reason |
|---|---|
| failed_parameter | Not a direction |
| failed_target | No dispenser there |
| failed_blocked | Dispenser cell occupied |

### submit

Submit attached block pattern to complete a task. Agent must be on a goal zone. A task is available while the deadline step has not been exceeded — consult the deadline reference traces for exact boundary semantics.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0 | task | Name of an active task |

| Failure Code | Reason |
|---|---|
| failed_target | No active task with that name |
| failed | Blocks don't match requirements, or agent not on goal zone |

On success, blocks matching the task requirements are consumed (removed from grid and attachments). The team's score increases by the task's reward.

### clear

Clears a target cell. Costs energy. Removes blocks and obstacles at the target. Damages entities at the target if role's `maxDistance > 1`.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0/1 | x/y | Relative coords of target cell |

| Failure Code | Reason |
|---|---|
| failed_parameter | Invalid coords |
| failed_target | Outside vision |
| failed_location | Outside clear distance |
| failed_resources | Not enough energy |

Damage to an entity at the target depends on Manhattan distance from clearing agent: `clearDamage[distance]` (use last value if distance exceeds array length). If entity energy reaches 0, it is deactivated.

### adopt

Adopts a role. Agent must be in a role zone.

| # | Parameter | Meaning |
|---|-----------|---------|
| 0 | role | Role name |

| Failure Code | Reason |
|---|---|
| failed_parameter | Invalid role |
| failed_location | Not in role zone |

### survey

Surveys a target. Simplified: always succeeds.

### All actions

| Failure Code | Reason |
|---|---|
| failed_status | Agent is deactivated |
| failed_role | Role does not permit this action |
| unknown_action | Action type not recognized |

## Tasks

Tasks require specific block patterns attached to the submitting agent. Each requirement specifies a relative position (x, y) from the agent and a block type. All requirements must be met simultaneously.

## Norms

Norms enforce constraints during the steps where `start <= current_step <= until`.

### Carry norm

`requirements: [{"type": "block", "name": "any", "quantity": N}]`

Agents carrying more than N attachable things (blocks, obstacles, entities) are punished.

### Adopt norm

`requirements: [{"type": "role", "name": "<roleName>", "quantity": N}]`

Teams with more than N agents in the specified role are punished (all agents in that role for the violating team).

Punishment: energy is reduced by `punishment` value for violating agents. Agents whose energy is fully depleted may be deactivated as a consequence. Consult the norms reference traces for exact enforcement semantics.

## Grid Mechanics

- The grid is a torus: coordinates wrap modulo width (x-axis) and height (y-axis).
- Manhattan distance on the torus: `min(|dx|, width-|dx|) + min(|dy|, height-|dy|)`.
- X-axis goes east (right), Y-axis goes south (down).
- Directions: `n` = (0,-1), `s` = (0,+1), `e` = (+1,0), `w` = (-1,0).

## Rotation

- Attached things rotate 90° around the agent in the specified direction.
- The coordinate system has X increasing eastward and Y increasing southward.
- The agent itself does not move; all attached things rotate around the agent.
- If any target position is occupied by a non-component thing, the rotation fails.
- If the agent is attached to another agent, rotation fails.
- For the exact rotation transform formulas, analyze the rotation reference traces.

## Attachment Model

- Attachments form an undirected graph. Agents, blocks, and obstacles are nodes.
- `attach` creates an edge between the agent and an adjacent thing.
- `detach` removes the edge between the agent and an adjacent attached thing.
- `connect` creates an edge between two blocks belonging to different agents' components. The resulting connection must be symmetric — both agents see the merged component.
- `disconnect` removes an edge between two attached things in the agent's component.
- A "connected component" is all nodes reachable through attachment edges.
- Movement speed depends on `len(component) - 1` (number of attached things, excluding the agent).
- When an agent moves, the entire component translates by the same delta.
- When an agent is deactivated, all its attachment edges are removed.
