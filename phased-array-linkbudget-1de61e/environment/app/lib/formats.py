"""Parsers for RF measurement data files.

Supports Touchstone S1P files and complex-valued coupling matrix CSV.
"""

import math


def read_s1p(filepath):
    """Read a Touchstone S1P (one-port S-parameter) file.

    Supports RI (Real/Imaginary), MA (Magnitude/Angle), and DB
    (dB-magnitude/Angle) formats.  Frequency units: Hz, kHz, MHz, GHz.

    Returns
    -------
    dict with keys
        'z0'          : float  -- reference impedance in ohms
        'frequencies' : list of float  -- frequencies in Hz
        's11'         : list of complex -- S11 values
    """
    freq_multipliers = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}

    z0 = 50.0
    fmt = "MA"
    f_mult = 1e9
    frequencies = []
    s11_vals = []

    with open(filepath) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("!"):
                continue

            if line.startswith("#"):
                parts = line[1:].split()
                if len(parts) >= 1:
                    f_mult = freq_multipliers.get(parts[0].upper(), 1e9)
                if len(parts) >= 3:
                    fmt = parts[2].upper()
                if len(parts) >= 5 and parts[3].upper() == "R":
                    z0 = float(parts[4])
                continue

            parts = line.split()
            if len(parts) < 3:
                continue

            freq = float(parts[0]) * f_mult
            p1 = float(parts[1])
            p2 = float(parts[2])

            if fmt == "RI":
                s11 = complex(p1, p2)
            elif fmt == "MA":
                angle_rad = math.radians(p2)
                s11 = complex(p1 * math.cos(angle_rad),
                              p1 * math.sin(angle_rad))
            elif fmt == "DB":
                mag = 10.0 ** (p1 / 20.0)
                angle_rad = math.radians(p2)
                s11 = complex(mag * math.cos(angle_rad),
                              mag * math.sin(angle_rad))
            else:
                s11 = complex(p1, p2)

            frequencies.append(freq)
            s11_vals.append(s11)

    return {"z0": z0, "frequencies": frequencies, "s11": s11_vals}


def read_coupling_matrix(filepath):
    """Read a complex mutual coupling matrix from CSV.

    File format: rows of comma-separated cells.  Each cell contains two
    space-separated floats ``real imag`` representing a complex number.
    Lines starting with '#' are comments.

    Returns
    -------
    list of lists of complex  -- N x N matrix
    """
    rows = []
    with open(filepath) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cells = line.split(",")
            row = []
            for cell in cells:
                parts = cell.strip().split()
                row.append(complex(float(parts[0]), float(parts[1])))
            rows.append(row)
    return rows
