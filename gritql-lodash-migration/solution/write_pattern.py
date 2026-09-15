#!/usr/bin/env python3
"""Write the correct GritQL pattern files for the lodash-to-native migration.

Creates two pattern files:
1. A sub-pattern file with the 19 transformation rules and inline test cases
2. An orchestrator file using sequential composition for import cleanup

This split is necessary because GritQL's sequential patterns are incompatible
with inline test cases (they produce no output for the test runner).

"""
import os

PATTERNS_DIR = "/app/.grit/patterns"

# ── Sub-pattern: transformation rules with inline tests ──────

TRANSFORMS_MD = """---
title: Lodash call transformations
tags: [js, lodash, internal]
---

Transform individual Lodash utility calls to native JavaScript.

```grit
engine marzano(0.1)
language js

or {
    `_.reduce($arr, $fn, $init)` => `$arr.reduce($fn, $init)`,
    `_.reduce($arr, $fn)` => `$arr.reduce($fn)`,
    `_.map($arr, $fn)` => `$arr.map($fn)`,
    `_.filter($arr, $fn)` => `$arr.filter($fn)`,
    `_.find($arr, $fn)` => `$arr.find($fn)`,
    `_.forEach($arr, $fn)` => `$arr.forEach($fn)`,
    `_.some($arr, $fn)` => `$arr.some($fn)`,
    `_.every($arr, $fn)` => `$arr.every($fn)`,
    `_.includes($arr, $val)` => `$arr.includes($val)`,
    `_.keys($obj)` => `Object.keys($obj)`,
    `_.values($obj)` => `Object.values($obj)`,
    `_.entries($obj)` => `Object.entries($obj)`,
    `_.isArray($val)` => `Array.isArray($val)`,
    `_.isNil($val)` => `$val == null`,
    `_.uniq($arr)` => `[...new Set($arr)]`,
    `_.flatten($arr)` => `$arr.flat()`,
    `_.flattenDeep($arr)` => `$arr.flat(Infinity)`,
    `_.compact($arr)` => `$arr.filter(Boolean)`,
    `_.cloneDeep($obj)` => `structuredClone($obj)`
}
```

## Array methods

```js
const names = _.map(users, u => u.name);
const active = _.filter(items, i => i.active);
const item = _.find(list, x => x.id === 5);
```

```js
const names = users.map(u => u.name);
const active = items.filter(i => i.active);
const item = list.find(x => x.id === 5);
```

## Iteration and search

```js
_.forEach(items, item => console.log(item));
const hasFoo = _.includes(arr, 'foo');
const anyValid = _.some(entries, e => e.valid);
const allDone = _.every(tasks, t => t.done);
```

```js
items.forEach(item => console.log(item));
const hasFoo = arr.includes('foo');
const anyValid = entries.some(e => e.valid);
const allDone = tasks.every(t => t.done);
```

## Object utilities

```js
const k = _.keys(config);
const v = _.values(config);
const pairs = _.entries(config);
```

```js
const k = Object.keys(config);
const v = Object.values(config);
const pairs = Object.entries(config);
```

## Type checks

```js
if (_.isArray(data)) {
  console.log('array');
}
if (_.isNil(value)) {
  return fallback;
}
```

```js
if (Array.isArray(data)) {
  console.log('array');
}
if (value == null) {
  return fallback;
}
```

## Collection operations

```js
const unique = _.uniq(items);
const flat = _.flatten(nested);
const deepFlat = _.flattenDeep(deepNested);
const truthy = _.compact(mixed);
const copy = _.cloneDeep(original);
```

```js
const unique = [...new Set(items)];
const flat = nested.flat();
const deepFlat = deepNested.flat(Infinity);
const truthy = mixed.filter(Boolean);
const copy = structuredClone(original);
```

## Reduce with initial value

```js
const sum = _.reduce(numbers, (acc, n) => acc + n, 0);
const total = _.reduce(items, (s, i) => s + i.price);
```

```js
const sum = numbers.reduce((acc, n) => acc + n, 0);
const total = items.reduce((s, i) => s + i.price);
```

## Does not transform non-lodash code

```js
const arr = [1, 2, 3];
const doubled = arr.map(x => x * 2);
const sum = arr.reduce((a, b) => a + b, 0);
```
"""

# ── Orchestrator: sequential transform + conditional import cleanup ──

ORCHESTRATOR_MD = """---
title: Migrate Lodash to native JavaScript
tags: [js, migration, lodash]
---

Orchestrate Lodash migration: transform calls via lodash_call_transforms,
then conditionally remove lodash import/require if no `_.*` usage remains.

```grit
engine marzano(0.1)
language js

sequential {
  maybe bubble file($body) where {
    $body <: contains bubble lodash_call_transforms()
  },
  maybe bubble file($body) where {
    $body <: not contains `_.$_`,
    $body <: contains bubble or {
      `import $_ from 'lodash'` => .,
      `import $_ from "lodash"` => .,
      `const $_ = require('lodash')` => .,
      `const $_ = require("lodash")` => .
    }
  }
}
```
"""


def main():
    os.makedirs(PATTERNS_DIR, exist_ok=True)

    # Read existing lodash_to_native.md to verify we're replacing the placeholder
    main_path = os.path.join(PATTERNS_DIR, "lodash_to_native.md")
    if os.path.exists(main_path):
        with open(main_path) as f:
            old_content = f.read()
        has_placeholder = "placeholder_that_matches_nothing" in old_content
        print(f"Existing lodash_to_native.md: placeholder={'yes' if has_placeholder else 'no'}")

    # Write the sub-pattern file with transformation rules + inline tests
    transforms_path = os.path.join(PATTERNS_DIR, "lodash_call_transforms.md")
    with open(transforms_path, "w") as f:
        f.write(TRANSFORMS_MD.lstrip())
    print(f"Wrote sub-pattern: {transforms_path}")

    # Write the orchestrator file (replaces the placeholder)
    with open(main_path, "w") as f:
        f.write(ORCHESTRATOR_MD.lstrip())
    print(f"Wrote orchestrator: {main_path}")

    # Verify the pattern structure by listing files
    files = os.listdir(PATTERNS_DIR)
    print(f"Pattern files: {files}")

    # Count transformation rules written
    rule_count = TRANSFORMS_MD.count("=>")
    print(f"Transformation rules written: {rule_count}")

    # Count inline test sections
    test_sections = [
        line for line in TRANSFORMS_MD.split("\n")
        if line.startswith("## ")
    ]
    print(f"Inline test sections: {len(test_sections)}")


if __name__ == "__main__":
    main()
