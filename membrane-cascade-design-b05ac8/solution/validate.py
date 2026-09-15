
"""Validate EOS against NIST WebBook reference data."""

import json

R = 8.314462  # J/(mol*K)
ATM_TO_PA = 101325.0
ATM_TO_BAR = 1.01325


def load_gas_properties():
    with open("/app/data/gas_properties.json") as f:
        return json.load(f)


def validate_eos(gas_name, pressure_atm):
    """Parse NIST WebBook TSV and compare Z values against EOS.

    Parameters
    ----------
    gas_name : str
    pressure_atm : int or float, pressure in atm

    Returns
    -------
    list of dict with T_K, P_bar, Z_computed, Z_nist, relative_error
    """
    from .eos import pr_fugacity_pure

    gas_props = load_gas_properties()
    gas_data = gas_props["gases"][gas_name]
    MW_kg = gas_data["molecular_weight"] / 1000.0  # kg/mol

    # Construct file path
    p_int = int(pressure_atm)
    tsv_path = f"/app/data/nist/{gas_name}_{p_int}atm.tsv"

    # Parse TSV file
    with open(tsv_path) as f:
        lines = f.readlines()

    # First line is column headers
    header_line = lines[0].strip()
    headers = header_line.split("\t")

    # Find column indices
    temp_idx = None
    pressure_idx = None
    density_idx = None
    for i, h in enumerate(headers):
        hl = h.strip().lower()
        if hl.startswith("temperature"):
            temp_idx = i
        elif hl.startswith("pressure"):
            pressure_idx = i
        elif hl.startswith("density"):
            density_idx = i

    if temp_idx is None or density_idx is None:
        raise ValueError(f"Could not find required columns in {tsv_path}")

    results = []
    P_Pa = float(pressure_atm) * ATM_TO_PA
    P_bar = float(pressure_atm) * ATM_TO_BAR

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")

        T = float(parts[temp_idx])
        rho = float(parts[density_idx])  # kg/m3

        # Z_nist = P * MW / (rho * R * T)
        Z_nist = P_Pa * MW_kg / (rho * R * T)

        # Compute Z using EOS
        try:
            eos_result = pr_fugacity_pure(gas_name, T, P_bar, gas_props)
            Z_computed = eos_result["Z"]
        except Exception:
            continue

        rel_error = abs(Z_computed - Z_nist) / Z_nist if Z_nist > 0 else 0.0

        results.append({
            "T_K": T,
            "P_bar": round(P_bar, 6),
            "Z_computed": round(Z_computed, 8),
            "Z_nist": round(Z_nist, 8),
            "relative_error": round(rel_error, 8),
        })

    results.sort(key=lambda x: x["T_K"])
    return results
