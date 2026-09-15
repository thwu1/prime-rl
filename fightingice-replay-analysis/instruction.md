`/app/replays/` contains binary protobuf-encoded replay data from a DareFightingICE-style fighting game tournament. The protobuf schema at `/app/proto/game.proto` was reconstructed from documentation and may not perfectly match the binary wire format of the replay files — you must validate and correct it if necessary. Tournament configuration is at `/app/tournament.json`.

Each `.bin` file is a serialized `MatchReplay` message with frame-by-frame game state and per-round results. `STD_` prefixed matches are Standard league (round-robin among 4 AIs); `SPD_` matches are Speedrunning league games against a baseline AI.

Produce `/app/output/results.json` with this structure:

```json
{
  "matches": [
    {
      "match_id": "STD_01",
      "p1_name": "...",
      "p2_name": "...",
      "rounds": [
        {"round": 1, "p1_hp": 280, "p2_hp": 0, "frames": 2400, "winner": "PlayerName"}
      ],
      "p1_total_damage": 0,
      "p2_total_damage": 0,
      "p1_total_hits": 0,
      "p2_total_hits": 0,
      "p1_max_combo_length": 0,
      "p2_max_combo_length": 0,
      "p1_max_combo_raw_damage": 0,
      "p2_max_combo_raw_damage": 0,
      "p1_max_combo_scaled_damage": 0.0,
      "p2_max_combo_scaled_damage": 0.0
    }
  ],
  "standard_league": {
    "rankings": [
      {"rank": 1, "ai": "...", "round_wins": 0, "total_remaining_hp": 0, "f1_points": 25}
    ]
  },
  "speedrunning_league": {
    "rankings": [
      {"rank": 1, "ai": "...", "avg_frames": 0.0, "f1_points": 25}
    ]
  },
  "elo_ratings": {"AI_Name": 1523.0},
  "final_rankings": [
    {"rank": 1, "ai": "...", "std_f1": 25, "spd_f1": 25, "elo_bonus": 2, "total_points": 52}
  ]
}
```

**Rules:**

- **Round winner**: higher remaining HP. Equal HP = draw (winner field omitted or "draw").
- **Combo detection**: a combo starts when a player lands a hit (`attack_landed=true`, `damage_dealt > 0`) with the receiver's `stun_remaining == 0`. Subsequent hits while `stun_remaining > 0` extend the combo. Minimum combo length is 2. Single hits are not combos.
- **Combo damage proration**: the `combo_scaling_factor` from `tournament.json` applies to successive combo hits. The n-th hit (0-indexed) has effective damage `raw_damage × factor^n`. Replays store raw (unscaled) damage. `max_combo_raw_damage` = highest sum of raw damages from any single combo. `max_combo_scaled_damage` = highest sum of scaled damages from any single combo (may come from a different combo).
- **Standard league**: rank competitors by total round wins across `STD_` matches. Tiebreak by sum of remaining HP. Assign F1 points from `f1_scoring.points` in config.
- **Speedrunning league**: for each competitor, average `elapsed_frames` across all rounds in their `SPD_` matches. Rounds the competitor lost use `penalty_frames` instead. Rank by lowest average. Assign F1 points.
- **Elo ratings**: process standard league matches in lexicographic `match_id` order, rounds sequentially within each match. Starting rating 1500 for all competitors. K=32. Expected score `E = 1 / (1 + 10^((R_opponent − R_self) / 400))`. Winner scores 1.0, loser 0.0, draw 0.5 each. Update: `R_new = R_old + K × (S − E)`. Report ratings rounded to 1 decimal place.
- **Final rankings**: total points = standard F1 + speedrunning F1 + Elo bonus (+2 for highest Elo rating, +1 for second highest, 0 for others). Tiebreak by Elo rating descending.