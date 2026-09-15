"""
Tests for the ChocoPy type checker pipeline.

"""

import sys
import os
import json
import subprocess
import pytest

sys.path.insert(0, "/app")

from typechecker import type_check


def _read_program(name: str) -> str:
    path = os.path.join("/app/programs", name)
    with open(path, "r") as f:
        return f.read()


# ============================================================
# Valid programs — type checker must accept these
# ============================================================


class TestValidPrograms:
    def test_basic_types(self):
        result = type_check(_read_program("basic_types.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_list_ops(self):
        result = type_check(_read_program("list_ops.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_class_basic(self):
        result = type_check(_read_program("class_basic.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_class_inherit(self):
        result = type_check(_read_program("class_inherit.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_nested_func(self):
        result = type_check(_read_program("nested_func.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_global_decl(self):
        result = type_check(_read_program("global_decl.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_cond_expr_join(self):
        result = type_check(_read_program("cond_expr_join.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_none_assign(self):
        result = type_check(_read_program("none_assign.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_empty_list(self):
        result = type_check(_read_program("empty_list.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_for_loops(self):
        result = type_check(_read_program("for_loops.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_list_display_join(self):
        result = type_check(_read_program("list_display_join.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"

    def test_multi_scope(self):
        result = type_check(_read_program("multi_scope.py"))
        assert result["well_typed"], f"Expected well-typed: {result.get('errors')}"


# ============================================================
# Invalid programs — type checker must reject these
# ============================================================


class TestInvalidPrograms:
    def test_type_mismatch(self):
        """int + str is not allowed"""
        result = type_check(_read_program("err_type_mismatch.py"))
        assert not result["well_typed"], "Expected type error for int + str"
        assert len(result["errors"]) > 0

    def test_override_ret(self):
        """Overriding method with different return type"""
        result = type_check(_read_program("err_override_ret.py"))
        assert not result["well_typed"], "Expected type error for wrong override return type"

    def test_none_to_int(self):
        """Cannot assign None to int variable"""
        result = type_check(_read_program("err_none_to_int.py"))
        assert not result["well_typed"], "Expected type error for None -> int"

    def test_inherit_int(self):
        """Cannot inherit from int"""
        result = type_check(_read_program("err_inherit_int.py"))
        assert not result["well_typed"], "Expected type error for inheriting from int"

    def test_arg_count(self):
        """Wrong number of arguments"""
        result = type_check(_read_program("err_arg_count.py"))
        assert not result["well_typed"], "Expected type error for wrong arg count"

    def test_for_type(self):
        """For loop variable type incompatible with list element type"""
        result = type_check(_read_program("err_for_type.py"))
        assert not result["well_typed"], "Expected type error for for loop type mismatch"

    def test_is_int(self):
        """Cannot use 'is' with int operands"""
        result = type_check(_read_program("err_is_int.py"))
        assert not result["well_typed"], "Expected type error for 'is' with int"

    def test_override_param(self):
        """Overriding method with different parameter type"""
        result = type_check(_read_program("err_override_param.py"))
        assert not result["well_typed"], "Expected type error for wrong override param type"


# ============================================================
# Specific type rule tests (using inline programs)
# ============================================================


class TestSpecificRules:
    def test_none_assignable_to_object(self):
        src = 'x: object = None\n'
        result = type_check(src)
        assert result["well_typed"], f"None should be assignable to object: {result.get('errors')}"

    def test_none_not_assignable_to_bool(self):
        src = 'x: bool = True\nx = None\n'
        result = type_check(src)
        assert not result["well_typed"], "None should not be assignable to bool"

    def test_none_not_assignable_to_str(self):
        src = 'x: str = ""\nx = None\n'
        result = type_check(src)
        assert not result["well_typed"], "None should not be assignable to str"

    def test_empty_list_to_any_list_type(self):
        src = 'x: [int] = []\ny: [str] = []\n'
        result = type_check(src)
        assert result["well_typed"], f"Empty list should be assignable to any list type: {result.get('errors')}"

    def test_subclass_assignable_to_superclass(self):
        src = (
            'class A(object):\n'
            '    pass\n'
            'class B(A):\n'
            '    pass\n'
            'x: A = None\n'
            'x = B()\n'
        )
        result = type_check(src)
        assert result["well_typed"], f"Subclass should be assignable to superclass: {result.get('errors')}"

    def test_superclass_not_assignable_to_subclass(self):
        src = (
            'class A(object):\n'
            '    pass\n'
            'class B(A):\n'
            '    pass\n'
            'x: B = None\n'
            'x = A()\n'
        )
        result = type_check(src)
        assert not result["well_typed"], "Superclass should not be assignable to subclass"

    def test_join_sibling_classes(self):
        """Join of two sibling classes should be their common ancestor."""
        src = (
            'class A(object):\n'
            '    pass\n'
            'class B(A):\n'
            '    pass\n'
            'class C(A):\n'
            '    pass\n'
            'x: A = None\n'
            'x = B() if True else C()\n'
        )
        result = type_check(src)
        assert result["well_typed"], f"Join of siblings should be their common parent: {result.get('errors')}"

    def test_join_fails_with_wrong_target(self):
        """Join of B and C is A, which is not assignable to B."""
        src = (
            'class A(object):\n'
            '    pass\n'
            'class B(A):\n'
            '    pass\n'
            'class C(A):\n'
            '    pass\n'
            'x: B = None\n'
            'x = B() if True else C()\n'
        )
        result = type_check(src)
        assert not result["well_typed"], "Join(B,C)=A is not assignable to B"

    def test_list_display_heterogeneous(self):
        """List display with mixed subclass elements should have LUB element type."""
        src = (
            'class A(object):\n'
            '    pass\n'
            'class B(A):\n'
            '    pass\n'
            'class C(A):\n'
            '    pass\n'
            'items: [A] = None\n'
            'items = [B(), C()]\n'
        )
        result = type_check(src)
        assert result["well_typed"], f"List with mixed subtypes should be valid: {result.get('errors')}"

    def test_method_override_valid(self):
        """Valid method override: same signature except self type."""
        src = (
            'class A(object):\n'
            '    def foo(self: "A", x: int) -> str:\n'
            '        return "a"\n'
            'class B(A):\n'
            '    def foo(self: "B", x: int) -> str:\n'
            '        return "b"\n'
        )
        result = type_check(src)
        assert result["well_typed"], f"Valid override should be accepted: {result.get('errors')}"

    def test_attribute_no_redefinition(self):
        """Attributes cannot be redefined in subclasses."""
        src = (
            'class A(object):\n'
            '    x: int = 0\n'
            'class B(A):\n'
            '    x: int = 1\n'
        )
        result = type_check(src)
        assert not result["well_typed"], "Attribute redefinition should be rejected"

    def test_int_not_subclass_of_bool(self):
        """int is not a subclass of bool in ChocoPy."""
        src = 'x: bool = True\nx = 1\n'
        result = type_check(src)
        assert not result["well_typed"], "int should not be assignable to bool"

    def test_bool_not_subclass_of_int(self):
        """bool is not a subclass of int in ChocoPy."""
        src = 'x: int = 0\nx = True\n'
        result = type_check(src)
        assert not result["well_typed"], "bool should not be assignable to int"


# ============================================================
# JSON output format tests
# ============================================================


class TestJSONOutput:
    def test_output_has_required_keys(self):
        result = type_check(_read_program("basic_types.py"))
        for key in ["well_typed", "globals", "classes", "errors"]:
            assert key in result, f"Missing key '{key}'"

    def test_globals_structure(self):
        result = type_check(_read_program("basic_types.py"))
        assert isinstance(result["globals"], dict)
        assert "x" in result["globals"]
        assert result["globals"]["x"]["type"] == "int"
        assert result["globals"]["x"]["kind"] == "var"

    def test_class_structure(self):
        result = type_check(_read_program("class_basic.py"))
        assert "Counter" in result["classes"]
        c = result["classes"]["Counter"]
        assert c["superclass"] == "object"
        assert "count" in c["attributes"]
        assert c["attributes"]["count"] == "int"
        assert "get" in c["methods"]

    def test_function_in_globals(self):
        result = type_check(_read_program("global_decl.py"))
        assert "bump" in result["globals"]
        assert result["globals"]["bump"]["kind"] == "func"
        assert result["globals"]["bump"]["type"] == "() -> object"

    def test_method_signature_format(self):
        result = type_check(_read_program("class_basic.py"))
        c = result["classes"]["Counter"]
        assert c["methods"]["get"] == "(Counter) -> int"
        assert c["methods"]["increment"] == "(Counter) -> object"

    def test_inheritance_in_classes(self):
        result = type_check(_read_program("class_inherit.py"))
        assert result["classes"]["Dog"]["superclass"] == "Animal"
        assert result["classes"]["Cat"]["superclass"] == "Animal"
        assert result["classes"]["Animal"]["superclass"] == "object"

    def test_no_builtin_classes_in_output(self):
        result = type_check(_read_program("basic_types.py"))
        for name in ["object", "int", "bool", "str"]:
            assert name not in result["classes"]

    def test_no_builtin_functions_in_globals(self):
        result = type_check(_read_program("basic_types.py"))
        for name in ["print", "input", "len"]:
            assert name not in result["globals"]

    def test_error_program_has_errors_list(self):
        result = type_check(_read_program("err_type_mismatch.py"))
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) > 0
        assert "message" in result["errors"][0]

    def test_list_type_format(self):
        result = type_check(_read_program("empty_list.py"))
        assert result["globals"]["x"]["type"] == "[int]"
        assert result["globals"]["y"]["type"] == "[bool]"
        assert result["globals"]["z"]["type"] == "[str]"

    def test_class_type_in_globals(self):
        result = type_check(_read_program("none_assign.py"))
        assert result["globals"]["a"]["type"] == "Foo"
        assert result["globals"]["d"]["type"] == "[Foo]"


# ============================================================
# CLI tool tests
# ============================================================


class TestCLI:
    def test_cli_exists(self):
        assert os.path.exists("/app/chocopy_tc"), "CLI tool not found at /app/chocopy_tc"

    def test_cli_help(self):
        result = subprocess.run(
            ["python3", "/app/chocopy_tc", "--help"],
            capture_output=True, text=True)
        assert result.returncode == 0

    def test_cli_valid_program_exit_0(self):
        result = subprocess.run(
            ["python3", "/app/chocopy_tc", "/app/programs/basic_types.py"],
            capture_output=True, text=True)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["well_typed"] is True

    def test_cli_invalid_program_exit_1(self):
        result = subprocess.run(
            ["python3", "/app/chocopy_tc", "/app/programs/err_type_mismatch.py"],
            capture_output=True, text=True)
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["well_typed"] is False

    def test_cli_pretty_flag(self):
        result = subprocess.run(
            ["python3", "/app/chocopy_tc", "/app/programs/basic_types.py", "--pretty"],
            capture_output=True, text=True)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["well_typed"] is True
        # Pretty output should have newlines (indented formatting)
        assert "\n" in result.stdout.strip()

    def test_cli_outputs_valid_json(self):
        for prog in ["basic_types.py", "class_inherit.py", "err_type_mismatch.py"]:
            result = subprocess.run(
                ["python3", "/app/chocopy_tc", f"/app/programs/{prog}"],
                capture_output=True, text=True)
            data = json.loads(result.stdout)
            for key in ["well_typed", "globals", "classes", "errors"]:
                assert key in data, f"Missing key '{key}' in output for {prog}"


# ============================================================
# Makefile tests
# ============================================================


class TestMakefile:
    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_clean(self):
        result = subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, text=True)
        assert result.returncode == 0

    def test_make_typecheck_all(self):
        subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
        result = subprocess.run(
            ["make", "-C", "/app", "typecheck-all"],
            capture_output=True, text=True)
        assert result.returncode == 0, f"make typecheck-all failed:\n{result.stderr}"
        assert os.path.isdir("/app/build")
        json_files = [f for f in os.listdir("/app/build") if f.endswith(".json")]
        assert len(json_files) >= 20, f"Expected >= 20 JSON files, got {len(json_files)}"

    def test_make_validate(self):
        subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
        subprocess.run(["make", "-C", "/app", "typecheck-all"], capture_output=True)
        result = subprocess.run(
            ["make", "-C", "/app", "validate"],
            capture_output=True, text=True)
        assert result.returncode == 0, f"make validate failed:\n{result.stdout}\n{result.stderr}"

    def test_make_diff_check(self):
        subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
        subprocess.run(["make", "-C", "/app", "typecheck-all"], capture_output=True)
        result = subprocess.run(
            ["make", "-C", "/app", "diff-check"],
            capture_output=True, text=True)
        assert result.returncode == 0, f"make diff-check failed:\n{result.stdout}\n{result.stderr}"


# ============================================================
# jq validation tests
# ============================================================


class TestJQValidation:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp = tmp_path

    def _tc_to_file(self, prog, outfile):
        r = subprocess.run(
            ["python3", "/app/chocopy_tc", f"/app/programs/{prog}", "--pretty"],
            capture_output=True, text=True)
        with open(outfile, "w") as f:
            f.write(r.stdout)

    def test_jq_extract_well_typed(self):
        out = self.tmp / "t1.json"
        self._tc_to_file("basic_types.py", str(out))
        r = subprocess.run(["jq", "-r", ".well_typed", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert r.stdout.strip() == "true"

    def test_jq_extract_global_type(self):
        out = self.tmp / "t2.json"
        self._tc_to_file("basic_types.py", str(out))
        r = subprocess.run(["jq", "-r", ".globals.x.type", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert r.stdout.strip() == "int"

    def test_jq_extract_class_superclass(self):
        out = self.tmp / "t3.json"
        self._tc_to_file("class_inherit.py", str(out))
        r = subprocess.run(["jq", "-r", ".classes.Dog.superclass", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert r.stdout.strip() == "Animal"

    def test_jq_count_errors(self):
        out = self.tmp / "t4.json"
        self._tc_to_file("err_type_mismatch.py", str(out))
        r = subprocess.run(["jq", ".errors | length", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert int(r.stdout.strip()) > 0

    def test_jq_schema_check(self):
        """Use jq to validate the JSON has the expected schema."""
        out = self.tmp / "t5.json"
        self._tc_to_file("class_basic.py", str(out))
        r = subprocess.run(
            ["jq", "-e",
             'has("well_typed") and has("globals") and has("classes") and has("errors") '
             'and (.globals | type) == "object" and (.classes | type) == "object" '
             'and (.errors | type) == "array"',
             str(out)],
            capture_output=True, text=True)
        assert r.returncode == 0

    def test_jq_method_query(self):
        out = self.tmp / "t6.json"
        self._tc_to_file("class_basic.py", str(out))
        r = subprocess.run(
            ["jq", "-r", ".classes.Counter.methods.get", str(out)],
            capture_output=True, text=True)
        assert r.returncode == 0
        assert r.stdout.strip() == "(Counter) -> int"

    def test_jq_diff_reference(self):
        """Verify jq -S normalization allows comparison with diff."""
        out = self.tmp / "t7.json"
        self._tc_to_file("global_decl.py", str(out))
        ref = "/app/reference_asts/global_decl.json"
        assert os.path.exists(ref), "Reference AST not found"
        r = subprocess.run(
            ["bash", "-c", f'diff <(jq -S . "{out}") <(jq -S . "{ref}")'],
            capture_output=True, text=True)
        assert r.returncode == 0, f"JSON diff failed:\n{r.stdout}"
