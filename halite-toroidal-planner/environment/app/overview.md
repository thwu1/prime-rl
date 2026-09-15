# Halite III — Game Overview

Halite III is a resource-collection game played on a two-dimensional grid with **toroidal topology** (edges wrap around in both dimensions). Players control fleets of ships that navigate the grid, extract a resource called **halite** from cells, and deliver it to structures for scoring.

## Grid and Movement

The board is a rectangle of width W and height H. Positions are `(x, y)` coordinates where x is the column and y is the row. Moving off one edge wraps to the opposite side. Ships move one cell per turn in a cardinal direction (north, south, east, west) or remain still.

Moving is not free — each move deducts a cost from the ship's cargo that depends on the halite present in the cell the ship is leaving. A ship that cannot afford the movement cost is forced to stay in place.

## Mining

A ship that stays still on a cell extracts a portion of the cell's halite into its cargo. Ships have a maximum cargo capacity.

## Structures and Deposit

Each player starts with a **shipyard**. Ships can also be converted into **dropoffs** (permanent deposit points) at a cost. Whenever a ship occupies a cell with a friendly structure (shipyard or dropoff), its cargo is automatically transferred to the player's stored halite.

## Spawning

New ships can be created at the shipyard if the player has sufficient stored halite and the shipyard cell is unoccupied.

## Collisions

If two or more ships end up on the same cell after movement, all ships at that cell are destroyed.

## Inspiration

When a ship is near a sufficient number of enemy ships, it becomes **inspired** and receives a bonus when mining. The details of how inspiration is triggered and what bonus it provides must be determined from the replay data.

## Data

Recorded game replays are available under `/app/replays/`. Each game directory contains:

- `metadata.json` — Grid dimensions and the game constants used by the engine
- `turn_000.json` — Initial game state (turn 0)
- `commands_000.json` — Commands issued during turn 0
- `turn_001.json` — Game state after executing commands from turn 0
- ... and so on for each subsequent turn

Each turn file contains the full halite grid (indexed as `halite_grid[y][x]`) and each player's stored halite, ship states, shipyard position, and dropoff positions.

Planning scenarios are in `/app/scenarios/` as JSON files containing a starting state, constants, turn limit (`max_turns`), and a target halite gain (`target_halite_gain`).
