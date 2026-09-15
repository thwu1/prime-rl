#!/usr/bin/env python3

"""
COBOL DAILYPOST migration — Python implementation.

Reads binary fixed-width account and transaction files that use COMP-3
(packed decimal) encoding, applies the exact same business logic as the
COBOL batch program including 30-day daily interest compounding and
batch control totals, and writes byte-identical output files.
"""

import os
from decimal import Decimal, ROUND_HALF_UP


# ── COMP-3 Packed Decimal ──────────────────────────────────────────────

def unpack_comp3(data: bytes) -> int:
    """Decode COMP-3 packed decimal to integer.

    Each byte holds two BCD nibbles (high, low). The last nibble is the
    sign: C = positive, D = negative, F = unsigned (treat as positive).
    Returns the raw integer value (caller handles implied decimals).
    """
    nibbles = []
    for b in data:
        nibbles.append((b >> 4) & 0xF)
        nibbles.append(b & 0xF)
    sign = nibbles.pop()
    neg = sign == 0xD
    value = int("".join(str(n) for n in nibbles))
    return -value if neg else value


def pack_comp3_signed(value: int, pic_digits: int) -> bytes:
    """Encode integer into COMP-3 signed format (C=pos, D=neg)."""
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


def pack_comp3_unsigned(value: int, pic_digits: int) -> bytes:
    """Encode integer into COMP-3 unsigned format (F sign nibble)."""
    digits = str(abs(value)).zfill(pic_digits)
    nibbles = [int(d) for d in digits]
    nibbles.append(0xF)
    if len(nibbles) % 2 == 1:
        nibbles.insert(0, 0)
    out = bytearray(len(nibbles) // 2)
    for i in range(len(out)):
        out[i] = (nibbles[2 * i] << 4) | nibbles[2 * i + 1]
    return bytes(out)


# ── Fixed-width field helpers ──────────────────────────────────────────

def ascii_field(s: str, n: int) -> bytes:
    return s.encode("ascii").ljust(n, b" ")[:n]


def numeric_field(val: int, n: int) -> bytes:
    return str(val).zfill(n).encode("ascii")[:n]


# ── Record I/O ─────────────────────────────────────────────────────────

ACCT_LEN = 72
TXN_LEN = 64
EXC_LEN = 88
SUMM_LEN = 80


def read_accounts(path: str) -> list[dict]:
    """Read 72-byte account records per ACCOUNT-REC.cpy layout."""
    accounts = []
    with open(path, "rb") as f:
        while True:
            rec = f.read(ACCT_LEN)
            if len(rec) < ACCT_LEN:
                break
            accounts.append({
                "id":       rec[0:10].decode("ascii"),
                "name":     rec[10:30].decode("ascii"),
                "type":     rec[30:32].decode("ascii"),
                "status":   rec[32:33].decode("ascii"),
                "bal":      unpack_comp3(rec[33:40]),      # S9(11)V99
                "credit":   unpack_comp3(rec[40:46]),      # S9(9)V99
                "rate":     unpack_comp3(rec[46:50]),       # 9(3)V9(4)
                "open_dt":  int(rec[50:58].decode("ascii")),
                "last_dt":  int(rec[58:66].decode("ascii")),
                "filler":   rec[66:72],
            })
    return accounts


def read_transactions(path: str) -> list[tuple[dict, bytes]]:
    """Read 64-byte txn records per TXN-REC.cpy layout.

    Returns list of (parsed_dict, raw_bytes) tuples so we can copy raw
    bytes into exception records (matching COBOL's MOVE TXN-IN-REC TO
    EXC-TXN-DATA).
    """
    txns = []
    with open(path, "rb") as f:
        while True:
            rec = f.read(TXN_LEN)
            if len(rec) < TXN_LEN:
                break
            parsed = {
                "acct_id":  rec[0:10].decode("ascii"),
                "txn_id":   rec[10:22].decode("ascii"),
                "txn_type": rec[22:26].decode("ascii"),
                "amount":   unpack_comp3(rec[26:32]),     # S9(9)V99
                "date":     int(rec[32:40].decode("ascii")),
                "desc":     rec[40:60].decode("ascii"),
            }
            txns.append((parsed, rec))
    return txns


def write_account_rec(acct: dict) -> bytes:
    """Serialize account dict to 72-byte record."""
    rec = bytearray(ACCT_LEN)
    rec[0:10]  = ascii_field(acct["id"], 10)
    rec[10:30] = ascii_field(acct["name"], 20)
    rec[30:32] = ascii_field(acct["type"], 2)
    rec[32:33] = ascii_field(acct["status"], 1)
    rec[33:40] = pack_comp3_signed(acct["bal"], 13)
    rec[40:46] = pack_comp3_signed(acct["credit"], 11)
    rec[46:50] = pack_comp3_unsigned(acct["rate"], 7)
    rec[50:58] = numeric_field(acct["open_dt"], 8)
    rec[58:66] = numeric_field(acct["last_dt"], 8)
    rec[66:72] = acct.get("filler", b"      ")
    return bytes(rec)


def write_exception_rec(txn_raw: bytes, code: int, desc: str) -> bytes:
    """Build 88-byte exception record."""
    rec = bytearray(EXC_LEN)
    rec[0:64]  = txn_raw[:64]
    rec[64:68] = str(code).zfill(4).encode("ascii")
    rec[68:88] = ascii_field(desc, 20)
    return bytes(rec)


def write_summary_rec(tot_debits: int, tot_credits: int,
                      acct_count: int, exc_count: int,
                      txn_count: int, hash_total: int) -> bytes:
    """Build 80-byte summary control totals record.

    Layout matches COBOL FD SUMM-FILE:
      Offset  Len  Field             PIC
      0        4   SUMM-LABEL        X(04)             "CTRL"
      4        7   SUMM-TOT-DEBITS   S9(11)V99 COMP-3
      11       7   SUMM-TOT-CREDITS  S9(11)V99 COMP-3
      18       4   SUMM-ACCT-COUNT   9(07) COMP-3
      22       4   SUMM-EXC-COUNT    9(07) COMP-3
      26       4   SUMM-TXN-COUNT    9(07) COMP-3
      30       8   SUMM-HASH-TOTAL   S9(13)V99 COMP-3
      38      42   FILLER            X(42)
    """
    # Initialize with spaces (matches COBOL MOVE SPACES TO SUMM-REC)
    rec = bytearray(b' ' * SUMM_LEN)
    rec[0:4]   = b"CTRL"
    rec[4:11]  = pack_comp3_signed(tot_debits, 13)
    rec[11:18] = pack_comp3_signed(tot_credits, 13)
    rec[18:22] = pack_comp3_unsigned(acct_count, 7)
    rec[22:26] = pack_comp3_unsigned(exc_count, 7)
    rec[26:30] = pack_comp3_unsigned(txn_count, 7)
    rec[30:38] = pack_comp3_signed(hash_total, 15)
    return bytes(rec)


# ── Main processing — mirrors COBOL DAILYPOST exactly ──────────────────

def main():
    accounts = read_accounts("/app/data/accounts.dat")
    txns = read_transactions("/app/data/txns.dat")

    os.makedirs("/app/output", exist_ok=True)

    out_accounts = []
    out_exceptions = []

    # Control totals accumulators
    tot_debits = 0
    tot_credits = 0
    acct_count = 0
    exc_count = 0
    txn_applied = 0
    hash_total = 0

    ti = 0  # transaction index

    for acct in accounts:
        acct_id = acct["id"]

        # ── Orphan transactions (TXN-ACCT-ID < ACCT-ID) ──
        while ti < len(txns) and txns[ti][0]["acct_id"] < acct_id:
            _, raw = txns[ti]
            out_exceptions.append(
                write_exception_rec(raw, 1001, "NO MATCHING ACCOUNT"))
            exc_count += 1
            ti += 1

        # ── Matching transactions (TXN-ACCT-ID == ACCT-ID) ──
        while ti < len(txns) and txns[ti][0]["acct_id"] == acct_id:
            t, raw = txns[ti]

            # Validation: account active
            if acct["status"] != "A":
                out_exceptions.append(
                    write_exception_rec(raw, 1002, "ACCOUNT NOT ACTIVE"))
                exc_count += 1
                ti += 1
                continue

            # Validation: txn date >= open date
            if t["date"] < acct["open_dt"]:
                out_exceptions.append(
                    write_exception_rec(raw, 1005, "TXN BEFORE OPEN DATE"))
                exc_count += 1
                ti += 1
                continue

            # ── APPLY-TRANSACTION ──
            txn_type = t["txn_type"]
            txn_amt = t["amount"]

            if txn_type == "DEPO":
                acct["bal"] += txn_amt
                tot_debits += txn_amt
                txn_applied += 1

            elif txn_type == "WDRW":
                new_bal = acct["bal"] - txn_amt
                neg_limit = 0 - acct["credit"]
                if new_bal >= neg_limit:
                    acct["bal"] = new_bal
                    tot_credits += txn_amt
                    txn_applied += 1
                else:
                    out_exceptions.append(
                        write_exception_rec(raw, 1003, "INSUFFICIENT FUNDS"))
                    exc_count += 1

            elif txn_type == "PYMT":
                acct["bal"] += txn_amt
                tot_debits += txn_amt
                txn_applied += 1

            elif txn_type == "FEES":
                acct["bal"] -= txn_amt
                tot_credits += txn_amt
                txn_applied += 1

            elif txn_type == "INTC":
                # COBOL: PERFORM VARYING WS-DAY FROM 1 BY 1
                #            UNTIL WS-DAY > 30
                #   COMPUTE WS-DAILY-INT ROUNDED
                #      = CURR-BAL * INT-RATE / 36000
                #   ADD WS-DAILY-INT TO CURR-BAL
                # END-PERFORM
                #
                # 30-day daily interest compounding (360-day convention).
                # CURR-BAL is V99 (cents), INT-RATE is V9(4).
                # WS-DAILY-INT is S9(11)V99 COMP-3, ROUNDED = HALF_UP.
                # Each daily accrual is rounded to 2 decimal places
                # before being added to the balance.
                bal_dec = Decimal(acct["bal"]) / Decimal(100)
                rate_dec = Decimal(acct["rate"]) / Decimal(10000)
                for _ in range(30):
                    daily_int = (bal_dec * rate_dec / Decimal(36000)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP)
                    bal_dec += daily_int
                acct["bal"] = int(bal_dec * 100)
                txn_applied += 1

            elif txn_type == "REVR":
                acct["bal"] -= txn_amt
                tot_credits += txn_amt
                txn_applied += 1

            else:
                out_exceptions.append(
                    write_exception_rec(raw, 1004, "UNKNOWN TXN TYPE"))
                exc_count += 1

            # MOVE TXN-DATE TO LAST-ACTIVITY-DT (post-EVALUATE, always)
            acct["last_dt"] = t["date"]

            ti += 1

        # Accumulate control totals and write account record
        hash_total += acct["bal"]
        acct_count += 1
        out_accounts.append(write_account_rec(acct))

    # ── Write output files ──
    with open("/app/output/accounts_out.dat", "wb") as f:
        for rec in out_accounts:
            f.write(rec)

    with open("/app/output/exceptions.dat", "wb") as f:
        for rec in out_exceptions:
            f.write(rec)

    with open("/app/output/summary.dat", "wb") as f:
        f.write(write_summary_rec(
            tot_debits, tot_credits, acct_count,
            exc_count, txn_applied, hash_total))


if __name__ == "__main__":
    main()
