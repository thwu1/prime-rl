A protobuf-serialized character move set for the fighting game character ZEN is at `/app/data/character_zen.bin`. The protobuf schema is at `/app/protos/game.proto`. The game mechanics — move phase timing, cancel/combo systems, and neutral-game interaction model — are described in `/app/data/rules.json`.

Build an analysis pipeline that compiles the proto schema, deserializes the binary character data, and produces six analysis outputs in `/app/output/`:

- **`frame_advantage.json`** — Per-move frame advantage on hit and on block, derived from move phase timing and stun mechanics.

- **`optimal_combos.json`** — Maximum-damage combo sequences for each move at each energy level, respecting cancel chains, energy tracking, stun decay, damage scaling, and all termination conditions.

- **`punish_table.json`** — Optimal punishment for each move after it is blocked, based on the frame advantage window and eligible starter restrictions, evaluated at the reference energy level.

- **`payoff_matrix.json`** — The zero-sum payoff matrix for the ZEN mirror matchup's neutral game, encoding all attack/throw/block interaction categories with correct payoff derivation.

- **`dominance_analysis.json`** — Iterated elimination of strictly dominated strategies (IESDS) on the payoff matrix, checking mixed-strategy dominance via linear programming at each round.

- **`nash_equilibrium.json`** — The minimax optimal mixed strategy and game value derived from the payoff matrix via linear programming.

Frame advantage formulas, combo timing constraints, and damage scaling calculations must be derived from the conceptual mechanics descriptions in the rules — they are not given as explicit equations.