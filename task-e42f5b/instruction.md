A stripped shared library at `/app/libfairkalah.so` implements a variant of the Mancala (Kalah) family of pit-and-seed board games. The library exports several C functions whose signatures and the game's sowing mechanics are undocumented. You must reverse-engineer the library's API and deduce the variant's rules.

## Board layout

Follows the Kalah convention with `2h+2` positions:
- South pits: indices `0` to `h-1`
- South store: index `h`
- North pits: indices `h+1` to `2h`
- North store: index `2h+1`

South moves first. Game-theoretic value = `South_store − North_store` (South maximizes, North minimizes). When the game ends (either side's pits all empty), remaining seeds are collected into their respective stores.

Game traces from prior runs are at `/app/traces/games.json`. Positions to solve are in `/app/positions.json`. Binary analysis tools (`readelf`, `nm`, `objdump`, `gdb`, `strace`, `ltrace`) and `sqlite3` are pre-installed.

## Deliverables

1. **`/app/solve.py`** — Python CLI solver:
   ```
   python3 /app/solve.py <h> <board_csv> <side>
   ```
   Prints a single integer: the game-theoretic value under optimal play by both sides.

2. **`/app/results.json`** — Solutions for `/app/positions.json`:
   ```json
   {"initial": {"<h>_<s>": <value>, ...}, "positions": [<value>, ...]}
   ```

3. **`/app/endgame.db`** — SQLite database with the complete solved game tree for all non-terminal positions reachable from the (h=3, s=3) initial position. Required schema:
   ```sql
   CREATE TABLE endgame (
     board TEXT NOT NULL,
     side INTEGER NOT NULL,
     value INTEGER NOT NULL,
     best_move INTEGER,
     PRIMARY KEY (board, side)
   );
   ```
   `board` is comma-separated pit/store values. `best_move` is the optimal pit index for the side to move.

4. **`/app/analysis.json`** — Game-theoretic analysis:
   ```json
   {
     "sweep": {"2_1": <val>, ..., "4_3": <val>},
     "reachable_3_3": <integer>,
     "principal_variation_3_2": [
       {"side": 0, "pit": <int>, "board_after": [<int>, ...]},
       ...
     ]
   }
   ```
   - `sweep`: game-theoretic value for every initial config with h ∈ {2,3,4}, s ∈ {1,2,3} (keys like `"3_2"`)
   - `reachable_3_3`: count of unique non-terminal (board, side) states in the full (3,3) game tree
   - `principal_variation_3_2`: sequence of optimal moves for both sides from the (3,2) initial position through to game end