#!/usr/bin/env python3
"""Compute per-recipe composite scores and derive system ranking."""
import json
import sqlite3

DB_PATH = '/app/pipeline.db'
ALL_NUTRIENTS = ['energy', 'fat', 'saturates', 'sugars', 'protein', 'salt']
FSA_NUTRIENTS = ['fat', 'saturates', 'sugars', 'salt']


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    weights = json.loads(c.execute(
        "SELECT value FROM config WHERE key='composite_weights'").fetchone()[0])
    tolerance_weight = weights['fsa']
    fsa_weight = weights['tolerance']

    round_digits = int(c.execute(
        "SELECT value FROM config WHERE key='round_digits'").fetchone()[0])

    systems = [r[0] for r in c.execute(
        'SELECT DISTINCT system_name FROM tolerance_results '
        'ORDER BY system_name')]
    recipe_ids = [r[0] for r in c.execute(
        'SELECT DISTINCT recipe_id FROM tolerance_results '
        'ORDER BY recipe_id')]

    c.execute('DELETE FROM composite_scores')
    c.execute('DELETE FROM system_ranking')

    system_composites = {}

    for sys in systems:
        recipe_scores = []
        for rid in recipe_ids:
            tol_hits = c.execute(
                'SELECT SUM(within_tolerance) FROM tolerance_results '
                'WHERE system_name=? AND recipe_id=?',
                (sys, rid)).fetchone()[0]
            tol_frac = tol_hits / len(ALL_NUTRIENTS)

            fsa_correct = c.execute(
                'SELECT COUNT(*) FROM fsa_results '
                'WHERE system_name=? AND recipe_id=? '
                'AND true_label=predicted_label',
                (sys, rid)).fetchone()[0]
            fsa_frac = fsa_correct / len(FSA_NUTRIENTS)

            composite = tolerance_weight * tol_frac + fsa_weight * fsa_frac
            recipe_scores.append(composite)

            c.execute('INSERT INTO composite_scores VALUES (?,?,?,?,?)',
                      (sys, rid, tol_frac, fsa_frac, composite))

        system_composites[sys] = round(
            sum(recipe_scores) / len(recipe_scores), round_digits)

    ranking = sorted(system_composites,
                     key=system_composites.get, reverse=True)
    for i, sys in enumerate(ranking):
        c.execute('INSERT INTO system_ranking VALUES (?,?,?)',
                  (i + 1, sys, system_composites[sys]))

    conn.commit()
    conn.close()
    print("Scoring complete.")


if __name__ == '__main__':
    main()
