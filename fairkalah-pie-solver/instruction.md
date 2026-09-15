A Kalah game engine is at `/app/kalah.py` (standard rules only). A C implementation of fast Kalah state operations is at `/app/src/kalah_engine.c` with header `/app/src/kalah_engine.h` and build system `/app/Makefile`. Board positions to analyze are in `/app/positions.json`. An SQLite schema for endgame storage is at `/app/schema.sql`.

In FairKalah, the empty-pit capture rule is removed: when the last sown stone lands in an empty pit on the current player's side, no capture occurs and the stone simply stays. All other standard Kalah rules apply unchanged (counter-clockwise sowing skipping opponent's store, extra turn when last stone lands in own store, game ends when one side's pits are all empty, remaining stones collected by respective side).

The provided C library implements standard Kalah rules only. Extend it to support both standard and FairKalah rule variants (controlled by a `captures` parameter in `kalah_make_move`), compile it to `/app/libkalah.so` using the provided Makefile, and interface with it from Python via `ctypes` for all game-state operations during solving.

Build complete endgame databases for every valid Kalah(3,s) board state with s in {1, 2}, under both standard and FairKalah rules. A valid state distributes exactly 2*n*s stones non-negatively across the 2*(n+1) board positions (pits and stores). Store all solved entries in SQLite at `/app/endgame.db` following `/app/schema.sql`. Board keys are comma-separated board array values (e.g., `1,1,1,0,1,1,1,0`).

Solve each position in `/app/positions.json` under both rule variants, leveraging the endgame database where the position's (n, total_stones) matches a database configuration. For South-to-move positions, compute the FairKalah pie-rule equilibrium: after South completes their first turn (including any extra-turn chains from landing in own store), North chooses to accept (play continues normally) or swap (exchange sides); both players reason optimally about this choice.

Compute game balance statistics from the endgame database: for each (n, s, rule_variant) configuration, report the fraction of South-to-move states where South wins (value > 0), draws (value == 0), or loses (value < 0).

Write results to `/app/results.json`:
```json
{
  "positions": {
    "<position_id>": {
      "standard_value": <int>,
      "standard_best_move": <int>,
      "fairkalah_value": <int>,
      "fairkalah_best_move": <int>,
      "pie_rule_value": <int or null>,
      "pie_rule_first_moves": [<int>, ...] or null
    }
  },
  "balance": {
    "<n>_<s>_standard": {"south_win_frac": <float>, "draw_frac": <float>, "north_win_frac": <float>, "total_positions": <int>},
    "<n>_<s>_fairkalah": {"south_win_frac": <float>, "draw_frac": <float>, "north_win_frac": <float>, "total_positions": <int>}
  }
}
```

Move indices use the board array layout from `kalah.py` (South pits: 0 to n-1, North pits: n+1 to 2n). Values are South store minus North store under optimal play. `pie_rule_value` and `pie_rule_first_moves` are null when it is not South's turn. Fractions rounded to 6 decimal places.