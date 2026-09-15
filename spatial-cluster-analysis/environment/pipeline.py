#!/usr/bin/env python3
"""Spatial analysis pipeline for zone-level autocorrelation statistics."""

import json
import csv
import os
import numpy as np
from shapely.geometry import shape, Point
from scipy.stats import norm


def load_zones(path):
    with open(path) as f:
        data = json.load(f)
    zones = []
    for feat in data["features"]:
        zones.append({
            "zone_id": feat["properties"]["zone_id"],
            "geometry": shape(feat["geometry"]),
            "feature": feat,
        })
    return zones


def load_observations(path):
    obs = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            obs.append({
                "obs_id": row["obs_id"],
                "point": Point(float(row["longitude"]), float(row["latitude"])),
                "value": float(row["value"]),
            })
    return obs


def spatial_join(zones, observations):
    """Assign each observation to its containing zone."""
    zone_obs = {z["zone_id"]: [] for z in zones}
    for obs in observations:
        for z in zones:
            if z["geometry"].contains(obs["point"]):
                zone_obs[z["zone_id"]].append(obs["value"])
                break
    return zone_obs


def compute_zone_values(zone_obs):
    return {
        zid: float(np.mean(vals)) if vals else 0.0
        for zid, vals in zone_obs.items()
    }


def build_contiguity_weights(zones):
    """Build contiguity weights from zone geometries."""
    n = len(zones)
    weights = {z["zone_id"]: [] for z in zones}
    for i in range(n):
        for j in range(i + 1, n):
            shared = zones[i]["geometry"].intersection(zones[j]["geometry"])
            if shared.length > 0:
                weights[zones[i]["zone_id"]].append(zones[j]["zone_id"])
                weights[zones[j]["zone_id"]].append(zones[i]["zone_id"])
    for zid in weights:
        weights[zid] = sorted(weights[zid])
    return weights


def build_weight_matrix(zone_ids, weights):
    n = len(zone_ids)
    idx = {zid: i for i, zid in enumerate(zone_ids)}
    W = np.zeros((n, n))
    for zid in zone_ids:
        i = idx[zid]
        for nid in weights[zid]:
            j = idx[nid]
            W[i, j] = 1.0
    return W


def compute_global_morans_i(z, W):
    """Compute Global Moran's I with analytical variance under randomization."""
    n = len(z)
    S0 = W.sum()

    numerator = n * float(z @ W @ z)
    denominator = S0 * float(z @ z)
    I = numerator / denominator

    EI = -1.0 / (n - 1)

    S1 = 0.5 * float(np.sum((W + W.T) ** 2))
    S2 = float(np.sum((W.sum(axis=1) + W.sum(axis=0)) ** 2))
    m2 = float(np.sum(z ** 2)) / n
    m4 = float(np.sum(z ** 4)) / n
    b2 = m4 / (m2 ** 2)

    A = n * ((n * n - 3 * n + 3) * S1 - n * S2 + 3 * S0 ** 2)
    B = b2 * ((n * n - n) * S1 - 2 * n * S2 + 6 * S0 ** 2)
    C = (n - 1) * (n - 2) * (n - 3) * S0 ** 2

    VI = (A - B) / C - EI ** 2

    z_score = (I - EI) / np.sqrt(VI)
    p_value = 2 * float(norm.sf(abs(z_score)))

    return {
        "morans_i": float(I),
        "expected_i": float(EI),
        "variance": float(VI),
        "z_score": float(z_score),
        "p_value": float(p_value),
    }


def compute_lisa(z, W, n_perms=999, seed=12345):
    """Compute Local Moran's I with conditional permutation inference."""
    n = len(z)
    m2 = float(np.sum(z ** 2)) / n
    rng = np.random.default_rng(seed)

    results = []
    for i in range(n):
        zi = z[i]
        neighbor_idx = np.where(W[i] > 0)[0]
        wi = len(neighbor_idx)

        if wi == 0:
            results.append({
                "local_morans_i": 0.0,
                "z_score": 0.0,
                "p_value": 1.0,
                "cluster_type": "NS",
            })
            continue

        lag_i = float(z[neighbor_idx].sum())
        Ii = (zi / m2) * lag_i

        z_others = np.delete(z, i)
        perm_neighbor_idx = np.array(
            [j if j < i else j - 1 for j in neighbor_idx]
        )

        Ii_perms = np.empty(n_perms)
        for p in range(n_perms):
            perm = rng.permutation(z_others)
            lag_perm = float(perm[perm_neighbor_idx].sum())
            Ii_perms[p] = (zi / m2) * lag_perm

        count = int(np.sum(np.abs(Ii_perms) >= abs(Ii)))
        p_value = count / n_perms

        perm_mean = float(Ii_perms.mean())
        perm_std = float(Ii_perms.std())
        z_score = (Ii - perm_mean) / perm_std if perm_std > 1e-12 else 0.0

        lag_std = lag_i / wi
        if p_value < 0.05:
            if zi > 0 and lag_std > 0:
                cluster = "HH"
            elif zi > 0 and lag_std < 0:
                cluster = "HL"
            elif zi < 0 and lag_std > 0:
                cluster = "LH"
            else:
                cluster = "LL"
        else:
            cluster = "NS"

        results.append({
            "local_morans_i": float(Ii),
            "z_score": float(z_score),
            "p_value": float(p_value),
            "cluster_type": cluster,
        })

    return results


def compute_gi_star(x, W):
    """Compute Getis-Ord Gi* statistic for hot spot analysis."""
    n = len(x)
    x_mean = float(x.mean())
    S = float(np.sqrt(np.sum(x ** 2) / n - x_mean ** 2))

    results = []
    for i in range(n):
        neighbor_idx = np.where(W[i] > 0)[0]
        sum_wxj = float(x[neighbor_idx].sum())
        di = len(neighbor_idx)

        numerator = sum_wxj - x_mean * di
        denominator = S * np.sqrt((n * di - di ** 2) / (n - 1))

        if denominator > 1e-12:
            z_score = numerator / denominator
        else:
            z_score = 0.0

        p_value = 2 * float(norm.sf(abs(z_score)))

        if p_value < 0.05:
            classification = "Hot Spot" if z_score > 0 else "Cold Spot"
        else:
            classification = "Not Significant"

        results.append({
            "gi_star": float(z_score),
            "z_score": float(z_score),
            "p_value": float(p_value),
            "classification": classification,
        })

    return results


def main():
    os.makedirs("/app/output", exist_ok=True)

    zones = load_zones("/app/data/zones.geojson")
    observations = load_observations("/app/data/observations.csv")
    zone_ids = [z["zone_id"] for z in zones]

    zone_obs = spatial_join(zones, observations)
    zone_values = compute_zone_values(zone_obs)

    with open("/app/output/zone_values.json", "w") as f:
        json.dump(zone_values, f, indent=2)

    weights = build_contiguity_weights(zones)
    with open("/app/output/spatial_weights.json", "w") as f:
        json.dump(weights, f, indent=2)

    W = build_weight_matrix(zone_ids, weights)

    x = np.array([zone_values[zid] for zid in zone_ids])
    z = x - x.mean()

    global_result = compute_global_morans_i(z, W)
    with open("/app/output/global_autocorrelation.json", "w") as f:
        json.dump(global_result, f, indent=2)

    lisa_results = compute_lisa(z, W)

    lisa_features = []
    for k, zone in enumerate(zones):
        zid = zone["zone_id"]
        lisa = lisa_results[k]
        props = {
            "zone_id": zid,
            "value": zone_values[zid],
            "local_morans_i": lisa["local_morans_i"],
            "z_score": lisa["z_score"],
            "p_value": lisa["p_value"],
            "cluster_type": lisa["cluster_type"],
        }
        lisa_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": zone["feature"]["geometry"],
        })

    with open("/app/output/local_clusters.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": lisa_features},
                  f, indent=2)

    gi_results = compute_gi_star(x, W)

    gi_features = []
    for k, zone in enumerate(zones):
        zid = zone["zone_id"]
        gi = gi_results[k]
        props = {
            "zone_id": zid,
            "value": zone_values[zid],
            "gi_star": gi["gi_star"],
            "z_score": gi["z_score"],
            "p_value": gi["p_value"],
            "classification": gi["classification"],
        }
        gi_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": zone["feature"]["geometry"],
        })

    with open("/app/output/hotspot_analysis.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": gi_features},
                  f, indent=2)

    n_hot = sum(1 for r in gi_results if r["classification"] == "Hot Spot")
    n_cold = sum(1 for r in gi_results if r["classification"] == "Cold Spot")
    n_hh = sum(1 for r in lisa_results if r["cluster_type"] == "HH")
    n_ll = sum(1 for r in lisa_results if r["cluster_type"] == "LL")

    summary = {
        "n_zones": len(zones),
        "n_observations": len(observations),
        "mean_value": float(x.mean()),
        "global_morans_i": global_result["morans_i"],
        "global_p_value": global_result["p_value"],
        "n_hot_spots": n_hot,
        "n_cold_spots": n_cold,
        "n_high_high": n_hh,
        "n_low_low": n_ll,
    }

    with open("/app/output/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("Pipeline complete.")


if __name__ == "__main__":
    main()
