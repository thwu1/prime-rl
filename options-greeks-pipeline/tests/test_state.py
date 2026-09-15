"""Tests for the futures options analytics pipeline."""

import struct
import sqlite3
import math
import os
import tomllib
from collections import defaultdict

import pytest

# Constants
SENTINEL = (1 << 63) - 1
PRICE_SCALE = 1_000_000_000
DATA_DIR = "/app/data"


def get_output_db_path():
    with open(os.path.join(DATA_DIR, "config.toml"), "rb") as f:
        config = tomllib.load(f)
    return config["output"]["database_path"]


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black76_price(F, K, T, sigma, r, is_call):
    """Compute Black-76 option price."""
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    disc = math.exp(-r * T)
    if is_call:
        return disc * (F * norm_cdf(d1) - K * norm_cdf(d2))
    else:
        return disc * (K * norm_cdf(-d2) - F * norm_cdf(-d1))


def load_config():
    with open(os.path.join(DATA_DIR, "config.toml"), "rb") as f:
        return tomllib.load(f)


def load_definitions():
    conn = sqlite3.connect(os.path.join(DATA_DIR, "reference.db"))
    conn.row_factory = sqlite3.Row
    defs = {}
    for row in conn.execute("SELECT * FROM instruments"):
        defs[row["instrument_id"]] = dict(row)
    conn.close()
    return defs


def parse_binary_quotes():
    """Parse quotes.bin and return raw records."""
    records = []
    path = os.path.join(DATA_DIR, "quotes.bin")
    header_fmt = "<4sIII"
    record_fmt = "<IBBHqqqIIII"

    with open(path, "rb") as f:
        header_data = f.read(struct.calcsize(header_fmt))
        header = struct.unpack(header_fmt, header_data)
        magic, version, num_records, _ = header
        assert magic == b"OPTQ" and version == 1

        rec_size = struct.calcsize(record_fmt)
        for _ in range(num_records):
            fields = struct.unpack(record_fmt, f.read(rec_size))
            records.append({
                "instrument_id": fields[0],
                "exchange_id": fields[1],
                "channel_id": fields[2],
                "msg_flags": fields[3],
                "ts_event": fields[4],
                "bid_px": fields[5],
                "ask_px": fields[6],
                "bid_sz": fields[7],
                "ask_sz": fields[8],
                "sequence": fields[9],
            })
    return records


def compute_expected_nbbo():
    """Compute expected NBBO independently from binary data."""
    records = parse_binary_quotes()

    # Filter heartbeats
    records = [r for r in records if r["instrument_id"] != 0]

    # Filter both-sentinel records
    records = [r for r in records
               if not (r["bid_px"] == SENTINEL and r["ask_px"] == SENTINEL)]

    # Deduplicate by (instrument_id, exchange_id, sequence), keep earliest ts
    dedup = {}
    for rec in records:
        key = (rec["instrument_id"], rec["exchange_id"], rec["sequence"])
        if key not in dedup or rec["ts_event"] < dedup[key]["ts_event"]:
            dedup[key] = rec
    records = list(dedup.values())

    # Group by instrument
    inst_quotes = defaultdict(list)
    for rec in records:
        inst_quotes[rec["instrument_id"]].append(rec)

    nbbo = {}
    for inst_id, quotes in inst_quotes.items():
        valid_bids = [q["bid_px"] / PRICE_SCALE for q in quotes
                      if q["bid_px"] != SENTINEL]
        valid_asks = [q["ask_px"] / PRICE_SCALE for q in quotes
                      if q["ask_px"] != SENTINEL]
        if valid_bids and valid_asks:
            best_bid = max(valid_bids)
            best_ask = min(valid_asks)
            nbbo[inst_id] = {
                "nbbo_bid": best_bid,
                "nbbo_ask": best_ask,
                "nbbo_mid": (best_bid + best_ask) / 2,
            }
    return nbbo


def query_output(sql):
    """Run a query against the output SQLite database."""
    db_path = get_output_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    conn.close()
    return rows


# ============================================================
# Output database structure tests
# ============================================================

class TestOutputDatabase:
    def test_database_exists(self):
        db_path = get_output_db_path()
        assert os.path.isfile(db_path), \
            "Output database not found at %s" % db_path

    def test_nbbo_table_exists(self):
        rows = query_output(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nbbo'")
        assert len(rows) == 1, "Table 'nbbo' not found in output database"

    def test_implied_volatility_table_exists(self):
        rows = query_output(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='implied_volatility'")
        assert len(rows) == 1, "Table 'implied_volatility' not found"

    def test_greeks_table_exists(self):
        rows = query_output(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='greeks'")
        assert len(rows) == 1, "Table 'greeks' not found"

    def test_parity_violations_table_exists(self):
        rows = query_output(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='parity_violations'")
        assert len(rows) == 1, "Table 'parity_violations' not found"


# ============================================================
# NBBO tests
# ============================================================

class TestNBBO:
    def test_nbbo_row_count(self):
        rows = query_output("SELECT * FROM nbbo")
        assert len(rows) == 22, "Expected 22 instruments, got %d" % len(rows)

    def test_nbbo_columns(self):
        rows = query_output("SELECT * FROM nbbo LIMIT 1")
        expected = {"instrument_id", "symbol", "nbbo_bid", "nbbo_ask", "nbbo_mid"}
        actual = set(rows[0].keys())
        assert expected.issubset(actual), \
            "Missing columns: %s" % (expected - actual)

    def test_nbbo_values(self):
        """Verify NBBO matches independently computed values."""
        expected = compute_expected_nbbo()
        rows = query_output("SELECT * FROM nbbo ORDER BY instrument_id")

        for row in rows:
            inst_id = int(row["instrument_id"])
            assert inst_id in expected, "Unexpected instrument %d" % inst_id

            exp = expected[inst_id]
            got_bid = float(row["nbbo_bid"])
            got_ask = float(row["nbbo_ask"])
            got_mid = float(row["nbbo_mid"])

            assert abs(got_bid - exp["nbbo_bid"]) < 0.01, \
                "Inst %d bid: got %.6f, expected %.6f" % (inst_id, got_bid, exp["nbbo_bid"])
            assert abs(got_ask - exp["nbbo_ask"]) < 0.01, \
                "Inst %d ask: got %.6f, expected %.6f" % (inst_id, got_ask, exp["nbbo_ask"])
            assert abs(got_mid - exp["nbbo_mid"]) < 0.01, \
                "Inst %d mid: got %.6f, expected %.6f" % (inst_id, got_mid, exp["nbbo_mid"])

    def test_nbbo_bid_leq_ask(self):
        rows = query_output("SELECT * FROM nbbo")
        for row in rows:
            bid = float(row["nbbo_bid"])
            ask = float(row["nbbo_ask"])
            assert bid <= ask + 1e-9, \
                "Inst %s: bid %.6f > ask %.6f" % (row["instrument_id"], bid, ask)


# ============================================================
# Implied volatility tests
# ============================================================

class TestImpliedVol:
    def test_iv_row_count(self):
        rows = query_output("SELECT * FROM implied_volatility")
        assert len(rows) == 22, "Expected 22 IVs, got %d" % len(rows)

    def test_iv_positive(self):
        rows = query_output("SELECT * FROM implied_volatility")
        for row in rows:
            iv = float(row["implied_vol"])
            assert iv > 0, "IV must be positive, got %f for %s" % (iv, row.get("symbol", "?"))

    def test_iv_reasonable_range(self):
        """IV should be between 1% and 200% for realistic data."""
        rows = query_output("SELECT * FROM implied_volatility")
        for row in rows:
            iv = float(row["implied_vol"])
            assert 0.01 < iv < 2.0, \
                "IV %.4f out of reasonable range for %s" % (iv, row.get("symbol", "?"))

    def test_iv_roundtrip(self):
        """Plugging IV back into the pricing model should reproduce the NBBO mid-price."""
        config = load_config()
        defs = load_definitions()
        nbbo = compute_expected_nbbo()

        F = config["market"]["futures_price"]
        r = config["market"]["risk_free_rate"]

        iv_rows = query_output(
            "SELECT * FROM implied_volatility ORDER BY instrument_id")
        for row in iv_rows:
            inst_id = int(row["instrument_id"])
            iv = float(row["implied_vol"])
            defn = defs[inst_id]
            T = defn["expiry_days"] / 365.0
            K = defn["strike"]
            is_call = defn["option_type"] == "C"

            computed = black76_price(F, K, T, iv, r, is_call)
            mid = nbbo[inst_id]["nbbo_mid"]

            # 1% relative tolerance or 0.05 absolute
            tol = max(mid * 0.01, 0.05)
            assert abs(computed - mid) < tol, \
                "Inst %d (%s): model(iv=%.4f)=%.4f vs mid=%.4f (tol=%.4f)" % (
                    inst_id, row.get("symbol", "?"), iv, computed, mid, tol)


# ============================================================
# Greeks tests
# ============================================================

class TestGreeks:
    def test_greeks_row_count(self):
        rows = query_output("SELECT * FROM greeks")
        assert len(rows) == 22, "Expected 22 rows, got %d" % len(rows)

    def test_greeks_columns(self):
        rows = query_output("SELECT * FROM greeks LIMIT 1")
        expected = {"instrument_id", "symbol", "delta", "gamma", "theta", "vega", "rho"}
        actual = set(rows[0].keys())
        assert expected.issubset(actual), \
            "Missing columns: %s" % (expected - actual)

    def test_delta_range(self):
        """Call delta in [0, 1], put delta in [-1, 0]."""
        defs = load_definitions()
        rows = query_output("SELECT * FROM greeks ORDER BY instrument_id")
        for row in rows:
            inst_id = int(row["instrument_id"])
            delta = float(row["delta"])
            is_call = defs[inst_id]["option_type"] == "C"
            if is_call:
                assert -0.01 <= delta <= 1.01, \
                    "Call delta %.4f out of [0,1] for inst %d" % (delta, inst_id)
            else:
                assert -1.01 <= delta <= 0.01, \
                    "Put delta %.4f out of [-1,0] for inst %d" % (delta, inst_id)

    def test_delta_putcall_parity(self):
        """For same strike: delta_call - delta_put should equal e^{-rT}."""
        config = load_config()
        defs = load_definitions()
        r = config["market"]["risk_free_rate"]

        rows = query_output("SELECT * FROM greeks ORDER BY instrument_id")
        greeks_by_id = {int(row["instrument_id"]): row for row in rows}

        by_strike = defaultdict(dict)
        for inst_id, defn in defs.items():
            by_strike[defn["strike"]][defn["option_type"]] = inst_id

        for strike, types in by_strike.items():
            if "C" in types and "P" in types:
                T = defs[types["C"]]["expiry_days"] / 365.0
                disc = math.exp(-r * T)
                call_delta = float(greeks_by_id[types["C"]]["delta"])
                put_delta = float(greeks_by_id[types["P"]]["delta"])
                sum_delta = call_delta - put_delta
                assert abs(sum_delta - disc) < 0.02, \
                    "Strike %.0f: delta_call(%.4f) - delta_put(%.4f) = %.4f, expected ~%.4f" % (
                        strike, call_delta, put_delta, sum_delta, disc)

    def test_gamma_positive(self):
        rows = query_output("SELECT * FROM greeks")
        for row in rows:
            gamma = float(row["gamma"])
            assert gamma > -1e-6, \
                "Gamma should be positive, got %.6f for inst %s" % (gamma, row["instrument_id"])

    def test_vega_positive(self):
        rows = query_output("SELECT * FROM greeks")
        for row in rows:
            vega = float(row["vega"])
            assert vega > -1e-6, \
                "Vega should be positive, got %.6f for inst %s" % (vega, row["instrument_id"])

    def test_rho_nonpositive(self):
        """For futures options, rho should always be non-positive."""
        rows = query_output("SELECT * FROM greeks")
        for row in rows:
            rho = float(row["rho"])
            assert rho < 0.01, \
                "Rho should be <= 0, got %.6f for inst %s" % (rho, row["instrument_id"])


# ============================================================
# Put-call parity violation tests
# ============================================================

class TestParityViolations:
    def test_violation_count(self):
        """Should find exactly 2 parity violations."""
        rows = query_output("SELECT * FROM parity_violations")
        assert len(rows) == 2, "Expected 2 violations, got %d" % len(rows)

    def test_violation_strikes(self):
        """Violations should be at strikes 5100 and 5350."""
        rows = query_output("SELECT * FROM parity_violations")
        strikes = {float(row["strike"]) for row in rows}
        assert strikes == {5100.0, 5350.0}, \
            "Expected violations at {5100, 5350}, got %s" % strikes

    def test_violation_exceeds_threshold(self):
        """Each violation should exceed the configured threshold."""
        config = load_config()
        threshold = config["arbitrage"]["parity_violation_threshold"]
        rows = query_output("SELECT * FROM parity_violations")
        for row in rows:
            amount = float(row["violation_amount"])
            assert amount > threshold, \
                "Violation %.4f at strike %s should exceed threshold %.1f" % (
                    amount, row["strike"], threshold)

    def test_violation_formula_consistency(self):
        """Verify internal consistency of violation columns."""
        config = load_config()
        defs = load_definitions()
        F = config["market"]["futures_price"]
        r = config["market"]["risk_free_rate"]
        T = list(defs.values())[0]["expiry_days"] / 365.0

        rows = query_output(
            "SELECT * FROM parity_violations ORDER BY strike")
        for row in rows:
            K = float(row["strike"])
            call_mid = float(row["call_mid"])
            put_mid = float(row["put_mid"])
            theo = float(row["theoretical_diff"])
            actual = float(row["actual_diff"])
            violation = float(row["violation_amount"])

            # theoretical_diff = e^{-rT} * (F - K)
            expected_theo = math.exp(-r * T) * (F - K)
            assert abs(theo - expected_theo) < 0.1, \
                "Strike %.0f: theoretical %.4f vs expected %.4f" % (K, theo, expected_theo)

            # actual_diff = call_mid - put_mid
            expected_actual = call_mid - put_mid
            assert abs(actual - expected_actual) < 0.01, \
                "Strike %.0f: actual_diff %.4f vs call-put=%.4f" % (K, actual, expected_actual)

            # violation_amount = |actual - theoretical|
            expected_viol = abs(actual - theo)
            assert abs(violation - expected_viol) < 0.01, \
                "Strike %.0f: violation %.4f vs |actual-theo|=%.4f" % (K, violation, expected_viol)
