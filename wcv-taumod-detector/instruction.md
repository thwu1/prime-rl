Implement a WCV_taumod (Well-Clear Volume with Modified Tau) conflict detector based on NASA DAIDALUS PVS formal specifications.

## Background

The WCV_taumod algorithm detects when two aircraft violate well-clear separation standards. It combines a horizontal detection component (based on modified tau time metric and horizontal distance threshold) with a vertical detection component (based on altitude threshold and time-to-co-altitude). The algorithm is formally specified and verified in PVS (Prototype Verification System) as part of the DAIDALUS (Detect and Avoid Alerting Logic for Unmanned Systems) framework per RTCA DO-365 MOPS.

## Provided Files

- `/app/specs/` — PVS formal specifications defining the WCV_taumod algorithm:
  - `horizontal_WCV.pvs` — parametric horizontal well-clear volume
  - `horizontal_WCV_taumod.pvs` — horizontal WCV interval computation using modified tau (includes the quadratic root-finding algorithm)
  - `vertical_WCV.pvs` — vertical well-clear volume and interval computation
  - `WCV_taumod.pvs` — 3D WCV combining horizontal and vertical with time-shifting

- `/app/scenarios/` — Encounter scenario files in DAIDALUS `.daa` relative coordinate format:
  - `head_on.daa` — head-on encounter at same altitude
  - `crossing.daa` — crossing encounter with 550ft vertical offset and intruder descending
  - `overtake.daa` — overtake encounter with 0.3nmi lateral offset
  - `diverging.daa` — diverging encounter (no conflict)

- `/app/configs/` — WCV threshold configuration files:
  - `standard_dwc.conf` — DTHR=0.66nmi, ZTHR=450ft, TTHR=35s, TCOA=0s
  - `buffered_dwc.conf` — DTHR=1.0nmi, ZTHR=750ft, TTHR=35s, TCOA=20s

## Task

Write a program that, for every (scenario, config) pair, computes the WCV_taumod 3D violation interval and per-timestep violation status. The program must faithfully implement the algorithms from the PVS specifications — particularly the `horizontal_WCV_taumod_interval` quadratic root-finding procedure and the 3D `WCV_interval` time-shifting algorithm that computes the horizontal interval within the vertical violation window.

## Scenario File Format

```
NAME sx sy sz trk gs vs time
[none] [nmi] [nmi] [ft] [deg] [knot] [fpm] [s]
Ownship, <East_nmi>, <North_nmi>, <alt_ft>, <track_deg>, <groundspeed_knot>, <vertspeed_fpm>, <time_s>
Intruder, ...
```

Track is clockwise from North: 0°=N, 90°=E, 180°=S, 270°=W. Velocity components: `vx = gs * sin(trk)`, `vy = gs * cos(trk)` (in knots = nmi/hr). Vertical speed is in ft/min. Relative state: `s = pos_intruder - pos_ownship`, `v = vel_intruder - vel_ownship`.

## Output

Write `/app/output/results.json` with exactly:

```json
{
  "analyses": [
    {
      "scenario": "<filename_without_extension>",
      "config": "<filename_without_extension>",
      "has_violation": true,
      "violation_entry_time": 23.29,
      "violation_exit_time": 67.92,
      "first_violation_step": 24,
      "last_violation_step": 67,
      "tcpa": 60.0,
      "dcpa": 0.0,
      "violation_steps": [24, 25, 26, ...]
    },
    ...
  ]
}
```

Include one entry per (scenario, config) pair (8 total). Iterate scenarios in order: head_on, crossing, overtake, diverging. For each scenario, iterate configs: standard_dwc, buffered_dwc. For non-violating pairs, set `has_violation` to `false` and omit interval/step fields (or set them to `null`). Times are in seconds (floats). Steps are integer time indices from the scenario file. `tcpa` and `dcpa` are computed from the initial state (t=0). `violation_steps` lists every integer timestep where `WCV_taumod(s+t*v, v)` is true.