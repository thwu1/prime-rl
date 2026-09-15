#!/usr/bin/env python3
"""

WCV Detector - Implementation of NASA DAIDALUS Well-Clear Volume detection
from PVS formal specifications.

All horizontal computations use nmi for distance and hours for time (knots = nmi/hr).
All vertical computations use ft for distance and seconds for time.
Output times are converted to seconds.
"""

import json
import math


def sq(x):
    return x * x


def sqv(v):
    return sum(x * x for x in v)


def dot(s, v):
    return sum(a * b for a, b in zip(s, v))


def tcpa_2d(s, v):
    """tcpa(s,v) = IF s*v < 0 THEN -(s*v)/sqv(v) ELSE 0"""
    sv = dot(s, v)
    vv = sqv(v)
    if sv < 0 and vv > 1e-30:
        return -sv / vv
    return 0.0


def tau_mod_value(s, v, DTHR):
    """taumod(s,v) = IF s*v < 0 THEN (DTHR^2 - |s|^2) / (s*v) ELSE -1"""
    sv = dot(s, v)
    if sv < 0:
        return (sq(DTHR) - sqv(s)) / sv
    return -1.0


def horizontal_wcv_check(s, v, DTHR, TTHR_hr):
    """horizontal_WCV(taumod)(s,v) from horizontal_WCV.pvs:
    sqv(s) <= sq(DTHR) OR
    (sqv(s+tcpa*v) <= sq(DTHR) AND 0 <= taumod(s,v) AND taumod(s,v) <= TTHR)
    """
    if sqv(s) <= sq(DTHR):
        return True
    t_cpa = tcpa_2d(s, v)
    s_cpa = [s[i] + t_cpa * v[i] for i in range(len(s))]
    if sqv(s_cpa) <= sq(DTHR):
        tm = tau_mod_value(s, v, DTHR)
        if 0 <= tm <= TTHR_hr:
            return True
    return False


def vertical_wcv_check(sz, vz, ZTHR, TCOA):
    """vertical_WCV(sz,vz) from vertical_WCV.pvs:
    abs(sz) <= ZTHR OR (0 <= tcoa(sz,vz) <= TCOA)
    """
    if abs(sz) <= ZTHR:
        return True
    if abs(vz) < 1e-12:
        return False
    if sz * vz < 0:
        t_coa = -sz / vz
        if 0 <= t_coa <= TCOA:
            return True
    return False


def delta_D(s, v, D):
    """Delta[D](s,v) from ACCoRD cd2d:
    Delta[D](s,v) = sq(D)*sqv(v) - sq(det(s,v))
    where det(s,v) is the 2D cross product (determinant).
    By Lagrange's identity: sq(det(s,v)) = sqv(s)*sqv(v) - sq(s*v)
    """
    cross_sq = sqv(s) * sqv(v) - sq(dot(s, v))
    return sq(D) * sqv(v) - cross_sq


def theta_D(s, v, D, eps):
    """Theta_D[D](s,v,eps) from ACCoRD cd2d:
    (-(s*v) + eps*sqrt(Delta[D](s,v))) / sqv(v)
    Returns cylinder entry (eps=-1) or exit (eps=1) time.
    """
    dd = delta_D(s, v, D)
    if dd < 0:
        return None
    vv = sqv(v)
    if vv < 1e-30:
        return None
    sv = dot(s, v)
    return (-sv + eps * math.sqrt(dd)) / vv


def discr(a, b, c):
    return b * b - 4 * a * c


def root_q(a, b, c, eps):
    d = discr(a, b, c)
    if d < 0:
        return None
    return (-b + eps * math.sqrt(d)) / (2 * a)


def horizontal_wcv_taumod_interval(T, s, v, TAUMOD, DTHR):
    """From horizontal_WCV_taumod.pvs:
    LET a=sqv(v), b=2*(s*v)+TAUMOD*sqv(v), c=sqv(s)+TAUMOD*(s*v)-sq(DTHR) IN
    IF a = 0 AND sqv(s)<=sq(DTHR) THEN WholeInterval
    ELSIF sqv(s)<=sq(DTHR) THEN (#entry:=0, exit:=min(T, Theta_D(s,v,1))#)
    ELSIF s*v>=0 OR discr(a,b,c)<0 THEN EmptyInterval
    ELSIF Delta[DTHR](s,v)>=0 AND root(a,b,c,-1)<=T THEN
      (#entry:=max(0, root(a,b,c,-1)), exit:=min(T, Theta_D(s,v,1))#)
    ELSE EmptyInterval
    """
    a = sqv(v)
    sv = dot(s, v)
    b = 2 * sv + TAUMOD * a
    c_val = sqv(s) + TAUMOD * sv - sq(DTHR)
    ss = sqv(s)

    if a < 1e-30 and ss <= sq(DTHR):
        return (0.0, T)

    if ss <= sq(DTHR):
        td = theta_D(s, v, DTHR, 1)
        if td is None:
            return (0.0, T)
        return (0.0, min(T, td))

    if sv >= 0 or discr(a, b, c_val) < 0:
        return None

    dd = delta_D(s, v, DTHR)
    r_entry = root_q(a, b, c_val, -1)
    if dd >= 0 and r_entry is not None and r_entry <= T:
        td_exit = theta_D(s, v, DTHR, 1)
        if td_exit is None:
            return None
        entry = max(0.0, r_entry)
        exit_t = min(T, td_exit)
        if entry > exit_t:
            return None
        return (entry, exit_t)

    return None


def vertical_wcv_interval(B, T, sz, vz, ZTHR, TCOA):
    """From vertical_WCV.pvs:
    Uses coalt_entry_exit with act_H = max(ZTHR, abs(vz)*TCOA).
    Entry uses act_H boundary, exit uses ZTHR boundary.
    """
    if abs(vz) < 1e-12:
        if abs(sz) <= ZTHR:
            return (B, T)
        return None

    act_H = max(ZTHR, abs(vz) * TCOA)

    t_a = (act_H - sz) / vz
    t_b = (-act_H - sz) / vz
    centry = min(t_a, t_b)

    t_c = (ZTHR - sz) / vz
    t_d = (-ZTHR - sz) / vz
    cexit = max(t_c, t_d)

    if T < centry or cexit < B:
        return None

    entry = max(B, centry)
    exit_t = min(T, cexit)
    if entry > exit_t:
        return None
    return (entry, exit_t)


def wcv_3d_interval(s, v, sz, vz, DTHR, ZTHR, TTHR, TCOA, T_s):
    """From WCV.pvs - WCV_interval: intersect vertical with horizontal.
    s,v in nmi/kn (time=hours). sz in ft, vz in ft/s. T_s in seconds.
    """
    vert = vertical_wcv_interval(0, T_s, sz, vz, ZTHR, TCOA)
    if vert is None:
        return None

    v_entry_s, v_exit_s = vert

    if abs(v_exit_s - v_entry_s) < 1e-12:
        t_hr = v_entry_s / 3600.0
        s_t = [s[i] + t_hr * v[i] for i in range(len(s))]
        if horizontal_wcv_check(s_t, v, DTHR, TTHR / 3600.0):
            return (v_entry_s, v_entry_s)
        return None

    T_horiz_hr = (v_exit_s - v_entry_s) / 3600.0
    t_offset_hr = v_entry_s / 3600.0
    s_shifted = [s[i] + t_offset_hr * v[i] for i in range(len(s))]

    horiz = horizontal_wcv_taumod_interval(T_horiz_hr, s_shifted, v, TTHR / 3600.0, DTHR)
    if horiz is None:
        return None

    h_entry_hr, h_exit_hr = horiz
    entry_s = h_entry_hr * 3600.0 + v_entry_s
    exit_s = h_exit_hr * 3600.0 + v_entry_s
    return (entry_s, exit_s)


def compute_alert_level(s, v, sz_ft, vz_fpm, alerts):
    vz_fps = vz_fpm / 60.0
    highest = 0
    for alert in alerts:
        level = alert["level"]
        atime = alert["alerting_time_s"]
        interval = wcv_3d_interval(
            s, v, sz_ft, vz_fps,
            alert["DTHR_nmi"], alert["ZTHR_ft"],
            alert["TTHR_s"], alert["TCOA_s"], atime
        )
        if interval is not None:
            entry, _ = interval
            if entry <= atime:
                highest = max(highest, level)
    return highest


def process_encounter(enc, config):
    s = [enc["sx_nmi"], enc["sy_nmi"]]
    v = [enc["vx_kn"], enc["vy_kn"]]
    sz_ft = enc["sz_ft"]
    vz_fpm = enc["vz_fpm"]
    vz_fps = vz_fpm / 60.0

    corr = config["corrective"]
    DTHR = corr["DTHR_nmi"]
    ZTHR = corr["ZTHR_ft"]
    TTHR = corr["TTHR_s"]
    TCOA = corr["TCOA_s"]
    lookahead = config["lookahead_s"]

    sv = dot(s, v)
    if sv < 0:
        tau_mod_s = (sq(DTHR) - sqv(s)) / sv * 3600.0
    else:
        tau_mod_s = -1.0

    h_wcv = horizontal_wcv_check(s, v, DTHR, TTHR / 3600.0)
    v_wcv = vertical_wcv_check(sz_ft, vz_fps, ZTHR, TCOA)
    w3d = h_wcv and v_wcv

    interval = wcv_3d_interval(s, v, sz_ft, vz_fps, DTHR, ZTHR, TTHR, TCOA, lookahead)
    if interval is not None:
        entry_s, exit_s = interval
    else:
        entry_s = -1.0
        exit_s = -1.0

    alert = compute_alert_level(s, v, sz_ft, vz_fpm, config["alerts"])

    return {
        "id": enc["id"],
        "tau_mod_s": round(tau_mod_s, 4),
        "horizontal_wcv": h_wcv,
        "vertical_wcv": v_wcv,
        "wcv_3d": w3d,
        "time_to_wcv_entry_s": round(entry_s, 4),
        "time_to_wcv_exit_s": round(exit_s, 4),
        "alert_level": alert
    }


def main():
    with open("/app/encounters.json") as f:
        encounters_data = json.load(f)
    with open("/app/config.json") as f:
        config = json.load(f)

    results = []
    for enc in encounters_data["encounters"]:
        result = process_encounter(enc, config)
        results.append(result)

    with open("/app/results.json", "w") as f:
        json.dump({"results": results}, f, indent=2)

    for r in results:
        print(f"{r['id']:20s}: alert={r['alert_level']}, tau_mod={r['tau_mod_s']:10.4f}s, "
              f"h_wcv={str(r['horizontal_wcv']):5s}, v_wcv={str(r['vertical_wcv']):5s}, "
              f"3d={str(r['wcv_3d']):5s}, entry={r['time_to_wcv_entry_s']:10.4f}s, "
              f"exit={r['time_to_wcv_exit_s']:10.4f}s")


if __name__ == "__main__":
    main()
