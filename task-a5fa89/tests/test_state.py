"""

Tests for SQLite forensic recovery, candidate strategy evaluation, and index design task.
Verifies database recovery (integrity + data), competitive evaluation (analysis.json),
and query optimization (indexes + plans).
"""
import sqlite3
import struct
import random
import os
import re
import json
import pytest

DB_PATH = '/app/evidence.db'
PAGE_SIZE = 8192
SEED = 42

# Target queries that must use indexed lookups on large tables
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


def generate_data():
    """Generate deterministic trading compliance data. Must match setup_db.py exactly."""
    random.seed(SEED)

    desks = ['Equity', 'FixedIncome', 'Derivatives', 'Commodities', 'FX']
    traders = []
    for i in range(1, 51):
        risk_limit = round(1000000.0 + random.random() * 99000000.0, 2)
        traders.append((i, f'Trader_{i:03d}', desks[i % 5], risk_limit))

    tickers = [
        'AAPL', 'GOOGL', 'MSFT', 'AMZN', 'META',
        'JPM', 'BAC', 'GS', 'MS', 'WFC',
        'UST10Y', 'UST2Y', 'UST5Y', 'BUND10', 'GILT10',
        'SPX_C4500', 'SPX_P4000', 'VIX_C20', 'NDX_C15000', 'RUT_P2000',
        'ES_FUT', 'NQ_FUT', 'CL_FUT', 'GC_FUT', 'SI_FUT',
        'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD'
    ]
    asset_classes = (['Equity'] * 10 + ['Bond'] * 5 + ['Option'] * 5 +
                     ['Future'] * 5 + ['FX'] * 5)
    instruments = []
    for i in range(30):
        ref_price = round(10.0 + random.random() * 990.0, 4)
        instruments.append((i + 1, tickers[i], f'{tickers[i]}_Security',
                           asset_classes[i], ref_price))

    trades = []
    for i in range(1, 2001):
        trader_id = random.randint(1, 50)
        instrument_id = random.randint(1, 30)
        side = 'BUY' if random.random() < 0.5 else 'SELL'
        quantity = random.randint(100, 10000)
        price = round(random.uniform(10.0, 1000.0), 4)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        trade_date = f'2024-{month:02d}-{day:02d}'
        trades.append((i, trader_id, instrument_id, side, quantity, price,
                       trade_date))

    flag_types = ['WASH_TRADE', 'FRONT_RUNNING', 'SPOOFING',
                  'INSIDER', 'CONCENTRATION', 'FAT_FINGER']
    flags = []
    for i in range(1, 301):
        trade_id = random.randint(1, 2000)
        ft = flag_types[random.randint(0, 5)]
        roll = random.random()
        if roll < 0.4:
            sev = 'LOW'
        elif roll < 0.7:
            sev = 'MEDIUM'
        elif roll < 0.9:
            sev = 'HIGH'
        else:
            sev = 'CRITICAL'
        desc_len = 200 + random.randint(0, 300)
        desc = f'Flag {ft} on trade {trade_id}: ' + 'A' * desc_len
        resolved = 1 if random.random() < 0.6 else 0
        flags.append((i, trade_id, ft, sev, desc, resolved))

    return traders, instruments, trades, flags


def create_reference_db(db_path):
    """Create a clean reference database with deterministic data."""
    conn = sqlite3.connect(db_path)
    conn.execute(f'PRAGMA page_size = {PAGE_SIZE}')
    conn.execute('PRAGMA journal_mode = DELETE')
    c = conn.cursor()

    c.execute('''CREATE TABLE traders (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        desk TEXT NOT NULL,
        risk_limit REAL NOT NULL
    )''')

    c.execute('''CREATE TABLE instruments (
        id INTEGER PRIMARY KEY,
        ticker TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        asset_class TEXT NOT NULL,
        reference_price REAL NOT NULL
    )''')

    c.execute('''CREATE TABLE trades (
        id INTEGER PRIMARY KEY,
        trader_id INTEGER NOT NULL REFERENCES traders(id),
        instrument_id INTEGER NOT NULL REFERENCES instruments(id),
        side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        trade_date TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE compliance_flags (
        id INTEGER PRIMARY KEY,
        trade_id INTEGER NOT NULL REFERENCES trades(id),
        flag_type TEXT NOT NULL,
        severity TEXT NOT NULL CHECK(severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
        description TEXT NOT NULL,
        resolved INTEGER NOT NULL DEFAULT 0
    )''')

    traders, instruments, trades, flags = generate_data()

    c.executemany('INSERT INTO traders VALUES (?,?,?,?)', traders)
    c.executemany('INSERT INTO instruments VALUES (?,?,?,?,?)', instruments)
    c.executemany('INSERT INTO trades VALUES (?,?,?,?,?,?,?)', trades)
    c.executemany('INSERT INTO compliance_flags VALUES (?,?,?,?,?,?)', flags)

    conn.commit()
    conn.close()


@pytest.fixture(scope='session')
def ref_db(tmp_path_factory):
    """Create reference database once per test session."""
    ref_path = str(tmp_path_factory.mktemp('ref') / 'reference.db')
    create_reference_db(ref_path)
    return ref_path


class TestFileExists:
    def test_evidence_db_exists(self):
        assert os.path.exists(DB_PATH), \
            f"Database file not found at {DB_PATH}"

    def test_file_not_empty(self):
        assert os.path.getsize(DB_PATH) > 100, \
            "Database file is too small"


class TestHeaderRecovery:
    """Verify the SQLite 100-byte header has been correctly repaired."""

    def test_magic_header_string(self):
        with open(DB_PATH, 'rb') as f:
            magic = f.read(16)
        assert magic == b'SQLite format 3\x00', \
            f"Magic header incorrect: {magic!r}"

    def test_page_size_field(self):
        with open(DB_PATH, 'rb') as f:
            f.seek(16)
            ps = struct.unpack('>H', f.read(2))[0]
        if ps == 1:
            ps = 65536
        assert ps == PAGE_SIZE, \
            f"Page size should be {PAGE_SIZE}, got {ps}"

    def test_reserved_bytes_per_page(self):
        with open(DB_PATH, 'rb') as f:
            f.seek(20)
            reserved = f.read(1)[0]
        assert reserved == 0, \
            f"Reserved bytes per page should be 0, got {reserved}"

    def test_text_encoding_valid(self):
        with open(DB_PATH, 'rb') as f:
            f.seek(56)
            enc = struct.unpack('>I', f.read(4))[0]
        assert enc == 1, \
            f"Text encoding should be 1 (UTF-8), got {enc}"

    def test_file_size_page_aligned(self):
        file_size = os.path.getsize(DB_PATH)
        assert file_size % PAGE_SIZE == 0, \
            f"File size {file_size} not aligned to page size {PAGE_SIZE}"


class TestDatabaseIntegrity:
    """Verify the database passes SQLite built-in checks."""

    def test_integrity_check(self):
        conn = sqlite3.connect(DB_PATH)
        result = conn.execute('PRAGMA integrity_check').fetchone()[0]
        conn.close()
        assert result == 'ok', \
            f"PRAGMA integrity_check failed: {result}"

    def test_all_tables_exist(self):
        conn = sqlite3.connect(DB_PATH)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        expected = {'traders', 'instruments', 'trades', 'compliance_flags'}
        assert expected.issubset(tables), \
            f"Expected tables {expected}, found {tables}"

    def test_schema_readable(self):
        conn = sqlite3.connect(DB_PATH)
        schemas = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        assert len(schemas) >= 4, \
            f"Expected at least 4 table schemas, got {len(schemas)}"
        for (sql,) in schemas:
            assert sql is not None and len(sql) > 0


class TestDataRecovery:
    """Verify all data has been correctly recovered by comparing with reference."""

    def test_trader_count(self, ref_db):
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_n = rec.execute('SELECT COUNT(*) FROM traders').fetchone()[0]
        ref_n = ref.execute('SELECT COUNT(*) FROM traders').fetchone()[0]
        rec.close()
        ref.close()
        assert rec_n == ref_n, \
            f"traders count: got {rec_n}, expected {ref_n}"

    def test_instrument_count(self, ref_db):
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_n = rec.execute('SELECT COUNT(*) FROM instruments').fetchone()[0]
        ref_n = ref.execute('SELECT COUNT(*) FROM instruments').fetchone()[0]
        rec.close()
        ref.close()
        assert rec_n == ref_n, \
            f"instruments count: got {rec_n}, expected {ref_n}"

    def test_trade_count(self, ref_db):
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_n = rec.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
        ref_n = ref.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
        rec.close()
        ref.close()
        assert rec_n == ref_n, \
            f"trades count: got {rec_n}, expected {ref_n}"

    def test_compliance_flag_count(self, ref_db):
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_n = rec.execute('SELECT COUNT(*) FROM compliance_flags').fetchone()[0]
        ref_n = ref.execute('SELECT COUNT(*) FROM compliance_flags').fetchone()[0]
        rec.close()
        ref.close()
        assert rec_n == ref_n, \
            f"compliance_flags count: got {rec_n}, expected {ref_n}"

    def test_total_trade_volume(self, ref_db):
        query = 'SELECT ROUND(SUM(CAST(quantity AS REAL) * price), 2) FROM trades'
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchone()[0]
        ref_val = ref.execute(query).fetchone()[0]
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            f"Total trade volume: got {rec_val}, expected {ref_val}"

    def test_risk_limit_sum(self, ref_db):
        query = 'SELECT ROUND(SUM(risk_limit), 2) FROM traders'
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchone()[0]
        ref_val = ref.execute(query).fetchone()[0]
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            f"Risk limit sum: got {rec_val}, expected {ref_val}"

    def test_critical_unresolved_flags(self, ref_db):
        query = ("SELECT COUNT(*) FROM compliance_flags "
                 "WHERE severity='CRITICAL' AND resolved=0")
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchone()[0]
        ref_val = ref.execute(query).fetchone()[0]
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            f"Critical unresolved flags: got {rec_val}, expected {ref_val}"

    def test_trade_side_distribution(self, ref_db):
        query = 'SELECT side, COUNT(*) FROM trades GROUP BY side ORDER BY side'
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchall()
        ref_val = ref.execute(query).fetchall()
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            f"Trade side distribution: got {rec_val}, expected {ref_val}"

    def test_all_trader_names(self, ref_db):
        query = ("SELECT GROUP_CONCAT(name, ',') FROM "
                 "(SELECT name FROM traders ORDER BY id)")
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchone()[0]
        ref_val = ref.execute(query).fetchone()[0]
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            "Trader name list mismatch"

    def test_all_tickers(self, ref_db):
        query = ("SELECT GROUP_CONCAT(ticker, ',') FROM "
                 "(SELECT ticker FROM instruments ORDER BY id)")
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchone()[0]
        ref_val = ref.execute(query).fetchone()[0]
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            "Ticker list mismatch"

    def test_flag_type_distribution(self, ref_db):
        query = ('SELECT flag_type, COUNT(*) FROM compliance_flags '
                 'GROUP BY flag_type ORDER BY flag_type')
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchall()
        ref_val = ref.execute(query).fetchall()
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            f"Flag type distribution: got {rec_val}, expected {ref_val}"

    def test_specific_trade_record(self, ref_db):
        """Verify a specific trade record survived recovery intact."""
        query = ('SELECT trader_id, instrument_id, side, quantity, price '
                 'FROM trades WHERE id = 1000')
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchone()
        ref_val = ref.execute(query).fetchone()
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            f"Trade #1000: got {rec_val}, expected {ref_val}"

    def test_asset_class_volume(self, ref_db):
        """Verify aggregate volume by asset class matches reference."""
        query = ('SELECT i.asset_class, ROUND(SUM(t.quantity * t.price), 2) '
                 'FROM trades t JOIN instruments i ON t.instrument_id = i.id '
                 'GROUP BY i.asset_class ORDER BY i.asset_class')
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_val = rec.execute(query).fetchall()
        ref_val = ref.execute(query).fetchall()
        rec.close()
        ref.close()
        assert rec_val == ref_val, \
            f"Asset class volume mismatch"


class TestQueryOptimization:
    """Verify the indexing strategy eliminates full table scans on large tables."""

    def test_index_count_within_limit(self):
        """No more than 4 user-created indexes allowed."""
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='index' AND sql IS NOT NULL"
        ).fetchone()[0]
        conn.close()
        assert count <= 4, \
            f"Too many user-created indexes: {count} (max 4 allowed)"

    def test_at_least_one_index_created(self):
        """At least one index must be created for optimization."""
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='index' AND sql IS NOT NULL"
        ).fetchone()[0]
        conn.close()
        assert count >= 1, \
            "No user-created indexes found — optimization required"

    @pytest.mark.parametrize("qi", range(len(QUERIES)))
    def test_no_full_scan_on_large_tables(self, qi):
        """Each target query must use indexed access on trades and compliance_flags."""
        conn = sqlite3.connect(DB_PATH)
        conn.execute("ANALYZE")
        plan = conn.execute(f"EXPLAIN QUERY PLAN {QUERIES[qi]}").fetchall()
        conn.close()
        for row in plan:
            detail = str(row[-1]).strip()
            if detail.startswith('SCAN'):
                assert 'trades' not in detail, \
                    f"Q{qi+1} performs full scan on trades: {detail}"
                assert 'compliance_flags' not in detail, \
                    f"Q{qi+1} performs full scan on compliance_flags: {detail}"

    @pytest.mark.parametrize("qi", range(len(QUERIES)))
    def test_query_results_match_reference(self, qi, ref_db):
        """Query results on recovered DB must match the reference."""
        rec = sqlite3.connect(DB_PATH)
        ref = sqlite3.connect(ref_db)
        rec_rows = sorted(rec.execute(QUERIES[qi]).fetchall())
        ref_rows = sorted(ref.execute(QUERIES[qi]).fetchall())
        rec.close()
        ref.close()
        assert rec_rows == ref_rows, \
            f"Q{qi+1}: Result set differs from reference ({len(rec_rows)} vs {len(ref_rows)} rows)"


class TestStrategyEvaluation:
    """Verify the competitive evaluation of candidate index strategies in analysis.json."""

    def test_analysis_json_exists(self):
        assert os.path.exists('/app/analysis.json'), \
            "Evaluation report not found at /app/analysis.json"

    def test_analysis_json_valid(self):
        with open('/app/analysis.json') as f:
            data = json.load(f)
        assert isinstance(data, dict), "analysis.json must be a JSON object"

    def test_analysis_has_all_keys(self):
        with open('/app/analysis.json') as f:
            data = json.load(f)
        for key in ['strategy_a', 'strategy_b', 'strategy_c', 'designed_strategy']:
            assert key in data, f"Missing key '{key}' in analysis.json"

    def test_strategy_a_no_full_scans(self):
        """Strategy A uses covering indexes and must be correctly identified as scan-free."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        assert data['strategy_a']['has_full_scans'] is False, \
            "Strategy A (covering indexes on correct columns) should have no full scans"

    def test_strategy_a_empty_scan_list(self):
        """Strategy A should have no queries with full scans."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        scan_queries = data['strategy_a'].get('full_scan_queries', [])
        assert len(scan_queries) == 0, \
            f"Strategy A should have 0 queries with scans, got {scan_queries}"

    def test_strategy_b_has_full_scans(self):
        """Strategy B indexes wrong columns and must be correctly identified as having scans."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        assert data['strategy_b']['has_full_scans'] is True, \
            "Strategy B (indexes on side/flag_type) should have full scans"

    def test_strategy_b_all_queries_scan(self):
        """Strategy B should cause full scans on all 5 target queries."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        scan_queries = data['strategy_b'].get('full_scan_queries', [])
        assert len(scan_queries) == 5, \
            f"Strategy B should have 5 queries with scans, got {len(scan_queries)}: {scan_queries}"

    def test_strategy_c_has_full_scans(self):
        """Strategy C indexes wrong tables and must be correctly identified as having scans."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        assert data['strategy_c']['has_full_scans'] is True, \
            "Strategy C (indexes on instruments/traders tables) should have full scans"

    def test_strategy_c_all_queries_scan(self):
        """Strategy C should cause full scans on all 5 target queries."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        scan_queries = data['strategy_c'].get('full_scan_queries', [])
        assert len(scan_queries) == 5, \
            f"Strategy C should have 5 queries with scans, got {len(scan_queries)}: {scan_queries}"

    def test_designed_strategy_has_indexes(self):
        """The designed strategy must include a list of index definitions."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        ds = data['designed_strategy']
        assert 'indexes' in ds, "designed_strategy must include 'indexes' list"
        assert isinstance(ds['indexes'], list), "'indexes' must be a list"
        assert 1 <= len(ds['indexes']) <= 4, \
            f"designed_strategy must define 1-4 indexes, got {len(ds['indexes'])}"

    def test_designed_strategy_efficiency(self):
        """Solver's indexes must use fewer total columns than Strategy A's covering indexes (26 cols)."""
        conn = sqlite3.connect(DB_PATH)
        indexes = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchall()
        conn.close()

        total_cols = 0
        for (sql,) in indexes:
            if sql is None:
                continue
            match = re.search(r'\(([^)]+)\)', sql)
            if match:
                cols = [c.strip() for c in match.group(1).split(',')]
                total_cols += len(cols)

        # Strategy A uses 26 total index columns (covering indexes).
        # An efficient strategy should use significantly fewer.
        assert total_cols <= 18, \
            f"Index strategy uses {total_cols} total columns across all indexes — " \
            f"not more efficient than Strategy A's covering indexes (26 columns)"

    def test_each_strategy_has_assessment(self):
        """Each candidate strategy evaluation must include a text assessment."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        for key in ['strategy_a', 'strategy_b', 'strategy_c']:
            assert 'assessment' in data[key], \
                f"{key} must include an 'assessment' field"
            assert isinstance(data[key]['assessment'], str) and len(data[key]['assessment']) > 10, \
                f"{key} assessment must be a non-trivial text explanation"

    def test_designed_strategy_has_rationale(self):
        """The designed strategy must include a rationale explaining the design choices."""
        with open('/app/analysis.json') as f:
            data = json.load(f)
        ds = data['designed_strategy']
        assert 'rationale' in ds, "designed_strategy must include 'rationale'"
        assert isinstance(ds['rationale'], str) and len(ds['rationale']) > 20, \
            "designed_strategy rationale must be a substantive explanation"
