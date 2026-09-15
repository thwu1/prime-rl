# Rail Simulation Schemas and Specifications

## State Transition Table

Conditions are evaluated top-to-bottom; first match wins.

| From | Condition | To |
|---|---|---|
| WAITING | in_malfunction | MALFUNCTION_OFF_MAP |
| WAITING | earliest_departure_reached | READY_TO_DEPART |
| WAITING | — | WAITING |
| READY_TO_DEPART | in_malfunction | MALFUNCTION_OFF_MAP |
| READY_TO_DEPART | movement_action_given AND movement_allowed | MOVING |
| READY_TO_DEPART | — | READY_TO_DEPART |
| MALFUNCTION_OFF_MAP | in_malfunction | MALFUNCTION_OFF_MAP |
| MALFUNCTION_OFF_MAP | NOT in_malfunction AND NOT earliest_departure_reached | WAITING |
| MALFUNCTION_OFF_MAP | NOT in_malfunction AND earliest_departure_reached AND movement_action_given AND movement_allowed | MOVING |
| MALFUNCTION_OFF_MAP | NOT in_malfunction AND earliest_departure_reached AND stop_action_given AND movement_allowed | STOPPED |
| MALFUNCTION_OFF_MAP | NOT in_malfunction AND earliest_departure_reached AND otherwise | READY_TO_DEPART |
| MOVING | in_malfunction | MALFUNCTION |
| MOVING | target_reached | DONE |
| MOVING | (stop_action_given AND new_speed_zero) OR NOT movement_allowed | STOPPED |
| MOVING | — | MOVING |
| STOPPED | in_malfunction | MALFUNCTION |
| STOPPED | movement_action_given AND movement_allowed | MOVING |
| STOPPED | — | STOPPED |
| MALFUNCTION | in_malfunction | MALFUNCTION |
| MALFUNCTION | NOT in_malfunction AND movement_action_given AND movement_allowed | MOVING |
| MALFUNCTION | NOT in_malfunction AND otherwise | STOPPED |
| DONE | — | DONE |

## Scenario JSON Input Schema

```json
{
  "agents": [
    {
      "handle": "<int: unique agent identifier>",
      "initial_position": ["<int: row>", "<int: col>"],
      "speed": "<float: initial speed, 0 to 1>",
      "max_speed": "<float: maximum speed, 0 to 1>",
      "target": ["<int: row>", "<int: col>"],
      "earliest_departure": "<int: 1-indexed step when agent may leave WAITING>"
    }
  ],
  "actions": [
    {
      "<handle_as_string>": "<int: action constant (0-4)>"
    }
  ],
  "max_steps": "<int: total simulation steps>"
}
```

All `handle` keys inside `actions` entries are **string** representations of the integer handle (e.g. `"0"`, `"1"`).

## Result JSON Output Schema

The CLI prints a JSON array to stdout. Each element corresponds to one simulation step:

```json
[
  {
    "step": "<int: 1-indexed step number>",
    "agents": {
      "<handle_as_string>": {
        "state": "<int: TrainState enum value (0-6)>",
        "position": ["<int: row>", "<int: col>"] or null,
        "speed": "<float: current speed>",
        "moving": "<bool: true iff state == MOVING>"
      }
    }
  }
]
```

`position` is `null` when the agent is off-map (WAITING, READY_TO_DEPART, MALFUNCTION_OFF_MAP) or DONE.

## SQLite Trace Database Schema

When invoked with `--trace-db <path>`, the simulator creates a SQLite database at that path with the following table:

```sql
CREATE TABLE agent_traces (
    step          INTEGER NOT NULL,
    agent_handle  INTEGER NOT NULL,
    state         INTEGER NOT NULL,
    position_row  INTEGER,
    position_col  INTEGER,
    speed         REAL    NOT NULL,
    moving        INTEGER NOT NULL,
    PRIMARY KEY (step, agent_handle)
);
```

Column mapping from JSON result:
- `step` ← result `step` field (1-indexed integer)
- `agent_handle` ← integer form of the handle key
- `state` ← `state` field (TrainState integer value)
- `position_row` ← first element of `position` array, or NULL if position is null
- `position_col` ← second element of `position` array, or NULL if position is null
- `speed` ← `speed` field (float)
- `moving` ← 1 if `moving` is true, 0 otherwise

Every step/agent combination from the JSON output must appear as a row in this table. The JSON output to stdout must still be produced regardless of whether `--trace-db` is specified.
