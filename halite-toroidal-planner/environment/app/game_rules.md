# Halite III Game Simulator Rules

## Grid

The game takes place on a **toroidal** (wrapping) grid of width `W` and height `H`. Positions are `(x, y)` where `x` is the column (0 to W-1, left to right) and `y` is the row (0 to H-1, top to bottom).

**Position normalization**: `(x % W, y % H)`

**Manhattan distance on torus**: `min(|x1-x2|, W - |x1-x2|) + min(|y1-y2|, H - |y1-y2|)`

**Directions**:
- North: `(0, -1)` (y decreases)
- South: `(0, +1)` (y increases)
- East: `(+1, 0)` (x increases)
- West: `(-1, 0)` (x decreases)

All resulting positions are normalized (wrapped).

## Entities

- **Ship**: Has `id` (int), `owner` (player id), position `(x, y)`, and `halite` cargo (0 to `MAX_HALITE`).
- **Shipyard**: One per player. Ships deposit halite here. Position `(x, y)`.
- **Dropoff**: Built by converting a ship. Also a deposit point. Has `id`, position.

## Turn Execution Order

Each turn processes in this exact order:

### 1. Update Inspiration

For each ship, determine if it is **inspired**: count the number of ships belonging to **other** players within `INSPIRATION_RADIUS` Manhattan distance. If that count >= `INSPIRATION_SHIP_COUNT` and `INSPIRATION_ENABLED` is true, the ship is inspired for this turn.

### 2. Spawn

If a player issues a `spawn` command, has >= `SHIP_COST` stored halite, and no entity currently occupies the shipyard cell, a new ship is created at the shipyard with 0 cargo. `SHIP_COST` is deducted from the player's stored halite.

### 3. Move / Construct

**Move**: For each ship with a move command (`north`/`south`/`east`/`west`):
- Compute movement cost from the **origin cell**: `ceil(origin_cell_halite / MOVE_COST_RATIO)`. If the ship is inspired, use `INSPIRED_MOVE_COST_RATIO` instead. If origin cell halite is 0, cost is 0.
- If the ship's cargo >= cost: deduct cost from cargo, move ship to the new position (normalized).
- If the ship's cargo < cost: move is **rejected**. Ship stays in place and will mine in step 5.

**Construct**: For each ship with a `construct` command:
- Credit the player with the ship's cargo + the cell's halite.
- Deduct `DROPOFF_COST` from the player's stored halite.
- Create a dropoff at the ship's position. Set cell halite to 0. Remove the ship.

### 4. Collision Resolution

After all movements, check for cells occupied by 2+ ships (from any player). For each such cell:
- **All** ships on that cell are destroyed.
- The sum of all destroyed ships' cargo is added to the cell's halite.

### 5. Mining

For each ship that did **not** move this turn (either stayed still, had its move rejected, or had no command) and is still alive after collision resolution:
- Compute base extraction: `ceil(cell_halite / EXTRACT_RATIO)`. If inspired, use `INSPIRED_EXTRACT_RATIO`.
- Cap extraction at `MAX_HALITE - ship_cargo` (cannot exceed ship capacity).
- Add the capped extraction to the ship's cargo. Subtract it from the cell's halite.
- If the ship is **inspired**: compute bonus = `INSPIRED_BONUS_MULTIPLIER * capped_extraction`. Cap the bonus at `MAX_HALITE - ship_cargo` (after base extraction was added). Add the capped bonus to the ship's cargo. The cell does **not** lose the bonus amount.

### 6. Deposit

For each ship currently on a **friendly** structure (shipyard or dropoff):
- Add the ship's entire cargo to the player's stored halite.
- Set the ship's cargo to 0.

## Default Constants

| Constant | Default Value |
|---|---|
| `MAX_HALITE` | 1000 |
| `SHIP_COST` | 1000 |
| `DROPOFF_COST` | 4000 |
| `EXTRACT_RATIO` | 4 |
| `MOVE_COST_RATIO` | 10 |
| `INSPIRATION_ENABLED` | true |
| `INSPIRATION_RADIUS` | 4 |
| `INSPIRATION_SHIP_COUNT` | 2 |
| `INSPIRED_EXTRACT_RATIO` | 4 |
| `INSPIRED_BONUS_MULTIPLIER` | 2 |
| `INSPIRED_MOVE_COST_RATIO` | 10 |

## Scenario JSON Format

```json
{
  "width": 12,
  "height": 12,
  "halite_grid": [[...], ...],
  "players": [
    {
      "id": 0,
      "halite": 5000,
      "shipyard": {"x": 0, "y": 0},
      "ships": [{"id": 0, "x": 0, "y": 0, "halite": 0}],
      "dropoffs": []
    }
  ],
  "constants": { ... },
  "max_turns": 40,
  "target_halite_gain": 600
}
```

The `halite_grid` is indexed as `halite_grid[y][x]` (row-major, y is row, x is column).
