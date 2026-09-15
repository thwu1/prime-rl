#!/usr/bin/env python3
"""
TARGET Services Billing Engine — Reference Solution.

Connects to existing billing.db (created by run_pipeline.sh via sqlite3 CLI),
parses the pricing schedule, computes monthly invoices, populates the
fee_breakdown table, and writes invoices.json and reconciliation.json.
"""

import json
import os
import re
import sqlite3
from decimal import Decimal, ROUND_HALF_UP


# ================================================================
# Helpers
# ================================================================

def to_dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_dec(value, places):
    quantizer = Decimal(10) ** -places
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


def compute_degressive(volume, bands):
    total_fee = Decimal("0")
    remaining = int(volume)
    for band in bands:
        if remaining <= 0:
            break
        b_from = int(band["from"])
        b_to = band.get("to")
        fee = to_dec(band["fee"])
        if b_to is not None:
            capacity = int(b_to) - b_from + 1
        else:
            capacity = remaining
        qty = min(remaining, capacity)
        total_fee += Decimal(qty) * fee
        remaining -= qty
    return total_fee


def lookup_fixed_fee_ii(guv_millions, brackets):
    guv = to_dec(guv_millions)
    for bracket in brackets:
        low = to_dec(bracket["from_millions"])
        high = bracket.get("to_millions")
        if high is not None:
            if low <= guv <= to_dec(high):
                return to_dec(bracket["monthly_fee"])
        else:
            if guv >= low:
                return to_dec(bracket["monthly_fee"])
    return Decimal("0")


# ================================================================
# Parse pricing schedule text
# ================================================================

def parse_band_table(text):
    """Extract band rows from a table section."""
    bands = []
    for m in re.finditer(
        r'\|\s*([\d,]+)\s*\|\s*([\d,]+|\.\.\.)\s*\|\s*([\d.]+)', text
    ):
        b_from = int(m.group(1).replace(",", ""))
        b_to_str = m.group(2).strip()
        if b_to_str == "...":
            b_to = None
        else:
            b_to = int(b_to_str.replace(",", ""))
        fee = float(m.group(3))
        bands.append({"from": b_from, "to": b_to, "fee": fee})
    return bands


def parse_pricing_schedule(path):
    with open(path) as f:
        text = f.read()

    # Split into sections
    sections = {}
    for m in re.finditer(
        r'SECTION (\d+):.*?\n={5,}\n(.*?)(?=SECTION \d+:|END OF FEE SCHEDULE)',
        text, re.DOTALL
    ):
        sections[int(m.group(1))] = m.group(2)

    rules = {}

    # --- SECTION 1: RTGS Core ---
    s1 = sections[1]

    opt_a_fee = float(re.search(
        r'OPTION A.*?Monthly fee per DCA\s*\.+\s*EUR\s*([\d,.]+)',
        s1, re.DOTALL
    ).group(1).replace(",", ""))
    opt_a_po = float(re.search(
        r'OPTION A.*?Fee per payment order.*?EUR\s*([\d.]+)',
        s1, re.DOTALL
    ).group(1))

    opt_b_fee = float(re.search(
        r'OPTION B.*?Monthly fee per DCA\s*\.+\s*EUR\s*([\d,.]+)',
        s1, re.DOTALL
    ).group(1).replace(",", ""))

    opt_b_start = s1.index("OPTION B")
    bg_start = s1.index("BILLING GROUPS")
    opt_b_bands = parse_band_table(s1[opt_b_start:bg_start])

    rules["rtgs"] = {
        "core": {
            "option_a": {
                "monthly_fee_per_dca": opt_a_fee,
                "fee_per_payment_order": opt_a_po,
            },
            "option_b": {
                "monthly_fee_per_dca": opt_b_fee,
                "bands": opt_b_bands,
            },
        },
    }

    # --- SECTION 2: RTGS AS ---
    s2 = sections[2]

    as_opt_a_fee = float(re.search(
        r'OPTION A.*?Monthly fee\s*\.+\s*EUR\s*([\d,.]+)',
        s2, re.DOTALL
    ).group(1).replace(",", ""))
    as_opt_a_cto = float(re.search(
        r'OPTION A.*?Fee per cash transfer order.*?EUR\s*([\d.]+)',
        s2, re.DOTALL
    ).group(1))

    as_opt_b_fee = float(re.search(
        r'OPTION B.*?Monthly fee\s*\.+\s*EUR\s*([\d,.]+)',
        s2, re.DOTALL
    ).group(1).replace(",", ""))

    opt_b_as_start = s2.index("OPTION B")
    all_as_start = s2.index("All ancillary")
    as_opt_b_bands = parse_band_table(s2[opt_b_as_start:all_as_start])

    ff_i = float(re.search(
        r'Fixed Fee I:\s*EUR\s*([\d,.]+)', s2
    ).group(1).replace(",", ""))

    ff_ii_text = s2[s2.index("Fixed Fee II"):]
    ff_ii_brackets = []
    for m in re.finditer(
        r'([\d,]+(?:\.\d+)?)\s+to\s+([\d,]+(?:\.\d+)?)\s*\|\s*([\d,]+)',
        ff_ii_text
    ):
        ff_ii_brackets.append({
            "from_millions": float(m.group(1).replace(",", "")),
            "to_millions": float(m.group(2).replace(",", "")),
            "monthly_fee": float(m.group(3).replace(",", "")),
        })
    m_above = re.search(
        r'([\d,]+)\s+and above\s*\|\s*([\d,]+)', ff_ii_text
    )
    if m_above:
        ff_ii_brackets.append({
            "from_millions": float(m_above.group(1).replace(",", "")),
            "to_millions": None,
            "monthly_fee": float(m_above.group(2).replace(",", "")),
        })

    rules["rtgs"]["ancillary_system"] = {
        "option_a": {
            "monthly_fee": as_opt_a_fee,
            "fee_per_cash_transfer_order": as_opt_a_cto,
        },
        "option_b": {
            "monthly_fee": as_opt_b_fee,
            "bands": as_opt_b_bands,
        },
        "fixed_fee_i": ff_i,
        "fixed_fee_ii": ff_ii_brackets,
    }

    # --- SECTION 3: BIC fees ---
    s3 = sections[3]
    rules["rtgs"]["bic_fees"] = {
        "addressable_bic": float(
            re.search(r'Addressable BIC.*?EUR\s*([\d.]+)', s3).group(1)
        ),
        "unpublished_bic": float(
            re.search(r'Unpublished BIC.*?EUR\s*([\d.]+)', s3).group(1)
        ),
        "multi_addressee_access": float(
            re.search(r'Multi-addressee access.*?EUR\s*([\d.]+)', s3).group(1)
        ),
    }

    # --- SECTION 4: Liquidity transfers ---
    s4 = sections[4]
    rules["rtgs"]["liquidity_transfer_cross_banking_group"] = float(
        re.search(r'Within RTGS\s*\.+\s*EUR\s*([\d.]+)', s4).group(1)
    )

    # --- SECTION 5: T2S ---
    s5 = sections[5]
    t2s_map = {
        "Messages bundled into a file": "messages_bundled_into_file",
        "Transmissions": "transmission",
        "U2A queries": "u2a_queries",
        "A2A queries": "a2a_queries",
        "A2A reports": "a2a_reports",
        "Internal T2S liquidity transfer": "internal_liquidity_transfer",
        "Intra-balance movements": "intra_balance_movement",
    }
    rules["t2s"] = {}
    for label, key in t2s_map.items():
        m = re.search(re.escape(label) + r'\s*\|\s*([\d.]+)', s5)
        rules["t2s"][key] = float(m.group(1))

    # --- SECTION 6: TIPS ---
    s6 = sections[6]

    m_settle = re.search(
        r'EUR\s*([\d.]+)\s*originator.*?EUR\s*([\d.]+)\s*beneficiary',
        s6, re.DOTALL
    )
    rules["tips"] = {
        "settlement_fee": {
            "originator": float(m_settle.group(1)),
            "beneficiary": float(m_settle.group(2)),
        },
    }

    psp_dca_fee = float(re.search(
        r'Fixed fee per TIPS DCA\s*\.+\s*EUR\s*([\d,.]+)', s6
    ).group(1).replace(",", ""))
    psp_bic_fee = float(re.search(
        r'6\.2.*?BIC fee.*?EUR\s*([\d.]+)', s6, re.DOTALL
    ).group(1))
    rules["tips"]["psp"] = {
        "fixed_fee_per_dca": psp_dca_fee,
        "bic_fee": psp_bic_fee,
        "free_bics_per_account": 1,
        "max_chargeable_bics_per_account": 50,
    }

    ach_asta_fee = float(re.search(
        r'Fixed fee per TIPS ASTA\s*\.+\s*EUR\s*([\d,.]+)', s6
    ).group(1).replace(",", ""))
    ach_bic_fee = float(re.search(
        r'6\.3.*?BIC fee.*?EUR\s*([\d.]+)', s6, re.DOTALL
    ).group(1))
    ach_band_text = s6[s6.index("6.4"):]
    ach_bands = parse_band_table(ach_band_text)
    rules["tips"]["ach"] = {
        "fixed_fee_per_asta": ach_asta_fee,
        "bic_fee": ach_bic_fee,
        "free_bics_per_account": 0,
        "max_chargeable_bics_per_account": 50,
        "internal_settlement_bands": ach_bands,
    }

    return rules


# ================================================================
# Invoice computation — returns (total, breakdown_dict)
# ================================================================

def invoice_rtgs_as(vol, part, rules):
    as_rules = rules["rtgs"]["ancillary_system"]
    option = part["pricing_option"]

    if option == "A":
        fixed = to_dec(as_rules["option_a"]["monthly_fee"])
        tx = Decimal(int(vol["cash_transfer_orders"])) * to_dec(
            as_rules["option_a"]["fee_per_cash_transfer_order"]
        )
    else:
        fixed = to_dec(as_rules["option_b"]["monthly_fee"])
        tx = compute_degressive(
            vol["cash_transfer_orders"], as_rules["option_b"]["bands"]
        )

    fee_i = to_dec(as_rules["fixed_fee_i"])
    fee_ii = lookup_fixed_fee_ii(
        vol["daily_guv_eur_millions"], as_rules["fixed_fee_ii"]
    )
    other = fee_i + fee_ii

    total = round_dec(fixed + tx + other, 2)

    return total, {
        "service": "RTGS",
        "fixed_fee": float(round_dec(fixed, 2)),
        "transaction_fee": float(round_dec(tx, 2)),
        "bic_fee": 0.0,
        "lt_fee": 0.0,
        "other_fee": float(round_dec(other, 2)),
    }


def invoice_rtgs_bank(vol, part, rules, bg_unit_price=None):
    core = rules["rtgs"]["core"]
    option = part["pricing_option"]

    # DCA fixed fee based on participant's own option
    if option == "A":
        fixed = to_dec(core["option_a"]["monthly_fee_per_dca"])
    else:
        fixed = to_dec(core["option_b"]["monthly_fee_per_dca"])

    # Payment order fees
    po = int(vol.get("payment_orders", 0))
    if bg_unit_price is not None:
        tx = round_dec(Decimal(po) * bg_unit_price, 2)
    else:
        if option == "A":
            tx = Decimal(po) * to_dec(
                core["option_a"]["fee_per_payment_order"]
            )
        else:
            tx = compute_degressive(po, core["option_b"]["bands"])

    # BIC fees
    bic_rules = rules["rtgs"]["bic_fees"]
    bic = (
        Decimal(int(vol.get("addressable_bics", 0)))
        * to_dec(bic_rules["addressable_bic"])
        + Decimal(int(vol.get("unpublished_bics", 0)))
        * to_dec(bic_rules["unpublished_bic"])
        + Decimal(int(vol.get("multi_addressee_bics", 0)))
        * to_dec(bic_rules["multi_addressee_access"])
    )

    # Cross-banking-group liquidity transfers
    lt_rate = to_dec(rules["rtgs"]["liquidity_transfer_cross_banking_group"])
    lt_count = int(vol.get("lt_within_rtgs_cross_bg", 0)) + int(
        vol.get("lt_rtgs_to_clm_cross_bg", 0)
    )
    lt = Decimal(lt_count) * lt_rate

    total = round_dec(fixed + tx + bic + lt, 2)

    return total, {
        "service": "RTGS",
        "fixed_fee": float(round_dec(fixed, 2)),
        "transaction_fee": float(round_dec(tx, 2)),
        "bic_fee": float(round_dec(bic, 2)),
        "lt_fee": float(round_dec(lt, 2)),
        "other_fee": 0.0,
    }


def invoice_t2s(vol, rules):
    t = rules["t2s"]
    activity_map = [
        ("messages_bundled", "messages_bundled_into_file"),
        ("transmissions", "transmission"),
        ("u2a_queries", "u2a_queries"),
        ("a2a_queries", "a2a_queries"),
        ("a2a_reports", "a2a_reports"),
        ("internal_lt", "internal_liquidity_transfer"),
        ("intra_balance_movements", "intra_balance_movement"),
    ]
    tx_total = Decimal("0")
    for vol_key, rule_key in activity_map:
        qty = int(vol.get(vol_key, 0))
        price = to_dec(t[rule_key])
        tx_total += Decimal(qty) * price

    total = round_dec(tx_total, 2)

    return total, {
        "service": "T2S",
        "fixed_fee": 0.0,
        "transaction_fee": float(total),
        "bic_fee": 0.0,
        "lt_fee": 0.0,
        "other_fee": 0.0,
    }


def invoice_tips_psp(vol, rules):
    psp = rules["tips"]["psp"]
    settle = rules["tips"]["settlement_fee"]

    dcas = int(vol.get("dcas", 0))
    fixed = Decimal(dcas) * to_dec(psp["fixed_fee_per_dca"])

    total_bics = int(vol.get("dca_aau_bics", 0))
    free_bics = int(psp["free_bics_per_account"]) * dcas
    max_chargeable = int(psp["max_chargeable_bics_per_account"]) * dcas
    chargeable = max(0, min(total_bics - free_bics, max_chargeable))
    bic = Decimal(chargeable) * to_dec(psp["bic_fee"])

    orig_rate = to_dec(settle["originator"])
    benef_rate = to_dec(settle["beneficiary"])

    tx = Decimal("0")
    for field in [
        "settled_ip_orig", "unsettled_ip_orig",
        "settled_recall_orig", "unsettled_recall_orig",
    ]:
        tx += Decimal(int(vol.get(field, 0))) * orig_rate

    for field in [
        "settled_ip_benef", "unsettled_ip_benef",
        "settled_recall_benef", "unsettled_recall_benef",
    ]:
        tx += Decimal(int(vol.get(field, 0))) * benef_rate

    total = round_dec(fixed + bic + tx, 2)

    return total, {
        "service": "TIPS",
        "fixed_fee": float(round_dec(fixed, 2)),
        "transaction_fee": float(round_dec(tx, 2)),
        "bic_fee": float(round_dec(bic, 2)),
        "lt_fee": 0.0,
        "other_fee": 0.0,
    }


def invoice_tips_ach(vol, rules):
    ach = rules["tips"]["ach"]
    settle = rules["tips"]["settlement_fee"]

    astas = int(vol.get("astas", 0))
    fixed = Decimal(astas) * to_dec(ach["fixed_fee_per_asta"])

    total_bics = int(vol.get("asta_aau_bics", 0))
    free_bics = int(ach["free_bics_per_account"]) * astas
    max_chargeable = int(ach["max_chargeable_bics_per_account"]) * astas
    chargeable = max(0, min(total_bics - free_bics, max_chargeable))
    bic = Decimal(chargeable) * to_dec(ach["bic_fee"])

    internal_vol = int(vol.get("internally_settled_ip", 0))
    internal_fee = compute_degressive(
        internal_vol, ach["internal_settlement_bands"]
    )

    orig_rate = to_dec(settle["originator"])
    benef_rate = to_dec(settle["beneficiary"])

    settle_tx = Decimal("0")
    for field in [
        "settled_ip_orig", "unsettled_ip_orig",
        "settled_recall_orig", "unsettled_recall_orig",
    ]:
        settle_tx += Decimal(int(vol.get(field, 0))) * orig_rate

    for field in [
        "settled_ip_benef", "unsettled_ip_benef",
        "settled_recall_benef", "unsettled_recall_benef",
    ]:
        settle_tx += Decimal(int(vol.get(field, 0))) * benef_rate

    tx = internal_fee + settle_tx
    total = round_dec(fixed + bic + tx, 2)

    return total, {
        "service": "TIPS",
        "fixed_fee": float(round_dec(fixed, 2)),
        "transaction_fee": float(round_dec(tx, 2)),
        "bic_fee": float(round_dec(bic, 2)),
        "lt_fee": 0.0,
        "other_fee": 0.0,
    }


# ================================================================
# Main
# ================================================================

def main():
    base = "/app"
    schedule_path = os.path.join(base, "pricing_schedule.txt")
    db_path = os.path.join(base, "billing.db")
    ref_path = os.path.join(base, "reference_invoices.json")
    invoices_path = os.path.join(base, "invoices.json")
    recon_path = os.path.join(base, "reconciliation.json")

    # 1. Parse pricing schedule
    rules = parse_pricing_schedule(schedule_path)

    # 2. Query data from existing database (created by run_pipeline.sh)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    participants = {}
    for row in conn.execute("SELECT * FROM participants"):
        participants[row["id"]] = dict(row)

    billing_groups = []
    for row in conn.execute("SELECT * FROM billing_groups"):
        bg = dict(row)
        members = [
            r["participant_id"]
            for r in conn.execute(
                "SELECT participant_id FROM billing_group_members "
                "WHERE group_id=?",
                (bg["id"],),
            )
        ]
        bg["members"] = members
        billing_groups.append(bg)

    volumes = {}
    for table in [
        "rtgs_bank_volumes", "rtgs_as_volumes", "t2s_activity",
        "tips_psp_volumes", "tips_ach_volumes",
    ]:
        for row in conn.execute(f"SELECT * FROM {table}"):
            volumes[row["participant_id"]] = dict(row)

    # 3. Compute billing-group unit prices
    bg_unit_prices = {}
    for bg in billing_groups:
        members = bg["members"]
        total_orders = sum(
            int(volumes[m]["payment_orders"]) for m in members
        )
        bands = rules["rtgs"]["core"]["option_b"]["bands"]
        total_fee = compute_degressive(total_orders, bands)
        unit_price = round_dec(total_fee / Decimal(total_orders), 4)
        for m in members:
            bg_unit_prices[m] = unit_price

    # 4. Compute invoices and fee breakdowns
    invoices = {}
    breakdowns = {}

    for pid, part in participants.items():
        ptype = part["type"]
        service = part.get("service", "")
        vol = volumes.get(pid, {})

        # Handle empty-string pricing_option from sqlite3 CSV import
        if part.get("pricing_option") == "":
            part["pricing_option"] = None

        if ptype == "ancillary_system":
            total, bd = invoice_rtgs_as(vol, part, rules)
        elif ptype == "payment_bank" and service == "RTGS":
            total, bd = invoice_rtgs_bank(
                vol, part, rules, bg_unit_prices.get(pid)
            )
        elif ptype == "payment_bank" and service == "T2S":
            total, bd = invoice_t2s(vol, rules)
        elif ptype == "psp":
            total, bd = invoice_tips_psp(vol, rules)
        elif ptype == "ach":
            total, bd = invoice_tips_ach(vol, rules)
        else:
            continue

        invoices[pid] = {"total": float(total)}
        breakdowns[pid] = bd
        breakdowns[pid]["total"] = float(total)

    # 5. Populate fee_breakdown table
    conn.execute("DELETE FROM fee_breakdown")
    for pid, bd in breakdowns.items():
        conn.execute(
            "INSERT INTO fee_breakdown "
            "(participant_id, service, fixed_fee, transaction_fee, "
            "bic_fee, lt_fee, other_fee, total) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pid, bd["service"], bd["fixed_fee"], bd["transaction_fee"],
                bd["bic_fee"], bd["lt_fee"], bd["other_fee"], bd["total"],
            ),
        )
    conn.commit()
    conn.close()

    # 6. Write invoices
    with open(invoices_path, "w") as f:
        json.dump(invoices, f, indent=2)

    # 7. Reconciliation
    with open(ref_path) as f:
        reference = json.load(f)

    discrepancies = []
    matched = []
    for pid, ref_inv in reference.items():
        if pid not in invoices:
            continue
        computed = invoices[pid]["total"]
        ref_total = ref_inv["total"]
        delta = round(computed - ref_total, 2)
        if abs(delta) > 0.01:
            discrepancies.append({
                "participant_id": pid,
                "computed": computed,
                "reference": ref_total,
                "delta": delta,
            })
        else:
            matched.append(pid)

    recon = {"discrepancies": discrepancies, "matched": sorted(matched)}
    with open(recon_path, "w") as f:
        json.dump(recon, f, indent=2)

    print(f"Computed {len(invoices)} invoices.")
    print(
        f"Reconciliation: {len(discrepancies)} discrepancies, "
        f"{len(matched)} matched."
    )


if __name__ == "__main__":
    main()
