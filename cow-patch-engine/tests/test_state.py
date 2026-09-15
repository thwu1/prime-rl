
import subprocess
import json
import pytest


@pytest.fixture(scope="session")
def test_results():
    proc = subprocess.run(
        ["node", "/tests/test_runner.js"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd="/app",
    )
    if proc.returncode != 0:
        pytest.fail(
            f"Test runner crashed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(
            f"Invalid JSON output:\n{proc.stdout}\nstderr: {proc.stderr}"
        )


def test_module_loads(test_results):
    assert (
        "_module_load" not in test_results
    ), test_results.get("_module_load", {}).get("error", "unknown error")


TEST_NAMES = [
    "basic_modify",
    "no_change_identity",
    "structural_sharing_partial",
    "base_immutable",
    "auto_freeze",
    "nested_modify",
    "array_push",
    "array_splice",
    "delete_property",
    "deep_structural_sharing",
    "set_undefined_new",
    "set_existing_undefined_noop",
    "recipe_return_value",
    "array_index_assign",
    "patches_simple",
    "patches_nested",
    "patches_add",
    "patches_remove",
    "patches_array_push",
    "patches_array_index",
    "inverse_patches_restore",
    "patches_replayable",
    "apply_patches_map",
    "apply_patches_set",
    "apply_patches_map_delete",
    "prototype_pollution_blocked",
    "prototype_pollution_constructor",
    "patch_values_cloned",
]


@pytest.mark.parametrize("test_name", TEST_NAMES)
def test_behavior(test_results, test_name):
    assert test_name in test_results, f"Test '{test_name}' not found in results"
    result = test_results[test_name]
    assert result["pass"], f"Test '{test_name}' failed: {result.get('error', 'unknown error')}"
