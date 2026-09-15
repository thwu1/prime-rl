import subprocess
import json
import pytest
import os


RUNNER_CODE = r"""
import {
  toRFC6902,
  fromRFC6902,
  compressPatches,
  detectConflicts,
  rebasePatches,
  pathsEqual,
  isPathPrefix,
  isPathPrefixStrict,
  applyPatches,
  invertPatches,
} from "./src/patch-engine.js";

type PathSegment = string | number;
type Result = { pass: boolean; expected: any; actual: any };
const results: Record<string, Result> = {};

function deepEqual(a: any, b: any): boolean {
  if (a === b) return true;
  if (a === null || b === null) return a === b;
  if (a === undefined || b === undefined) return a === b;
  if (typeof a !== typeof b) return false;
  if (typeof a !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    if (a.length !== b.length) return false;
    return a.every((v: any, i: number) => deepEqual(v, b[i]));
  }
  const keysA = Object.keys(a).sort();
  const keysB = Object.keys(b).sort();
  if (keysA.length !== keysB.length) return false;
  if (keysA.some((k, i) => k !== keysB[i])) return false;
  return keysA.every((k) => deepEqual(a[k], b[k]));
}

function test(name: string, fn: () => { expected: any; actual: any }) {
  try {
    const { expected, actual } = fn();
    results[name] = { pass: deepEqual(expected, actual), expected, actual };
  } catch (e: any) {
    results[name] = { pass: false, expected: "no error", actual: e.message };
  }
}

// ===== RFC-6902 Conversion Tests =====

test("rfc6902_basic_path", () => {
  const rfc = toRFC6902([{ op: "replace", path: ["x", "y"], value: 5 }]);
  return { expected: "/x/y", actual: rfc[0].path };
});

test("rfc6902_numeric_path", () => {
  const rfc = toRFC6902([{ op: "add", path: ["arr", 0], value: "hello" }]);
  return { expected: "/arr/0", actual: rfc[0].path };
});

test("rfc6902_escape_tilde", () => {
  const rfc = toRFC6902([{ op: "replace", path: ["a~b"], value: 1 }]);
  return { expected: "/a~0b", actual: rfc[0].path };
});

test("rfc6902_escape_slash", () => {
  const rfc = toRFC6902([{ op: "replace", path: ["a/b"], value: 1 }]);
  return { expected: "/a~1b", actual: rfc[0].path };
});

test("rfc6902_escape_tilde_slash", () => {
  const rfc = toRFC6902([{ op: "replace", path: ["~/"], value: 1 }]);
  return { expected: "/~0~1", actual: rfc[0].path };
});

test("rfc6902_escape_slash_tilde", () => {
  const rfc = toRFC6902([{ op: "replace", path: ["/~"], value: 1 }]);
  return { expected: "/~1~0", actual: rfc[0].path };
});

test("rfc6902_unescape_tilde_digit", () => {
  const patches = fromRFC6902([{ op: "replace", path: "/~01", value: 1 }]);
  return { expected: ["~1"], actual: patches[0].path };
});

test("rfc6902_roundtrip", () => {
  const original = [
    { op: "replace" as const, path: ["a~1b" as PathSegment, 0 as PathSegment], value: { x: 1 } },
    { op: "add" as const, path: ["~0" as PathSegment, "c/d" as PathSegment], value: "test" },
  ];
  const rfc = toRFC6902(original);
  const back = fromRFC6902(rfc);
  return {
    expected: original.map((p) => p.path),
    actual: back.map((p) => p.path),
  };
});

test("rfc6902_root_empty", () => {
  const patches = fromRFC6902([{ op: "replace", path: "", value: 42 }]);
  return { expected: [] as PathSegment[], actual: patches[0].path };
});

test("rfc6902_root_slash", () => {
  const patches = fromRFC6902([{ op: "replace", path: "/", value: 43 }]);
  return { expected: [""], actual: patches[0].path };
});

// ===== Path Utility Tests =====

test("path_prefix_strict_types", () => {
  const result = isPathPrefix([0], ["0", "x"]);
  return { expected: false, actual: result };
});

test("path_prefix_number_match", () => {
  const result = isPathPrefix([0], [0, "x"]);
  return { expected: true, actual: result };
});

test("paths_equal_type_sensitivity", () => {
  const result = pathsEqual([0], ["0"]);
  return { expected: false, actual: result };
});

// ===== Compression Tests =====

test("compress_replace_replace", () => {
  const compressed = compressPatches([
    { op: "replace", path: ["x"], value: 1 },
    { op: "replace", path: ["x"], value: 2 },
  ]);
  return {
    expected: [{ op: "replace", path: ["x"], value: 2 }],
    actual: compressed,
  };
});

test("compress_add_remove_cancel", () => {
  const compressed = compressPatches([
    { op: "add", path: ["x"], value: 1 },
    { op: "remove", path: ["x"] },
  ]);
  return { expected: [] as any[], actual: compressed };
});

test("compress_add_replace", () => {
  const compressed = compressPatches([
    { op: "add", path: ["x"], value: 1 },
    { op: "replace", path: ["x"], value: 2 },
  ]);
  return {
    expected: [{ op: "add", path: ["x"], value: 2 }],
    actual: compressed,
  };
});

test("compress_remove_add", () => {
  const compressed = compressPatches([
    { op: "remove", path: ["x"] },
    { op: "add", path: ["x"], value: 5 },
  ]);
  return {
    expected: [{ op: "replace", path: ["x"], value: 5 }],
    actual: compressed,
  };
});

test("compress_parent_remove_cleans_children", () => {
  const compressed = compressPatches([
    { op: "replace", path: ["a", "b"], value: 1 },
    { op: "add", path: ["a", "c"], value: 2 },
    { op: "remove", path: ["a"] },
  ]);
  return {
    expected: [{ op: "remove", path: ["a"] }],
    actual: compressed,
  };
});

test("compress_parent_remove_preserves_siblings", () => {
  const compressed = compressPatches([
    { op: "replace", path: ["a", "b"], value: 1 },
    { op: "replace", path: ["x"], value: 2 },
    { op: "remove", path: ["a"] },
  ]);
  return {
    expected: [
      { op: "replace", path: ["x"], value: 2 },
      { op: "remove", path: ["a"] },
    ],
    actual: compressed,
  };
});

// ===== Conflict Detection Tests =====

test("conflicts_exact_write_write", () => {
  const conflicts = detectConflicts(
    [{ op: "replace", path: ["x"], value: 1 }],
    [{ op: "replace", path: ["x"], value: 2 }]
  );
  return { expected: 1, actual: conflicts.length };
});

test("conflicts_exact_write_write_type", () => {
  const conflicts = detectConflicts(
    [{ op: "replace", path: ["x"], value: 1 }],
    [{ op: "replace", path: ["x"], value: 2 }]
  );
  return { expected: "write-write", actual: conflicts[0]?.type };
});

test("conflicts_ancestor_delete_write", () => {
  const conflicts = detectConflicts(
    [{ op: "remove", path: ["x"] }],
    [{ op: "replace", path: ["x", "y"], value: 1 }]
  );
  return { expected: 1, actual: conflicts.length };
});

test("conflicts_ancestor_delete_write_type", () => {
  const conflicts = detectConflicts(
    [{ op: "remove", path: ["x"] }],
    [{ op: "replace", path: ["x", "y"], value: 1 }]
  );
  return { expected: "delete-write", actual: conflicts[0]?.type };
});

test("conflicts_descendant_write_delete", () => {
  const conflicts = detectConflicts(
    [{ op: "replace", path: ["x", "y"], value: 1 }],
    [{ op: "remove", path: ["x"] }]
  );
  return { expected: 1, actual: conflicts.length };
});

test("conflicts_descendant_write_delete_type", () => {
  const conflicts = detectConflicts(
    [{ op: "replace", path: ["x", "y"], value: 1 }],
    [{ op: "remove", path: ["x"] }]
  );
  return { expected: "write-delete", actual: conflicts[0]?.type };
});

test("conflicts_no_conflict_disjoint", () => {
  const conflicts = detectConflicts(
    [{ op: "replace", path: ["x"], value: 1 }],
    [{ op: "replace", path: ["y"], value: 2 }]
  );
  return { expected: 0, actual: conflicts.length };
});

// ===== Rebase Tests =====

test("rebase_remove_drops_patch", () => {
  const rebased = rebasePatches(
    [{ op: "replace", path: ["x"], value: 1 }],
    [{ op: "remove", path: ["x"] }]
  );
  return { expected: 0, actual: rebased.length };
});

test("rebase_array_add_shifts_index_up", () => {
  const rebased = rebasePatches(
    [{ op: "replace", path: ["arr", 3], value: "updated" }],
    [{ op: "add", path: ["arr", 1], value: "inserted" }]
  );
  return { expected: ["arr", 4], actual: rebased[0]?.path };
});

test("rebase_array_remove_shifts_index_down", () => {
  const rebased = rebasePatches(
    [{ op: "replace", path: ["arr", 3], value: "updated" }],
    [{ op: "remove", path: ["arr", 1] }]
  );
  return { expected: ["arr", 2], actual: rebased[0]?.path };
});

test("rebase_array_remove_same_index_drops", () => {
  const rebased = rebasePatches(
    [{ op: "replace", path: ["arr", 1], value: "updated" }],
    [{ op: "remove", path: ["arr", 1] }]
  );
  return { expected: 0, actual: rebased.length };
});

test("rebase_array_add_no_shift_before", () => {
  const rebased = rebasePatches(
    [{ op: "replace", path: ["arr", 3], value: "updated" }],
    [{ op: "add", path: ["arr", 5], value: "inserted" }]
  );
  return { expected: ["arr", 3], actual: rebased[0]?.path };
});

test("rebase_parent_remove_drops", () => {
  const rebased = rebasePatches(
    [{ op: "replace", path: ["x", "y", "z"], value: 1 }],
    [{ op: "remove", path: ["x"] }]
  );
  return { expected: 0, actual: rebased.length };
});

// ===== Apply Patches Tests =====

test("apply_object_replace", () => {
  const state = { x: { y: 1, z: 2 } };
  const result = applyPatches(state, [{ op: "replace", path: ["x", "y"], value: 99 }]);
  return { expected: { x: { y: 99, z: 2 } }, actual: result };
});

test("apply_object_add", () => {
  const state = { x: 1 };
  const result = applyPatches(state, [{ op: "add", path: ["y"], value: 2 }]);
  return { expected: { x: 1, y: 2 }, actual: result };
});

test("apply_object_remove", () => {
  const state = { x: 1, y: 2 };
  const result = applyPatches(state, [{ op: "remove", path: ["y"] }]);
  return { expected: { x: 1 }, actual: result };
});

test("apply_array_add_splice", () => {
  const state = { arr: [10, 20, 30] };
  const result = applyPatches(state, [{ op: "add", path: ["arr", 1], value: 15 }]);
  return { expected: { arr: [10, 15, 20, 30] }, actual: result };
});

test("apply_array_remove_splice", () => {
  const state = { arr: [10, 20, 30] };
  const result = applyPatches(state, [{ op: "remove", path: ["arr", 1] }]);
  return { expected: { arr: [10, 30] }, actual: result };
});

test("apply_root_replace", () => {
  const state = { x: 1 };
  const result = applyPatches(state, [{ op: "replace", path: [], value: { y: 2 } }]);
  return { expected: { y: 2 }, actual: result };
});

test("apply_no_mutate", () => {
  const state = { x: { y: 1 } };
  const original = JSON.parse(JSON.stringify(state));
  applyPatches(state, [{ op: "replace", path: ["x", "y"], value: 99 }]);
  return { expected: original, actual: state };
});

test("apply_multiple_sequential", () => {
  const state = { items: [1, 2, 3] };
  const result = applyPatches(state, [
    { op: "add", path: ["items", 0], value: 0 },
    { op: "remove", path: ["items", 3] },
  ]);
  return { expected: { items: [0, 1, 2] }, actual: result };
});

test("apply_nested_array_in_object", () => {
  const state = { users: [{ name: "Alice", scores: [1, 2, 3] }] };
  const result = applyPatches(state, [
    { op: "add", path: ["users", 0, "scores", 1], value: 1.5 },
  ]);
  return { expected: { users: [{ name: "Alice", scores: [1, 1.5, 2, 3] }] }, actual: result };
});

// ===== Inverse Patches Tests =====

test("invert_replace", () => {
  const state = { x: 10 };
  const patches = [{ op: "replace" as const, path: ["x" as PathSegment], value: 20 }];
  const inv = invertPatches(patches, state);
  return { expected: [{ op: "replace", path: ["x"], value: 10 }], actual: inv };
});

test("invert_add", () => {
  const state = { x: 1 };
  const patches = [{ op: "add" as const, path: ["y" as PathSegment], value: 2 }];
  const inv = invertPatches(patches, state);
  return { expected: [{ op: "remove", path: ["y"] }], actual: inv };
});

test("invert_remove", () => {
  const state = { x: 1, y: 2 };
  const patches = [{ op: "remove" as const, path: ["y" as PathSegment] }];
  const inv = invertPatches(patches, state);
  return { expected: [{ op: "add", path: ["y"], value: 2 }], actual: inv };
});

test("invert_roundtrip", () => {
  const state = { a: 1, b: { c: 2 }, d: [10, 20] };
  const patches: any[] = [
    { op: "replace", path: ["a"], value: 99 },
    { op: "add", path: ["e"], value: "new" },
    { op: "remove", path: ["b"] },
  ];
  const newState = applyPatches(state, patches);
  const inv = invertPatches(patches, state);
  const recovered = applyPatches(newState, inv);
  return { expected: state, actual: recovered };
});

test("invert_nested_replace", () => {
  const state = { a: { b: { c: 42 } } };
  const patches = [{ op: "replace" as const, path: ["a" as PathSegment, "b" as PathSegment, "c" as PathSegment], value: 100 }];
  const inv = invertPatches(patches, state);
  return { expected: [{ op: "replace", path: ["a", "b", "c"], value: 42 }], actual: inv };
});

test("invert_order_reversed", () => {
  const state = { x: 1, y: 2 };
  const patches: any[] = [
    { op: "replace", path: ["x"], value: 10 },
    { op: "remove", path: ["y"] },
  ];
  const inv = invertPatches(patches, state);
  return { expected: 2, actual: inv.length };
});

test("invert_order_first_op", () => {
  const state = { x: 1, y: 2 };
  const patches: any[] = [
    { op: "replace", path: ["x"], value: 10 },
    { op: "remove", path: ["y"] },
  ];
  const inv = invertPatches(patches, state);
  return { expected: "add", actual: inv[0]?.op };
});

test("invert_roundtrip_array", () => {
  const state = { items: ["a", "b", "c"] };
  const patches: any[] = [
    { op: "add", path: ["items", 1], value: "x" },
  ];
  const newState = applyPatches(state, patches);
  const inv = invertPatches(patches, state);
  const recovered = applyPatches(newState, inv);
  return { expected: state, actual: recovered };
});

console.log(JSON.stringify(results));
"""


@pytest.fixture(scope="session")
def test_results():
    """Install deps, write and run test runner, return results dict."""
    runner_path = "/app/_test_runner.ts"
    with open(runner_path, "w") as f:
        f.write(RUNNER_CODE)

    result = subprocess.run(
        ["npx", "tsx", "_test_runner.ts"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        pytest.fail(
            f"Test runner failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout[:2000]}\n"
            f"stderr: {result.stderr[:2000]}"
        )

    try:
        output = result.stdout.strip()
        lines = output.split("\n")
        json_line = lines[-1]
        return json.loads(json_line)
    except (json.JSONDecodeError, IndexError) as e:
        pytest.fail(f"Invalid JSON output: {result.stdout[:2000]}\nError: {e}")


def _check(test_results, name):
    """Check a single test result from the runner."""
    assert name in test_results, f"Test '{name}' not found in runner results"
    r = test_results[name]
    assert r["pass"], (
        f"Test '{name}' failed:\n"
        f"  expected: {json.dumps(r['expected'])}\n"
        f"  actual:   {json.dumps(r['actual'])}"
    )


# ===== RFC-6902 Conversion Tests =====

def test_rfc6902_basic_path(test_results):
    _check(test_results, "rfc6902_basic_path")

def test_rfc6902_numeric_path(test_results):
    _check(test_results, "rfc6902_numeric_path")

def test_rfc6902_escape_tilde(test_results):
    _check(test_results, "rfc6902_escape_tilde")

def test_rfc6902_escape_slash(test_results):
    _check(test_results, "rfc6902_escape_slash")

def test_rfc6902_escape_tilde_slash(test_results):
    _check(test_results, "rfc6902_escape_tilde_slash")

def test_rfc6902_escape_slash_tilde(test_results):
    _check(test_results, "rfc6902_escape_slash_tilde")

def test_rfc6902_unescape_tilde_digit(test_results):
    _check(test_results, "rfc6902_unescape_tilde_digit")

def test_rfc6902_roundtrip(test_results):
    _check(test_results, "rfc6902_roundtrip")

def test_rfc6902_root_empty(test_results):
    _check(test_results, "rfc6902_root_empty")

def test_rfc6902_root_slash(test_results):
    _check(test_results, "rfc6902_root_slash")


# ===== Path Utility Tests =====

def test_path_prefix_strict_types(test_results):
    _check(test_results, "path_prefix_strict_types")

def test_path_prefix_number_match(test_results):
    _check(test_results, "path_prefix_number_match")

def test_paths_equal_type_sensitivity(test_results):
    _check(test_results, "paths_equal_type_sensitivity")


# ===== Compression Tests =====

def test_compress_replace_replace(test_results):
    _check(test_results, "compress_replace_replace")

def test_compress_add_remove_cancel(test_results):
    _check(test_results, "compress_add_remove_cancel")

def test_compress_add_replace(test_results):
    _check(test_results, "compress_add_replace")

def test_compress_remove_add(test_results):
    _check(test_results, "compress_remove_add")

def test_compress_parent_remove_cleans_children(test_results):
    _check(test_results, "compress_parent_remove_cleans_children")

def test_compress_parent_remove_preserves_siblings(test_results):
    _check(test_results, "compress_parent_remove_preserves_siblings")


# ===== Conflict Detection Tests =====

def test_conflicts_exact_write_write(test_results):
    _check(test_results, "conflicts_exact_write_write")

def test_conflicts_exact_write_write_type(test_results):
    _check(test_results, "conflicts_exact_write_write_type")

def test_conflicts_ancestor_delete_write(test_results):
    _check(test_results, "conflicts_ancestor_delete_write")

def test_conflicts_ancestor_delete_write_type(test_results):
    _check(test_results, "conflicts_ancestor_delete_write_type")

def test_conflicts_descendant_write_delete(test_results):
    _check(test_results, "conflicts_descendant_write_delete")

def test_conflicts_descendant_write_delete_type(test_results):
    _check(test_results, "conflicts_descendant_write_delete_type")

def test_conflicts_no_conflict_disjoint(test_results):
    _check(test_results, "conflicts_no_conflict_disjoint")


# ===== Rebase Tests =====

def test_rebase_remove_drops_patch(test_results):
    _check(test_results, "rebase_remove_drops_patch")

def test_rebase_array_add_shifts_index_up(test_results):
    _check(test_results, "rebase_array_add_shifts_index_up")

def test_rebase_array_remove_shifts_index_down(test_results):
    _check(test_results, "rebase_array_remove_shifts_index_down")

def test_rebase_array_remove_same_index_drops(test_results):
    _check(test_results, "rebase_array_remove_same_index_drops")

def test_rebase_array_add_no_shift_before(test_results):
    _check(test_results, "rebase_array_add_no_shift_before")

def test_rebase_parent_remove_drops(test_results):
    _check(test_results, "rebase_parent_remove_drops")


# ===== Apply Patches Tests =====

def test_apply_object_replace(test_results):
    _check(test_results, "apply_object_replace")

def test_apply_object_add(test_results):
    _check(test_results, "apply_object_add")

def test_apply_object_remove(test_results):
    _check(test_results, "apply_object_remove")

def test_apply_array_add_splice(test_results):
    _check(test_results, "apply_array_add_splice")

def test_apply_array_remove_splice(test_results):
    _check(test_results, "apply_array_remove_splice")

def test_apply_root_replace(test_results):
    _check(test_results, "apply_root_replace")

def test_apply_no_mutate(test_results):
    _check(test_results, "apply_no_mutate")

def test_apply_multiple_sequential(test_results):
    _check(test_results, "apply_multiple_sequential")

def test_apply_nested_array_in_object(test_results):
    _check(test_results, "apply_nested_array_in_object")


# ===== Inverse Patches Tests =====

def test_invert_replace(test_results):
    _check(test_results, "invert_replace")

def test_invert_add(test_results):
    _check(test_results, "invert_add")

def test_invert_remove(test_results):
    _check(test_results, "invert_remove")

def test_invert_roundtrip(test_results):
    _check(test_results, "invert_roundtrip")

def test_invert_nested_replace(test_results):
    _check(test_results, "invert_nested_replace")

def test_invert_order_reversed(test_results):
    _check(test_results, "invert_order_reversed")

def test_invert_order_first_op(test_results):
    _check(test_results, "invert_order_first_op")

def test_invert_roundtrip_array(test_results):
    _check(test_results, "invert_roundtrip_array")
