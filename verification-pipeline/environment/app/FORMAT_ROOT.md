# Isabelle ROOT File Format

## Overview

ROOT files define Isabelle proof sessions — named collections of theories
with dependencies on other sessions. Each file may define multiple sessions.

## Syntax

### Comments

ML-style block comments: `(* ... *)`. May span multiple lines. Everything
between `(*` and the matching `*)` is ignored.

### Session Declaration

```
session Name = Parent +
```

Declares a new session named `Name` that extends `Parent`. The parent session
is an implicit dependency. Session names are identifiers containing letters,
digits, underscores, and hyphens.

### Session Blocks

After the session declaration line, indented blocks may follow in any order:

- **`sessions`**: Each subsequent indented line names a required session
  dependency.
  ```
    sessions
      Dep1
      Dep2
  ```

- **`theories`**: Each subsequent indented line names a theory file (in
  double quotes).
  ```
    theories
      "Theory1"
      "Theory2"
  ```

- **`options`**: Build options in brackets on the same or subsequent lines.
  Ignored for dependency analysis.
  ```
    options [timeout = 600, quick_and_dirty]
  ```

- **`directories`**: Additional theory search paths (ignored for dependency
  analysis).

A block ends when:
- A new block keyword (`sessions`, `theories`, `options`, `directories`)
  appears, OR
- A new `session` declaration appears, OR
- End-of-file is reached.

### Whitespace

- Blank lines are ignored.
- Block content lines are indented relative to the block keyword.

## Session Dependencies

A session's direct dependencies are the **union** of:

1. The **parent** session (from `session Name = Parent +`)
2. All sessions listed in the **`sessions`** block

Note: some dependencies reference external sessions (e.g. `Word_Lib`, `HOL`,
`HOL-Eisbach`) that are provided by the Isabelle distribution rather than
defined in these ROOT files.
