#!/usr/bin/env python3
"""Audit special function reference table using independent recomputation and DLMF identities."""

import json
from mpmath import mp, mpf, gamma, besselj, airyai, airybi, nstr, pi, sqrt, fabs

mp.dps = 60

COMPUTE_MAP = {
    "gamma_1_3": lambda: gamma(mpf(1) / 3),
    "gamma_2_3": lambda: gamma(mpf(2) / 3),
    "gamma_1_4": lambda: gamma(mpf(1) / 4),
    "gamma_3_4": lambda: gamma(mpf(3) / 4),
    "ai_1": lambda: airyai(mpf(1)),
    "ai_prime_1": lambda: airyai(mpf(1), derivative=1),
    "bi_1": lambda: airybi(mpf(1)),
    "bi_prime_1": lambda: airybi(mpf(1), derivative=1),
    "ai_2": lambda: airyai(mpf(2)),
    "ai_prime_2": lambda: airyai(mpf(2), derivative=1),
    "bi_2": lambda: airybi(mpf(2)),
    "bi_prime_2": lambda: airybi(mpf(2), derivative=1),
    "j0_1": lambda: besselj(0, mpf(1)),
    "j1_1": lambda: besselj(1, mpf(1)),
    "j2_1": lambda: besselj(2, mpf(1)),
    "j0_10": lambda: besselj(0, mpf(10)),
    "ai_0": lambda: airyai(mpf(0)),
    "bi_0": lambda: airybi(mpf(0)),
    "ai_prime_0": lambda: airyai(mpf(0), derivative=1),
    "bi_prime_0": lambda: airybi(mpf(0), derivative=1),
}


def check_identities_on_values(values_dict):
    """Evaluate DLMF functional identities on a dict of {id: mpf_value}."""
    checks = []

    # Gamma reflection: Gamma(1/3) * Gamma(2/3) = 2*pi/sqrt(3)
    if "gamma_1_3" in values_dict and "gamma_2_3" in values_dict:
        lhs = values_dict["gamma_1_3"] * values_dict["gamma_2_3"]
        rhs = 2 * pi / sqrt(3)
        residual = fabs(lhs - rhs)
        checks.append({
            "identity_type": "gamma_reflection",
            "description": "Gamma(1/3)*Gamma(2/3) = 2*pi/sqrt(3)",
            "entries_involved": ["gamma_1_3", "gamma_2_3"],
            "residual": float(residual),
            "passed": bool(residual < mpf("1e-40")),
        })

    # Gamma reflection: Gamma(1/4) * Gamma(3/4) = pi*sqrt(2)
    if "gamma_1_4" in values_dict and "gamma_3_4" in values_dict:
        lhs = values_dict["gamma_1_4"] * values_dict["gamma_3_4"]
        rhs = pi * sqrt(2)
        residual = fabs(lhs - rhs)
        checks.append({
            "identity_type": "gamma_reflection",
            "description": "Gamma(1/4)*Gamma(3/4) = pi*sqrt(2)",
            "entries_involved": ["gamma_1_4", "gamma_3_4"],
            "residual": float(residual),
            "passed": bool(residual < mpf("1e-40")),
        })

    # Airy Wronskians at x = 0, 1, 2
    for x_label in ["0", "1", "2"]:
        ai_id = f"ai_{x_label}"
        aip_id = f"ai_prime_{x_label}"
        bi_id = f"bi_{x_label}"
        bip_id = f"bi_prime_{x_label}"
        ids = [ai_id, aip_id, bi_id, bip_id]
        if all(k in values_dict for k in ids):
            w = values_dict[ai_id] * values_dict[bip_id] - values_dict[aip_id] * values_dict[bi_id]
            expected = 1 / pi
            residual = fabs(w - expected)
            checks.append({
                "identity_type": "airy_wronskian",
                "description": f"Ai({x_label})*Bi'({x_label}) - Ai'({x_label})*Bi({x_label}) = 1/pi",
                "entries_involved": ids,
                "residual": float(residual),
                "passed": bool(residual < mpf("1e-40")),
            })

    # Bessel recurrence: J_0(1) + J_2(1) = 2*J_1(1)
    if all(k in values_dict for k in ["j0_1", "j1_1", "j2_1"]):
        lhs = values_dict["j0_1"] + values_dict["j2_1"]
        rhs = 2 * values_dict["j1_1"]
        residual = fabs(lhs - rhs)
        checks.append({
            "identity_type": "bessel_recurrence",
            "description": "J_0(1) + J_2(1) = 2*J_1(1)",
            "entries_involved": ["j0_1", "j1_1", "j2_1"],
            "residual": float(residual),
            "passed": bool(residual < mpf("1e-40")),
        })

    return checks


def main():
    # Load reference table
    with open("/app/reference_table.json", "r") as f:
        table = json.load(f)

    entries = table["entries"]

    # Step 1: Independent recomputation
    correct_values = {}
    for entry in entries:
        correct_values[entry["id"]] = COMPUTE_MAP[entry["id"]]()

    # Step 2: Compare claimed vs. correct
    errors = []
    validated = []
    error_ids = set()

    for entry in entries:
        eid = entry["id"]
        claimed = mpf(entry["claimed_value"])
        correct = correct_values[eid]

        if correct != 0:
            rel_err = fabs(claimed - correct) / fabs(correct)
        else:
            rel_err = fabs(claimed - correct)

        if rel_err > mpf("1e-45"):
            errors.append({
                "id": eid,
                "function": entry["function"],
                "parameters": entry["parameters"],
                "claimed_value": entry["claimed_value"],
                "corrected_value": nstr(correct, 52, strip_zeros=False),
                "relative_error": float(rel_err),
            })
            error_ids.add(eid)
        else:
            validated.append({
                "id": eid,
                "function": entry["function"],
                "parameters": entry["parameters"],
                "verified_value": nstr(correct, 52, strip_zeros=False),
            })

    # Step 3: Cross-validate using DLMF identities on claimed values
    claimed_dict = {e["id"]: mpf(e["claimed_value"]) for e in entries}
    claimed_checks = check_identities_on_values(claimed_dict)

    # Also check identities on correct values (should all pass)
    correct_checks = check_identities_on_values(correct_values)

    # Step 4: Assign detection methods to errors
    for err in errors:
        detected = False
        for check in claimed_checks:
            if not check["passed"] and err["id"] in check["entries_involved"]:
                err["detected_by"] = {
                    "identity_type": check["identity_type"],
                    "description": check["description"],
                    "identity_residual": check["residual"],
                }
                detected = True
                break
        if not detected:
            err["detected_by"] = {
                "identity_type": "independent_recomputation",
                "description": "Detected via independent high-precision recomputation using mpmath",
            }

    # Step 5: Assign validation methods to correct entries
    for val in validated:
        assigned = False
        for check in correct_checks:
            if check["passed"] and val["id"] in check["entries_involved"]:
                val["validation"] = {
                    "identity_type": check["identity_type"],
                    "description": check["description"],
                    "identity_residual": check["residual"],
                }
                assigned = True
                break
        if not assigned:
            val["validation"] = {
                "identity_type": "independent_recomputation",
                "description": "Verified via independent high-precision recomputation using mpmath",
            }

    # Step 6: Write report
    report = {
        "summary": {
            "total_entries": len(entries),
            "errors_found": len(errors),
            "validated_entries_count": len(validated),
            "identities_checked": len(correct_checks),
        },
        "errors": errors,
        "validated_entries": validated,
        "identity_checks_correct_values": correct_checks,
        "identity_checks_claimed_values": claimed_checks,
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete: {len(errors)} errors found in {len(entries)} entries")
    for err in errors:
        print(f"  - {err['id']}: rel_err={err['relative_error']:.2e}, "
              f"detected by {err['detected_by']['identity_type']}")
    print(f"\nIdentity checks on claimed values:")
    for check in claimed_checks:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['description']} (residual: {check['residual']:.2e})")


if __name__ == "__main__":
    main()
