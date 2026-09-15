#!/usr/bin/env python3
"""Court database query processor.

Reads queries from /app/queries.jsonl, resolves them against courts-db,
and writes results to /app/results.json.
"""
import json
from datetime import datetime, timedelta


from courts_db import find_court, find_court_by_id
from courts_db.utils import load_courts_db


def main():
    courts = load_courts_db()

    parent_map = {}
    for c in courts:
        p = c.get("parent")
        if p:
            parent_map.setdefault(p, []).append(c["id"])

    with open("/app/queries.jsonl") as f:
        queries = [json.loads(line) for line in f if line.strip()]

    results = {}

    for q in queries:
        qid = str(q["id"])
        qtype = q["type"]

        if qtype == "resolve":
            kwargs = {}
            if q.get("bankruptcy"):
                kwargs["bankruptcy"] = q["bankruptcy"]
            if q.get("date"):
                date_val = datetime.strptime(q["date"], "%Y-%m-%d")
            if q.get("location"):
                kwargs["location"] = q["location"]
            ids = find_court(court_str=q["text"], **kwargs)
            results[qid] = {"court_ids": sorted(ids)}

        elif qtype == "temporal_status":
            court_data = find_court_by_id(q["court_id"])
            if not court_data:
                results[qid] = {"active": False, "matching_range": None}
                continue
            court = court_data[0]
            date = datetime.strptime(q["date"], "%Y-%m-%d")
            found = False
            for d in court["dates"]:
                s = d.get("start")
                e = d.get("end")
                start = (
                    datetime.strptime(s, "%Y-%m-%d")
                    if s
                    else datetime(1600, 1, 1)
                )
                end = (
                    datetime.strptime(e, "%Y-%m-%d")
                    if e
                    else datetime(2100, 1, 1)
                )
                if start < date < end:
                    results[qid] = {
                        "active": True,
                        "matching_range": {"start": s, "end": e},
                    }
                    found = True
                    break
            if not found:
                results[qid] = {"active": False, "matching_range": None}

        elif qtype == "temporal_gaps":
            court_data = [c for c in courts if c["id"] == q["court_id"]]
            if not court_data:
                results[qid] = {"gaps": []}
                continue
            court = court_data[0]
            ranges = []
            for d in court["dates"]:
                start_val = d.get("start") if d.get("start") else "0001-01-01"
                end_val = d.get("end")
                ranges.append({"start": start_val, "end": end_val})
            ranges.sort(key=lambda x: x["start"])
            gaps = []
            for i in range(len(ranges) - 1):
                end_str = ranges[i].get("end")
                next_start = ranges[i + 1]["start"]
                if end_str and end_str < next_start:
                    end_dt = datetime.strptime(
                        end_str, "%Y-%m-%d"
                    ) + timedelta(days=1)
                    start_dt = datetime.strptime(
                        next_start, "%Y-%m-%d"
                    ) - timedelta(days=1)
                    gaps.append(
                        {
                            "start": end_dt.strftime("%Y-%m-%d"),
                            "end": start_dt.strftime("%Y-%m-%d"),
                        }
                    )
            results[qid] = {"gaps": gaps}

        elif qtype == "hierarchy":
            ancestors = []
            current = q["court_id"]
            visited = set()
            while True:
                cd = [c for c in courts if c["id"] == current]
                if not cd:
                    break
                p = cd[0].get("parent")
                if not p or p in visited:
                    break
                ancestors.append(p)
                visited.add(p)
                current = p

            descendants = sorted(parent_map.get(q["court_id"], []))
            results[qid] = {
                "ancestors": ancestors,
                "descendants": descendants,
            }

        elif qtype == "collisions":
            target_name = q["name"]
            matching = [
                {"id": c["id"], "location": c.get("location", "")}
                for c in courts
                if target_name.lower() in c["name"].lower()
            ]
            matching.sort(key=lambda x: x["id"])
            results[qid] = {"courts": matching}

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote {len(results)} results to /app/results.json")


if __name__ == "__main__":
    main()
