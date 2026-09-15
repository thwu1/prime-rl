#!/usr/bin/env python3
"""SSURGO Soil Report Generator -- Reference Solution.

Queries the USDA Soil Data Access (SDA) REST API for SSURGO soil data
and produces a structured JSON assessment report.

"""

import argparse
import json
import sys
import time

import requests

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"


def query_sda(session, sql, max_retries=3):
    """Execute a SQL query against the SDA REST API with retry logic."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = session.post(
                SDA_URL,
                json={"query": sql, "format": "JSON+COLUMNNAME"},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                table = data.get("Table") or data.get("table") or []
                if len(table) < 2:
                    return []
                headers = table[0]
                return [dict(zip(headers, row)) for row in table[1:]]
            return []
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(3 * (2 ** attempt))
    raise RuntimeError(f"SDA query failed after {max_retries} attempts: {last_exc}")


def safe_int(val):
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    return int(float(s))


def safe_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    return float(s)


def classify_texture(sand, silt, clay):
    """Classify soil texture using the USDA Soil Texture Triangle."""
    if sand is None or silt is None or clay is None:
        return None

    if silt + 1.5 * clay < 15:
        return "Sand"
    if silt + 2 * clay < 30:
        return "Loamy sand"
    if (clay >= 7 and clay < 20 and sand > 52 and silt + 2 * clay >= 30) or \
       (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "Sandy loam"
    if clay >= 7 and clay < 27 and silt >= 28 and silt < 50 and sand <= 52:
        return "Loam"
    if (silt >= 50 and clay >= 12 and clay < 27) or \
       (silt >= 50 and silt < 80 and clay < 12):
        return "Silt loam"
    if silt >= 80 and clay < 12:
        return "Silt"
    if clay >= 20 and clay < 35 and silt < 28 and sand >= 45:
        return "Sandy clay loam"
    if clay >= 27 and clay < 40 and sand > 20 and sand <= 45:
        return "Clay loam"
    if clay >= 27 and clay < 40 and sand <= 20:
        return "Silty clay loam"
    if clay >= 35 and sand >= 45:
        return "Sandy clay"
    if clay >= 40 and silt >= 40:
        return "Silty clay"
    if clay >= 40:
        return "Clay"
    return None


def depth_weighted_avg(horizons, prop_key, depth_top, depth_bottom, restriction_depth):
    """Compute depth-weighted average of a soil property within a depth range."""
    effective_bottom = float(depth_bottom)
    if restriction_depth is not None:
        effective_bottom = min(effective_bottom, restriction_depth)

    if effective_bottom <= depth_top:
        return None

    total_thickness = 0.0
    weighted_sum = 0.0

    for hz in horizons:
        ht = hz.get("hzdept_r")
        hb = hz.get("hzdepb_r")
        val = hz.get(prop_key)

        if ht is None or hb is None or val is None:
            continue

        overlap_top = max(float(ht), float(depth_top))
        overlap_bottom = min(float(hb), effective_bottom)
        thickness = overlap_bottom - overlap_top

        if thickness <= 0:
            continue

        total_thickness += thickness
        weighted_sum += val * thickness

    if total_thickness == 0:
        return None

    return weighted_sum / total_thickness


def compute_aws_mm(horizons, depth_top, depth_bottom, restriction_depth):
    """Compute total Available Water Storage in mm within the depth range.

    AWS(mm) = sum of (AWC(cm/cm) * overlap_thickness(cm) * 10)
    This is a cumulative total, not a per-unit average.
    """
    effective_bottom = float(depth_bottom)
    if restriction_depth is not None:
        effective_bottom = min(effective_bottom, restriction_depth)

    if effective_bottom <= depth_top:
        return None

    total_aws = 0.0
    has_data = False

    for hz in horizons:
        ht = hz.get("hzdept_r")
        hb = hz.get("hzdepb_r")
        awc = hz.get("awc_r")

        if ht is None or hb is None or awc is None:
            continue

        overlap_top = max(float(ht), float(depth_top))
        overlap_bottom = min(float(hb), effective_bottom)
        thickness = overlap_bottom - overlap_top

        if thickness <= 0:
            continue

        has_data = True
        total_aws += awc * thickness * 10

    return total_aws if has_data else None


def main():
    parser = argparse.ArgumentParser(description="SSURGO Soil Report Generator")
    parser.add_argument("--mukeys", required=True,
                        help="Comma-separated map unit keys")
    parser.add_argument("--depth-top", type=int, default=0,
                        help="Top of depth range in cm (default: 0)")
    parser.add_argument("--depth-bottom", type=int, default=100,
                        help="Bottom of depth range in cm (default: 100)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")
    args = parser.parse_args()

    mukeys = [k.strip() for k in args.mukeys.split(",")]
    depth_top = args.depth_top
    depth_bottom = args.depth_bottom

    mukey_sql = ",".join(f"'{k}'" for k in mukeys)

    session = requests.Session()
    session.headers.update({"User-Agent": "SoilReport/1.0"})

    # Fetch mapunit + component info
    mc_rows = query_sda(session, f"""
        SELECT m.mukey, m.muname, m.mukind,
               c.cokey, c.compname, c.comppct_r,
               c.hydgrp, c.drainagecl, c.taxsubgrp
        FROM mapunit m
        INNER JOIN component c ON m.mukey = c.mukey
        WHERE m.mukey IN ({mukey_sql})
        ORDER BY m.mukey, c.comppct_r DESC
    """)

    mu_info = {}
    comps_by_mu = {}
    for r in mc_rows:
        mukey = str(r["mukey"]).strip()
        cokey = str(r["cokey"]).strip()
        if mukey not in mu_info:
            mu_info[mukey] = {
                "muname": (r.get("muname") or "").strip() or None,
                "mukind": (r.get("mukind") or "").strip() or None,
            }
        comps_by_mu.setdefault(mukey, {})[cokey] = {
            "compname": (r.get("compname") or "").strip() or None,
            "comppct_r": safe_int(r.get("comppct_r")),
            "hydgrp": (r.get("hydgrp") or "").strip() or None,
            "drainagecl": (r.get("drainagecl") or "").strip() or None,
            "taxsubgrp": (r.get("taxsubgrp") or "").strip() or None,
        }

    # Fetch horizon info
    hz_rows = query_sda(session, f"""
        SELECT ch.cokey, ch.hzdept_r, ch.hzdepb_r,
               ch.sandtotal_r, ch.silttotal_r, ch.claytotal_r,
               ch.awc_r, ch.ksat_r, ch.dbthirdbar_r
        FROM chorizon ch
        INNER JOIN component c ON ch.cokey = c.cokey
        WHERE c.mukey IN ({mukey_sql})
        ORDER BY ch.cokey, ch.hzdept_r
    """)

    hz_by_cokey = {}
    for r in hz_rows:
        cokey = str(r["cokey"]).strip()
        sand = safe_float(r.get("sandtotal_r"))
        silt = safe_float(r.get("silttotal_r"))
        clay = safe_float(r.get("claytotal_r"))

        hz = {
            "hzdept_r": safe_int(r.get("hzdept_r")),
            "hzdepb_r": safe_int(r.get("hzdepb_r")),
            "sandtotal_r": sand,
            "silttotal_r": silt,
            "claytotal_r": clay,
            "texture_class": classify_texture(sand, silt, clay),
            "awc_r": safe_float(r.get("awc_r")),
            "ksat_r": safe_float(r.get("ksat_r")),
            "dbthirdbar_r": safe_float(r.get("dbthirdbar_r")),
        }
        hz_by_cokey.setdefault(cokey, []).append(hz)

    # Fetch restrictive layers
    rest_rows = query_sda(session, f"""
        SELECT cr.cokey, cr.resdept_r
        FROM corestrictions cr
        INNER JOIN component c ON cr.cokey = c.cokey
        WHERE c.mukey IN ({mukey_sql})
    """)

    rest_by_cokey = {}
    for r in rest_rows:
        cokey = str(r["cokey"]).strip()
        depth = safe_float(r.get("resdept_r"))
        if depth is not None:
            if cokey not in rest_by_cokey or depth < rest_by_cokey[cokey]:
                rest_by_cokey[cokey] = depth

    # Fetch soil interpretations
    interp_rows = query_sda(session, f"""
        SELECT ci.cokey, ci.mrulename, ci.interphr, ci.interphrc
        FROM cointerp ci
        INNER JOIN component c ON ci.cokey = c.cokey
        WHERE c.mukey IN ({mukey_sql})
        AND ci.mrulename = 'ENG - Septic Tank Absorption Fields'
        AND ci.rulename = ci.mrulename
    """)

    interp_by_cokey = {}
    for r in interp_rows:
        cokey = str(r["cokey"]).strip()
        rc = (r.get("interphrc") or "").strip() or None
        interp_by_cokey[cokey] = {
            "rating_class": rc,
            "rating_value": safe_float(r.get("interphr")),
        }

    # Build output
    result = {
        "query_params": {
            "mukeys": mukeys,
            "depth_top_cm": depth_top,
            "depth_bottom_cm": depth_bottom,
        },
        "mapunits": {},
    }

    for mukey in mukeys:
        if mukey not in mu_info:
            continue

        mi = mu_info[mukey]
        components = comps_by_mu.get(mukey, {})

        mu_result = {
            "muname": mi["muname"],
            "mukind": mi["mukind"],
            "components": {},
            "aggregated": {},
            "interpretations": {},
        }

        comp_data_list = []

        for cokey, comp in components.items():
            horizons = hz_by_cokey.get(cokey, [])
            restriction_depth = rest_by_cokey.get(cokey)

            dw_awc = depth_weighted_avg(horizons, "awc_r", depth_top, depth_bottom, restriction_depth)
            dw_ksat = depth_weighted_avg(horizons, "ksat_r", depth_top, depth_bottom, restriction_depth)
            dw_bd = depth_weighted_avg(horizons, "dbthirdbar_r", depth_top, depth_bottom, restriction_depth)
            dw_aws = compute_aws_mm(horizons, depth_top, depth_bottom, restriction_depth)

            comp_result = {
                "compname": comp["compname"],
                "comppct_r": comp["comppct_r"],
                "hydgrp": comp["hydgrp"],
                "drainagecl": comp["drainagecl"],
                "taxsubgrp": comp["taxsubgrp"],
                "restriction_depth_cm": restriction_depth,
                "horizons": horizons,
                "depth_weighted": {
                    "awc": dw_awc,
                    "ksat": dw_ksat,
                    "dbthirdbar": dw_bd,
                    "aws_mm": dw_aws,
                },
            }

            mu_result["components"][cokey] = comp_result
            comp_data_list.append(comp_result)

        # Mapunit aggregation
        def wtd_avg(prop):
            total_pct = 0
            total_val = 0.0
            for cd in comp_data_list:
                val = cd["depth_weighted"].get(prop)
                pct = cd.get("comppct_r")
                if val is not None and pct is not None:
                    total_pct += pct
                    total_val += pct * val
            return total_val / total_pct if total_pct > 0 else None

        def dom_cond(prop_name):
            class_pct = {}
            for cd in comp_data_list:
                cls = cd.get(prop_name)
                pct = cd.get("comppct_r")
                if cls and pct:
                    class_pct[cls] = class_pct.get(cls, 0) + pct
            if not class_pct:
                return None
            max_pct = max(class_pct.values())
            candidates = sorted([c for c, p in class_pct.items() if p == max_pct])
            return candidates[0]

        mu_result["aggregated"] = {
            "wtd_avg_awc": wtd_avg("awc"),
            "wtd_avg_ksat": wtd_avg("ksat"),
            "wtd_avg_bd": wtd_avg("dbthirdbar"),
            "wtd_avg_aws_mm": wtd_avg("aws_mm"),
            "dominant_hydgrp": dom_cond("hydgrp"),
            "dominant_drainagecl": dom_cond("drainagecl"),
        }

        # Interpretation aggregation
        interp_key = "ENG - Septic Tank Absorption Fields"
        interp_comps = {}
        for cokey in components:
            if cokey in interp_by_cokey:
                interp_comps[cokey] = interp_by_cokey[cokey]

        class_pct = {}
        wtd_val_sum = 0.0
        wtd_pct_sum = 0
        for cokey, idata in interp_comps.items():
            comp = components.get(cokey, {})
            pct = comp.get("comppct_r")
            rc = idata.get("rating_class")
            rv = idata.get("rating_value")

            if rc and rc.lower() != "not rated" and pct:
                class_pct[rc] = class_pct.get(rc, 0) + pct
                if rv is not None:
                    wtd_val_sum += pct * rv
                    wtd_pct_sum += pct

        dom_rc = None
        if class_pct:
            max_pct_val = max(class_pct.values())
            candidates = sorted([c for c, p in class_pct.items() if p == max_pct_val])
            dom_rc = candidates[0]

        wtd_rv = wtd_val_sum / wtd_pct_sum if wtd_pct_sum > 0 else None

        mu_result["interpretations"][interp_key] = {
            "components": interp_comps,
            "dominant_rating_class": dom_rc,
            "weighted_rating_value": wtd_rv,
        }

        result["mapunits"][mukey] = mu_result

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
