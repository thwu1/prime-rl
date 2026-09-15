#!/usr/bin/env python3
"""MegaCorp Employee Directory API — internal service."""


import os
import sys
import hashlib
import sqlite3
import json
import unicodedata
import threading

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Runtime secret generation — values exist ONLY in this process's memory.
# Nothing below is deterministic or derivable from files on disk.
# ---------------------------------------------------------------------------
_rng = os.urandom
FLAG_HALF_A = _rng(8).hex()
FLAG_HALF_B = _rng(8).hex()
FULL_FLAG = "TBENCH{" + FLAG_HALF_A + FLAG_HALF_B + "}"
REDIS_KEY = "intcfg_" + _rng(4).hex()
REDIS_PASS = os.environ.pop("REDIS_AUTH_TOKEN", "")

if not REDIS_PASS:
    print("[!] REDIS_AUTH_TOKEN not set", file=sys.stderr)
    sys.exit(1)

# Write one-way SHA-256 hash for test verification only.
os.makedirs("/var/run", exist_ok=True)
with open("/var/run/.flag_verify", "w") as _fv:
    _fv.write(hashlib.sha256(FULL_FLAG.encode()).hexdigest())

# ---------------------------------------------------------------------------
# SQLite in-memory database (inaccessible from other processes)
# ---------------------------------------------------------------------------
_db_lock = threading.Lock()
_conn = sqlite3.connect(":memory:", check_same_thread=False)
_conn.row_factory = sqlite3.Row


def _init_db():
    c = _conn.cursor()
    c.execute(
        """CREATE TABLE employees (
            id INTEGER PRIMARY KEY, name TEXT, department TEXT,
            email TEXT, hire_date TEXT)"""
    )
    rows = [
        (1, "Alice Chen", "Engineering", "achen@megacorp.local", "2019-03-15"),
        (2, "Bob Martinez", "Engineering", "bmartinez@megacorp.local", "2020-01-10"),
        (3, "Carol White", "Marketing", "cwhite@megacorp.local", "2018-07-22"),
        (4, "David Kim", "Sales", "dkim@megacorp.local", "2021-05-01"),
        (5, "Eve Johnson", "Engineering", "ejohnson@megacorp.local", "2017-11-30"),
        (6, "Frank Brown", "HR", "fbrown@megacorp.local", "2019-09-14"),
        (7, "Grace Lee", "Marketing", "glee@megacorp.local", "2020-06-18"),
        (8, "Henry Davis", "Sales", "hdavis@megacorp.local", "2022-02-28"),
        (9, "Irene Wilson", "Engineering", "iwilson@megacorp.local", "2016-12-05"),
        (10, "Jack Taylor", "HR", "jtaylor@megacorp.local", "2021-08-20"),
        (11, "Karen Moore", "Engineering", "kmoore@megacorp.local", "2018-04-11"),
        (12, "Leo Garcia", "Marketing", "lgarcia@megacorp.local", "2023-01-09"),
        (13, "Mia Anderson", "Sales", "manderson@megacorp.local", "2019-10-25"),
        (14, "Nathan Clark", "Engineering", "nclark@megacorp.local", "2020-03-07"),
        (15, "Olivia Hall", "HR", "ohall@megacorp.local", "2022-07-16"),
    ]
    c.executemany("INSERT INTO employees VALUES (?,?,?,?,?)", rows)

    c.execute(
        "CREATE TABLE internal_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    configs = [
        ("flag_half", FLAG_HALF_A),
        ("cache_backend_key", REDIS_KEY),
        ("cache_backend_host", "127.0.0.1"),
        ("cache_backend_port", "6379"),
        ("cache_backend_auth", REDIS_PASS),
        ("app_version", "2.4.1"),
        ("last_security_audit", "2024-11-15"),
        ("deployment_env", "production"),
    ]
    c.executemany("INSERT INTO internal_config VALUES (?,?)", configs)
    _conn.commit()


_init_db()

# ---------------------------------------------------------------------------
# Redis — store second flag half alongside decoy data
# ---------------------------------------------------------------------------
try:
    import redis as _redis_lib

    _rc = _redis_lib.Redis(
        host="127.0.0.1", port=6379, password=REDIS_PASS, decode_responses=True
    )
    _rc.ping()
    _rc.set(REDIS_KEY, FLAG_HALF_B)
    # Decoy keys so KEYS * does not trivially reveal which holds the flag
    for _i in range(9):
        _rc.set(f"sess_{_rng(4).hex()}", _rng(16).hex())
    for _i in range(5):
        _rc.set(
            f"cache_{_rng(4).hex()}",
            json.dumps({"ts": _i, "d": _rng(8).hex()}),
        )
    _rc.set("app_meta", json.dumps({"ver": "2.4.1", "debug": False}))
    _rc.set("rate_limiter", "0")
    print("[+] Cache backend seeded")
except Exception as _e:
    print(f"[!] Cache backend error: {_e}", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# WAF — pattern-match on raw (pre-normalization) input only
# ---------------------------------------------------------------------------
_WAF_PATTERNS = [
    "'", '"', ";", "--", "/*", "*/", "#",
    "union", "select", "insert", "update", "delete", "drop",
    "where", "from", "and", "or", "order", "group", "having",
    "like", "between", "case", "when", "then", "else",
    "substr", "substring", "char", "ascii", "unicode",
    "sqlite", "master", "table", "column", "information_schema",
    "exec", "execute", "xp_", "sp_", "0x",
]


def _waf_check(raw):
    low = raw.lower()
    for p in _WAF_PATTERNS:
        if p in low:
            return False, p
    return True, None


def _nfkc(s):
    return unicodedata.normalize("NFKC", s)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify(status="ok")


@app.route("/api/docs")
def docs():
    return jsonify(
        name="MegaCorp Employee Directory API",
        version="2.4.1",
        note="All inputs undergo Unicode NFKC normalization for i18n support.",
        endpoints=[
            dict(path="/api/employees", method="GET",
                 description="List all employees"),
            dict(path="/api/employees/search", method="POST",
                 description="Search by name or department",
                 body={"query": "search term"},
                 content_type="application/json"),
        ],
    )


@app.route("/api/employees")
def list_employees():
    with _db_lock:
        c = _conn.cursor()
        c.execute("SELECT * FROM employees")
        data = [dict(r) for r in c.fetchall()]
    return jsonify(employees=data, count=len(data))


@app.route("/api/employees/search", methods=["POST"])
def search():
    body = request.get_json(silent=True)
    if not body or "query" not in body:
        return jsonify(error="Missing 'query' field"), 400

    raw = body["query"]
    ok, pat = _waf_check(raw)
    if not ok:
        return jsonify(error="WAF: blocked", detail=pat), 403

    # Unicode NFKC normalization AFTER WAF check — this is the vulnerability.
    norm = _nfkc(raw)

    sql = (
        f"SELECT * FROM employees "
        f"WHERE name LIKE '%{norm}%' OR department LIKE '%{norm}%'"
    )
    with _db_lock:
        try:
            cur = _conn.cursor()
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
            return jsonify(results=rows, count=len(rows))
        except Exception as e:
            return jsonify(error="DB error", detail=str(e)), 500


if __name__ == "__main__":
    print("[*] MegaCorp API starting on :8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
