#!/usr/bin/env python3
"""Paired bootstrap significance testing between adjacent ranked systems."""
import json
import random
import sqlite3

DB_PATH = '/app/pipeline.db'


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    boot_cfg = json.loads(c.execute(
        "SELECT value FROM config WHERE key='bootstrap'").fetchone()[0])
    n_resamples = boot_cfg['n_resamples']
    seed = boot_cfg['random_seed']

    sig_level = float(c.execute(
        "SELECT value FROM config WHERE key='significance_level'").fetchone()[0])
    round_digits = int(c.execute(
        "SELECT value FROM config WHERE key='round_digits'").fetchone()[0])

    ranking = [r[0] for r in c.execute(
        'SELECT system_name FROM system_ranking ORDER BY rank_order')]
    recipe_ids = [r[0] for r in c.execute(
        'SELECT DISTINCT recipe_id FROM composite_scores ORDER BY recipe_id')]

    c.execute('DELETE FROM significance_results')

    rng = random.Random(seed)

    for i in range(len(ranking) - 1):
        sys_a, sys_b = ranking[i], ranking[i + 1]

        diffs = []
        for rid in recipe_ids:
            sa = c.execute(
                'SELECT composite FROM composite_scores '
                'WHERE system_name=? AND recipe_id=?',
                (sys_a, rid)).fetchone()[0]
            sb = c.execute(
                'SELECT composite FROM composite_scores '
                'WHERE system_name=? AND recipe_id=?',
                (sys_b, rid)).fetchone()[0]
            diffs.append(sa - sb)

        observed_mean = sum(diffs) / len(diffs)

        n = len(diffs)
        count_extreme = 0
        for _ in range(n_resamples):
            sample = [diffs[rng.randint(0, n - 1)] for _ in range(n)]
            boot_mean = sum(sample) / n
            if abs(boot_mean) >= abs(observed_mean):
                count_extreme += 1

        p_value = round((count_extreme + 1) / (n_resamples + 1), round_digits)
        pair_key = f"{sys_a}_vs_{sys_b}"

        c.execute('INSERT INTO significance_results VALUES (?,?,?)',
                  (pair_key, p_value, 1 if p_value < sig_level else 0))

    conn.commit()
    conn.close()
    print("Significance testing complete.")


if __name__ == '__main__':
    main()
