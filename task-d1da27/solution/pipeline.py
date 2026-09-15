#!/usr/bin/env python3
"""
Seismic hazard analysis pipeline.
Fetches USGS earthquake catalog data, computes Gutenberg-Richter statistics,
queries ASCE 7-22 design parameters, and performs hazard discrepancy analysis.
"""

import csv
import json
import math
import os
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime


# === Configuration ===

START_TIME = "2024-01-01"
END_TIME = "2024-03-31"
MIN_MAG = 2.5
MIN_LAT, MAX_LAT = 32, 49
MIN_LON, MAX_LON = -125, -105
GRID_BIN_SIZE = 1.0
MIN_EVENTS_PER_CELL = 10
MAG_BIN_WIDTH = 0.1
MAXC_CORRECTION = 0.2
SEARCH_RADIUS_KM = 200
RISK_CATEGORY = "II"
SITE_CLASS = "D"


# === Utility Functions ===

def haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance between two points on Earth in kilometers."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = [math.radians(x) for x in [lat1, lon1, lat2, lon2]]
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def fetch_url(url, retries=3, delay=5):
    """Fetch URL content with retry logic."""
    headers = {"User-Agent": "SeismicHazardPipeline/1.0 (research)"}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            print(f"  Attempt {attempt + 1}/{retries} failed: {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def parse_iso_time(time_str):
    """Parse ISO 8601 time string to datetime object."""
    if time_str.endswith("Z"):
        time_str = time_str[:-1] + "+00:00"
    return datetime.fromisoformat(time_str)


def grid_cell_center(lat, lon, bin_size=1.0):
    """Return center of the grid cell containing the given coordinates."""
    lat_c = math.floor(lat / bin_size) * bin_size + bin_size / 2.0
    lon_c = math.floor(lon / bin_size) * bin_size + bin_size / 2.0
    return (round(lat_c, 1), round(lon_c, 1))


# === Data Fetching ===

def fetch_catalog():
    """Fetch earthquake catalog from USGS FDSN Event API as CSV."""
    url = (
        f"https://earthquake.usgs.gov/fdsnws/event/1/query?"
        f"format=csv&starttime={START_TIME}&endtime={END_TIME}"
        f"&minmagnitude={MIN_MAG}"
        f"&minlatitude={MIN_LAT}&maxlatitude={MAX_LAT}"
        f"&minlongitude={MIN_LON}&maxlongitude={MAX_LON}"
        f"&orderby=time"
    )
    print(f"Fetching catalog from USGS FDSN Event API...")
    print(f"  URL: {url}")
    text = fetch_url(url)

    lines = text.strip().split("\n")
    reader = csv.DictReader(lines)
    events = []
    skipped = 0
    for row in reader:
        try:
            mag = float(row["mag"]) if row.get("mag") else None
            if mag is None:
                skipped += 1
                continue
            events.append({
                "time": row["time"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "depth": float(row["depth"]) if row.get("depth") else None,
                "mag": mag,
                "magType": row.get("magType", ""),
                "place": row.get("place", ""),
                "id": row.get("id", ""),
            })
        except (ValueError, KeyError):
            skipped += 1
            continue

    print(f"  Parsed {len(events)} events ({skipped} skipped)")
    return events


def query_design_maps(lat, lon):
    """Query USGS ASCE 7-22 Design Maps web service."""
    url = (
        f"https://earthquake.usgs.gov/ws/designmaps/asce7-22.json?"
        f"latitude={lat}&longitude={lon}"
        f"&riskCategory={RISK_CATEGORY}&siteClass={SITE_CLASS}"
        f"&title=hazard_analysis"
    )
    print(f"  Querying design maps for ({lat}, {lon})...")
    text = fetch_url(url)
    data = json.loads(text)

    if data.get("request", {}).get("status") != "success":
        print(f"  WARNING: API returned non-success status", file=sys.stderr)
        return None

    d = data.get("response", {}).get("data", {})
    return {
        "ss": d.get("ss"),
        "s1": d.get("s1"),
        "sms": d.get("sms"),
        "sm1": d.get("sm1"),
        "sds": d.get("sds"),
        "sd1": d.get("sd1"),
        "sdc": d.get("sdc"),
        "pgam": d.get("pgam"),
        "t0": d.get("t0"),
        "ts": d.get("ts"),
        "tl": d.get("tl"),
    }


# === Seismological Analysis ===

def compute_mc_maxc(magnitudes):
    """
    Compute completeness magnitude using the Maximum Curvature (MAXC) method
    with a +0.2 correction and 0.1 magnitude bin width.
    """
    if len(magnitudes) < 5:
        return None

    bins = defaultdict(int)
    for m in magnitudes:
        bin_idx = round(m / MAG_BIN_WIDTH)
        bin_center = round(bin_idx * MAG_BIN_WIDTH, 2)
        bins[bin_center] += 1

    if not bins:
        return None

    peak_bin = max(bins, key=bins.get)
    mc = round(peak_bin + MAXC_CORRECTION, 2)
    return mc


def compute_gr_parameters(magnitudes, mc):
    """
    Compute Gutenberg-Richter b-value using Aki (1965) MLE:
        b = log10(e) / (M_mean - (Mc - dM/2))

    Standard error via Shi & Bolt (1982):
        delta_b = 2.30 * b^2 * sigma / sqrt(n)
    """
    above_mc = [m for m in magnitudes if m >= mc]
    n = len(above_mc)

    if n < 5:
        return None, None

    m_mean = sum(above_mc) / n
    m_min = mc - MAG_BIN_WIDTH / 2.0

    denominator = m_mean - m_min
    if denominator <= 0:
        return None, None

    b = math.log10(math.e) / denominator

    if n > 1:
        variance = sum((m - m_mean) ** 2 for m in above_mc) / (n - 1)
        sigma = math.sqrt(variance)
    else:
        sigma = 0.0

    b_stderr = 2.30 * b ** 2 * sigma / math.sqrt(n)

    return b, b_stderr


# === Main Pipeline ===

def main():
    os.makedirs("/app/output", exist_ok=True)

    with open("/app/sites.json") as f:
        sites = json.load(f)
    print(f"Loaded {len(sites)} building sites\n")

    # Fetch earthquake catalog
    print("=" * 60)
    print("Fetching Earthquake Catalog")
    print("=" * 60)
    events = fetch_catalog()
    print(f"Catalog contains {len(events)} events\n")

    # Compute catalog time span
    parsed_times = []
    for e in events:
        try:
            parsed_times.append(parse_iso_time(e["time"]))
        except (ValueError, TypeError):
            pass

    if len(parsed_times) >= 2:
        time_span_days = (max(parsed_times) - min(parsed_times)).total_seconds() / 86400.0
    else:
        time_span_days = 90.0
    time_span_years = time_span_days / 365.25

    mags = [e["mag"] for e in events]

    catalog_summary = {
        "total_events": len(events),
        "time_span_days": round(time_span_days, 2),
        "time_span_years": round(time_span_years, 4),
        "min_magnitude": round(min(mags), 2) if mags else None,
        "max_magnitude": round(max(mags), 2) if mags else None,
        "mean_magnitude": round(sum(mags) / len(mags), 3) if mags else None,
        "region": {
            "min_lat": MIN_LAT,
            "max_lat": MAX_LAT,
            "min_lon": MIN_LON,
            "max_lon": MAX_LON,
        },
    }
    with open("/app/output/catalog_summary.json", "w") as f:
        json.dump(catalog_summary, f, indent=2)
    print("Wrote catalog_summary.json")

    # Grid-based Gutenberg-Richter analysis
    print("\n" + "=" * 60)
    print("Grid-Based Frequency-Magnitude Analysis")
    print("=" * 60)

    grid_events = defaultdict(list)
    for e in events:
        cell = grid_cell_center(e["latitude"], e["longitude"], GRID_BIN_SIZE)
        grid_events[cell].append(e["mag"])

    grid_cells = []
    for (lat_c, lon_c) in sorted(grid_events.keys()):
        cell_mags = grid_events[(lat_c, lon_c)]
        if len(cell_mags) < MIN_EVENTS_PER_CELL:
            continue

        mc = compute_mc_maxc(cell_mags)
        if mc is None:
            continue

        b, b_stderr = compute_gr_parameters(cell_mags, mc)
        if b is None:
            continue

        n_above_mc = len([m for m in cell_mags if m >= mc])
        if time_span_years > 0 and n_above_mc > 0:
            annual_rate = n_above_mc / time_span_years
            a_value = math.log10(annual_rate) + b * mc
        else:
            a_value = None

        grid_cells.append({
            "lat_center": lat_c,
            "lon_center": lon_c,
            "event_count": len(cell_mags),
            "mc": round(mc, 2),
            "b_value": round(b, 4),
            "b_value_stderr": round(b_stderr, 4),
            "a_value": round(a_value, 4) if a_value is not None else None,
            "events_above_mc": n_above_mc,
        })
        print(
            f"  Cell ({lat_c:6.1f}, {lon_c:7.1f}): "
            f"n={len(cell_mags):4d}, Mc={mc:.2f}, "
            f"b={b:.3f} +/- {b_stderr:.3f}"
        )

    grid_output = {
        "bin_size_degrees": GRID_BIN_SIZE,
        "min_events_threshold": MIN_EVENTS_PER_CELL,
        "magnitude_bin_width": MAG_BIN_WIDTH,
        "maxc_correction": MAXC_CORRECTION,
        "method": "Aki (1965) MLE with MAXC completeness",
        "cells": grid_cells,
    }
    with open("/app/output/grid_bvalues.json", "w") as f:
        json.dump(grid_output, f, indent=2)
    print(f"\nWrote grid_bvalues.json ({len(grid_cells)} qualifying cells)")

    # Query ASCE 7-22 Design Maps for each site
    print("\n" + "=" * 60)
    print("Querying USGS ASCE 7-22 Design Maps")
    print("=" * 60)

    site_designs = []
    for site in sites:
        params = query_design_maps(site["latitude"], site["longitude"])
        entry = {
            "name": site["name"],
            "latitude": site["latitude"],
            "longitude": site["longitude"],
        }
        if params:
            entry.update(params)
        site_designs.append(entry)
        if params:
            print(
                f"    {site['name']}: SDS={params.get('sds')}, "
                f"SD1={params.get('sd1')}, SDC={params.get('sdc')}"
            )

    design_output = {
        "reference_document": "ASCE7-22",
        "risk_category": RISK_CATEGORY,
        "site_class": SITE_CLASS,
        "sites": site_designs,
    }
    with open("/app/output/site_design.json", "w") as f:
        json.dump(design_output, f, indent=2)
    print("Wrote site_design.json")

    # Catalog-based activity metrics per site
    print("\n" + "=" * 60)
    print("Computing Catalog-Based Activity Metrics")
    print("=" * 60)

    site_activities = []
    for site in sites:
        nearby = []
        for e in events:
            d = haversine_km(
                site["latitude"], site["longitude"],
                e["latitude"], e["longitude"],
            )
            if d <= SEARCH_RADIUS_KM:
                nearby.append({"mag": e["mag"], "dist": d})

        n_events = len(nearby)
        max_mag = max(ev["mag"] for ev in nearby) if nearby else None
        min_dist = min(ev["dist"] for ev in nearby) if nearby else None
        annual_rate = n_events / time_span_years if time_span_years > 0 else 0.0

        n_m4 = len([ev for ev in nearby if ev["mag"] >= 4.0])
        rate_m4 = n_m4 / time_span_years if time_span_years > 0 else 0.0

        site_activities.append({
            "name": site["name"],
            "latitude": site["latitude"],
            "longitude": site["longitude"],
            "events_within_radius": n_events,
            "max_magnitude": round(max_mag, 2) if max_mag is not None else None,
            "nearest_event_distance_km": round(min_dist, 1) if min_dist is not None else None,
            "annualized_rate_all": round(annual_rate, 2),
            "events_m4plus": n_m4,
            "annualized_rate_m4plus": round(rate_m4, 4),
        })
        print(
            f"  {site['name']:20s}: {n_events:4d} events within {SEARCH_RADIUS_KM}km, "
            f"Mmax={max_mag}, rate={annual_rate:.1f}/yr"
        )

    activity_output = {
        "search_radius_km": SEARCH_RADIUS_KM,
        "catalog_time_span_years": round(time_span_years, 4),
        "sites": site_activities,
    }
    with open("/app/output/site_activity.json", "w") as f:
        json.dump(activity_output, f, indent=2)
    print("Wrote site_activity.json")

    # Hazard discrepancy analysis
    print("\n" + "=" * 60)
    print("Hazard Discrepancy Analysis")
    print("=" * 60)

    discrepancies = []
    for i, site in enumerate(sites):
        sa = site_activities[i]
        sd = site_designs[i]

        sds = sd.get("sds")
        rate = sa["annualized_rate_all"]
        max_mag = sa["max_magnitude"]

        if sds is not None and sds > 0 and rate > 0 and max_mag is not None:
            observed_metric = rate * max_mag / 10.0
            code_metric = sds
            ratio = round(observed_metric / code_metric, 4)

            if ratio > 2.0:
                classification = "observed_exceeds_design"
            elif ratio < 0.1:
                classification = "design_exceeds_observed"
            else:
                classification = "consistent"
        else:
            ratio = None
            classification = "insufficient_data"

        discrepancies.append({
            "name": site["name"],
            "sds": sds,
            "annualized_rate": rate,
            "max_observed_magnitude": max_mag,
            "discrepancy_ratio": ratio,
            "classification": classification,
        })
        print(f"  {site['name']:20s}: ratio={ratio}, class={classification}")

    discrepancy_output = {
        "method": "Observed seismicity rate * max_magnitude / (10 * SDS)",
        "thresholds": {
            "observed_exceeds_design": "> 2.0",
            "design_exceeds_observed": "< 0.1",
        },
        "sites": discrepancies,
    }
    with open("/app/output/discrepancy.json", "w") as f:
        json.dump(discrepancy_output, f, indent=2)
    print("Wrote discrepancy.json")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"All output files written to /app/output/")


if __name__ == "__main__":
    main()
