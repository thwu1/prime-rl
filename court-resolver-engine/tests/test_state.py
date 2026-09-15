"""Tests for court-resolver-debug task."""
import json
import pytest
from datetime import datetime


from courts_db import find_court, find_court_by_id
from courts_db.utils import load_courts_db


# --- Module-level data loading ---

COURTS = load_courts_db()

PARENT_MAP = {}
for _c in COURTS:
    _p = _c.get("parent")
    if _p:
        PARENT_MAP.setdefault(_p, []).append(_c["id"])


def _load_results():
    try:
        with open("/app/results.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_queries():
    try:
        with open("/app/queries.jsonl") as f:
            qs = [json.loads(line) for line in f if line.strip()]
            return {str(q["id"]): q for q in qs}
    except FileNotFoundError:
        return {}


RESULTS = _load_results()
QUERIES = _load_queries()


# --- Expected-value computation ---

def expected_resolve(q):
    kwargs = {}
    if q.get("bankruptcy") is not None:
        kwargs["bankruptcy"] = q["bankruptcy"]
    if q.get("date"):
        kwargs["date_found"] = datetime.strptime(q["date"], "%Y-%m-%d")
    if q.get("location"):
        kwargs["location"] = q["location"]
    return sorted(find_court(court_str=q["text"], **kwargs))


def expected_temporal_status(q):
    court_data = find_court_by_id(q["court_id"])
    if not court_data:
        return {"active": False, "matching_range": None}
    court = court_data[0]
    date = datetime.strptime(q["date"], "%Y-%m-%d")
    for d in court["dates"]:
        s = d.get("start")
        e = d.get("end")
        start = datetime.strptime(s, "%Y-%m-%d") if s else datetime(1600, 1, 1)
        end = datetime.strptime(e, "%Y-%m-%d") if e else datetime(2100, 1, 1)
        if start <= date <= end:
            return {"active": True, "matching_range": {"start": s, "end": e}}
    return {"active": False, "matching_range": None}


def expected_temporal_gaps(q):
    court_data = [c for c in COURTS if c["id"] == q["court_id"]]
    if not court_data:
        return {"gaps": []}
    court = court_data[0]
    ranges = [d for d in court["dates"] if d.get("start") is not None]
    ranges.sort(key=lambda d: d["start"])
    gaps = []
    for i in range(len(ranges) - 1):
        end_str = ranges[i].get("end")
        next_start = ranges[i + 1]["start"]
        if end_str and end_str < next_start:
            gaps.append({"start": end_str, "end": next_start})
    return {"gaps": gaps}


def expected_hierarchy(q):
    ancestors = []
    current = q["court_id"]
    visited = set()
    while True:
        cd = [c for c in COURTS if c["id"] == current]
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
        for child in PARENT_MAP.get(pid, []):
            if child not in desc_visited:
                descendants.append(child)
                desc_visited.add(child)
                queue.append(child)
    return {"ancestors": ancestors, "descendants": sorted(descendants)}


def expected_collisions(q):
    matching = [
        {"id": c["id"], "location": c.get("location", "")}
        for c in COURTS if c["name"] == q["name"]
    ]
    matching.sort(key=lambda x: x["id"])
    return {"courts": matching}


# --- Structural tests ---

class TestStructure:
    def test_results_file_exists(self):
        assert len(RESULTS) > 0, "results.json is empty or missing"

    def test_queries_loaded(self):
        assert len(QUERIES) > 0, "queries.jsonl is empty or missing"

    def test_all_queries_have_results(self):
        missing = [qid for qid in QUERIES if qid not in RESULTS]
        assert not missing, f"Missing results for queries: {missing}"


# --- Resolve tests ---

RESOLVE_IDS = [str(i) for i in range(1, 19)]


class TestResolve:
    @pytest.mark.parametrize("qid", RESOLVE_IDS)
    def test_resolve(self, qid):
        q = QUERIES[qid]
        exp = expected_resolve(q)
        actual = sorted(RESULTS.get(qid, {}).get("court_ids", []))
        assert actual == exp, (
            f"Query {qid} text='{q['text'][:50]}' "
            f"expected={exp} got={actual}"
        )


# --- Temporal status tests ---

TEMPORAL_STATUS_IDS = [str(i) for i in range(19, 31)]


class TestTemporalStatus:
    @pytest.mark.parametrize("qid", TEMPORAL_STATUS_IDS)
    def test_temporal_status_active(self, qid):
        q = QUERIES[qid]
        exp = expected_temporal_status(q)
        actual = RESULTS.get(qid, {})
        assert actual.get("active") == exp["active"], (
            f"Query {qid} court={q['court_id']} date={q['date']} "
            f"active: expected={exp['active']} got={actual.get('active')}"
        )

    @pytest.mark.parametrize("qid", TEMPORAL_STATUS_IDS)
    def test_temporal_status_range(self, qid):
        q = QUERIES[qid]
        exp = expected_temporal_status(q)
        actual = RESULTS.get(qid, {})
        assert actual.get("matching_range") == exp["matching_range"], (
            f"Query {qid} court={q['court_id']} date={q['date']} "
            f"range: expected={exp['matching_range']} "
            f"got={actual.get('matching_range')}"
        )


# --- Temporal gaps tests ---

TEMPORAL_GAPS_IDS = [str(i) for i in range(31, 38)]


class TestTemporalGaps:
    @pytest.mark.parametrize("qid", TEMPORAL_GAPS_IDS)
    def test_temporal_gaps(self, qid):
        q = QUERIES[qid]
        exp = expected_temporal_gaps(q)
        actual = RESULTS.get(qid, {})
        assert actual.get("gaps") == exp["gaps"], (
            f"Query {qid} court={q['court_id']} "
            f"expected_gaps={exp['gaps']} got_gaps={actual.get('gaps')}"
        )


# --- Hierarchy tests ---

HIERARCHY_IDS = [str(i) for i in range(38, 44)]


class TestHierarchy:
    @pytest.mark.parametrize("qid", HIERARCHY_IDS)
    def test_hierarchy_ancestors(self, qid):
        q = QUERIES[qid]
        exp = expected_hierarchy(q)
        actual = RESULTS.get(qid, {})
        assert actual.get("ancestors") == exp["ancestors"], (
            f"Query {qid} court={q['court_id']} "
            f"ancestors: expected={exp['ancestors']} "
            f"got={actual.get('ancestors')}"
        )

    @pytest.mark.parametrize("qid", HIERARCHY_IDS)
    def test_hierarchy_descendants(self, qid):
        q = QUERIES[qid]
        exp = expected_hierarchy(q)
        actual = RESULTS.get(qid, {})
        actual_desc = sorted(actual.get("descendants", []))
        assert actual_desc == exp["descendants"], (
            f"Query {qid} court={q['court_id']} "
            f"descendants: expected {len(exp['descendants'])} items, "
            f"got {len(actual_desc)} items"
        )


# --- Collisions tests ---

COLLISIONS_IDS = [str(i) for i in range(44, 48)]


class TestCollisions:
    @pytest.mark.parametrize("qid", COLLISIONS_IDS)
    def test_collisions(self, qid):
        q = QUERIES[qid]
        exp = expected_collisions(q)
        actual = RESULTS.get(qid, {})
        actual_courts = sorted(
            actual.get("courts", []), key=lambda x: x.get("id", "")
        )
        assert actual_courts == exp["courts"], (
            f"Query {qid} name='{q['name']}' "
            f"expected={exp['courts']} got={actual_courts}"
        )
