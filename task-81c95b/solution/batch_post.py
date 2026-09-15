#!/usr/bin/env python3
"""
COBOL batch migration - multi-format transaction processing with
REDEFINES variant records, COMP-3/COMP-5 mixed encodings, foreign
currency conversion, and control-break summary reporting.

"""

import os
import struct
from decimal import Decimal, ROUND_HALF_UP

ACCT_REC_LEN = 66
TXN_REC_LEN = 80
SUM_REC_LEN = 58
TODAY = 20250115


def unpack_comp3(data):
    """Unpack COMP-3 (BCD packed decimal) to raw integer.

    COMP-3 stores each digit as a 4-bit nibble. The last nibble
    is the sign: 0xC = positive, 0xD = negative, 0xF = unsigned.
    Returns the raw integer value (caller applies implied decimal).
    """
    nibbles = []
    for byte in data:
        nibbles.append((byte >> 4) & 0x0F)
        nibbles.append(byte & 0x0F)
    sign_nibble = nibbles.pop()
    digit_str = "".join(str(n) for n in nibbles)
    value = int(digit_str) if digit_str else 0
    if sign_nibble == 0x0D:
        value = -value
    return value


def pack_comp3(value, num_bytes):
    """Pack integer value into COMP-3 bytes.

    num_bytes determines the number of digit nibbles (num_bytes*2-1)
    plus one sign nibble (0xC positive, 0xD negative).
    """
    is_negative = value < 0
    abs_value = abs(value)
    num_digits = num_bytes * 2 - 1
    digit_str = str(abs_value).zfill(num_digits)
    if len(digit_str) > num_digits:
        raise ValueError(
            f"Value {value} exceeds capacity of {num_bytes} COMP-3 bytes"
        )
    nibbles = [int(d) for d in digit_str]
    nibbles.append(0x0D if is_negative else 0x0C)
    result = bytearray(num_bytes)
    for i in range(num_bytes):
        result[i] = (nibbles[2 * i] << 4) | (nibbles[2 * i + 1] & 0x0F)
    return bytes(result)


def read_accounts(path):
    """Read 66-byte account records with mixed COMP-3/COMP-5 fields."""
    accounts = []
    with open(path, "rb") as f:
        while True:
            data = f.read(ACCT_REC_LEN)
            if len(data) < ACCT_REC_LEN:
                break
            acct = {
                "acct_id": data[0:12].decode("ascii"),
                "cust_id": data[12:24].decode("ascii"),
                "product": data[24:28].decode("ascii"),
                "acct_status": data[28:29].decode("ascii"),
                "curr_bal": unpack_comp3(data[29:36]),
                "overdraft_limit": unpack_comp3(data[36:42]),
                "open_date": data[42:50].decode("ascii"),
                "close_date": data[50:58].decode("ascii"),
                "txn_count": struct.unpack('<H', data[58:60])[0],
                "last_interest": unpack_comp3(data[60:66]),
            }
            accounts.append(acct)
    return accounts


def read_transactions(path):
    """Read 80-byte transaction records with REDEFINES variant layout.

    REC-TYPE determines which variant to parse:
      'D' = domestic (TXN-DOM)
      'F' = foreign currency (TXN-FX)
      'A' = adjustment (TXN-ADJ)
    """
    txns = []
    with open(path, "rb") as f:
        while True:
            data = f.read(TXN_REC_LEN)
            if len(data) < TXN_REC_LEN:
                break
            rec_type = data[0:1].decode("ascii")
            base = {
                "rec_type": rec_type,
                "acct_id": data[1:13].decode("ascii"),
                "txn_id": data[13:29].decode("ascii"),
                "raw": bytes(data),
            }
            body = data[29:]
            if rec_type == "D":
                base["txn_code"] = body[0:4].decode("ascii")
                base["txn_amount"] = unpack_comp3(body[4:10])
                base["txn_ts"] = body[10:24].decode("ascii")
                base["channel"] = body[24:28].decode("ascii")
            elif rec_type == "F":
                base["fx_code"] = body[0:4].decode("ascii")
                base["fx_local_amt"] = unpack_comp3(body[4:10])
                base["fx_ts"] = body[10:24].decode("ascii")
                base["fx_rate"] = unpack_comp3(body[24:28])
                base["fx_currency"] = body[28:31].decode("ascii")
                base["fx_orig_amt"] = unpack_comp3(body[31:37])
            elif rec_type == "A":
                base["adj_code"] = body[0:4].decode("ascii")
                base["adj_amount"] = unpack_comp3(body[4:10])
                base["adj_ts"] = body[10:24].decode("ascii")
                base["adj_orig_txn"] = body[24:40].decode("ascii")
                base["adj_reason"] = body[40:44].decode("ascii")
            txns.append(base)
    return txns


def write_account_record(acct):
    """Serialize account to 66 bytes matching COBOL ACCOUNT-REC layout."""
    rec = bytearray(ACCT_REC_LEN)
    rec[0:12] = acct["acct_id"].encode("ascii").ljust(12)
    rec[12:24] = acct["cust_id"].encode("ascii").ljust(12)
    rec[24:28] = acct["product"].encode("ascii").ljust(4)
    rec[28:29] = acct["acct_status"].encode("ascii").ljust(1)
    rec[29:36] = pack_comp3(acct["curr_bal"], 7)
    rec[36:42] = pack_comp3(acct["overdraft_limit"], 6)
    rec[42:50] = acct["open_date"].encode("ascii").ljust(8)
    rec[50:58] = acct["close_date"].encode("ascii").ljust(8)
    rec[58:60] = struct.pack('<H', acct["txn_count"])
    rec[60:66] = pack_comp3(acct["last_interest"], 6)
    return bytes(rec)


def write_summary_record(summary):
    """Serialize summary to 58 bytes matching COBOL SUMMARY-REC layout."""
    rec = bytearray(SUM_REC_LEN)
    rec[0:12] = summary["acct_id"].encode("ascii").ljust(12)
    rec[12:14] = struct.pack('<H', summary["dom_count"])
    rec[14:21] = pack_comp3(summary["dom_net"], 7)
    rec[21:23] = struct.pack('<H', summary["fx_count"])
    rec[23:30] = pack_comp3(summary["fx_net"], 7)
    rec[30:32] = struct.pack('<H', summary["adj_count"])
    rec[32:39] = pack_comp3(summary["adj_net"], 7)
    rec[39:45] = pack_comp3(summary["interest"], 6)
    rec[45:51] = pack_comp3(summary["fee"], 6)
    rec[51:58] = pack_comp3(summary["final_bal"], 7)
    return bytes(rec)


def calc_interest(curr_bal_cents, product):
    """Replicate CALCRATE subprogram: tiered interest with COBOL ROUNDED.

    COBOL ROUNDED uses half-away-from-zero (ROUND_HALF_UP for positive).
    Interest = balance * annual_rate / 1200, rounded to 2 decimal places.
    Returns (interest_cents, rate_tier).
    """
    if curr_bal_cents <= 0:
        return 0, 0

    if product == "SAVE":
        if curr_bal_cents >= 1000000:
            annual_rate = Decimal("4.7500")
            tier = 3
        elif curr_bal_cents >= 100000:
            annual_rate = Decimal("4.5000")
            tier = 2
        else:
            annual_rate = Decimal("2.0000")
            tier = 1
    elif product == "CHCK":
        if curr_bal_cents >= 500000:
            annual_rate = Decimal("1.0000")
            tier = 2
        else:
            annual_rate = Decimal("0")
            tier = 1
    elif product == "PREM":
        if curr_bal_cents >= 50000:
            annual_rate = Decimal("5.5000")
            tier = 2
        else:
            annual_rate = Decimal("3.0000")
            tier = 1
    elif product == "MMKT":
        if curr_bal_cents >= 1000000:
            annual_rate = Decimal("5.0000")
            tier = 3
        elif curr_bal_cents >= 500000:
            annual_rate = Decimal("3.5000")
            tier = 2
        else:
            annual_rate = Decimal("2.0000")
            tier = 1
    else:
        annual_rate = Decimal("0")
        tier = 0

    if annual_rate == 0:
        return 0, tier

    bal_dollars = Decimal(curr_bal_cents) / Decimal(100)
    interest_dollars = (bal_dollars * annual_rate / Decimal(1200)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return int(interest_dollars * 100), tier


def assess_fee(curr_bal_cents, product):
    """Assess monthly maintenance fee based on product and balance."""
    if product == "CHCK":
        return 1500 if curr_bal_cents < 150000 else 0
    elif product == "SAVE":
        return 500 if curr_bal_cents < 30000 else 0
    elif product == "PREM":
        return 2500
    elif product == "MMKT":
        return 1000 if curr_bal_cents < 250000 else 0
    return 0


def process():
    """Main batch processing: merge-join, variant dispatch, summaries."""
    accounts = read_accounts("data/accounts.dat")
    txns = read_transactions("data/txns.dat")

    exceptions = []
    summaries = []
    ti = 0

    for acct in accounts:
        summary = {
            "acct_id": acct["acct_id"],
            "dom_count": 0, "dom_net": 0,
            "fx_count": 0, "fx_net": 0,
            "adj_count": 0, "adj_net": 0,
            "interest": 0, "fee": 0, "final_bal": 0,
        }

        while ti < len(txns) and txns[ti]["acct_id"] < acct["acct_id"]:
            ti += 1

        while ti < len(txns) and txns[ti]["acct_id"] == acct["acct_id"]:
            txn = txns[ti]
            rec_type = txn["rec_type"]

            if rec_type == "D":
                ts_date = int(txn["txn_ts"]) // 1000000
                if ts_date == TODAY:
                    code = txn["txn_code"]
                    txn_net = 0
                    if code == "DEPO":
                        acct["curr_bal"] += txn["txn_amount"]
                        txn_net = txn["txn_amount"]
                    elif code == "WDRW":
                        new_bal = acct["curr_bal"] - txn["txn_amount"]
                        neg_limit = 0 - acct["overdraft_limit"]
                        if new_bal >= neg_limit:
                            acct["curr_bal"] = new_bal
                            txn_net = 0 - txn["txn_amount"]
                        else:
                            exceptions.append(txn)
                            txn_net = 0
                    elif code == "FEE ":
                        acct["curr_bal"] += txn["txn_amount"]
                        txn_net = txn["txn_amount"]
                    elif code == "INT ":
                        acct["curr_bal"] += txn["txn_amount"]
                        txn_net = txn["txn_amount"]
                    elif code == "REV ":
                        acct["curr_bal"] -= txn["txn_amount"]
                        txn_net = 0 - txn["txn_amount"]

                    summary["dom_count"] += 1
                    summary["dom_net"] += txn_net
                    acct["txn_count"] += 1

            elif rec_type == "F":
                ts_date = int(txn["fx_ts"]) // 1000000
                if ts_date == TODAY:
                    orig_dollars = Decimal(txn["fx_orig_amt"]) / Decimal(100)
                    rate = Decimal(txn["fx_rate"]) / Decimal(1000000)
                    local_dollars = (orig_dollars * rate).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    local_cents = int(local_dollars * 100)

                    fx_code = txn["fx_code"]
                    txn_net = 0
                    if fx_code == "FXBY":
                        acct["curr_bal"] -= local_cents
                        txn_net = 0 - local_cents
                    elif fx_code == "FXSL":
                        acct["curr_bal"] += local_cents
                        txn_net = local_cents

                    summary["fx_count"] += 1
                    summary["fx_net"] += txn_net
                    acct["txn_count"] += 1

            elif rec_type == "A":
                ts_date = int(txn["adj_ts"]) // 1000000
                if ts_date == TODAY:
                    acct["curr_bal"] += txn["adj_amount"]
                    summary["adj_count"] += 1
                    summary["adj_net"] += txn["adj_amount"]
                    acct["txn_count"] += 1

            ti += 1

        interest, tier = calc_interest(acct["curr_bal"], acct["product"])
        acct["curr_bal"] += interest
        acct["last_interest"] = interest

        fee = assess_fee(acct["curr_bal"], acct["product"])
        acct["curr_bal"] -= fee

        summary["interest"] = interest
        summary["fee"] = fee
        summary["final_bal"] = acct["curr_bal"]
        summaries.append(summary)

    os.makedirs("out", exist_ok=True)

    with open("out/accounts_out.dat", "wb") as f:
        for acct in accounts:
            f.write(write_account_record(acct))

    with open("out/exceptions.dat", "wb") as f:
        for exc in exceptions:
            f.write(exc["raw"])

    with open("out/summary.dat", "wb") as f:
        for s in summaries:
            f.write(write_summary_record(s))


if __name__ == "__main__":
    process()
