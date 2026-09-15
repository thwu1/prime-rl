A 20-player, 9-round FIDE Dutch Swiss chess tournament was managed with the bbpPairings engine (`/app/bbpPairings.exe`). After 5 rounds of play, a data migration corrupted the tournament report file. The pairing engine now refuses to generate round 6 pairings or validate the tournament state.

The corrupted tournament file is at `/app/tournament.trf`. Player reference data is in `/app/players.csv`. The bbpPairings source code and documentation are at `/app/bbpPairings-src/` (see `readme.txt` for CLI usage and TRF format details).

Diagnose all data integrity issues in the TRF file, repair it to restore a valid tournament state through round 5, and then complete the remaining four rounds. The original pairing and result data from rounds 1-5 must be preserved wherever the records are not corrupted.

## Result function for rounds 6-9

For each game, given the white player's ID, the black player's ID, and the 1-indexed round number:

```
seed = (white_id * 997 + black_id * 31 + round_num * 7919) % 100
```

- `seed < 45`: white wins (TRF result code `1` for white, `0` for black)
- `45 <= seed < 90`: black wins (`0` for white, `1` for black)
- `seed >= 90`: draw (`=` for both)

## Required outputs

- `/app/tournament_repaired.trf` — the repaired tournament with 5 rounds of correct data. Must pass `./bbpPairings.exe --dutch /app/tournament_repaired.trf -c`.

- `/app/tournament_complete.trf` — the completed 9-round tournament with rounds 6-9 paired by bbpPairings and results from the deterministic function above. Must pass `./bbpPairings.exe --dutch /app/tournament_complete.trf -c`.

- `/app/diagnosis.json` — a JSON object with an `"issues"` array where each entry documents a data integrity problem found and the correction applied.