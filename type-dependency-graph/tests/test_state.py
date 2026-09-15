import json
import pytest


OUTPUT_FILE = "/tmp/analyzer_output.json"


@pytest.fixture
def output():
    with open(OUTPUT_FILE) as f:
        return json.load(f)


def find_symbol(output, name):
    matches = [s for s in output if s["name"] == name]
    assert len(matches) == 1, f"Expected exactly one symbol '{name}', found {len(matches)}"
    return matches[0]


class TestSymbolCount:
    def test_total_symbols(self, output):
        assert len(output) == 23, (
            f"Expected 23 symbols, got {len(output)}: "
            f"{[s['name'] for s in output]}"
        )


class TestCoreTypes:
    def test_identifiable(self, output):
        s = find_symbol(output, "Identifiable")
        assert s["kind"] == "interface"
        assert s["file"] == "src/core.ts"
        assert s["dependencies"] == []
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []

    def test_timestamped(self, output):
        s = find_symbol(output, "Timestamped")
        assert s["kind"] == "interface"
        assert s["file"] == "src/core.ts"
        assert s["dependencies"] == []
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []

    def test_permission(self, output):
        s = find_symbol(output, "Permission")
        assert s["kind"] == "enum"
        assert s["file"] == "src/core.ts"
        assert s["dependencies"] == []
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []

    def test_versioned(self, output):
        s = find_symbol(output, "Versioned")
        assert s["kind"] == "interface"
        assert s["file"] == "src/core.ts"
        assert s["dependencies"] == []
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []


class TestModelTypes:
    def test_user(self, output):
        s = find_symbol(output, "User")
        assert s["kind"] == "interface"
        assert s["file"] == "src/models.ts"
        assert s["dependencies"] == ["Identifiable", "Permission", "Timestamped"]
        assert s["transitiveDependencies"] == ["Identifiable", "Permission", "Timestamped"]
        assert s["cyclicWith"] == []

    def test_post(self, output):
        s = find_symbol(output, "Post")
        assert s["kind"] == "interface"
        assert s["file"] == "src/models.ts"
        assert s["dependencies"] == ["Identifiable", "Timestamped", "User", "Versioned"]
        assert s["transitiveDependencies"] == [
            "Identifiable", "Permission", "Timestamped", "User", "Versioned"
        ]
        assert s["cyclicWith"] == []

    def test_user_summary(self, output):
        s = find_symbol(output, "UserSummary")
        assert s["kind"] == "type"
        assert s["file"] == "src/models.ts"
        assert s["dependencies"] == ["User"]
        assert s["transitiveDependencies"] == [
            "Identifiable", "Permission", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == []


class TestServiceTypes:
    def test_crud_service(self, output):
        s = find_symbol(output, "CrudService")
        assert s["kind"] == "interface"
        assert s["file"] == "src/services.ts"
        assert s["dependencies"] == ["Identifiable"]
        assert s["transitiveDependencies"] == ["Identifiable"]
        assert s["cyclicWith"] == []

    def test_user_crud_service(self, output):
        s = find_symbol(output, "UserCrudService")
        assert s["kind"] == "interface"
        assert s["file"] == "src/services.ts"
        assert s["dependencies"] == ["CrudService", "User"]
        assert s["transitiveDependencies"] == [
            "CrudService", "Identifiable", "Permission", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == []

    def test_service_result(self, output):
        s = find_symbol(output, "ServiceResult")
        assert s["kind"] == "type"
        assert s["file"] == "src/services.ts"
        assert s["dependencies"] == []
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []

    def test_create_user_service(self, output):
        s = find_symbol(output, "createUserService")
        assert s["kind"] == "function"
        assert s["file"] == "src/services.ts"
        assert s["dependencies"] == [
            "CrudService", "Post", "ServiceResult", "User"
        ]
        assert s["transitiveDependencies"] == [
            "CrudService", "Identifiable", "Permission", "Post",
            "ServiceResult", "Timestamped", "User", "Versioned"
        ]
        assert s["cyclicWith"] == []


class TestUtilTypes:
    def test_deep_readonly(self, output):
        s = find_symbol(output, "DeepReadonly")
        assert s["kind"] == "type"
        assert s["file"] == "src/utils.ts"
        assert s["dependencies"] == ["DeepReadonly"]
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []

    def test_nullable(self, output):
        s = find_symbol(output, "Nullable")
        assert s["kind"] == "type"
        assert s["file"] == "src/utils.ts"
        assert s["dependencies"] == []
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []

    def test_json_value(self, output):
        s = find_symbol(output, "JsonValue")
        assert s["kind"] == "type"
        assert s["file"] == "src/utils.ts"
        assert s["dependencies"] == ["JsonValue"]
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []

    def test_extract_id(self, output):
        s = find_symbol(output, "ExtractId")
        assert s["kind"] == "type"
        assert s["file"] == "src/utils.ts"
        assert s["dependencies"] == ["Identifiable"]
        assert s["transitiveDependencies"] == ["Identifiable"]
        assert s["cyclicWith"] == []


class TestEventTypes:
    def test_event_map(self, output):
        s = find_symbol(output, "EventMap")
        assert s["kind"] == "interface"
        assert s["file"] == "src/events.ts"
        assert s["dependencies"] == ["Identifiable", "Timestamped", "User"]
        assert s["transitiveDependencies"] == [
            "Identifiable", "Permission", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == []

    def test_event_payload(self, output):
        s = find_symbol(output, "EventPayload")
        assert s["kind"] == "type"
        assert s["file"] == "src/events.ts"
        assert s["dependencies"] == ["EventMap"]
        assert s["transitiveDependencies"] == [
            "EventMap", "Identifiable", "Permission", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == []

    def test_unwrap_array(self, output):
        s = find_symbol(output, "UnwrapArray")
        assert s["kind"] == "type"
        assert s["file"] == "src/events.ts"
        assert s["dependencies"] == []
        assert s["transitiveDependencies"] == []
        assert s["cyclicWith"] == []

    def test_audit_entry(self, output):
        s = find_symbol(output, "AuditEntry")
        assert s["kind"] == "type"
        assert s["file"] == "src/events.ts"
        assert s["dependencies"] == ["Identifiable", "Timestamped", "User"]
        assert s["transitiveDependencies"] == [
            "Identifiable", "Permission", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == []

    def test_create_event_bus(self, output):
        s = find_symbol(output, "createEventBus")
        assert s["kind"] == "function"
        assert s["file"] == "src/events.ts"
        assert s["dependencies"] == ["EventMap", "EventPayload", "Identifiable"]
        assert s["transitiveDependencies"] == [
            "EventMap", "EventPayload", "Identifiable",
            "Permission", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == []


class TestRegistryTypes:
    def test_registry_entry(self, output):
        s = find_symbol(output, "RegistryEntry")
        assert s["kind"] == "interface"
        assert s["file"] == "src/registry.ts"
        assert s["dependencies"] == ["EntryMetadata", "Identifiable", "Registry"]
        assert s["transitiveDependencies"] == [
            "EntryMetadata", "Identifiable", "Permission",
            "Registry", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == ["EntryMetadata", "Registry"]

    def test_registry(self, output):
        s = find_symbol(output, "Registry")
        assert s["kind"] == "interface"
        assert s["file"] == "src/registry.ts"
        assert s["dependencies"] == ["Identifiable", "RegistryEntry", "User"]
        assert s["transitiveDependencies"] == [
            "EntryMetadata", "Identifiable", "Permission",
            "RegistryEntry", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == ["EntryMetadata", "RegistryEntry"]

    def test_entry_metadata(self, output):
        s = find_symbol(output, "EntryMetadata")
        assert s["kind"] == "type"
        assert s["file"] == "src/registry.ts"
        assert s["dependencies"] == ["Identifiable", "RegistryEntry"]
        assert s["transitiveDependencies"] == [
            "Identifiable", "Permission", "Registry",
            "RegistryEntry", "Timestamped", "User"
        ]
        assert s["cyclicWith"] == ["Registry", "RegistryEntry"]


class TestSorting:
    def test_sorted_by_file_then_line(self, output):
        for i in range(len(output) - 1):
            a, b = output[i], output[i + 1]
            if a["file"] == b["file"]:
                assert a["line"] <= b["line"], (
                    f"Not sorted by line within {a['file']}: "
                    f"{a['name']} (line {a['line']}) before {b['name']} (line {b['line']})"
                )
            else:
                assert a["file"] < b["file"], (
                    f"Not sorted by file: {a['file']} before {b['file']}"
                )

    def test_dependencies_sorted(self, output):
        for s in output:
            assert s["dependencies"] == sorted(s["dependencies"]), (
                f"Dependencies not sorted for {s['name']}: {s['dependencies']}"
            )

    def test_transitive_sorted(self, output):
        for s in output:
            assert s["transitiveDependencies"] == sorted(s["transitiveDependencies"]), (
                f"Transitive dependencies not sorted for {s['name']}: {s['transitiveDependencies']}"
            )

    def test_cyclic_sorted(self, output):
        for s in output:
            assert s["cyclicWith"] == sorted(s["cyclicWith"]), (
                f"cyclicWith not sorted for {s['name']}: {s['cyclicWith']}"
            )


class TestLineNumbers:
    def test_positive_line_numbers(self, output):
        for s in output:
            assert isinstance(s["line"], int) and s["line"] > 0, (
                f"Invalid line number for {s['name']}: {s['line']}"
            )

    def test_core_line_numbers(self, output):
        assert find_symbol(output, "Identifiable")["line"] == 1
        assert find_symbol(output, "Timestamped")["line"] == 5
        assert find_symbol(output, "Permission")["line"] == 10
        assert find_symbol(output, "Versioned")["line"] == 16

    def test_event_line_numbers(self, output):
        assert find_symbol(output, "EventMap")["line"] == 4
        assert find_symbol(output, "EventPayload")["line"] == 10
        assert find_symbol(output, "UnwrapArray")["line"] == 12
        assert find_symbol(output, "AuditEntry")["line"] == 14
        assert find_symbol(output, "createEventBus")["line"] == 16

    def test_model_line_numbers(self, output):
        assert find_symbol(output, "User")["line"] == 3
        assert find_symbol(output, "Post")["line"] == 9
        assert find_symbol(output, "UserSummary")["line"] == 15

    def test_service_line_numbers(self, output):
        assert find_symbol(output, "CrudService")["line"] == 4
        assert find_symbol(output, "UserCrudService")["line"] == 12
        assert find_symbol(output, "ServiceResult")["line"] == 16
        assert find_symbol(output, "createUserService")["line"] == 20

    def test_util_line_numbers(self, output):
        assert find_symbol(output, "DeepReadonly")["line"] == 3
        assert find_symbol(output, "Nullable")["line"] == 7
        assert find_symbol(output, "JsonValue")["line"] == 9
        assert find_symbol(output, "ExtractId")["line"] == 17

    def test_registry_line_numbers(self, output):
        assert find_symbol(output, "RegistryEntry")["line"] == 4
        assert find_symbol(output, "Registry")["line"] == 10
        assert find_symbol(output, "EntryMetadata")["line"] == 15


class TestNoBuiltins:
    def test_no_builtin_deps(self, output):
        builtins = {
            "string", "number", "boolean", "void", "null", "undefined",
            "never", "unknown", "any", "object", "Date", "Promise",
            "Array", "Map", "Set", "Partial", "Pick", "Omit", "Record",
            "Required", "Readonly", "Error", "Function", "Object", "Symbol",
            "Capitalize", "Uncapitalize", "Uppercase", "Lowercase",
            "ReadonlyArray", "Exclude", "Extract", "NonNullable",
            "ReturnType", "Parameters", "InstanceType", "PropertyKey",
        }
        for s in output:
            for d in s["dependencies"]:
                assert d not in builtins, (
                    f"Built-in type '{d}' found in dependencies of {s['name']}"
                )
            for d in s["transitiveDependencies"]:
                assert d not in builtins, (
                    f"Built-in type '{d}' found in transitive dependencies of {s['name']}"
                )

    def test_no_type_params(self, output):
        type_params = {"T", "K", "U", "V", "P", "R", "A"}
        for s in output:
            for d in s["dependencies"]:
                assert d not in type_params, (
                    f"Type parameter '{d}' found in dependencies of {s['name']}"
                )
            for d in s["transitiveDependencies"]:
                assert d not in type_params, (
                    f"Type parameter '{d}' found in transitive dependencies of {s['name']}"
                )


class TestOutputSchema:
    def test_required_fields(self, output):
        required = {"name", "kind", "file", "line", "dependencies",
                     "transitiveDependencies", "cyclicWith"}
        for s in output:
            assert set(s.keys()) >= required, (
                f"Missing fields in {s.get('name', '?')}: "
                f"{required - set(s.keys())}"
            )

    def test_valid_kinds(self, output):
        valid_kinds = {"interface", "type", "enum", "function", "class"}
        for s in output:
            assert s["kind"] in valid_kinds, (
                f"Invalid kind '{s['kind']}' for {s['name']}"
            )

    def test_all_fields_are_lists(self, output):
        for s in output:
            assert isinstance(s["dependencies"], list), (
                f"dependencies for {s['name']} is not a list"
            )
            assert isinstance(s["transitiveDependencies"], list), (
                f"transitiveDependencies for {s['name']} is not a list"
            )
            assert isinstance(s["cyclicWith"], list), (
                f"cyclicWith for {s['name']} is not a list"
            )


class TestCycleProperties:
    def test_cycle_symmetry(self, output):
        """If A lists B in cyclicWith, B must list A."""
        symbol_map = {s["name"]: s for s in output}
        for s in output:
            for partner in s["cyclicWith"]:
                assert partner in symbol_map, (
                    f"{s['name']} lists '{partner}' in cyclicWith but it doesn't exist"
                )
                partner_sym = symbol_map[partner]
                assert s["name"] in partner_sym["cyclicWith"], (
                    f"{s['name']} lists '{partner}' in cyclicWith but "
                    f"{partner} does not list {s['name']}"
                )

    def test_no_self_in_cyclic(self, output):
        """No symbol should list itself in cyclicWith."""
        for s in output:
            assert s["name"] not in s["cyclicWith"], (
                f"{s['name']} lists itself in cyclicWith"
            )

    def test_exactly_three_cyclic_symbols(self, output):
        """Exactly three symbols should have non-empty cyclicWith."""
        cyclic = [s["name"] for s in output if s["cyclicWith"]]
        assert sorted(cyclic) == ["EntryMetadata", "Registry", "RegistryEntry"], (
            f"Expected exactly EntryMetadata, Registry, RegistryEntry to be cyclic, "
            f"got {sorted(cyclic)}"
        )


class TestTransitiveProperties:
    def test_direct_subset_of_transitive(self, output):
        """Direct deps (minus self-references) should be subset of transitive deps."""
        for s in output:
            non_self_deps = set(d for d in s["dependencies"] if d != s["name"])
            transitive = set(s["transitiveDependencies"])
            assert non_self_deps <= transitive, (
                f"Direct deps of {s['name']} not in transitive: "
                f"{non_self_deps - transitive}"
            )

    def test_self_referential_empty_transitive(self, output):
        """Self-referential types with no other deps have empty transitive sets."""
        for name in ["JsonValue", "DeepReadonly"]:
            s = find_symbol(output, name)
            assert s["dependencies"] == [name]
            assert s["transitiveDependencies"] == []

    def test_no_self_in_transitive(self, output):
        """No symbol should list itself in transitiveDependencies."""
        for s in output:
            assert s["name"] not in s["transitiveDependencies"], (
                f"{s['name']} lists itself in transitiveDependencies"
            )
