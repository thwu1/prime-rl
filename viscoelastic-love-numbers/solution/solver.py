"""
Pipeline: compile and run TABOO, parse output, compute Heaviside response.

"""

import json
import csv
import os
import math
import subprocess
import tempfile
import shutil


def compile_taboo(taboo_src, work_dir):
    """Compile TABOO Fortran source. Returns path to executable."""
    src_path = os.path.join(work_dir, "taboo.f90")

    # Read and sanitize non-ASCII characters
    with open(taboo_src, "rb") as f:
        raw = f.read()
    clean = bytes(b for b in raw if b < 128)
    with open(src_path, "wb") as f:
        f.write(clean)

    exe_path = os.path.join(work_dir, "taboo.exe")

    # Try compilation with standard flags
    flags = [
        "gfortran", "-O2", "-fallow-argument-mismatch", "-std=legacy",
        "-ffree-line-length-none", "-w", src_path, "-o", exe_path
    ]
    result = subprocess.run(flags, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(exe_path):
        # Retry with -O0
        flags[2] = "-O0"
        flags[1] = "-O0"
        result = subprocess.run(
            ["gfortran", "-O0", "-fallow-argument-mismatch", "-std=legacy",
             "-ffree-line-length-none", "-w", src_path, "-o", exe_path],
            capture_output=True, text=True
        )
    if not os.path.exists(exe_path):
        raise RuntimeError(f"TABOO compilation failed:\n{result.stderr}")
    return exe_path


def create_task_files(work_dir, spec):
    """Create TABOO task_1.dat, task_2.dat, task_3.dat from model spec."""
    nv = spec["nv"]
    code = spec["code"]
    lt = spec["lithosphere_thickness_km"]
    ilm = spec.get("ilm", 0)
    viscosities = spec["viscosities_1e21_Pa_s"]
    lmin = spec["lmin"]
    lmax = spec["lmax"]
    loading = 1 if spec["loading"] else 0

    # task_1.dat
    lines = ["Active"]
    lines.append("Harmonic_Degrees")
    lines.append(f"    {lmin}   {lmax}")
    lines.append("    0")       # VERBOSE = 0
    lines.append(f"    {loading}")
    lines.append("Make_Model")
    lines.append(f"    {nv}")
    lines.append(f"    {code}")
    lines.append(f"    {lt:.1f}")
    lines.append(f"    {ilm}")
    for v in viscosities:
        lines.append(f"    {v}")
    lines.append("El_Fluid_Viscel")
    lines.append("    1")
    lines.append("    1")
    lines.append("    1")

    with open(os.path.join(work_dir, "task_1.dat"), "w") as f:
        f.write("\n".join(lines) + "\n")

    with open(os.path.join(work_dir, "task_2.dat"), "w") as f:
        f.write("!Inactive\n")

    with open(os.path.join(work_dir, "task_3.dat"), "w") as f:
        f.write("!Inactive\n")


def run_taboo(exe_path, work_dir):
    """Run TABOO executable in work_dir."""
    result = subprocess.run(
        [exe_path],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=120
    )
    if result.returncode != 0:
        log_path = os.path.join(work_dir, "taboo.log")
        log_content = ""
        if os.path.exists(log_path):
            with open(log_path) as f:
                log_content = f.read()[-2000:]
        raise RuntimeError(
            f"TABOO run failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}\n"
            f"log: {log_content}"
        )
    return result


def parse_spectrum(filepath):
    """Parse TABOO spectrum.dat.
    Returns dict: degree -> list of s values (all nroots modes, in order).
    """
    modes = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                deg = int(parts[0])
                s_val = float(parts[2])
            except (ValueError, IndexError):
                continue
            modes.setdefault(deg, []).append(s_val)
    return modes


def parse_love_dat(filepath):
    """Parse TABOO h/l/k.dat (El_Fluid_Viscel format).
    Returns dict: degree -> (elastic, fluid, [residue_0, ..., residue_N]).
    """
    result = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                deg = int(parts[0])
                elastic = float(parts[1])
                fluid = float(parts[2])
                residues = [float(x) for x in parts[3:]]
            except (ValueError, IndexError):
                continue
            result[deg] = (elastic, fluid, residues)
    return result


def compute_heaviside_response(elastic, s_values, residues, t):
    """Compute Heaviside response: h^H(l,t) = h_e + sum_k [h_v_k/s_k * (exp(s_k*t) - 1)]
    Only uses physical modes (s < 0).
    """
    val = elastic
    for idx, s_val in enumerate(s_values):
        if s_val < 0 and idx < len(residues):
            h_v = residues[idx]
            val += (h_v / s_val) * (math.exp(s_val * t) - 1.0)
    return val


def main():
    spec_path = "/app/model_spec.json"
    taboo_src = "/app/taboo.f90"
    output_dir = "/app/output"

    with open(spec_path) as f:
        spec = json.load(f)

    lmin = spec["lmin"]
    lmax = spec["lmax"]
    time_points = spec["time_points_kyr"]

    # Set up working directory
    work_dir = tempfile.mkdtemp(prefix="taboo_run_")

    try:
        # Step 1: Compile TABOO
        print("Compiling TABOO...")
        exe_path = compile_taboo(taboo_src, work_dir)
        print("TABOO compiled successfully")

        # Step 2: Create input files
        print("Creating TABOO input files...")
        create_task_files(work_dir, spec)

        # Step 3: Run TABOO
        print("Running TABOO...")
        run_taboo(exe_path, work_dir)
        print("TABOO completed")

        # Step 4: Parse output files
        spectrum_path = os.path.join(work_dir, "spectrum.dat")
        h_path = os.path.join(work_dir, "h.dat")
        l_path = os.path.join(work_dir, "l.dat")
        k_path = os.path.join(work_dir, "k.dat")

        for fpath in [spectrum_path, h_path, l_path, k_path]:
            if not os.path.exists(fpath):
                raise FileNotFoundError(f"Expected TABOO output not found: {fpath}")

        spectrum = parse_spectrum(spectrum_path)
        h_data = parse_love_dat(h_path)
        l_data = parse_love_dat(l_path)
        k_data = parse_love_dat(k_path)

        # Step 5: Write output CSVs
        os.makedirs(output_dir, exist_ok=True)

        # modes.csv - physical modes only
        with open(os.path.join(output_dir, "modes.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["degree", "mode_index", "s_kyr_inv"])
            for deg in range(lmin, lmax + 1):
                if deg not in spectrum:
                    continue
                all_s = spectrum[deg]
                phys_modes = []
                for idx, s_val in enumerate(all_s):
                    if s_val < 0:
                        phys_modes.append((idx, s_val))
                phys_modes.sort(key=lambda x: x[1])
                for mode_idx, (_, s_val) in enumerate(phys_modes):
                    writer.writerow([deg, mode_idx, f"{s_val:.12e}"])

        # love_numbers.csv
        with open(os.path.join(output_dir, "love_numbers.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["degree", "h_elastic", "h_fluid",
                             "l_elastic", "l_fluid", "k_elastic", "k_fluid"])
            for deg in range(lmin, lmax + 1):
                h_e, h_f, _ = h_data[deg]
                l_e, l_f, _ = l_data[deg]
                k_e, k_f, _ = k_data[deg]
                writer.writerow([
                    deg,
                    f"{h_e:.12e}", f"{h_f:.12e}",
                    f"{l_e:.12e}", f"{l_f:.12e}",
                    f"{k_e:.12e}", f"{k_f:.12e}"
                ])

        # Heaviside response CSVs
        for love_label, love_data, out_name in [
            ("h", h_data, "heaviside_h.csv"),
            ("l", l_data, "heaviside_l.csv"),
            ("k", k_data, "heaviside_k.csv"),
        ]:
            with open(os.path.join(output_dir, out_name), "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["degree", "t_kyr", "value"])
                for deg in range(lmin, lmax + 1):
                    if deg not in love_data or deg not in spectrum:
                        continue
                    elastic, fluid, residues = love_data[deg]
                    all_s = spectrum[deg]
                    for t in time_points:
                        val = compute_heaviside_response(
                            elastic, all_s, residues, t
                        )
                        writer.writerow([deg, t, f"{val:.12e}"])

        print(f"Output written to {output_dir}")
        print(f"  modes.csv: physical modes for degrees {lmin}-{lmax}")
        n_modes = sum(
            1 for deg in range(lmin, lmax + 1)
            if deg in spectrum
            for s in spectrum[deg] if s < 0
        )
        print(f"  Total physical modes: {n_modes}")
        print(f"  love_numbers.csv: {lmax - lmin + 1} degrees")
        print(f"  heaviside_*.csv: {lmax - lmin + 1} degrees x {len(time_points)} times")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
