#!/usr/bin/env python3
"""Classify nutrient values using the UK FSA front-of-pack traffic-light system."""
import sqlite3

DB_PATH = '/app/pipeline.db'
FSA_NUTRIENTS = ['fat', 'saturates', 'sugars', 'salt']


def classify(value, low, high):
    """Assign an FSA traffic-light label to a nutrient value per 100 g."""
    if value < low:
        return 'green'
    elif value <= high:
        return 'amber'
    else:
        return 'red'


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    thresholds = {}
    for nut, low, high in c.execute('SELECT * FROM fsa_thresholds'):
        thresholds[nut] = (low, high)

    systems = [r[0] for r in c.execute(
        'SELECT DISTINCT system_name FROM predictions ORDER BY system_name')]
    recipe_ids = [r[0] for r in c.execute(
        'SELECT DISTINCT recipe_id FROM recipes ORDER BY recipe_id')]

    c.execute('DELETE FROM fsa_results')

    for sys in systems:
        for rid in recipe_ids:
            for nut in FSA_NUTRIENTS:
                actual = c.execute(
                    'SELECT actual_value FROM recipes '
                    'WHERE recipe_id=? AND nutrient=?',
                    (rid, nut)).fetchone()[0]
                predicted = c.execute(
                    'SELECT predicted_value FROM predictions '
                    'WHERE system_name=? AND recipe_id=? AND nutrient=?',
                    (sys, rid, nut)).fetchone()[0]

                low, high = thresholds[nut]
                true_label = classify(actual, low, high)
                pred_label = classify(predicted, low, high)

                c.execute('INSERT INTO fsa_results VALUES (?,?,?,?,?)',
                          (sys, rid, nut, true_label, pred_label))

    conn.commit()
    conn.close()
    print("FSA labeling complete.")


if __name__ == '__main__':
    main()
