#!/usr/bin/env python3
"""
Parameter search for balanced game configuration.

"""

import json
import sys

sys.path.insert(0, '/app')

from game import GameConfig, play_game
from players import RandomPlayer
from ai_player import AIPlayer
from evaluate import (evaluate_random_balance, init_analysis_db,
                      store_search_result, store_chosen_config)


def eval_skill(cfg, n=25, base=99):
    w = 0
    for i in range(n):
        r = play_game(AIPlayer(budget=200, seed=base + i * 7),
                      RandomPlayer(seed=base + i * 13 + 1),
                      cfg, seed=base + 20000 + i)
        if r['winner'] == 0:
            w += 1
    return w / n


def generate_candidates():
    configs = []
    for ns in [3, 4, 5]:
        for cps in [6, 8]:
            for ts in [-1, 0]:
                for ltb in [0, 5, 10, 15]:
                    total = ns * cps
                    for hs in [8, 10, 12]:
                        if 2 * hs > total or hs < 6:
                            continue
                        pvs = [
                            {cps - 1: 11, cps - 2: 10, cps - 3: 4,
                             cps - 4: 3, cps - 5: 2},
                            {cps - 1: 5, cps - 2: 4, cps - 3: 3,
                             cps - 4: 2, cps - 5: 1},
                        ]
                        for pv in pvs:
                            pv = {k: v for k, v in pv.items() if k >= 0}
                            cfg = GameConfig(ns, cps, hs, ts, pv, ltb)
                            try:
                                cfg.validate()
                                configs.append(cfg)
                            except Exception:
                                pass
    return configs


def main():
    # Initialize analysis database
    conn = init_analysis_db('/app/analysis.db')

    candidates = generate_candidates()
    print(f"Evaluating {len(candidates)} configurations...")

    best = None
    best_dist = 1.0

    for i, cfg in enumerate(candidates):
        metrics = evaluate_random_balance(cfg, num_games=200)
        wr = metrics['p0_win_rate']
        pts = metrics['avg_total_points']
        tricks = metrics['avg_tricks']

        if not (0.43 <= wr <= 0.57) or pts <= 30 or not (6 <= tricks <= 16):
            store_search_result(conn, cfg, wr, pts, tricks)
            continue

        dist = abs(wr - 0.50)
        if dist < best_dist:
            sr = eval_skill(cfg, n=20)
            store_search_result(conn, cfg, wr, pts, tricks, sr)
            if sr >= 0.55:
                best = cfg
                best_dist = dist
                print(f"  #{i}: wr={wr:.3f} pts={pts:.0f} skill={sr:.2f} "
                      f"cfg={cfg.to_dict()}")
        else:
            store_search_result(conn, cfg, wr, pts, tricks)

    if best is None:
        print("No config found via search, using fallback.")
        best = GameConfig(
            num_suits=4, cards_per_suit=8, hand_size=10,
            trump_suit=-1,
            point_values={7: 5, 6: 4, 5: 3, 4: 2, 3: 1},
            last_trick_bonus=5,
        )

    # Store chosen config metrics
    final_metrics = evaluate_random_balance(best, num_games=300)
    store_chosen_config(conn, best, final_metrics)
    conn.close()

    # Write JSON
    with open('/app/optimal_params.json', 'w') as f:
        json.dump(best.to_dict(), f, indent=2)
    print(f"Saved optimal_params.json: {best.to_dict()}")


if __name__ == '__main__':
    main()
