
import subprocess
import json
import pytest
import tempfile
import os


def run_parser(schema_text: str) -> dict:
    """Write schema to a temp file, invoke the parser, return parsed JSON."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sdl", delete=False, dir="/tmp"
    ) as f:
        f.write(schema_text)
        f.flush()
        temp_path = f.name

    try:
        result = subprocess.run(
            ["npx", "tsx", "src/index.ts", temp_path],
            capture_output=True,
            text=True,
            cwd="/app",
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Parser exited with code {result.returncode}:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return json.loads(result.stdout)
    finally:
        os.unlink(temp_path)


# ──────────────────────────────────────────────
# Parser construction and basic type parsing
# ──────────────────────────────────────────────

class TestParserConstruction:
    def test_parser_starts_on_empty_type(self):
        result = run_parser("type Empty {}")
        assert "ast" in result

    def test_parser_starts_on_empty_enum(self):
        result = run_parser("enum Color { RED }")
        assert "ast" in result


class TestTypeParsing:
    def test_simple_type_two_fields(self):
        schema = """
        type User {
            id: Int;
            name: String;
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        types = result["ast"]["types"]
        assert len(types) == 1
        assert types[0]["name"] == "User"
        assert len(types[0]["fields"]) == 2
        assert types[0]["fields"][0] == {
            "name": "id", "type": "Int", "nullable": False, "list": False,
        }
        assert types[0]["fields"][1] == {
            "name": "name", "type": "String", "nullable": False, "list": False,
        }

    def test_nullable_field(self):
        schema = """
        type Profile {
            bio: String?;
            age: Int;
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        fields = result["ast"]["types"][0]["fields"]
        assert fields[0]["nullable"] is True
        assert fields[0]["type"] == "String"
        assert fields[1]["nullable"] is False

    def test_list_field(self):
        schema = """
        type Article {
            tags: [String];
            scores: [Int];
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        fields = result["ast"]["types"][0]["fields"]
        assert fields[0]["list"] is True
        assert fields[0]["type"] == "String"
        assert fields[1]["list"] is True
        assert fields[1]["type"] == "Int"

    def test_empty_type_body(self):
        schema = "type Empty {}"
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        assert result["ast"]["types"][0]["name"] == "Empty"
        assert result["ast"]["types"][0]["fields"] == []


# ──────────────────────────────────────────────
# Enum parsing
# ──────────────────────────────────────────────

class TestEnumParsing:
    def test_simple_enum(self):
        schema = """
        enum Status {
            ACTIVE,
            INACTIVE,
            PENDING
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        enums = result["ast"]["enums"]
        assert len(enums) == 1
        assert enums[0]["name"] == "Status"
        assert enums[0]["values"] == ["ACTIVE", "INACTIVE", "PENDING"]

    def test_single_value_enum(self):
        schema = "enum Singleton { ONLY }"
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        enums = result["ast"]["enums"]
        assert enums[0]["values"] == ["ONLY"]


# ──────────────────────────────────────────────
# Mixed declarations
# ──────────────────────────────────────────────

class TestMultipleDeclarations:
    def test_types_and_enums_together(self):
        schema = """
        type User {
            id: Int;
            name: String;
            role: Role;
        }
        enum Role {
            ADMIN,
            USER,
            GUEST
        }
        type Post {
            title: String;
            author: User;
            published: Boolean;
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        assert len(result["ast"]["types"]) == 2
        assert len(result["ast"]["enums"]) == 1
        assert result["ast"]["types"][0]["name"] == "User"
        assert result["ast"]["types"][1]["name"] == "Post"
        assert result["ast"]["enums"][0]["name"] == "Role"
        assert result["ast"]["enums"][0]["values"] == ["ADMIN", "USER", "GUEST"]
        user_fields = result["ast"]["types"][0]["fields"]
        assert len(user_fields) == 3
        assert user_fields[2]["type"] == "Role"
        post_fields = result["ast"]["types"][1]["fields"]
        assert len(post_fields) == 3
        assert post_fields[1]["type"] == "User"


# ──────────────────────────────────────────────
# Error recovery
# ──────────────────────────────────────────────

class TestErrorRecovery:
    def test_missing_semicolon_recovers(self):
        schema = """
        type Config {
            host: String
            port: Int;
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) >= 1
        config_type = result["ast"]["types"][0]
        assert config_type["name"] == "Config"
        assert len(config_type["fields"]) == 2
        assert config_type["fields"][0]["name"] == "host"
        assert config_type["fields"][1]["name"] == "port"

    def test_no_errors_on_valid_input(self):
        schema = """
        type Valid {
            x: Int;
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        assert len(result["lexErrors"]) == 0


# ──────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────

class TestEdgeCases:
    def test_comments_ignored(self):
        schema = """
        // Schema header comment
        type Commented {
            // field-level comment
            value: Int;
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        assert result["ast"]["types"][0]["name"] == "Commented"
        assert len(result["ast"]["types"][0]["fields"]) == 1

    def test_custom_type_references(self):
        schema = """
        type Order {
            customer: Customer;
            items: [OrderItem];
            note: String?;
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        fields = result["ast"]["types"][0]["fields"]
        assert fields[0] == {
            "name": "customer", "type": "Customer",
            "nullable": False, "list": False,
        }
        assert fields[1] == {
            "name": "items", "type": "OrderItem",
            "nullable": False, "list": True,
        }
        assert fields[2] == {
            "name": "note", "type": "String",
            "nullable": True, "list": False,
        }

    def test_keyword_prefix_identifier(self):
        """Identifiers starting with keyword prefixes lex as Identifier."""
        schema = """
        type TypeInfo {
            typeface: String;
            enumerate: Int;
        }
        """
        result = run_parser(schema)
        assert len(result["parseErrors"]) == 0
        assert result["ast"]["types"][0]["name"] == "TypeInfo"
        fields = result["ast"]["types"][0]["fields"]
        assert fields[0]["name"] == "typeface"
        assert fields[1]["name"] == "enumerate"


# ──────────────────────────────────────────────
# Semantic analysis: diagnostics output
# ──────────────────────────────────────────────

class TestDiagnosticsPresence:
    """The output must include a diagnostics array."""

    def test_diagnostics_key_exists(self):
        result = run_parser("type Foo { x: Int; }")
        assert "diagnostics" in result
        assert isinstance(result["diagnostics"], list)

    def test_clean_schema_no_diagnostics(self):
        schema = """
        type User { name: String; age: Int; }
        enum Role { ADMIN, USER }
        """
        result = run_parser(schema)
        errors = [d for d in result["diagnostics"] if d["severity"] == "error"]
        assert len(errors) == 0


class TestDuplicateNames:
    def test_duplicate_type_names(self):
        schema = """
        type Dup { a: Int; }
        type Dup { b: String; }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        dup_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "duplicate" in d["message"].lower()
            and "Dup" in d["message"]
        ]
        assert len(dup_errors) >= 1, "Should detect duplicate type name 'Dup'"

    def test_duplicate_enum_names(self):
        schema = """
        enum Color { RED, BLUE }
        enum Color { GREEN }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        dup_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "duplicate" in d["message"].lower()
            and "Color" in d["message"]
        ]
        assert len(dup_errors) >= 1

    def test_type_and_enum_same_name(self):
        schema = """
        type Status { code: Int; }
        enum Status { ACTIVE, INACTIVE }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        dup_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "duplicate" in d["message"].lower()
            and "Status" in d["message"]
        ]
        assert len(dup_errors) >= 1

    def test_case_sensitive_not_duplicates(self):
        """user and User are different names — no duplicate error."""
        schema = """
        type user { a: Int; }
        type User { b: String; }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        dup_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "duplicate" in d["message"].lower()
        ]
        assert len(dup_errors) == 0, (
            "Case-sensitive: 'user' and 'User' are not duplicates"
        )


class TestUndefinedTypes:
    def test_undefined_type_reference(self):
        schema = """
        type User {
            role: Role;
            name: String;
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        undef = [
            d for d in diags
            if d["severity"] == "error"
            and "undefined" in d["message"].lower()
            and "Role" in d["message"]
        ]
        assert len(undef) >= 1, "Role is undefined — should be reported"

    def test_enum_resolves_type_reference(self):
        """Enum names should count as defined types."""
        schema = """
        type User {
            role: Role;
        }
        enum Role { ADMIN, USER }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        undef = [
            d for d in diags
            if d["severity"] == "error"
            and "undefined" in d["message"].lower()
            and "Role" in d["message"]
        ]
        assert len(undef) == 0, (
            "Role is defined as an enum — should not be flagged as undefined"
        )

    def test_builtin_types_not_undefined(self):
        schema = """
        type Entity {
            id: ID;
            name: String;
            count: Int;
            score: Float;
            active: Boolean;
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        undef = [
            d for d in diags
            if d["severity"] == "error"
            and "undefined" in d["message"].lower()
        ]
        assert len(undef) == 0, "Builtin types should not be flagged as undefined"

    def test_cross_type_reference_resolves(self):
        schema = """
        type Author { name: String; }
        type Book { writer: Author; title: String; }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        undef = [
            d for d in diags
            if d["severity"] == "error"
            and "undefined" in d["message"].lower()
        ]
        assert len(undef) == 0


class TestDuplicateFields:
    def test_duplicate_field_in_type(self):
        schema = """
        type Widget {
            name: String;
            size: Int;
            name: Float;
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        dup = [
            d for d in diags
            if d["severity"] == "error"
            and "duplicate" in d["message"].lower()
            and "name" in d["message"].lower()
        ]
        assert len(dup) >= 1


class TestDuplicateEnumValues:
    def test_duplicate_enum_value(self):
        schema = """
        enum Priority {
            HIGH,
            MEDIUM,
            HIGH
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        dup = [
            d for d in diags
            if d["severity"] == "error"
            and "duplicate" in d["message"].lower()
            and "HIGH" in d["message"]
        ]
        assert len(dup) >= 1


# ──────────────────────────────────────────────
# Required reference cycle detection
# ──────────────────────────────────────────────

class TestRequiredCycles:
    def test_direct_self_reference_cycle(self):
        schema = """
        type Node {
            child: Node;
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        cycle_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "cycle" in d["message"].lower()
            and "Node" in d["message"]
        ]
        assert len(cycle_errors) >= 1, "Direct self-reference cycle should be detected"

    def test_indirect_two_type_cycle(self):
        schema = """
        type Alpha {
            other: Beta;
        }
        type Beta {
            other: Alpha;
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        cycle_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "cycle" in d["message"].lower()
        ]
        assert len(cycle_errors) >= 1, "Indirect cycle Alpha->Beta->Alpha must be detected"
        all_messages = " ".join(d["message"] for d in cycle_errors)
        assert "Alpha" in all_messages and "Beta" in all_messages

    def test_indirect_three_type_cycle(self):
        schema = """
        type Xray { link: Yankee; }
        type Yankee { link: Zulu; }
        type Zulu { link: Xray; }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        cycle_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "cycle" in d["message"].lower()
        ]
        assert len(cycle_errors) >= 1, "Three-type cycle must be detected"
        all_messages = " ".join(d["message"] for d in cycle_errors)
        assert "Xray" in all_messages
        assert "Yankee" in all_messages
        assert "Zulu" in all_messages

    def test_nullable_breaks_cycle(self):
        schema = """
        type Foo {
            bar: Bar?;
        }
        type Bar {
            foo: Foo;
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        cycle_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "cycle" in d["message"].lower()
        ]
        assert len(cycle_errors) == 0, "Nullable reference breaks the cycle"

    def test_list_breaks_cycle(self):
        schema = """
        type Parent {
            children: [Child];
        }
        type Child {
            parent: Parent;
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        cycle_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "cycle" in d["message"].lower()
        ]
        assert len(cycle_errors) == 0, "List reference breaks the cycle"

    def test_no_false_positive_on_chain(self):
        """A -> B -> C with no back-edge is not a cycle."""
        schema = """
        type A { b: B; }
        type B { c: C; }
        type C { val: Int; }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        cycle_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "cycle" in d["message"].lower()
        ]
        assert len(cycle_errors) == 0, "Linear chain is not a cycle"

    def test_self_ref_nullable_no_cycle(self):
        """Nullable self-reference is fine (e.g. linked list)."""
        schema = """
        type LinkedNode {
            next: LinkedNode?;
            value: Int;
        }
        """
        result = run_parser(schema)
        diags = result["diagnostics"]
        cycle_errors = [
            d for d in diags
            if d["severity"] == "error"
            and "cycle" in d["message"].lower()
        ]
        assert len(cycle_errors) == 0
