
import json
import os
import struct
import subprocess
import sys

import pytest
import zstandard

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
T0 = 1_700_000_000_000_000_000  # base timestamp (nanoseconds)
PRICE_SCALE = 1_000_000_000
UNDEF_PRICE = 0x7FFFFFFFFFFFFFFF
RECORD_FMT = '<BBHIQQqIBBccQiI'
RECORD_SIZE = struct.calcsize(RECORD_FMT)  # 56 bytes


# ---------------------------------------------------------------------------
# Data generation helpers
# ---------------------------------------------------------------------------
def _fp(dollars):
    """Dollar amount -> fixed-point price (1 unit = 1e-9)."""
    return int(round(dollars * PRICE_SCALE))


def _rec(pub_id, inst_id, ts_event, order_id, price_fp, size, action, side, sequence,
         flags=0, channel_id=0):
    """Build a single 56-byte MBO record."""
    ts_recv = ts_event + 1000
    ts_in_delta = -500
    return struct.pack(
        RECORD_FMT,
        RECORD_SIZE // 4,  # length in 32-bit words = 14
        0xA0,              # rtype = MBO
        pub_id, inst_id, ts_event,
        order_id, price_fp, size, flags, channel_id,
        action.encode('ascii'), side.encode('ascii'),
        ts_recv, ts_in_delta, sequence,
    )


def _header(dataset, record_count, start_ts, end_ts, compression=0):
    """Build a variable-length DBN file header."""
    name_bytes = dataset.encode('utf-8')
    hdr = b'DBN'
    hdr += struct.pack('<B', 1)                       # version
    hdr += struct.pack('<H', len(name_bytes))         # dataset name length (u16 LE)
    hdr += name_bytes                                 # dataset name
    hdr += struct.pack('<I', record_count)             # record count
    hdr += struct.pack('<Q', start_ts)                 # start timestamp
    hdr += struct.pack('<Q', end_ts)                   # end timestamp
    hdr += struct.pack('<BB', compression, 0xA0)       # compression, schema
    hdr += b'\x00\x00'                                 # reserved
    return hdr


def generate_data():
    """Generate all test input files deterministically."""
    os.makedirs('/app/feeds', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    # ------------------------------------------------------------------
    # Venue Alpha — XNAS.ITCH, publisher_id=1, uncompressed, 18 records
    # Instruments: 5001 (AAPL), 5002 (MSFT), 5003 (GOOG)
    # ------------------------------------------------------------------
    alpha = [
        _rec(1, 5001, T0+100,  1001, _fp(150.00),  100, 'A', 'B', 1),
        _rec(1, 5002, T0+110,  2001, _fp(380.00),  200, 'A', 'B', 2),
        _rec(1, 5003, T0+120,  3001, _fp(50.00),   500, 'A', 'B', 3),
        _rec(1, 5001, T0+150,  1002, _fp(150.50),   50, 'A', 'B', 4),
        _rec(1, 5002, T0+160,  2002, _fp(380.50),  100, 'A', 'A', 5),
        _rec(1, 5003, T0+170,  3002, _fp(50.50),   300, 'A', 'A', 6),
        _rec(1, 5001, T0+200,  1003, _fp(151.00),  200, 'A', 'A', 7),
        _rec(1, 5001, T0+250,  1004, _fp(151.25),  150, 'A', 'A', 8),
        _rec(1, 5001, T0+300,  1005, _fp(150.75),   75, 'A', 'B', 9),
        # --- sequence gap: 10, 11 missing ---
        _rec(1, 5001, T0+1000, 1002, _fp(150.625),  50, 'M', 'B', 12),   # modify known
        _rec(1, 5001, T0+1500,    0, _fp(151.00),   30, 'T', 'A', 13),   # trade
        _rec(1, 5001, T0+1600, 1003, _fp(151.00),   30, 'F', 'A', 14),   # fill 200->170
        _rec(1, 5001, T0+2000, 9999, UNDEF_PRICE,    0, 'C', 'N', 15),   # phantom cancel
        _rec(1, 5002, T0+2500,    0, _fp(380.50),   50, 'T', 'A', 16),   # trade
        _rec(1, 5002, T0+2600, 2002, _fp(380.50),   50, 'F', 'A', 17),   # fill 100->50
        # Clear all GOOG orders
        _rec(1, 5003, T0+2800,    0, UNDEF_PRICE,    0, 'R', 'N', 18),   # clear
        # Re-add GOOG after clear
        _rec(1, 5003, T0+2900, 3003, _fp(51.00),   200, 'A', 'B', 19),
        _rec(1, 5001, T0+3000, 1006, _fp(151.125), 100, 'A', 'B', 20),   # high bid -> cross
    ]

    alpha_data = b''.join(alpha)
    alpha_hdr = _header("XNAS.ITCH", len(alpha), T0+100, T0+3000, compression=0)
    with open('/app/feeds/venue_alpha.bin', 'wb') as f:
        f.write(alpha_hdr)
        f.write(alpha_data)

    # ------------------------------------------------------------------
    # Venue Beta — XNYS.PILLAR, publisher_id=2, zstd compressed, 9 records
    # Instruments: 8001 (AAPL), 8002 (MSFT)
    # ------------------------------------------------------------------
    beta = [
        _rec(2, 8001, T0+105,  6001, _fp(150.25),   80, 'A', 'B', 1),
        _rec(2, 8002, T0+115,  7001, _fp(379.75),  150, 'A', 'B', 2),
        _rec(2, 8001, T0+155,  6002, _fp(150.875), 120, 'A', 'A', 3),
        _rec(2, 8002, T0+165,  7002, _fp(380.75),   80, 'A', 'A', 4),
        _rec(2, 8001, T0+1500,    0, _fp(151.00),   30, 'T', 'A', 5),   # dup trade AAPL
        _rec(2, 8002, T0+2500,    0, _fp(380.50),   50, 'T', 'A', 6),   # dup trade MSFT
        # Modify unknown order (treat as Add)
        _rec(2, 8001, T0+2650, 6099, _fp(150.50),   40, 'M', 'B', 7),
        _rec(2, 8001, T0+2700, 6003, _fp(151.00),   60, 'A', 'A', 8),
        _rec(2, 8001, T0+3200, 6002, _fp(150.875), 120, 'F', 'A', 9),   # full fill
    ]

    beta_data = b''.join(beta)
    cctx = zstandard.ZstdCompressor()
    beta_compressed = cctx.compress(beta_data)
    beta_hdr = _header("XNYS.PILLAR", len(beta), T0+105, T0+3200, compression=1)
    with open('/app/feeds/venue_beta.bin', 'wb') as f:
        f.write(beta_hdr)
        f.write(beta_compressed)

    # Symbology
    symbology = {
        "mappings": [
            {"canonical": "AAPL", "venues": {"XNAS.ITCH": 5001, "XNYS.PILLAR": 8001}},
            {"canonical": "MSFT", "venues": {"XNAS.ITCH": 5002, "XNYS.PILLAR": 8002}},
            {"canonical": "GOOG", "venues": {"XNAS.ITCH": 5003}},
        ]
    }
    with open('/app/symbology.json', 'w') as f:
        json.dump(symbology, f, indent=2)

    # Checkpoints
    checkpoints = [T0 + 500, T0 + 2000, T0 + 3500]
    with open('/app/checkpoints.json', 'w') as f:
        json.dump(checkpoints, f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Generate test data and run the solver's reconcile executable."""
    generate_data()

    assert os.path.isfile('/app/reconcile'), \
        "/app/reconcile executable not found"

    result = subprocess.run(
        ["/app/reconcile"],
        timeout=120,
        capture_output=True,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"reconcile exited {result.returncode}\n"
        f"stdout: {result.stdout.decode(errors='replace')[:2000]}\n"
        f"stderr: {result.stderr.decode(errors='replace')[:2000]}"
    )
    assert os.path.isfile('/app/output/snapshots.json'), "snapshots.json not created"
    assert os.path.isfile('/app/output/anomalies.json'), "anomalies.json not created"


@pytest.fixture(scope="session")
def snapshots(run_pipeline):
    with open('/app/output/snapshots.json') as f:
        return json.load(f)


@pytest.fixture(scope="session")
def anomalies(run_pipeline):
    with open('/app/output/anomalies.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_cp(snapshots, ts):
    for cp in snapshots:
        if cp['timestamp'] == ts:
            return cp
    pytest.fail(f"Checkpoint at timestamp {ts} not found in snapshots")


def _approx(val, expected, tol=1e-6):
    assert abs(val - expected) < tol, f"{val} != {expected} (tol={tol})"


# ===================================================================
# Snapshot structure tests
# ===================================================================
class TestSnapshotStructure:
    def test_checkpoint_count(self, snapshots):
        assert len(snapshots) == 3

    def test_checkpoint_timestamps(self, snapshots):
        ts_list = [cp['timestamp'] for cp in snapshots]
        assert ts_list == [T0 + 500, T0 + 2000, T0 + 3500]


# ===================================================================
# CP1  (T0+500) — after all initial adds, before any modifications
# ===================================================================
class TestCP1:
    TS = T0 + 500

    def test_instruments_present(self, snapshots):
        cp = _find_cp(snapshots, self.TS)
        assert set(cp['books'].keys()) == {'AAPL', 'MSFT', 'GOOG'}

    # -- AAPL --
    def test_aapl_bid_count(self, snapshots):
        bids = _find_cp(snapshots, self.TS)['books']['AAPL']['bids']
        assert len(bids) == 4

    def test_aapl_bid_prices(self, snapshots):
        bids = _find_cp(snapshots, self.TS)['books']['AAPL']['bids']
        prices = [b['price'] for b in bids]
        expected = [150.75, 150.50, 150.25, 150.00]
        for p, e in zip(prices, expected):
            _approx(p, e)

    def test_aapl_bid_sizes(self, snapshots):
        bids = _find_cp(snapshots, self.TS)['books']['AAPL']['bids']
        sizes = [b['size'] for b in bids]
        assert sizes == [75, 50, 80, 100]

    def test_aapl_ask_count(self, snapshots):
        asks = _find_cp(snapshots, self.TS)['books']['AAPL']['asks']
        assert len(asks) == 3

    def test_aapl_ask_prices(self, snapshots):
        asks = _find_cp(snapshots, self.TS)['books']['AAPL']['asks']
        prices = [a['price'] for a in asks]
        expected = [150.875, 151.00, 151.25]
        for p, e in zip(prices, expected):
            _approx(p, e)

    def test_aapl_ask_sizes(self, snapshots):
        asks = _find_cp(snapshots, self.TS)['books']['AAPL']['asks']
        sizes = [a['size'] for a in asks]
        assert sizes == [120, 200, 150]

    # -- MSFT --
    def test_msft_bids(self, snapshots):
        bids = _find_cp(snapshots, self.TS)['books']['MSFT']['bids']
        assert len(bids) == 2
        _approx(bids[0]['price'], 380.00)
        assert bids[0]['size'] == 200
        _approx(bids[1]['price'], 379.75)
        assert bids[1]['size'] == 150

    def test_msft_asks(self, snapshots):
        asks = _find_cp(snapshots, self.TS)['books']['MSFT']['asks']
        assert len(asks) == 2
        _approx(asks[0]['price'], 380.50)
        assert asks[0]['size'] == 100
        _approx(asks[1]['price'], 380.75)
        assert asks[1]['size'] == 80

    # -- GOOG --
    def test_goog_book(self, snapshots):
        goog = _find_cp(snapshots, self.TS)['books']['GOOG']
        assert len(goog['bids']) == 1
        _approx(goog['bids'][0]['price'], 50.00)
        assert goog['bids'][0]['size'] == 500
        assert len(goog['asks']) == 1
        _approx(goog['asks'][0]['price'], 50.50)
        assert goog['asks'][0]['size'] == 300


# ===================================================================
# CP2  (T0+2000) — after modify, trade, fill, phantom cancel
# ===================================================================
class TestCP2:
    TS = T0 + 2000

    def test_aapl_bids_after_modify(self, snapshots):
        bids = _find_cp(snapshots, self.TS)['books']['AAPL']['bids']
        assert len(bids) == 4
        _approx(bids[0]['price'], 150.75)
        assert bids[0]['size'] == 75
        _approx(bids[1]['price'], 150.625)
        assert bids[1]['size'] == 50
        _approx(bids[2]['price'], 150.25)
        assert bids[2]['size'] == 80
        _approx(bids[3]['price'], 150.00)
        assert bids[3]['size'] == 100

    def test_aapl_asks_after_fill(self, snapshots):
        asks = _find_cp(snapshots, self.TS)['books']['AAPL']['asks']
        assert len(asks) == 3
        _approx(asks[0]['price'], 150.875)
        assert asks[0]['size'] == 120
        _approx(asks[1]['price'], 151.00)
        assert asks[1]['size'] == 170   # 200 - 30
        _approx(asks[2]['price'], 151.25)
        assert asks[2]['size'] == 150

    def test_msft_unchanged(self, snapshots):
        msft = _find_cp(snapshots, self.TS)['books']['MSFT']
        assert msft['asks'][0]['size'] == 100  # not yet filled

    def test_goog_unchanged(self, snapshots):
        goog = _find_cp(snapshots, self.TS)['books']['GOOG']
        assert goog['bids'][0]['size'] == 500
        assert goog['asks'][0]['size'] == 300


# ===================================================================
# CP3  (T0+3500) — final state: crossed book, price aggregation,
#                  GOOG clear+re-add, modify-unknown, full fill
# ===================================================================
class TestCP3:
    TS = T0 + 3500

    def test_aapl_bids_5_levels(self, snapshots):
        """Includes modify-unknown order 6099 at 150.50."""
        bids = _find_cp(snapshots, self.TS)['books']['AAPL']['bids']
        assert len(bids) == 5
        expected = [
            (151.125, 100, 1),
            (150.75,   75, 1),
            (150.625,  50, 1),
            (150.50,   40, 1),   # order 6099 from modify-unknown
            (150.25,   80, 1),
        ]
        for bid, (ep, es, ec) in zip(bids, expected):
            _approx(bid['price'], ep)
            assert bid['size'] == es
            assert bid['count'] == ec

    def test_aapl_asks_aggregated(self, snapshots):
        """6002 removed by full fill; 1003 (170) + 6003 (60) aggregate at 151.00."""
        asks = _find_cp(snapshots, self.TS)['books']['AAPL']['asks']
        assert len(asks) == 2
        _approx(asks[0]['price'], 151.00)
        assert asks[0]['size'] == 230   # 170 + 60
        assert asks[0]['count'] == 2    # two orders at this price
        _approx(asks[1]['price'], 151.25)
        assert asks[1]['size'] == 150
        assert asks[1]['count'] == 1

    def test_msft_after_fill(self, snapshots):
        msft = _find_cp(snapshots, self.TS)['books']['MSFT']
        _approx(msft['asks'][0]['price'], 380.50)
        assert msft['asks'][0]['size'] == 50   # 100 - 50

    def test_goog_after_clear_and_readd(self, snapshots):
        """GOOG was cleared at T0+2800, then one bid re-added at T0+2900."""
        goog = _find_cp(snapshots, self.TS)['books']['GOOG']
        assert len(goog['bids']) == 1
        _approx(goog['bids'][0]['price'], 51.00)
        assert goog['bids'][0]['size'] == 200
        assert goog['bids'][0]['count'] == 1
        assert len(goog['asks']) == 0


# ===================================================================
# Anomaly tests
# ===================================================================
class TestAnomalies:
    def test_anomaly_count(self, anomalies):
        assert len(anomalies) == 5

    def test_sorted_by_timestamp(self, anomalies):
        ts_list = [a['timestamp'] for a in anomalies]
        assert ts_list == sorted(ts_list)

    def test_sequence_gap(self, anomalies):
        gaps = [a for a in anomalies if a['type'] == 'sequence_gap']
        assert len(gaps) == 1
        g = gaps[0]
        assert g['timestamp'] == T0 + 1000
        assert g['venue'] == 'XNAS.ITCH'
        assert g['expected_seq'] == 10
        assert g['actual_seq'] == 12

    def test_phantom_order(self, anomalies):
        phantoms = [a for a in anomalies if a['type'] == 'phantom_order']
        assert len(phantoms) == 1
        p = phantoms[0]
        assert p['timestamp'] == T0 + 2000
        assert p['venue'] == 'XNAS.ITCH'
        assert p['order_id'] == 9999

    def test_duplicate_trade_aapl(self, anomalies):
        dups = [a for a in anomalies
                if a['type'] == 'duplicate_trade' and a['symbol'] == 'AAPL']
        assert len(dups) == 1
        d = dups[0]
        assert d['timestamp'] == T0 + 1500
        _approx(d['price'], 151.00)
        assert d['size'] == 30

    def test_duplicate_trade_msft(self, anomalies):
        dups = [a for a in anomalies
                if a['type'] == 'duplicate_trade' and a['symbol'] == 'MSFT']
        assert len(dups) == 1
        d = dups[0]
        assert d['timestamp'] == T0 + 2500
        _approx(d['price'], 380.50)
        assert d['size'] == 50

    def test_crossed_book(self, anomalies):
        crosses = [a for a in anomalies if a['type'] == 'crossed_book']
        assert len(crosses) == 1
        c = crosses[0]
        assert c['timestamp'] == T0 + 3000
        assert c['symbol'] == 'AAPL'
        _approx(c['best_bid'], 151.125)
        _approx(c['best_ask'], 150.875)
