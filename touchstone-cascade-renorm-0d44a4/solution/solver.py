#!/usr/bin/env python3
"""Reference solution for the Touchstone cascade renormalization task.

Uses ctypes to interface with the C matrix operations library (libmatrix.so)
for all 2x2 complex matrix arithmetic. Generates gnuplot SVG plot and
Touchstone v2.0 output.
"""


import json
import os
import math
import cmath
import ctypes
import subprocess


# =============================================================================
# C Library Interface
# =============================================================================

class MatLib:
    """Python wrapper around the C matrix operations shared library.

    Complex 2x2 matrices are packed as double[8]:
      [re(0,0), im(0,0), re(0,1), im(0,1), re(1,0), im(1,0), re(1,1), im(1,1)]
    """

    D8 = ctypes.c_double * 8

    def __init__(self, lib_path):
        self.lib = ctypes.CDLL(lib_path)
        self._setup_prototypes()

    def _setup_prototypes(self):
        PD = ctypes.POINTER(ctypes.c_double)
        CD = ctypes.c_double

        self.lib.cmat2_multiply.argtypes = [PD, PD, PD]
        self.lib.cmat2_multiply.restype = None

        self.lib.cmat2_invert.argtypes = [PD, PD]
        self.lib.cmat2_invert.restype = ctypes.c_int

        self.lib.cmat2_determinant.argtypes = [PD, PD, PD]
        self.lib.cmat2_determinant.restype = None

        self.lib.cmat2_add.argtypes = [PD, PD, PD]
        self.lib.cmat2_add.restype = None

        self.lib.cmat2_subtract.argtypes = [PD, PD, PD]
        self.lib.cmat2_subtract.restype = None

        self.lib.cmat2_scale.argtypes = [PD, CD, CD, PD]
        self.lib.cmat2_scale.restype = None

        self.lib.cmat2_identity.argtypes = [PD]
        self.lib.cmat2_identity.restype = None

        self.lib.cmat2_diag.argtypes = [CD, CD, CD, CD, PD]
        self.lib.cmat2_diag.restype = None

    def _pack(self, m):
        """Pack [[complex, complex], [complex, complex]] -> double[8]."""
        arr = self.D8()
        arr[0], arr[1] = m[0][0].real, m[0][0].imag
        arr[2], arr[3] = m[0][1].real, m[0][1].imag
        arr[4], arr[5] = m[1][0].real, m[1][0].imag
        arr[6], arr[7] = m[1][1].real, m[1][1].imag
        return arr

    def _unpack(self, arr):
        """Unpack double[8] -> [[complex, complex], [complex, complex]]."""
        return [
            [complex(arr[0], arr[1]), complex(arr[2], arr[3])],
            [complex(arr[4], arr[5]), complex(arr[6], arr[7])]
        ]

    def multiply(self, A, B):
        a, b, c = self._pack(A), self._pack(B), self.D8()
        self.lib.cmat2_multiply(a, b, c)
        return self._unpack(c)

    def invert(self, A):
        a, ainv = self._pack(A), self.D8()
        ret = self.lib.cmat2_invert(a, ainv)
        if ret != 0:
            raise ValueError("Singular matrix")
        return self._unpack(ainv)

    def add(self, A, B):
        a, b, c = self._pack(A), self._pack(B), self.D8()
        self.lib.cmat2_add(a, b, c)
        return self._unpack(c)

    def subtract(self, A, B):
        a, b, c = self._pack(A), self._pack(B), self.D8()
        self.lib.cmat2_subtract(a, b, c)
        return self._unpack(c)

    def scale(self, A, s):
        """Scale matrix A by complex scalar s."""
        a, c = self._pack(A), self.D8()
        self.lib.cmat2_scale(a, ctypes.c_double(s.real),
                             ctypes.c_double(s.imag), c)
        return self._unpack(c)

    def identity(self):
        i = self.D8()
        self.lib.cmat2_identity(i)
        return self._unpack(i)

    def diag(self, d00, d11):
        """Create diagonal matrix with complex entries d00 and d11."""
        d = self.D8()
        self.lib.cmat2_diag(ctypes.c_double(d00.real), ctypes.c_double(d00.imag),
                            ctypes.c_double(d11.real), ctypes.c_double(d11.imag), d)
        return self._unpack(d)

    def determinant(self, A):
        a = self._pack(A)
        dr, di = ctypes.c_double(), ctypes.c_double()
        self.lib.cmat2_determinant(a, ctypes.byref(dr), ctypes.byref(di))
        return complex(dr.value, di.value)


# =============================================================================
# Touchstone Parsing
# =============================================================================

def parse_touchstone_v1(filepath):
    """Parse a Touchstone v1.0 2-port file.

    Returns: (freqs, S_matrices, z0)
      freqs: list of float
      S_matrices: list of [[S11, S12], [S21, S22]] complex
      z0: float reference impedance
    """
    with open(filepath) as f:
        lines = f.readlines()

    fmt = "ma"
    z0 = 50.0
    option_parsed = False
    data_values = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        if "!" in stripped:
            stripped = stripped[:stripped.index("!")].strip()
            if not stripped:
                continue

        if stripped.startswith("#") and not option_parsed:
            parts = stripped[1:].strip().lower().split()
            defaults = ["ghz", "s", "ma", "r", "50"]
            parts.extend(defaults[len(parts):])
            fmt = parts[2]
            if len(parts) >= 5 and parts[3] == "r":
                z0 = float(parts[4])
            option_parsed = True
            continue

        try:
            vals = list(map(float, stripped.split()))
            data_values.extend(vals)
        except ValueError:
            continue

    # 2-port: 1 freq + 8 data values = 9 per frequency
    n_freq = len(data_values) // 9
    freqs = []
    S_matrices = []

    for i in range(n_freq):
        off = i * 9
        freqs.append(data_values[off])

        s_raw = []
        for j in range(4):
            v1 = data_values[off + 1 + 2 * j]
            v2 = data_values[off + 2 + 2 * j]
            if fmt == "ma":
                s_raw.append(v1 * cmath.exp(1j * math.radians(v2)))
            elif fmt == "db":
                mag = 10.0 ** (v1 / 20.0)
                s_raw.append(mag * cmath.exp(1j * math.radians(v2)))
            elif fmt == "ri":
                s_raw.append(complex(v1, v2))

        # Legacy 21_12 ordering: S11, S21, S12, S22
        S_matrices.append([
            [s_raw[0], s_raw[2]],
            [s_raw[1], s_raw[3]]
        ])

    return freqs, S_matrices, z0


def parse_touchstone_v2(filepath):
    """Parse a Touchstone v2.0 2-port file.

    Returns: (freqs, S_matrices, z0_per_port)
      freqs: list of float
      S_matrices: list of [[S11, S12], [S21, S22]] complex
      z0_per_port: list of float
    """
    with open(filepath) as f:
        lines = f.readlines()

    fmt = "ma"
    z0_default = 50.0
    two_port_order = "21_12"
    z0_per_port = None
    in_network_data = False
    data_values = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue

        lower = stripped.lower()

        if lower.startswith("[version]"):
            continue
        elif stripped.startswith("#"):
            parts = stripped[1:].strip().lower().split()
            defaults = ["ghz", "s", "ma", "r", "50"]
            parts.extend(defaults[len(parts):])
            fmt = parts[2]
            if len(parts) >= 5 and parts[3] == "r":
                z0_default = float(parts[4])
            continue
        elif lower.startswith("[number of ports]"):
            continue
        elif lower.startswith("[two-port data order]"):
            two_port_order = stripped.split()[-1]
            continue
        elif lower.startswith("[number of frequencies]"):
            continue
        elif lower.startswith("[reference]"):
            bracket_end = stripped.index("]") + 1
            ref_str = stripped[bracket_end:].strip()
            if "!" in ref_str:
                ref_str = ref_str[:ref_str.index("!")].strip()
            z0_per_port = [float(v) for v in ref_str.split()]
            continue
        elif lower.startswith("[matrix format]"):
            continue
        elif lower.startswith("[network data]"):
            in_network_data = True
            continue
        elif lower.startswith("[end]"):
            break
        elif lower.startswith("["):
            continue

        if not in_network_data:
            continue

        if "!" in stripped:
            stripped = stripped[:stripped.index("!")].strip()
            if not stripped:
                continue

        try:
            vals = list(map(float, stripped.split()))
            data_values.extend(vals)
        except ValueError:
            continue

    if z0_per_port is None:
        z0_per_port = [z0_default, z0_default]

    n_freq = len(data_values) // 9
    freqs = []
    S_matrices = []

    for i in range(n_freq):
        off = i * 9
        freqs.append(data_values[off])

        s_raw = []
        for j in range(4):
            v1 = data_values[off + 1 + 2 * j]
            v2 = data_values[off + 2 + 2 * j]
            if fmt == "ma":
                s_raw.append(v1 * cmath.exp(1j * math.radians(v2)))
            elif fmt == "db":
                mag = 10.0 ** (v1 / 20.0)
                s_raw.append(mag * cmath.exp(1j * math.radians(v2)))
            elif fmt == "ri":
                s_raw.append(complex(v1, v2))

        if two_port_order == "12_21":
            S_matrices.append([
                [s_raw[0], s_raw[1]],
                [s_raw[2], s_raw[3]]
            ])
        else:
            S_matrices.append([
                [s_raw[0], s_raw[2]],
                [s_raw[1], s_raw[3]]
            ])

    return freqs, S_matrices, z0_per_port


# =============================================================================
# RF Operations (using C library via MatLib)
# =============================================================================

def s_to_z_perport(ml, S, z0_ports):
    """Convert S to Z with per-port reference impedances.
    Z = sqrt(Z0) * (I + S) * inv(I - S) * sqrt(Z0)
    """
    I = ml.identity()
    sqrt_z0 = ml.diag(complex(math.sqrt(z0_ports[0])),
                       complex(math.sqrt(z0_ports[1])))
    IpS = ml.add(I, S)
    ImS = ml.subtract(I, S)
    ImS_inv = ml.invert(ImS)
    t1 = ml.multiply(sqrt_z0, IpS)
    t2 = ml.multiply(t1, ImS_inv)
    Z = ml.multiply(t2, sqrt_z0)
    return Z


def s_to_z_uniform(ml, S, z0):
    """Convert S to Z with uniform reference impedance.
    Z = z0 * (I + S) * inv(I - S)
    """
    I = ml.identity()
    IpS = ml.add(I, S)
    ImS = ml.subtract(I, S)
    ImS_inv = ml.invert(ImS)
    temp = ml.multiply(IpS, ImS_inv)
    Z = ml.scale(temp, complex(z0))
    return Z


def z_to_s_uniform(ml, Z, z0):
    """Convert Z to S with uniform reference impedance.
    S = (Z - z0*I) * inv(Z + z0*I)
    """
    I = ml.identity()
    z0I = ml.scale(I, complex(z0))
    ZmZ0 = ml.subtract(Z, z0I)
    ZpZ0 = ml.add(Z, z0I)
    ZpZ0_inv = ml.invert(ZpZ0)
    S = ml.multiply(ZmZ0, ZpZ0_inv)
    return S


def s_to_t(ml, S):
    """Convert S-parameters to transfer (T) parameters.
    T11 = -det(S)/S21, T12 = S11/S21, T21 = -S22/S21, T22 = 1/S21
    """
    S11 = S[0][0]
    S12 = S[0][1]
    S21 = S[1][0]
    S22 = S[1][1]
    det_S = ml.determinant(S)
    return [
        [-det_S / S21, S11 / S21],
        [-S22 / S21, complex(1.0) / S21]
    ]


def t_to_s(T):
    """Convert transfer (T) parameters to S-parameters.
    S11 = T12/T22, S12 = det(T)/T22, S21 = 1/T22, S22 = -T21/T22
    """
    T11, T12, T21, T22 = T[0][0], T[0][1], T[1][0], T[1][1]
    return [
        [T12 / T22, (T11 * T22 - T12 * T21) / T22],
        [complex(1.0) / T22, -T21 / T22]
    ]


# =============================================================================
# Output Writers
# =============================================================================

def write_cascade_sparams(freqs, S_final, target_z0, output_path):
    out = {
        "reference_impedance_ohm": target_z0,
        "frequencies_ghz": freqs,
        "s_parameters": []
    }
    for i in range(len(freqs)):
        S = S_final[i]
        out["s_parameters"].append({
            "freq_ghz": freqs[i],
            "S11_re": S[0][0].real, "S11_im": S[0][0].imag,
            "S12_re": S[0][1].real, "S12_im": S[0][1].imag,
            "S21_re": S[1][0].real, "S21_im": S[1][0].imag,
            "S22_re": S[1][1].real, "S22_im": S[1][1].imag,
        })
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)


def write_z_matrix(freqs, Z_params, output_path):
    out = {"frequencies_ghz": freqs, "z_parameters": []}
    for i in range(len(freqs)):
        Z = Z_params[i]
        out["z_parameters"].append({
            "freq_ghz": freqs[i],
            "Z11_re": Z[0][0].real, "Z11_im": Z[0][0].imag,
            "Z12_re": Z[0][1].real, "Z12_im": Z[0][1].imag,
            "Z21_re": Z[1][0].real, "Z21_im": Z[1][0].imag,
            "Z22_re": Z[1][1].real, "Z22_im": Z[1][1].imag,
        })
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)


def write_metrics(freqs, S_final, output_path):
    il = []
    rl = []
    for i in range(len(freqs)):
        s21_mag = abs(S_final[i][1][0])
        s11_mag = abs(S_final[i][0][0])
        il.append(20.0 * math.log10(s21_mag))
        rl.append(-20.0 * math.log10(s11_mag))
    out = {
        "frequencies_ghz": freqs,
        "insertion_loss_db": il,
        "return_loss_db": rl
    }
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)
    return il, rl


def write_touchstone_v2(freqs, S_final, target_z0, output_path):
    """Write cascaded S-parameters as a Touchstone v2.0 file."""
    n = len(freqs)
    with open(output_path, "w") as f:
        f.write("[Version] 2.0\n")
        f.write(f"# GHz S RI R {target_z0}\n")
        f.write("[Number of Ports] 2\n")
        f.write("[Two-Port Data Order] 12_21\n")
        f.write(f"[Number of Frequencies] {n}\n")
        f.write(f"[Reference] {target_z0} {target_z0}\n")
        f.write("[Matrix Format] Full\n")
        f.write("[Network Data]\n")
        for i in range(n):
            S = S_final[i]
            # 12_21 ordering: S11, S12, S21, S22
            f.write(f"{freqs[i]:.6f}"
                    f" {S[0][0].real:.9f} {S[0][0].imag:.9f}"
                    f" {S[0][1].real:.9f} {S[0][1].imag:.9f}"
                    f" {S[1][0].real:.9f} {S[1][0].imag:.9f}"
                    f" {S[1][1].real:.9f} {S[1][1].imag:.9f}\n")
        f.write("[End]\n")


def generate_gnuplot_svg(freqs, il, rl, output_dir):
    """Generate SVG frequency response plot using gnuplot."""
    data_path = os.path.join(output_dir, "_plot_data.dat")
    script_path = os.path.join(output_dir, "_plot.gp")
    svg_path = os.path.join(output_dir, "frequency_response.svg")

    with open(data_path, "w") as f:
        f.write("# freq_ghz  insertion_loss_db  return_loss_db\n")
        for i in range(len(freqs)):
            f.write(f"{freqs[i]:.6f}  {il[i]:.6f}  {rl[i]:.6f}\n")

    with open(script_path, "w") as f:
        f.write(f"set terminal svg size 800,600 enhanced\n")
        f.write(f'set output "{svg_path}"\n')
        f.write(f'set title "Cascaded Network Frequency Response"\n')
        f.write(f'set xlabel "Frequency (GHz)"\n')
        f.write(f'set ylabel "Magnitude (dB)"\n')
        f.write(f"set grid\n")
        f.write(f"set key top right box\n")
        f.write(f'plot "{data_path}" using 1:2 with linespoints lw 2 '
                f'title "Insertion Loss", \\\n')
        f.write(f'     "{data_path}" using 1:3 with linespoints lw 2 '
                f'title "Return Loss"\n')

    subprocess.run(["gnuplot", script_path], check=True)


# =============================================================================
# Main Pipeline
# =============================================================================

def main():
    # Ensure the C library is compiled
    subprocess.run(["make", "-C", "/app"], check=True,
                   capture_output=True, text=True)

    # Load the C library
    ml = MatLib("/app/libmatrix.so")

    # Read config
    with open("/app/config.json") as f:
        config = json.load(f)

    target_z0 = config["target_impedance_ohm"]
    output_dir = config["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    # Parse both networks
    freqs_a, S_A, z0_a = parse_touchstone_v1(config["network_a"])
    freqs_b, S_B, z0_b_per_port = parse_touchstone_v2(config["network_b"])

    assert len(freqs_a) == len(freqs_b), "Frequency count mismatch"
    for i in range(len(freqs_a)):
        assert abs(freqs_a[i] - freqs_b[i]) < 1e-9, \
            f"Frequency mismatch at index {i}"

    freqs = freqs_a
    n_freq = len(freqs)

    # Renormalize Network B from per-port impedances to uniform z0_a
    S_B_uniform = []
    for i in range(n_freq):
        Z_B = s_to_z_perport(ml, S_B[i], z0_b_per_port)
        S_B_uniform.append(z_to_s_uniform(ml, Z_B, z0_a))

    # Cascade via T-parameters
    S_cascade = []
    for i in range(n_freq):
        T_A = s_to_t(ml, S_A[i])
        T_B = s_to_t(ml, S_B_uniform[i])
        T_cas = ml.multiply(T_A, T_B)
        S_cascade.append(t_to_s(T_cas))

    # Renormalize from z0_a to target_z0 and compute Z-parameters
    S_final = []
    Z_params = []
    for i in range(n_freq):
        Z_cas = s_to_z_uniform(ml, S_cascade[i], z0_a)
        S_final.append(z_to_s_uniform(ml, Z_cas, target_z0))
        Z_params.append(Z_cas)

    # Write all outputs
    write_cascade_sparams(freqs, S_final, target_z0,
                          os.path.join(output_dir, "cascade_sparams.json"))
    write_z_matrix(freqs, Z_params,
                   os.path.join(output_dir, "z_matrix.json"))
    il, rl = write_metrics(freqs, S_final,
                           os.path.join(output_dir, "metrics.json"))
    write_touchstone_v2(freqs, S_final, target_z0,
                        os.path.join(output_dir, "cascade_output.ts"))
    generate_gnuplot_svg(freqs, il, rl, output_dir)

    print("Processing complete. Output written to", output_dir)


if __name__ == "__main__":
    main()
