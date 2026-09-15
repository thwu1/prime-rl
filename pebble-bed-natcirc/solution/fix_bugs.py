#!/usr/bin/env python3
"""
Fix all physics defects in the natcirc_sim simulation stack.

Bug 1 (Fortran - src/packed_bed.f90): Ergun equation viscous term uses
    constant 180 (Blake-Kozeny-Carman) instead of 150 (standard Ergun).
    Fix: edit Fortran source and recompile shared library with make.

Bug 2 (Python - natcirc_sim/helium.py): Viscosity uses hardcoded
    Sutherland's law instead of the power-law correlation specified
    in reactor.toml (mu_coeff * T^mu_exp).
    Fix: replace Sutherland function with power-law, update loop.py callers.

Bug 3 (SQLite - reactor.db): The include_chimney_buoyancy solver option
    is set to 0, disabling the chimney/riser buoyancy contribution to the
    driving force. This omits a major portion of the buoyancy integral.
    Fix: UPDATE the flag to 1 in the solver_options table.

"""
import os
import subprocess
import sqlite3


def fix_fortran_ergun():
    """Fix Ergun constant in Fortran source: 180 -> 150, then rebuild."""
    path = "/app/src/packed_bed.f90"
    with open(path, "r") as f:
        content = f.read()

    content = content.replace("180.0d0", "150.0d0")

    with open(path, "w") as f:
        f.write(content)

    # Rebuild the shared library
    subprocess.run(["make", "-C", "/app", "clean"], check=True)
    subprocess.run(["make", "-C", "/app"], check=True)
    print("Fixed packed_bed.f90: Ergun constant 180 -> 150, rebuilt libpackedbed.so")


def fix_helium_viscosity():
    """Fix helium.py: use power-law viscosity from config instead of Sutherland."""
    path = "/app/natcirc_sim/helium.py"
    with open(path, "r") as f:
        content = f.read()

    old_func = '''def viscosity(T):
    """
    Dynamic viscosity of helium [Pa\xb7s].

    Uses Sutherland's law for monatomic gases (Crane TP-410).

    Parameters
    ----------
    T : float
        Temperature [K]
    """
    mu_ref = 1.96e-5    # Pa\xb7s at T_ref
    T_ref = 273.15       # K
    S = 79.4             # Sutherland constant for He [K]
    return mu_ref * (T / T_ref) ** 1.5 * (T_ref + S) / (T + S)'''

    new_func = '''def viscosity(T, mu_coeff, mu_exp):
    """
    Dynamic viscosity of helium [Pa\xb7s].

    Power-law correlation: mu = mu_coeff * T^mu_exp

    Parameters
    ----------
    T : float
        Temperature [K]
    mu_coeff : float
        Power-law coefficient
    mu_exp : float
        Power-law exponent
    """
    return mu_coeff * T ** mu_exp'''

    content = content.replace(old_func, new_func)
    with open(path, "w") as f:
        f.write(content)
    print("Fixed helium.py: power-law viscosity")


def fix_loop_viscosity_calls():
    """Update loop.py to pass mu_coeff/mu_exp to the viscosity function."""
    path = "/app/natcirc_sim/loop.py"
    with open(path, "r") as f:
        content = f.read()

    # Add mu_coeff/mu_exp extraction from config
    content = content.replace(
        "    k_coeff = he_cfg['k_coeff']\n"
        "    k_exp = he_cfg['k_exp']",
        "    k_coeff = he_cfg['k_coeff']\n"
        "    k_exp = he_cfg['k_exp']\n"
        "    mu_coeff = he_cfg['mu_coeff']\n"
        "    mu_exp = he_cfg['mu_exp']"
    )

    # Update all vectorized viscosity calls to use power-law directly
    content = content.replace(
        "mu_f = np.vectorize(helium.viscosity)(T_f)",
        "mu_f = mu_coeff * T_f ** mu_exp"
    )

    with open(path, "w") as f:
        f.write(content)
    print("Fixed loop.py: viscosity calls use power-law parameters")


def fix_database_chimney_buoyancy():
    """Fix reactor.db: enable chimney buoyancy contribution."""
    db_path = "/app/reactor.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE solver_options SET value = 1 "
        "WHERE key = 'include_chimney_buoyancy'"
    )
    conn.commit()
    conn.close()
    print("Fixed reactor.db: include_chimney_buoyancy = 1")


if __name__ == "__main__":
    fix_fortran_ergun()
    fix_helium_viscosity()
    fix_loop_viscosity_calls()
    fix_database_chimney_buoyancy()
    print("\nAll fixes applied successfully.")
