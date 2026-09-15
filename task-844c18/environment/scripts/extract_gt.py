#!/usr/bin/env python3
"""Extract ground truth from capsules SQLite database to JSON format."""

import sqlite3
import json


def main():
    conn = sqlite3.connect('/app/capsules.db')
    c = conn.cursor()

    capsules = c.execute(
        'SELECT capsule_id, field, language FROM capsules ORDER BY rowid'
    ).fetchall()

    result = []

    for cap_id, field, lang in capsules:
        runs = c.execute(
            'SELECT run_number FROM runs WHERE capsule_id=? ORDER BY run_number',
            (cap_id,)
        ).fetchall()

        results_list = []
        for (run_num,) in runs:
            run_data = {}

            # Numeric metrics
            for row in c.execute(
                'SELECT metric, value FROM numeric_results '
                'WHERE capsule_id=? AND run_number=?',
                (cap_id, run_num)
            ):
                run_data[row[0]] = row[1]

            # String metrics
            for row in c.execute(
                'SELECT metric, value FROM string_results '
                'WHERE capsule_id=? AND run_number=?',
                (cap_id, run_num)
            ):
                run_data[row[0]] = row[1]

            # List metrics
            list_metrics = c.execute(
                'SELECT DISTINCT metric FROM list_results '
                'WHERE capsule_id=? AND run_number=?',
                (cap_id, run_num)
            ).fetchall()
            for (metric,) in list_metrics:
                elements = c.execute(
                    'SELECT element FROM list_results '
                    'WHERE capsule_id=? AND run_number=? AND metric=? '
                    'ORDER BY position',
                    (cap_id, run_num, metric)
                ).fetchall()
                run_data[metric] = [e[0] for e in elements]

            results_list.append(run_data)

        result.append({
            'capsule_id': cap_id,
            'field': field,
            'language': lang,
            'results': results_list
        })

    with open('/app/build/ground_truth.json', 'w') as f:
        json.dump(result, f, indent=2)

    conn.close()
    print("Ground truth extracted to /app/build/ground_truth.json")


if __name__ == '__main__':
    main()
