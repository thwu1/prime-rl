#!/usr/bin/env python3
"""

Fix a corrupted SQLite database, evaluate three candidate index strategies,
design an optimal strategy, and write a competitive evaluation report.
"""
import struct
import sqlite3
import json
import shutil
import tempfile
import os

DB_PATH = '/app/evidence.db'
STRATEGIES_DIR = '/app/candidate_strategies'
VALID_BTREE_TYPES = {0x02, 0x05, 0x0a, 0x0d}

QUERIES = [
    # Q1: Trades by specific trader in date range
    ("SELECT id, instrument_id, side, quantity, price FROM trades "
     "WHERE trader_id = 7 AND trade_date BETWEEN '2024-03-01' AND '2024-06-30'"),
    # Q2: Large trades for a specific instrument
    ("SELECT id, trader_id, side, quantity, trade_date FROM trades "
     "WHERE instrument_id = 5 AND price > 500.0"),
    # Q3: Critical unresolved flags with trade details
    ("SELECT compliance_flags.id, compliance_flags.flag_type, "
     "compliance_flags.severity, trades.price, trades.quantity "
     "FROM compliance_flags "
     "JOIN trades ON compliance_flags.trade_id = trades.id "
     "WHERE compliance_flags.severity = 'CRITICAL' "
     "AND compliance_flags.resolved = 0"),
    # Q4: Recent trades sorted by date
    ("SELECT id, trader_id, instrument_id, side, quantity, price FROM trades "
     "WHERE trade_date >= '2024-11-01' ORDER BY trade_date"),
    # Q5: Volume by trader for a specific instrument
    ("SELECT trader_id, side, SUM(quantity) AS total_qty, COUNT(*) AS num_trades "
     "FROM trades WHERE instrument_id = 15 "
     "GROUP BY trader_id, side ORDER BY total_qty DESC"),
]


def deduce_page_size(data):
    """Determine the correct page size by checking B-tree page type bytes at
    candidate page boundaries. The correct page size will produce valid B-tree
    page type bytes (0x02, 0x05, 0x0a, 0x0d) at the start of each page."""
    file_size = len(data)
    candidates = [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]

    best_size = 4096
    best_score = -1

    for ps in candidates:
        if file_size % ps != 0:
            continue

        num_pages = file_size // ps
        if num_pages < 2:
            continue

        score = 0
        checked = 0
        for page_num in range(2, min(num_pages + 1, 20)):
            offset = (page_num - 1) * ps
            page_type = data[offset]
            checked += 1
            if page_type in VALID_BTREE_TYPES:
                score += 1

        if checked > 0 and score > best_score:
            best_score = score
            best_size = ps

    return best_size


def fix_header(data):
    """Fix the 5 header-level corruptions."""
    correct_magic = b'SQLite format 3\x00'
    data[0:16] = correct_magic
    print("[1] Fixed magic header string")

    page_size = deduce_page_size(data)
    if page_size == 65536:
        struct.pack_into('>H', data, 16, 1)
    else:
        struct.pack_into('>H', data, 16, page_size)
    print(f"[2] Fixed page size to {page_size}")

    data[20] = 0
    print("[3] Fixed reserved bytes per page to 0")

    struct.pack_into('>I', data, 56, 1)
    print("[4] Fixed text encoding to 1 (UTF-8)")

    vvf = struct.unpack_from('>I', data, 92)[0]
    struct.pack_into('>I', data, 24, vvf)
    print(f"[5] Fixed change counter to {vvf} (matches version-valid-for)")

    return page_size


def fix_page_level(data, page_size):
    """Fix page-level B-tree corruption by finding and repairing invalid
    page type bytes for known table root pages."""
    with open(DB_PATH, 'wb') as f:
        f.write(data)

    conn = sqlite3.connect(DB_PATH)
    try:
        tables = conn.execute(
            "SELECT name, rootpage FROM sqlite_master WHERE type='table'"
        ).fetchall()
    except Exception as e:
        print(f"Warning: could not read sqlite_master: {e}")
        conn.close()
        return
    conn.close()

    with open(DB_PATH, 'rb') as f:
        data = bytearray(f.read())

    fixed_any = False
    for table_name, rootpage in tables:
        if rootpage == 1:
            offset = 100
        else:
            offset = (rootpage - 1) * page_size

        current_type = data[offset]
        if current_type not in VALID_BTREE_TYPES:
            print(f"[6] Found corrupted page type 0x{current_type:02x} at "
                  f"page {rootpage} (table '{table_name}')")

            for candidate_type in [0x05, 0x0d]:
                data[offset] = candidate_type
                with open(DB_PATH, 'wb') as f:
                    f.write(data)

                conn = sqlite3.connect(DB_PATH)
                try:
                    result = conn.execute('PRAGMA integrity_check').fetchone()[0]
                    count = conn.execute(
                        f'SELECT COUNT(*) FROM "{table_name}"'
                    ).fetchone()[0]
                    conn.close()

                    if result == 'ok' and count > 0:
                        print(f"    Fixed to 0x{candidate_type:02x} "
                              f"(integrity OK, {count} rows)")
                        fixed_any = True
                        break
                except Exception:
                    conn.close()
                    continue
            else:
                for candidate_type in [0x02, 0x0a]:
                    data[offset] = candidate_type
                    with open(DB_PATH, 'wb') as f:
                        f.write(data)

                    conn = sqlite3.connect(DB_PATH)
                    try:
                        result = conn.execute(
                            'PRAGMA integrity_check'
                        ).fetchone()[0]
                        conn.close()
                        if result == 'ok':
                            print(f"    Fixed to 0x{candidate_type:02x}")
                            fixed_any = True
                            break
                    except Exception:
                        conn.close()
                        continue

    if not fixed_any:
        print("[6] No page-level corruption found (or already fixed)")


def evaluate_strategy(strategy_file, db_path):
    """Evaluate a candidate index strategy by applying it to a temporary copy
    of the database and checking EXPLAIN QUERY PLAN for full table scans."""
    tmp = tempfile.mktemp(suffix='.db')
    shutil.copy(db_path, tmp)
    conn = sqlite3.connect(tmp)

    # Read and apply strategy SQL
    with open(strategy_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('--') and line.upper().startswith('CREATE'):
                conn.execute(line)
    conn.execute("ANALYZE")
    conn.commit()

    # Check each query for full table scans
    has_scans = False
    scan_queries = []
    for i, q in enumerate(QUERIES, 1):
        plan = conn.execute(f"EXPLAIN QUERY PLAN {q}").fetchall()
        query_has_scan = False
        for row in plan:
            detail = str(row[-1]).strip()
            if detail.startswith('SCAN') and \
               ('trades' in detail or 'compliance_flags' in detail):
                query_has_scan = True
                break
        if query_has_scan:
            has_scans = True
            scan_queries.append(i)

    conn.close()
    os.unlink(tmp)
    return has_scans, scan_queries


def evaluate_all_strategies():
    """Evaluate all three candidate strategies and return results."""
    strategies = {}

    assessments = {
        'strategy_a': ("Covering indexes that include all table columns eliminate "
                       "full scans on every target query, but waste significant "
                       "storage by duplicating data across 26 total index columns. "
                       "Each of the three trades indexes stores a near-complete copy "
                       "of the table."),
        'strategy_b': ("Indexes on trades(side) and compliance_flags(flag_type) are "
                       "ineffective because no target query filters on these columns "
                       "in its WHERE clause. The side column has only 2 distinct values "
                       "(BUY/SELL) making it poor for indexing even if it were used. "
                       "All 5 queries still require full table scans."),
        'strategy_c': ("Indexes are placed on the wrong tables entirely — instruments "
                       "and traders — while all target queries filter on the trades "
                       "and compliance_flags tables. These indexes provide zero benefit "
                       "for the compliance workload."),
    }

    for name in ['strategy_a', 'strategy_b', 'strategy_c']:
        path = os.path.join(STRATEGIES_DIR, f'{name}.sql')
        has_scans, scan_queries = evaluate_strategy(path, DB_PATH)
        strategies[name] = {
            'has_full_scans': has_scans,
            'full_scan_queries': scan_queries,
            'assessment': assessments[name],
        }
        print(f"  {name}: has_full_scans={has_scans}, scan_queries={scan_queries}")

    return strategies


def create_optimal_indexes():
    """Design and create an optimal set of indexes for the target compliance queries.

    Analysis of target queries:
    - Q1 filters on trader_id (equality) + trade_date (range) -> compound index
    - Q2 filters on instrument_id (equality) + price (range) -> instrument_id index
    - Q3 filters on compliance_flags severity+resolved -> compound index on flags
    - Q4 filters on trade_date (range) with ORDER BY -> trade_date index
    - Q5 filters on instrument_id (equality) -> reuses instrument_id index from Q2

    Optimal 4-index strategy (6 total columns vs Strategy A's 26):
    1. trades(trader_id, trade_date) - Q1: seek by trader, range on date
    2. trades(instrument_id)         - Q2, Q5: seek by instrument
    3. compliance_flags(severity, resolved) - Q3: seek by severity+resolved
    4. trades(trade_date)            - Q4: range seek + ordered output
    """
    optimal_indexes = [
        "CREATE INDEX idx_trades_trader_date ON trades(trader_id, trade_date)",
        "CREATE INDEX idx_trades_instrument ON trades(instrument_id)",
        "CREATE INDEX idx_flags_sev_res ON compliance_flags(severity, resolved)",
        "CREATE INDEX idx_trades_date ON trades(trade_date)",
    ]

    conn = sqlite3.connect(DB_PATH)
    for stmt in optimal_indexes:
        conn.execute(stmt)
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    print("[8] Created 4 indexes and ran ANALYZE for query optimization")
    return optimal_indexes


def verify():
    """Final verification of the repaired and optimized database."""
    conn = sqlite3.connect(DB_PATH)

    result = conn.execute('PRAGMA integrity_check').fetchone()[0]
    print(f"\nIntegrity check: {result}")
    assert result == 'ok', f"Integrity check failed: {result}"

    for table in ['traders', 'instruments', 'trades', 'compliance_flags']:
        count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(f"  {table}: {count} rows")

    idx_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
    ).fetchone()[0]
    print(f"\nUser-created indexes: {idx_count}")

    print("\n--- Query Plan Verification ---")
    for i, q in enumerate(QUERIES, 1):
        plan = conn.execute(f"EXPLAIN QUERY PLAN {q}").fetchall()
        print(f"Q{i}:")
        for row in plan:
            print(f"  {row[-1]}")

    conn.close()
    print("\nDatabase recovery, evaluation, and optimization complete.")


def main():
    print("=== SQLite Forensic Recovery and Index Strategy Evaluation ===\n")

    with open(DB_PATH, 'rb') as f:
        data = bytearray(f.read())

    print(f"File size: {len(data)} bytes\n")

    # Phase 1: Header Repair
    print("--- Phase 1: Header Repair ---")
    page_size = fix_header(data)

    with open(DB_PATH, 'wb') as f:
        f.write(data)

    # Phase 2: Page-Level Repair
    print("\n--- Phase 2: Page-Level Repair ---")
    fix_page_level(data, page_size)

    # Phase 3: Evaluate Candidate Strategies
    print("\n--- Phase 3: Candidate Strategy Evaluation ---")
    evaluation = evaluate_all_strategies()

    # Phase 4: Design Optimal Strategy
    print("\n--- Phase 4: Optimal Index Strategy Design ---")
    optimal_indexes = create_optimal_indexes()

    # Write evaluation report
    evaluation['designed_strategy'] = {
        'indexes': optimal_indexes,
        'rationale': (
            "Minimal compound indexes targeting each query's WHERE clause leading "
            "columns: trader_id+trade_date for Q1 (equality+range), instrument_id "
            "for Q2/Q5 (equality filter), severity+resolved for Q3 (compound "
            "equality on compliance_flags), trade_date for Q4 (range+ordering). "
            "Uses 6 total index columns vs Strategy A's 26, eliminating all full "
            "scans with minimal storage overhead. Strategy B fails because it indexes "
            "columns not present in any WHERE clause. Strategy C fails because it "
            "indexes entirely wrong tables."
        ),
    }

    with open('/app/analysis.json', 'w') as f:
        json.dump(evaluation, f, indent=2)
    print("\n[9] Wrote evaluation report to /app/analysis.json")

    # Phase 5: Verification
    print("\n--- Phase 5: Verification ---")
    verify()


if __name__ == '__main__':
    main()
