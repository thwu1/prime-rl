#!/usr/bin/env python3
"""Create the device calibration SQLite database for the Hamiltonian estimation task."""
import sqlite3
import os

DB_PATH = "/app/device.db"
os.makedirs("/app", exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
""")

c.execute("""
CREATE TABLE hamiltonian_terms (
    term_index INTEGER PRIMARY KEY,
    pauli_string TEXT NOT NULL,
    coefficient REAL NOT NULL,
    ideal_expectation REAL NOT NULL
)
""")

c.execute("""
CREATE TABLE qubit_noise (
    qubit_index INTEGER PRIMARY KEY,
    depolarizing_rate REAL NOT NULL
)
""")

c.execute("""
CREATE TABLE scale_factors (
    factor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_value REAL NOT NULL UNIQUE
)
""")

c.execute("INSERT INTO metadata VALUES (?, ?)", (
    "hamiltonian_description",
    "4-qubit electronic structure Hamiltonian (Bravyi-Kitaev mapping) with 15 Pauli terms."
))
c.execute("INSERT INTO metadata VALUES (?, ?)", (
    "noise_model",
    "Exponential depolarizing noise model. The effective noise rate for a Pauli "
    "term equals the sum of per-qubit depolarizing rates across all qubits where "
    "the term acts non-trivially (operator is not I). At noise amplification "
    "factor lambda, the noisy expectation value is: "
    "E_i(lambda) = ideal_ev_i * exp(-r_i * lambda), where r_i is the effective "
    "noise rate. Single-shot measurement variance for eigenvalue +/-1 observables: "
    "Var_i(lambda) = 1 - E_i(lambda)^2. "
    "Pauli terms that commute qubitwise (at every qubit position, the operators "
    "are identical or at least one is the identity I) can be measured "
    "simultaneously from a single circuit execution; each shot yields one "
    "independent sample for every term in the group."
))

terms_data = [
    (0,  "ZIII",  0.3732, 0.50),
    (1,  "ZZII",  0.3732, 0.30),
    (2,  "IZII", -0.1377, -0.40),
    (3,  "IIZI",  0.1859, 0.60),
    (4,  "IZIZ", -0.1006, -0.20),
    (5,  "IZZZ",  0.1859, 0.15),
    (6,  "ZZZI",  0.0675, 0.25),
    (7,  "ZZZZ",  0.0675, 0.10),
    (8,  "ZIZI",  0.0630, -0.35),
    (9,  "ZIZZ",  0.0630, 0.18),
    (10, "XXXI",  0.0140, 0.05),
    (11, "XXXZ",  0.0050, 0.02),
    (12, "XYYI", -0.0089, -0.03),
    (13, "YXYI",  0.0140, 0.04),
    (14, "YXYZ",  0.0050, -0.01),
]

for idx, pauli, coeff, ideal_ev in terms_data:
    c.execute(
        "INSERT INTO hamiltonian_terms VALUES (?, ?, ?, ?)",
        (idx, pauli, coeff, ideal_ev),
    )

qubit_rates = [
    (0, 0.03),
    (1, 0.03),
    (2, 0.03),
    (3, 0.03),
]

for qi, rate in qubit_rates:
    c.execute("INSERT INTO qubit_noise VALUES (?, ?)", (qi, rate))

for sf in [1, 3, 5, 7, 9]:
    c.execute("INSERT INTO scale_factors (factor_value) VALUES (?)", (sf,))

conn.commit()
conn.close()
