#!/usr/bin/env python3
"""Generate deterministic patent citation data with embedded quality issues."""
import duckdb
import random
import os
from datetime import date, timedelta

random.seed(42)

DB_PATH = "/app/patents.duckdb"

COUNTRIES = ["US", "EP", "JP", "CN", "KR", "DE"]
KIND_CODES = {
    "US": ["B1", "B2"], "EP": ["B1"], "JP": ["B2"],
    "CN": ["B"], "KR": ["B1"], "DE": ["B3", "B4"],
}

IPC4_CLASSES = [
    "A01B", "A23L", "A61B", "A61K", "A61P",
    "B01D", "B01J", "B29C", "B60W", "B65D",
    "C07C", "C07D", "C07K", "C08G", "C12N",
    "D01F", "D21H",
    "E04B", "E21B",
    "F01D", "F16H", "F24F",
    "G01N", "G02B", "G06F", "G06N", "G06Q", "G06T", "G16H",
    "H01L", "H01M", "H04B", "H04L", "H04N", "H04W",
]

ASSIGNEES = [
    "TechCorp International", "BioPharm Solutions", "Advanced Materials Inc",
    "Digital Systems Ltd", "NanoTech Research", "GreenEnergy Corp",
    "Semiconductor Dynamics", "Quantum Computing Labs", "Medical Devices Plus",
    "Automotive Innovation", "ChemProcess Industries", "Telecom Networks Inc",
    "Optical Systems Corp", "Robotics Engineering", "AI Research Institute",
    "Battery Tech Solutions", "Wireless Systems Ltd", "Polymer Sciences Inc",
    "Aerospace Technologies", "Smart Grid Solutions", "Data Analytics Corp",
    "Cloud Infrastructure Inc", "Precision Manufacturing", "Sensor Technologies",
    "Clean Water Systems", "Gene Therapy Labs", "Display Technologies",
    "Security Systems Inc", "IoT Devices Corp", "Renewable Energy Research",
]

ASSIGNEE_WEIGHTS = [5, 5, 4, 4, 4, 3, 3, 3, 3, 3,
                    2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
                    1, 1, 1, 1, 1, 1, 1, 1, 1, 1]

CITATION_CATEGORIES = ["SEA", "CH2", "DOC", "APP", "CIT"]
IPC_SUBGROUPS = ["00", "02", "04", "06", "08", "10", "12", "14", "16", "18", "20"]


def random_date(start_year, end_year):
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    days = (end - start).days
    return start + timedelta(days=random.randint(0, days))


def pick_assignee():
    return random.choices(ASSIGNEES, weights=ASSIGNEE_WEIGHTS, k=1)[0]


def pick_country():
    return random.choices(COUNTRIES, weights=[35, 15, 15, 15, 10, 10], k=1)[0]


def generate():
    os.makedirs("/app", exist_ok=True)
    con = duckdb.connect(DB_PATH)

    con.execute("""
        CREATE TABLE publications (
            publication_number VARCHAR PRIMARY KEY,
            country_code VARCHAR NOT NULL,
            kind_code VARCHAR NOT NULL,
            application_number VARCHAR,
            filing_date DATE NOT NULL,
            grant_date DATE,
            title VARCHAR,
            abstract VARCHAR,
            assignee_harmonized VARCHAR,
            family_id INTEGER NOT NULL
        )
    """)

    con.execute("""
        CREATE TABLE citations (
            citing_pub VARCHAR NOT NULL,
            cited_pub VARCHAR NOT NULL,
            category VARCHAR
        )
    """)

    con.execute("""
        CREATE TABLE ipc_codes (
            publication_number VARCHAR NOT NULL,
            code VARCHAR NOT NULL,
            sequence_num INTEGER NOT NULL
        )
    """)

    con.execute("""
        CREATE TABLE cpc_codes (
            publication_number VARCHAR NOT NULL,
            code VARCHAR NOT NULL,
            section VARCHAR NOT NULL,
            class_code VARCHAR NOT NULL,
            subclass VARCHAR NOT NULL,
            group_code VARCHAR NOT NULL,
            sequence_num INTEGER NOT NULL
        )
    """)

    patents = []
    pid = 1000000

    # Phase 1: Multi-national families (50 families, 3-5 members each)
    for fam_id in range(1, 51):
        n_members = random.randint(3, 5)
        n_countries = min(random.randint(3, min(n_members, 6)), len(COUNTRIES))
        countries = random.sample(COUNTRIES, n_countries)
        while len(countries) < n_members:
            countries.append(random.choice(COUNTRIES))
        random.shuffle(countries)
        assignee = pick_assignee()
        base_filing = random_date(2005, 2016)
        for country in countries:
            pid += 1
            kind = random.choice(KIND_CODES[country])
            fd = base_filing + timedelta(days=random.randint(0, 365))
            gd = fd + timedelta(days=random.randint(400, 1500))
            patents.append({
                "pn": f"{country}-{pid}-{kind}",
                "cc": country, "kc": kind,
                "an": f"{country}-APP-{pid}",
                "fd": fd, "gd": gd,
                "title": f"Method and apparatus for system {pid}",
                "abstract": f"Disclosed is a technique related to field {pid}",
                "assignee": assignee,
                "fam": fam_id,
            })

    # Phase 2: Medium families (120 families, 2-3 members)
    for fam_id in range(51, 171):
        n_members = random.randint(2, 3)
        assignee = pick_assignee()
        base_filing = random_date(2006, 2018)
        for _ in range(n_members):
            pid += 1
            country = pick_country()
            kind = random.choice(KIND_CODES[country])
            fd = base_filing + timedelta(days=random.randint(0, 180))
            gd = fd + timedelta(days=random.randint(400, 1500))
            patents.append({
                "pn": f"{country}-{pid}-{kind}",
                "cc": country, "kc": kind,
                "an": f"{country}-APP-{pid}",
                "fd": fd, "gd": gd,
                "title": f"Improved method for processing in domain {pid}",
                "abstract": f"An improved technique for application {pid}",
                "assignee": assignee,
                "fam": fam_id,
            })

    # Phase 3: Single-member families
    target_total = 800
    current = len(patents)
    remaining = target_total - current
    for i in range(remaining):
        fam_id = 171 + i
        pid += 1
        country = pick_country()
        kind = random.choice(KIND_CODES[country])
        fd = random_date(2005, 2020)
        gd = fd + timedelta(days=random.randint(400, 1500))
        assignee = pick_assignee()
        patents.append({
            "pn": f"{country}-{pid}-{kind}",
            "cc": country, "kc": kind,
            "an": f"{country}-APP-{pid}",
            "fd": fd, "gd": gd,
            "title": f"System and method for operation {pid}",
            "abstract": f"A system relating to procedure {pid}",
            "assignee": assignee,
            "fam": fam_id,
        })

    # Sort by filing date for deterministic citation generation
    patents.sort(key=lambda p: (p["fd"], p["pn"]))

    # Insert patents
    for p in patents:
        con.execute(
            "INSERT INTO publications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [p["pn"], p["cc"], p["kc"], p["an"],
             p["fd"].isoformat(), p["gd"].isoformat(),
             p["title"], p["abstract"], p["assignee"], p["fam"]]
        )

    # Generate IPC codes (2-5 per patent, distinct 4-digit classes)
    ipc_rows = []
    for p in patents:
        n_codes = random.choices([2, 3, 4, 5], weights=[20, 40, 30, 10], k=1)[0]
        used = set()
        for seq in range(n_codes):
            ipc4 = random.choice(IPC4_CLASSES)
            attempts = 0
            while ipc4 in used and attempts < 50:
                ipc4 = random.choice(IPC4_CLASSES)
                attempts += 1
            if ipc4 in used:
                continue
            used.add(ipc4)
            subnum = random.randint(1, 40)
            subsuf = random.choice(IPC_SUBGROUPS)
            full_code = f"{ipc4}{subnum}/{subsuf}"
            ipc_rows.append((p["pn"], full_code, seq))

    con.executemany("INSERT INTO ipc_codes VALUES (?, ?, ?)", ipc_rows)

    # Generate CPC codes (2-5 per patent, distinct 4-digit groups)
    cpc_rows = []
    for p in patents:
        n_codes = random.choices([2, 3, 4, 5], weights=[20, 40, 30, 10], k=1)[0]
        used = set()
        for seq in range(n_codes):
            ipc4 = random.choice(IPC4_CLASSES)
            attempts = 0
            while ipc4 in used and attempts < 50:
                ipc4 = random.choice(IPC4_CLASSES)
                attempts += 1
            if ipc4 in used:
                continue
            used.add(ipc4)
            subnum = random.randint(1, 40)
            subsuf = random.choice(IPC_SUBGROUPS[:6])
            full_code = f"{ipc4}{subnum}/{subsuf}"
            section = ipc4[0]
            class_code = ipc4[:3]
            subclass = ipc4[:4]
            cpc_rows.append((p["pn"], full_code, section, class_code, subclass, ipc4, seq))

    con.executemany("INSERT INTO cpc_codes VALUES (?, ?, ?, ?, ?, ?, ?)", cpc_rows)

    # Generate normal citations (0-12 per patent, only to earlier-filed patents)
    citation_rows = []
    pn_list = [p["pn"] for p in patents]
    fd_list = [p["fd"] for p in patents]

    for i, p in enumerate(patents):
        candidates = [j for j in range(i) if fd_list[j] < p["fd"]]
        if not candidates:
            continue
        n_cite = random.choices(
            range(13),
            weights=[5, 5, 8, 12, 15, 15, 12, 10, 7, 5, 3, 2, 1],
            k=1
        )[0]
        n_cite = min(n_cite, len(candidates))
        if n_cite == 0:
            continue
        cited_indices = random.sample(candidates, n_cite)
        for j in cited_indices:
            cat = random.choice(CITATION_CATEGORIES)
            citation_rows.append((p["pn"], pn_list[j], cat))

    # ========== INJECT DATA QUALITY ISSUES ==========
    normal_citation_count = len(citation_rows)

    # Issue 1: Self-referencing citations (a publication cites itself)
    self_ref_indices = random.sample(range(len(patents)), 15)
    for idx in self_ref_indices:
        cat = random.choice(CITATION_CATEGORIES)
        citation_rows.append((pn_list[idx], pn_list[idx], cat))

    # Issue 2: Duplicate citation edges (same citing-cited pair appears again)
    dup_indices = random.sample(range(normal_citation_count), 25)
    for idx in dup_indices:
        row = citation_rows[idx]
        cat = random.choice(CITATION_CATEGORIES)
        citation_rows.append((row[0], row[1], cat))

    # Issue 3: Orphan citations (cited_pub not in publications table)
    for i in range(20):
        citing = random.choice(pn_list)
        cat = random.choice(CITATION_CATEGORIES)
        citation_rows.append((citing, f"ORPHAN-{9999990 + i}-B1", cat))

    # Insert ALL citations (normal + injected issues)
    con.executemany("INSERT INTO citations VALUES (?, ?, ?)", citation_rows)

    # Issue 4: Inverted dates (grant_date set before filing_date)
    inv_indices = random.sample(range(len(patents)), 12)
    for idx in inv_indices:
        p = patents[idx]
        new_gd = p["fd"] - timedelta(days=random.randint(30, 365))
        con.execute(
            "UPDATE publications SET grant_date = ? WHERE publication_number = ?",
            [new_gd.isoformat(), p["pn"]]
        )

    # Issue 5: Null assignees
    null_indices = random.sample(range(len(patents)), 10)
    for idx in null_indices:
        con.execute(
            "UPDATE publications SET assignee_harmonized = NULL WHERE publication_number = ?",
            [patents[idx]["pn"]]
        )

    # Create indexes for query performance
    con.execute("CREATE INDEX idx_pub_cc_kc ON publications(country_code, kind_code)")
    con.execute("CREATE INDEX idx_pub_family ON publications(family_id)")
    con.execute("CREATE INDEX idx_pub_assignee ON publications(assignee_harmonized)")
    con.execute("CREATE INDEX idx_cite_citing ON citations(citing_pub)")
    con.execute("CREATE INDEX idx_cite_cited ON citations(cited_pub)")
    con.execute("CREATE INDEX idx_ipc_pub ON ipc_codes(publication_number)")
    con.execute("CREATE INDEX idx_cpc_pub ON cpc_codes(publication_number)")

    stats = {
        "publications": con.execute("SELECT COUNT(*) FROM publications").fetchone()[0],
        "citations": con.execute("SELECT COUNT(*) FROM citations").fetchone()[0],
        "ipc_codes": con.execute("SELECT COUNT(*) FROM ipc_codes").fetchone()[0],
        "cpc_codes": con.execute("SELECT COUNT(*) FROM cpc_codes").fetchone()[0],
    }
    for k, v in stats.items():
        print(f"{k}: {v}")

    con.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    generate()
