"""
Verify ABS securitization pipeline output against 10-D servicer report golden numbers.
Golden values are from the Santander Drive Auto Receivables Trust 2026-1
monthly distribution report for the May 2026 collection period.

Tolerances account for minor methodology differences between raw EX-102 XML
computation and servicer-prepared 10-D aggregate statistics.
"""

import json
import os
import pytest


OUTPUT_DIR = "/app/output"


def load_json(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    assert os.path.exists(path), f"Output file {path} does not exist"
    with open(path) as f:
        return json.load(f)


# ── Pool Summary ──────────────────────────────────────────────────


class TestPoolSummary:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("pool_summary.json")

    def test_pool_balance(self):
        expected = 1_746_643_344.74
        actual = self.data["pool_balance"]
        assert abs(actual - expected) < 5.0, (
            f"pool_balance {actual} not within $5 of {expected}"
        )

    def test_pool_factor(self):
        expected = 0.902114
        actual = self.data["pool_factor"]
        assert abs(actual - expected) < 0.000005, (
            f"pool_factor {actual} not within 0.000005 of {expected}"
        )

    def test_wac_pct(self):
        expected = 18.35
        actual = self.data["wac_pct"]
        assert abs(actual - expected) < 0.10, (
            f"wac_pct {actual} not within 0.10 of {expected}"
        )

    def test_wart_months(self):
        expected = 63.67
        actual = self.data["wart_months"]
        assert abs(actual - expected) < 0.65, (
            f"wart_months {actual} not within 0.65 of {expected}"
        )

    def test_active_loan_count(self):
        expected = 80_381
        actual = self.data["active_loan_count"]
        assert abs(actual - expected) < 10, (
            f"active_loan_count {actual} not within 10 of {expected}"
        )


# ── Delinquency ──────────────────────────────────────────────────


DELINQ_GOLDEN = [
    {"label": "31-60", "units": 4_669, "dollars": 116_704_543.85, "pct": 6.68},
    {"label": "61-90", "units": 1_612, "dollars": 40_762_878.84, "pct": 2.33},
    {"label": "91-120", "units": 496, "dollars": 12_845_156.51, "pct": 0.74},
]


class TestDelinquency:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("delinquency.json")
        self.buckets = self.data["buckets"]
        assert len(self.buckets) == 3, f"Expected 3 buckets, got {len(self.buckets)}"

    @pytest.mark.parametrize("idx,golden", enumerate(DELINQ_GOLDEN),
                             ids=[g["label"] for g in DELINQ_GOLDEN])
    def test_delinquency_units(self, idx, golden):
        bucket = self.buckets[idx]
        assert abs(bucket["units"] - golden["units"]) < 10, (
            f"Bucket {golden['label']} units: {bucket['units']} "
            f"not within 10 of {golden['units']}"
        )

    @pytest.mark.parametrize("idx,golden", enumerate(DELINQ_GOLDEN),
                             ids=[g["label"] for g in DELINQ_GOLDEN])
    def test_delinquency_dollars(self, idx, golden):
        bucket = self.buckets[idx]
        assert abs(bucket["dollars"] - golden["dollars"]) < 5.0, (
            f"Bucket {golden['label']} dollars: {bucket['dollars']} "
            f"not within $5 of {golden['dollars']}"
        )

    @pytest.mark.parametrize("idx,golden", enumerate(DELINQ_GOLDEN),
                             ids=[g["label"] for g in DELINQ_GOLDEN])
    def test_delinquency_pct(self, idx, golden):
        bucket = self.buckets[idx]
        assert abs(bucket["pct"] - golden["pct"]) < 0.02, (
            f"Bucket {golden['label']} pct: {bucket['pct']} "
            f"not within 0.02 of {golden['pct']}"
        )


# ── Tranche Interest ────────────────────────────────────────────


TRANCHE_GOLDEN = {
    "A-1": 49_391.55,
    "A-2": 2_086_660.00,
    "A-3": 1_376_515.25,
    "B": 577_872.17,
    "C": 632_361.50,
    "D": 777_891.67,
    "E": 594_687.75,
}


class TestTrancheInterest:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("tranche_interest.json")
        self.tranches = {t["class"]: t for t in self.data["tranches"]}

    @pytest.mark.parametrize("cls,expected", TRANCHE_GOLDEN.items())
    def test_tranche_interest(self, cls, expected):
        assert cls in self.tranches, f"Missing tranche {cls}"
        actual = self.tranches[cls]["interest"]
        assert abs(actual - expected) < 0.02, (
            f"Tranche {cls} interest: {actual} not within $0.02 of {expected}"
        )
