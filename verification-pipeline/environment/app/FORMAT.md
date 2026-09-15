# seL4 L4V Regression Test Specification Format

## Overview

The XML test specification files define tests and their dependencies for the
seL4 formal verification regression framework. Multiple XML files can define
tests, and tests in one file may reference tests from other files as
dependencies.

## Elements

### `<testsuite>`
Root element. Functions as an unordered grouping of tests (identical semantics
to `<set>`).

### `<set>`
Unordered grouping. All children are independent of each other within the set.
If one test fails, others still run.

### `<sequence>`
Ordered grouping. Tests are processed in document order. Each test implicitly
depends on **all** tests that appear before it in the same sequence. If one
fails, remaining tests are skipped.

### `<test>`
A single test. Must have a `name` attribute (unique across all files). Text
content is the shell command to run.

## Attributes

These attributes may appear on any element (`testsuite`, `set`, `sequence`,
`test`):

- **`cpu-timeout`** *(float)*: CPU-time timeout in seconds. When specified on a
  group element, inherited by all descendant tests as a default value. A
  descendant element's `cpu-timeout` **overrides** (replaces) the inherited
  value.

- **`depends`** *(space-separated string)*: Names of tests that must complete
  successfully before this test or group can run. When specified on a group
  element, all descendant tests inherit these dependencies. Dependencies are
  **cumulative** — an inner `depends` adds to (unions with) the outer depends,
  never replaces it.

- **`cwd`** *(string)*: Working directory (informational; not relevant for
  dependency analysis).

## Dependency Rules

1. **Explicit dependencies** (`depends` attribute): Listed tests must complete
   successfully before this test can start.

2. **Inherited dependencies**: Group-level `depends` are inherited by all tests
   within that group. Nested groups accumulate dependencies from all ancestor
   groups.

3. **Sequence ordering**: In a `<sequence>`, each test implicitly depends on
   all preceding tests in that sequence. This is additive with any inherited or
   explicit dependencies. Concretely: after processing each child in a
   sequence, its name is added to the dependency set inherited by subsequent
   children.

4. **Cross-file references**: A test's `depends` may reference tests defined in
   any other specification file.
