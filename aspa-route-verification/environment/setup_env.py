#!/usr/bin/env python3
"""Generate RPKI/ASPA Cache Integrity Audit environment data.

Creates:
  - SQLite database at /app/rpki_cache.db with normalized schema
  - PEM signing certificates at /app/rpki_certs/ (some expired)
"""
import json
import os
import sqlite3
import datetime

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

os.makedirs("/app/rpki_certs", exist_ok=True)

# ============================================================
# CERTIFICATE GENERATION
# ============================================================

EXPIRED_ASNS = {64512, 64522, 64531}


def make_cert(asn):
    """Generate a self-signed PEM certificate for an ASPA attestation."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"ASPA-AS{asn}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Example ISP RPKI CA"),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, str(asn)),
    ])

    valid = asn not in EXPIRED_ASNS
    if valid:
        nb = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        na = datetime.datetime(2027, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
    else:
        nb = datetime.datetime(2022, 3, 1, tzinfo=datetime.timezone.utc)
        na = datetime.datetime(2023, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nb)
        .not_valid_after(na)
        .sign(key, hashes.SHA256())
    )

    path = f"/app/rpki_certs/aspa_{asn}.pem"
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return path


# ============================================================
# SQLITE DATABASE
# ============================================================

db_path = "/app/rpki_cache.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.executescript("""
CREATE TABLE autonomous_systems (
    asn INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    region TEXT
);

CREATE TABLE transit_relationships (
    provider_asn INTEGER NOT NULL,
    customer_asn INTEGER NOT NULL,
    capacity_gbps REAL,
    established TEXT,
    PRIMARY KEY (provider_asn, customer_asn),
    FOREIGN KEY (provider_asn) REFERENCES autonomous_systems(asn),
    FOREIGN KEY (customer_asn) REFERENCES autonomous_systems(asn)
);

CREATE TABLE peering_sessions (
    asn_a INTEGER NOT NULL,
    asn_b INTEGER NOT NULL,
    ix_name TEXT,
    session_type TEXT DEFAULT 'settlement-free',
    PRIMARY KEY (asn_a, asn_b),
    FOREIGN KEY (asn_a) REFERENCES autonomous_systems(asn),
    FOREIGN KEY (asn_b) REFERENCES autonomous_systems(asn)
);

CREATE TABLE aspa_attestations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_asn INTEGER NOT NULL UNIQUE,
    signing_cert_path TEXT NOT NULL,
    published_at TEXT NOT NULL,
    FOREIGN KEY (customer_asn) REFERENCES autonomous_systems(asn)
);

CREATE TABLE aspa_provider_entries (
    attestation_id INTEGER NOT NULL,
    provider_asn INTEGER NOT NULL,
    PRIMARY KEY (attestation_id, provider_asn),
    FOREIGN KEY (attestation_id) REFERENCES aspa_attestations(id),
    FOREIGN KEY (provider_asn) REFERENCES autonomous_systems(asn)
);

CREATE TABLE rpki_roa_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_asn INTEGER NOT NULL,
    prefix TEXT NOT NULL,
    max_length INTEGER NOT NULL,
    trust_anchor TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    FOREIGN KEY (origin_asn) REFERENCES autonomous_systems(asn)
);

CREATE TABLE bgp_updates (
    update_id TEXT PRIMARY KEY,
    receiver_asn INTEGER NOT NULL,
    as_path TEXT NOT NULL,
    has_as_set INTEGER DEFAULT 0,
    collector TEXT,
    observed_at TEXT NOT NULL,
    FOREIGN KEY (receiver_asn) REFERENCES autonomous_systems(asn)
);
""")

# --- Autonomous Systems ---
nodes = [
    (64500, "Global Transit Alpha", "tier1", "global"),
    (64501, "Global Transit Beta", "tier1", "global"),
    (64510, "Regional Transit East", "tier2", "east"),
    (64511, "Regional Transit Central", "tier2", "central"),
    (64512, "Regional Transit West", "tier2", "west"),
    (64520, "Metro NE", "tier3", "northeast"),
    (64521, "Metro NC", "tier3", "northcentral"),
    (64522, "Metro CW", "tier3", "centralwest"),
    (64523, "Metro SW", "tier3", "southwest"),
    (64530, "Access NE-1", "tier4", "northeast"),
    (64531, "Access NC-1", "tier4", "northcentral"),
    (64532, "Access CW-1", "tier4", "centralwest"),
    (64533, "Access SW-1", "tier4", "southwest"),
    (64534, "Access SW-2", "tier4", "southwest"),
    (64540, "Enterprise NE-1", "stub", "northeast"),
    (64541, "Enterprise NC-1", "stub", "northcentral"),
    (64542, "Enterprise CW-1", "stub", "centralwest"),
    (64543, "Enterprise SW-1", "stub", "southwest"),
    (64544, "Enterprise SW-2", "stub", "southwest"),
    (64545, "Enterprise SW-3", "stub", "southwest"),
]
c.executemany("INSERT INTO autonomous_systems VALUES (?, ?, ?, ?)", nodes)

# --- Transit Relationships (provider -> customer) ---
transit = [
    (64500, 64510, 100.0, "2020-01-15"),
    (64500, 64511, 100.0, "2020-02-01"),
    (64501, 64511, 100.0, "2020-01-20"),
    (64501, 64512, 100.0, "2020-03-10"),
    (64510, 64520, 40.0, "2021-06-01"),
    (64510, 64521, 40.0, "2021-06-15"),
    (64511, 64521, 40.0, "2021-07-01"),
    (64511, 64522, 40.0, "2021-07-20"),
    (64512, 64522, 40.0, "2021-08-01"),
    (64512, 64523, 40.0, "2021-08-15"),
    (64520, 64530, 10.0, "2022-01-10"),
    (64520, 64531, 10.0, "2022-01-25"),
    (64521, 64531, 10.0, "2022-02-01"),
    (64521, 64532, 10.0, "2022-02-15"),
    (64522, 64532, 10.0, "2022-03-01"),
    (64522, 64533, 10.0, "2022-03-15"),
    (64523, 64533, 10.0, "2022-04-01"),
    (64523, 64534, 10.0, "2022-04-15"),
    (64530, 64540, 1.0, "2023-01-05"),
    (64531, 64541, 1.0, "2023-01-20"),
    (64532, 64542, 1.0, "2023-02-10"),
    (64533, 64543, 1.0, "2023-02-25"),
    (64534, 64544, 1.0, "2023-03-10"),
    (64534, 64545, 1.0, "2023-03-25"),
]
c.executemany("INSERT INTO transit_relationships VALUES (?, ?, ?, ?)", transit)

# --- Peering Sessions ---
peering = [
    (64500, 64501, "GlobalIX", "settlement-free"),
    (64510, 64511, "RegionalIX-East", "settlement-free"),
]
c.executemany("INSERT INTO peering_sessions VALUES (?, ?, ?, ?)", peering)

# --- ASPA Attestations + Provider Entries ---
# Three ASes (64512, 64522, 64531) have expired signing certs AND incorrect provider data.
aspa_deployed = {
    64500: [],
    64501: [],
    64510: [64500],
    64511: [64500, 64501],
    64512: [64501, 64500],      # WRONG: 64500 is NOT a transit provider of 64512
    64520: [64510],
    64521: [64510, 64511],
    64522: [64510, 64512],      # WRONG: 64510 is NOT a provider; 64511 is MISSING
    64523: [64512],
    64530: [64520],
    64531: [64520, 64521, 64511],  # WRONG: 64511 is NOT a provider of 64531
    64532: [64521, 64522],
    64533: [64522, 64523],
    64534: [64523],
}

for customer_asn, providers in aspa_deployed.items():
    cert_path = make_cert(customer_asn)
    c.execute(
        "INSERT INTO aspa_attestations (customer_asn, signing_cert_path, published_at) "
        "VALUES (?, ?, ?)",
        (customer_asn, cert_path, "2025-03-01T00:00:00Z")
    )
    att_id = c.lastrowid
    for prov in providers:
        c.execute(
            "INSERT INTO aspa_provider_entries (attestation_id, provider_asn) "
            "VALUES (?, ?)",
            (att_id, prov)
        )

# --- ROA Entries (noise — unrelated to ASPA audit) ---
roa_data = [
    (64500, "10.0.0.0/8", 24, "ARIN", "2027-01-01"),
    (64501, "172.16.0.0/12", 28, "ARIN", "2027-01-01"),
    (64510, "10.10.0.0/16", 24, "ARIN", "2026-06-01"),
    (64520, "10.10.10.0/24", 24, "ARIN", "2026-06-01"),
    (64530, "10.10.10.0/28", 28, "ARIN", "2026-06-01"),
    (64512, "192.168.0.0/16", 24, "RIPE", "2027-01-01"),
    (64523, "192.168.100.0/24", 24, "RIPE", "2027-01-01"),
    (64534, "192.168.100.128/25", 25, "RIPE", "2026-12-01"),
]
c.executemany(
    "INSERT INTO rpki_roa_entries (origin_asn, prefix, max_length, trust_anchor, valid_until) "
    "VALUES (?, ?, ?, ?, ?)", roa_data
)

# --- BGP Route Observations ---
routes = [
    ("OBS-001", 64521, [64540, 64530, 64520, 64510], 0, "collector-ne"),
    ("OBS-002", 64501, [64530, 64520, 64510, 64500], 0, "collector-core"),
    ("OBS-003", 64500, [64534, 64523, 64512, 64501], 0, "collector-core"),
    ("OBS-004", 64522, [64530, 64520, 64521, 64511], 0, "collector-cw"),
    ("OBS-005", 64521, [64533, 64522, 64511], 0, "collector-nc"),
    ("OBS-006", 64521, [64543, 64533, 64522, 64511], 0, "collector-nc"),
    ("OBS-007", 64511, [64530, 64520, 64510], 0, "collector-central"),
    ("OBS-008", 64522, [64534, 64523, 64512], 0, "collector-cw"),
    ("OBS-009", 64511, [64544, 64534, 64523, 64512, 64501], 0, "collector-central"),
    ("OBS-010", 64501, [64532, 64521, 64510, 64500], 0, "collector-core"),
    ("OBS-011", 64500, [64530, 64520, 64510, 64511, 64501], 0, "collector-core"),
    ("OBS-012", 64510, [64532, 64522, 64511], 0, "collector-east"),
    ("OBS-013", 64501, [64531, 64521, 64511, 64500], 0, "collector-core"),
    ("OBS-014", 64520, [64542, 64532, 64521, 64510], 0, "collector-ne"),
    ("OBS-015", 64520, [64533, 64523, 64521, 64510], 0, "collector-ne"),
    ("OBS-016", 64522, [64530, 64520, 64510, 64521, 64532], 0, "collector-cw"),
    ("OBS-017", 64520, [64534, 64523, 64512, 64501, 64511, 64521, 64531], 0, "collector-ne"),
    ("OBS-018", 64523, [64530, 64520, 64522, 64533], 0, "collector-sw"),
    ("OBS-019", 64522, [64544, 64534, 64523, 64533], 0, "collector-cw"),
    ("OBS-020", 64521, [64530, 64520, 64510, 64511, 64522, 64532], 0, "collector-nc"),
    ("OBS-021", 64521, [64540, 64530, 64531], 0, "collector-nc"),
    ("OBS-022", 64521, [64533, 64522, 64511, 64500, 64510, 64520, 64531], 0, "collector-nc"),
    ("OBS-023", 64521, [64534, 64523, 64512, 64501, 64511, 64522, 64532], 0, "collector-nc"),
    ("OBS-024", 64521, [64544, 64534, 64523, 64522, 64532], 0, "collector-nc"),
    ("OBS-025", 64510, [64530, 64520], 0, "collector-east"),
    ("OBS-026", 64520, [64510], 0, "collector-ne"),
    ("OBS-027", 64521, [64530, 64530, 64520, 64520, 64510], 0, "collector-nc"),
    ("OBS-028", 64500, [64534, 64534, 64523, 64523, 64512, 64512, 64501], 0, "collector-core"),
    ("OBS-029", 64521, [64530, 64520, 64510], 1, "collector-nc"),
    ("OBS-030", 64521, [64530, 64531], 1, "collector-nc"),
]

for update_id, receiver, path, has_as_set, collector in routes:
    c.execute(
        "INSERT INTO bgp_updates VALUES (?, ?, ?, ?, ?, ?)",
        (update_id, receiver, json.dumps(path), has_as_set, collector,
         "2025-03-14T12:00:00Z")
    )

conn.commit()

# Verify counts
row_counts = {}
for table in ["autonomous_systems", "transit_relationships", "peering_sessions",
              "aspa_attestations", "aspa_provider_entries", "bgp_updates"]:
    c.execute(f"SELECT COUNT(*) FROM {table}")
    row_counts[table] = c.fetchone()[0]

conn.close()

print(f"Database created: {db_path}")
print(f"Row counts: {json.dumps(row_counts)}")
print(f"Certificates generated in /app/rpki_certs/")
