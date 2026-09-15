#!/usr/bin/env python3
"""
OpenDRIVE Geometry Evaluation Engine.

Evaluates road geometry queries (ref_point, heading, elevation, lane_width,
lane_edge) against an ASAM OpenDRIVE (.xodr) road network file.

Usage:
    python3 odr_eval.py <xodr_path> <queries_json> <results_json>
"""

import json
import math
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class GeometrySegment:
    s: float
    x: float
    y: float
    hdg: float
    length: float
    geo_type: str  # "line", "paramPoly3"
    # paramPoly3 parameters
    aU: float = 0.0
    bU: float = 0.0
    cU: float = 0.0
    dU: float = 0.0
    aV: float = 0.0
    bV: float = 0.0
    cV: float = 0.0
    dV: float = 0.0
    p_range: str = "arcLength"


@dataclass
class ElevationEntry:
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
    lane_type: str
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
    """Parse an OpenDRIVE file and return a dict of Road objects keyed by ID."""
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    roads = {}

    for road_elem in root.findall("road"):
        road_id = int(road_elem.get("id"))
        length = float(road_elem.get("length"))
        road = Road(road_id=road_id, length=length)

        # Parse geometry
        plan_view = road_elem.find("planView")
        if plan_view is not None:
            for geo_elem in plan_view.findall("geometry"):
                seg = GeometrySegment(
                    s=float(geo_elem.get("s")),
                    x=float(geo_elem.get("x")),
                    y=float(geo_elem.get("y")),
                    hdg=float(geo_elem.get("hdg")),
                    length=float(geo_elem.get("length")),
                    geo_type="line",
                )
                line = geo_elem.find("line")
                pp3 = geo_elem.find("paramPoly3")
                if pp3 is not None:
                    seg.geo_type = "paramPoly3"
                    seg.aU = float(pp3.get("aU", 0))
                    seg.bU = float(pp3.get("bU", 0))
                    seg.cU = float(pp3.get("cU", 0))
                    seg.dU = float(pp3.get("dU", 0))
                    seg.aV = float(pp3.get("aV", 0))
                    seg.bV = float(pp3.get("bV", 0))
                    seg.cV = float(pp3.get("cV", 0))
                    seg.dV = float(pp3.get("dV", 0))
                    seg.p_range = pp3.get("pRange", "arcLength")
                road.geometry.append(seg)
            road.geometry.sort(key=lambda g: g.s)

        # Parse elevation
        elev_profile = road_elem.find("elevationProfile")
        if elev_profile is not None:
            for elev_elem in elev_profile.findall("elevation"):
                entry = ElevationEntry(
                    s=float(elev_elem.get("s")),
                    a=float(elev_elem.get("a")),
                    b=float(elev_elem.get("b")),
                    c=float(elev_elem.get("c")),
                    d=float(elev_elem.get("d")),
                )
                road.elevation.append(entry)
            road.elevation.sort(key=lambda e: e.s)

        # Parse lanes
        lanes_elem = road_elem.find("lanes")
        if lanes_elem is not None:
            for ls_elem in lanes_elem.findall("laneSection"):
                section = LaneSection(s=float(ls_elem.get("s")))

                # Parse left lanes
                left = ls_elem.find("left")
                if left is not None:
                    for lane_elem in left.findall("lane"):
                        lane = _parse_lane(lane_elem)
                        section.left_lanes.append(lane)
                    # Sort by ID ascending (1, 2, 3... inner to outer)
                    section.left_lanes.sort(key=lambda l: l.lane_id)

                # Parse right lanes
                right = ls_elem.find("right")
                if right is not None:
                    for lane_elem in right.findall("lane"):
                        lane = _parse_lane(lane_elem)
                        section.right_lanes.append(lane)
                    # Sort by ID descending (abs value: -1, -2, -3... inner to outer)
                    section.right_lanes.sort(key=lambda l: l.lane_id, reverse=True)

                road.lane_sections.append(section)
            road.lane_sections.sort(key=lambda ls: ls.s)

        roads[road_id] = road

    return roads


def _parse_lane(lane_elem):
    """Parse a single lane element."""
    lane = Lane(
        lane_id=int(lane_elem.get("id")),
        lane_type=lane_elem.get("type", ""),
    )
    for w_elem in lane_elem.findall("width"):
        width = WidthEntry(
            s_offset=float(w_elem.get("sOffset", 0)),
            a=float(w_elem.get("a", 0)),
            b=float(w_elem.get("b", 0)),
            c=float(w_elem.get("c", 0)),
            d=float(w_elem.get("d", 0)),
        )
        lane.widths.append(width)
    lane.widths.sort(key=lambda w: w.s_offset)
    return lane


def _find_segment(road, s):
    """Find the geometry segment containing s-coordinate."""
    seg = road.geometry[0]
    for g in road.geometry:
        if g.s <= s:
            seg = g
        else:
            break
    return seg


def eval_ref_point(road, s):
    """Evaluate reference line (x, y) at s-coordinate."""
    seg = _find_segment(road, s)
    ds = s - seg.s

    if seg.geo_type == "line":
        x = seg.x + ds * math.cos(seg.hdg)
        y = seg.y + ds * math.sin(seg.hdg)
    elif seg.geo_type == "paramPoly3":
        p = ds  # arcLength: p = ds
        u = seg.aU + seg.bU * p + seg.cU * p**2 + seg.dU * p**3
        v = seg.aV + seg.bV * p + seg.cV * p**2 + seg.dV * p**3
        cos_h = math.cos(seg.hdg)
        sin_h = math.sin(seg.hdg)
        x = seg.x + u * cos_h - v * sin_h
        y = seg.y + u * sin_h + v * cos_h
    else:
        raise ValueError(f"Unsupported geometry type: {seg.geo_type}")

    return x, y


def eval_heading(road, s):
    """Evaluate reference line heading at s-coordinate."""
    seg = _find_segment(road, s)
    ds = s - seg.s

    if seg.geo_type == "line":
        return seg.hdg
    elif seg.geo_type == "paramPoly3":
        p = ds
        du = seg.bU + 2 * seg.cU * p + 3 * seg.dU * p**2
        dv = seg.bV + 2 * seg.cV * p + 3 * seg.dV * p**2
        return seg.hdg + math.atan2(dv, du)
    else:
        raise ValueError(f"Unsupported geometry type: {seg.geo_type}")


def eval_elevation(road, s):
    """Evaluate elevation at s-coordinate."""
    if not road.elevation:
        return 0.0
    entry = road.elevation[0]
    for e in road.elevation:
        if e.s <= s:
            entry = e
        else:
            break
    ds = s - entry.s
    return entry.a + entry.b * ds + entry.c * ds**2 + entry.d * ds**3


def _find_lane_section(road, s):
    """Find the lane section containing s-coordinate."""
    section = road.lane_sections[0]
    for ls in road.lane_sections:
        if ls.s <= s:
            section = ls
        else:
            break
    return section


def _find_width_entry(lane, ds_from_section):
    """Find the applicable width entry for a given distance from section start."""
    entry = lane.widths[0]
    for w in lane.widths:
        if w.s_offset <= ds_from_section:
            entry = w
        else:
            break
    return entry


def eval_lane_width(road, s, lane_id):
    """Evaluate width of a specific lane at s-coordinate."""
    section = _find_lane_section(road, s)
    ds_from_section = s - section.s

    # Find the lane
    all_lanes = section.left_lanes + section.right_lanes
    lane = None
    for l in all_lanes:
        if l.lane_id == lane_id:
            lane = l
            break

    if lane is None or not lane.widths:
        return 0.0

    w_entry = _find_width_entry(lane, ds_from_section)
    ds = ds_from_section - w_entry.s_offset
    return w_entry.a + w_entry.b * ds + w_entry.c * ds**2 + w_entry.d * ds**3


def eval_lane_edge(road, s, lane_id):
    """Evaluate (x, y) of the outer edge of a lane at s-coordinate."""
    x_ref, y_ref = eval_ref_point(road, s)
    hdg = eval_heading(road, s)
    section = _find_lane_section(road, s)

    # Accumulate t-offset from center to outer edge of the specified lane
    t = 0.0
    if lane_id > 0:
        # Left lane: accumulate widths from lane 1 to lane_id
        for l in section.left_lanes:
            if l.lane_id >= 1 and l.lane_id <= lane_id:
                t += eval_lane_width(road, s, l.lane_id)
    elif lane_id < 0:
        # Right lane: accumulate widths from lane -1 to lane_id
        for l in section.right_lanes:
            if l.lane_id <= -1 and l.lane_id >= lane_id:
                t += eval_lane_width(road, s, l.lane_id)
        t = -t  # Right side is negative t

    # Convert from Frenet to Cartesian
    x = x_ref + t * (-math.sin(hdg))
    y = y_ref + t * math.cos(hdg)

    return x, y


def process_query(roads, query):
    """Process a single query and return the result dict."""
    road_id = query["road_id"]
    s = query["s"]
    road = roads[road_id]
    q_type = query["type"]

    if q_type == "ref_point":
        x, y = eval_ref_point(road, s)
        return {"x": x, "y": y}
    elif q_type == "heading":
        hdg = eval_heading(road, s)
        return {"hdg": hdg}
    elif q_type == "elevation":
        z = eval_elevation(road, s)
        return {"z": z}
    elif q_type == "lane_width":
        lane_id = query["lane_id"]
        width = eval_lane_width(road, s, lane_id)
        return {"width": width}
    elif q_type == "lane_edge":
        lane_id = query["lane_id"]
        x, y = eval_lane_edge(road, s, lane_id)
        return {"x": x, "y": y}
    else:
        raise ValueError(f"Unknown query type: {q_type}")


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <xodr_path> <queries_json> <results_json>")
        sys.exit(1)

    xodr_path = sys.argv[1]
    queries_path = sys.argv[2]
    results_path = sys.argv[3]

    roads = parse_xodr(xodr_path)

    with open(queries_path) as f:
        queries = json.load(f)

    results = []
    for query in queries:
        result = process_query(roads, query)
        results.append(result)

    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
