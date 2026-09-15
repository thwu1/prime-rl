"""Hazard calculation with source-type-specific distance and floating ruptures."""

import math
from pipeline.mfd import discretize_mfd
from pipeline.distance import (
    horizontal_distance,
    convert_trace_to_local,
    point_to_polyline,
)
from pipeline.gmm import evaluate_gmm, compute_exceedance


def compute_source_hazard(src, site_lon, site_lat, vs30, imls, branches,
                          mref, vref, trunc_level, kpd, fstep):
    """Compute hazard contribution from a single seismic source.

    Handles both point sources (direct distance calculation) and fault
    sources (floating rupture averaging along the trace).
    """
    src_rates = [0.0] * len(imls)
    mag_rate_pairs = discretize_mfd(src["mfd"])

    for mag, rate in mag_rate_pairs:
        if src["type"] == "point":
            rjb_weights = [(
                horizontal_distance(
                    site_lon, site_lat,
                    src["longitude"], src["latitude"],
                    kpd
                ),
                1.0,
            )]
        else:
            rjb_weights = _floating_rupture_rjb(
                site_lon, site_lat, src["trace"], mag, kpd, fstep
            )

        for rjb, rw in rjb_weights:
            for br in branches:
                mu, sig = evaluate_gmm(mag, rjb, vs30, br, mref, vref)
                bw = br["weight"]
                for i, y in enumerate(imls):
                    p = compute_exceedance(y, mu, sig, trunc_level)
                    src_rates[i] += rate * p * bw * rw

    return src_rates


def _floating_rupture_rjb(site_lon, site_lat, trace, mag, kpd, fstep):
    """Compute distance samples for floating rupture positions.

    The rupture slides along the fault trace at the specified step
    interval. Returns a list of (rjb, weight) pairs representing
    each floating position's distance and its contribution weight.
    """
    tkm = convert_trace_to_local(trace, site_lon, site_lat, kpd)

    cum_dist = [0.0]
    for i in range(len(tkm) - 1):
        seg_len = math.sqrt(
            (tkm[i + 1][0] - tkm[i][0]) ** 2
            + (tkm[i + 1][1] - tkm[i][1]) ** 2
        )
        cum_dist.append(cum_dist[-1] + seg_len)
    fault_len = cum_dist[-1]

    rup_len = math.exp(-2.44 + 0.59 * mag)
    rup_len = min(rup_len, fault_len)

    if rup_len >= fault_len - 0.01:
        return [(point_to_polyline(0.0, 0.0, tkm), 1.0)]

    positions = []
    s = 0.0
    while s <= fault_len - rup_len + 1e-6:
        positions.append(s)
        s += fstep

    n_pos = len(positions)
    result = []
    for sp in positions:
        ep = sp + rup_len
        sub = _extract_subtrace(tkm, cum_dist, sp, ep)
        d = point_to_polyline(0.0, 0.0, sub)
        result.append((d, 1.0 / n_pos))
    return result


def _extract_subtrace(tkm, cum_dist, start_km, end_km):
    """Extract the portion of a trace polyline between two distances."""
    pts = []
    for i in range(len(tkm) - 1):
        seg_s = cum_dist[i]
        seg_e = cum_dist[i + 1]
        if seg_e <= start_km or seg_s >= end_km:
            continue
        sl = seg_e - seg_s
        if sl < 1e-10:
            continue
        dx = tkm[i + 1][0] - tkm[i][0]
        dy = tkm[i + 1][1] - tkm[i][1]
        cs = max(start_km, seg_s)
        ce = min(end_km, seg_e)
        ts = (cs - seg_s) / sl
        te = (ce - seg_s) / sl
        if not pts:
            pts.append((tkm[i][0] + ts * dx, tkm[i][1] + ts * dy))
        pts.append((tkm[i][0] + te * dx, tkm[i][1] + te * dy))
    return pts
