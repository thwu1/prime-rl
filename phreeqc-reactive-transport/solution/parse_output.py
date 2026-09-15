#!/usr/bin/env python3
"""
Parse PHREEQC SELECTED_OUTPUT and write results.json.

"""
import json
import sys


def parse_selected_output(filepath):
    """Parse a PHREEQC SELECTED_OUTPUT TSV file.

    Returns (headers, rows) where each row is a dict mapping header -> value.
    """
    with open(filepath, "r") as fh:
        lines = fh.readlines()

    # Locate header (first non-blank, non-comment line)
    header_idx = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("#"):
            header_idx = i
            break

    headers = [h.strip() for h in lines[header_idx].split("\t")]

    rows = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        values = [v.strip() for v in line.split("\t")]
        row = {}
        for h, v in zip(headers, values):
            if not h:
                continue
            try:
                row[h] = float(v)
            except (ValueError, TypeError):
                row[h] = v
        rows.append(row)

    return headers, rows


def get_cell_at_final_shift(rows, cell_num):
    """Return the row for *cell_num* at the last transport shift (step > 0)."""
    transport = []
    for r in rows:
        try:
            step = float(r.get("step", 0))
            if step > 0:
                transport.append(r)
        except (ValueError, TypeError):
            pass

    if not transport:
        raise RuntimeError(
            "No transport rows found (all step <= 0). "
            "Check that SELECTED_OUTPUT includes the 'step' column "
            "(do not use '-reset false' without explicitly adding '-step true')."
        )

    max_step = max(r["step"] for r in transport)

    for r in transport:
        if abs(r["step"] - max_step) < 0.5:
            soln = r.get("soln", -999)
            try:
                soln = float(soln)
            except (ValueError, TypeError):
                continue
            if abs(soln - cell_num) < 0.5:
                return r

    raise RuntimeError(
        f"Could not find cell {cell_num} at final shift {max_step}. "
        "Check that SELECTED_OUTPUT includes the 'soln' column."
    )


def find_col(headers, exact_name):
    """Find a header matching *exact_name* (stripped)."""
    for h in headers:
        if h.strip() == exact_name:
            return h
    return None


def main():
    filepath = "/app/transport_results.tsv"
    headers, rows = parse_selected_output(filepath)

    print(f"Parsed {len(rows)} data rows with {len(headers)} columns.")
    print(f"Headers: {headers}")

    cell10 = get_cell_at_final_shift(rows, 10)
    cell1 = get_cell_at_final_shift(rows, 1)

    # PHREEQC SELECTED_OUTPUT column naming:
    #   -totals Ca S(6) Mg Na       → columns: "Ca", "S(6)", "Mg", "Na"
    #   -equilibrium_phases Calcite  → columns: "Calcite", "d_Calcite"
    #   -saturation_indices X Y      → columns: "si_X", "si_Y"
    ca_col = find_col(headers, "Ca")
    so4_col = find_col(headers, "S(6)")
    calcite_col = find_col(headers, "Calcite")
    si_gypsum_col = find_col(headers, "si_Gypsum")

    if ca_col is None:
        print(f"ERROR: Ca column not found. Headers: {headers}", file=sys.stderr)
        sys.exit(1)
    if so4_col is None:
        print(f"ERROR: S(6) column not found. Headers: {headers}", file=sys.stderr)
        sys.exit(1)
    if calcite_col is None:
        print(f"ERROR: Calcite column not found. Headers: {headers}", file=sys.stderr)
        sys.exit(1)
    if si_gypsum_col is None:
        print(f"ERROR: si_Gypsum column not found. Headers: {headers}", file=sys.stderr)
        sys.exit(1)

    results = {
        "effluent_pH": round(float(cell10["pH"]), 4),
        "effluent_Ca_mol_kgw": round(float(cell10[ca_col]), 8),
        "effluent_SO4_mol_kgw": round(float(cell10[so4_col]), 8),
        "calcite_remaining_cell1": round(float(cell1[calcite_col]), 6),
        "gypsum_si_cell10": round(float(cell10[si_gypsum_col]), 4),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
