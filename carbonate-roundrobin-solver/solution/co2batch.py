#!/usr/bin/env python3
"""CLI tool for batch carbonate system calculations.

Reads CSV from stdin, writes CSV to stdout with computed results.
"""

import sys
import csv
import importlib.util

# Import carbonate solver from /app
spec = importlib.util.spec_from_file_location("carbonate", "/app/carbonate.py")
carbonate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(carbonate)

DEFAULTS = {
    "temperature": 25.0,
    "salinity": 35.0,
    "pressure": 0.0,
    "total_silicate": 0.0,
    "total_phosphate": 0.0,
}

OUTPUT_KEYS = ["TA", "DIC", "pH", "pCO2", "fCO2", "CO3", "HCO3", "CO2aq"]


def main():
    reader = csv.DictReader(sys.stdin)
    input_fieldnames = list(reader.fieldnames) if reader.fieldnames else []
    output_fieldnames = input_fieldnames + [k for k in OUTPUT_KEYS if k not in input_fieldnames]

    writer = csv.DictWriter(sys.stdout, fieldnames=output_fieldnames)
    writer.writeheader()

    for row in reader:
        par1 = float(row["par1"])
        par2 = float(row["par2"])
        par1_type = int(row["par1_type"])
        par2_type = int(row["par2_type"])

        kwargs = {}
        for key, default in DEFAULTS.items():
            if key in row and row[key] != "":
                kwargs[key] = float(row[key])
            else:
                kwargs[key] = default

        result = carbonate.solve(par1, par2, par1_type, par2_type, **kwargs)

        out_row = dict(row)
        for key in OUTPUT_KEYS:
            out_row[key] = result[key]

        writer.writerow(out_row)

    sys.exit(0)


if __name__ == "__main__":
    main()
