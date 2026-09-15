#!/usr/bin/env python3
"""Generate scenario files and configuration files for WCV_taumod task."""
import os
import math

def generate_scenario(ownship, intruders, max_t):
    """Generate .daa scenario content in relative coordinate format."""
    lines = [
        "NAME sx sy sz trk gs vs time",
        "[none] [nmi] [nmi] [ft] [deg] [knot] [fpm] [s]"
    ]
    for t in range(max_t + 1):
        vx_o = ownship['gs'] * math.sin(math.radians(ownship['trk'])) / 3600.0
        vy_o = ownship['gs'] * math.cos(math.radians(ownship['trk'])) / 3600.0
        vz_o = ownship['vs'] / 60.0
        sx_o = ownship['sx'] + vx_o * t
        sy_o = ownship['sy'] + vy_o * t
        sz_o = ownship['sz'] + vz_o * t
        lines.append(
            f"Ownship, {sx_o:.6f}, {sy_o:.6f}, {sz_o:.1f}, "
            f"{ownship['trk']:.1f}, {ownship['gs']:.1f}, {ownship['vs']:.1f}, {float(t):.1f}"
        )
        for intr in intruders:
            vx_i = intr['gs'] * math.sin(math.radians(intr['trk'])) / 3600.0
            vy_i = intr['gs'] * math.cos(math.radians(intr['trk'])) / 3600.0
            vz_i = intr['vs'] / 60.0
            sx_i = intr['sx'] + vx_i * t
            sy_i = intr['sy'] + vy_i * t
            sz_i = intr['sz'] + vz_i * t
            lines.append(
                f"{intr['name']}, {sx_i:.6f}, {sy_i:.6f}, {sz_i:.1f}, "
                f"{intr['trk']:.1f}, {intr['gs']:.1f}, {intr['vs']:.1f}, {float(t):.1f}"
            )
    return '\n'.join(lines) + '\n'

def main():
    os.makedirs('/app/scenarios', exist_ok=True)
    os.makedirs('/app/configs', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    # ---- Scenario 1: Head-on, same altitude ----
    head_on = generate_scenario(
        ownship={'sx': 0.0, 'sy': 0.0, 'sz': 15000.0, 'trk': 0.0, 'gs': 150.0, 'vs': 0.0},
        intruders=[{'name': 'Intruder', 'sx': 0.0, 'sy': 5.0, 'sz': 15000.0,
                    'trk': 180.0, 'gs': 150.0, 'vs': 0.0}],
        max_t=120
    )
    with open('/app/scenarios/head_on.daa', 'w') as f:
        f.write(head_on)

    # ---- Scenario 2: Crossing with vertical offset ----
    crossing = generate_scenario(
        ownship={'sx': 0.0, 'sy': 0.0, 'sz': 10000.0, 'trk': 0.0, 'gs': 120.0, 'vs': 0.0},
        intruders=[{'name': 'Intruder', 'sx': 2.0, 'sy': 2.0, 'sz': 10550.0,
                    'trk': 270.0, 'gs': 180.0, 'vs': -300.0}],
        max_t=100
    )
    with open('/app/scenarios/crossing.daa', 'w') as f:
        f.write(crossing)

    # ---- Scenario 3: Overtake with lateral offset ----
    overtake = generate_scenario(
        ownship={'sx': 0.0, 'sy': 0.0, 'sz': 20000.0, 'trk': 0.0, 'gs': 250.0, 'vs': 0.0},
        intruders=[{'name': 'Intruder', 'sx': 0.3, 'sy': 2.0, 'sz': 20000.0,
                    'trk': 0.0, 'gs': 150.0, 'vs': 0.0}],
        max_t=120
    )
    with open('/app/scenarios/overtake.daa', 'w') as f:
        f.write(overtake)

    # ---- Scenario 4: Diverging, no conflict ----
    diverging = generate_scenario(
        ownship={'sx': 0.0, 'sy': 0.0, 'sz': 15000.0, 'trk': 180.0, 'gs': 150.0, 'vs': 0.0},
        intruders=[{'name': 'Intruder', 'sx': 0.0, 'sy': -3.0, 'sz': 15000.0,
                    'trk': 180.0, 'gs': 200.0, 'vs': 0.0}],
        max_t=60
    )
    with open('/app/scenarios/diverging.daa', 'w') as f:
        f.write(diverging)

    # ---- Configuration 1: Standard DWC (DO-365 Phase I thresholds) ----
    config1 = """\
# Standard DWC Configuration (based on DO-365A Phase I corrective thresholds)
# WCV_TAUMOD detection parameters
WCV_DTHR = 0.66 [nmi]
WCV_ZTHR = 450.0 [ft]
WCV_TTHR = 35.0 [s]
WCV_TCOA = 0.0 [s]
lookahead_time = 180.0 [s]
"""
    with open('/app/configs/standard_dwc.conf', 'w') as f:
        f.write(config1)

    # ---- Configuration 2: Buffered DWC ----
    config2 = """\
# Buffered DWC Configuration (wider thresholds for increased safety margin)
# WCV_TAUMOD detection parameters
WCV_DTHR = 1.0 [nmi]
WCV_ZTHR = 750.0 [ft]
WCV_TTHR = 35.0 [s]
WCV_TCOA = 20.0 [s]
lookahead_time = 180.0 [s]
"""
    with open('/app/configs/buffered_dwc.conf', 'w') as f:
        f.write(config2)

    print("Data generation complete.")
    print(f"  Scenarios: {os.listdir('/app/scenarios/')}")
    print(f"  Configs:   {os.listdir('/app/configs/')}")

if __name__ == '__main__':
    main()
