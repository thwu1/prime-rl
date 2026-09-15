"""
Tests for TARGET Services Billing Pipeline.
Validates multi-tool pipeline outputs: shell orchestration, SQL views,
fee breakdowns, invoice totals, reconciliation, and audit CSV export.
"""

import csv
import json
import os
import sqlite3
import subprocess

import pytest

TOL = 0.015  # EUR tolerance for floating-point comparison


# ============================================================
# Expected correct invoice totals (derived from ECB Pricing
# Guide v3.0 Annex 1 worked examples and additional scenarios)
# ============================================================

EXPECTED_TOTALS = {
    # RTGS Ancillary Systems
    "AS1": 10367.00,
    "AS2": 49916.00,
    # RTGS Payment Banks (standalone)
    "Bank1": 57294.00,
    "Bank2": 3050.40,
    # RTGS Payment Banks (billing group BG1, leader=Bank3)
    "Bank3": 11480.19,
    "Bank4": 12653.47,
    "Bank5": 917.11,
    # T2S Cash-Related Services
    "Bank6": 222.72,
    "Bank7": 46.36,
    # TIPS
    "PSP1": 1626.26,
    "ACH1": 7158.20,
    # Additional scenario
    "AS_Alpha": 36250.00,
    "Bank_X": 64869.80,
    "Bank_P": 38623.20,
    "Bank_Q": 15549.00,
    "Bank_T": 112.62,
    "PSP_Beta": 1026.20,
    "ACH_Gamma": 12260.00,
}

# Expected discrepancies: participant_id -> (computed, reference, delta)
EXPECTED_DISCREPANCIES = {
    "AS2": (49916.00, 49500.00, 416.00),
    "Bank3": (11480.19, 11450.19, 30.00),
    "Bank5": (917.11, 921.11, -4.00),
    "PSP1": (1626.26, 1646.26, -20.00),
    "Bank_P": (38623.20, 38700.00, -76.80),
    "ACH_Gamma": (12260.00, 12320.00, -60.00),
}

EXPECTED_MATCHED = {
    "AS1", "Bank1", "Bank2", "Bank4", "Bank6", "Bank7",
    "ACH1", "AS_Alpha", "Bank_X", "Bank_Q", "Bank_T", "PSP_Beta",
}

EXPECTED_BG_AGGREGATES = {
    "BG1": {"leader_id": "Bank3", "total_payment_orders": 36788, "member_count": 3},
    "BG_Alpha": {"leader_id": "Bank_P", "total_payment_orders": 145000, "member_count": 2},
}

# Fee breakdown: participant_id -> (service, fixed, tx, bic, lt, other, total)
EXPECTED_FEE_BREAKDOWN = {
    "AS1": ("RTGS", 300.00, 6400.00, 0.00, 0.00, 3667.00, 10367.00),
    "AS2": ("RTGS", 3750.00, 37500.00, 0.00, 0.00, 8666.00, 49916.00),
    "Bank1": ("RTGS", 5000.00, 52250.00, 40.00, 4.00, 0.00, 57294.00),
    "Bank2": ("RTGS", 400.00, 2568.80, 80.00, 1.60, 0.00, 3050.40),
    "Bank3": ("RTGS", 5000.00, 6447.79, 30.00, 2.40, 0.00, 11480.19),
    "Bank4": ("RTGS", 400.00, 12251.07, 0.00, 2.40, 0.00, 12653.47),
    "Bank6": ("T2S", 0.00, 222.72, 0.00, 0.00, 0.00, 222.72),
    "PSP1": ("TIPS", 800.00, 826.26, 0.00, 0.00, 0.00, 1626.26),
    "ACH1": ("TIPS", 3000.00, 4138.20, 20.00, 0.00, 0.00, 7158.20),
    "ACH_Gamma": ("TIPS", 3000.00, 9200.00, 60.00, 0.00, 0.00, 12260.00),
}


# ============================================================
# Pipeline structure tests
# ============================================================

class TestPipelineStructure:
    def test_shell_script_exists(self):
        assert os.path.exists("/app/run_pipeline.sh"), "run_pipeline.sh not found"

    def test_shell_script_executable(self):
        assert os.access("/app/run_pipeline.sh", os.X_OK), (
            "run_pipeline.sh not executable"
        )

    def test_shell_script_has_shebang(self):
        with open("/app/run_pipeline.sh") as f:
            first_line = f.readline()
        assert first_line.startswith("#!"), "run_pipeline.sh must have a shebang line"

    def test_uses_sqlite3_cli(self):
        """run_pipeline.sh must invoke the sqlite3 CLI tool directly."""
        with open("/app/run_pipeline.sh") as f:
            content = f.read()
        # Strip comments
        lines = [
            l for l in content.split("\n")
            if l.strip() and not l.strip().startswith("#")
        ]
        non_comment = "\n".join(lines)
        assert "sqlite3" in non_comment, (
            "run_pipeline.sh must use the sqlite3 CLI tool"
        )


# ============================================================
# SQL view tests
# ============================================================

class TestBillingGroupView:
    @pytest.fixture(autouse=True)
    def setup(self):
        assert os.path.exists("/app/billing.db"), "billing.db not found"
        self.conn = sqlite3.connect("/app/billing.db")
        self.conn.row_factory = sqlite3.Row
        yield
        self.conn.close()

    def test_view_exists(self):
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='view' AND name='v_billing_group_aggregate'"
        )
        assert cursor.fetchone() is not None, (
            "View v_billing_group_aggregate not found in billing.db"
        )

    @pytest.mark.parametrize("gid,expected", list(EXPECTED_BG_AGGREGATES.items()))
    def test_aggregate_values(self, gid, expected):
        row = self.conn.execute(
            "SELECT * FROM v_billing_group_aggregate WHERE group_id=?",
            (gid,),
        ).fetchone()
        assert row is not None, f"No row for group {gid} in view"
        assert row["leader_id"] == expected["leader_id"], (
            f"{gid}: leader mismatch"
        )
        assert row["total_payment_orders"] == expected["total_payment_orders"], (
            f"{gid}: total_payment_orders expected "
            f"{expected['total_payment_orders']}, got {row['total_payment_orders']}"
        )
        assert row["member_count"] == expected["member_count"], (
            f"{gid}: member_count expected "
            f"{expected['member_count']}, got {row['member_count']}"
        )


# ============================================================
# Fee breakdown table tests
# ============================================================

class TestFeeBreakdown:
    @pytest.fixture(autouse=True)
    def setup(self):
        assert os.path.exists("/app/billing.db"), "billing.db not found"
        self.conn = sqlite3.connect("/app/billing.db")
        self.conn.row_factory = sqlite3.Row
        yield
        self.conn.close()

    def test_table_exists(self):
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='fee_breakdown'"
        )
        assert cursor.fetchone() is not None, (
            "Table fee_breakdown not found"
        )

    def test_row_count(self):
        count = self.conn.execute(
            "SELECT COUNT(*) FROM fee_breakdown"
        ).fetchone()[0]
        assert count >= 18, f"Expected at least 18 rows, got {count}"

    @pytest.mark.parametrize(
        "pid,expected", list(EXPECTED_FEE_BREAKDOWN.items())
    )
    def test_breakdown_values(self, pid, expected):
        row = self.conn.execute(
            "SELECT * FROM fee_breakdown WHERE participant_id=?",
            (pid,),
        ).fetchone()
        assert row is not None, f"No fee_breakdown row for {pid}"
        exp_svc, exp_fixed, exp_tx, exp_bic, exp_lt, exp_other, exp_total = expected
        assert row["service"] == exp_svc, (
            f"{pid}: service expected {exp_svc}, got {row['service']}"
        )
        assert abs(row["fixed_fee"] - exp_fixed) < TOL, (
            f"{pid}: fixed_fee expected {exp_fixed}, got {row['fixed_fee']}"
        )
        assert abs(row["transaction_fee"] - exp_tx) < TOL, (
            f"{pid}: transaction_fee expected {exp_tx}, got {row['transaction_fee']}"
        )
        assert abs(row["bic_fee"] - exp_bic) < TOL, (
            f"{pid}: bic_fee expected {exp_bic}, got {row['bic_fee']}"
        )
        assert abs(row["lt_fee"] - exp_lt) < TOL, (
            f"{pid}: lt_fee expected {exp_lt}, got {row['lt_fee']}"
        )
        assert abs(row["other_fee"] - exp_other) < TOL, (
            f"{pid}: other_fee expected {exp_other}, got {row['other_fee']}"
        )
        assert abs(row["total"] - exp_total) < TOL, (
            f"{pid}: total expected {exp_total}, got {row['total']}"
        )

    def test_total_equals_components(self):
        """Verify total ~ sum of components for all rows."""
        rows = self.conn.execute("SELECT * FROM fee_breakdown").fetchall()
        for row in rows:
            component_sum = (
                row["fixed_fee"] + row["transaction_fee"]
                + row["bic_fee"] + row["lt_fee"] + row["other_fee"]
            )
            assert abs(row["total"] - component_sum) < 0.02, (
                f"{row['participant_id']}: total {row['total']} != "
                f"component sum {component_sum}"
            )


# ============================================================
# Audit CSV tests
# ============================================================

class TestAuditCSV:
    @pytest.fixture(autouse=True)
    def setup(self):
        path = "/app/audit.csv"
        assert os.path.exists(path), "audit.csv not found"
        with open(path) as f:
            self.rows = list(csv.DictReader(f))

    def test_row_count(self):
        assert len(self.rows) >= 18, (
            f"Expected >= 18 data rows, got {len(self.rows)}"
        )

    def test_has_required_columns(self):
        required = {
            "participant_id", "service", "fixed_fee", "transaction_fee",
            "bic_fee", "lt_fee", "other_fee", "total",
        }
        actual = set(self.rows[0].keys())
        missing = required - actual
        assert not missing, f"Missing columns in audit.csv: {missing}"

    def test_sorted_by_participant_id(self):
        pids = [row["participant_id"] for row in self.rows]
        assert pids == sorted(pids), "audit.csv must be sorted by participant_id"

    def test_spot_check_as1(self):
        for row in self.rows:
            if row["participant_id"] == "AS1":
                assert abs(float(row["total"]) - 10367.00) < TOL
                assert abs(float(row["fixed_fee"]) - 300.00) < TOL
                assert abs(float(row["other_fee"]) - 3667.00) < TOL
                return
        pytest.fail("AS1 not found in audit.csv")

    def test_spot_check_bank3(self):
        for row in self.rows:
            if row["participant_id"] == "Bank3":
                assert abs(float(row["total"]) - 11480.19) < TOL
                assert abs(float(row["transaction_fee"]) - 6447.79) < TOL
                return
        pytest.fail("Bank3 not found in audit.csv")


# ============================================================
# Invoice total tests
# ============================================================

class TestInvoices:
    @pytest.fixture(autouse=True)
    def setup(self):
        path = "/app/invoices.json"
        assert os.path.exists(path), f"Output file not found: {path}"
        with open(path) as f:
            self.invoices = json.load(f)

    @pytest.mark.parametrize("pid,expected", list(EXPECTED_TOTALS.items()))
    def test_invoice_total(self, pid, expected):
        assert pid in self.invoices, f"Missing invoice for {pid}"
        actual = self.invoices[pid]["total"]
        assert abs(actual - expected) < TOL, (
            f"{pid}: expected {expected}, got {actual}"
        )

    def test_all_participants_present(self):
        for pid in EXPECTED_TOTALS:
            assert pid in self.invoices, f"Missing invoice for {pid}"

    def test_output_schema(self):
        for pid, inv in self.invoices.items():
            assert isinstance(inv, dict), f"{pid}: invoice must be a dict"
            assert "total" in inv, f"{pid}: missing 'total' field"
            assert isinstance(inv["total"], (int, float)), (
                f"{pid}: 'total' must be numeric"
            )


# ============================================================
# Reconciliation tests
# ============================================================

class TestReconciliation:
    @pytest.fixture(autouse=True)
    def setup(self):
        path = "/app/reconciliation.json"
        assert os.path.exists(path), f"Output file not found: {path}"
        with open(path) as f:
            self.recon = json.load(f)

    def test_has_required_keys(self):
        assert "discrepancies" in self.recon, "Missing 'discrepancies' key"
        assert "matched" in self.recon, "Missing 'matched' key"

    def test_discrepancy_count(self):
        assert len(self.recon["discrepancies"]) == len(EXPECTED_DISCREPANCIES), (
            f"Expected {len(EXPECTED_DISCREPANCIES)} discrepancies, "
            f"got {len(self.recon['discrepancies'])}"
        )

    def test_discrepancy_participants(self):
        disc_ids = {d["participant_id"] for d in self.recon["discrepancies"]}
        expected_ids = set(EXPECTED_DISCREPANCIES.keys())
        assert disc_ids == expected_ids, (
            f"Discrepancy participant mismatch: "
            f"extra={disc_ids - expected_ids}, "
            f"missing={expected_ids - disc_ids}"
        )

    @pytest.mark.parametrize(
        "pid,expected_vals",
        list(EXPECTED_DISCREPANCIES.items()),
    )
    def test_discrepancy_values(self, pid, expected_vals):
        exp_computed, exp_reference, exp_delta = expected_vals
        disc = None
        for d in self.recon["discrepancies"]:
            if d["participant_id"] == pid:
                disc = d
                break
        assert disc is not None, f"Missing discrepancy for {pid}"
        assert abs(disc["computed"] - exp_computed) < TOL, (
            f"{pid}: computed expected {exp_computed}, got {disc['computed']}"
        )
        assert abs(disc["reference"] - exp_reference) < TOL, (
            f"{pid}: reference expected {exp_reference}, "
            f"got {disc['reference']}"
        )
        assert abs(disc["delta"] - exp_delta) < TOL, (
            f"{pid}: delta expected {exp_delta}, got {disc['delta']}"
        )

    def test_matched_count(self):
        assert len(self.recon["matched"]) == len(EXPECTED_MATCHED), (
            f"Expected {len(EXPECTED_MATCHED)} matched, "
            f"got {len(self.recon['matched'])}"
        )

    def test_matched_participants(self):
        actual_matched = set(self.recon["matched"])
        assert actual_matched == EXPECTED_MATCHED, (
            f"Matched mismatch: "
            f"extra={actual_matched - EXPECTED_MATCHED}, "
            f"missing={EXPECTED_MATCHED - actual_matched}"
        )


# ============================================================
# Database structural tests
# ============================================================

class TestDatabase:
    def test_db_exists(self):
        assert os.path.exists("/app/billing.db"), "billing.db not found"

    def test_db_tables(self):
        conn = sqlite3.connect("/app/billing.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        required = {
            "participants", "billing_groups", "billing_group_members",
            "rtgs_bank_volumes", "rtgs_as_volumes", "t2s_activity",
            "tips_psp_volumes", "tips_ach_volumes", "fee_breakdown",
        }
        missing = required - tables
        assert not missing, f"Missing tables: {missing}"

    def test_participant_count(self):
        conn = sqlite3.connect("/app/billing.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM participants"
        ).fetchone()[0]
        conn.close()
        assert count >= 18, f"Expected at least 18 participants, got {count}"

    def test_billing_group_data(self):
        conn = sqlite3.connect("/app/billing.db")
        groups = conn.execute(
            "SELECT COUNT(*) FROM billing_groups"
        ).fetchone()[0]
        members = conn.execute(
            "SELECT COUNT(*) FROM billing_group_members"
        ).fetchone()[0]
        conn.close()
        assert groups >= 2, f"Expected at least 2 billing groups, got {groups}"
        assert members >= 5, (
            f"Expected at least 5 billing group members, got {members}"
        )


# ============================================================
# Dynamic test -- prevents hardcoding by inserting new
# participants and re-running the full pipeline
# ============================================================

class TestDynamic:
    @pytest.fixture(autouse=True, scope="class")
    def setup(self, request):
        # Append new participants to CSV files (runs once per class)
        with open("/app/data/participants.csv", "a") as f:
            f.write("DynTest_AS,ancillary_system,RTGS,A\n")
            f.write("DynTest_Bank,payment_bank,RTGS,A\n")

        with open("/app/data/rtgs_as_volumes.csv", "a") as f:
            f.write("DynTest_AS,8000,3500\n")

        with open("/app/data/rtgs_bank_volumes.csv", "a") as f:
            f.write("DynTest_Bank,5000,3,0,0,0,0\n")

        # Re-run the full pipeline
        result = subprocess.run(
            ["/app/run_pipeline.sh"],
            capture_output=True, text=True, cwd="/app",
        )
        assert result.returncode == 0, (
            f"Pipeline failed on dynamic re-run:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        with open("/app/invoices.json") as f:
            request.cls.invoices = json.load(f)

    def test_dynamic_as_total(self):
        """DynTest_AS: Option A, 8000 CTOs, GUV 3500M EUR"""
        pid = "DynTest_AS"
        assert pid in self.invoices, f"Missing invoice for {pid}"
        # Monthly=300 + CTO=8000*1.60 + FF_I=2000 + FF_II(3500M)=3334
        expected = 18434.00
        actual = self.invoices[pid]["total"]
        assert abs(actual - expected) < TOL, (
            f"{pid}: expected {expected}, got {actual}"
        )

    def test_dynamic_bank_total(self):
        """DynTest_Bank: Option A, 5000 POs, 3 addressable BICs"""
        pid = "DynTest_Bank"
        assert pid in self.invoices, f"Missing invoice for {pid}"
        # Monthly=400 + PO=5000*0.80 + BIC=3*20
        expected = 4460.00
        actual = self.invoices[pid]["total"]
        assert abs(actual - expected) < TOL, (
            f"{pid}: expected {expected}, got {actual}"
        )

    def test_existing_totals_preserved(self):
        """Verify existing participants still have correct totals."""
        spot_checks = {
            "AS1": 10367.00,
            "Bank1": 57294.00,
            "Bank6": 222.72,
            "PSP1": 1626.26,
            "ACH1": 7158.20,
        }
        for pid, expected in spot_checks.items():
            assert pid in self.invoices, f"Missing invoice for {pid}"
            actual = self.invoices[pid]["total"]
            assert abs(actual - expected) < TOL, (
                f"{pid} changed after dynamic insert: "
                f"expected {expected}, got {actual}"
            )

    def test_dynamic_fee_breakdown(self):
        """Verify fee_breakdown has entries for new participants."""
        conn = sqlite3.connect("/app/billing.db")
        conn.row_factory = sqlite3.Row
        for pid in ["DynTest_AS", "DynTest_Bank"]:
            row = conn.execute(
                "SELECT * FROM fee_breakdown WHERE participant_id=?",
                (pid,),
            ).fetchone()
            assert row is not None, f"No fee_breakdown for {pid}"
            component_sum = (
                row["fixed_fee"] + row["transaction_fee"]
                + row["bic_fee"] + row["lt_fee"] + row["other_fee"]
            )
            assert abs(row["total"] - component_sum) < 0.02, (
                f"{pid}: total != component sum"
            )
        conn.close()

    def test_dynamic_view_consistency(self):
        """v_billing_group_aggregate still correct after dynamic insert."""
        conn = sqlite3.connect("/app/billing.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM v_billing_group_aggregate WHERE group_id='BG1'"
        ).fetchone()
        assert row is not None, "BG1 missing from view after re-run"
        assert row["total_payment_orders"] == 36788, (
            f"BG1 total_payment_orders changed: {row['total_payment_orders']}"
        )
        assert row["member_count"] == 3, (
            f"BG1 member_count changed: {row['member_count']}"
        )
        conn.close()
