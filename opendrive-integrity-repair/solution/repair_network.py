#!/usr/bin/env python3
"""Repair an OpenDRIVE road network and produce a cross-standard audit report."""

import json
from lxml import etree


def lane_ids_in_section(section):
    ids = set()
    for path in ("left/lane", "center/lane", "right/lane"):
        for lane in section.findall(path):
            ids.add(int(lane.get("id")))
    return ids


def repair(tree):
    root = tree.getroot()
    defects = []
    road_index = {r.get("id"): r for r in root.findall("road")}

    for rid, road in road_index.items():
        geoms = road.findall("planView/geometry")

        # --- geometry s-contiguity ---
        for i in range(len(geoms) - 1):
            s_i = float(geoms[i].get("s"))
            l_i = float(geoms[i].get("length"))
            expected = s_i + l_i
            actual = float(geoms[i + 1].get("s"))
            if abs(actual - expected) > 0.01:
                defects.append({
                    "road_id": rid,
                    "element": f"planView/geometry[{i+2}] s-attribute",
                    "category": "geometry_contiguity",
                    "description": (
                        f"Geometry segment {i+2} starts at s={actual} but "
                        f"preceding segment ends at s={expected}"
                    ),
                    "repair": f"Set s from {actual} to {expected}",
                })
                geoms[i + 1].set("s", f"{expected:.16e}")

        # --- road length vs geometry sum ---
        geo_sum = sum(float(g.get("length")) for g in geoms)
        declared = float(road.get("length"))
        if abs(declared - geo_sum) > 0.01:
            defects.append({
                "road_id": rid,
                "element": "road/@length",
                "category": "road_length_mismatch",
                "description": (
                    f"Declared length {declared} != geometry sum {geo_sum}"
                ),
                "repair": f"Set length from {declared} to {geo_sum}",
            })
            road.set("length", f"{geo_sum:.16e}")

        road_len = float(road.get("length"))

        # --- lane link validity ---
        sections = road.findall("lanes/laneSection")
        for idx, sec in enumerate(sections):
            all_lanes = (
                sec.findall("left/lane")
                + sec.findall("center/lane")
                + sec.findall("right/lane")
            )
            for lane in all_lanes:
                lid = lane.get("id")
                pred = lane.find("link/predecessor")
                if pred is not None and idx > 0:
                    pid = int(pred.get("id"))
                    prev_ids = lane_ids_in_section(sections[idx - 1])
                    if pid not in prev_ids:
                        fixed = (
                            int(lid)
                            if int(lid) in prev_ids
                            else min(prev_ids, key=lambda x: abs(x - int(lid)))
                        )
                        defects.append({
                            "road_id": rid,
                            "element": (
                                f"laneSection[{idx}]/lane[{lid}]"
                                f"/link/predecessor"
                            ),
                            "category": "lane_link_invalid",
                            "description": (
                                f"Predecessor id={pid} absent from previous "
                                f"section (has {sorted(prev_ids)})"
                            ),
                            "repair": f"Changed predecessor from {pid} to {fixed}",
                        })
                        pred.set("id", str(fixed))

                succ = lane.find("link/successor")
                if succ is not None and idx + 1 < len(sections):
                    sid = int(succ.get("id"))
                    nxt_ids = lane_ids_in_section(sections[idx + 1])
                    if sid not in nxt_ids:
                        fixed = (
                            int(lid)
                            if int(lid) in nxt_ids
                            else min(nxt_ids, key=lambda x: abs(x - int(lid)))
                        )
                        defects.append({
                            "road_id": rid,
                            "element": (
                                f"laneSection[{idx}]/lane[{lid}]"
                                f"/link/successor"
                            ),
                            "category": "lane_link_invalid",
                            "description": (
                                f"Successor id={sid} absent from next "
                                f"section (has {sorted(nxt_ids)})"
                            ),
                            "repair": f"Changed successor from {sid} to {fixed}",
                        })
                        succ.set("id", str(fixed))

        # --- elevation profile bounds ---
        elev_parent = road.find("elevationProfile")
        if elev_parent is not None:
            to_remove = []
            for elev in elev_parent.findall("elevation"):
                s = float(elev.get("s"))
                if s > road_len + 0.01:
                    defects.append({
                        "road_id": rid,
                        "element": f"elevationProfile/elevation s={s}",
                        "category": "elevation_out_of_range",
                        "description": (
                            f"Elevation at s={s} exceeds road length {road_len}"
                        ),
                        "repair": "Removed out-of-range elevation entry",
                    })
                    to_remove.append(elev)
            for el in to_remove:
                elev_parent.remove(el)

        # --- object placement bounds ---
        for obj in road.findall("objects/object"):
            s = float(obj.get("s"))
            if s > road_len + 0.01:
                new_s = road_len - 50.0
                defects.append({
                    "road_id": rid,
                    "element": f"objects/object id={obj.get('id')} s={s}",
                    "category": "object_out_of_range",
                    "description": (
                        f"Object at s={s} exceeds road length {road_len}"
                    ),
                    "repair": f"Moved object s from {s} to {new_s}",
                })
                obj.set("s", f"{new_s:.16e}")

    # --- junction reference validity ---
    all_road_ids = set(road_index.keys())
    for junc in root.findall("junction"):
        jid = junc.get("id")
        for conn in junc.findall("connection"):
            inc = conn.get("incomingRoad")
            con = conn.get("connectingRoad")
            if inc not in all_road_ids:
                # Derive correct incoming road from connecting road's links
                fixed = None
                cr = road_index.get(con)
                if cr is not None:
                    for link_dir in ("predecessor", "successor"):
                        lk = cr.find(f"link/{link_dir}")
                        if (
                            lk is not None
                            and lk.get("elementType") == "road"
                            and lk.get("elementId") in all_road_ids
                        ):
                            cand = lk.get("elementId")
                            cand_road = road_index[cand]
                            if cand_road.get("junction") == "-1":
                                fixed = cand
                                break
                if fixed is None:
                    for r in root.findall("road"):
                        sl = r.find("link/successor")
                        if (
                            sl is not None
                            and sl.get("elementType") == "junction"
                            and sl.get("elementId") == jid
                        ):
                            fixed = r.get("id")
                            break
                if fixed:
                    defects.append({
                        "road_id": None,
                        "element": (
                            f"junction[{jid}]/connection[{conn.get('id')}]"
                            f" incomingRoad"
                        ),
                        "category": "junction_reference_invalid",
                        "description": (
                            f"incomingRoad={inc} does not match any road "
                            f"(available: {sorted(all_road_ids)})"
                        ),
                        "repair": f"Changed incomingRoad from {inc} to {fixed}",
                    })
                    conn.set("incomingRoad", fixed)

    return defects


def cross_validate(xodr_root, xosc_tree):
    # Build road model
    roads = {}
    for road in xodr_root.findall("road"):
        rid = road.get("id")
        rlen = float(road.get("length"))
        secs = []
        for sec in road.findall("lanes/laneSection"):
            s0 = float(sec.get("s"))
            lids = lane_ids_in_section(sec)
            secs.append({"s": s0, "lane_ids": lids})
        roads[rid] = {"length": rlen, "sections": secs}

    placements = []
    xr = xosc_tree.getroot()
    for priv in xr.findall(".//Init/Actions/Private"):
        entity = priv.get("entityRef")
        for lp in priv.findall(".//LanePosition"):
            rid = lp.get("roadId")
            lid = int(lp.get("laneId"))
            s = float(lp.get("s"))

            valid = True
            reason = ""
            if rid not in roads:
                valid, reason = False, f"Road {rid} does not exist"
            else:
                rd = roads[rid]
                if s > rd["length"]:
                    valid = False
                    reason = f"s={s} > road length {rd['length']}"
                else:
                    containing = None
                    for j, sec in enumerate(rd["sections"]):
                        upper = (
                            rd["sections"][j + 1]["s"]
                            if j + 1 < len(rd["sections"])
                            else rd["length"]
                        )
                        if sec["s"] <= s < upper or (
                            j == len(rd["sections"]) - 1 and sec["s"] <= s
                        ):
                            containing = sec
                            break
                    if containing is None:
                        valid = False
                        reason = f"No lane section for s={s}"
                    elif lid not in containing["lane_ids"]:
                        valid = False
                        reason = (
                            f"Lane {lid} absent from section at "
                            f"s={containing['s']}"
                        )
                    else:
                        reason = (
                            f"Resolves to road {rid}, lane {lid}, "
                            f"section at s={containing['s']}"
                        )

            placements.append({
                "entity": entity,
                "road_id": rid,
                "lane_id": lid,
                "s": s,
                "valid": valid,
                "reason": reason,
            })

    return placements


def main():
    xodr = etree.parse("/app/network.xodr")
    xosc = etree.parse("/app/scenario.xosc")

    defects = repair(xodr)
    xodr.write(
        "/app/repaired_network.xodr",
        xml_declaration=True,
        encoding="utf-8",
        pretty_print=True,
    )

    placements = cross_validate(xodr.getroot(), xosc)

    report = {"defects": defects, "entity_placements": placements}
    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Done: {len(defects)} defects repaired, {len(placements)} placements checked")


if __name__ == "__main__":
    main()
