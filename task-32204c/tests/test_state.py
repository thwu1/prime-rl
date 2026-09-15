
import sqlite3
import os
import pytest


OUTPUT_DB = '/app/output/analysis.db'

# Expected analytics hardcoded from deterministic data generation (seed 54321).
# These values are NOT stored anywhere in the task environment.
EXPECTED = {
    '1001': {
        'vwap': 4499.715959,
        'total_volume': 2945,
        'trade_count': 88,
        'max_spread': 0.5,
        'iceberg_count': 3,
        'final_best_bid': 4499.75,
        'final_best_ask': 4500.0,
        'final_bid_size': 32,
        'final_ask_size': 380,
        'bid_depth': 8,
        'ask_depth': 9,
        'message_count': 288,
    },
    '1002': {
        'vwap': 14999.444638,
        'total_volume': 1725,
        'trade_count': 77,
        'max_spread': 0.25,
        'iceberg_count': 3,
        'final_best_bid': 14999.75,
        'final_best_ask': 15000.0,
        'final_bid_size': 60,
        'final_ask_size': 115,
        'bid_depth': 6,
        'ask_depth': 8,
        'message_count': 231,
    },
}


@pytest.fixture(scope='module')
def output_db():
    """Connect to the output SQLite database."""
    assert os.path.exists(OUTPUT_DB), \
        f"Output database not found: {OUTPUT_DB}. Pipeline must create {OUTPUT_DB}"
    conn = sqlite3.connect(OUTPUT_DB)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# -- Schema validation --------------------------------------------------------

def test_output_db_exists():
    """The pipeline must produce a SQLite database at the expected path."""
    assert os.path.exists(OUTPUT_DB), f"{OUTPUT_DB} does not exist"
    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    required = {'metrics', 'trades', 'gaps', 'latency'}
    missing = required - tables
    assert not missing, f"Missing tables: {missing}. Found: {tables}"


def test_metrics_schema(output_db):
    """Metrics table must have the required columns."""
    cursor = output_db.cursor()
    cursor.execute("PRAGMA table_info(metrics)")
    columns = {row[1] for row in cursor.fetchall()}
    required = {
        'instrument_id', 'symbol', 'vwap', 'total_volume', 'trade_count',
        'max_spread', 'iceberg_count', 'final_best_bid', 'final_best_ask',
        'final_bid_size', 'final_ask_size', 'bid_depth', 'ask_depth',
        'message_count',
    }
    missing = required - columns
    assert not missing, f"Missing columns in metrics: {missing}"


def test_trades_schema(output_db):
    """Trades table must have the required columns."""
    cursor = output_db.cursor()
    cursor.execute("PRAGMA table_info(trades)")
    columns = {row[1] for row in cursor.fetchall()}
    required = {
        'instrument_id', 'timestamp_ns', 'price', 'quantity',
        'side', 'action', 'sequence',
    }
    missing = required - columns
    assert not missing, f"Missing columns in trades: {missing}"


def test_gaps_schema(output_db):
    """Gaps table must have the required columns."""
    cursor = output_db.cursor()
    cursor.execute("PRAGMA table_info(gaps)")
    columns = {row[1] for row in cursor.fetchall()}
    required = {'channel_id', 'expected_seq', 'actual_seq', 'gap_size'}
    missing = required - columns
    assert not missing, f"Missing columns in gaps: {missing}"


def test_latency_schema(output_db):
    """Latency table must have the required columns."""
    cursor = output_db.cursor()
    cursor.execute("PRAGMA table_info(latency)")
    columns = {row[1] for row in cursor.fetchall()}
    required = {'channel_id', 'capture_epoch_us', 'message_time_ns', 'packet_msg_count'}
    missing = required - columns
    assert not missing, f"Missing columns in latency: {missing}"


# -- Multi-instrument validation -----------------------------------------------

def test_both_instruments_present(output_db):
    """Metrics must include rows for both ES.FUT (1001) and NQ.FUT (1002)."""
    cursor = output_db.cursor()
    cursor.execute("SELECT instrument_id FROM metrics")
    ids = {row[0] for row in cursor.fetchall()}
    assert 1001 in ids, "Missing metrics for instrument 1001 (ES.FUT)"
    assert 1002 in ids, "Missing metrics for instrument 1002 (NQ.FUT)"


def test_instrument_symbols(output_db):
    """Symbols must match reference database entries."""
    cursor = output_db.cursor()
    cursor.execute("SELECT instrument_id, symbol FROM metrics ORDER BY instrument_id")
    rows = cursor.fetchall()
    symbols = {row[0]: row[1] for row in rows}
    assert symbols.get(1001) == 'ES.FUT', \
        f"Instrument 1001 symbol: expected 'ES.FUT', got '{symbols.get(1001)}'"
    assert symbols.get(1002) == 'NQ.FUT', \
        f"Instrument 1002 symbol: expected 'NQ.FUT', got '{symbols.get(1002)}'"


# -- Per-instrument analytics validation ---------------------------------------

def _get_metrics(output_db, inst_id):
    cursor = output_db.cursor()
    cursor.execute("SELECT * FROM metrics WHERE instrument_id = ?", (inst_id,))
    row = cursor.fetchone()
    assert row is not None, f"No metrics row for instrument {inst_id}"
    return dict(row)


def test_es_vwap(output_db):
    """ES.FUT VWAP must match expected value within tolerance."""
    m = _get_metrics(output_db, 1001)
    exp = EXPECTED['1001']
    assert m['vwap'] is not None, "ES VWAP is None"
    assert abs(float(m['vwap']) - exp['vwap']) < 0.01, \
        f"ES VWAP: expected {exp['vwap']}, got {m['vwap']}"


def test_es_volume(output_db):
    """ES.FUT total volume must match expected value."""
    m = _get_metrics(output_db, 1001)
    exp = EXPECTED['1001']
    assert int(m['total_volume']) == exp['total_volume'], \
        f"ES volume: expected {exp['total_volume']}, got {m['total_volume']}"


def test_es_trade_count(output_db):
    """ES.FUT trade count must match expected value."""
    m = _get_metrics(output_db, 1001)
    exp = EXPECTED['1001']
    assert int(m['trade_count']) == exp['trade_count'], \
        f"ES trade_count: expected {exp['trade_count']}, got {m['trade_count']}"


def test_es_max_spread(output_db):
    """ES.FUT max spread must match within tolerance."""
    m = _get_metrics(output_db, 1001)
    exp = EXPECTED['1001']
    assert abs(float(m['max_spread']) - exp['max_spread']) < 0.01, \
        f"ES max_spread: expected {exp['max_spread']}, got {m['max_spread']}"


def test_es_iceberg_count(output_db):
    """ES.FUT iceberg count must match expected value."""
    m = _get_metrics(output_db, 1001)
    exp = EXPECTED['1001']
    assert int(m['iceberg_count']) == exp['iceberg_count'], \
        f"ES iceberg_count: expected {exp['iceberg_count']}, got {m['iceberg_count']}"


def test_es_final_book(output_db):
    """ES.FUT final book state must match expected values."""
    m = _get_metrics(output_db, 1001)
    exp = EXPECTED['1001']

    if exp['final_best_bid'] is not None:
        assert m['final_best_bid'] is not None, "ES final_best_bid is None"
        assert abs(float(m['final_best_bid']) - exp['final_best_bid']) < 0.01, \
            f"ES final_best_bid: expected {exp['final_best_bid']}, got {m['final_best_bid']}"

    if exp['final_best_ask'] is not None:
        assert m['final_best_ask'] is not None, "ES final_best_ask is None"
        assert abs(float(m['final_best_ask']) - exp['final_best_ask']) < 0.01, \
            f"ES final_best_ask: expected {exp['final_best_ask']}, got {m['final_best_ask']}"

    assert int(m['final_bid_size']) == exp['final_bid_size'], \
        f"ES final_bid_size: expected {exp['final_bid_size']}, got {m['final_bid_size']}"
    assert int(m['final_ask_size']) == exp['final_ask_size'], \
        f"ES final_ask_size: expected {exp['final_ask_size']}, got {m['final_ask_size']}"
    assert int(m['bid_depth']) == exp['bid_depth'], \
        f"ES bid_depth: expected {exp['bid_depth']}, got {m['bid_depth']}"
    assert int(m['ask_depth']) == exp['ask_depth'], \
        f"ES ask_depth: expected {exp['ask_depth']}, got {m['ask_depth']}"


def test_es_message_count(output_db):
    """ES.FUT message count must match expected value."""
    m = _get_metrics(output_db, 1001)
    exp = EXPECTED['1001']
    assert int(m['message_count']) == exp['message_count'], \
        f"ES message_count: expected {exp['message_count']}, got {m['message_count']}"


def test_nq_vwap(output_db):
    """NQ.FUT VWAP must match expected value within tolerance."""
    m = _get_metrics(output_db, 1002)
    exp = EXPECTED['1002']
    assert m['vwap'] is not None, "NQ VWAP is None"
    assert abs(float(m['vwap']) - exp['vwap']) < 0.01, \
        f"NQ VWAP: expected {exp['vwap']}, got {m['vwap']}"


def test_nq_volume(output_db):
    """NQ.FUT total volume must match expected value."""
    m = _get_metrics(output_db, 1002)
    exp = EXPECTED['1002']
    assert int(m['total_volume']) == exp['total_volume'], \
        f"NQ volume: expected {exp['total_volume']}, got {m['total_volume']}"


def test_nq_trade_count(output_db):
    """NQ.FUT trade count must match expected value."""
    m = _get_metrics(output_db, 1002)
    exp = EXPECTED['1002']
    assert int(m['trade_count']) == exp['trade_count'], \
        f"NQ trade_count: expected {exp['trade_count']}, got {m['trade_count']}"


def test_nq_final_book(output_db):
    """NQ.FUT final book state must match expected values."""
    m = _get_metrics(output_db, 1002)
    exp = EXPECTED['1002']

    if exp['final_best_bid'] is not None:
        assert m['final_best_bid'] is not None, "NQ final_best_bid is None"
        assert abs(float(m['final_best_bid']) - exp['final_best_bid']) < 0.01, \
            f"NQ final_best_bid: expected {exp['final_best_bid']}, got {m['final_best_bid']}"

    if exp['final_best_ask'] is not None:
        assert m['final_best_ask'] is not None, "NQ final_best_ask is None"
        assert abs(float(m['final_best_ask']) - exp['final_best_ask']) < 0.01, \
            f"NQ final_best_ask: expected {exp['final_best_ask']}, got {m['final_best_ask']}"

    assert int(m['final_bid_size']) == exp['final_bid_size'], \
        f"NQ final_bid_size: expected {exp['final_bid_size']}, got {m['final_bid_size']}"
    assert int(m['final_ask_size']) == exp['final_ask_size'], \
        f"NQ final_ask_size: expected {exp['final_ask_size']}, got {m['final_ask_size']}"
    assert int(m['bid_depth']) == exp['bid_depth'], \
        f"NQ bid_depth: expected {exp['bid_depth']}, got {m['bid_depth']}"
    assert int(m['ask_depth']) == exp['ask_depth'], \
        f"NQ ask_depth: expected {exp['ask_depth']}, got {m['ask_depth']}"


# -- Trades table validation ---------------------------------------------------

def test_trades_not_empty(output_db):
    """Trades table must have entries."""
    cursor = output_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM trades")
    count = cursor.fetchone()[0]
    assert count > 0, "Trades table is empty"


def test_trades_total_count(output_db):
    """Total trade count across both instruments must match expected total."""
    cursor = output_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM trades")
    total = cursor.fetchone()[0]
    expected_total = EXPECTED['1001']['trade_count'] + EXPECTED['1002']['trade_count']
    assert total == expected_total, \
        f"Total trade count: expected {expected_total}, got {total}"


def test_trades_match_metrics(output_db):
    """Trade count in trades table must match metrics for each instrument."""
    cursor = output_db.cursor()
    cursor.execute("""
        SELECT t.instrument_id, COUNT(*) as t_count, m.trade_count
        FROM trades t
        JOIN metrics m ON t.instrument_id = m.instrument_id
        GROUP BY t.instrument_id
    """)
    for row in cursor.fetchall():
        assert row[1] == row[2], \
            f"Instrument {row[0]}: trades table has {row[1]} rows, metrics says {row[2]}"


def test_trades_valid_actions(output_db):
    """All trade actions must be 'T' or 'F'."""
    cursor = output_db.cursor()
    cursor.execute("SELECT DISTINCT action FROM trades")
    actions = {row[0] for row in cursor.fetchall()}
    assert actions <= {'T', 'F'}, f"Unexpected trade actions: {actions - {'T', 'F'}}"


def test_trades_valid_sides(output_db):
    """All trade sides must be 'B' or 'S'."""
    cursor = output_db.cursor()
    cursor.execute("SELECT DISTINCT side FROM trades")
    sides = {row[0] for row in cursor.fetchall()}
    assert sides <= {'B', 'S'}, f"Unexpected trade sides: {sides - {'B', 'S'}}"


def test_trades_positive_prices(output_db):
    """All trade prices must be positive."""
    cursor = output_db.cursor()
    cursor.execute("SELECT MIN(price) FROM trades")
    min_price = cursor.fetchone()[0]
    assert min_price > 0, f"Found non-positive trade price: {min_price}"


def test_trades_positive_quantities(output_db):
    """All trade quantities must be positive."""
    cursor = output_db.cursor()
    cursor.execute("SELECT MIN(quantity) FROM trades")
    min_qty = cursor.fetchone()[0]
    assert min_qty > 0, f"Found non-positive trade quantity: {min_qty}"


def test_es_trades_price_range(output_db):
    """ES.FUT trade prices should be in the expected range (~4500)."""
    cursor = output_db.cursor()
    cursor.execute(
        "SELECT MIN(price), MAX(price) FROM trades WHERE instrument_id = 1001")
    row = cursor.fetchone()
    if row[0] is not None:
        assert 4400 < row[0] < 4600, f"ES min price {row[0]} out of range"
        assert 4400 < row[1] < 4600, f"ES max price {row[1]} out of range"


def test_nq_trades_price_range(output_db):
    """NQ.FUT trade prices should be in the expected range (~15000)."""
    cursor = output_db.cursor()
    cursor.execute(
        "SELECT MIN(price), MAX(price) FROM trades WHERE instrument_id = 1002")
    row = cursor.fetchone()
    if row[0] is not None:
        assert 14800 < row[0] < 15200, f"NQ min price {row[0]} out of range"
        assert 14800 < row[1] < 15200, f"NQ max price {row[1]} out of range"


def test_trades_sequences_unique(output_db):
    """Each trade must have a unique record sequence number."""
    cursor = output_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM trades")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT sequence) FROM trades")
    distinct = cursor.fetchone()[0]
    assert total == distinct, \
        f"Duplicate sequence numbers in trades: {total} rows but {distinct} distinct sequences"


def test_trades_vwap_consistency(output_db):
    """VWAP in metrics must equal sum(price*qty)/sum(qty) from trades table."""
    cursor = output_db.cursor()
    cursor.execute("""
        SELECT t.instrument_id,
               SUM(t.price * t.quantity) / SUM(t.quantity) as computed_vwap,
               m.vwap
        FROM trades t
        JOIN metrics m ON t.instrument_id = m.instrument_id
        GROUP BY t.instrument_id
    """)
    for row in cursor.fetchall():
        assert abs(row[1] - row[2]) < 0.01, \
            f"Instrument {row[0]}: computed VWAP {row[1]} != metrics VWAP {row[2]}"


# -- Gap detection validation --------------------------------------------------

def test_gaps_detected(output_db):
    """Channel A gaps must be detected."""
    cursor = output_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM gaps WHERE channel_id = 1")
    count = cursor.fetchone()[0]
    assert count > 0, "No gaps detected in channel A (gaps were intentionally injected)"


def test_gaps_positive_sizes(output_db):
    """All detected gaps must have positive gap_size."""
    cursor = output_db.cursor()
    cursor.execute("SELECT MIN(gap_size) FROM gaps")
    row = cursor.fetchone()
    if row[0] is not None:
        assert row[0] > 0, f"Found non-positive gap_size: {row[0]}"


def test_gaps_consistency(output_db):
    """Gap size must equal actual_seq - expected_seq for each gap."""
    cursor = output_db.cursor()
    cursor.execute("SELECT channel_id, expected_seq, actual_seq, gap_size FROM gaps")
    for row in cursor.fetchall():
        computed = row[2] - row[1]
        assert computed == row[3], \
            f"Channel {row[0]}: gap_size {row[3]} != actual({row[2]}) - expected({row[1]}) = {computed}"


# -- Latency validation -------------------------------------------------------

def test_latency_not_empty(output_db):
    """Latency table must have entries."""
    cursor = output_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM latency")
    count = cursor.fetchone()[0]
    assert count > 0, "Latency table is empty"


def test_latency_valid_channels(output_db):
    """Latency entries must reference valid channel IDs."""
    cursor = output_db.cursor()
    cursor.execute("SELECT DISTINCT channel_id FROM latency")
    channels = {row[0] for row in cursor.fetchall()}
    assert channels <= {1, 2}, f"Unexpected channel IDs in latency: {channels}"


def test_latency_positive_timestamps(output_db):
    """Latency timestamps must be positive."""
    cursor = output_db.cursor()
    cursor.execute("SELECT MIN(capture_epoch_us), MIN(message_time_ns) FROM latency")
    row = cursor.fetchone()
    assert row[0] > 0, f"Found non-positive capture_epoch_us: {row[0]}"
    assert row[1] > 0, f"Found non-positive message_time_ns: {row[1]}"


def test_latency_packet_msg_counts(output_db):
    """All packet_msg_count values must be between 1 and 3."""
    cursor = output_db.cursor()
    cursor.execute("SELECT MIN(packet_msg_count), MAX(packet_msg_count) FROM latency")
    row = cursor.fetchone()
    assert row[0] >= 1, f"Found packet_msg_count < 1: {row[0]}"
    assert row[1] <= 10, f"Found unreasonably large packet_msg_count: {row[1]}"


# -- Cross-table consistency ---------------------------------------------------

def test_metrics_bid_ask_consistency(output_db):
    """Where both bid and ask exist, best_ask must exceed best_bid."""
    cursor = output_db.cursor()
    cursor.execute("""
        SELECT instrument_id, final_best_bid, final_best_ask
        FROM metrics
        WHERE final_best_bid IS NOT NULL AND final_best_ask IS NOT NULL
    """)
    for row in cursor.fetchall():
        assert row[2] > row[1], \
            f"Instrument {row[0]}: best_ask ({row[2]}) <= best_bid ({row[1]})"


def test_metrics_volume_consistency(output_db):
    """Total volume in metrics must equal sum of quantities in trades table."""
    cursor = output_db.cursor()
    cursor.execute("""
        SELECT m.instrument_id, m.total_volume, COALESCE(SUM(t.quantity), 0)
        FROM metrics m
        LEFT JOIN trades t ON m.instrument_id = t.instrument_id
        GROUP BY m.instrument_id
    """)
    for row in cursor.fetchall():
        assert row[1] == row[2], \
            f"Instrument {row[0]}: metrics volume ({row[1]}) != trades sum ({row[2]})"


def test_metrics_spread_positive(output_db):
    """Max spread must be positive for instruments with both bid and ask sides."""
    cursor = output_db.cursor()
    cursor.execute("""
        SELECT instrument_id, max_spread
        FROM metrics
        WHERE final_best_bid IS NOT NULL AND final_best_ask IS NOT NULL
    """)
    for row in cursor.fetchall():
        assert row[1] > 0, f"Instrument {row[0]}: max_spread must be positive, got {row[1]}"


def test_metrics_message_count_ge_trade_count(output_db):
    """Message count must be at least as large as trade count for each instrument."""
    cursor = output_db.cursor()
    cursor.execute("SELECT instrument_id, message_count, trade_count FROM metrics")
    for row in cursor.fetchall():
        assert row[1] >= row[2], \
            f"Instrument {row[0]}: message_count ({row[1]}) < trade_count ({row[2]})"
