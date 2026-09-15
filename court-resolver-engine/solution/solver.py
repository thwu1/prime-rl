#!/usr/bin/env python3
"""Reference solver for court-resolver-debug task.

Correct implementation that fixes all bugs from the provided resolver.py:
1. resolve: properly checks bankruptcy with `is not None` instead of truthiness
2. resolve: passes date_found to find_court instead of computing but ignoring it
3. temporal_status: uses inclusive <= comparison instead of exclusive <
4. temporal_gaps: filters out null-start date ranges before gap computation
5. temporal_gaps: uses raw boundary dates without day adjustment
6. hierarchy: recursively collects all descendants via BFS, not just direct children
7. collisions: uses exact name equality instead of substring matching
"""
import json
from datetime import datetime


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
            if q.get("bankruptcy") is not None:
                kwargs["bankruptcy"] = q["bankruptcy"]
            if q.get("date"):
                kwargs["date_found"] = datetime.strptime(q["date"], "%Y-%m-%d")
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
                if start <= date <= end:
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
            ranges = [
                d for d in court["dates"] if d.get("start") is not None
            ]
            ranges.sort(key=lambda d: d["start"])
            gaps = []
            for i in range(len(ranges) - 1):
                end_str = ranges[i].get("end")
                next_start = ranges[i + 1]["start"]
                if end_str and end_str < next_start:
                    gaps.append({"start": end_str, "end": next_start})
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

            descendants = []
            queue = [q["court_id"]]
            desc_visited = {q["court_id"]}
            while queue:
                pid = queue.pop(0)
                for child in parent_map.get(pid, []):
                    if child not in desc_visited:
                        descendants.append(child)
                        desc_visited.add(child)
                        queue.append(child)

            results[qid] = {
                "ancestors": ancestors,
                "descendants": sorted(descendants),
            }

        elif qtype == "collisions":
            target_name = q["name"]
            matching = [
                {"id": c["id"], "location": c.get("location", "")}
                for c in courts
                if c["name"] == target_name
            ]
            matching.sort(key=lambda x: x["id"])
            results[qid] = {"courts": matching}

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote results for {len(results)} queries to /app/results.json")


if __name__ == "__main__":
    main()
