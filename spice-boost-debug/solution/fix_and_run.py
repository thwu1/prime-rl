#!/usr/bin/env python3
"""
Fix the broken PSPICE-format boost converter netlist for ngspice,
run the simulation, and extract measurement results.

"""

import re
import subprocess
import os
import sys


def fix_netlist(filepath='/app/boost.cir'):
    """Apply all PSPICE-to-ngspice fixes to the broken netlist."""
    with open(filepath, 'r') as f:
        content = f.read()

    # ----------------------------------------------------------------
    # Fix 1: MOSFET model — PSPICE NMOS LEVEL=7 -> ngspice VDMOS
    #
    # LEVEL=7 is not a valid MOSFET level in ngspice. Power MOSFETs
    # in ngspice use the VDMOS model type. Parameters like Rds must
    # be split into Rd (drain resistance) and Rs (source resistance).
    # ----------------------------------------------------------------
    content = re.sub(
        r'\.model\s+NMOS_SW\s+NMOS\s*\(LEVEL=7[^)]*\)',
        '.model NMOS_SW VDMOS(Vto=2.0 Kp=40 Rd=0.04 Rs=0.01'
        ' Cgdmax=800p Cgdmin=100p Cgs=1000p Cjo=200p Is=1e-10 Rb=0.01)',
        content,
        flags=re.IGNORECASE | re.DOTALL
    )

    # ----------------------------------------------------------------
    # Fix 2: MOSFET instance — fix pin order and node count
    #
    # Standard MOSFET: M1 drain gate source body MODEL W= L=
    # VDMOS:           M1 drain gate source MODEL
    #
    # The broken netlist has: M1 gate sw2 0 0 NMOS_SW W=10m L=0.5u
    #   - drain and gate are SWAPPED (gate where drain should be)
    #   - has 4 nodes (body node) but VDMOS uses 3 nodes
    #   - has W/L parameters not needed for VDMOS
    #
    # Correct: M1 sw2 gate 0 NMOS_SW
    #   (drain=sw2, gate=gate, source=0)
    # ----------------------------------------------------------------
    content = re.sub(
        r'M1\s+gate\s+sw2\s+0\s+0\s+NMOS_SW[^\n]*',
        'M1 sw2 gate 0 NMOS_SW',
        content
    )

    # ----------------------------------------------------------------
    # Fix 3: Behavioral source — PSPICE VALUE={} -> ngspice B-source
    #
    # PSPICE: ESENSE sense 0 VALUE={V(out)*0.275}
    # ngspice: BSENSE sense 0 V=V(out)*0.275
    #
    # Also add a high-value pulldown on the sense node to prevent
    # a floating-node warning.
    # ----------------------------------------------------------------
    content = content.replace(
        'ESENSE sense 0 VALUE={V(out)*0.275}',
        'BSENSE sense 0 V=V(out)*0.275\nRSENSE sense 0 1G'
    )

    # ----------------------------------------------------------------
    # Fix 4: Add convergence options for switching simulation
    #
    # Switching power supplies create stiff ODEs that require:
    #   method=gear  — Gear integration (better for stiff systems)
    #   chgtol       — charge tolerance relaxation
    #   reltol       — relative tolerance relaxation
    #   rshunt       — shunt resistance on every node (helps convergence)
    #   cshunt       — shunt capacitance on every node
    #   trtol        — transient error tolerance factor
    #
    # Without these, ngspice fails with "timestep too small".
    # (See ngspice manual chapter 15.1)
    # ----------------------------------------------------------------
    options_line = (
        '.options method=gear chgtol=1e-11 reltol=0.003'
        ' rshunt=1G cshunt=1p trtol=1\n\n'
    )
    content = content.replace(
        '***** Transient Simulation *****',
        '***** Convergence Options *****\n'
        + options_line
        + '***** Transient Simulation *****'
    )

    with open(filepath, 'w') as f:
        f.write(content)

    print("All netlist fixes applied.")


def run_simulation(filepath='/app/boost.cir'):
    """Run ngspice in batch mode and return combined stdout+stderr."""
    print("Running ngspice simulation...")
    result = subprocess.run(
        ['ngspice', '-b', filepath],
        capture_output=True, text=True, timeout=300
    )
    output = result.stdout + '\n' + result.stderr
    print(output[-2000:])  # Print last 2000 chars for debugging
    if result.returncode != 0:
        print(f"WARNING: ngspice exited with code {result.returncode}")
    return output


def extract_results(output):
    """Parse ngspice meas output and write result files."""
    os.makedirs('/app/results', exist_ok=True)

    # Parse all measurement values from ngspice output.
    # Format: "vout_avg              =  1.18700e+01"
    measurements = {}
    for match in re.finditer(r'(\w+)\s*=\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)', output):
        name = match.group(1).lower()
        try:
            value = float(match.group(2))
            measurements[name] = value
        except ValueError:
            pass

    print(f"Parsed measurements: {measurements}")

    # --- Output voltage ---
    vout_avg = measurements.get('vout_avg')
    if vout_avg is None:
        print("ERROR: vout_avg not found in simulation output")
        sys.exit(1)

    with open('/app/results/output_voltage.txt', 'w') as f:
        f.write(f'{vout_avg:.4f}\n')

    # --- Output ripple ---
    vout_max = measurements.get('vout_max')
    vout_min = measurements.get('vout_min')
    if vout_max is None or vout_min is None:
        print("ERROR: vout_max or vout_min not found")
        sys.exit(1)

    ripple_mv = (vout_max - vout_min) * 1000.0
    with open('/app/results/ripple_mv.txt', 'w') as f:
        f.write(f'{ripple_mv:.4f}\n')

    # --- Efficiency ---
    iin_avg = measurements.get('iin_avg')
    if iin_avg is None:
        print("ERROR: iin_avg not found")
        sys.exit(1)

    # In ngspice, current through a voltage source follows passive sign
    # convention: positive current flows from + to - INSIDE the source.
    # For a source supplying current to the circuit, i(VIN) is negative.
    # Pin = Vin * |Iin| = -Vin * iin_avg  (since iin_avg < 0)
    pin = -5.0 * iin_avg
    pout = vout_avg * vout_avg / 120.0

    if pin > 0:
        efficiency_pct = 100.0 * pout / pin
    else:
        print("ERROR: Computed input power is non-positive")
        sys.exit(1)

    with open('/app/results/efficiency_pct.txt', 'w') as f:
        f.write(f'{efficiency_pct:.4f}\n')

    print(f"\nResults:")
    print(f"  Output voltage: {vout_avg:.4f} V")
    print(f"  Ripple:         {ripple_mv:.4f} mV")
    print(f"  Efficiency:     {efficiency_pct:.4f} %")


if __name__ == '__main__':
    fix_netlist()
    output = run_simulation()
    extract_results(output)
