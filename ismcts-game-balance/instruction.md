`/app/` contains a two-player trick-taking card game engine with partial observability. Each player is dealt cards from a shuffled deck; the remainder forms a hidden talon. Players alternate playing tricks — the follower must follow suit if able. Trump beats non-trump; higher rank beats lower within the same suit. Neither player sees the opponent's hand or the talon.

## Files

- `/app/game.py`: `GameConfig` (configurable rules), `GameState` (forward model with `get_legal_actions()`, `apply_action()`, `clone()`, `get_unseen_cards(player)`), `play_game()`.
- `/app/players.py`: `AbstractPlayer`, `RandomPlayer`, `HeuristicPlayer` (trump-aware strategy).
- `/app/ai_player.py`: Skeleton `AIPlayer` — implement this.
- `/app/evaluate.py`: Balance evaluation utilities and SQLite helpers (`init_analysis_db`, `store_search_result`, `store_chosen_config`).
- `/app/baseline.db`: Historical game results across configurations. Query to inform your parameter search.
- `/app/Makefile`: Benchmarking targets.

## Deliverables

1. **`/app/ai_player.py`**: Complete the `AIPlayer` to handle hidden information. Must beat `RandomPlayer` in ≥56% of 50 games and `HeuristicPlayer` in ≥52% of 80 games.

2. **`/app/optimal_params.json`**: JSON game configuration (loadable via `GameConfig.from_dict()`) satisfying: first-player win rate ∈ [0.43, 0.57] over 500 Random-vs-Random games, `AIPlayer(budget=200)` beats `RandomPlayer` in ≥56% of 50 games, average total points > 30, average tricks ∈ [6, 16].

3. **`/app/analysis.db`**: SQLite database with table `search_results` (`config_json TEXT, win_rate_p0 REAL, avg_points REAL, avg_tricks REAL, skill_rate REAL`, ≥5 rows) and table `chosen_config` (`config_json TEXT, metric_name TEXT, metric_value REAL`, ≥1 row).