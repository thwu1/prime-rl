"""
Encounter processor: reads encounter and config files, runs WCV_TAUMOD
detection, and writes results.json.

"""

import json
import math
import os
import sys

sys.path.insert(0, "/app")
import wcv_taumod


def aircraft_velocity(trk_deg, gs_knot, vs_fpm):
    """Convert track/groundspeed/vertical-speed to Cartesian velocity."""
    trk_rad = math.radians(trk_deg)
    gs_nmi_s = gs_knot / 3600.0
    vx = gs_nmi_s * math.sin(trk_rad)
    vy = gs_nmi_s * math.cos(trk_rad)
    vz = vs_fpm / 60.0
    return (vx, vy, vz)


def compute_relative_state(own, intr):
    """Compute relative state vector (ownship - intruder)."""
    sx = own["sx_nmi"] - intr["sx_nmi"]
    sy = own["sy_nmi"] - intr["sy_nmi"]
    sz = own["sz_ft"] - intr["sz_ft"]
    vo = aircraft_velocity(own["trk_deg"], own["gs_knot"], own["vs_fpm"])
    vi = aircraft_velocity(intr["trk_deg"], intr["gs_knot"], intr["vs_fpm"])
    vx = vo[0] - vi[0]
    vy = vo[1] - vi[1]
    vz = vo[2] - vi[2]
    return (sx, sy, sz), (vx, vy, vz)


def load_encounters(enc_dir="/app/data/encounters"):
    encounters = []
    for fn in sorted(os.listdir(enc_dir)):
        if fn.endswith(".json"):
            with open(os.path.join(enc_dir, fn)) as f:
                encounters.append(json.load(f))
    return encounters


def load_configs(cfg_dir="/app/data/configs"):
    configs = []
    for fn in sorted(os.listdir(cfg_dir)):
        if fn.endswith(".json"):
            with open(os.path.join(cfg_dir, fn)) as f:
                configs.append(json.load(f))
    return configs


def main():
    encounters = load_encounters()
    configs = load_configs()

    results = []

    for enc in encounters:
        for cfg in configs:
            for intr in enc["intruders"]:
                s3, v3 = compute_relative_state(enc["ownship"], intr)
                T = cfg["lookahead_s"]

                conflict = wcv_taumod.wcv_taumod_detection(
                    0.0, T, s3, v3,
                    cfg["TAUMOD_s"], cfg["TCOA_s"],
                    cfg["DTHR_nmi"], cfg["ZTHR_ft"]
                )

                entry_time = None
                exit_time = None
                if conflict:
                    e, x = wcv_taumod.wcv_taumod_interval(
                        0.0, T, s3, v3,
                        cfg["TAUMOD_s"], cfg["TCOA_s"],
                        cfg["DTHR_nmi"], cfg["ZTHR_ft"]
                    )
                    entry_time = round(e, 6)
                    exit_time = round(x, 6)

                results.append({
                    "encounter": enc["name"],
                    "intruder": intr["id"],
                    "config": cfg["name"],
                    "conflict": conflict,
                    "entry_time_s": entry_time,
                    "exit_time_s": exit_time,
                })

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/results.json", "w") as f:
        json.dump({"results": results}, f, indent=2)

    print(f"Wrote {len(results)} results to /app/output/results.json")
    for r in results:
        status = f"CONFLICT [{r['entry_time_s']:.1f}s - {r['exit_time_s']:.1f}s]" if r["conflict"] else "CLEAR"
        print(f"  {r['encounter']:25s} x {r['config']:20s} -> {status}")


if __name__ == "__main__":
    main()
