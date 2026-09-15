
import json
import os

import pytest
from lxml import etree


@pytest.fixture
def repaired_tree():
    path = "/app/repaired_network.xodr"
    assert os.path.isfile(path), "repaired_network.xodr not found at /app/"
    tree = etree.parse(path)
    return tree


@pytest.fixture
def audit_report():
    path = "/app/audit_report.json"
    assert os.path.isfile(path), "audit_report.json not found at /app/"
    with open(path) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Repaired-network structural invariants
# ---------------------------------------------------------------------------


class TestRepairedNetwork:
    def test_valid_xml_root(self, repaired_tree):
        root = repaired_tree.getroot()
        assert root.tag == "OpenDRIVE", "Root element must be <OpenDRIVE>"

    def test_road_count_preserved(self, repaired_tree):
        roads = repaired_tree.getroot().findall("road")
        assert len(roads) == 3, f"Expected 3 roads, found {len(roads)}"

    def test_road_lengths_match_geometry_sum(self, repaired_tree):
        root = repaired_tree.getroot()
        for road in root.findall("road"):
            rid = road.get("id")
            declared = float(road.get("length"))
            geoms = road.findall("planView/geometry")
            if not geoms:
                continue
            geo_sum = sum(float(g.get("length")) for g in geoms)
            assert abs(declared - geo_sum) < 1.0, (
                f"Road {rid}: declared length {declared} != geometry sum {geo_sum}"
            )

    def test_geometry_s_contiguity(self, repaired_tree):
        root = repaired_tree.getroot()
        for road in root.findall("road"):
            rid = road.get("id")
            geoms = road.findall("planView/geometry")
            for i in range(len(geoms) - 1):
                s_i = float(geoms[i].get("s"))
                l_i = float(geoms[i].get("length"))
                s_next = float(geoms[i + 1].get("s"))
                expected = s_i + l_i
                assert abs(s_next - expected) < 0.5, (
                    f"Road {rid}, segment {i+1}: expected s={expected:.2f}, "
                    f"got s={s_next:.2f}"
                )

    def test_lane_links_reference_existing_lanes(self, repaired_tree):
        root = repaired_tree.getroot()
        for road in root.findall("road"):
            rid = road.get("id")
            sections = road.findall("lanes/laneSection")
            for idx, sec in enumerate(sections):
                lanes = (
                    sec.findall("left/lane")
                    + sec.findall("center/lane")
                    + sec.findall("right/lane")
                )
                for lane in lanes:
                    lid = lane.get("id")
                    # predecessor
                    pred = lane.find("link/predecessor")
                    if pred is not None and idx > 0:
                        pid = int(pred.get("id"))
                        prev = sections[idx - 1]
                        prev_ids = set()
                        for s in ("left/lane", "center/lane", "right/lane"):
                            for pl in prev.findall(s):
                                prev_ids.add(int(pl.get("id")))
                        assert pid in prev_ids, (
                            f"Road {rid}, section {idx}, lane {lid}: "
                            f"predecessor {pid} not in prev section {sorted(prev_ids)}"
                        )
                    # successor
                    succ = lane.find("link/successor")
                    if succ is not None and idx + 1 < len(sections):
                        sid = int(succ.get("id"))
                        nxt = sections[idx + 1]
                        nxt_ids = set()
                        for s in ("left/lane", "center/lane", "right/lane"):
                            for nl in nxt.findall(s):
                                nxt_ids.add(int(nl.get("id")))
                        assert sid in nxt_ids, (
                            f"Road {rid}, section {idx}, lane {lid}: "
                            f"successor {sid} not in next section {sorted(nxt_ids)}"
                        )

    def test_elevation_within_road_bounds(self, repaired_tree):
        root = repaired_tree.getroot()
        for road in root.findall("road"):
            rid = road.get("id")
            rlen = float(road.get("length"))
            for elev in road.findall("elevationProfile/elevation"):
                s = float(elev.get("s"))
                assert s <= rlen + 0.01, (
                    f"Road {rid}: elevation s={s} exceeds length {rlen}"
                )

    def test_junction_references_existing_roads(self, repaired_tree):
        root = repaired_tree.getroot()
        road_ids = {r.get("id") for r in root.findall("road")}
        for junc in root.findall("junction"):
            jid = junc.get("id")
            for conn in junc.findall("connection"):
                inc = conn.get("incomingRoad")
                con = conn.get("connectingRoad")
                assert inc in road_ids, (
                    f"Junction {jid}: incomingRoad={inc} not a valid road"
                )
                assert con in road_ids, (
                    f"Junction {jid}: connectingRoad={con} not a valid road"
                )

    def test_objects_within_road_bounds(self, repaired_tree):
        root = repaired_tree.getroot()
        for road in root.findall("road"):
            rid = road.get("id")
            rlen = float(road.get("length"))
            for obj in road.findall("objects/object"):
                s = float(obj.get("s"))
                assert s <= rlen + 0.01, (
                    f"Road {rid}: object {obj.get('id')} s={s} exceeds length {rlen}"
                )


# ---------------------------------------------------------------------------
# Audit-report structure and content
# ---------------------------------------------------------------------------


class TestAuditReport:
    def test_defects_key_exists(self, audit_report):
        assert "defects" in audit_report, "Missing 'defects' key"
        assert isinstance(audit_report["defects"], list)

    def test_minimum_defects_found(self, audit_report):
        n = len(audit_report["defects"])
        assert n >= 5, f"Expected >= 5 defects, found {n}"

    def test_defect_schema(self, audit_report):
        required = {"element", "category", "description", "repair"}
        for i, d in enumerate(audit_report["defects"]):
            for f in required:
                assert f in d, f"Defect {i} missing field '{f}'"

    def test_entity_placements_key_exists(self, audit_report):
        assert "entity_placements" in audit_report, "Missing 'entity_placements' key"
        assert isinstance(audit_report["entity_placements"], list)

    def test_three_entity_placements(self, audit_report):
        n = len(audit_report["entity_placements"])
        assert n == 3, f"Expected 3 entity placements, got {n}"

    def test_entity_placement_schema(self, audit_report):
        required = {"entity", "road_id", "lane_id", "s", "valid", "reason"}
        for i, ep in enumerate(audit_report["entity_placements"]):
            for f in required:
                assert f in ep, f"Placement {i} missing field '{f}'"

    def test_entity_names_present(self, audit_report):
        names = {ep["entity"] for ep in audit_report["entity_placements"]}
        assert "Ego" in names, "Missing Ego placement"
        assert "Target" in names, "Missing Target placement"
        assert "Obstacle" in names, "Missing Obstacle placement"

    def test_all_placements_valid(self, audit_report):
        for ep in audit_report["entity_placements"]:
            assert ep["valid"] is True, (
                f"Entity {ep['entity']} should be valid: {ep.get('reason')}"
            )

    def test_placement_coordinates_match_scenario(self, audit_report):
        expected = {
            "Ego": {"road_id": "0", "lane_id": -1, "s": 300.0},
            "Target": {"road_id": "0", "lane_id": -2, "s": 600.0},
            "Obstacle": {"road_id": "1", "lane_id": -1, "s": 100.0},
        }
        for ep in audit_report["entity_placements"]:
            name = ep["entity"]
            if name in expected:
                exp = expected[name]
                assert str(ep["road_id"]) == exp["road_id"], (
                    f"{name}: road_id {ep['road_id']} != {exp['road_id']}"
                )
                assert int(ep["lane_id"]) == exp["lane_id"], (
                    f"{name}: lane_id {ep['lane_id']} != {exp['lane_id']}"
                )
                assert abs(float(ep["s"]) - exp["s"]) < 1.0, (
                    f"{name}: s={ep['s']} != {exp['s']}"
                )
