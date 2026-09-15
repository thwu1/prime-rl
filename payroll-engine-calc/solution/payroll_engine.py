#!/usr/bin/env python3

"""Payroll calculation engine that processes multiple scenario types."""

import json
import math


def round_cents(value):
    """Round to nearest cent using half-up rounding."""
    return math.floor(value * 100 + 0.5) / 100


def compute_fit_percentage(taxable_wages, filing_status, pay_frequency, config):
    """Compute FIT using percentage method brackets."""
    method = config["fit_percentage_method"][pay_frequency][filing_status]
    sd = method["standard_deduction_per_period"]
    adjusted = taxable_wages - sd
    if adjusted <= 0:
        return 0.0
    brackets = method["brackets"]
    for b in brackets:
        bmax = b["max"]
        if bmax is None or adjusted < bmax:
            return round_cents(b["base_tax"] + b["rate"] * (adjusted - b["over"]))
    # Should not reach here
    last = brackets[-1]
    return round_cents(last["base_tax"] + last["rate"] * (adjusted - last["over"]))


def compute_imputed_income(group_term_life, age, pay_periods, config):
    """Compute per-period group-term life imputed income."""
    if not group_term_life:
        return 0.0
    coverage = group_term_life["coverage_amount"]
    emp_monthly = group_term_life["employee_monthly_contribution"]
    coverage_over = max(0, coverage - 50000)
    # Round to nearest $100
    coverage_over = round(coverage_over / 100) * 100
    units = coverage_over / 1000
    # Look up cost by age
    cost_per_1000 = 0.0
    for entry in config["group_term_life_table"]:
        if entry["min_age"] <= age <= entry["max_age"]:
            cost_per_1000 = entry["cost_per_1000"]
            break
    monthly_cost = units * cost_per_1000
    annual_imputed = monthly_cost * 12 - emp_monthly * 12
    if annual_imputed < 0:
        annual_imputed = 0.0
    return round_cents(annual_imputed / pay_periods)


def compute_ss_tax(fica_wages, ytd_fica_wages, config):
    """Compute SS tax handling wage base crossing."""
    ss_rate = config["fica"]["ss_rate"]
    ss_base = config["fica"]["ss_wage_base"]
    ss_remaining = max(0, ss_base - ytd_fica_wages)
    ss_taxable = min(fica_wages, ss_remaining)
    ss_tax = round_cents(ss_taxable * ss_rate)
    return ss_taxable, ss_tax


def compute_medicare_tax(fica_wages, ytd_fica_wages, config):
    """Compute Medicare and Additional Medicare tax."""
    med_rate = config["fica"]["medicare_rate"]
    add_rate = config["fica"]["additional_medicare_rate"]
    threshold = config["fica"]["additional_medicare_threshold"]
    medicare_tax = round_cents(fica_wages * med_rate)
    # Additional Medicare Tax
    cumulative = ytd_fica_wages + fica_wages
    if cumulative > threshold:
        above = cumulative - threshold
        taxable_this_period = min(fica_wages, above)
        add_medicare = round_cents(taxable_this_period * add_rate)
    else:
        add_medicare = 0.0
    return medicare_tax, add_medicare


def process_regular(scenario, config):
    """Process a regular paycheck scenario."""
    emp = scenario["employee"]
    comp = scenario["compensation"]
    deductions = scenario.get("deductions", {})
    ytd = scenario["ytd_fica_wages"]
    pay_freq = emp["pay_frequency"]
    pay_periods = config["pay_periods"][pay_freq]
    filing = emp["filing_status"]
    state = emp["state"]
    age = emp.get("age", 0)

    gross = round_cents(comp["annual_salary"] / pay_periods)

    # Group-term life imputed income
    gtl = scenario.get("group_term_life")
    imputed = compute_imputed_income(gtl, age, pay_periods, config)

    # Pre-tax deductions
    k401_pct = deductions.get("traditional_401k_pct", 0.0)
    pretax_401k = round_cents(gross * k401_pct)
    pretax_health = deductions.get("section_125_health", 0.0)

    # FIT taxable wages (401k and S125 both reduce, imputed adds)
    fit_taxable = round_cents(gross - pretax_401k - pretax_health + imputed)

    # FIT withholding
    fit = compute_fit_percentage(fit_taxable, filing, pay_freq, config)

    # FICA wages (only S125 reduces, 401k does NOT)
    fica_wages = round_cents(gross - pretax_health + imputed)

    # SS
    ss_taxable, ss_tax = compute_ss_tax(fica_wages, ytd, config)

    # Medicare
    medicare_tax, add_medicare = compute_medicare_tax(fica_wages, ytd, config)

    # State tax
    state_taxable = fit_taxable  # same base as FIT but without SD
    state_rate = config["state_taxes"][state]["rate"]
    state_tax = round_cents(state_taxable * state_rate)

    # Net pay
    net = round_cents(
        gross - pretax_401k - pretax_health - fit - ss_tax
        - medicare_tax - add_medicare - state_tax
    )

    return {
        "id": scenario["id"],
        "type": "regular",
        "gross_pay": gross,
        "imputed_income": imputed,
        "pretax_401k": pretax_401k,
        "pretax_health": pretax_health,
        "fit_taxable_wages": fit_taxable,
        "fit_withholding": fit,
        "ss_taxable_wages": ss_taxable,
        "ss_tax": ss_tax,
        "medicare_taxable_wages": fica_wages,
        "medicare_tax": medicare_tax,
        "additional_medicare_tax": add_medicare,
        "state_taxable_wages": state_taxable,
        "state_tax": state_tax,
        "net_pay": net,
    }


def process_regular_with_garnishment(scenario, config):
    """Process a regular paycheck with child support garnishment."""
    # First compute all regular paycheck fields
    result = process_regular(scenario, config)
    result["type"] = "regular_with_garnishment"

    # Compute garnishment
    garnishment = scenario["garnishment"]
    order_amount = garnishment["order_amount"]
    supporting_another = garnishment["supporting_another"]
    arrears = garnishment["arrears_over_12_weeks"]

    # CCPA limit percentage
    if supporting_another:
        ccpa_pct = 0.55 if arrears else 0.50
    else:
        ccpa_pct = 0.65 if arrears else 0.60

    # Disposable earnings = gross - legally required withholdings
    disposable = round_cents(
        result["gross_pay"]
        - result["fit_withholding"]
        - result["ss_tax"]
        - result["medicare_tax"]
        - result["additional_medicare_tax"]
        - result["state_tax"]
    )

    max_garnishment = round_cents(disposable * ccpa_pct)
    actual_garnishment = round_cents(min(order_amount, max_garnishment))
    net_after = round_cents(result["net_pay"] - actual_garnishment)

    result.update({
        "disposable_earnings": disposable,
        "ccpa_limit_pct": ccpa_pct,
        "max_garnishment": max_garnishment,
        "actual_garnishment": actual_garnishment,
        "net_pay_after_garnishment": net_after,
    })

    return result


def process_bonus_aggregate(scenario, config):
    """Process bonus with aggregate method."""
    emp = scenario["employee"]
    comp = scenario["compensation"]
    ytd = scenario["ytd_fica_wages"]
    pay_freq = emp["pay_frequency"]
    filing = emp["filing_status"]
    state = emp["state"]

    regular_gross = comp["regular_biweekly_gross"]
    bonus = comp["bonus_amount"]

    # FIT on regular only (no pre-tax deductions in this scenario)
    fit_regular = compute_fit_percentage(regular_gross, filing, pay_freq, config)

    # FIT on combined
    combined = regular_gross + bonus
    fit_combined = compute_fit_percentage(combined, filing, pay_freq, config)

    fit_on_bonus = round_cents(fit_combined - fit_regular)

    # FICA on bonus
    # Check SS cap: ytd + regular + bonus
    ss_rate = config["fica"]["ss_rate"]
    ss_base = config["fica"]["ss_wage_base"]
    # SS remaining after regular wages this period
    ss_remaining_after_regular = max(0, ss_base - ytd - regular_gross)
    ss_on_bonus_taxable = min(bonus, ss_remaining_after_regular)
    ss_on_bonus = round_cents(ss_on_bonus_taxable * ss_rate)

    med_rate = config["fica"]["medicare_rate"]
    medicare_on_bonus = round_cents(bonus * med_rate)

    # Additional Medicare on bonus
    add_rate = config["fica"]["additional_medicare_rate"]
    threshold = config["fica"]["additional_medicare_threshold"]
    cumulative = ytd + regular_gross + bonus
    if cumulative > threshold:
        above = cumulative - threshold
        prior_above = max(0, (ytd + regular_gross) - threshold)
        taxable = above - prior_above
        add_medicare_on_bonus = round_cents(min(bonus, taxable) * add_rate)
    else:
        add_medicare_on_bonus = 0.0

    # State on bonus (flat rate)
    state_rate = config["state_taxes"][state]["rate"]
    state_on_bonus = round_cents(bonus * state_rate)

    total_taxes = round_cents(
        fit_on_bonus + ss_on_bonus + medicare_on_bonus
        + add_medicare_on_bonus + state_on_bonus
    )
    net_bonus = round_cents(bonus - total_taxes)

    return {
        "id": scenario["id"],
        "type": "bonus_aggregate",
        "regular_gross": regular_gross,
        "bonus_gross": bonus,
        "fit_regular_only": fit_regular,
        "fit_combined": fit_combined,
        "fit_on_bonus": fit_on_bonus,
        "ss_on_bonus": ss_on_bonus,
        "medicare_on_bonus": medicare_on_bonus,
        "additional_medicare_on_bonus": add_medicare_on_bonus,
        "state_on_bonus": state_on_bonus,
        "total_bonus_taxes": total_taxes,
        "net_bonus": net_bonus,
    }


def compute_supplemental_taxes(gross, ytd_fica_wages, state, config):
    """Compute taxes on supplemental wages using flat rates."""
    fit_rate = config["federal_supplemental_flat_rate"]
    fit = round_cents(gross * fit_rate)

    ss_taxable, ss_tax = compute_ss_tax(gross, ytd_fica_wages, config)
    medicare_tax, add_medicare = compute_medicare_tax(gross, ytd_fica_wages, config)

    state_rate = config["state_taxes"][state]["rate"]
    state_tax = round_cents(gross * state_rate)

    total = round_cents(fit + ss_tax + medicare_tax + add_medicare + state_tax)
    return fit, ss_tax, medicare_tax, add_medicare, state_tax, total


def process_gross_up(scenario, config):
    """Process gross-up calculation with SS wage base boundary."""
    desired_net = scenario["desired_net"]
    ytd = scenario["ytd_fica_wages"]
    state = scenario["employee"]["state"]

    fit_rate = config["federal_supplemental_flat_rate"]
    ss_rate = config["fica"]["ss_rate"]
    med_rate = config["fica"]["medicare_rate"]
    add_med_rate = config["fica"]["additional_medicare_rate"]
    ss_base = config["fica"]["ss_wage_base"]
    med_threshold = config["fica"]["additional_medicare_threshold"]
    state_rate = config["state_taxes"][state]["rate"]

    ss_remaining = max(0, ss_base - ytd)
    med_remaining = max(0, med_threshold - ytd)

    # Rate components (excluding SS and Additional Medicare which may be piecewise)
    base_rate = fit_rate + med_rate + state_rate

    # Try simple formula first (all taxes apply uniformly)
    total_rate = base_rate + ss_rate
    simple_gross = desired_net / (1 - total_rate)

    # Check if we need piecewise for SS
    if simple_gross <= ss_remaining:
        # Also check Additional Medicare
        if ytd + simple_gross <= med_threshold:
            gross_estimate = simple_gross
        else:
            rate_with_all = base_rate + ss_rate + add_med_rate
            gross_estimate = (desired_net + (ytd - med_threshold) * add_med_rate) / (1 - rate_with_all)
    else:
        if ytd + simple_gross <= med_threshold:
            gross_estimate = (desired_net + ss_remaining * ss_rate) / (1 - base_rate)
        else:
            gross_estimate = (desired_net + ss_remaining * ss_rate + (ytd - med_threshold) * add_med_rate) / (1 - base_rate - add_med_rate)

    # Convert to cents and search for minimum gross
    gross_cents = int(math.floor(gross_estimate * 100))

    # Search around the estimate
    best_gross = None
    for offset in range(-5, 20):
        g_cents = gross_cents + offset
        g = g_cents / 100.0

        # Compute individual taxes
        t_fit = round_cents(g * fit_rate)
        ss_tax_amt = min(g, ss_remaining)
        t_ss = round_cents(ss_tax_amt * ss_rate)
        t_med = round_cents(g * med_rate)

        # Additional Medicare
        cum = ytd + g
        if cum > med_threshold:
            above = cum - med_threshold
            t_add_med = round_cents(min(g, above) * add_med_rate)
        else:
            t_add_med = 0.0

        t_state = round_cents(g * state_rate)
        total_tax = round_cents(t_fit + t_ss + t_med + t_add_med + t_state)
        net = round_cents(g - total_tax)

        if net >= desired_net:
            best_gross = g
            best_fit = t_fit
            best_ss = t_ss
            best_med = t_med
            best_add_med = t_add_med
            best_state = t_state
            best_total = total_tax
            best_net = net
            break

    return {
        "id": scenario["id"],
        "type": "gross_up",
        "desired_net": desired_net,
        "computed_gross": best_gross,
        "fit": best_fit,
        "ss_tax": best_ss,
        "medicare_tax": best_med,
        "additional_medicare_tax": best_add_med,
        "state_tax": best_state,
        "total_taxes": best_total,
        "actual_net": best_net,
    }


def process_retro_pay(scenario, config):
    """Process retroactive pay with overtime recalculation."""
    old_rate = scenario["old_hourly_rate"]
    new_rate = scenario["new_hourly_rate"]
    weeks_data = scenario["weeks"]
    state = scenario["employee"]["state"]
    ytd = scenario["ytd_fica_wages"]

    ot_mult = config["overtime"]["multiplier"]
    ot_threshold = config["overtime"]["weekly_threshold_hours"]

    rate_diff = new_rate - old_rate
    ot_rate_diff = (new_rate * ot_mult) - (old_rate * ot_mult)

    weeks_output = []
    total_retro = 0.0
    for i, w in enumerate(weeks_data):
        hours = w["hours_worked"]
        reg_hours = min(hours, ot_threshold)
        ot_hours = max(0, hours - ot_threshold)
        reg_diff = round_cents(reg_hours * rate_diff)
        ot_diff = round_cents(ot_hours * ot_rate_diff)
        total_diff = round_cents(reg_diff + ot_diff)
        weeks_output.append({
            "week": i + 1,
            "regular_diff": reg_diff,
            "ot_diff": ot_diff,
            "total_diff": total_diff,
        })
        total_retro += total_diff

    total_retro = round_cents(total_retro)

    # Supplemental wage taxes
    fit, ss_tax, medicare_tax, add_medicare, state_tax, total_taxes = (
        compute_supplemental_taxes(total_retro, ytd, state, config)
    )
    net_retro = round_cents(total_retro - total_taxes)

    return {
        "id": scenario["id"],
        "type": "retro_pay",
        "weeks": weeks_output,
        "total_retro_gross": total_retro,
        "fit": fit,
        "ss_tax": ss_tax,
        "medicare_tax": medicare_tax,
        "additional_medicare_tax": add_medicare,
        "state_tax": state_tax,
        "total_taxes": total_taxes,
        "net_retro": net_retro,
    }


def main():
    with open("/app/payroll_input.json") as f:
        data = json.load(f)

    config = data["tax_config"]
    results = []

    for scenario in data["scenarios"]:
        stype = scenario["type"]
        if stype == "regular":
            results.append(process_regular(scenario, config))
        elif stype == "regular_with_garnishment":
            results.append(process_regular_with_garnishment(scenario, config))
        elif stype == "bonus_aggregate":
            results.append(process_bonus_aggregate(scenario, config))
        elif stype == "gross_up":
            results.append(process_gross_up(scenario, config))
        elif stype == "retro_pay":
            results.append(process_retro_pay(scenario, config))
        else:
            raise ValueError(f"Unknown scenario type: {stype}")

    with open("/app/payroll_output.json", "w") as f:
        json.dump({"results": results}, f, indent=2)


if __name__ == "__main__":
    main()
