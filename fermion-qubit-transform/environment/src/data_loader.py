"""Load molecular system data from SQLite database."""
import sqlite3
import numpy as np
import yaml


def load_config(path="/app/config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def list_systems(db_path):
    """List all molecular systems in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, description, n_spatial_orbitals, n_electrons "
        "FROM molecular_systems"
    )
    systems = cursor.fetchall()
    conn.close()
    return systems


def load_system(db_path, system_name, convention="physicist"):
    """Load molecular integral data for a named system.

    Args:
        db_path: Path to SQLite database
        system_name: Name of the molecular system
        convention: Integral convention for two-body terms.
            'physicist': <pq|rs> stored directly as g[p,q,r,s]
            'chemist':   (pq|rs) = <pr|qs>, so we transpose to g[p,r,q,s]
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, n_spatial_orbitals, n_electrons, nuclear_repulsion "
        "FROM molecular_systems WHERE name = ?",
        (system_name,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"System '{system_name}' not found in database")

    sys_id, n_so, n_elec, nuc_rep = row

    # One-body integrals (spatial orbital basis)
    h = np.zeros((n_so, n_so))
    cursor.execute(
        "SELECT p, q, value FROM one_body WHERE system_id = ?", (sys_id,)
    )
    for p, q, v in cursor.fetchall():
        h[p, q] = v

    # Two-body integrals (spatial orbital basis)
    g = np.zeros((n_so, n_so, n_so, n_so))
    cursor.execute(
        "SELECT p, q, r, s, value FROM two_body WHERE system_id = ?", (sys_id,)
    )
    for p, q, r, s, v in cursor.fetchall():
        if convention == "chemist":
            # Interpret stored values as chemist (pq|rs) and rearrange
            g[p, r, q, s] = v
        else:
            g[p, q, r, s] = v

    conn.close()

    return {
        "name": system_name,
        "n_spatial_orbitals": n_so,
        "n_electrons": n_elec,
        "nuclear_repulsion_energy": nuc_rep,
        "one_body_integrals": h,
        "two_body_integrals": g,
    }


def to_spin_orbital_basis(data):
    """Convert spatial orbital integrals to spin-orbital basis.

    Spin-orbital ordering: site0-alpha, site0-beta, site1-alpha, ...
    """
    n_so = data["n_spatial_orbitals"]
    n_spin = 2 * n_so
    h_spatial = data["one_body_integrals"]
    g_spatial = data["two_body_integrals"]

    h_spin = np.zeros((n_spin, n_spin))
    g_spin = np.zeros((n_spin, n_spin, n_spin, n_spin))

    for p in range(n_spin):
        for q in range(n_spin):
            if p % 2 == q % 2:
                h_spin[p, q] = h_spatial[p // 2, q // 2]

    for p in range(n_spin):
        for q in range(n_spin):
            for r in range(n_spin):
                for s in range(n_spin):
                    if p % 2 == r % 2 and q % 2 == s % 2:
                        g_spin[p, q, r, s] = g_spatial[
                            p // 2, q // 2, r // 2, s // 2
                        ]

    return h_spin, g_spin, n_spin
