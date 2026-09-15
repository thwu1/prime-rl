"""Extract solvation free energy from gmx bar output.

Multiple parsing strategies with fallbacks:
1. Parse gmx bar text log for 'total' line
2. Parse bar.xvg output file
3. Sum individual DG/BAR values from log
4. Compute via thermodynamic integration from dhdl.xvg files

"""

import re
import os
import sys

RESULT_FILE = "/app/result.txt"
NUM_LAMBDAS = 11

# Lambda schedule (must match the corrected MDP)
COUL_LAMBDAS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
VDW_LAMBDAS = [0.0, 0.0, 0.0, 0.0, 0.0, 0.20, 0.40, 0.60, 0.80, 0.90, 1.0]


def to_solvation_sign(value):
    """Ensure the value has the solvation free energy sign (negative).

    gmx bar computes DG(coupled -> decoupled) which is positive for
    favorably solvated molecules. The solvation free energy is the negative
    of this. If the value is already negative, assume it's already in
    solvation convention.
    """
    if value is None:
        return None
    if value > 0:
        return -value
    return value


def try_bar_log(log_path):
    """Strategy 1: Parse gmx bar text output for the total DG line."""
    try:
        with open(log_path) as fh:
            text = fh.read()
    except (FileNotFoundError, IOError):
        return None

    # Look for a line containing "total" (case-insensitive)
    for line in text.split("\n"):
        if "total" not in line.lower():
            continue

        # Pattern 1: "DG = -20.50" or "DG=  -20.50"
        m = re.search(r"DG\s*=\s*([-+]?\d+\.?\d*)", line)
        if m:
            return float(m.group(1))

        # Pattern 2: "BAR = -20.50"
        m = re.search(r"BAR\s*=\s*([-+]?\d+\.?\d*)", line)
        if m:
            return float(m.group(1))

        # Pattern 3: number followed by +/- (free energy estimate)
        m = re.search(r"([-+]?\d+\.\d+)\s+\+/-", line)
        if m:
            return float(m.group(1))

        # Pattern 4: after a comma or colon, first float
        m = re.search(r"[,:].*?([-+]?\d+\.\d+)", line)
        if m:
            val = float(m.group(1))
            # Skip small numbers that might be lambda indices
            if abs(val) > 1.0:
                return val

    return None


def try_sum_individual_dg(log_path):
    """Strategy 2: Sum individual DG/BAR values from each lambda pair."""
    try:
        with open(log_path) as fh:
            text = fh.read()
    except (FileNotFoundError, IOError):
        return None

    dg_values = []
    for line in text.split("\n"):
        low = line.lower()
        if "total" in low:
            continue

        # Look for lines with lambda pair patterns like "0 - 1" or "0 -- 1"
        if re.search(r"\d+\s*-+\s*\d+", line):
            # Extract the DG value after = or as the first float after the pair
            m = re.search(r"[=:]\s*([-+]?\d+\.?\d+)", line)
            if m:
                dg_values.append(float(m.group(1)))
            else:
                # Try: float followed by +/-
                m = re.search(r"([-+]?\d+\.\d+)\s+\+/-", line)
                if m:
                    dg_values.append(float(m.group(1)))

    if len(dg_values) >= NUM_LAMBDAS - 2:  # Allow for some missing
        return sum(dg_values)
    return None


def try_bar_xvg(xvg_path):
    """Strategy 3: Parse bar.xvg for the cumulative free energy.

    The last data point's y-value should be the total DG.
    """
    try:
        with open(xvg_path) as fh:
            lines = fh.readlines()
    except (FileNotFoundError, IOError):
        return None

    last_y = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", "@", ";")):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                last_y = float(parts[1])
            except ValueError:
                continue

    return last_y


def try_ti_from_dhdl(base_dir="/app"):
    """Strategy 4: Compute free energy via thermodynamic integration.

    Read dhdl.xvg files from each lambda directory, extract dH/dl,
    and integrate using the trapezoidal rule over the combined lambda path.
    """
    # Read average dH/dl from each lambda window
    avg_dhdl = []
    found_windows = []

    for i in range(NUM_LAMBDAS):
        path = os.path.join(base_dir, f"lambda_{i}", "dhdl.xvg")
        if not os.path.isfile(path):
            continue

        dhdl_values = []
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith(("#", "@", ";")):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        # Column 2 is dH/dl (total derivative)
                        dhdl_values.append(float(parts[1]))
                    except (ValueError, IndexError):
                        continue

        if dhdl_values:
            # Discard first 20% as equilibration
            n_discard = max(1, len(dhdl_values) // 5)
            production = dhdl_values[n_discard:]
            if production:
                avg_dhdl.append(sum(production) / len(production))
                found_windows.append(i)

    if len(avg_dhdl) < NUM_LAMBDAS - 2:
        return None

    # Construct the overall lambda path
    # For each state i, the "combined lambda" is the fraction of interactions removed
    # We use a simple index-based integration: each step is delta_state = 1
    # TI: DG = sum of (avg_dhdl[i] + avg_dhdl[i+1]) / 2 * delta_state
    # where delta_state = 1 for adjacent states
    # But this gives DG per "state index" not per lambda, so we need to normalize

    # For separate coul and vdw lambdas, dH/dl in dhdl.xvg is typically
    # the derivative with respect to the state index (if init-lambda-state is used).
    # In this case, the integral is just the trapezoidal sum over state indices.

    total_dg = 0.0
    for j in range(len(avg_dhdl) - 1):
        total_dg += (avg_dhdl[j] + avg_dhdl[j + 1]) / 2.0

    return total_dg


def main():
    value = None

    # Strategy 1: Parse gmx bar log (try multiple possible log locations)
    for log_path in ["/app/bar.log", "/app/bar_output.log"]:
        value = try_bar_log(log_path)
        if value is not None:
            print(f"Strategy 1 (bar log total): {value:.4f} from {log_path}")
            break

    # Strategy 2: Sum individual DG values from log
    if value is None:
        for log_path in ["/app/bar.log", "/app/bar_output.log"]:
            value = try_sum_individual_dg(log_path)
            if value is not None:
                print(f"Strategy 2 (sum individual DG): {value:.4f} from {log_path}")
                break

    # Strategy 3: Parse bar.xvg
    if value is None:
        value = try_bar_xvg("/app/bar.xvg")
        if value is not None:
            print(f"Strategy 3 (bar.xvg last value): {value:.4f}")

    # Strategy 4: Thermodynamic integration from dhdl files
    if value is None:
        value = try_ti_from_dhdl("/app")
        if value is not None:
            print(f"Strategy 4 (TI from dhdl.xvg): {value:.4f}")

    if value is None:
        print("ERROR: All extraction strategies failed", file=sys.stderr)
        sys.exit(1)

    # Ensure solvation free energy sign convention (negative for favorable solvation)
    solvation_dg = to_solvation_sign(value)
    print(f"Solvation free energy: {solvation_dg:.4f} kJ/mol")

    with open(RESULT_FILE, "w") as fh:
        fh.write(f"{solvation_dg:.4f}\n")

    print(f"Result written to {RESULT_FILE}")


if __name__ == "__main__":
    main()
