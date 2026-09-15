
"use strict";

const results = {};

function test(name, fn) {
  try {
    fn();
    results[name] = { pass: true };
  } catch (e) {
    results[name] = { pass: false, error: String(e.message || e) };
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "Assertion failed");
}

function deepEqual(a, b) {
  if (Object.is(a, b)) return true;
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object")
    return false;
  if (a instanceof Map && b instanceof Map) {
    if (a.size !== b.size) return false;
    for (const [k, v] of a)
      if (!b.has(k) || !deepEqual(v, b.get(k))) return false;
    return true;
  }
  if (a instanceof Set && b instanceof Set) {
    if (a.size !== b.size) return false;
    for (const v of a) if (!b.has(v)) return false;
    return true;
  }
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => deepEqual(a[k], b[k]));
}

function assertEqual(a, b, msg) {
  if (!deepEqual(a, b)) {
    throw new Error(
      msg ||
        "Expected " + JSON.stringify(b) + " but got " + JSON.stringify(a)
    );
  }
}

// Load module
let m;
try {
  m = require("/app/dist/index");
} catch (e) {
  console.log(
    JSON.stringify({
      _module_load: {
        pass: false,
        error: "Module load failed: " + e.message,
      },
    })
  );
  process.exit(0);
}

const { produce, produceWithPatches, applyPatches } = m;

// === Core produce tests ===

test("basic_modify", () => {
  const base = { x: 1, y: 2 };
  const result = produce(base, (d) => {
    d.x = 10;
  });
  assert(result.x === 10, "x should be 10, got " + result.x);
  assert(result.y === 2, "y should be 2");
  assert(result !== base, "result should be different reference from base");
});

test("no_change_identity", () => {
  const base = { x: 1, y: { z: 2 } };
  const result = produce(base, (d) => {
    /* no changes */
  });
  assert(result === base, "should return same reference when no changes");
});

test("structural_sharing_partial", () => {
  const base = { a: { b: 1 }, c: { d: 2 } };
  const result = produce(base, (d) => {
    d.a.b = 10;
  });
  assert(result !== base, "result should differ from base");
  assert(result.a !== base.a, "modified subtree should be different");
  assert(result.c === base.c, "unmodified subtree should share identity");
  assert(result.a.b === 10, "modified value should be updated");
});

test("base_immutable", () => {
  const base = { x: { y: 1 } };
  const result = produce(base, (d) => {
    d.x.y = 99;
  });
  assert(base.x.y === 1, "base should not be mutated");
  assert(result.x.y === 99, "result should have new value");
});

test("auto_freeze", () => {
  const base = { x: 1, nested: { y: 2 } };
  const result = produce(base, (d) => {
    d.x = 2;
    d.nested.y = 3;
  });
  assert(Object.isFrozen(result), "result should be frozen");
  assert(Object.isFrozen(result.nested), "nested result should be frozen");
});

test("nested_modify", () => {
  const base = { a: { b: { c: 1 } } };
  const result = produce(base, (d) => {
    d.a.b.c = 42;
  });
  assert(result.a.b.c === 42, "deep nested value should be 42");
  assert(result !== base, "result !== base");
  assert(result.a !== base.a, "result.a !== base.a");
  assert(result.a.b !== base.a.b, "result.a.b !== base.a.b");
});

test("array_push", () => {
  const base = { items: [1, 2, 3] };
  const result = produce(base, (d) => {
    d.items.push(4);
  });
  assertEqual(result.items, [1, 2, 3, 4], "items should have 4 appended");
  assert(result !== base, "result !== base");
  assertEqual(base.items, [1, 2, 3], "base should not be mutated");
});

test("array_splice", () => {
  const base = [1, 2, 3, 4];
  const result = produce(base, (d) => {
    d.splice(1, 2);
  });
  assertEqual(result, [1, 4], "splice should remove elements");
  assertEqual(base, [1, 2, 3, 4], "base should not be mutated");
});

test("delete_property", () => {
  const base = { x: 1, y: 2 };
  const result = produce(base, (d) => {
    delete d.x;
  });
  assert(!("x" in result), "x should be deleted from result");
  assert(result.y === 2, "y should remain");
  assert("x" in base, "base should not be mutated");
});

test("deep_structural_sharing", () => {
  const base = {
    a: { x: 1 },
    b: { y: 2 },
    c: { z: { w: 3 } },
  };
  const result = produce(base, (d) => {
    d.a.x = 10;
  });
  assert(result.b === base.b, "b should share identity");
  assert(result.c === base.c, "c should share identity");
});

test("set_undefined_new", () => {
  const base = {};
  const result = produce(base, (d) => {
    d.x = undefined;
  });
  assert(result !== base, "should create new ref for new undefined prop");
  assert("x" in result, "x should exist");
  assert(result.x === undefined, "x should be undefined");
});

test("set_existing_undefined_noop", () => {
  const base = { x: undefined };
  const result = produce(base, (d) => {
    d.x = undefined;
  });
  assert(
    result === base,
    "setting existing undefined to undefined should be noop"
  );
});

test("recipe_return_value", () => {
  const base = { x: 1 };
  const result = produce(base, (d) => {
    return { x: 2, y: 3 };
  });
  assertEqual(result, { x: 2, y: 3 }, "should use returned value");
});

test("array_index_assign", () => {
  const base = [1, 2, 3];
  const result = produce(base, (d) => {
    d[1] = 20;
  });
  assertEqual(result, [1, 20, 3], "index assignment should work");
});

// === Patch generation tests ===

test("patches_simple", () => {
  const base = { x: 3 };
  const [result, patches, inversePatches] = produceWithPatches(base, (d) => {
    d.x = 4;
  });
  assert(result.x === 4, "result.x should be 4");
  assertEqual(patches, [{ op: "replace", path: ["x"], value: 4 }]);
  assertEqual(inversePatches, [{ op: "replace", path: ["x"], value: 3 }]);
});

test("patches_nested", () => {
  const base = { x: { y: 4 } };
  const [result, patches, inversePatches] = produceWithPatches(base, (d) => {
    d.x.y = 5;
  });
  assert(result.x.y === 5, "result.x.y should be 5");
  assertEqual(patches, [{ op: "replace", path: ["x", "y"], value: 5 }]);
  assertEqual(inversePatches, [
    { op: "replace", path: ["x", "y"], value: 4 },
  ]);
});

test("patches_add", () => {
  const base = { x: 1 };
  const [result, patches, inversePatches] = produceWithPatches(base, (d) => {
    d.y = 2;
  });
  assert(result.y === 2, "result.y should be 2");
  assertEqual(patches, [{ op: "add", path: ["y"], value: 2 }]);
  assertEqual(inversePatches, [{ op: "remove", path: ["y"] }]);
});

test("patches_remove", () => {
  const base = { x: 1, y: 2 };
  const [result, patches, inversePatches] = produceWithPatches(base, (d) => {
    delete d.x;
  });
  assert(!("x" in result), "x should not be in result");
  assertEqual(patches, [{ op: "remove", path: ["x"] }]);
  assertEqual(inversePatches, [{ op: "add", path: ["x"], value: 1 }]);
});

test("patches_array_push", () => {
  const base = { items: [1, 2] };
  const [result, patches] = produceWithPatches(base, (d) => {
    d.items.push(3);
  });
  assertEqual(result.items, [1, 2, 3], "result should have pushed element");
  const addPatch = patches.find(
    (p) =>
      p.op === "add" &&
      p.path.length === 2 &&
      p.path[0] === "items"
  );
  assert(addPatch, "should have add patch for new array element");
  assert(addPatch.value === 3, "add patch value should be 3");
});

test("patches_array_index", () => {
  const base = [10, 20, 30];
  const [result, patches, inversePatches] = produceWithPatches(base, (d) => {
    d[1] = 99;
  });
  assertEqual(result, [10, 99, 30]);
  const rp = patches.find((p) => p.op === "replace");
  assert(rp, "should have replace patch");
  assert(rp.value === 99, "replace value should be 99");
  const irp = inversePatches.find((p) => p.op === "replace");
  assert(irp, "should have inverse replace patch");
  assert(irp.value === 20, "inverse replace value should be 20");
});

test("inverse_patches_restore", () => {
  const base = { x: 1, y: { z: 2 } };
  const [result, patches, inversePatches] = produceWithPatches(base, (d) => {
    d.x = 10;
    d.y.z = 20;
  });
  assertEqual(result, { x: 10, y: { z: 20 } }, "result should match");
  const restored = applyPatches({ x: 10, y: { z: 20 } }, inversePatches);
  assertEqual(restored, { x: 1, y: { z: 2 } }, "inverse should restore base");
});

test("patches_replayable", () => {
  const base = { x: 1, y: { z: 2 } };
  const [result, patches] = produceWithPatches(base, (d) => {
    d.x = 10;
    d.y.z = 20;
  });
  const replayed = applyPatches({ x: 1, y: { z: 2 } }, patches);
  assertEqual(replayed, result, "replayed patches should match result");
});

// === applyPatches tests ===

test("apply_patches_map", () => {
  const base = new Map([["x", 1]]);
  const result = applyPatches(base, [
    { op: "replace", path: ["x"], value: 2 },
    { op: "add", path: ["y"], value: 3 },
  ]);
  assert(result instanceof Map, "result should be a Map");
  assert(result.get("x") === 2, "x should be 2");
  assert(result.get("y") === 3, "y should be 3");
  assert(result !== base, "should not mutate base");
  assert(base.get("x") === 1, "base.x should still be 1");
});

test("apply_patches_set", () => {
  const base = new Set([1, 2, 3]);
  const result = applyPatches(base, [
    { op: "add", path: [0], value: 4 },
    { op: "remove", path: [0], value: 1 },
  ]);
  assert(result instanceof Set, "result should be a Set");
  assert(result.has(4), "should have added value 4");
  assert(!result.has(1), "should have removed value 1");
  assert(result.has(2), "should still have 2");
  assert(result.has(3), "should still have 3");
});

test("apply_patches_map_delete", () => {
  const base = new Map([
    ["a", 1],
    ["b", 2],
  ]);
  const result = applyPatches(base, [{ op: "remove", path: ["a"] }]);
  assert(result instanceof Map, "result should be a Map");
  assert(!result.has("a"), "a should be removed");
  assert(result.get("b") === 2, "b should remain");
});

test("prototype_pollution_blocked", () => {
  let threw = false;
  try {
    applyPatches({}, [
      { op: "add", path: ["__proto__", "polluted"], value: true },
    ]);
  } catch (e) {
    threw = true;
  }
  assert(threw, "should throw on __proto__ in path");
  assert(!{}.polluted, "Object.prototype should not be polluted");
});

test("prototype_pollution_constructor", () => {
  let threw = false;
  try {
    applyPatches({}, [
      { op: "add", path: ["constructor", "polluted"], value: true },
    ]);
  } catch (e) {
    threw = true;
  }
  assert(threw, "should throw on constructor in path");
});

test("patch_values_cloned", () => {
  const base = { items: [1] };
  const [result, patches] = produceWithPatches(base, (d) => {
    d.items = [2, 3];
  });
  // Mutate the patch value array
  if (patches[0] && patches[0].value) {
    patches[0].value.push(99);
  }
  assertEqual(result.items, [2, 3], "result should not be affected by patch mutation");
});

console.log(JSON.stringify(results));
