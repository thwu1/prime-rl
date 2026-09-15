"""
Tests for SPIR-V Binary Dead Code Analyzer.

"""

import json
import os
import sys

sys.path.insert(0, "/app")

MODULES_DIR = "/app/modules"

# Expected results for each module
EXPECTED = {
    "simple.spv": {"dead_instruction_count": 0, "dead_function_count": 0},
    "dead_computation.spv": {"dead_instruction_count": 3, "dead_function_count": 0},
    "dead_function.spv": {"dead_instruction_count": 0, "dead_function_count": 1},
    "complex_dead.spv": {"dead_instruction_count": 4, "dead_function_count": 1},
}


class TestParserExists:
    def test_parser_file_exists(self):
        assert os.path.isfile("/app/spirv_parser.py"), "spirv_parser.py not found at /app/"

    def test_analyzer_file_exists(self):
        assert os.path.isfile(
            "/app/dead_code_analyzer.py"
        ), "dead_code_analyzer.py not found at /app/"


class TestParserNoSubprocess:
    """Verify the parser reads binary directly without shelling out."""

    def test_no_subprocess_in_parser(self):
        with open("/app/spirv_parser.py") as f:
            source = f.read()
        assert "subprocess" not in source, "Parser must not use subprocess module"
        assert "os.system" not in source, "Parser must not use os.system"
        assert "os.popen" not in source, "Parser must not use os.popen"


class TestParserCorrectness:
    def test_parse_simple_header(self):
        import spirv_parser

        result = spirv_parser.parse_module(os.path.join(MODULES_DIR, "simple.spv"))
        header = result["header"]
        assert header["magic"] == 0x07230203, f"Wrong magic: {hex(header['magic'])}"
        assert header["version_major"] == 1, f"Wrong major version: {header['version_major']}"
        assert header["version_minor"] >= 0, f"Invalid minor version: {header['version_minor']}"
        assert header["bound"] > 0, f"Invalid bound: {header['bound']}"

    def test_parse_returns_instructions(self):
        import spirv_parser

        result = spirv_parser.parse_module(os.path.join(MODULES_DIR, "simple.spv"))
        instructions = result["instructions"]
        assert len(instructions) > 10, f"Too few instructions: {len(instructions)}"

    def test_instruction_structure(self):
        import spirv_parser

        result = spirv_parser.parse_module(os.path.join(MODULES_DIR, "simple.spv"))
        inst = result["instructions"][0]
        assert "opcode" in inst, "Instruction missing 'opcode' field"
        assert "opname" in inst, "Instruction missing 'opname' field"
        assert "word_count" in inst, "Instruction missing 'word_count' field"
        assert "result_id" in inst, "Instruction missing 'result_id' field"
        assert "result_type" in inst, "Instruction missing 'result_type' field"
        assert "id_refs" in inst, "Instruction missing 'id_refs' field"

    def test_first_instruction_is_capability(self):
        import spirv_parser

        result = spirv_parser.parse_module(os.path.join(MODULES_DIR, "simple.spv"))
        first = result["instructions"][0]
        assert first["opcode"] == 17, f"First instruction should be OpCapability (17), got {first['opcode']}"
        assert "Capability" in first["opname"], f"First opname should contain 'Capability', got {first['opname']}"

    def test_parse_all_modules(self):
        """All four modules must parse without error."""
        import spirv_parser

        for name in EXPECTED:
            path = os.path.join(MODULES_DIR, name)
            result = spirv_parser.parse_module(path)
            assert result["header"]["magic"] == 0x07230203, f"Failed to parse {name}"
            assert len(result["instructions"]) > 0, f"No instructions in {name}"

    def test_result_ids_within_bound(self):
        import spirv_parser

        result = spirv_parser.parse_module(os.path.join(MODULES_DIR, "simple.spv"))
        bound = result["header"]["bound"]
        for inst in result["instructions"]:
            if inst["result_id"] is not None:
                assert inst["result_id"] < bound, (
                    f"Result ID {inst['result_id']} >= bound {bound} "
                    f"in {inst['opname']}"
                )


class TestDeadCodeAnalysis:
    def _analyze(self, module_name):
        import dead_code_analyzer

        return dead_code_analyzer.analyze(os.path.join(MODULES_DIR, module_name))

    def test_simple_no_dead_instructions(self):
        result = self._analyze("simple.spv")
        assert result["dead_instruction_count"] == 0, (
            f"simple.spv should have 0 dead instructions, got {result['dead_instruction_count']}"
        )

    def test_simple_no_dead_functions(self):
        result = self._analyze("simple.spv")
        assert result["dead_function_count"] == 0, (
            f"simple.spv should have 0 dead functions, got {result['dead_function_count']}"
        )

    def test_dead_computation_count(self):
        result = self._analyze("dead_computation.spv")
        assert result["dead_instruction_count"] == 3, (
            f"dead_computation.spv should have 3 dead instructions (iterative), "
            f"got {result['dead_instruction_count']}"
        )

    def test_dead_computation_no_dead_functions(self):
        result = self._analyze("dead_computation.spv")
        assert result["dead_function_count"] == 0, (
            f"dead_computation.spv should have 0 dead functions, got {result['dead_function_count']}"
        )

    def test_dead_function_no_dead_instructions(self):
        result = self._analyze("dead_function.spv")
        assert result["dead_instruction_count"] == 0, (
            f"dead_function.spv should have 0 dead instructions, got {result['dead_instruction_count']}"
        )

    def test_dead_function_count(self):
        result = self._analyze("dead_function.spv")
        assert result["dead_function_count"] == 1, (
            f"dead_function.spv should have 1 dead function, got {result['dead_function_count']}"
        )

    def test_complex_dead_instructions(self):
        result = self._analyze("complex_dead.spv")
        assert result["dead_instruction_count"] == 4, (
            f"complex_dead.spv should have 4 dead instructions (iterative), "
            f"got {result['dead_instruction_count']}"
        )

    def test_complex_dead_functions(self):
        result = self._analyze("complex_dead.spv")
        assert result["dead_function_count"] == 1, (
            f"complex_dead.spv should have 1 dead function, got {result['dead_function_count']}"
        )


class TestAnalysisResultsJSON:
    def test_json_exists(self):
        assert os.path.isfile("/app/analysis_results.json"), (
            "analysis_results.json not found at /app/"
        )

    def test_json_structure(self):
        with open("/app/analysis_results.json") as f:
            data = json.load(f)
        for module_name in EXPECTED:
            assert module_name in data, f"Missing module {module_name} in results"
            entry = data[module_name]
            assert "dead_instruction_count" in entry, (
                f"Missing dead_instruction_count for {module_name}"
            )
            assert "dead_function_count" in entry, (
                f"Missing dead_function_count for {module_name}"
            )

    def test_json_values(self):
        with open("/app/analysis_results.json") as f:
            data = json.load(f)
        for module_name, expected in EXPECTED.items():
            entry = data[module_name]
            assert entry["dead_instruction_count"] == expected["dead_instruction_count"], (
                f"{module_name}: expected {expected['dead_instruction_count']} dead instructions, "
                f"got {entry['dead_instruction_count']}"
            )
            assert entry["dead_function_count"] == expected["dead_function_count"], (
                f"{module_name}: expected {expected['dead_function_count']} dead functions, "
                f"got {entry['dead_function_count']}"
            )
