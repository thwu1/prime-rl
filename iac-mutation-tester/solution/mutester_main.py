#!/usr/bin/env python3
"""
Mutation testing framework with section-isolation analysis for OPA Rego policies
that validate Terraform plan JSONs.
"""

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile


SECTION_NAMES = ["configuration", "planned_values", "resource_changes"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Mutation testing with section-isolation analysis"
    )
    parser.add_argument("--plan", required=True, help="Terraform plan JSON path")
    parser.add_argument("--policy", required=True, help="OPA Rego policy path")
    parser.add_argument("--output", required=True, help="Output report JSON path")
    return parser.parse_args()


def load_json(path):
    with open(path) as f:
        return json.load(f)


def extract_all_values(obj):
    values = []
    if isinstance(obj, dict):
        for v in obj.values():
            values.extend(extract_all_values(v))
    elif isinstance(obj, list):
        for v in obj:
            values.extend(extract_all_values(v))
    else:
        values.append(obj)
    return values


def evaluate_opa(plan, policy_path):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(plan, f)
        temp_plan = f.name
    try:
        result = subprocess.run(
            ["opa", "eval", "-i", temp_plan, "-d", policy_path, "data"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False
        output = json.loads(result.stdout)
        values = extract_all_values(
            output["result"][0]["expressions"][0]["value"]
        )
        return False not in values
    except Exception:
        return False
    finally:
        os.unlink(temp_plan)


# ---- Resource/field discovery ----

def get_all_resource_addresses(plan):
    addresses = set()
    for r in plan.get("planned_values", {}).get("root_module", {}).get("resources", []):
        addresses.add(r["address"])
    for rc in plan.get("resource_changes", []):
        addresses.add(rc["address"])
    for r in plan.get("configuration", {}).get("root_module", {}).get("resources", []):
        addresses.add(r["address"])
    return sorted(addresses)


def collect_fields_for_resource(plan, address):
    fields = set()
    for r in plan.get("configuration", {}).get("root_module", {}).get("resources", []):
        if r["address"] == address:
            for fn in r.get("expressions", {}):
                fields.add(fn)
    for r in plan.get("planned_values", {}).get("root_module", {}).get("resources", []):
        if r["address"] == address:
            for fn in r.get("values", {}):
                fields.add(fn)
    for rc in plan.get("resource_changes", []):
        if rc["address"] == address:
            after = rc.get("change", {}).get("after")
            if after and isinstance(after, dict):
                for fn in after:
                    fields.add(fn)
    return sorted(fields)


# ---- Section-specific mutation helpers ----

def remove_field_from_section(mutant, section, address, field):
    """Remove field from one section. Returns True if found and removed."""
    if section == "configuration":
        for r in mutant.get("configuration", {}).get("root_module", {}).get("resources", []):
            if r["address"] == address:
                exprs = r.get("expressions", {})
                if field in exprs:
                    del exprs[field]
                    return True
    elif section == "planned_values":
        for r in mutant.get("planned_values", {}).get("root_module", {}).get("resources", []):
            if r["address"] == address:
                vals = r.get("values", {})
                if field in vals:
                    del vals[field]
                    return True
    elif section == "resource_changes":
        for rc in mutant.get("resource_changes", []):
            if rc["address"] == address:
                after = rc.get("change", {}).get("after")
                if after and isinstance(after, dict) and field in after:
                    del after[field]
                    return True
    return False


def alter_value(value):
    if isinstance(value, bool):
        return not value
    elif isinstance(value, str):
        return value + "_MUTATED"
    elif isinstance(value, int):
        return value + 99999
    elif isinstance(value, float):
        return value + 99999.0
    elif isinstance(value, list):
        return ["MUTATED_ENTRY"] if len(value) == 0 else []
    elif isinstance(value, dict):
        return {"MUTATED_KEY": True} if len(value) == 0 else {}
    return value


def alter_value_in_section(mutant, section, address, field, new_value):
    """Alter field value in one section. Returns True if found and altered."""
    if section == "configuration":
        for r in mutant.get("configuration", {}).get("root_module", {}).get("resources", []):
            if r["address"] == address:
                exprs = r.get("expressions", {})
                if field in exprs and isinstance(exprs[field], dict) and "constant_value" in exprs[field]:
                    exprs[field] = {"constant_value": new_value}
                    return True
    elif section == "planned_values":
        for r in mutant.get("planned_values", {}).get("root_module", {}).get("resources", []):
            if r["address"] == address:
                vals = r.get("values", {})
                if field in vals:
                    vals[field] = new_value
                    return True
    elif section == "resource_changes":
        for rc in mutant.get("resource_changes", []):
            if rc["address"] == address:
                after = rc.get("change", {}).get("after")
                if after and isinstance(after, dict) and field in after:
                    after[field] = new_value
                    return True
    return False


def get_original_config_value(plan, address, field):
    """Get original constant_value for a field from configuration."""
    for r in plan.get("configuration", {}).get("root_module", {}).get("resources", []):
        if r["address"] == address:
            expr = r.get("expressions", {}).get(field)
            if isinstance(expr, dict) and "constant_value" in expr:
                return expr["constant_value"]
    return None


def run_section_isolated_tests_removal(plan, policy_path, address, field):
    """Run section-isolated field_removal tests."""
    results = {}
    for section in SECTION_NAMES:
        iso_mutant = copy.deepcopy(plan)
        if remove_field_from_section(iso_mutant, section, address, field):
            iso_killed = not evaluate_opa(iso_mutant, policy_path)
            results[f"{section}_only"] = iso_killed
        else:
            results[f"{section}_only"] = None
    return results


def run_section_isolated_tests_alteration(plan, policy_path, address, field, new_value):
    """Run section-isolated value_alteration tests."""
    results = {}
    for section in SECTION_NAMES:
        iso_mutant = copy.deepcopy(plan)
        if alter_value_in_section(iso_mutant, section, address, field, new_value):
            iso_killed = not evaluate_opa(iso_mutant, policy_path)
            results[f"{section}_only"] = iso_killed
        else:
            results[f"{section}_only"] = None
    return results


# ---- Mutation generators ----

def generate_field_removal_mutants(plan, policy_path):
    mutants = []
    for address in get_all_resource_addresses(plan):
        fields = collect_fields_for_resource(plan, address)
        for field in fields:
            # All-sections mutant
            mutant = copy.deepcopy(plan)
            for section in SECTION_NAMES:
                remove_field_from_section(mutant, section, address, field)
            killed = not evaluate_opa(mutant, policy_path)

            # Section-isolated tests
            iso_results = run_section_isolated_tests_removal(plan, policy_path, address, field)
            section_results = {"all_sections": killed, **iso_results}

            mutants.append({
                "operator": "field_removal",
                "target_resource": address,
                "target_field": field,
                "killed": killed,
                "section_results": section_results,
            })
    return mutants


def generate_value_alteration_mutants(plan, policy_path):
    mutants = []
    for address in get_all_resource_addresses(plan):
        conf_resources = plan.get("configuration", {}).get("root_module", {}).get("resources", [])
        config_fields = {}
        for r in conf_resources:
            if r["address"] == address:
                for field_name, expr in r.get("expressions", {}).items():
                    if isinstance(expr, dict) and "constant_value" in expr:
                        config_fields[field_name] = expr["constant_value"]

        for field, original in sorted(config_fields.items()):
            new_value = alter_value(original)
            if new_value == original:
                continue

            # All-sections mutant
            mutant = copy.deepcopy(plan)
            for section in SECTION_NAMES:
                alter_value_in_section(mutant, section, address, field, new_value)
            killed = not evaluate_opa(mutant, policy_path)

            # Section-isolated tests
            iso_results = run_section_isolated_tests_alteration(
                plan, policy_path, address, field, new_value
            )
            section_results = {"all_sections": killed, **iso_results}

            mutants.append({
                "operator": "value_alteration",
                "target_resource": address,
                "target_field": field,
                "killed": killed,
                "section_results": section_results,
            })
    return mutants


NULL_SECTION_RESULTS = {
    "configuration_only": None,
    "planned_values_only": None,
    "resource_changes_only": None,
}


def generate_type_change_mutants(plan, policy_path):
    mutants = []
    fake_type = "aws_null_resource"
    for address in get_all_resource_addresses(plan):
        mutant = copy.deepcopy(plan)
        original_type = None
        for r in mutant.get("configuration", {}).get("root_module", {}).get("resources", []):
            if r["address"] == address:
                original_type = r["type"]
                r["type"] = fake_type
        for r in mutant.get("planned_values", {}).get("root_module", {}).get("resources", []):
            if r["address"] == address:
                r["type"] = fake_type
        for rc in mutant.get("resource_changes", []):
            if rc["address"] == address:
                rc["type"] = fake_type
        if original_type:
            killed = not evaluate_opa(mutant, policy_path)
            mutants.append({
                "operator": "type_change",
                "target_resource": address,
                "killed": killed,
                "section_results": {"all_sections": killed, **NULL_SECTION_RESULTS},
            })
    return mutants


def generate_reference_break_mutants(plan, policy_path):
    mutants = []
    conf_resources = plan.get("configuration", {}).get("root_module", {}).get("resources", [])
    for r in conf_resources:
        address = r["address"]
        for field_name, expr in r.get("expressions", {}).items():
            if isinstance(expr, dict) and "references" in expr:
                mutant = copy.deepcopy(plan)
                for mr in mutant.get("configuration", {}).get("root_module", {}).get("resources", []):
                    if mr["address"] == address:
                        mr["expressions"][field_name] = {
                            "references": [
                                "nonexistent_resource.fake.id",
                                "nonexistent_resource.fake",
                            ]
                        }
                killed = not evaluate_opa(mutant, policy_path)
                mutants.append({
                    "operator": "reference_break",
                    "target_resource": address,
                    "target_field": field_name,
                    "killed": killed,
                    "section_results": {"all_sections": killed, **NULL_SECTION_RESULTS},
                })
    return mutants


def generate_resource_removal_mutants(plan, policy_path):
    mutants = []
    for address in get_all_resource_addresses(plan):
        mutant = copy.deepcopy(plan)
        resource_type = None
        for r in plan.get("configuration", {}).get("root_module", {}).get("resources", []):
            if r["address"] == address:
                resource_type = r["type"]
                break
        conf = mutant.get("configuration", {}).get("root_module", {})
        conf["resources"] = [r for r in conf.get("resources", []) if r["address"] != address]
        pv = mutant.get("planned_values", {}).get("root_module", {})
        pv["resources"] = [r for r in pv.get("resources", []) if r["address"] != address]
        mutant["resource_changes"] = [
            rc for rc in mutant.get("resource_changes", []) if rc["address"] != address
        ]
        if resource_type:
            killed = not evaluate_opa(mutant, policy_path)
            mutants.append({
                "operator": "resource_removal",
                "target_resource": address,
                "killed": killed,
                "section_results": {"all_sections": killed, **NULL_SECTION_RESULTS},
            })
    return mutants


# ---- Analysis functions ----

def compute_coverage_analysis(results):
    field_results = {}
    for m in results:
        field = m.get("target_field")
        if field and m["operator"] in ("field_removal", "value_alteration"):
            addr = m["target_resource"]
            key = (addr, field)
            if key not in field_results:
                field_results[key] = []
            field_results[key].append(m["killed"])

    coverage = {}
    for (addr, field), kills in sorted(field_results.items()):
        if addr not in coverage:
            coverage[addr] = {"covered_fields": [], "uncovered_fields": []}
        if any(kills):
            coverage[addr]["covered_fields"].append(field)
        else:
            coverage[addr]["uncovered_fields"].append(field)

    for addr in coverage:
        coverage[addr]["covered_fields"].sort()
        coverage[addr]["uncovered_fields"].sort()

    return coverage


def compute_section_analysis(results):
    """Build per-resource, per-field section dependency map from isolation results."""
    field_section_data = {}  # (addr, field) -> {section: [killed_bools]}

    for m in results:
        field = m.get("target_field")
        if not field or m["operator"] not in ("field_removal", "value_alteration"):
            continue
        addr = m["target_resource"]
        key = (addr, field)
        if key not in field_section_data:
            field_section_data[key] = {s: [] for s in SECTION_NAMES}

        sr = m.get("section_results", {})
        for section in SECTION_NAMES:
            val = sr.get(f"{section}_only")
            if val is not None:
                field_section_data[key][section].append(val)

    analysis = {}
    for (addr, field), sections in sorted(field_section_data.items()):
        if addr not in analysis:
            analysis[addr] = {}
        detected = []
        undetected = []
        for section in SECTION_NAMES:
            if sections[section]:  # non-empty results list
                if any(sections[section]):
                    detected.append(section)
                else:
                    undetected.append(section)
            # empty list = field doesn't exist in this section, skip

        analysis[addr][field] = {
            "detected_in_sections": detected,
            "undetected_in_sections": undetected,
        }

    return analysis


def detect_cross_section_gaps(section_analysis):
    """Find fields validated in some sections but not others."""
    gaps = []
    for addr, fields in sorted(section_analysis.items()):
        for field, data in sorted(fields.items()):
            if data["detected_in_sections"] and data["undetected_in_sections"]:
                gaps.append({
                    "resource": addr,
                    "field": field,
                    "validated_in": data["detected_in_sections"],
                    "missing_in": data["undetected_in_sections"],
                })
    return gaps


def apply_mutation_to_plan(mutant_plan, meta, original_plan):
    """Apply a single mutation to a plan (for higher-order testing)."""
    addr = meta["target_resource"]
    field = meta.get("target_field")
    op = meta["operator"]

    if op == "field_removal" and field:
        for section in SECTION_NAMES:
            remove_field_from_section(mutant_plan, section, addr, field)
    elif op == "value_alteration" and field:
        original_val = get_original_config_value(original_plan, addr, field)
        if original_val is not None:
            new_val = alter_value(original_val)
            for section in SECTION_NAMES:
                alter_value_in_section(mutant_plan, section, addr, field, new_val)
    elif op == "reference_break" and field:
        for r in mutant_plan.get("configuration", {}).get("root_module", {}).get("resources", []):
            if r["address"] == addr and field in r.get("expressions", {}):
                r["expressions"][field] = {
                    "references": ["nonexistent_resource.fake.id", "nonexistent_resource.fake"]
                }


def test_higher_order_pairs(plan, policy_path, results):
    """Test pairs of surviving mutants on the same resource."""
    survived_by_resource = {}
    for m in results:
        if not m["killed"]:
            addr = m["target_resource"]
            if addr not in survived_by_resource:
                survived_by_resource[addr] = []
            survived_by_resource[addr].append(m)

    pairs = []
    for addr, muts in survived_by_resource.items():
        if len(muts) < 2:
            continue
        tested = 0
        for i in range(len(muts)):
            for j in range(i + 1, len(muts)):
                if tested >= 10:
                    break
                m_a, m_b = muts[i], muts[j]
                # Skip pairs targeting the same field
                if (m_a.get("target_field") and m_b.get("target_field")
                        and m_a["target_field"] == m_b["target_field"]):
                    continue

                combined = copy.deepcopy(plan)
                apply_mutation_to_plan(combined, m_a, plan)
                apply_mutation_to_plan(combined, m_b, plan)

                combined_killed = not evaluate_opa(combined, policy_path)
                pairs.append({
                    "mutant_a": m_a["id"],
                    "mutant_b": m_b["id"],
                    "combined_killed": combined_killed,
                })
                tested += 1
            if tested >= 10:
                break

    return {
        "pairs_tested": len(pairs),
        "synergistic_kills": sum(1 for p in pairs if p["combined_killed"]),
        "pairs": pairs,
    }


# ---- Main ----

def run_mutation_testing(plan_path, policy_path):
    plan = load_json(plan_path)

    if not evaluate_opa(plan, policy_path):
        print("ERROR: Baseline plan does not pass the policy.", file=sys.stderr)
        sys.exit(1)

    # Generate and test all first-order mutants
    all_results = []
    all_results.extend(generate_field_removal_mutants(plan, policy_path))
    all_results.extend(generate_value_alteration_mutants(plan, policy_path))
    all_results.extend(generate_type_change_mutants(plan, policy_path))
    all_results.extend(generate_reference_break_mutants(plan, policy_path))
    all_results.extend(generate_resource_removal_mutants(plan, policy_path))

    # Assign sequential IDs
    for i, m in enumerate(all_results):
        m["id"] = f"mutant_{i:04d}"

    # Statistics
    total = len(all_results)
    killed = sum(1 for r in all_results if r["killed"])
    survived = total - killed
    score = round(killed / total, 4) if total > 0 else 0.0

    # Operator summary
    operators = sorted(set(r["operator"] for r in all_results))
    operator_summary = {}
    for op in operators:
        op_results = [r for r in all_results if r["operator"] == op]
        op_killed = sum(1 for r in op_results if r["killed"])
        operator_summary[op] = {
            "total": len(op_results),
            "killed": op_killed,
            "survived": len(op_results) - op_killed,
        }

    # Coverage analysis
    coverage = compute_coverage_analysis(all_results)

    # Section analysis
    section_analysis = compute_section_analysis(all_results)

    # Cross-section gaps
    cross_section_gaps = detect_cross_section_gaps(section_analysis)

    # Higher-order mutations
    higher_order = test_higher_order_pairs(plan, policy_path, all_results)

    return {
        "total_mutants": total,
        "killed": killed,
        "survived": survived,
        "mutation_score": score,
        "operator_summary": operator_summary,
        "mutants": all_results,
        "coverage_analysis": coverage,
        "section_analysis": section_analysis,
        "cross_section_gaps": cross_section_gaps,
        "higher_order_results": higher_order,
    }


def main():
    args = parse_args()
    report = run_mutation_testing(args.plan, args.policy)

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Mutation testing complete.")
    print(f"Total: {report['total_mutants']}, Killed: {report['killed']}, "
          f"Survived: {report['survived']}, Score: {report['mutation_score']:.2%}")
    print(f"Cross-section gaps: {len(report['cross_section_gaps'])}")
    ho = report["higher_order_results"]
    print(f"Higher-order: {ho['pairs_tested']} pairs, "
          f"{ho['synergistic_kills']} synergistic kills")


if __name__ == "__main__":
    main()
