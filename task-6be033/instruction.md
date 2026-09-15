A tournament simulator `woa-sim` is installed at `/usr/local/bin/woa-sim`. It simulates "War of Attrition," a parameterized two-player turn-based strategy game with 8 tunable integer parameters and three AI strategies (`heuristic`, `aggressive`, `defensive`).

A reference game engine at `/app/game_engine.py` documents the basic rules but may not reflect the complete set of mechanics implemented by the actual simulator. Identify all discrepancies through empirical analysis or source inspection.

Run `woa-sim --help` for usage, `woa-sim --param-ranges` for parameter ranges, `woa-sim --list-strategies` for strategy descriptions. Configuration template at `/app/config_template.toml`, database schema at `/app/schema.sql`.

## Objective 1 — Mechanism Discovery

Identify all game mechanics present in the actual simulator but absent from the reference engine at `/app/game_engine.py`. Document findings in `/app/results/mechanics_report.json`:

```json
{"hidden_mechanics": [{"name": "<str>", "description": "<str>", "impact": "<str>"}, ...]}
```

## Objective 2 — Balance Optimization

Find parameter values producing balanced games across **all six** strategy matchup combinations. Constraints (verified with 300 games, seed=50000):

- **Per-matchup**: fairness (1 − 2·|win_rate − 0.5|) ≥ 0.72, decisiveness (1 − draw_rate) ≥ 0.72, depth ≥ 0.58, variety (action entropy / log₂4) ≥ 0.48
- **Cross-strategy**: no AI strategy may win more than 56% of its aggregate games
- **Overall composite** (mean of per-matchup composites) ≥ 0.80
- **Robustness** (seed=60000, 300 games): overall composite ≥ 0.70, no matchup composite < 0.50

## Objective 3 — Meta-Game Analysis

Compute the game-theoretic payoff matrix and mixed-strategy Nash equilibrium for the strategy-selection meta-game under your optimal parameters.

## Required Output Files in `/app/results/`

- `optimal_params.json` — `{"params": {"base_hp": <int>, "base_mana": <int>, "attack_damage": <int>, "defend_block": <int>, "charge_gain": <int>, "spell_damage": <int>, "spell_cost": <int>, "mana_regen": <int>}}`
- `mechanics_report.json` — hidden mechanics documentation (see above)
- `payoff_matrix.json` — `{"matrix": [[<float>, ...], ...], "strategies": ["heuristic", "aggressive", "defensive"]}` where `matrix[i][j]` = win rate of `strategies[i]` against `strategies[j]` (500 games, seed=50000)
- `nash_equilibrium.json` — `{"probabilities": {"heuristic": <float>, "aggressive": <float>, "defensive": <float>}, "expected_value": <float>}`
- `tournament.db` — SQLite database (conforming to `/app/schema.sql`) with ≥100 game records per matchup type
- `balance_report.json` — `{"matchups": {"<name>": {"fairness": <float>, "decisiveness": <float>, "depth": <float>, "variety": <float>, "composite": <float>}, ...}, "strategy_win_rates": {"heuristic": <float>, "aggressive": <float>, "defensive": <float>}, "overall_composite": <float>}`