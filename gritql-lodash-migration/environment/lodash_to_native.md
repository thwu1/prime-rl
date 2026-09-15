---
title: Migrate Lodash to native JavaScript
tags: [js, migration, lodash]
---

Convert Lodash utility function calls to their native JavaScript equivalents and clean up unused lodash imports.

The pattern must handle two phases:
1. Transform all recognized `_.method()` calls to their native JavaScript equivalents
2. Conditionally remove `import _ from 'lodash'` or `const _ = require('lodash')` only when ALL `_.*` member expressions in a file have been eliminated by phase 1. When untransformable calls remain (e.g. `_.debounce`), the import must be preserved.

```grit
engine marzano(0.1)
language js

// TODO: Implement the lodash-to-native migration pattern
// This placeholder does nothing useful — replace it entirely.
// You may create additional pattern files in .grit/patterns/ for composition.
`_.placeholder_that_matches_nothing()` => `noop()`
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
