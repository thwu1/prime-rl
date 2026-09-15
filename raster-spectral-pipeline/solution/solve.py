#!/usr/bin/env python3
"""
Multi-criteria geospatial suitability analysis engine.
Implements AHP weighting, fuzzy normalization, Jenks natural breaks,
contiguous site extraction, and sensitivity analysis.
"""
import json
import os
import numpy as np
import rasterio
from rasterio.features import shapes as rasterio_shapes
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from scipy import ndimage


def load_config(path="/app/criteria.json"):
    with open(path) as f:
        return json.load(f)


def read_raster(path):
    with rasterio.open(path) as ds:
        data = ds.read(1).astype(np.float64)
        profile = ds.profile.copy()
        transform = ds.transform
        nodata = ds.nodata
    return data, profile, transform, nodata


# ---------------------------------------------------------------------------
# AHP
# ---------------------------------------------------------------------------
def compute_ahp_weights(matrix):
    """Compute priority weights via power iteration on pairwise comparison matrix."""
    A = np.array(matrix, dtype=np.float64)
    n = A.shape[0]
    v = np.ones(n) / n
    for _ in range(300):
        v_new = A @ v
        v_new /= v_new.sum()
        if np.max(np.abs(v_new - v)) < 1e-12:
            break
        v = v_new
    weights = v_new
    Aw = A @ weights
    lam = np.mean(Aw / weights)
    ci = (lam - n) / (n - 1) if n > 1 else 0
    ri_table = {
        1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12,
        6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
    }
    ri = ri_table.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0
    return weights, lam, cr


# ---------------------------------------------------------------------------
# Normalization functions
# ---------------------------------------------------------------------------
def norm_linear_cost(data, valid, ideal, max_acc, hard_limit=None):
    out = np.zeros_like(data)
    out[valid] = np.clip((max_acc - data[valid]) / (max_acc - ideal), 0, 1)
    if hard_limit is not None:
        out[valid & (data > hard_limit)] = 0
    return out


def norm_linear_benefit(data, valid, min_acc, max_val):
    out = np.zeros_like(data)
    d = max_val - min_acc
    if d > 0:
        out[valid] = np.clip((data[valid] - min_acc) / d, 0, 1)
    return out


def norm_sigmoidal_cost(data, valid, midpoint, spread):
    out = np.zeros_like(data)
    out[valid] = 1.0 / (1.0 + np.exp(spread * (data[valid] - midpoint)))
    return out


def norm_gaussian_circular(data, valid, optimal, sigma):
    """Gaussian on circular aspect data with 0/360 wrap-around."""
    out = np.zeros_like(data)
    diff = data[valid] - optimal
    ang = np.abs((diff + 180) % 360 - 180)
    out[valid] = np.exp(-(ang ** 2) / (2 * sigma ** 2))
    return out


def norm_categorical(data, valid, scores):
    out = np.zeros_like(data)
    for k, v in scores.items():
        out[valid & (data == int(k))] = v
    return out


# ---------------------------------------------------------------------------
# Jenks natural breaks (Fisher-Jenks DP)
# ---------------------------------------------------------------------------
def jenks_breaks(values, k):
    arr = np.sort(values)
    n = len(arr)
    if n <= k:
        return list(np.linspace(arr[0], arr[-1], k + 1))
    if n > 5000:
        idx = np.linspace(0, n - 1, 5000, dtype=int)
        arr = arr[idx]
        n = len(arr)

    cs = np.zeros(n + 1)
    cs2 = np.zeros(n + 1)
    for i in range(n):
        cs[i + 1] = cs[i] + arr[i]
        cs2[i + 1] = cs2[i] + arr[i] ** 2

    def ssd(a, b):
        c = b - a + 1
        s = cs[b + 1] - cs[a]
        s2 = cs2[b + 1] - cs2[a]
        return s2 - s * s / c

    gvf = np.full((n, k), np.inf)
    bp = np.zeros((n, k), dtype=int)
    for i in range(n):
        gvf[i][0] = ssd(0, i)
    for j in range(1, k):
        for i in range(j, n):
            best = np.inf
            bi = j
            for m in range(j - 1, i):
                v = gvf[m][j - 1] + ssd(m + 1, i)
                if v < best:
                    best = v
                    bi = m + 1
            gvf[i][j] = best
            bp[i][j] = bi

    breaks = [float(arr[-1])]
    ix = n - 1
    for j in range(k - 1, 0, -1):
        b = bp[ix][j]
        breaks.append(float(arr[b]))
        ix = b - 1
    breaks.append(float(arr[0]))
    breaks.reverse()
    return breaks


# ---------------------------------------------------------------------------
# Site extraction
# ---------------------------------------------------------------------------
def extract_sites(suit, threshold, min_px, transform, valid):
    binary = (suit >= threshold) & valid
    labeled, nf = ndimage.label(binary)
    pa = abs(transform.a * transform.e)
    sites = []
    for lid in range(1, nf + 1):
        m = labeled == lid
        pc = int(m.sum())
        if pc < min_px:
            continue
        vals = suit[m]
        rows, cols = np.where(m)
        cx = transform.c + (cols.mean() + 0.5) * transform.a
        cy = transform.f + (rows.mean() + 0.5) * transform.e
        sites.append({
            "site_id": 0,
            "pixel_count": pc,
            "area_ha": round(pc * pa / 10000, 2),
            "mean_suitability": round(float(vals.mean()), 4),
            "max_suitability": round(float(vals.max()), 4),
            "centroid_x": round(cx, 2),
            "centroid_y": round(cy, 2),
            "_mask": m,
        })
    sites.sort(key=lambda s: s["mean_suitability"], reverse=True)
    for i, s in enumerate(sites):
        s["site_id"] = i + 1
    return sites


def sites_to_geojson(sites, transform):
    feats = []
    for site in sites:
        m = site["_mask"]
        r = m.astype(np.int32)
        polys = [
            shape(g)
            for g, v in rasterio_shapes(r, mask=m, transform=transform)
            if v == 1
        ]
        if not polys:
            continue
        merged = unary_union(polys)
        props = {k: v for k, v in site.items() if k != "_mask"}
        feats.append({
            "type": "Feature",
            "geometry": mapping(merged),
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": feats}


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------
def sensitivity_analysis(normalized, weights, cmask, vmask, config, names):
    pert = config["output"]["sensitivity_perturbation"]
    thr = config["output"]["suitability_threshold"]
    ps = config["output"]["pixel_size_m"]
    mah = config["output"]["min_site_area_ha"]
    mpx = int(mah * 10000 / (ps ** 2))
    result = {}
    for i, nm in enumerate(names):
        vals = {}
        for d, lb in [(1, "plus"), (-1, "minus")]:
            pw = weights.copy()
            pw[i] *= (1 + d * pert)
            pw /= pw.sum()
            s = np.zeros_like(normalized[0])
            for j in range(len(names)):
                s += pw[j] * normalized[j]
            s[cmask] = 0
            s[~vmask] = 0
            binary = (s >= thr) & vmask & ~cmask
            lab, nf = ndimage.label(binary)
            best = 0.0
            for lid in range(1, nf + 1):
                mm = lab == lid
                if mm.sum() >= mpx:
                    mv = float(s[mm].mean())
                    if mv > best:
                        best = mv
            vals[lb] = round(best, 4)
        result[nm] = {
            "weight_plus_10pct": vals["plus"],
            "weight_minus_10pct": vals["minus"],
            "delta": round(vals["plus"] - vals["minus"], 4),
        }
    return result


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    config = load_config()
    os.makedirs("/app/output", exist_ok=True)

    # AHP weights
    weights, lam, cr = compute_ahp_weights(config["ahp_matrix"])
    names = [c["name"] for c in config["criteria"]]
    wd = {n: round(float(w), 6) for n, w in zip(names, weights)}
    print(f"AHP weights: {wd}")
    print(f"Consistency ratio: {cr:.6f}")

    # Read criterion layers
    ref_prof = None
    ref_tr = None
    cdata = {}
    nd_mask = None
    for crit in config["criteria"]:
        data, prof, tr, nd = read_raster(crit["layer"])
        cdata[crit["name"]] = data
        if ref_prof is None:
            ref_prof = prof
            ref_tr = tr
            nd_mask = (
                (data == nd) if nd is not None
                else np.zeros_like(data, dtype=bool)
            )
        else:
            if nd is not None:
                nd_mask |= (data == nd)
    vmask = ~nd_mask
    h, w = list(cdata.values())[0].shape

    # Constraint mask
    cmask = np.zeros((h, w), dtype=bool)
    for con in config["constraints"]:
        if "layer" in con:
            cd, _, _, _ = read_raster(con["layer"])
            cmask |= (cd == con["exclude_value"])
        elif "source" in con:
            cmask |= (cdata[con["source"]] == con["exclude_value"])

    # Normalize each criterion
    normalized = []
    cstats = {}
    for crit in config["criteria"]:
        nm = crit["name"]
        d = cdata[nm]
        nt = crit.get("normalization")
        ct = crit.get("type")
        if nt == "linear" and ct == "cost":
            norm = norm_linear_cost(
                d, vmask, crit["ideal_value"],
                crit["max_acceptable"], crit.get("hard_limit"),
            )
        elif nt == "linear" and ct == "benefit":
            norm = norm_linear_benefit(
                d, vmask, crit["min_acceptable"], crit["max_value"],
            )
        elif nt == "sigmoidal":
            norm = norm_sigmoidal_cost(
                d, vmask, crit["midpoint"], crit["spread"],
            )
        elif nt == "gaussian":
            norm = norm_gaussian_circular(
                d, vmask, crit["optimal_direction"], crit["sigma"],
            )
        elif ct == "categorical":
            norm = norm_categorical(d, vmask, crit["suitability_scores"])
        else:
            vmin, vmax = d[vmask].min(), d[vmask].max()
            norm = np.zeros_like(d)
            if vmax > vmin:
                norm[vmask] = (d[vmask] - vmin) / (vmax - vmin)
        normalized.append(norm)
        rv = d[vmask & ~cmask]
        nv = norm[vmask & ~cmask]
        cstats[nm] = {
            "raw_min": round(float(rv.min()), 4) if len(rv) else 0,
            "raw_max": round(float(rv.max()), 4) if len(rv) else 0,
            "raw_mean": round(float(rv.mean()), 4) if len(rv) else 0,
            "normalized_min": round(float(nv.min()), 4) if len(nv) else 0,
            "normalized_max": round(float(nv.max()), 4) if len(nv) else 0,
            "normalized_mean": round(float(nv.mean()), 4) if len(nv) else 0,
        }

    # Weighted linear combination
    suit = np.zeros((h, w), dtype=np.float64)
    for i in range(len(names)):
        suit += weights[i] * normalized[i]
    suit[cmask] = 0
    suit[nd_mask] = 0

    # Write suitability raster
    sp = ref_prof.copy()
    sp.update(count=1, dtype="float32", nodata=0)
    with rasterio.open("/app/output/suitability.tif", "w", **sp) as dst:
        dst.write(suit.astype(np.float32), 1)
    print("  -> suitability.tif")

    # Jenks classification
    vs = suit[vmask & ~cmask]
    vs = vs[vs > 0]
    nc = config["output"]["suitability_classes"]
    classified = np.zeros((h, w), dtype=np.uint8)
    if len(vs) > 0:
        brks = jenks_breaks(vs, nc)
        for c in range(nc):
            if c == 0:
                m = vmask & ~cmask & (suit > 0) & (suit <= brks[c + 1])
            else:
                m = vmask & ~cmask & (suit > brks[c]) & (suit <= brks[c + 1])
            classified[m] = c + 1

    cp = ref_prof.copy()
    cp.update(count=1, dtype="uint8", nodata=0)
    with rasterio.open("/app/output/suitability_classified.tif", "w", **cp) as dst:
        dst.write(classified, 1)
    print("  -> suitability_classified.tif")

    # Extract contiguous sites
    ps = config["output"]["pixel_size_m"]
    mah = config["output"]["min_site_area_ha"]
    mpx = int(mah * 10000 / (ps ** 2))
    thr = config["output"]["suitability_threshold"]
    sites = extract_sites(suit, thr, mpx, ref_tr, vmask & ~cmask)
    gj = sites_to_geojson(sites, ref_tr)
    with open("/app/output/suitable_sites.geojson", "w") as f:
        json.dump(gj, f, indent=2)
    print(f"  -> suitable_sites.geojson ({len(gj['features'])} sites)")

    # Sensitivity analysis
    sens = sensitivity_analysis(
        normalized, weights.copy(), cmask, vmask, config, names,
    )

    # Report
    ss = [
        {
            "site_id": s["site_id"],
            "area_ha": s["area_ha"],
            "mean_suitability": s["mean_suitability"],
            "max_suitability": s["max_suitability"],
            "centroid_x": s["centroid_x"],
            "centroid_y": s["centroid_y"],
        }
        for s in sites
    ]
    report = {
        "ahp_weights": wd,
        "consistency_ratio": round(float(cr), 6),
        "lambda_max": round(float(lam), 6),
        "criterion_statistics": cstats,
        "site_summary": ss,
        "sensitivity": sens,
    }
    with open("/app/output/report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("  -> report.json")

    print("Suitability analysis complete.")


if __name__ == "__main__":
    main()
