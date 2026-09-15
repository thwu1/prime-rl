"""
Tests for the NACHA ACH file pipeline: merger + validator.

Generates test ACH files with known values, runs the pipeline,
and validates both the merged output and the JSON validation report.
"""

import json
import os
import subprocess
import tempfile

import pytest

RECORD_LENGTH = 94


# ---------------------------------------------------------------------------
# ACH record builder helpers
# ---------------------------------------------------------------------------

def ljust(s, width):
    """Left-justify string, pad with spaces, truncate if too long."""
    return str(s).ljust(width)[:width]


def zfill(n, width):
    """Zero-pad integer to width, keeping only the rightmost digits if overflow."""
    return str(int(n)).zfill(width)[-width:]


def make_file_header(dest_rt, origin_rt, date, time_str, modifier,
                     dest_name, origin_name, ref=""):
    rec = ("1" + "01"
           + " " + dest_rt
           + " " + origin_rt
           + date + time_str + modifier
           + "094" + "10" + "1"
           + ljust(dest_name, 23)
           + ljust(origin_name, 23)
           + ljust(ref, 8))
    assert len(rec) == RECORD_LENGTH, f"file header len={len(rec)}"
    return rec


def make_batch_header(scc, co_name, disc, co_id, sec, entry_desc,
                      desc_date, eff_date, settle, orig_status,
                      odfi_id, batch_num):
    rec = ("5" + str(scc)
           + ljust(co_name, 16) + ljust(disc, 20)
           + ljust(co_id, 10) + sec + ljust(entry_desc, 10)
           + ljust(desc_date, 6) + ljust(eff_date, 6)
           + ljust(settle, 3) + str(orig_status)
           + ljust(odfi_id, 8) + zfill(batch_num, 7))
    assert len(rec) == RECORD_LENGTH, f"batch header len={len(rec)}"
    return rec


def make_entry(tc, rdfi, chk, acct, amount, indiv_id, indiv_name,
               disc, addenda_ind, trace):
    rec = ("6" + str(tc)
           + ljust(rdfi, 8) + str(chk)
           + ljust(acct, 17) + zfill(amount, 10)
           + ljust(indiv_id, 15) + ljust(indiv_name, 22)
           + ljust(disc, 2) + str(addenda_ind)
           + ljust(trace, 15))
    assert len(rec) == RECORD_LENGTH, f"entry len={len(rec)}"
    return rec


def make_addenda05(info, seq, entry_seq):
    rec = ("7" + "05"
           + ljust(info, 80) + zfill(seq, 4) + zfill(entry_seq, 7))
    assert len(rec) == RECORD_LENGTH, f"addenda len={len(rec)}"
    return rec


def make_batch_control(scc, ea_count, entry_hash, total_debit,
                       total_credit, co_id, odfi_id, batch_num):
    rec = ("8" + str(scc)
           + zfill(ea_count, 6) + zfill(entry_hash, 10)
           + zfill(total_debit, 12) + zfill(total_credit, 12)
           + ljust(co_id, 10) + ljust("", 19) + ljust("", 6)
           + ljust(odfi_id, 8) + zfill(batch_num, 7))
    assert len(rec) == RECORD_LENGTH, f"batch control len={len(rec)}"
    return rec


def make_file_control(batch_count, block_count, ea_count, entry_hash,
                      total_debit, total_credit):
    rec = ("9"
           + zfill(batch_count, 6) + zfill(block_count, 6)
           + zfill(ea_count, 8) + zfill(entry_hash, 10)
           + zfill(total_debit, 12) + zfill(total_credit, 12)
           + ljust("", 39))
    assert len(rec) == RECORD_LENGTH, f"file control len={len(rec)}"
    return rec


PADDING = "9" * RECORD_LENGTH


def pad_to_block(lines):
    """Append padding records so total line count is a multiple of 10."""
    remainder = len(lines) % 10
    if remainder != 0:
        lines.extend([PADDING] * (10 - remainder))
    return lines


def write_ach(path, lines):
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Test data generation -- clean files (for merge tests)
# ---------------------------------------------------------------------------

def generate_test_files(outdir):
    """Generate three clean ACH files with known, verifiable control values."""
    os.makedirs(outdir, exist_ok=True)

    # -- File 1: PPD mixed (200), 1 batch, 2 entries --
    # Entry 1: Checking Credit (22), RDFI 09100001 chk 9, $1500.00
    # Entry 2: Checking Debit  (27), RDFI 09100001 chk 9, $750.00
    # Batch hash = 09100001 + 09100001 = 18200002
    # Debit = 75000, Credit = 150000
    lines = pad_to_block([
        make_file_header("091000019", "091000019", "260101", "1200", "A",
                         "Federal Reserve Bank", "ACME Corp"),
        make_batch_header(200, "ACME Corp", "", "1233456789", "PPD",
                          "PAYROLL", "260101", "260102", "", 1,
                          "09100001", 1),
        make_entry(22, "09100001", 9, "12345678900", 150000, "EMP001",
                   "John Smith", "", 0, "091000010000001"),
        make_entry(27, "09100001", 9, "98765432100", 75000, "EMP002",
                   "Jane Doe", "", 0, "091000010000002"),
        make_batch_control(200, 2, 18200002, 75000, 150000, "1233456789",
                           "09100001", 1),
        make_file_control(1, 1, 2, 18200002, 75000, 150000),
    ])
    write_ach(os.path.join(outdir, "file1.ach"), lines)

    # -- File 2: WEB debits only (225), 1 batch, 2 entries + 1 addenda --
    # Entry 1: Checking Debit (27), RDFI 09100001 chk 9, $250.00, has addenda
    # Entry 2: Checking Debit (27), RDFI 09100001 chk 9, $189.99
    # Batch hash = 09100001 + 09100001 = 18200002
    # EA count = 3 (2 entries + 1 addenda)
    # Debit = 43999, Credit = 0
    lines = pad_to_block([
        make_file_header("091000019", "091000019", "260105", "1430", "A",
                         "Federal Reserve Bank", "WebPay Inc"),
        make_batch_header(225, "WebPay Inc", "", "9876543210", "WEB",
                          "TRANSFER", "260105", "260106", "", 1,
                          "09100001", 1),
        make_entry(27, "09100001", 9, "11223344556", 25000, "WEBPAY-001",
                   "Alice Williams", "S", 1, "091000010000001"),
        make_addenda05("Payment for invoice 12345 online transaction",
                       1, 1),
        make_entry(27, "09100001", 9, "55667788900", 18999, "WEBPAY-002",
                   "Carlos Martinez", "S", 0, "091000010000002"),
        make_batch_control(225, 3, 18200002, 43999, 0, "9876543210",
                           "09100001", 1),
        make_file_control(1, 1, 3, 18200002, 43999, 0),
    ])
    write_ach(os.path.join(outdir, "file2.ach"), lines)

    # -- File 3: 2 batches --
    # Batch 1: CCD credits only (220), 1 entry
    #   Entry 1: Checking Credit (22), RDFI 09100001 chk 9, $5000.00
    #   Batch hash = 9100001, Debit = 0, Credit = 500000
    # Batch 2: PPD debits only (225), 2 entries
    #   Entry 1: Checking Debit (27), RDFI 09100001 chk 9, $1200.00
    #   Entry 2: Checking Debit (27), RDFI 09100001 chk 9, $800.00
    #   Batch hash = 09100001 + 09100001 = 18200002
    #   Debit = 200000, Credit = 0
    # File hash = 9100001 + 18200002 = 27300003
    # File Debit = 200000, File Credit = 500000
    lines = pad_to_block([
        make_file_header("091000019", "091000019", "260110", "1000", "A",
                         "Federal Reserve Bank", "Multi Corp Inc"),
        make_batch_header(220, "Multi Corp Inc", "", "5551234567", "CCD",
                          "INVOICE", "260110", "260111", "", 1,
                          "09100001", 1),
        make_entry(22, "09100001", 9, "VENDORACCT001", 500000,
                   "INV20260001", "Vendor Services LLC", "", 0,
                   "091000010000001"),
        make_batch_control(220, 1, 9100001, 0, 500000, "5551234567",
                           "09100001", 1),
        make_batch_header(225, "Multi Corp Inc", "", "5551234567", "PPD",
                          "LOAN PMT", "260110", "260111", "", 1,
                          "09100001", 2),
        make_entry(27, "09100001", 9, "12345678901", 120000, "LOAN001",
                   "David Park", "", 0, "091000010000001"),
        make_entry(27, "09100001", 9, "98765000011", 80000, "LOAN002",
                   "Emily Chen", "", 0, "091000010000002"),
        make_batch_control(225, 2, 18200002, 200000, 0, "5551234567",
                           "09100001", 2),
        make_file_control(2, 1, 3, 27300003, 200000, 500000),
    ])
    write_ach(os.path.join(outdir, "file3.ach"), lines)


# ---------------------------------------------------------------------------
# Test data generation -- error file (for validation tests)
# ---------------------------------------------------------------------------

def generate_validation_file(outdir):
    """Generate an ACH file with known validation errors for testing.

    Batch 1 (clean, SCC=200 mixed):
      Entry 1: TC=22 credit, RDFI=09100001, check=9, routing=091000019 (ABA valid)
      Entry 2: TC=27 debit,  RDFI=09100001, check=9, routing=091000019 (ABA valid)
      Both valid: no SCC errors (200=mixed), valid check digits, amounts OK

    Batch 2 (SCC=225 debits only, but has credit + bad check digit):
      Entry 1: TC=22 credit (SCC mismatch!), RDFI=07300000, check=0,
               routing=073000000 (ABA INVALID: weighted=52, 52%10!=0;
               but simple sum=10, 10%10==0 -- so buggy validator misses it)
      Expected: CHECKDIGIT + SCC_MISMATCH

    Batch 3 (SCC=225 debits only, amount over limit + duplicate trace):
      Entry 1: TC=27 debit, RDFI=09100001, amount=$30M (3000000000 > 2500000000)
               trace=091000010000001
      Entry 2: TC=27 debit, RDFI=09100001, amount=$1000
               trace=091000010000001 (DUPLICATE!)
      Expected: AMOUNT_RANGE + DUPLICATE_TRACE

    Batch 4 (SCC=200 mixed, addenda + trace issues):
      Entry 1: addenda_ind=1, 1 addenda, trace=091000010000001. All clean.
      Entry 2: addenda_ind=1, 1 addenda, trace=091000010000002. Clean.
      Entry 3: addenda_ind=0, 1 addenda follows -> ADDENDA_IND error.
               trace=191000010000003 (prefix 19100001 != ODFI 09100001) -> TRACE_ODFI
      Entry 4: addenda_ind=0, no addenda, trace=091000010000004. Clean.
      Expected: ADDENDA_IND + TRACE_ODFI
    """
    os.makedirs(outdir, exist_ok=True)

    lines = pad_to_block([
        make_file_header("091000019", "091000019", "260201", "0900", "A",
                         "Test Bank", "Test Corp"),
        # Batch 1: clean
        make_batch_header(200, "Test Corp", "", "1234567890", "PPD",
                          "TEST", "260201", "260202", "", 1, "09100001", 1),
        make_entry(22, "09100001", 9, "11111111111", 50000, "TEST001",
                   "Clean Credit", "", 0, "091000010000001"),
        make_entry(27, "09100001", 9, "22222222222", 30000, "TEST002",
                   "Clean Debit", "", 0, "091000010000002"),
        make_batch_control(200, 2, 18200002, 30000, 50000, "1234567890",
                           "09100001", 1),
        # Batch 2: bad check digit + SCC mismatch
        make_batch_header(225, "Test Corp", "", "1234567890", "PPD",
                          "TEST", "260201", "260202", "", 1, "09100001", 2),
        make_entry(22, "07300000", 0, "33333333333", 25000, "TEST003",
                   "Bad Checkdigit", "", 0, "091000010000001"),
        make_batch_control(225, 1, 7300000, 0, 25000, "1234567890",
                           "09100001", 2),
        # Batch 3: amount over limit + duplicate trace
        make_batch_header(225, "Test Corp", "", "1234567890", "PPD",
                          "TEST", "260201", "260202", "", 1, "09100001", 3),
        make_entry(27, "09100001", 9, "44444444444", 3000000000, "TEST004",
                   "Over Limit", "", 0, "091000010000001"),
        make_entry(27, "09100001", 9, "55555555555", 100000, "TEST005",
                   "Dup Trace", "", 0, "091000010000001"),
        make_batch_control(225, 2, 18200002, 3000100000, 0, "1234567890",
                           "09100001", 3),
        # Batch 4: addenda indicator + trace ODFI issues
        make_batch_header(200, "Test Corp", "", "1234567890", "PPD",
                          "TEST", "260201", "260202", "", 1, "09100001", 4),
        make_entry(22, "09100001", 9, "66666666666", 50000, "TEST006",
                   "Add Entry 1", "", 1, "091000010000001"),
        make_addenda05("Addenda info for entry 1", 1, 1),
        make_entry(27, "09100001", 9, "77777777777", 30000, "TEST007",
                   "Add Entry 2", "", 1, "091000010000002"),
        make_addenda05("Addenda info for entry 2", 1, 2),
        make_entry(27, "09100001", 9, "88888888888", 20000, "TEST008",
                   "Bad Indicator", "", 0, "191000010000003"),
        make_addenda05("Addenda for bad indicator entry", 1, 3),
        make_entry(27, "09100001", 9, "99999999999", 10000, "TEST009",
                   "Clean No Add", "", 0, "091000010000004"),
        make_batch_control(200, 7, 36400004, 60000, 50000, "1234567890",
                           "09100001", 4),
        make_file_control(4, 3, 12, 80100008, 3000190000, 125000),
    ])
    write_ach(os.path.join(outdir, "errors.ach"), lines)


# ---------------------------------------------------------------------------
# Expected merged values (clean files)
# ---------------------------------------------------------------------------

# Merged file has 4 batches (renumbered 1-4):
#   Batch 1 (from file1): PPD 200, EA=2, hash=18200002, D=75000,   C=150000
#   Batch 2 (from file2): WEB 225, EA=3, hash=18200002, D=43999,   C=0
#   Batch 3 (from file3 b1): CCD 220, EA=1, hash=9100001, D=0,     C=500000
#   Batch 4 (from file3 b2): PPD 225, EA=2, hash=18200002, D=200000, C=0
#
# File control:
#   Batch count = 4
#   Records = 1(fh) + 4+5+3+4 (batches) + 1(fc) = 18 -> pad to 20
#   Block count = 2
#   EA count = 2+3+1+2 = 8
#   Entry hash = 18200002+18200002+9100001+18200002 = 63700007
#   Total debit = 75000+43999+0+200000 = 318999
#   Total credit = 150000+0+500000+0 = 650000

EXPECTED_BATCH_EA = [2, 3, 1, 2]
EXPECTED_BATCH_HASH = [18200002, 18200002, 9100001, 18200002]
EXPECTED_BATCH_DEBIT = [75000, 43999, 0, 200000]
EXPECTED_BATCH_CREDIT = [150000, 0, 500000, 0]
EXPECTED_BATCH_SCC = ["200", "225", "220", "225"]
EXPECTED_BATCH_COID = ["1233456789", "9876543210", "5551234567", "5551234567"]

EXPECTED_FILE_BATCH_COUNT = 4
EXPECTED_FILE_BLOCK_COUNT = 2
EXPECTED_FILE_EA_COUNT = 8
EXPECTED_FILE_ENTRY_HASH = 63700007
EXPECTED_FILE_TOTAL_DEBIT = 318999
EXPECTED_FILE_TOTAL_CREDIT = 650000
EXPECTED_TOTAL_RECORDS = 20  # 18 real + 2 padding
EXPECTED_PADDING_COUNT = 2

# Expected validation errors in the error test file
EXPECTED_VAL_TOTAL_ERRORS = 6
EXPECTED_VAL_CHECKDIGIT_COUNT = 1
EXPECTED_VAL_CHECKDIGIT_BATCH = 2
EXPECTED_VAL_SCC_MISMATCH_COUNT = 1
EXPECTED_VAL_SCC_MISMATCH_BATCH = 2
EXPECTED_VAL_AMOUNT_RANGE_COUNT = 1
EXPECTED_VAL_AMOUNT_RANGE_BATCH = 3
EXPECTED_VAL_DUP_TRACE_COUNT = 1
EXPECTED_VAL_DUP_TRACE_BATCH = 3
EXPECTED_VAL_ADDENDA_IND_COUNT = 1
EXPECTED_VAL_ADDENDA_IND_BATCH = 4
EXPECTED_VAL_ADDENDA_IND_ENTRY_SEQ = 3
EXPECTED_VAL_TRACE_ODFI_COUNT = 1
EXPECTED_VAL_TRACE_ODFI_BATCH = 4
EXPECTED_VAL_TRACE_ODFI_ENTRY_SEQ = 3
EXPECTED_VAL_ADDENDA_SEQ_COUNT = 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def binary():
    """Build the Go program and return the binary path."""
    result = subprocess.run(
        ["go", "build", "-o", "/app/achpipe", "."],
        cwd="/app", capture_output=True, text=True,
    )
    assert result.returncode == 0, f"go build failed:\n{result.stderr}"
    return "/app/achpipe"


@pytest.fixture(scope="module")
def clean_run(binary):
    """Run pipeline on clean files, return (merged_lines, report_dict)."""
    tmpdir = tempfile.mkdtemp(prefix="ach_clean_")
    indir = os.path.join(tmpdir, "input")
    outfile = os.path.join(tmpdir, "merged.ach")
    reportfile = os.path.join(tmpdir, "report.json")

    generate_test_files(indir)

    result = subprocess.run(
        [binary, "--input", indir, "--output", outfile, "--report", reportfile],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"achpipe failed:\n{result.stderr}"

    with open(outfile) as f:
        lines = [line.rstrip("\n") for line in f.readlines()]

    with open(reportfile) as f:
        report = json.load(f)

    return lines, report


@pytest.fixture(scope="module")
def merged_records(clean_run):
    """Return merged output lines from the clean run."""
    return clean_run[0]


@pytest.fixture(scope="module")
def clean_report(clean_run):
    """Return the validation report from the clean run."""
    return clean_run[1]


@pytest.fixture(scope="module")
def error_report(binary):
    """Run pipeline on the error file, return the validation report dict."""
    tmpdir = tempfile.mkdtemp(prefix="ach_val_")
    indir = os.path.join(tmpdir, "input")
    outfile = os.path.join(tmpdir, "merged.ach")
    reportfile = os.path.join(tmpdir, "report.json")

    generate_validation_file(indir)

    result = subprocess.run(
        [binary, "--input", indir, "--output", outfile, "--report", reportfile],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"achpipe failed:\n{result.stderr}"

    with open(reportfile) as f:
        report = json.load(f)

    return report


def get_batches(records):
    """Extract structured batches from a list of records."""
    batches = []
    current = None
    for rec in records:
        if len(rec) < 1:
            continue
        rt = rec[0]
        if rt == "5":
            current = {"header": rec, "entries": [], "control": None}
        elif rt in ("6", "7"):
            if current is not None:
                current["entries"].append(rec)
        elif rt == "8":
            if current is not None:
                current["control"] = rec
                batches.append(current)
                current = None
    return batches


def get_file_control(records):
    """Return the file control record (type 9 that is NOT all-9s padding)."""
    for rec in records:
        if len(rec) == RECORD_LENGTH and rec[0] == "9" and rec != PADDING:
            return rec
    return None


# ---------------------------------------------------------------------------
# Tests -- Record Format
# ---------------------------------------------------------------------------

class TestRecordFormat:
    def test_all_records_94_chars(self, merged_records):
        for i, line in enumerate(merged_records):
            assert len(line) == RECORD_LENGTH, (
                f"Record {i} has {len(line)} chars, expected {RECORD_LENGTH}"
            )

    def test_total_lines_multiple_of_10(self, merged_records):
        assert len(merged_records) % 10 == 0

    def test_total_lines(self, merged_records):
        assert len(merged_records) == EXPECTED_TOTAL_RECORDS

    def test_file_header_type(self, merged_records):
        assert merged_records[0][0] == "1"


# ---------------------------------------------------------------------------
# Tests -- Batch Structure
# ---------------------------------------------------------------------------

class TestBatchStructure:
    def test_batch_count(self, merged_records):
        batches = get_batches(merged_records)
        assert len(batches) == EXPECTED_FILE_BATCH_COUNT

    def test_batch_numbers_sequential(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            bn = int(b["header"][87:94])
            assert bn == i + 1, (
                f"Batch {i} header number={bn}, expected {i + 1}"
            )

    def test_batch_header_control_numbers_match(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            hdr_num = int(b["header"][87:94])
            ctl_num = int(b["control"][87:94])
            assert hdr_num == ctl_num, (
                f"Batch {i}: header batch#={hdr_num}, control batch#={ctl_num}"
            )

    def test_service_class_codes_match(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            hdr_scc = b["header"][1:4]
            ctl_scc = b["control"][1:4]
            assert hdr_scc == ctl_scc, (
                f"Batch {i}: header SCC={hdr_scc}, control SCC={ctl_scc}"
            )

    def test_service_class_code_values(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            scc = b["control"][1:4]
            assert scc == EXPECTED_BATCH_SCC[i], (
                f"Batch {i}: SCC={scc}, expected {EXPECTED_BATCH_SCC[i]}"
            )


# ---------------------------------------------------------------------------
# Tests -- Batch Control
# ---------------------------------------------------------------------------

class TestBatchControl:
    def test_entry_addenda_counts(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            eac = int(b["control"][4:10])
            assert eac == EXPECTED_BATCH_EA[i], (
                f"Batch {i}: EA count={eac}, expected {EXPECTED_BATCH_EA[i]}"
            )

    def test_entry_hashes(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            eh = int(b["control"][10:20])
            assert eh == EXPECTED_BATCH_HASH[i], (
                f"Batch {i}: entry hash={eh}, expected {EXPECTED_BATCH_HASH[i]}"
            )

    def test_debit_amounts(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            td = int(b["control"][20:32])
            assert td == EXPECTED_BATCH_DEBIT[i], (
                f"Batch {i}: total debit={td}, expected {EXPECTED_BATCH_DEBIT[i]}"
            )

    def test_credit_amounts(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            tc = int(b["control"][32:44])
            assert tc == EXPECTED_BATCH_CREDIT[i], (
                f"Batch {i}: total credit={tc}, expected {EXPECTED_BATCH_CREDIT[i]}"
            )

    def test_company_identification(self, merged_records):
        batches = get_batches(merged_records)
        for i, b in enumerate(batches):
            coid = b["control"][44:54].strip()
            assert coid == EXPECTED_BATCH_COID[i], (
                f"Batch {i}: company ID='{coid}', expected '{EXPECTED_BATCH_COID[i]}'"
            )


# ---------------------------------------------------------------------------
# Tests -- File Control
# ---------------------------------------------------------------------------

class TestFileControl:
    def test_batch_count(self, merged_records):
        fc = get_file_control(merged_records)
        assert fc is not None, "No file control record found"
        bc = int(fc[1:7])
        assert bc == EXPECTED_FILE_BATCH_COUNT, (
            f"File batch count={bc}, expected {EXPECTED_FILE_BATCH_COUNT}"
        )

    def test_block_count(self, merged_records):
        fc = get_file_control(merged_records)
        block = int(fc[7:13])
        assert block == EXPECTED_FILE_BLOCK_COUNT, (
            f"File block count={block}, expected {EXPECTED_FILE_BLOCK_COUNT}"
        )

    def test_entry_addenda_count(self, merged_records):
        fc = get_file_control(merged_records)
        eac = int(fc[13:21])
        assert eac == EXPECTED_FILE_EA_COUNT, (
            f"File EA count={eac}, expected {EXPECTED_FILE_EA_COUNT}"
        )

    def test_entry_hash(self, merged_records):
        fc = get_file_control(merged_records)
        eh = int(fc[21:31])
        assert eh == EXPECTED_FILE_ENTRY_HASH, (
            f"File entry hash={eh}, expected {EXPECTED_FILE_ENTRY_HASH}"
        )

    def test_entry_hash_field_length(self, merged_records):
        fc = get_file_control(merged_records)
        eh_field = fc[21:31]
        assert len(eh_field) == 10, f"Entry hash field len={len(eh_field)}"
        assert eh_field.isdigit(), (
            f"Entry hash field contains non-digits: '{eh_field}'"
        )

    def test_total_debit(self, merged_records):
        fc = get_file_control(merged_records)
        td = int(fc[31:43])
        assert td == EXPECTED_FILE_TOTAL_DEBIT, (
            f"File total debit={td}, expected {EXPECTED_FILE_TOTAL_DEBIT}"
        )

    def test_total_credit(self, merged_records):
        fc = get_file_control(merged_records)
        tc = int(fc[43:55])
        assert tc == EXPECTED_FILE_TOTAL_CREDIT, (
            f"File total credit={tc}, expected {EXPECTED_FILE_TOTAL_CREDIT}"
        )


# ---------------------------------------------------------------------------
# Tests -- Padding
# ---------------------------------------------------------------------------

class TestPadding:
    def test_padding_count(self, merged_records):
        padding_lines = [r for r in merged_records if r == PADDING]
        assert len(padding_lines) == EXPECTED_PADDING_COUNT, (
            f"Padding records={len(padding_lines)}, expected {EXPECTED_PADDING_COUNT}"
        )

    def test_file_control_before_padding(self, merged_records):
        """File control must be the last non-padding record."""
        for i in range(len(merged_records) - 1, -1, -1):
            if merged_records[i] != PADDING:
                assert merged_records[i][0] == "9", (
                    "Last non-padding record must be file control (type 9)"
                )
                break


# ---------------------------------------------------------------------------
# Tests -- Clean Validation (no errors expected on clean files)
# ---------------------------------------------------------------------------

class TestCleanValidation:
    def test_no_validation_errors(self, clean_report):
        assert len(clean_report["errors"]) == 0, (
            f"Expected 0 validation errors on clean files, got {len(clean_report['errors'])}: "
            + str(clean_report["errors"])
        )

    def test_valid_flag_true(self, clean_report):
        assert clean_report["valid"] is True

    def test_files_processed(self, clean_report):
        assert clean_report["files_processed"] == 3

    def test_total_batches(self, clean_report):
        assert clean_report["total_batches"] == 4

    def test_total_entries(self, clean_report):
        assert clean_report["total_entries"] == 7


# ---------------------------------------------------------------------------
# Tests -- Validation Report (errors expected on error file)
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def test_total_error_count(self, error_report):
        assert len(error_report["errors"]) == EXPECTED_VAL_TOTAL_ERRORS, (
            f"Expected {EXPECTED_VAL_TOTAL_ERRORS} errors, got "
            f"{len(error_report['errors'])}: {error_report['errors']}"
        )

    def test_valid_flag_false(self, error_report):
        assert error_report["valid"] is False

    def test_error_file_files_processed(self, error_report):
        assert error_report["files_processed"] == 1

    def test_error_file_total_batches(self, error_report):
        assert error_report["total_batches"] == 4

    def test_error_file_total_entries(self, error_report):
        assert error_report["total_entries"] == 9

    # -- CHECKDIGIT --
    def test_checkdigit_count(self, error_report):
        cd_errors = [e for e in error_report["errors"]
                     if e["error_code"] == "CHECKDIGIT"]
        assert len(cd_errors) == EXPECTED_VAL_CHECKDIGIT_COUNT, (
            f"Expected {EXPECTED_VAL_CHECKDIGIT_COUNT} CHECKDIGIT errors, got {len(cd_errors)}"
        )

    def test_checkdigit_batch(self, error_report):
        cd_errors = [e for e in error_report["errors"]
                     if e["error_code"] == "CHECKDIGIT"]
        assert len(cd_errors) > 0 and cd_errors[0]["batch_number"] == EXPECTED_VAL_CHECKDIGIT_BATCH

    # -- SCC_MISMATCH --
    def test_scc_mismatch_count(self, error_report):
        scc_errors = [e for e in error_report["errors"]
                      if e["error_code"] == "SCC_MISMATCH"]
        assert len(scc_errors) == EXPECTED_VAL_SCC_MISMATCH_COUNT, (
            f"Expected {EXPECTED_VAL_SCC_MISMATCH_COUNT} SCC_MISMATCH errors, got {len(scc_errors)}"
        )

    def test_scc_mismatch_batch(self, error_report):
        scc_errors = [e for e in error_report["errors"]
                      if e["error_code"] == "SCC_MISMATCH"]
        assert len(scc_errors) > 0 and scc_errors[0]["batch_number"] == EXPECTED_VAL_SCC_MISMATCH_BATCH

    # -- AMOUNT_RANGE --
    def test_amount_range_count(self, error_report):
        ar_errors = [e for e in error_report["errors"]
                     if e["error_code"] == "AMOUNT_RANGE"]
        assert len(ar_errors) == EXPECTED_VAL_AMOUNT_RANGE_COUNT, (
            f"Expected {EXPECTED_VAL_AMOUNT_RANGE_COUNT} AMOUNT_RANGE errors, got {len(ar_errors)}"
        )

    def test_amount_range_batch(self, error_report):
        ar_errors = [e for e in error_report["errors"]
                     if e["error_code"] == "AMOUNT_RANGE"]
        assert len(ar_errors) > 0 and ar_errors[0]["batch_number"] == EXPECTED_VAL_AMOUNT_RANGE_BATCH

    # -- DUPLICATE_TRACE --
    def test_duplicate_trace_count(self, error_report):
        dt_errors = [e for e in error_report["errors"]
                     if e["error_code"] == "DUPLICATE_TRACE"]
        assert len(dt_errors) == EXPECTED_VAL_DUP_TRACE_COUNT, (
            f"Expected {EXPECTED_VAL_DUP_TRACE_COUNT} DUPLICATE_TRACE errors, got {len(dt_errors)}"
        )

    def test_duplicate_trace_batch(self, error_report):
        dt_errors = [e for e in error_report["errors"]
                     if e["error_code"] == "DUPLICATE_TRACE"]
        assert len(dt_errors) > 0 and dt_errors[0]["batch_number"] == EXPECTED_VAL_DUP_TRACE_BATCH

    # -- ADDENDA_IND --
    def test_addenda_ind_count(self, error_report):
        ind_errors = [e for e in error_report["errors"]
                      if e["error_code"] == "ADDENDA_IND"]
        assert len(ind_errors) == EXPECTED_VAL_ADDENDA_IND_COUNT, (
            f"Expected {EXPECTED_VAL_ADDENDA_IND_COUNT} ADDENDA_IND errors, got {len(ind_errors)}"
        )

    def test_addenda_ind_batch(self, error_report):
        ind_errors = [e for e in error_report["errors"]
                      if e["error_code"] == "ADDENDA_IND"]
        assert len(ind_errors) > 0 and ind_errors[0]["batch_number"] == EXPECTED_VAL_ADDENDA_IND_BATCH

    def test_addenda_ind_entry_seq(self, error_report):
        ind_errors = [e for e in error_report["errors"]
                      if e["error_code"] == "ADDENDA_IND"]
        assert len(ind_errors) > 0 and ind_errors[0]["entry_sequence"] == EXPECTED_VAL_ADDENDA_IND_ENTRY_SEQ

    # -- TRACE_ODFI --
    def test_trace_odfi_count(self, error_report):
        odfi_errors = [e for e in error_report["errors"]
                       if e["error_code"] == "TRACE_ODFI"]
        assert len(odfi_errors) == EXPECTED_VAL_TRACE_ODFI_COUNT, (
            f"Expected {EXPECTED_VAL_TRACE_ODFI_COUNT} TRACE_ODFI errors, got {len(odfi_errors)}"
        )

    def test_trace_odfi_batch(self, error_report):
        odfi_errors = [e for e in error_report["errors"]
                       if e["error_code"] == "TRACE_ODFI"]
        assert len(odfi_errors) > 0 and odfi_errors[0]["batch_number"] == EXPECTED_VAL_TRACE_ODFI_BATCH

    def test_trace_odfi_entry_seq(self, error_report):
        odfi_errors = [e for e in error_report["errors"]
                       if e["error_code"] == "TRACE_ODFI"]
        assert len(odfi_errors) > 0 and odfi_errors[0]["entry_sequence"] == EXPECTED_VAL_TRACE_ODFI_ENTRY_SEQ

    # -- ADDENDA_SEQ (should be zero -- no real sequence errors in test data) --
    def test_no_addenda_seq_errors(self, error_report):
        seq_errors = [e for e in error_report["errors"]
                      if e["error_code"] == "ADDENDA_SEQ"]
        assert len(seq_errors) == EXPECTED_VAL_ADDENDA_SEQ_COUNT, (
            f"Expected {EXPECTED_VAL_ADDENDA_SEQ_COUNT} ADDENDA_SEQ errors, got {len(seq_errors)}"
        )


# ---------------------------------------------------------------------------
# Tests -- Report Schema
# ---------------------------------------------------------------------------

class TestReportSchema:
    def test_error_has_error_code_field(self, error_report):
        for e in error_report["errors"]:
            assert "error_code" in e, (
                f"Error object missing 'error_code' field: {e}"
            )

    def test_error_has_batch_number_field(self, error_report):
        for e in error_report["errors"]:
            assert "batch_number" in e, (
                f"Error object missing 'batch_number' field: {e}"
            )

    def test_error_has_entry_sequence_field(self, error_report):
        for e in error_report["errors"]:
            assert "entry_sequence" in e, (
                f"Error object missing 'entry_sequence' field: {e}"
            )

    def test_error_has_field_field(self, error_report):
        for e in error_report["errors"]:
            assert "field" in e, (
                f"Error object missing 'field' field: {e}"
            )

    def test_error_has_message_field(self, error_report):
        for e in error_report["errors"]:
            assert "message" in e, (
                f"Error object missing 'message' field: {e}"
            )

    def test_report_has_files_processed(self, error_report):
        assert "files_processed" in error_report

    def test_report_has_total_batches(self, error_report):
        assert "total_batches" in error_report

    def test_report_has_total_entries(self, error_report):
        assert "total_entries" in error_report

    def test_report_has_valid(self, error_report):
        assert "valid" in error_report

    def test_report_has_errors(self, error_report):
        assert "errors" in error_report
