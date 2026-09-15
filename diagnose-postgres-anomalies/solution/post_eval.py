#!/usr/bin/env python3
"""
Post-restart performance evaluation.
Reads baseline EXPLAIN costs captured before fixes, runs EXPLAIN again
after fixes and server restart, and writes the performance comparison.
"""

import json
import psycopg2


def main():
    with open('/app/.before_costs.json', 'r') as f:
        before = json.load(f)

    conn = psycopg2.connect(dbname='benchmark', user='postgres')
    conn.autocommit = True
    cur = conn.cursor()

    evaluations = []
    for qid, info in before.items():
        before_cost = info.get('cost')
        if before_cost is None:
            continue

        sql = info['sql']
        try:
            cur.execute("EXPLAIN (FORMAT JSON) " + sql)
            plan = cur.fetchone()[0]
            after_cost = plan[0]["Plan"]["Total Cost"]
        except Exception:
            continue

        if before_cost > 0:
            improvement = ((before_cost - after_cost) / before_cost) * 100
        else:
            improvement = 0.0

        evaluations.append({
            "query_id": qid,
            "query_sql": sql,
            "before_total_cost": round(before_cost, 2),
            "after_total_cost": round(after_cost, 2),
            "improvement_pct": round(improvement, 2)
        })

    conn.close()

    with open('/app/performance_eval.json', 'w') as f:
        json.dump({"evaluations": evaluations}, f, indent=2)

    print(f"Performance evaluation: {len(evaluations)} queries assessed.")
    for ev in evaluations:
        print(f"  {ev['query_id']}: {ev['before_total_cost']} -> "
              f"{ev['after_total_cost']} ({ev['improvement_pct']}% improvement)")


if __name__ == '__main__':
    main()
