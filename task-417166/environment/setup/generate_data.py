#!/usr/bin/env python3
"""Generate binary input data for COBOL DAILYPOST batch task.

This script runs during Docker build (first stage) and is NOT included
in the final image. It creates only the INPUT data files — no expected
output is generated here.
"""
import os


# ── COMP-3 Packed Decimal Encoding ──────────────────────────────────────

def pack_comp3_signed(value, pic_digits):
    """Pack integer value into COMP-3 signed format (C=pos, D=neg)."""
    neg = value < 0
    digits = str(abs(value)).zfill(pic_digits)
    nibbles = [int(d) for d in digits]
    nibbles.append(0xD if neg else 0xC)
    if len(nibbles) % 2 == 1:
        nibbles.insert(0, 0)
    out = bytearray(len(nibbles) // 2)
    for i in range(len(out)):
        out[i] = (nibbles[2 * i] << 4) | nibbles[2 * i + 1]
    return bytes(out)


def pack_comp3_unsigned(value, pic_digits):
    """Pack integer value into COMP-3 unsigned format (F sign nibble)."""
    digits = str(abs(value)).zfill(pic_digits)
    nibbles = [int(d) for d in digits]
    nibbles.append(0xF)
    if len(nibbles) % 2 == 1:
        nibbles.insert(0, 0)
    out = bytearray(len(nibbles) // 2)
    for i in range(len(out)):
        out[i] = (nibbles[2 * i] << 4) | nibbles[2 * i + 1]
    return bytes(out)


# ── Fixed-Width Field Helpers ───────────────────────────────────────────

def ascii_field(s, n):
    return s.encode('ascii').ljust(n, b' ')[:n]


def numeric_field(val, n):
    return str(val).zfill(n).encode('ascii')[:n]


# ── Record Construction ────────────────────────────────────────────────

def make_account(acct_id, cust_name, acct_type, status,
                 bal_cents, credit_cents, rate_ten_thousandths,
                 open_dt, last_dt):
    """Build a 72-byte account record per ACCOUNT-REC.cpy layout."""
    rec = bytearray(72)
    rec[0:10] = ascii_field(acct_id, 10)
    rec[10:30] = ascii_field(cust_name, 20)
    rec[30:32] = ascii_field(acct_type, 2)
    rec[32:33] = ascii_field(status, 1)
    rec[33:40] = pack_comp3_signed(bal_cents, 13)
    rec[40:46] = pack_comp3_signed(credit_cents, 11)
    rec[46:50] = pack_comp3_unsigned(rate_ten_thousandths, 7)
    rec[50:58] = numeric_field(open_dt, 8)
    rec[58:66] = numeric_field(last_dt, 8)
    rec[66:72] = b'      '
    return bytes(rec)


def make_txn(acct_id, txn_id, txn_type, amt_cents, txn_date, desc):
    """Build a 64-byte transaction record per TXN-REC.cpy layout."""
    rec = bytearray(64)
    rec[0:10] = ascii_field(acct_id, 10)
    rec[10:22] = ascii_field(txn_id, 12)
    rec[22:26] = ascii_field(txn_type, 4)
    rec[26:32] = pack_comp3_signed(amt_cents, 11)
    rec[32:40] = numeric_field(txn_date, 8)
    rec[40:60] = ascii_field(desc, 20)
    rec[60:64] = b'    '
    return bytes(rec)


# ── Test Data ──────────────────────────────────────────────────────────

ACCOUNTS = [
    ("A000000001", "JOHNSON ALICE M",  "CH", "A",  1523467,   50000,  15000,
     20200115, 20250101),
    ("A000000002", "SMITH ROBERT J",   "CR", "A",  -245890, 1000000, 189900,
     20190301, 20250110),
    ("A000000003", "WILLIAMS MARIA",   "SV", "A",  8750025,       0,  42500,
     20210601, 20250105),
    ("A000000004", "BROWN DAVID K",    "CH", "C",    32100,   25000,  10000,
     20180901, 20241215),
    ("A000000005", "DAVIS JENNIFER",   "CR", "A",  -892345, 1500000, 214500,
     20200701, 20250112),
    ("A000000006", "GARCIA CARLOS R",  "CH", "A",    45230,  100000,   8750,
     20220315, 20250108),
    ("A000000007", "MARTINEZ ELENA",   "SV", "S",  2100000,       0,  35000,
     20210101, 20250101),
    ("A000000008", "ANDERSON JAMES",   "CH", "A",   156078,   75000,  12500,
     20230401, 20250114),
]

TRANSACTIONS = [
    ("A000000000", "TX0000000001", "DEPO",      10000, 20250115,
     "ORPHAN DEPOSIT"),
    ("A000000001", "TX0001000001", "DEPO",     250000, 20250115,
     "PAYROLL DEPOSIT"),
    ("A000000001", "TX0001000002", "WDRW",      50000, 20250115,
     "ATM WITHDRAWAL"),
    ("A000000001", "TX0001000003", "FEES",       1500, 20250115,
     "MONTHLY SVC FEE"),
    ("A000000001", "TX0001000004", "INTC",          0, 20250115,
     "MONTHLY INTEREST"),
    ("A000000002", "TX0002000001", "PYMT",     100000, 20250115,
     "ONLINE PAYMENT"),
    ("A000000002", "TX0002000002", "WDRW",      35099, 20250115,
     "AMAZON PURCHASE"),
    ("A000000002", "TX0002000003", "INTC",          0, 20250115,
     "INTEREST CHARGE"),
    ("A000000002", "TX0002000004", "FEES",       3500, 20250115,
     "ANNUAL FEE"),
    ("A000000003", "TX0003000001", "DEPO",     500000, 20250115,
     "WIRE TRANSFER"),
    ("A000000003", "TX0003000002", "INTC",          0, 20250115,
     "MONTHLY INTEREST"),
    ("A000000003", "TX0003000003", "WDRW",   10000000, 20250115,
     "LARGE WITHDRAWAL"),
    ("A000000004", "TX0004000001", "DEPO",      50000, 20250115,
     "DEPOSIT ATTEMPT"),
    ("A000000005", "TX0005000001", "WDRW",     700000, 20250115,
     "ELECTRONICS STORE"),
    ("A000000005", "TX0005000002", "WDRW",     500000, 20250115,
     "GROCERY STORE"),
    ("A000000005", "TX0005000003", "INTC",          0, 20250115,
     "INTEREST CHARGE"),
    ("A000000006", "TX0006000001", "DEPO",     120000, 20250115,
     "DIRECT DEPOSIT"),
    ("A000000006", "TX0006000002", "WDRW",     200000, 20250115,
     "RENT PAYMENT"),
    ("A000000006", "TX0006000003", "REVR",       5000, 20250115,
     "CHARGEBACK"),
    ("A000000006", "TX0006000004", "INTC",          0, 20250115,
     "MONTHLY INTEREST"),
    ("A000000007", "TX0007000001", "DEPO",     100000, 20250115,
     "DEPOSIT ATTEMPT"),
    ("A000000008", "TX0008000001", "DEPO",      30000, 20230301,
     "BACKDATED DEPOSIT"),
    ("A000000008", "TX0008000002", "DEPO",      75000, 20250115,
     "PAYCHECK"),
    ("A000000008", "TX0008000003", "XYZZ",       1000, 20250115,
     "UNKNOWN TYPE"),
    ("A000000008", "TX0008000004", "INTC",          0, 20250115,
     "MONTHLY INTEREST"),
]


# ── Generate Binary Input Files ────────────────────────────────────────

os.makedirs("/app/data", exist_ok=True)

with open("/app/data/accounts.dat", "wb") as f:
    for a in ACCOUNTS:
        f.write(make_account(*a))

with open("/app/data/txns.dat", "wb") as f:
    for t in TRANSACTIONS:
        f.write(make_txn(*t))

print(f"Generated {len(ACCOUNTS)} accounts ({72 * len(ACCOUNTS)} bytes)")
print(f"Generated {len(TRANSACTIONS)} txns ({64 * len(TRANSACTIONS)} bytes)")
