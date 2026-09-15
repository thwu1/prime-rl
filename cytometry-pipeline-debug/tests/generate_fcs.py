#!/usr/bin/env python3
"""
Generate a synthetic FCS 3.0 binary file for pipeline testing.

Creates a file with known data (deterministic via fixed seed) so that
pipeline output can be verified against independently computed values.

"""

import os
import struct
import numpy as np


def generate_fcs(output_path, raw_csv_path):
    np.random.seed(42)

    n_events = 1000
    param_names = ["FSC-H", "SSC-H", "FL1-H", "FL2-H",
                   "FL3-H", "FL4-H", "Time", "FSC-A"]
    n_params = len(param_names)

    # ----- Generate realistic bimodal flow cytometry data -----
    n_dim = 700
    n_bright = 300

    # Scatter channels: positive log-normal
    fsc = np.random.lognormal(6.0, 0.5, n_events).astype(np.float32)
    ssc = np.random.lognormal(5.5, 0.8, n_events).astype(np.float32)

    # Fluorescence: bimodal (dim negative/low + bright positive)
    indices = np.random.permutation(n_events)

    fl1 = np.empty(n_events, dtype=np.float32)
    fl1[indices[:n_dim]] = np.random.normal(50, 30, n_dim).astype(np.float32)
    fl1[indices[n_dim:]] = np.random.normal(10000, 3000, n_bright).astype(np.float32)

    fl2 = np.empty(n_events, dtype=np.float32)
    fl2[indices[:n_dim]] = np.random.normal(20, 15, n_dim).astype(np.float32)
    fl2[indices[n_dim:]] = np.random.normal(5000, 2000, n_bright).astype(np.float32)

    fl3 = np.empty(n_events, dtype=np.float32)
    fl3[indices[:n_dim]] = np.random.normal(-10, 20, n_dim).astype(np.float32)
    fl3[indices[n_dim:]] = np.random.normal(3000, 1000, n_bright).astype(np.float32)

    fl4 = np.empty(n_events, dtype=np.float32)
    fl4[indices[:n_dim]] = np.random.normal(30, 25, n_dim).astype(np.float32)
    fl4[indices[n_dim:]] = np.random.normal(8000, 2500, n_bright).astype(np.float32)

    # Time: linearly increasing
    time_ch = np.linspace(0, 1000, n_events).astype(np.float32)

    # FSC-A: correlated with FSC-H
    fsc_a = (fsc * np.random.uniform(0.8, 1.2, n_events)).astype(np.float32)

    data = np.column_stack([fsc, ssc, fl1, fl2, fl3, fl4, time_ch, fsc_a])

    # Save raw data CSV for test verification
    header_line = ",".join(param_names)
    np.savetxt(raw_csv_path, data, delimiter=",", header=header_line,
               comments="")

    # ----- Build FCS 3.0 binary file -----
    delimiter = "|"

    # Spillover matrix (4x4, row-major) for FL1-FL4
    spillover_values = [
        1.0,   0.25,  0.01,  0.002,   # row 1: FL1-H
        0.1,   1.0,   0.20,  0.01,    # row 2: FL2-H
        0.005, 0.15,  1.0,   0.15,    # row 3: FL3-H
        0.001, 0.01,  0.10,  1.0      # row 4: FL4-H
    ]
    spill_str = "4,FL1-H,FL2-H,FL3-H,FL4-H," + \
                ",".join(str(v) for v in spillover_values)

    # FCS keywords
    keywords = {
        "$BEGINANALYSIS": "0",
        "$ENDANALYSIS":   "0",
        "$BEGINSTEXT":    "0",
        "$ENDSTEXT":      "0",
        "$MODE":          "L",
        "$DATATYPE":      "F",
        "$BYTEORD":       "4,3,2,1",
        "$PAR":           str(n_params),
        "$TOT":           str(n_events),
        "$NEXTDATA":      "0",
        "$SPILLOVER":     spill_str,
        "$SRC":           "SyntheticTestData",
    }

    for i, name in enumerate(param_names, 1):
        keywords[f"$P{i}N"] = name
        keywords[f"$P{i}B"] = "32"
        keywords[f"$P{i}R"] = "262144"
        keywords[f"$P{i}E"] = "0,0"

    # Placeholder offsets — will be resolved iteratively
    keywords["$BEGINDATA"] = "0"
    keywords["$ENDDATA"]   = "0"

    # Binary DATA segment (big-endian float32)
    data_bytes = data.astype(">f4").tobytes()

    # Iteratively resolve TEXT ↔ offset circular dependency
    header_size = 58
    text_start = header_size

    for _ in range(20):
        # Build TEXT segment
        parts = []
        for key in sorted(keywords.keys()):
            val = keywords[key]
            # Escape any delimiters in values (double them)
            escaped = val.replace(delimiter, delimiter + delimiter)
            parts.append(key)
            parts.append(escaped)
        text_content = delimiter + delimiter.join(parts) + delimiter
        text_bytes = text_content.encode("ascii")

        text_end = text_start + len(text_bytes) - 1
        data_start = text_end + 1
        data_end = data_start + len(data_bytes) - 1

        # Check convergence
        if (keywords["$BEGINDATA"] == str(data_start) and
                keywords["$ENDDATA"] == str(data_end)):
            break

        keywords["$BEGINDATA"] = str(data_start)
        keywords["$ENDDATA"]   = str(data_end)

    # Write the FCS file
    with open(output_path, "wb") as f:
        # HEADER (58 bytes)
        header = (f"FCS3.0    "
                  f"{text_start:>8d}{text_end:>8d}"
                  f"{data_start:>8d}{data_end:>8d}"
                  f"{0:>8d}{0:>8d}")
        assert len(header) == 58, f"Header length {len(header)} != 58"
        f.write(header.encode("ascii"))

        # TEXT segment
        f.write(text_bytes)

        # DATA segment
        f.write(data_bytes)

    print(f"Generated FCS file: {output_path}")
    print(f"  {n_events} events, {n_params} parameters")
    print(f"  TEXT: {text_start}-{text_end}")
    print(f"  DATA: {data_start}-{data_end}")
    print(f"  Total file size: {data_end + 1} bytes")


if __name__ == "__main__":
    os.makedirs("/app/data", exist_ok=True)
    generate_fcs("/app/data/test_sample.fcs", "/app/data/test_sample_raw.csv")
