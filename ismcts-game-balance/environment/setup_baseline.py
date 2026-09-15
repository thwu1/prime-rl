#!/usr/bin/env python3
"""Generate baseline game statistics database for analysis."""

import json
import sqlite3
import sys

sys.path.insert(0, '/app')

from game import GameConfig, play_game
from players import RandomPlayer, HeuristicPlayer


def main():
    conn = sqlite3.connect('/app/baseline.db')
    conn.execute('''CREATE TABLE game_results (
        game_id INTEGER PRIMARY KEY,
        config_json TEXT,
        p0_type TEXT,
        p1_type TEXT,
        winner INTEGER,
        p0_score INTEGER,
        p1_score INTEGER,
        num_tricks INTEGER
    )''')
    conn.execute('''CREATE TABLE config_summary (
        config_json TEXT,
        matchup TEXT,
        total_games INTEGER,
        p0_wins INTEGER,
        avg_total_points REAL,
        avg_tricks REAL
    )''')

    configs = []
    for ns in [3, 4, 5]:
        for cps in [6, 8]:
            total = ns * cps
            for hs in [6, 8, 10]:
                if 2 * hs > total or hs < 4:
                    continue
                for ts in [-1, 0]:
                    for ltb in [0, 5, 10, 15]:
                        pv = {}
                        for r_off in range(1, 6):
                            r = cps - r_off
                            if r >= 0:
                                pv[r] = [11, 10, 4, 3, 2][r_off - 1]
                        try:
                            cfg = GameConfig(ns, cps, hs, ts, pv, ltb)
                            cfg.validate()
                            configs.append(cfg)
                        except Exception:
                            pass

    game_id = 0
    n_games = 30
    for cfg in configs:
        cfg_json = json.dumps(cfg.to_dict())

        # Random vs Random
        p0w, tp, tt = 0, 0, 0
        for i in range(n_games):
            p0 = RandomPlayer(seed=game_id * 2)
            p1 = RandomPlayer(seed=game_id * 2 + 1)
            r = play_game(p0, p1, cfg, seed=game_id + 50000)
            conn.execute('INSERT INTO game_results VALUES (?,?,?,?,?,?,?,?)',
                         (game_id, cfg_json, 'random', 'random',
                          r['winner'], r['scores'][0], r['scores'][1],
                          r['num_tricks']))
            if r['winner'] == 0:
                p0w += 1
            tp += sum(r['scores'])
            tt += r['num_tricks']
            game_id += 1
        conn.execute('INSERT INTO config_summary VALUES (?,?,?,?,?,?)',
                     (cfg_json, 'random_vs_random', n_games, p0w,
                      tp / n_games, tt / n_games))

        # Heuristic vs Random
        p0w, tp, tt = 0, 0, 0
        for i in range(n_games):
            p0 = HeuristicPlayer(seed=game_id * 2)
            p1 = RandomPlayer(seed=game_id * 2 + 1)
            r = play_game(p0, p1, cfg, seed=game_id + 50000)
            conn.execute('INSERT INTO game_results VALUES (?,?,?,?,?,?,?,?)',
                         (game_id, cfg_json, 'heuristic', 'random',
                          r['winner'], r['scores'][0], r['scores'][1],
                          r['num_tricks']))
            if r['winner'] == 0:
                p0w += 1
            tp += sum(r['scores'])
            tt += r['num_tricks']
            game_id += 1
        conn.execute('INSERT INTO config_summary VALUES (?,?,?,?,?,?)',
                     (cfg_json, 'heuristic_vs_random', n_games, p0w,
                      tp / n_games, tt / n_games))

    conn.commit()
    conn.close()
    print(f"Generated baseline.db: {game_id} games across {len(configs)} configs")


if __name__ == '__main__':
    main()
