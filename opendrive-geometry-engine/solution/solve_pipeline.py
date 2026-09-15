#!/usr/bin/env python3
"""
Cross-standard analysis pipeline for OpenDRIVE + OpenSCENARIO.

Produces:
  /app/qc_report.json       - ASAM QC checker validation summary
  /app/entity_positions.json - Entity positions and cross-reference errors
"""

import json
import math
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


# ===========================================================================
# Part 1: ASAM Quality Checker
# ===========================================================================

def run_qc_checker(xodr_path, output_json_path):
    """Run asam-qc-opendrive and produce qc_report.json."""
    xqar_path = "/tmp/qc_result.xqar"
    config_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        "<Config>\n"
        f'    <Param name="InputFile" value="{xodr_path}" />\n'
        '    <CheckerBundle application="xodrBundle">\n'
        f'        <Param name="resultFile" value="{xqar_path}" />\n'
        "    </CheckerBundle>\n"
        "</Config>\n"
    )

    config_path = "/tmp/qc_config.xml"
    with open(config_path, "w") as f:
        f.write(config_xml)

    try:
        proc = subprocess.run(
            ["qc_opendrive", "-c", config_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as e:
        print(f"Warning: qc_opendrive failed: {e}", file=sys.stderr)
        proc = None

    report = {
        "checkers_run": 0,
        "checkers_passed": 0,
        "issues_found": 0,
        "checker_details": [],
    }

    if os.path.isfile(xqar_path):
        try:
            report = _parse_xqar(xqar_path)
        except Exception as e:
            print(f"Warning: Failed to parse XQAR: {e}", file=sys.stderr)

    with open(output_json_path, "w") as f:
        json.dump(report, f, indent=2)


def _parse_xqar(xqar_path):
    """Parse an XQAR result file and extract checker information."""
    tree = ET.parse(xqar_path)
    root = tree.getroot()

    checkers = []
    total_issues = 0

    # Walk XML tree looking for elements with checkerId attribute
    for elem in root.iter():
        checker_id = elem.get("checkerId")
        if checker_id is None:
            continue

        # Determine status
        status = "unknown"
        status_elem = elem.find("Status")
        if status_elem is None:
            status_elem = elem.find("status")
        if status_elem is not None and status_elem.text:
            status = status_elem.text.strip().lower()

        # If element has a summary attribute, might indicate status
        summary = elem.get("summary", "")

        # Count issues under this checker
        issues = 0
        for child in elem.iter():
            if child.tag in ("Issue", "issue"):
                issues += 1
            # Also check for RuleResult/Issues pattern
            if child.tag == "Issues":
                for issue in child:
                    issues += 1

        total_issues += issues
        checkers.append({
            "checker_id": checker_id,
            "status": status,
            "issues": issues,
        })

    checkers_passed = sum(
        1 for c in checkers if c["status"] in ("completed", "skipped") and c["issues"] == 0
    )

    return {
        "checkers_run": len(checkers),
        "checkers_passed": checkers_passed,
        "issues_found": total_issues,
        "checker_details": checkers,
    }


# ===========================================================================
# Part 2: OpenDRIVE Parsing (reuse geometry logic)
# ===========================================================================

@dataclass
class GeomSeg:
    s: float
    x: float
    y: float
    hdg: float
    length: float
    geo_type: str
    aU: float = 0.0
    bU: float = 0.0
    cU: float = 0.0
    dU: float = 0.0
    aV: float = 0.0
    bV: float = 0.0
    cV: float = 0.0
    dV: float = 0.0


@dataclass
class ElevEntry:
    s: float
    a: float
    b: float
    c: float
    d: float


@dataclass
class WidthEntry:
    s_offset: float
    a: float
    b: float
    c: float
    d: float


@dataclass
class Lane:
    lane_id: int
    widths: list = field(default_factory=list)


@dataclass
class LaneSection:
    s: float
    left_lanes: list = field(default_factory=list)
    right_lanes: list = field(default_factory=list)


@dataclass
class Road:
    road_id: int
    length: float
    geometry: list = field(default_factory=list)
    elevation: list = field(default_factory=list)
    lane_sections: list = field(default_factory=list)


def parse_xodr(xodr_path):
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    roads = {}

    for road_elem in root.findall("road"):
        road_id = int(road_elem.get("id"))
        length = float(road_elem.get("length"))
        road = Road(road_id=road_id, length=length)

        pv = road_elem.find("planView")
        if pv is not None:
            for ge in pv.findall("geometry"):
                seg = GeomSeg(
                    s=float(ge.get("s")),
                    x=float(ge.get("x")),
                    y=float(ge.get("y")),
                    hdg=float(ge.get("hdg")),
                    length=float(ge.get("length")),
                    geo_type="line",
                )
                pp3 = ge.find("paramPoly3")
                if pp3 is not None:
                    seg.geo_type = "paramPoly3"
                    for attr in ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV"):
                        setattr(seg, attr, float(pp3.get(attr, 0)))
                road.geometry.append(seg)
            road.geometry.sort(key=lambda g: g.s)

        ep = road_elem.find("elevationProfile")
        if ep is not None:
            for ee in ep.findall("elevation"):
                road.elevation.append(ElevEntry(
                    s=float(ee.get("s")),
                    a=float(ee.get("a")),
                    b=float(ee.get("b")),
                    c=float(ee.get("c")),
                    d=float(ee.get("d")),
                ))
            road.elevation.sort(key=lambda e: e.s)

        lanes = road_elem.find("lanes")
        if lanes is not None:
            for ls in lanes.findall("laneSection"):
                section = LaneSection(s=float(ls.get("s")))
                for side, attr in [("left", "left_lanes"), ("right", "right_lanes")]:
                    side_elem = ls.find(side)
                    if side_elem is not None:
                        for le in side_elem.findall("lane"):
                            lane = Lane(lane_id=int(le.get("id")))
                            for we in le.findall("width"):
                                lane.widths.append(WidthEntry(
                                    s_offset=float(we.get("sOffset", 0)),
                                    a=float(we.get("a", 0)),
                                    b=float(we.get("b", 0)),
                                    c=float(we.get("c", 0)),
                                    d=float(we.get("d", 0)),
                                ))
                            lane.widths.sort(key=lambda w: w.s_offset)
                            getattr(section, attr).append(lane)
                    if side == "left":
                        section.left_lanes.sort(key=lambda l: l.lane_id)
                    else:
                        section.right_lanes.sort(key=lambda l: l.lane_id, reverse=True)
                road.lane_sections.append(section)
            road.lane_sections.sort(key=lambda s: s.s)

        roads[road_id] = road

    return roads


def _find_seg(road, s):
    seg = road.geometry[0]
    for g in road.geometry:
        if g.s <= s:
            seg = g
        else:
            break
    return seg


def _find_section(road, s):
    section = road.lane_sections[0]
    for ls in road.lane_sections:
        if ls.s <= s:
            section = ls
        else:
            break
    return section


def eval_ref_point(road, s):
    seg = _find_seg(road, s)
    ds = s - seg.s
    if seg.geo_type == "line":
        return seg.x + ds * math.cos(seg.hdg), seg.y + ds * math.sin(seg.hdg)
    else:
        p = ds
        u = seg.aU + seg.bU * p + seg.cU * p ** 2 + seg.dU * p ** 3
        v = seg.aV + seg.bV * p + seg.cV * p ** 2 + seg.dV * p ** 3
        ch, sh = math.cos(seg.hdg), math.sin(seg.hdg)
        return seg.x + u * ch - v * sh, seg.y + u * sh + v * ch


def eval_heading(road, s):
    seg = _find_seg(road, s)
    ds = s - seg.s
    if seg.geo_type == "line":
        return seg.hdg
    p = ds
    du = seg.bU + 2 * seg.cU * p + 3 * seg.dU * p ** 2
    dv = seg.bV + 2 * seg.cV * p + 3 * seg.dV * p ** 2
    return seg.hdg + math.atan2(dv, du)


def eval_elevation(road, s):
    if not road.elevation:
        return 0.0
    entry = road.elevation[0]
    for e in road.elevation:
        if e.s <= s:
            entry = e
        else:
            break
    ds = s - entry.s
    return entry.a + entry.b * ds + entry.c * ds ** 2 + entry.d * ds ** 3


def eval_lane_width(road, s, lane_id):
    section = _find_section(road, s)
    ds_sec = s - section.s
    all_lanes = section.left_lanes + section.right_lanes
    lane = None
    for l in all_lanes:
        if l.lane_id == lane_id:
            lane = l
            break
    if lane is None or not lane.widths:
        return 0.0
    entry = lane.widths[0]
    for w in lane.widths:
        if w.s_offset <= ds_sec:
            entry = w
        else:
            break
    ds = ds_sec - entry.s_offset
    return entry.a + entry.b * ds + entry.c * ds ** 2 + entry.d * ds ** 3


def lane_exists(road, s, lane_id):
    """Check whether lane_id exists in the lane section at s."""
    section = _find_section(road, s)
    for l in section.left_lanes + section.right_lanes:
        if l.lane_id == lane_id:
            return True
    return False


def eval_lane_center(road, s, lane_id):
    """Compute (x, y) at the center of a lane."""
    xr, yr = eval_ref_point(road, s)
    hdg = eval_heading(road, s)
    section = _find_section(road, s)

    t = 0.0
    if lane_id > 0:
        for l in section.left_lanes:
            if 1 <= l.lane_id < lane_id:
                t += eval_lane_width(road, s, l.lane_id)
        t += eval_lane_width(road, s, lane_id) / 2.0
    elif lane_id < 0:
        for l in section.right_lanes:
            if -1 >= l.lane_id > lane_id:
                t += eval_lane_width(road, s, l.lane_id)
        t += eval_lane_width(road, s, lane_id) / 2.0
        t = -t

    x = xr + t * (-math.sin(hdg))
    y = yr + t * math.cos(hdg)
    return x, y


# ===========================================================================
# Part 3: OpenSCENARIO Parsing
# ===========================================================================

def parse_xosc(xosc_path):
    """Parse .xosc to extract parameter declarations and entity positions."""
    tree = ET.parse(xosc_path)
    root = tree.getroot()

    # Extract parameters
    params = {}
    for pd in root.findall(".//ParameterDeclaration"):
        name = pd.get("name")
        ptype = pd.get("parameterType", "string")
        val = pd.get("value", "")
        if ptype == "double":
            params[name] = float(val)
        elif ptype == "integer":
            params[name] = int(val)
        else:
            params[name] = val

    # Extract entity initial positions
    entities = {}
    for private in root.findall(".//Init/Actions/Private"):
        entity_ref = private.get("entityRef")
        for lp in private.findall(".//TeleportAction/Position/LanePosition"):
            road_id = int(lp.get("roadId"))
            lane_id = int(lp.get("laneId"))
            s_raw = lp.get("s")
            offset = float(lp.get("offset", "0"))

            # Resolve parameter references
            if s_raw.startswith("$"):
                param_name = s_raw[1:]
                s = float(params.get(param_name, s_raw))
            else:
                try:
                    s = float(s_raw)
                except ValueError:
                    s = 0.0

            entities[entity_ref] = {
                "road_id": road_id,
                "lane_id": lane_id,
                "s": s,
                "offset": offset,
            }

    return entities, params


# ===========================================================================
# Main pipeline
# ===========================================================================

def main():
    xodr_path = "/app/network.xodr"
    xosc_path = "/app/scenario.xosc"

    # 1. QC Report
    print("Running ASAM QC checker...")
    run_qc_checker(xodr_path, "/app/qc_report.json")
    print("QC report written to /app/qc_report.json")

    # 2. Entity Position Analysis
    print("Parsing scenario and computing entity positions...")
    roads = parse_xodr(xodr_path)
    entities_raw, params = parse_xosc(xosc_path)

    result = {"entities": {}, "cross_ref_errors": []}

    for name, ent in entities_raw.items():
        road_id = ent["road_id"]
        lane_id = ent["lane_id"]
        s = ent["s"]

        entity_result = {
            "road_id": road_id,
            "lane_id": lane_id,
            "s": s,
            "valid": True,
            "x": None,
            "y": None,
            "z": None,
            "error": None,
        }

        if road_id not in roads:
            entity_result["valid"] = False
            entity_result["error"] = f"Road {road_id} does not exist in the network"
            result["cross_ref_errors"].append(
                f"Entity '{name}' references non-existent road {road_id}"
            )
        elif s > roads[road_id].length:
            entity_result["valid"] = False
            entity_result["error"] = (
                f"s={s} exceeds road {road_id} length {roads[road_id].length}"
            )
            result["cross_ref_errors"].append(
                f"Entity '{name}' s-coordinate {s} exceeds road length "
                f"{roads[road_id].length}"
            )
        elif not lane_exists(roads[road_id], s, lane_id):
            entity_result["valid"] = False
            entity_result["error"] = (
                f"Lane {lane_id} does not exist on road {road_id} at s={s}"
            )
            result["cross_ref_errors"].append(
                f"Entity '{name}' references non-existent lane {lane_id} "
                f"on road {road_id}"
            )
        else:
            road = roads[road_id]
            x, y = eval_lane_center(road, s, lane_id)
            z = eval_elevation(road, s)
            entity_result["x"] = x
            entity_result["y"] = y
            entity_result["z"] = z

        result["entities"][name] = entity_result

    with open("/app/entity_positions.json", "w") as f:
        json.dump(result, f, indent=2)

    print("Entity positions written to /app/entity_positions.json")


if __name__ == "__main__":
    main()
