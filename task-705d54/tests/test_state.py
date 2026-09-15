
import json
import os
import shutil
import sqlite3
import subprocess
import pytest

REQUIRED_VIOLATIONS = {
    ("errors.ExtendsInterface", 1),
    ("errors.ImplementsClass", 2),
    ("errors.DuplicateIface", 3),
    ("errors.InterfaceDupExtends", 3),
    ("errors.ExtendsFinal", 4),
    ("errors.IfaceExtendsClass", 5),
    ("errors.CycleA", 6),
    ("errors.CycleB", 6),
    ("errors.DeepCycleA", 6),
    ("errors.DeepCycleB", 6),
    ("errors.DeepCycleC", 6),
    ("errors.InterfaceCycleX", 6),
    ("errors.InterfaceCycleY", 6),
    ("errors.DuplicateMethod", 7),
    ("errors.InterfaceDupMethod", 7),
    ("errors.DuplicateCtor", 8),
    ("errors.ConflictInherit", 9),
    ("errors.ConcreteAbstract", 10),
    ("errors.ConcretePartial", 10),
    ("errors.StaticOverride", 11),
    ("errors.ReturnMismatch", 12),
    ("errors.NarrowAccess", 13),
    ("errors.NarrowReturn", 12),
    ("errors.NarrowReturn", 13),
    ("errors.OverrideFinal", 14),
    ("errors.DeepFinal", 14),
}

VALID_TYPES = {
    "java.lang.Object",
    "java.lang.String",
    "app.Printable",
    "app.Serializable",
    "app.Loggable",
    "app.Entity",
    "app.User",
    "app.Admin",
    "app.Document",
    "app.FinalDoc",
    "app.Configurable",
    "app.Displayable",
    "app.Renderable",
    "app.PartialImpl",
    "app.SubDoc",
    "app.DataStore",
}


def load_violations():
    path = "/app/violations.json"
    assert os.path.isfile(path), f"violations.json not found at {path}"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "violations.json must contain a JSON array"
    return data


class TestViolationsFileFormat:
    def test_file_exists_and_is_valid_json(self):
        data = load_violations()
        assert len(data) > 0, "violations.json is empty"

    def test_each_entry_has_required_fields(self):
        data = load_violations()
        for i, v in enumerate(data):
            assert "type" in v, f"Entry {i} missing 'type' field"
            assert "rule" in v, f"Entry {i} missing 'rule' field"
            assert isinstance(v["type"], str), f"Entry {i}: 'type' must be string"
            assert isinstance(v["rule"], int), f"Entry {i}: 'rule' must be int"
            assert 1 <= v["rule"] <= 14, f"Entry {i}: rule must be 1-14"


class TestRequiredViolations:
    """Every expected violation must be present."""

    @pytest.fixture(scope="class")
    def actual_violations(self):
        data = load_violations()
        return {(v["type"], v["rule"]) for v in data}

    @pytest.mark.parametrize(
        "type_name,rule",
        sorted(REQUIRED_VIOLATIONS),
        ids=[f"{t}__R{r}" for t, r in sorted(REQUIRED_VIOLATIONS)],
    )
    def test_violation_present(self, actual_violations, type_name, rule):
        assert (type_name, rule) in actual_violations, (
            f"Missing required violation: type={type_name}, rule={rule}"
        )


class TestNoFalsePositives:
    """Valid types must have zero violations reported."""

    @pytest.fixture(scope="class")
    def violations_by_type(self):
        data = load_violations()
        by_type = {}
        for v in data:
            by_type.setdefault(v["type"], []).append(v["rule"])
        return by_type

    @pytest.mark.parametrize("type_name", sorted(VALID_TYPES))
    def test_no_violation_on_valid_type(self, violations_by_type, type_name):
        rules = violations_by_type.get(type_name, [])
        assert len(rules) == 0, (
            f"False positive on valid type {type_name}: rules {rules}"
        )


class TestRuleCoverage:
    """Every rule 1-14 must be tested by at least one violation."""

    def test_all_rules_covered(self):
        data = load_violations()
        rules_found = {v["rule"] for v in data}
        for r in range(1, 15):
            assert r in rules_found, f"Rule {r} has no violations in output"


class TestPipelineIntegrity:
    """Verify multi-stage pipeline produces consistent outputs."""

    def test_sql_violations_exist(self):
        path = "/app/sql_violations.json"
        assert os.path.isfile(path), "sql_violations.json not found"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list), "sql_violations.json must be a JSON array"
        # All SQL violations should be rules 1-5
        for v in data:
            assert 1 <= v["rule"] <= 5, (
                f"SQL violation has unexpected rule {v['rule']}")

    def test_py_violations_exist(self):
        path = "/app/py_violations.json"
        assert os.path.isfile(path), "py_violations.json not found"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list), "py_violations.json must be a JSON array"
        # All Python violations should be rules 6-14
        for v in data:
            assert 6 <= v["rule"] <= 14, (
                f"Python violation has unexpected rule {v['rule']}")

    def test_merged_output_covers_both_sources(self):
        data = load_violations()
        rules = {v["rule"] for v in data}
        # Must have violations from both SQL (1-5) and Python (6-14) stages
        assert any(r <= 5 for r in rules), "No structural violations from SQL stage"
        assert any(r >= 6 for r in rules), "No semantic violations from Python stage"


class TestCheckerDynamic:
    """Dynamic tests: insert new types into the DB and re-run the pipeline."""

    @pytest.fixture(autouse=True)
    def pipeline_backup(self):
        shutil.copy("/app/hierarchy.db", "/tmp/hierarchy_test_bak.db")
        backups = {}
        for fname in [
            "violations.json", "sql_violations.json",
            "py_violations.json", ".views_applied"
        ]:
            path = f"/app/{fname}"
            if os.path.exists(path):
                with open(path, "rb") as f:
                    backups[fname] = f.read()
        yield
        shutil.move("/tmp/hierarchy_test_bak.db", "/app/hierarchy.db")
        for fname, content in backups.items():
            with open(f"/app/{fname}", "wb") as f:
                f.write(content)
        for fname in [
            "violations.json", "sql_violations.json",
            "py_violations.json", ".views_applied"
        ]:
            path = f"/app/{fname}"
            if fname not in backups and os.path.exists(path):
                os.remove(path)

    def _run_pipeline(self):
        for fname in [
            "violations.json", "sql_violations.json",
            "py_violations.json", ".views_applied"
        ]:
            path = f"/app/{fname}"
            if os.path.exists(path):
                os.remove(path)
        result = subprocess.run(
            ["make", "-C", "/app", "check"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Pipeline failed: {result.stderr}\n{result.stdout}")
        with open("/app/violations.json") as f:
            return {(v["type"], v["rule"]) for v in json.load(f)}

    def test_dynamic_abstract_obligation(self):
        """New concrete class extending abstract class must trigger rule 10."""
        conn = sqlite3.connect("/app/hierarchy.db")
        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.NoConcrete", "class", '["public"]'))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.NoConcrete", "app.Entity", "extends"))
        conn.execute(
            "INSERT INTO constructors (type_name, parameter_types, modifiers) "
            "VALUES (?, ?, ?)",
            ("test.NoConcrete", "[]", '["public"]'))
        conn.commit()
        conn.close()
        violations = self._run_pipeline()
        assert ("test.NoConcrete", 10) in violations, (
            "Checker must detect abstract method obligation on dynamically "
            "added type")

    def test_dynamic_interface_cycle(self):
        """New interface cycle must be detected as rule 6."""
        conn = sqlite3.connect("/app/hierarchy.db")
        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.IA", "interface", '["public"]'))
        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.IB", "interface", '["public"]'))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.IA", "test.IB", "extends"))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.IB", "test.IA", "extends"))
        conn.commit()
        conn.close()
        violations = self._run_pipeline()
        assert ("test.IA", 6) in violations, "Interface cycle A not detected"
        assert ("test.IB", 6) in violations, "Interface cycle B not detected"

    def test_dynamic_valid_type(self):
        """Valid class must produce no violations."""
        conn = sqlite3.connect("/app/hierarchy.db")
        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.Valid", "class", '["public"]'))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.Valid", "java.lang.Object", "extends"))
        conn.execute(
            "INSERT INTO constructors (type_name, parameter_types, modifiers) "
            "VALUES (?, ?, ?)",
            ("test.Valid", "[]", '["public"]'))
        conn.execute(
            "INSERT INTO methods (type_name, name, parameter_types, "
            "return_type, modifiers) VALUES (?, ?, ?, ?, ?)",
            ("test.Valid", "work", '["int"]', "void", '["public"]'))
        conn.commit()
        conn.close()
        violations = self._run_pipeline()
        bad = [(t, r) for t, r in violations if t == "test.Valid"]
        assert len(bad) == 0, f"Valid type has false positives: {bad}"

    def test_dynamic_overloaded_methods(self):
        """Methods with same name but different params are NOT duplicates."""
        conn = sqlite3.connect("/app/hierarchy.db")
        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.Overload", "class", '["public"]'))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.Overload", "java.lang.Object", "extends"))
        conn.execute(
            "INSERT INTO constructors (type_name, parameter_types, modifiers) "
            "VALUES (?, ?, ?)",
            ("test.Overload", "[]", '["public"]'))
        conn.execute(
            "INSERT INTO methods (type_name, name, parameter_types, "
            "return_type, modifiers) VALUES (?, ?, ?, ?, ?)",
            ("test.Overload", "handle", '["int"]', "int", '["public"]'))
        conn.execute(
            "INSERT INTO methods (type_name, name, parameter_types, "
            "return_type, modifiers) VALUES (?, ?, ?, ?, ?)",
            ("test.Overload", "handle", '["java.lang.String"]',
             "java.lang.String", '["public"]'))
        conn.commit()
        conn.close()
        violations = self._run_pipeline()
        assert ("test.Overload", 7) not in violations, (
            "Overloaded methods (different param types) must not be flagged "
            "as duplicate")

    def test_dynamic_transitive_final(self):
        """Overriding final method from grandparent must be detected."""
        conn = sqlite3.connect("/app/hierarchy.db")
        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.GP", "class", '["public"]'))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.GP", "java.lang.Object", "extends"))
        conn.execute(
            "INSERT INTO constructors (type_name, parameter_types, modifiers) "
            "VALUES (?, ?, ?)",
            ("test.GP", "[]", '["public"]'))
        conn.execute(
            "INSERT INTO methods (type_name, name, parameter_types, "
            "return_type, modifiers) VALUES (?, ?, ?, ?, ?)",
            ("test.GP", "locked", "[]", "void", '["public", "final"]'))

        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.Mid", "class", '["public"]'))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.Mid", "test.GP", "extends"))
        conn.execute(
            "INSERT INTO constructors (type_name, parameter_types, modifiers) "
            "VALUES (?, ?, ?)",
            ("test.Mid", "[]", '["public"]'))

        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.Child", "class", '["public"]'))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.Child", "test.Mid", "extends"))
        conn.execute(
            "INSERT INTO constructors (type_name, parameter_types, modifiers) "
            "VALUES (?, ?, ?)",
            ("test.Child", "[]", '["public"]'))
        conn.execute(
            "INSERT INTO methods (type_name, name, parameter_types, "
            "return_type, modifiers) VALUES (?, ?, ?, ?, ?)",
            ("test.Child", "locked", "[]", "void", '["public"]'))
        conn.commit()
        conn.close()
        violations = self._run_pipeline()
        assert ("test.Child", 14) in violations, (
            "Must detect overriding a final method declared in a grandparent")

    def test_dynamic_multi_violation_type(self):
        """A type with both return mismatch and access narrowing must
        report both violations, not just one."""
        conn = sqlite3.connect("/app/hierarchy.db")
        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            ("test.MultiErr", "class", '["public"]'))
        conn.execute(
            "INSERT INTO inheritance (child_name, parent_name, relation) "
            "VALUES (?, ?, ?)",
            ("test.MultiErr", "app.Entity", "extends"))
        conn.execute(
            "INSERT INTO constructors (type_name, parameter_types, modifiers) "
            "VALUES (?, ?, ?)",
            ("test.MultiErr", "[]", '["public"]'))
        conn.execute(
            "INSERT INTO methods (type_name, name, parameter_types, "
            "return_type, modifiers) VALUES (?, ?, ?, ?, ?)",
            ("test.MultiErr", "getId", "[]", "int", '["public"]'))
        conn.execute(
            "INSERT INTO methods (type_name, name, parameter_types, "
            "return_type, modifiers) VALUES (?, ?, ?, ?, ?)",
            ("test.MultiErr", "validate", "[]", "int", '["protected"]'))
        conn.commit()
        conn.close()
        violations = self._run_pipeline()
        assert ("test.MultiErr", 12) in violations, (
            "Must detect return type mismatch")
        assert ("test.MultiErr", 13) in violations, (
            "Must detect access narrowing on same type that has return "
            "mismatch - both violations must be reported")
