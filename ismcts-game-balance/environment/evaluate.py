"""Balance evaluation and analysis utilities for the trick-taking card game."""

import json
import sqlite3
from game import GameConfig, play_game
from players import RandomPlayer


def evaluate_random_balance(config: GameConfig, num_games: int = 500,
                            seed_base: int = 0) -> dict:
    """Evaluate balance using Random vs Random games."""
    p0_wins = 0
    draws = 0
    total_points = 0
    total_tricks = 0

    for i in range(num_games):
        p0 = RandomPlayer(seed=seed_base + i * 2)
        p1 = RandomPlayer(seed=seed_base + i * 2 + 1)
        result = play_game(p0, p1, config, seed=seed_base + 10000 + i)
        if result['winner'] == 0:
            p0_wins += 1
        elif result['winner'] == -1:
            draws += 1
        total_points += sum(result['scores'])
        total_tricks += result['num_tricks']

    return {
        'p0_win_rate': p0_wins / num_games,
        'draw_rate': draws / num_games,
        'avg_total_points': total_points / num_games,
        'avg_tricks': total_tricks / num_games,
        'num_games': num_games,
    }


def check_balance_criteria(metrics: dict) -> dict:
    """Check whether metrics satisfy all balance criteria."""
    results = {
        'first_player_balanced': 0.43 <= metrics['p0_win_rate'] <= 0.57,
        'sufficient_points': metrics['avg_total_points'] > 30,
        'good_game_length': 6 <= metrics['avg_tricks'] <= 16,
    }
    results['all_passed'] = all(results.values())
    return results


def init_analysis_db(path='/app/analysis.db'):
    """Initialize analysis database with required tables."""
    conn = sqlite3.connect(path)
    conn.execute('''CREATE TABLE IF NOT EXISTS search_results (
        config_json TEXT,
        win_rate_p0 REAL,
        avg_points REAL,
        avg_tricks REAL,
        skill_rate REAL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chosen_config (
        config_json TEXT,
        metric_name TEXT,
        metric_value REAL
    )''')
    conn.commit()
    return conn


def store_search_result(conn, config, wr, pts, tricks, skill=None):
    """Store a parameter search result."""
    conn.execute('INSERT INTO search_results VALUES (?, ?, ?, ?, ?)',
                 (json.dumps(config.to_dict()), wr, pts, tricks, skill))
    conn.commit()


def store_chosen_config(conn, config, metrics):
    """Store the chosen optimal configuration with its metrics."""
    cfg_json = json.dumps(config.to_dict())
    for name, val in metrics.items():
        if isinstance(val, (int, float)):
            conn.execute('INSERT INTO chosen_config VALUES (?, ?, ?)',
                         (cfg_json, name, float(val)))
    conn.commit()


if __name__ == '__main__':
    config = GameConfig()
    print("Default configuration balance:")
    metrics = evaluate_random_balance(config, num_games=500)
    print(json.dumps(metrics, indent=2))
    checks = check_balance_criteria(metrics)
    print(json.dumps(checks, indent=2))
