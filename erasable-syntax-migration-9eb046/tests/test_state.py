import subprocess
import json
import os
import glob
import pytest


TSC_BIN = "./node_modules/.bin/tsc"


@pytest.fixture(scope="module")
def compiled_output():
    """Compile TypeScript and run the output, returning parsed JSON."""
    subprocess.run(["rm", "-rf", "/app/dist"], cwd="/app")
    compile_result = subprocess.run(
        [TSC_BIN],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert compile_result.returncode == 0, (
        f"TypeScript compilation failed with erasableSyntaxOnly: true\n"
        f"stdout: {compile_result.stdout}\n"
        f"stderr: {compile_result.stderr}"
    )
    assert os.path.exists("/app/dist/main.js"), "dist/main.js was not produced"

    run_result = subprocess.run(
        ["node", "/app/dist/main.js"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert run_result.returncode == 0, (
        f"Runtime error:\nstdout: {run_result.stdout}\nstderr: {run_result.stderr}"
    )
    data = json.loads(run_result.stdout)
    return data


# --------------- Anti-cheat tests ---------------


def test_tsconfig_has_erasable_flag():
    """tsconfig.json must have erasableSyntaxOnly: true and no weakening."""
    with open("/app/tsconfig.json") as f:
        tsconfig = json.load(f)
    opts = tsconfig.get("compilerOptions", {})
    assert opts.get("erasableSyntaxOnly") is True, (
        "erasableSyntaxOnly must be true in tsconfig.json"
    )
    assert opts.get("noCheck") is not True, "noCheck must not be enabled"
    assert opts.get("useDefineForClassFields") is not False, (
        "useDefineForClassFields must not be explicitly disabled"
    )


def test_no_ts_suppression_comments():
    """Source files must not use @ts-ignore, @ts-expect-error, or @ts-nocheck."""
    for filepath in glob.glob("/app/src/**/*.ts", recursive=True):
        with open(filepath) as f:
            content = f.read()
        assert "@ts-ignore" not in content, f"{filepath} contains @ts-ignore"
        assert "@ts-expect-error" not in content, (
            f"{filepath} contains @ts-expect-error"
        )
        assert "@ts-nocheck" not in content, f"{filepath} contains @ts-nocheck"


def test_tsconfig_not_modified():
    """tsconfig.json must not have been altered from original."""
    with open("/app/tsconfig.json") as f:
        tsconfig = json.load(f)
    opts = tsconfig.get("compilerOptions", {})
    assert opts.get("target") == "ES2022", "target must remain ES2022"
    assert opts.get("module") == "commonjs", "module must remain commonjs"
    assert opts.get("strict") is True, "strict must remain true"


# --------------- Compilation test ---------------


def test_compilation_succeeds():
    """tsc --noEmit must succeed with erasableSyntaxOnly: true."""
    result = subprocess.run(
        [TSC_BIN, "--noEmit"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"tsc --noEmit failed:\n{result.stdout}\n{result.stderr}"
    )


# --------------- Protocol runtime behavior tests ---------------


def test_protocol_reverse_mapping(compiled_output):
    """Numeric enum reverse mapping must be preserved."""
    assert compiled_output["protocol_name_1"] == "HTTP"
    assert compiled_output["protocol_name_2"] == "HTTPS"
    assert compiled_output["protocol_name_4"] == "WSS"


def test_protocol_namespace_functions(compiled_output):
    """Namespace-merged functions must remain on the same object."""
    assert compiled_output["is_secure_http"] is False
    assert compiled_output["is_secure_https"] is True
    assert compiled_output["is_secure_wss"] is True
    assert compiled_output["protocol_names"] == ["HTTP", "HTTPS", "WS", "WSS"]


def test_string_enum_values(compiled_output):
    """String enum replacement must preserve values without reverse mapping."""
    assert compiled_output["msg_type_request"] == "REQ"
    assert compiled_output["msg_type_response"] == "RES"


def test_const_enum_flags(compiled_output):
    """Const enum bitflag values must be computed identically."""
    assert compiled_output["flags_value"] == 3
    assert compiled_output["has_compressed"] is True
    assert compiled_output["has_signed"] is False
    assert compiled_output["all_flags"] == 7


def test_heterogeneous_enum(compiled_output):
    """Heterogeneous enum: numeric reverse mapping, string values, type detection."""
    assert compiled_output["log_debug"] == 0
    assert compiled_output["log_error"] == "ERROR"
    assert compiled_output["log_debug_name"] == "Debug"
    assert compiled_output["log_info_name"] == "Info"
    assert compiled_output["log_is_numeric_debug"] is True
    assert compiled_output["log_is_numeric_error"] is False


# --------------- Transport runtime behavior tests ---------------


def test_parameter_properties(compiled_output):
    """Parameter properties must be expanded to explicit field declarations."""
    assert compiled_output["conn_host"] == "localhost"
    assert compiled_output["conn_port"] == 8080
    assert compiled_output["conn_protocol"] == 1
    assert compiled_output["conn_compressed"] is True
    assert compiled_output["conn_encrypted"] is True
    assert compiled_output["conn_describe"] == "localhost:8080 [HTTP]"


def test_namespace_with_class(compiled_output):
    """Namespace-exported class (Transport.Pool) must remain constructible."""
    assert compiled_output["pool_max"] == 10
    assert compiled_output["pool_size_0"] == 0
    assert compiled_output["pool_size_1"] == 1


# --------------- Middleware runtime behavior tests ---------------


def test_middleware_basic_properties(compiled_output):
    """Middleware basic properties must be accessible after migration."""
    assert "mw_name" in compiled_output, (
        f"mw_name key missing from output. Keys present: {sorted(compiled_output.keys())}"
    )
    assert compiled_output["mw_name"] == "auth"
    assert compiled_output["mw_priority"] == 10
    assert compiled_output["mw_protocol"] == 2
    assert compiled_output["mw_describe"] == "[10] auth"


def test_middleware_mutation_tracking(compiled_output):
    """Critical: TrackedComponent mutations must be recorded via getter/setter.

    This test catches naive parameter property migration that uses field
    declarations instead of 'declare' — field declarations with
    useDefineForClassFields:true shadow the base class getter/setters,
    silently breaking mutation tracking.
    """
    assert "mw_mutation_count" in compiled_output, (
        f"mw_mutation_count key missing. Keys present: {sorted(compiled_output.keys())}"
    )
    assert compiled_output["mw_mutation_count"] == 2, (
        "Expected 2 mutations from constructor property assignments; "
        "got %d — field declarations may be shadowing TrackedComponent's "
        "getter/setters" % compiled_output["mw_mutation_count"]
    )
    mutations = compiled_output["mw_mutations"]
    assert len(mutations) == 2
    assert mutations[0] == {"prop": "name", "from": None, "to": "auth"}
    assert mutations[1] == {"prop": "priority", "from": None, "to": 10}


def test_middleware_post_update_tracking(compiled_output):
    """Post-construction property mutations must also be tracked."""
    assert "mw_initial_mutations" in compiled_output, (
        f"mw_initial_mutations key missing. Keys present: {sorted(compiled_output.keys())}"
    )
    assert compiled_output["mw_initial_mutations"] == 2, (
        "Expected 2 initial mutations from constructor"
    )
    assert compiled_output["mw_after_update_mutations"] == 4, (
        "Expected 4 total mutations (2 from constructor + 2 from updates); "
        "got %d" % compiled_output["mw_after_update_mutations"]
    )
    assert compiled_output["mw_after_update_name"] == "test-v2"
    assert compiled_output["mw_after_update_priority"] == 99


def test_middleware_factory_and_sort(compiled_output):
    """Middleware.create() and Middleware.sortByPriority() must work."""
    assert "mw2_mutation_count" in compiled_output, (
        f"mw2_mutation_count key missing. Keys present: {sorted(compiled_output.keys())}"
    )
    assert compiled_output["mw2_mutation_count"] == 2
    assert compiled_output["mw_sorted_names"] == ["logging", "auth", "compress"]
    assert compiled_output["mw_sorted_priorities"] == [5, 10, 15]


# --------------- Registry runtime behavior tests ---------------


def test_registry(compiled_output):
    """Registry namespace, import alias, and parameter property replacements."""
    assert compiled_output["registry_name"] == "main"
    assert compiled_output["registry_count"] == 1
    assert compiled_output["registry_entry"] == {
        "name": "api",
        "protocol": 2,
        "messageTypes": ["REQ", "RES"],
    }
    assert compiled_output["registry_pool_max"] == 3


# --------------- Output completeness test ---------------


def test_output_completeness(compiled_output):
    """All expected keys must be present in output."""
    expected_keys = [
        "protocol_name_1",
        "protocol_name_2",
        "protocol_name_4",
        "is_secure_http",
        "is_secure_https",
        "is_secure_wss",
        "protocol_names",
        "msg_type_request",
        "msg_type_response",
        "flags_value",
        "has_compressed",
        "has_signed",
        "all_flags",
        "log_debug",
        "log_error",
        "log_debug_name",
        "log_info_name",
        "log_is_numeric_debug",
        "log_is_numeric_error",
        "conn_host",
        "conn_port",
        "conn_protocol",
        "conn_compressed",
        "conn_encrypted",
        "conn_describe",
        "pool_max",
        "pool_size_0",
        "pool_size_1",
        "mw_name",
        "mw_priority",
        "mw_protocol",
        "mw_mutations",
        "mw_mutation_count",
        "mw_describe",
        "mw_sorted_names",
        "mw_sorted_priorities",
        "mw2_mutation_count",
        "mw_initial_mutations",
        "mw_after_update_mutations",
        "mw_after_update_name",
        "mw_after_update_priority",
        "registry_name",
        "registry_count",
        "registry_entry",
        "registry_pool_max",
    ]
    missing = [k for k in expected_keys if k not in compiled_output]
    assert not missing, f"Missing keys in output: {missing}"
