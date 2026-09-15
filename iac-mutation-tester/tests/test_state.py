
import json
import os
import subprocess
import copy
import tempfile
import pytest

SCENARIOS = ["vpc_network", "dns_loadbalancer", "iam_permissions"]
REQUIRED_OPERATORS = [
    "field_removal",
    "value_alteration",
    "type_change",
    "reference_break",
    "resource_removal",
]
SECTION_NAMES = ["configuration", "planned_values", "resource_changes"]


def extract_values(obj):
    """Recursively extract all leaf values from nested dict/list."""
    values = []
    if isinstance(obj, dict):
        for v in obj.values():
            values.extend(extract_values(v))
    elif isinstance(obj, list):
        for v in obj:
            values.extend(extract_values(v))
    else:
        values.append(obj)
    return values


def run_opa(plan_path, policy_path):
    """Run OPA eval and return whether the plan passes the policy."""
    result = subprocess.run(
        ["opa", "eval", "-i", plan_path, "-d", policy_path, "data"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"OPA eval failed: {result.stderr}"
    output = json.loads(result.stdout)
    values = extract_values(
        output["result"][0]["expressions"][0]["value"]
    )
    return False not in values


def run_tool(scenario, output_path=None):
    """Run the mutation testing tool on a scenario."""
    if output_path is None:
        output_path = f"/tmp/test_report_{scenario}.json"
    plan_path = f"/app/scenarios/{scenario}/plan.json"
    policy_path = f"/app/scenarios/{scenario}/policy.rego"
    result = subprocess.run(
        [
            "python3",
            "/app/mutester/main.py",
            "--plan", plan_path,
            "--policy", policy_path,
            "--output", output_path,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result, output_path


def load_report(path):
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reports():
    """Run the tool once per scenario and cache results for all tests."""
    results = {}
    for scenario in SCENARIOS:
        result, output_path = run_tool(scenario)
        assert result.returncode == 0, (
            f"Tool failed on {scenario}: {result.stderr}\n{result.stdout}"
        )
        assert os.path.isfile(output_path), (
            f"Output file not created for {scenario}"
        )
        results[scenario] = load_report(output_path)
    return results


class TestInfrastructure:
    """Verify OPA and baseline plans work."""

    def test_opa_available(self):
        result = subprocess.run(
            ["opa", "version"], capture_output=True, text=True
        )
        assert result.returncode == 0, "OPA binary not available"

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_baseline_passes(self, scenario):
        plan_path = f"/app/scenarios/{scenario}/plan.json"
        policy_path = f"/app/scenarios/{scenario}/policy.rego"
        assert run_opa(plan_path, policy_path), (
            f"Baseline plan for {scenario} does not pass its policy"
        )

    def test_tool_exists(self):
        assert os.path.isfile("/app/mutester/main.py"), (
            "Tool not found at /app/mutester/main.py"
        )


class TestOutputSchema:
    """Verify the output JSON conforms to the required schema."""

    def test_required_top_level_keys(self, reports):
        report = reports["vpc_network"]
        for key in [
            "total_mutants", "killed", "survived", "mutation_score",
            "operator_summary", "mutants", "coverage_analysis",
            "section_analysis", "cross_section_gaps", "higher_order_results",
        ]:
            assert key in report, f"Missing required key: {key}"

    def test_mutant_record_schema(self, reports):
        report = reports["vpc_network"]
        assert len(report["mutants"]) > 0, "No mutants in report"
        for mutant in report["mutants"]:
            assert "id" in mutant, "Mutant missing 'id'"
            assert "operator" in mutant, "Mutant missing 'operator'"
            assert "killed" in mutant, "Mutant missing 'killed'"
            assert isinstance(mutant["killed"], bool), "'killed' must be boolean"
            assert "target_resource" in mutant, "Mutant missing 'target_resource'"
            assert "section_results" in mutant, "Mutant missing 'section_results'"

    def test_section_results_schema(self, reports):
        report = reports["vpc_network"]
        for mutant in report["mutants"]:
            sr = mutant["section_results"]
            assert "all_sections" in sr, "Missing all_sections in section_results"
            for key in ["configuration_only", "planned_values_only", "resource_changes_only"]:
                assert key in sr, f"Missing {key} in section_results"
                assert sr[key] is None or isinstance(sr[key], bool), (
                    f"{key} must be bool or null, got {type(sr[key])}"
                )

    def test_numeric_consistency(self, reports):
        report = reports["vpc_network"]
        assert report["total_mutants"] == len(report["mutants"])
        assert report["killed"] + report["survived"] == report["total_mutants"]
        if report["total_mutants"] > 0:
            expected_score = report["killed"] / report["total_mutants"]
            assert abs(report["mutation_score"] - expected_score) < 0.01

    def test_section_results_matches_killed(self, reports):
        """section_results.all_sections must match killed."""
        report = reports["vpc_network"]
        for m in report["mutants"]:
            assert m["section_results"]["all_sections"] == m["killed"], (
                f"all_sections ({m['section_results']['all_sections']}) != "
                f"killed ({m['killed']}) for {m['id']}"
            )


class TestMutationResults:
    """Verify mutation testing produces meaningful results."""

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_sufficient_mutants(self, scenario, reports):
        report = reports[scenario]
        assert report["total_mutants"] >= 15, (
            f"Too few mutants for {scenario}: {report['total_mutants']}"
        )

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_some_killed(self, scenario, reports):
        report = reports[scenario]
        assert report["killed"] > 0, (
            f"No mutants killed for {scenario} - OPA eval may be broken"
        )

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_some_survived(self, scenario, reports):
        report = reports[scenario]
        assert report["survived"] > 0, (
            f"All mutants killed for {scenario} - mutations may not be diverse"
        )

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_mutation_score_range(self, scenario, reports):
        report = reports[scenario]
        score = report["mutation_score"]
        assert 0.2 <= score <= 0.95, (
            f"Unusual mutation score for {scenario}: {score}"
        )


class TestOperators:
    """Verify all mutation operators work correctly."""

    def test_all_operators_present(self, reports):
        report = reports["vpc_network"]
        found = set(report["operator_summary"].keys())
        for op in REQUIRED_OPERATORS:
            assert op in found, f"Missing operator in summary: {op}"

    def test_operator_summary_consistency(self, reports):
        report = reports["vpc_network"]
        for op, summary in report["operator_summary"].items():
            op_mutants = [
                m for m in report["mutants"] if m["operator"] == op
            ]
            assert summary["total"] == len(op_mutants), (
                f"Total mismatch for {op}: summary={summary['total']} "
                f"vs detail={len(op_mutants)}"
            )
            op_killed = sum(1 for m in op_mutants if m["killed"])
            assert summary["killed"] == op_killed, (
                f"Killed mismatch for {op}"
            )
            assert summary["survived"] == len(op_mutants) - op_killed, (
                f"Survived mismatch for {op}"
            )

    def test_type_change_all_killed(self, reports):
        """Changing resource types must always be caught by policies."""
        report = reports["vpc_network"]
        tc_mutants = [
            m for m in report["mutants"] if m["operator"] == "type_change"
        ]
        assert len(tc_mutants) > 0, "No type_change mutants found"
        for m in tc_mutants:
            assert m["killed"], (
                f"type_change mutant survived: {m.get('target_resource')}"
            )

    def test_resource_removal_all_killed(self, reports):
        """Removing resources must always be caught by policies."""
        report = reports["vpc_network"]
        rr_mutants = [
            m for m in report["mutants"]
            if m["operator"] == "resource_removal"
        ]
        assert len(rr_mutants) > 0, "No resource_removal mutants found"
        for m in rr_mutants:
            assert m["killed"], (
                f"resource_removal mutant survived: "
                f"{m.get('target_resource')}"
            )

    def test_section_results_null_for_non_eligible(self, reports):
        """type_change, reference_break, resource_removal have null section results."""
        report = reports["vpc_network"]
        for m in report["mutants"]:
            if m["operator"] in ("type_change", "reference_break", "resource_removal"):
                sr = m["section_results"]
                for key in ["configuration_only", "planned_values_only", "resource_changes_only"]:
                    assert sr[key] is None, (
                        f"{m['operator']} mutant {m['id']} should have null {key}"
                    )

    def test_section_results_available_for_eligible(self, reports):
        """field_removal and value_alteration should have at least one non-null section result."""
        report = reports["vpc_network"]
        for m in report["mutants"]:
            if m["operator"] in ("field_removal", "value_alteration"):
                sr = m["section_results"]
                has_result = any(
                    sr.get(f"{s}_only") is not None for s in SECTION_NAMES
                )
                assert has_result, (
                    f"No section-isolated results for {m['operator']} "
                    f"mutant {m['id']}"
                )


class TestCoverageAnalysis:
    """Verify coverage analysis classifies field coverage correctly."""

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_coverage_analysis_exists(self, scenario, reports):
        report = reports[scenario]
        assert "coverage_analysis" in report
        ca = report["coverage_analysis"]
        assert isinstance(ca, dict) and len(ca) > 0, (
            f"Empty coverage_analysis for {scenario}"
        )

    def test_coverage_analysis_structure(self, reports):
        report = reports["vpc_network"]
        ca = report["coverage_analysis"]
        for addr, analysis in ca.items():
            assert isinstance(addr, str)
            assert "covered_fields" in analysis
            assert "uncovered_fields" in analysis
            assert isinstance(analysis["covered_fields"], list)
            assert isinstance(analysis["uncovered_fields"], list)

    def test_vpc_cidr_block_covered(self, reports):
        """cidr_block must be covered for aws_vpc.main."""
        ca = reports["vpc_network"]["coverage_analysis"]
        assert "aws_vpc.main" in ca
        assert "cidr_block" in ca["aws_vpc.main"]["covered_fields"], (
            "cidr_block should be covered for aws_vpc.main"
        )

    def test_has_uncovered_fields(self, reports):
        """Real policies rarely cover all fields; some must be uncovered."""
        ca = reports["vpc_network"]["coverage_analysis"]
        total_uncovered = sum(
            len(a["uncovered_fields"]) for a in ca.values()
        )
        assert total_uncovered > 0, (
            "No uncovered fields found — unlikely for real-world policies"
        )


class TestSectionAnalysis:
    """Verify section-isolation analysis correctly identifies which plan sections
    each policy evaluates per field."""

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_section_analysis_exists(self, scenario, reports):
        report = reports[scenario]
        assert "section_analysis" in report
        sa = report["section_analysis"]
        assert isinstance(sa, dict) and len(sa) > 0, (
            f"Empty section_analysis for {scenario}"
        )

    def test_section_analysis_structure(self, reports):
        report = reports["vpc_network"]
        sa = report["section_analysis"]
        for addr, fields in sa.items():
            assert isinstance(fields, dict) and len(fields) > 0, (
                f"No fields in section_analysis for {addr}"
            )
            for field, data in fields.items():
                assert "detected_in_sections" in data, (
                    f"Missing detected_in_sections for {addr}.{field}"
                )
                assert "undetected_in_sections" in data, (
                    f"Missing undetected_in_sections for {addr}.{field}"
                )
                assert isinstance(data["detected_in_sections"], list)
                assert isinstance(data["undetected_in_sections"], list)
                for s in data["detected_in_sections"] + data["undetected_in_sections"]:
                    assert s in SECTION_NAMES, (
                        f"Invalid section name '{s}' in {addr}.{field}"
                    )

    def test_vpc_cidr_detected_in_configuration(self, reports):
        """VPC policy checks input.configuration for cidr_block —
        mutating cidr_block in configuration_only must be detected."""
        sa = reports["vpc_network"]["section_analysis"]
        assert "aws_vpc.main" in sa, "aws_vpc.main missing from section_analysis"
        assert "cidr_block" in sa["aws_vpc.main"], (
            "cidr_block missing from aws_vpc.main section_analysis"
        )
        cidr_info = sa["aws_vpc.main"]["cidr_block"]
        assert "configuration" in cidr_info["detected_in_sections"], (
            "VPC cidr_block should be detected in configuration section "
            "(policy evaluates input.configuration for VPC resources)"
        )

    def test_vpc_cidr_not_detected_in_other_sections(self, reports):
        """VPC policy does NOT check planned_values or resource_changes for cidr_block."""
        sa = reports["vpc_network"]["section_analysis"]
        cidr_info = sa["aws_vpc.main"]["cidr_block"]
        assert "planned_values" in cidr_info["undetected_in_sections"], (
            "VPC cidr_block should NOT be detected in planned_values "
            "(policy only evaluates input.configuration for VPC)"
        )
        assert "resource_changes" in cidr_info["undetected_in_sections"], (
            "VPC cidr_block should NOT be detected in resource_changes"
        )

    def test_sg_name_detected_in_resource_changes(self, reports):
        """SG policy checks input.resource_changes for name —
        mutating name in resource_changes_only must be detected."""
        sa = reports["vpc_network"]["section_analysis"]
        assert "aws_security_group.web" in sa, (
            "aws_security_group.web missing from section_analysis"
        )
        assert "name" in sa["aws_security_group.web"], (
            "name missing from aws_security_group.web section_analysis"
        )
        name_info = sa["aws_security_group.web"]["name"]
        assert "resource_changes" in name_info["detected_in_sections"], (
            "SG name should be detected in resource_changes section "
            "(policy evaluates input.resource_changes for security group)"
        )

    def test_sg_name_not_detected_in_configuration(self, reports):
        """SG policy does NOT check configuration for name."""
        sa = reports["vpc_network"]["section_analysis"]
        name_info = sa["aws_security_group.web"]["name"]
        assert "configuration" in name_info["undetected_in_sections"], (
            "SG name should NOT be detected in configuration "
            "(policy only evaluates input.resource_changes for SG)"
        )

    def test_iam_role_detected_in_resource_changes(self, reports):
        """IAM role policy checks resource_changes for name."""
        sa = reports["iam_permissions"]["section_analysis"]
        assert "aws_iam_role.app_role" in sa
        assert "name" in sa["aws_iam_role.app_role"]
        name_info = sa["aws_iam_role.app_role"]["name"]
        assert "resource_changes" in name_info["detected_in_sections"], (
            "IAM role name should be detected in resource_changes"
        )


class TestCrossSectionGaps:
    """Verify cross-section gap detection identifies fields validated in some
    plan sections but not others."""

    def test_cross_section_gaps_exist(self, reports):
        """At least one cross-section gap should exist across all scenarios."""
        total_gaps = sum(
            len(reports[s]["cross_section_gaps"]) for s in SCENARIOS
        )
        assert total_gaps > 0, (
            "No cross-section gaps found across any scenario — "
            "the provided policies query different sections for different "
            "resources, so gaps must exist"
        )

    def test_gap_structure(self, reports):
        report = reports["vpc_network"]
        gaps = report["cross_section_gaps"]
        assert len(gaps) > 0, "VPC scenario should have cross-section gaps"
        for gap in gaps:
            assert "resource" in gap, "Gap missing 'resource'"
            assert "field" in gap, "Gap missing 'field'"
            assert "validated_in" in gap, "Gap missing 'validated_in'"
            assert "missing_in" in gap, "Gap missing 'missing_in'"
            assert isinstance(gap["validated_in"], list)
            assert isinstance(gap["missing_in"], list)
            assert len(gap["validated_in"]) > 0, (
                "validated_in must not be empty"
            )
            assert len(gap["missing_in"]) > 0, (
                "missing_in must not be empty"
            )
            for s in gap["validated_in"] + gap["missing_in"]:
                assert s in SECTION_NAMES, f"Invalid section name '{s}'"

    def test_vpc_cidr_cross_section_gap(self, reports):
        """cidr_block should have a cross-section gap: validated in configuration,
        missing in planned_values/resource_changes."""
        gaps = reports["vpc_network"]["cross_section_gaps"]
        cidr_gaps = [
            g for g in gaps
            if g["resource"] == "aws_vpc.main" and g["field"] == "cidr_block"
        ]
        assert len(cidr_gaps) > 0, (
            "Expected cross-section gap for aws_vpc.main cidr_block"
        )
        gap = cidr_gaps[0]
        assert "configuration" in gap["validated_in"], (
            "cidr_block gap should show 'configuration' in validated_in"
        )

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_gaps_per_scenario(self, scenario, reports):
        """Each scenario should have at least one cross-section gap since each
        policy mixes section queries across its rules."""
        gaps = reports[scenario]["cross_section_gaps"]
        assert len(gaps) > 0, (
            f"Expected cross-section gaps for {scenario}"
        )


class TestHigherOrder:
    """Verify higher-order mutation testing results."""

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_higher_order_exists(self, scenario, reports):
        report = reports[scenario]
        assert "higher_order_results" in report
        ho = report["higher_order_results"]
        assert "pairs_tested" in ho
        assert "synergistic_kills" in ho
        assert "pairs" in ho
        assert isinstance(ho["pairs"], list)

    def test_higher_order_numeric_consistency(self, reports):
        report = reports["vpc_network"]
        ho = report["higher_order_results"]
        assert ho["pairs_tested"] == len(ho["pairs"]), (
            "pairs_tested must equal len(pairs)"
        )
        actual_synergistic = sum(1 for p in ho["pairs"] if p["combined_killed"])
        assert ho["synergistic_kills"] == actual_synergistic, (
            "synergistic_kills count mismatch"
        )
        assert ho["synergistic_kills"] <= ho["pairs_tested"]

    def test_higher_order_pair_structure(self, reports):
        report = reports["vpc_network"]
        ho = report["higher_order_results"]
        for pair in ho["pairs"]:
            assert "mutant_a" in pair, "Pair missing 'mutant_a'"
            assert "mutant_b" in pair, "Pair missing 'mutant_b'"
            assert "combined_killed" in pair, "Pair missing 'combined_killed'"
            assert isinstance(pair["combined_killed"], bool)
            assert pair["mutant_a"] != pair["mutant_b"], (
                "Pair must reference distinct mutants"
            )

    def test_higher_order_pairs_tested(self, reports):
        """Surviving same-resource mutants exist, so at least one pair should be tested."""
        report = reports["vpc_network"]
        ho = report["higher_order_results"]
        assert ho["pairs_tested"] > 0, (
            "Expected at least one higher-order pair — "
            "surviving mutants exist on the same resource"
        )


class TestManualVerification:
    """Cross-check tool results with independent OPA evaluation."""

    def test_cidr_mutation_fails_policy(self):
        """A manually mutated VPC cidr_block must fail the policy."""
        plan_path = "/app/scenarios/vpc_network/plan.json"
        policy_path = "/app/scenarios/vpc_network/policy.rego"

        with open(plan_path) as f:
            plan = json.load(f)

        mutant = copy.deepcopy(plan)
        for r in mutant["configuration"]["root_module"]["resources"]:
            if r["type"] == "aws_vpc":
                r["expressions"]["cidr_block"]["constant_value"] = (
                    "192.168.0.0/16"
                )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(mutant, f)
            temp_path = f.name

        try:
            passes = run_opa(temp_path, policy_path)
            assert not passes, (
                "Mutated plan with wrong cidr_block should fail the policy"
            )
        finally:
            os.unlink(temp_path)

    def test_zone_name_mutation_fails_policy(self):
        """A mutated Route53 zone name must fail the policy."""
        plan_path = "/app/scenarios/dns_loadbalancer/plan.json"
        policy_path = "/app/scenarios/dns_loadbalancer/policy.rego"

        with open(plan_path) as f:
            plan = json.load(f)

        mutant = copy.deepcopy(plan)
        for r in mutant["configuration"]["root_module"]["resources"]:
            if r["type"] == "aws_route53_zone":
                r["expressions"]["name"]["constant_value"] = "wrong.com"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(mutant, f)
            temp_path = f.name

        try:
            passes = run_opa(temp_path, policy_path)
            assert not passes, (
                "Mutated plan with wrong zone name should fail the policy"
            )
        finally:
            os.unlink(temp_path)

    def test_section_isolated_cidr_configuration_only(self):
        """Mutating cidr_block only in configuration must fail the VPC policy
        (policy evaluates input.configuration)."""
        plan_path = "/app/scenarios/vpc_network/plan.json"
        policy_path = "/app/scenarios/vpc_network/policy.rego"

        with open(plan_path) as f:
            plan = json.load(f)

        mutant = copy.deepcopy(plan)
        for r in mutant["configuration"]["root_module"]["resources"]:
            if r["type"] == "aws_vpc":
                r["expressions"]["cidr_block"]["constant_value"] = "192.168.0.0/16"
        # planned_values and resource_changes left unchanged

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(mutant, f)
            temp_path = f.name

        try:
            passes = run_opa(temp_path, policy_path)
            assert not passes, (
                "Mutating cidr_block only in configuration should fail "
                "(VPC policy evaluates input.configuration)"
            )
        finally:
            os.unlink(temp_path)

    def test_section_isolated_cidr_resource_changes_only(self):
        """Mutating cidr_block only in resource_changes must NOT fail the VPC policy
        (policy does not evaluate resource_changes for VPC resources)."""
        plan_path = "/app/scenarios/vpc_network/plan.json"
        policy_path = "/app/scenarios/vpc_network/policy.rego"

        with open(plan_path) as f:
            plan = json.load(f)

        mutant = copy.deepcopy(plan)
        for rc in mutant["resource_changes"]:
            if rc["type"] == "aws_vpc":
                rc["change"]["after"]["cidr_block"] = "192.168.0.0/16"
        # configuration and planned_values left unchanged

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(mutant, f)
            temp_path = f.name

        try:
            passes = run_opa(temp_path, policy_path)
            assert passes, (
                "Mutating cidr_block only in resource_changes should PASS "
                "(VPC policy does not check resource_changes for VPC)"
            )
        finally:
            os.unlink(temp_path)
