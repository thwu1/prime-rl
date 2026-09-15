
"""
Tests for COBOL VSAM-style indexed file transaction processor.
Verifies compilation, CRUD operations, browse by alternate key,
FILE STATUS handling, and audit log format.
"""

import subprocess
import os
import pytest
import shutil

APP_DIR = "/app"
COBOL_SRC = os.path.join(APP_DIR, "txnproc.cbl")
COBOL_BIN = os.path.join(APP_DIR, "txnproc")
TXN_FILE = os.path.join(APP_DIR, "transactions.dat")
AUDIT_FILE = os.path.join(APP_DIR, "audit.log")
INV_FILE = os.path.join(APP_DIR, "inventory.dat")


def clean_env():
    """Remove data files from previous runs."""
    for f in [TXN_FILE, AUDIT_FILE, INV_FILE]:
        if os.path.exists(f):
            os.remove(f)
    # Also remove any .dat lock files
    for f in os.listdir(APP_DIR):
        if f.endswith(".dat.lock") or f.endswith(".dat.lck"):
            os.remove(os.path.join(APP_DIR, f))


def write_txn_file(lines):
    """Write transaction file with fixed-width 120-char records."""
    with open(TXN_FILE, "w") as f:
        for line in lines:
            padded = line.ljust(120)[:120]
            f.write(padded + "\n")


def run_program():
    """Run the compiled COBOL program."""
    result = subprocess.run(
        [COBOL_BIN],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=30
    )
    return result


def read_audit():
    """Read audit log and return lines."""
    with open(AUDIT_FILE, "r") as f:
        return [line.rstrip() for line in f.readlines()]


def parse_audit_line(line):
    """Parse an audit line into parts: OP|KEY|STATUS|DETAIL"""
    parts = line.split("|", 3)
    return parts


def fmt_txn(op, item_code, category="", supplier="", desc="",
            price="0000000", qty="0000000"):
    """Format a transaction record.
    op: 3 chars, item_code: 10 chars, category: 15 chars,
    supplier: 8 chars, desc: 30 chars, price: 7 chars, qty: 7 chars
    """
    rec = (op.ljust(3)[:3] +
           item_code.ljust(10)[:10] +
           category.ljust(15)[:15] +
           supplier.ljust(8)[:8] +
           desc.ljust(30)[:30] +
           price.ljust(7)[:7] +
           qty.ljust(7)[:7])
    return rec.ljust(120)[:120]


class TestCompilation:
    def test_source_exists(self):
        assert os.path.exists(COBOL_SRC), "txnproc.cbl must exist at /app/"

    def test_compiles_successfully(self):
        result = subprocess.run(
            ["cobc", "-x", "-o", COBOL_BIN, COBOL_SRC],
            capture_output=True, text=True, cwd=APP_DIR
        )
        assert result.returncode == 0, (
            f"Compilation failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_binary_exists(self):
        # Compile first
        subprocess.run(
            ["cobc", "-x", "-o", COBOL_BIN, COBOL_SRC],
            capture_output=True, text=True, cwd=APP_DIR
        )
        assert os.path.exists(COBOL_BIN), "Compiled binary must exist at /app/txnproc"


class TestBasicCRUD:
    @pytest.fixture(autouse=True)
    def setup(self):
        subprocess.run(
            ["cobc", "-x", "-o", COBOL_BIN, COBOL_SRC],
            capture_output=True, text=True, cwd=APP_DIR
        )
        clean_env()

    def test_add_single_record(self):
        write_txn_file([
            fmt_txn("ADD", "ITEM000001", "ELECTRONICS", "SUP00001",
                    "Widget Alpha", "0100050", "0050000"),
        ])
        result = run_program()
        assert result.returncode == 0, f"Program failed: {result.stderr}"
        lines = read_audit()
        # Should have at least 2 lines: the ADD result + SUMMARY
        assert len(lines) >= 2
        parts = parse_audit_line(lines[0])
        assert parts[0].strip() == "ADD"
        assert parts[1].strip() == "ITEM000001"
        assert parts[2].strip() in ("00", "02")

    def test_add_and_query(self):
        write_txn_file([
            fmt_txn("ADD", "ITEM000010", "HARDWARE", "SUP00002",
                    "Bolt Set", "0005099", "1000000"),
            fmt_txn("QRY", "ITEM000010"),
        ])
        result = run_program()
        assert result.returncode == 0, f"Program failed: {result.stderr}"
        lines = read_audit()
        assert len(lines) >= 3  # ADD + QRY + SUMMARY

        qry_line = lines[1]
        parts = parse_audit_line(qry_line)
        assert parts[0].strip() == "QRY"
        assert parts[1].strip() == "ITEM000010"
        assert parts[2].strip() in ("00", "02")
        # Detail should contain the record fields
        detail = parts[3] if len(parts) > 3 else ""
        assert "HARDWARE" in detail
        assert "SUP00002" in detail

    def test_add_duplicate_key(self):
        write_txn_file([
            fmt_txn("ADD", "ITEM000020", "TOOLS", "SUP00003",
                    "Hammer", "0012000", "0200000"),
            fmt_txn("ADD", "ITEM000020", "TOOLS", "SUP00003",
                    "Hammer Dup", "0012000", "0200000"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()
        assert len(lines) >= 3  # ADD + ADD(dup) + SUMMARY
        dup_parts = parse_audit_line(lines[1])
        assert dup_parts[0].strip() == "ADD"
        assert dup_parts[2].strip() == "22"

    def test_update_existing(self):
        write_txn_file([
            fmt_txn("ADD", "ITEM000030", "PLUMBING", "SUP00004",
                    "Pipe Fitting", "0003050", "0500000"),
            fmt_txn("UPD", "ITEM000030", "PLUMBING", "SUP00004",
                    "Pipe Fitting XL", "0004050", "0450000"),
            fmt_txn("QRY", "ITEM000030"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()
        assert len(lines) >= 4  # ADD + UPD + QRY + SUMMARY

        upd_parts = parse_audit_line(lines[1])
        assert upd_parts[0].strip() == "UPD"
        assert upd_parts[2].strip() in ("00", "02")

        qry_parts = parse_audit_line(lines[2])
        detail = qry_parts[3] if len(qry_parts) > 3 else ""
        assert "Pipe Fitting XL" in detail

    def test_update_nonexistent(self):
        write_txn_file([
            fmt_txn("UPD", "ITEM999999", "NONE", "SUP00000",
                    "Ghost Item", "0000000", "0000000"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()
        assert len(lines) >= 2
        parts = parse_audit_line(lines[0])
        assert parts[0].strip() == "UPD"
        assert parts[2].strip() == "23"

    def test_delete_existing(self):
        write_txn_file([
            fmt_txn("ADD", "ITEM000040", "ELECTRICAL", "SUP00005",
                    "Wire Spool", "0025000", "0100000"),
            fmt_txn("DEL", "ITEM000040"),
            fmt_txn("QRY", "ITEM000040"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()
        assert len(lines) >= 4

        del_parts = parse_audit_line(lines[1])
        assert del_parts[0].strip() == "DEL"
        assert del_parts[2].strip() in ("00", "02")

        qry_parts = parse_audit_line(lines[2])
        assert qry_parts[0].strip() == "QRY"
        assert qry_parts[2].strip() == "23"

    def test_delete_nonexistent(self):
        write_txn_file([
            fmt_txn("DEL", "ITEM888888"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()
        parts = parse_audit_line(lines[0])
        assert parts[0].strip() == "DEL"
        assert parts[2].strip() == "23"


class TestBrowse:
    @pytest.fixture(autouse=True)
    def setup(self):
        subprocess.run(
            ["cobc", "-x", "-o", COBOL_BIN, COBOL_SRC],
            capture_output=True, text=True, cwd=APP_DIR
        )
        clean_env()

    def test_browse_by_category_multiple(self):
        """Browse should find all records matching a category."""
        write_txn_file([
            fmt_txn("ADD", "ITEM000100", "FASTENERS", "SUP00010",
                    "Bolt M6", "0000250", "5000000"),
            fmt_txn("ADD", "ITEM000101", "FASTENERS", "SUP00011",
                    "Nut M6", "0000100", "8000000"),
            fmt_txn("ADD", "ITEM000102", "FASTENERS", "SUP00010",
                    "Washer M6", "0000050", "9000000"),
            fmt_txn("ADD", "ITEM000103", "ADHESIVES", "SUP00012",
                    "Epoxy", "0005000", "0200000"),
            fmt_txn("BRW", "BROWSECAT1", "FASTENERS"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()

        brw_lines = [l for l in lines
                     if l.strip().startswith("BRW")]
        # Should find exactly 3 FASTENERS records
        assert len(brw_lines) == 3, (
            f"Expected 3 BRW lines for FASTENERS, got {len(brw_lines)}: {brw_lines}"
        )
        for bl in brw_lines:
            parts = parse_audit_line(bl)
            assert parts[2].strip() in ("00", "02")
            assert "FASTENERS" in (parts[3] if len(parts) > 3 else "")

    def test_browse_by_supplier(self):
        """When category is spaces, browse by supplier ID."""
        write_txn_file([
            fmt_txn("ADD", "ITEM000200", "WIDGETS", "SUP00020",
                    "Gizmo A", "0010000", "0300000"),
            fmt_txn("ADD", "ITEM000201", "GADGETS", "SUP00020",
                    "Gizmo B", "0015000", "0250000"),
            fmt_txn("ADD", "ITEM000202", "WIDGETS", "SUP00021",
                    "Thingamajig", "0020000", "0100000"),
            # BRW with empty category triggers supplier browse
            fmt_txn("BRW", "BROWSESUP1", "", "SUP00020"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()

        brw_lines = [l for l in lines
                     if l.strip().startswith("BRW")]
        assert len(brw_lines) == 2, (
            f"Expected 2 BRW lines for SUP00020, got {len(brw_lines)}: {brw_lines}"
        )
        for bl in brw_lines:
            parts = parse_audit_line(bl)
            detail = parts[3] if len(parts) > 3 else ""
            assert "SUP00020" in detail

    def test_browse_no_match(self):
        """Browse for nonexistent category yields single failure line."""
        write_txn_file([
            fmt_txn("ADD", "ITEM000300", "EXISTING", "SUP00030",
                    "Real Item", "0001000", "0010000"),
            fmt_txn("BRW", "BRWNOMAT1", "NONEXIST"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()

        brw_lines = [l for l in lines
                     if l.strip().startswith("BRW")]
        assert len(brw_lines) == 1
        parts = parse_audit_line(brw_lines[0])
        assert parts[2].strip() == "23"


class TestSummary:
    @pytest.fixture(autouse=True)
    def setup(self):
        subprocess.run(
            ["cobc", "-x", "-o", COBOL_BIN, COBOL_SRC],
            capture_output=True, text=True, cwd=APP_DIR
        )
        clean_env()

    def test_empty_transaction_file(self):
        """Empty transactions.dat should produce only summary line with zeros."""
        write_txn_file([])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()
        assert len(lines) >= 1
        summary = lines[-1]
        parts = summary.split("|")
        assert parts[0].strip() == "SUMMARY"
        assert int(parts[1].strip()) == 0
        assert int(parts[2].strip()) == 0
        assert int(parts[3].strip()) == 0

    def test_summary_counts(self):
        """Summary must accurately count successes and failures."""
        write_txn_file([
            fmt_txn("ADD", "ITEM000400", "CATEGORY1", "SUP00040",
                    "Item One", "0010000", "0100000"),
            fmt_txn("ADD", "ITEM000401", "CATEGORY1", "SUP00041",
                    "Item Two", "0020000", "0200000"),
            fmt_txn("ADD", "ITEM000400", "CATEGORY1", "SUP00040",
                    "Duplicate", "0010000", "0100000"),  # dup key = fail
            fmt_txn("DEL", "ITEM777777"),  # not found = fail
            fmt_txn("QRY", "ITEM000401"),  # success
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()
        summary = lines[-1]
        parts = summary.split("|")
        assert parts[0].strip() == "SUMMARY"
        total = int(parts[1].strip())
        success = int(parts[2].strip())
        failed = int(parts[3].strip())
        assert total == 5
        assert success == 3  # 2 ADDs + 1 QRY
        assert failed == 2   # 1 dup ADD + 1 DEL not found
        assert total == success + failed


class TestAuditFormat:
    @pytest.fixture(autouse=True)
    def setup(self):
        subprocess.run(
            ["cobc", "-x", "-o", COBOL_BIN, COBOL_SRC],
            capture_output=True, text=True, cwd=APP_DIR
        )
        clean_env()

    def test_audit_line_format(self):
        """Each audit line must follow OP|KEY|STATUS|DETAIL format."""
        write_txn_file([
            fmt_txn("ADD", "ITEM000500", "TESTCAT", "SUP00050",
                    "Test Item", "0099099", "0001000"),
            fmt_txn("QRY", "ITEM000500"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split("|")
            assert len(parts) >= 3, f"Malformed audit line: {stripped}"
            op = parts[0].strip()
            assert op in ("ADD", "UPD", "DEL", "QRY", "BRW", "ERR", "SUMMARY"), \
                f"Unknown op code in audit: {op}"

    def test_qry_detail_has_semicolons(self):
        """QRY detail must have format: CAT;SUP;DESC;PRICE;QTY"""
        write_txn_file([
            fmt_txn("ADD", "ITEM000600", "MYCAT", "SUP00060",
                    "My Description", "0123456", "0654321"),
            fmt_txn("QRY", "ITEM000600"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()

        qry_lines = [l for l in lines if l.strip().startswith("QRY")]
        assert len(qry_lines) == 1
        parts = parse_audit_line(qry_lines[0])
        detail = parts[3] if len(parts) > 3 else ""
        semicolons = detail.count(";")
        assert semicolons == 4, (
            f"QRY detail must have 4 semicolons (CAT;SUP;DESC;PRICE;QTY), "
            f"got {semicolons}: '{detail}'"
        )


class TestEdgeCases:
    @pytest.fixture(autouse=True)
    def setup(self):
        subprocess.run(
            ["cobc", "-x", "-o", COBOL_BIN, COBOL_SRC],
            capture_output=True, text=True, cwd=APP_DIR
        )
        clean_env()

    def test_multiple_operations_sequence(self):
        """Full CRUD cycle: add, query, update, query, delete, query."""
        write_txn_file([
            fmt_txn("ADD", "ITEM000700", "LIFECYCLE", "SUP00070",
                    "Lifecycle Item", "0050000", "0100000"),
            fmt_txn("QRY", "ITEM000700"),
            fmt_txn("UPD", "ITEM000700", "LIFECYCLE", "SUP00070",
                    "Updated Item", "0060000", "0090000"),
            fmt_txn("QRY", "ITEM000700"),
            fmt_txn("DEL", "ITEM000700"),
            fmt_txn("QRY", "ITEM000700"),
        ])
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()
        # Expect: ADD, QRY(found), UPD, QRY(found-updated), DEL, QRY(not-found), SUMMARY
        assert len(lines) >= 7

        # First QRY should find "Lifecycle Item"
        qry1 = parse_audit_line(lines[1])
        assert qry1[2].strip() in ("00", "02")
        assert "Lifecycle Item" in (qry1[3] if len(qry1) > 3 else "")

        # Second QRY should find "Updated Item"
        qry2 = parse_audit_line(lines[3])
        assert qry2[2].strip() in ("00", "02")
        assert "Updated Item" in (qry2[3] if len(qry2) > 3 else "")

        # Third QRY should not find (after delete)
        qry3 = parse_audit_line(lines[5])
        assert qry3[2].strip() == "23"

    def test_add_many_then_browse(self):
        """Add 10 records in same category, browse should find all 10."""
        txns = []
        for i in range(10):
            txns.append(fmt_txn(
                "ADD", f"ITEMB{i:05d}", "BULKCAT", "SUP00080",
                f"Bulk Item {i:03d}", "0001000", "0010000"
            ))
        txns.append(fmt_txn("BRW", "BRWBULK01", "BULKCAT"))
        write_txn_file(txns)
        result = run_program()
        assert result.returncode == 0
        lines = read_audit()

        brw_lines = [l for l in lines if l.strip().startswith("BRW")]
        assert len(brw_lines) == 10, (
            f"Expected 10 BRW lines for BULKCAT, got {len(brw_lines)}"
        )
