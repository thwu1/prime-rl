A tactical unit deployment game engine at `/app/engine.py` with configuration at `/app/config.json` simulates matches between six strategy archetypes. Each strategy deploys warriors, mages, and archers across three lanes, with outcomes governed by a configurable type-matchup table (warriors beat archers, archers beat mages, mages beat warriors — with asymmetric multipliers).

Perform a full meta-game analysis and balance optimization. Write all results to `/app/results/`:

**`payoff_matrix.csv`** — 6×6 CSV where entry (i, j) is the win rate of strategy i against strategy j. Strategy names serve as both row and column headers. Diagonal entries should be 0.5. Use at least 1000 games per matchup for statistical accuracy.

**`nash_equilibrium.json`** — JSON containing at minimum an `"equilibrium"` key mapping each strategy name to its Nash Equilibrium mixed-strategy probability for this two-player zero-sum game.

**`balanced_config.json`** — A modified copy of `/app/config.json` where only `matchup_table` values are changed to yield a higher-entropy Nash Equilibrium (improved meta-game balance). All strategy definitions (unit counts, `lane_weights`, `noise`) must remain identical to the original.