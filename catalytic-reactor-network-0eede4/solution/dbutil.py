"""Database utility for loading species properties from SQLite."""
import sqlite3


def load_species_from_db(db_path, species_name):
    """Load adsorption constant K and reference concentration for a species.

    Returns dict with 'K' and 'C' keys.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT adsorption_K, ref_conc FROM species_properties WHERE name = ?",
        (species_name,)
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"Species '{species_name}' not found in database")
    return {"K": row[0], "C": row[1]}
