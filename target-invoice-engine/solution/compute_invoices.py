#!/usr/bin/env python3
"""
TARGET Services Invoice Computation Engine.

Implements monthly billing for ECB TARGET Services: RTGS (core + ancillary
system), T2S cash-related, and TIPS (PSP + ACH). Handles degressive band
allocation, billing group pro-rata distribution with 4-decimal rounding,
and the full range of fixed/variable fee schedules.
"""

import json
import sys
from decimal import Decimal, ROUND_HALF_UP


def load_json(path):
    with open(path) as f:
        return json.load(f)


def to_dec(value):
    """Convert a numeric value to Decimal via string for exact representation."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_dec(value, places):
    """Round a Decimal to the given number of decimal places (half-up)."""
    quantizer = Decimal(10) ** -places
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


def compute_degressive(volume, bands):
    """
    Apply degressive band pricing cumulatively.

    Each band specifies 'from', 'to' (null for unbounded), and 'fee'.
    Band capacity = to - from + 1 (or unlimited for the last band).
    Items fill bands sequentially.
    """
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
    """Look up the Fixed Fee II monthly amount from the gross underlying value."""
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


def invoice_rtgs_as(participant, rules):
    """Compute RTGS Ancillary System invoice total."""
    as_rules = rules["rtgs"]["ancillary_system"]
    option = participant["pricing_option"]

    # Core fixed fee
    if option == "A":
        core_fee = to_dec(as_rules["option_a"]["monthly_fee"])
        tx_fee = Decimal(int(participant["cash_transfer_orders"])) * to_dec(
            as_rules["option_a"]["fee_per_cash_transfer_order"]
        )
    else:
        core_fee = to_dec(as_rules["option_b"]["monthly_fee"])
        tx_fee = compute_degressive(
            participant["cash_transfer_orders"], as_rules["option_b"]["bands"]
        )

    fee_i = to_dec(as_rules["fixed_fee_i"])
    fee_ii = lookup_fixed_fee_ii(
        participant["daily_gross_underlying_value_eur_millions"],
        as_rules["fixed_fee_ii"],
    )

    total = core_fee + fee_i + fee_ii + tx_fee
    return round_dec(total, 2)


def invoice_rtgs_bank(participant, rules, bg_unit_price=None):
    """Compute RTGS Payment Bank invoice total."""
    core_rules = rules["rtgs"]["core"]
    option = participant["pricing_option"]

    # DCA fixed fee — based on the participant's own option
    if option == "A":
        fixed_fee = to_dec(core_rules["option_a"]["monthly_fee_per_dca"])
    else:
        fixed_fee = to_dec(core_rules["option_b"]["monthly_fee_per_dca"])

    # Payment order fees
    po = int(participant.get("payment_orders", 0))
    if bg_unit_price is not None:
        # Billing group: pro-rata charge
        po_fee = round_dec(Decimal(po) * bg_unit_price, 2)
    else:
        if option == "A":
            po_fee = Decimal(po) * to_dec(core_rules["option_a"]["fee_per_payment_order"])
        else:
            po_fee = compute_degressive(po, core_rules["option_b"]["bands"])

    # BIC registration fees
    bic = rules["rtgs"]["bic_fees"]
    bic_fee = (
        int(participant.get("addressable_bics", 0)) * to_dec(bic["addressable_bic"])
        + int(participant.get("unpublished_bics", 0)) * to_dec(bic["unpublished_bic"])
        + int(participant.get("multi_addressee_bics", 0))
        * to_dec(bic["multi_addressee_access"])
    )

    # Cross-banking-group liquidity transfer fees
    lt_rate = to_dec(rules["rtgs"]["liquidity_transfer_cross_banking_group"])
    lt_count = int(
        participant.get("liquidity_transfers_within_rtgs_cross_banking_group", 0)
    ) + int(
        participant.get("liquidity_transfers_rtgs_to_clm_cross_banking_group", 0)
    )
    lt_fee = Decimal(lt_count) * lt_rate

    total = fixed_fee + po_fee + bic_fee + lt_fee
    return round_dec(total, 2)


def invoice_t2s(participant, rules):
    """Compute T2S Cash-Related Services invoice total."""
    t = rules["t2s"]

    # Map scenario fields to pricing-rule keys
    activity_map = [
        ("messages_bundled_into_file", "messages_bundled_into_file"),
        ("transmissions", "transmission"),
        ("u2a_queries", "u2a_queries"),
        ("a2a_queries", "a2a_queries"),
        ("a2a_reports", "a2a_reports"),
        ("internal_t2s_liquidity_transfers", "internal_liquidity_transfer"),
        ("intra_balance_movements", "intra_balance_movement"),
    ]

    total = Decimal("0")
    for scenario_key, rule_key in activity_map:
        qty = int(participant.get(scenario_key, 0))
        price = to_dec(t[rule_key])
        total += Decimal(qty) * price

    return round_dec(total, 2)


def invoice_tips_psp(participant, rules):
    """Compute TIPS PSP invoice total."""
    psp = rules["tips"]["psp"]
    settle = rules["tips"]["settlement_fee"]

    # Fixed DCA fee
    dcas = int(participant.get("tips_dcas", 0))
    fixed_fee = Decimal(dcas) * to_dec(psp["fixed_fee_per_dca"])

    # BIC fees — first BIC per DCA is free
    total_bics = int(participant.get("tips_dca_aau_bics", 0))
    free_bics = int(psp.get("free_bics_per_account", 1)) * dcas
    max_chargeable = int(psp["max_chargeable_bics_per_account"]) * dcas
    chargeable = max(0, min(total_bics - free_bics, max_chargeable))
    bic_fee = Decimal(chargeable) * to_dec(psp["bic_fee"])

    # Settlement fees
    orig_rate = to_dec(settle["originator"])
    benef_rate = to_dec(settle["beneficiary"])

    settle_total = Decimal("0")
    for field in [
        "settled_ip_originator",
        "unsettled_ip_originator",
        "settled_recall_originator",
        "unsettled_recall_originator",
    ]:
        settle_total += Decimal(int(participant.get(field, 0))) * orig_rate

    for field in [
        "settled_ip_beneficiary",
        "unsettled_ip_beneficiary",
        "settled_recall_beneficiary",
        "unsettled_recall_beneficiary",
    ]:
        settle_total += Decimal(int(participant.get(field, 0))) * benef_rate

    total = fixed_fee + bic_fee + settle_total
    return round_dec(total, 2)


def invoice_tips_ach(participant, rules):
    """Compute TIPS ACH invoice total."""
    ach = rules["tips"]["ach"]
    settle = rules["tips"]["settlement_fee"]

    # Fixed ASTA fee
    astas = int(participant.get("tips_astas", 0))
    fixed_fee = Decimal(astas) * to_dec(ach["fixed_fee_per_asta"])

    # BIC fees — all chargeable from 1st
    total_bics = int(participant.get("tips_asta_aau_bics", 0))
    free_bics = int(ach.get("free_bics_per_account", 0)) * astas
    max_chargeable = int(ach["max_chargeable_bics_per_account"]) * astas
    chargeable = max(0, min(total_bics - free_bics, max_chargeable))
    bic_fee = Decimal(chargeable) * to_dec(ach["bic_fee"])

    # Internal settlement bands
    internal_vol = int(participant.get("internally_settled_ip", 0))
    internal_fee = compute_degressive(internal_vol, ach["internal_settlement_bands"])

    # TIPS settlement fees (for orders settled on the ASTA)
    orig_rate = to_dec(settle["originator"])
    benef_rate = to_dec(settle["beneficiary"])

    settle_total = Decimal("0")
    for field in [
        "settled_ip_originator",
        "unsettled_ip_originator",
        "settled_recall_originator",
        "unsettled_recall_originator",
    ]:
        settle_total += Decimal(int(participant.get(field, 0))) * orig_rate

    for field in [
        "settled_ip_beneficiary",
        "unsettled_ip_beneficiary",
        "settled_recall_beneficiary",
        "unsettled_recall_beneficiary",
    ]:
        settle_total += Decimal(int(participant.get(field, 0))) * benef_rate

    total = fixed_fee + bic_fee + internal_fee + settle_total
    return round_dec(total, 2)


def compute_all_invoices(rules, scenario):
    """Compute invoices for all participants in a scenario."""
    billing_groups = scenario.get("billing_groups", [])
    participants = {p["id"]: p for p in scenario["participants"]}

    # Pre-compute billing-group unit prices
    bg_unit_prices = {}
    rounding_cfg = rules.get("rounding", {})
    up_decimals = int(rounding_cfg.get("billing_group_unit_price_decimals", 4))

    for bg in billing_groups:
        members = bg["members"]
        total_orders = sum(int(participants[m]["payment_orders"]) for m in members)

        # Leader's Option B core bands
        bands = rules["rtgs"]["core"]["option_b"]["bands"]
        total_fee = compute_degressive(total_orders, bands)

        # Unit price rounded to 4 decimal places (half-up at 5th digit)
        unit_price = round_dec(total_fee / Decimal(total_orders), up_decimals)

        for m in members:
            bg_unit_prices[m] = unit_price

    # Compute each participant's invoice
    invoices = {}
    for pid, p in participants.items():
        ptype = p["type"]
        service = p.get("service", "")

        if ptype == "ancillary_system":
            total = invoice_rtgs_as(p, rules)
        elif ptype == "payment_bank" and service == "RTGS":
            total = invoice_rtgs_bank(p, rules, bg_unit_prices.get(pid))
        elif ptype == "payment_bank" and service == "T2S":
            total = invoice_t2s(p, rules)
        elif ptype == "psp":
            total = invoice_tips_psp(p, rules)
        elif ptype == "ach":
            total = invoice_tips_ach(p, rules)
        else:
            continue

        invoices[pid] = {"total": float(total)}

    return invoices


def main():
    if len(sys.argv) != 4:
        print(
            f"Usage: {sys.argv[0]} <pricing_rules.json> <scenario.json> <output.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    rules_path, scenario_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
    rules = load_json(rules_path)
    scenario = load_json(scenario_path)

    invoices = compute_all_invoices(rules, scenario)

    with open(output_path, "w") as f:
        json.dump(invoices, f, indent=2)


if __name__ == "__main__":
    main()
