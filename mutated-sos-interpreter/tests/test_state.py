
import json
import os
import subprocess
import pytest


# ---- Ground truth: mutated semantics ----
# Derived by hand-tracing under the nonstandard SOS rules where:
#   syntax +  computes subtraction    syntax -  computes addition
#   syntax *  computes division       syntax /  computes multiplication
#   syntax <  checks >                syntax >  checks <
#   syntax <= checks >=               syntax >= checks <=
#   syntax == checks !=               syntax != checks ==
#   syntax && computes ||             syntax || computes &&
#   unary +  negates                  unary -  is identity

EXPECTED_RESULTS = {
    "arithmetic": {"a": 120, "b": 8, "c": 112, "d": 15, "e": 127},
    "branches": {"x": 5, "y": 10, "r": 0, "s": 0},
    "loop": {"i": 5, "s": 40},
    "combined": {"a": 15, "b": 4, "c": 60, "result": 60},
    "search": {"i": 14, "found": 14},
    "continue_filter": {"n": 12, "sum": 47, "i": 1},
    "nested": {"outer": 1, "inner": 1, "acc": 120},
    "modular": {"a": 37, "b": 5, "r": 2},
}

# ---- Ground truth: standard semantics ----
# Every operator computes its conventional meaning.

STANDARD_RESULTS = {
    "arithmetic": {"a": 120, "b": 8, "c": 128, "d": 960, "e": -832},
    "branches": {"x": 5, "y": 10, "r": 1, "s": 1},
    "loop": {"i": 10, "s": 0},
    "combined": {"a": 15, "b": 4, "c": 3, "result": 3},
    "search": {"i": 20, "found": 0},
    "continue_filter": {"n": 12, "sum": 0, "i": 12},
    "nested": {"outer": 6, "inner": 0, "acc": 0},
    "modular": {"a": 37, "b": 5, "r": 2},
}

EXPECTED_MUTATIONS = {
    "arithmetic": {"+": "-", "-": "+", "*": "/", "/": "*", "%": "%"},
    "comparison": {
        "<": ">", "<=": ">=", ">": "<", ">=": "<=",
        "==": "!=", "!=": "==",
    },
    "logical": {"&&": "||", "||": "&&"},
    "unary": {"+": "negate", "-": "identity"},
}

# Which mutation categories have at least one mutated operator appearing
# in the program text, for programs that differ between the two semantics.
EXPECTED_AFFECTED = {
    "arithmetic": ["arithmetic"],
    "branches": ["comparison"],
    "loop": ["arithmetic", "comparison"],
    "combined": ["arithmetic", "comparison", "logical"],
    "search": ["arithmetic", "comparison"],
    "continue_filter": ["arithmetic", "comparison"],
    "nested": ["arithmetic", "comparison"],
    "modular": [],
}


# ---- PLY Artifact Tests ----

class TestPLYArtifacts:
    """Verify that PLY was used for parser generation."""

    def test_parsetab_exists(self):
        assert os.path.isfile("/app/parsetab.py"), \
            "PLY parser table file /app/parsetab.py not found"

    def test_ply_import_in_source(self):
        found_ply = False
        for fname in os.listdir("/app"):
            if fname.endswith(".py"):
                fpath = os.path.join("/app", fname)
                with open(fpath) as f:
                    content = f.read()
                if "import ply" in content or "from ply" in content:
                    found_ply = True
                    break
        assert found_ply, "No Python file in /app/ imports the PLY library"


# ---- Makefile Tests ----

class TestMakefile:
    """Verify Makefile exists and has required targets."""

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), \
            "Makefile not found at /app/Makefile"

    @pytest.mark.parametrize("target", [
        "all", "parse-tables", "analyze",
        "run-mutated", "run-standard", "diverge",
    ])
    def test_makefile_has_target(self, target):
        result = subprocess.run(
            ["make", "-n", target], cwd="/app",
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, \
            f"'make -n {target}' failed: {result.stderr}"


# ---- Mutation Analysis Tests ----

class TestMutationAnalysis:
    """Verify the semantic mutation analysis output."""

    def test_mutations_file_exists(self):
        assert os.path.isfile("/app/analysis/mutations.json"), \
            "Mutation analysis file not found"

    @pytest.mark.parametrize("category", sorted(EXPECTED_MUTATIONS.keys()))
    def test_mutation_category_present(self, category):
        with open("/app/analysis/mutations.json") as f:
            data = json.load(f)
        assert category in data, \
            f"Missing mutation category '{category}'"

    @pytest.mark.parametrize("category", sorted(EXPECTED_MUTATIONS.keys()))
    def test_mutation_mappings_correct(self, category):
        with open("/app/analysis/mutations.json") as f:
            data = json.load(f)
        expected = EXPECTED_MUTATIONS[category]
        actual = data.get(category, {})
        for op, expected_actual in expected.items():
            assert op in actual, \
                f"Missing operator '{op}' in {category} mutations"
            assert actual[op] == expected_actual, (
                f"{category} operator '{op}': got '{actual[op]}', "
                f"expected '{expected_actual}'"
            )


# ---- Mutated Program Result Tests ----

@pytest.mark.parametrize("program_name", sorted(EXPECTED_RESULTS.keys()))
class TestMutatedResults:
    """Verify interpreter output under mutated semantics."""

    def test_result_file_exists(self, program_name):
        path = f"/app/results/{program_name}.json"
        assert os.path.isfile(path), f"Missing result file: {path}"

    def test_result_values_correct(self, program_name):
        path = f"/app/results/{program_name}.json"
        with open(path) as f:
            result = json.load(f)
        expected = EXPECTED_RESULTS[program_name]
        for var, val in expected.items():
            assert var in result, (
                f"{program_name}: missing variable '{var}'. "
                f"Got keys: {sorted(result.keys())}"
            )
            assert result[var] == val, (
                f"{program_name}: variable '{var}' = {result[var]}, "
                f"expected {val}"
            )
        assert set(result.keys()) == set(expected.keys()), (
            f"{program_name}: unexpected variables. "
            f"Got {sorted(result.keys())}, expected {sorted(expected.keys())}"
        )


# ---- Standard Program Result Tests ----

@pytest.mark.parametrize("program_name", sorted(STANDARD_RESULTS.keys()))
class TestStandardResults:
    """Verify interpreter output under standard semantics."""

    def test_standard_result_file_exists(self, program_name):
        path = f"/app/results_standard/{program_name}.json"
        assert os.path.isfile(path), f"Missing standard result: {path}"

    def test_standard_result_values_correct(self, program_name):
        path = f"/app/results_standard/{program_name}.json"
        with open(path) as f:
            result = json.load(f)
        expected = STANDARD_RESULTS[program_name]
        for var, val in expected.items():
            assert var in result, (
                f"{program_name} (standard): missing variable '{var}'. "
                f"Got keys: {sorted(result.keys())}"
            )
            assert result[var] == val, (
                f"{program_name} (standard): variable '{var}' = {result[var]}, "
                f"expected {val}"
            )
        assert set(result.keys()) == set(expected.keys()), (
            f"{program_name} (standard): unexpected variables. "
            f"Got {sorted(result.keys())}, expected {sorted(expected.keys())}"
        )


# ---- Divergence Analysis Tests ----

class TestDivergenceAnalysis:
    """Verify the semantic divergence analysis."""

    def test_divergence_file_exists(self):
        assert os.path.isfile("/app/analysis/divergence.json"), \
            "Divergence analysis file not found"

    def test_divergence_is_valid_json(self):
        with open("/app/analysis/divergence.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    @pytest.mark.parametrize("program_name", sorted(EXPECTED_RESULTS.keys()))
    def test_divergence_entry_present(self, program_name):
        with open("/app/analysis/divergence.json") as f:
            data = json.load(f)
        assert program_name in data, \
            f"Missing divergence entry for '{program_name}'"

    @pytest.mark.parametrize("program_name", sorted(EXPECTED_RESULTS.keys()))
    def test_divergence_differs_correct(self, program_name):
        with open("/app/analysis/divergence.json") as f:
            data = json.load(f)
        entry = data[program_name]
        expected_differs = (
            EXPECTED_RESULTS[program_name] != STANDARD_RESULTS[program_name]
        )
        assert entry["differs"] == expected_differs, (
            f"{program_name}: differs={entry['differs']}, "
            f"expected {expected_differs}"
        )

    @pytest.mark.parametrize("program_name", sorted(EXPECTED_RESULTS.keys()))
    def test_divergence_mutated_state(self, program_name):
        with open("/app/analysis/divergence.json") as f:
            data = json.load(f)
        entry = data[program_name]
        expected = EXPECTED_RESULTS[program_name]
        actual = entry["mutated_state"]
        for var, val in expected.items():
            assert actual.get(var) == val, (
                f"{program_name} divergence mutated_state: "
                f"'{var}'={actual.get(var)}, expected {val}"
            )

    @pytest.mark.parametrize("program_name", sorted(EXPECTED_RESULTS.keys()))
    def test_divergence_standard_state(self, program_name):
        with open("/app/analysis/divergence.json") as f:
            data = json.load(f)
        entry = data[program_name]
        expected = STANDARD_RESULTS[program_name]
        actual = entry["standard_state"]
        for var, val in expected.items():
            assert actual.get(var) == val, (
                f"{program_name} divergence standard_state: "
                f"'{var}'={actual.get(var)}, expected {val}"
            )

    @pytest.mark.parametrize("program_name", sorted(EXPECTED_AFFECTED.keys()))
    def test_divergence_affected_categories(self, program_name):
        with open("/app/analysis/divergence.json") as f:
            data = json.load(f)
        entry = data[program_name]
        expected = EXPECTED_AFFECTED[program_name]
        actual = sorted(entry.get("affected_categories", []))
        assert actual == expected, (
            f"{program_name}: affected_categories={actual}, "
            f"expected {expected}"
        )


# ---- Verification Program Tests ----

class TestVerificationProgram:
    """Verify the synthesized verification.imp program."""

    def test_verification_source_exists(self):
        assert os.path.isfile("/app/programs/verification.imp"), \
            "verification.imp not found in /app/programs/"

    def test_verification_mutated_result_exists(self):
        assert os.path.isfile("/app/results/verification.json"), \
            "Mutated result for verification.imp not found"

    def test_verification_standard_result_exists(self):
        assert os.path.isfile("/app/results_standard/verification.json"), \
            "Standard result for verification.imp not found"

    def test_verification_mutated_check_is_1(self):
        with open("/app/results/verification.json") as f:
            data = json.load(f)
        assert data.get("check") == 1, (
            f"verification.imp under mutated semantics: "
            f"check={data.get('check')}, expected 1"
        )

    def test_verification_standard_check_is_0(self):
        with open("/app/results_standard/verification.json") as f:
            data = json.load(f)
        assert data.get("check") == 0, (
            f"verification.imp under standard semantics: "
            f"check={data.get('check')}, expected 0"
        )

    def test_verification_in_divergence(self):
        with open("/app/analysis/divergence.json") as f:
            data = json.load(f)
        assert "verification" in data, \
            "verification program missing from divergence.json"
        assert data["verification"]["differs"] is True, \
            "verification program should differ between semantics"
