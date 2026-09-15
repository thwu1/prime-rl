#!/usr/bin/env python3
"""
Fix broken PSPICE boost converter netlists for ngspice, optimize
synchronous converter dead-time, evaluate both topologies across
multiple load conditions, analyze crossover behavior, and produce
an engineering design recommendation.

"""

import re
import subprocess
import os
import csv
import sys


def fix_pspice(filepath):
    """Apply all PSPICE-to-ngspice compatibility fixes to a netlist."""
    with open(filepath) as f:
        content = f.read()

    # Fix 1: MOSFET model -- PSPICE NMOS LEVEL=7 -> ngspice VDMOS
    content = re.sub(
        r'\.model\s+NMOS_SW\s+NMOS\s*\(LEVEL=7[^)]*\)',
        '.model NMOS_SW VDMOS(Vto=2.0 Kp=40 Rd=0.04 Rs=0.01'
        ' Cgdmax=800p Cgdmin=100p Cgs=1000p Cjo=200p Is=1e-10 Rb=0.01)',
        content,
        flags=re.IGNORECASE | re.DOTALL
    )

    # Fix 2: MOSFET instance pin order
    # PSPICE: M1 gate sw2 0 0 NMOS_SW W=10m L=0.5u (drain/gate swapped + body)
    # ngspice VDMOS: M1 drain gate source MODEL
    content = re.sub(
        r'M1\s+(gate\d*)\s+sw2\s+0\s+0\s+NMOS_SW[^\n]*',
        r'M1 sw2 \1 0 NMOS_SW',
        content
    )
    content = re.sub(
        r'M2\s+(gate\d*)\s+out\s+sw2\s+0\s+NMOS_SW[^\n]*',
        r'M2 out \1 sw2 NMOS_SW',
        content
    )

    # Fix 3: Behavioral source
    # PSPICE: ESENSE sense 0 VALUE={V(out)*0.275}
    # ngspice: BSENSE sense 0 V=V(out)*0.275  + pulldown resistor
    content = content.replace(
        'ESENSE sense 0 VALUE={V(out)*0.275}',
        'BSENSE sense 0 V=V(out)*0.275\nRSENSE sense 0 1G'
    )

    # Fix 4: Add convergence options for switching simulation
    if '.options' not in content.lower():
        content = content.replace(
            '.tran',
            '.options method=gear chgtol=1e-11 reltol=0.003'
            ' rshunt=1G cshunt=1p trtol=1\n\n.tran'
        )

    with open(filepath, 'w') as f:
        f.write(content)


def set_dead_time_ns(filepath, dt_ns):
    """Set the dead_time parameter in a netlist to dt_ns nanoseconds."""
    with open(filepath) as f:
        content = f.read()
    content = re.sub(
        r'\.param\s+dead_time\s*=\s*\S+',
        f'.param dead_time={dt_ns}n',
        content
    )
    with open(filepath, 'w') as f:
        f.write(content)


def set_load_resistance(filepath, resistance):
    """Set RLOAD value in a netlist."""
    with open(filepath) as f:
        content = f.read()
    content = re.sub(
        r'RLOAD\s+out\s+0\s+\S+',
        f'RLOAD out 0 {resistance}',
        content
    )
    with open(filepath, 'w') as f:
        f.write(content)


def run_sim(filepath, timeout=300):
    """Run ngspice in batch mode and return combined stdout+stderr."""
    result = subprocess.run(
        ['ngspice', '-b', filepath],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout + '\n' + result.stderr


def parse_measurements(output):
    """Parse all named measurements from ngspice output."""
    meas = {}
    for m in re.finditer(
        r'(\w+)\s*=\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)', output
    ):
        try:
            meas[m.group(1).lower()] = float(m.group(2))
        except ValueError:
            pass
    return meas


def compute_efficiency(meas, rload):
    """Compute power conversion efficiency from ngspice measurements."""
    vout = abs(meas.get('vout_avg', 0))
    iin = meas.get('iin_avg', 0)
    # Passive sign convention: current out of VIN positive terminal
    # is reported negative by ngspice
    pin = -5.0 * iin
    pout = vout * vout / rload
    eff = 100.0 * pout / pin if pin > 0 else 0.0
    return eff


def main():
    os.makedirs('/app/results', exist_ok=True)

    # ==================================================================
    # Phase 1: Fix both PSPICE netlists for ngspice
    # ==================================================================
    print("=== Phase 1: Fix PSPICE netlists ===")
    fix_pspice('/app/async_boost.cir')
    fix_pspice('/app/sync_boost.cir')
    print("Both netlists fixed for ngspice compatibility")

    # ==================================================================
    # Phase 2: Dead-time optimization sweep at 60 ohm
    # ==================================================================
    print("\n=== Phase 2: Dead-time sweep at 60 ohm ===")
    dead_times_ns = [10, 20, 40, 60, 100, 160]
    sweep_results = []

    for dt in dead_times_ns:
        set_dead_time_ns('/app/sync_boost.cir', dt)
        try:
            output = run_sim('/app/sync_boost.cir', timeout=120)
            meas = parse_measurements(output)
            eff = compute_efficiency(meas, 60.0)
        except Exception as e:
            print(f"  dt={dt} ns: FAILED ({e})")
            eff = 0.0
        sweep_results.append((dt, eff))
        print(f"  dt={dt} ns: efficiency = {eff:.2f}%")

    # Write sweep CSV
    with open('/app/results/deadtime_sweep.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['dead_time_ns', 'efficiency_pct'])
        for dt, eff in sweep_results:
            writer.writerow([dt, f'{eff:.4f}'])

    # ==================================================================
    # Phase 3: Select optimal dead-time
    # ==================================================================
    valid = [(dt, eff) for dt, eff in sweep_results if eff > 0]
    if not valid:
        print("ERROR: All sync simulations failed")
        sys.exit(1)

    optimal_dt, optimal_eff = max(valid, key=lambda x: x[1])
    print(f"\nOptimal dead-time: {optimal_dt} ns "
          f"(efficiency = {optimal_eff:.2f}%)")

    with open('/app/results/optimal_deadtime_ns.txt', 'w') as f:
        f.write(f'{optimal_dt}\n')

    # Set sync converter to optimal dead-time for remaining evaluation
    set_dead_time_ns('/app/sync_boost.cir', optimal_dt)

    # ==================================================================
    # Phase 4: Multi-load topology evaluation
    # ==================================================================
    print("\n=== Phase 4: Multi-load topology evaluation ===")
    load_resistances = [30, 60, 120, 240, 600]
    load_data = []  # list of (rload, async_eff, sync_eff)

    for rload in load_resistances:
        print(f"\n  --- Load = {rload} ohm ---")

        # Async topology
        set_load_resistance('/app/async_boost.cir', rload)
        output = run_sim('/app/async_boost.cir', timeout=120)
        meas = parse_measurements(output)
        async_eff = compute_efficiency(meas, rload)
        print(f"    Async efficiency: {async_eff:.2f}%")

        # Sync topology
        set_load_resistance('/app/sync_boost.cir', rload)
        output = run_sim('/app/sync_boost.cir', timeout=120)
        meas = parse_measurements(output)
        sync_eff = compute_efficiency(meas, rload)
        print(f"    Sync efficiency:  {sync_eff:.2f}%")

        load_data.append((rload, async_eff, sync_eff))

    # Write efficiency map
    with open('/app/results/efficiency_map.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['load_ohms', 'async_eff_pct', 'sync_eff_pct'])
        for rload, ae, se in load_data:
            writer.writerow([rload, f'{ae:.4f}', f'{se:.4f}'])

    # ==================================================================
    # Phase 5: Restore netlists to 60 ohm nominal operating point
    # ==================================================================
    set_load_resistance('/app/async_boost.cir', 60)
    set_load_resistance('/app/sync_boost.cir', 60)

    # ==================================================================
    # Phase 6: Crossover analysis and design recommendation
    # ==================================================================
    print("\n=== Phase 6: Crossover analysis ===")

    # Check for efficiency crossover across load range
    crossover_r = None
    for i in range(len(load_data) - 1):
        r1, a1, s1 = load_data[i]
        r2, a2, s2 = load_data[i + 1]
        diff1 = s1 - a1  # positive = sync better
        diff2 = s2 - a2
        if diff1 * diff2 < 0:
            # Sign change: interpolate crossover
            t = diff1 / (diff1 - diff2)
            crossover_r = r1 + t * (r2 - r1)
            break

    # Determine which topology wins at extremes
    heavy_r, heavy_ae, heavy_se = load_data[0]   # 30 ohm
    light_r, light_ae, light_se = load_data[-1]   # 600 ohm

    # Count wins across load range
    async_wins = sum(1 for _, ae, se in load_data if ae > se + 0.5)
    sync_wins = sum(1 for _, ae, se in load_data if se > ae + 0.5)

    if crossover_r is not None:
        recommendation = 'load-dependent'
        crossover_str = f'{crossover_r:.1f}'
    elif sync_wins > async_wins:
        recommendation = 'sync'
        crossover_str = 'N/A'
    elif async_wins > sync_wins:
        recommendation = 'async'
        crossover_str = 'N/A'
    else:
        avg_async = sum(ae for _, ae, _ in load_data) / len(load_data)
        avg_sync = sum(se for _, _, se in load_data) / len(load_data)
        recommendation = 'sync' if avg_sync >= avg_async else 'async'
        crossover_str = 'N/A'

    # Build light-load loss mechanism sentence
    if light_se > light_ae + 0.5:
        light_mech = (
            f"At light load ({light_r} ohm), synchronous rectification "
            f"achieves {light_se:.1f}% vs {light_ae:.1f}% for async "
            f"because the Schottky diode forward voltage remains the "
            f"dominant rectification loss even at low currents, outweighing "
            f"the sync MOSFET's gate-drive overhead."
        )
    elif light_ae > light_se + 0.5:
        light_mech = (
            f"At light load ({light_r} ohm), asynchronous rectification "
            f"achieves {light_ae:.1f}% vs {light_se:.1f}% for sync "
            f"because the synchronous MOSFET's fixed gate-drive switching "
            f"losses and body-diode reverse-recovery losses become a larger "
            f"fraction of the diminished total power throughput."
        )
    else:
        light_mech = (
            f"At light load ({light_r} ohm), both topologies achieve "
            f"similar efficiency (async {light_ae:.1f}%, sync {light_se:.1f}%) "
            f"as the reduced current makes the rectifier voltage drop less "
            f"significant relative to fixed switching losses."
        )

    # Build heavy-load loss mechanism sentence
    if heavy_se > heavy_ae + 0.5:
        heavy_mech = (
            f"At heavy load ({heavy_r} ohm), synchronous rectification "
            f"achieves {heavy_se:.1f}% vs {heavy_ae:.1f}% for async "
            f"because the MOSFET channel Rds_on (~50 mohm) produces a "
            f"much lower voltage drop than the Schottky diode forward "
            f"voltage (~0.3V) during the high-current rectification interval."
        )
    elif heavy_ae > heavy_se + 0.5:
        heavy_mech = (
            f"At heavy load ({heavy_r} ohm), asynchronous rectification "
            f"achieves {heavy_ae:.1f}% vs {heavy_se:.1f}% for sync "
            f"because body-diode conduction during dead-time intervals "
            f"offsets the channel resistance advantage at high currents."
        )
    else:
        heavy_mech = (
            f"At heavy load ({heavy_r} ohm), both topologies achieve "
            f"similar efficiency (async {heavy_ae:.1f}%, sync {heavy_se:.1f}%) "
            f"as conduction losses in both the diode and MOSFET channel "
            f"are comparable at this current level."
        )

    # Build quantitative recommendation
    eff_parts = []
    for rload, ae, se in load_data:
        eff_parts.append(f"{rload} ohm: async={ae:.1f}%, sync={se:.1f}%")
    eff_summary = "; ".join(eff_parts)

    if recommendation == 'load-dependent':
        final_rec = (
            f"The optimal topology is load-dependent with a crossover near "
            f"{crossover_r:.0f} ohm. Measured efficiencies: {eff_summary}. "
            f"Use synchronous rectification for heavy loads below the "
            f"crossover where channel conduction losses are lower than "
            f"diode forward-voltage losses, and asynchronous rectification "
            f"for light loads above the crossover where fixed switching "
            f"overhead penalizes the synchronous topology."
        )
    elif recommendation == 'sync':
        final_rec = (
            f"Synchronous rectification is recommended across the full "
            f"load range. Measured efficiencies: {eff_summary}. "
            f"The MOSFET channel resistance provides consistently lower "
            f"rectification losses than the Schottky diode forward voltage "
            f"at all tested load levels, with the advantage most pronounced "
            f"at heavy loads where conduction losses dominate."
        )
    else:
        final_rec = (
            f"Asynchronous rectification is recommended across the full "
            f"load range. Measured efficiencies: {eff_summary}. "
            f"Despite the Schottky diode's higher forward voltage, the "
            f"simpler gate drive and absence of body-diode dead-time "
            f"conduction losses make it more efficient across all tested "
            f"operating points."
        )

    # Write topology report
    with open('/app/results/topology_report.txt', 'w') as f:
        f.write(f'{recommendation}\n')
        f.write(f'{crossover_str}\n')
        f.write(f'{light_mech}\n')
        f.write(f'{heavy_mech}\n')
        f.write(f'{final_rec}\n')

    print(f"\nRecommendation: {recommendation}")
    if crossover_r is not None:
        print(f"Crossover: ~{crossover_r:.1f} ohm")
    print(f"\nEfficiency map:")
    for rload, ae, se in load_data:
        winner = "sync" if se > ae else "async"
        print(f"  {rload:>4d} ohm: async={ae:.1f}%, sync={se:.1f}%"
              f" -> {winner}")
    print(f"\n{final_rec}")
    print("\nDone.")


if __name__ == '__main__':
    main()
