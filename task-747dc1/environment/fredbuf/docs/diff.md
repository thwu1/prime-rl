# Diff API

**Header**: `fredbuf/myers_diff.h`
**Namespace**: `fredbuf`

## Struct: `DiffHunk`

Represents a single unit of difference between two texts.

```cpp
struct DiffHunk {
    enum Op { Insert, Delete, Equal };
    Op op;
    std::string line;    // the line content (without trailing newline)
    int old_lineno;      // line number in old text (-1 if Insert)
    int new_lineno;      // line number in new text (-1 if Delete)
};
```

## Function: `myers_diff`

```cpp
std::vector<DiffHunk> myers_diff(
    const std::string& old_text,
    const std::string& new_text
);
```

Computes the shortest edit script between `old_text` and `new_text`,
operating on lines. Returns a sequence of `DiffHunk` values.

### Behavioral Contract

- Equal hunks use the line from `old_text`.
- Concatenating all `Equal` and `Delete` hunk lines (with newlines) must
  reconstruct `old_text`.
- Concatenating all `Equal` and `Insert` hunk lines (with newlines) must
  reconstruct `new_text`.
- Identical inputs produce only `Equal` hunks.
- Empty old text with non-empty new text produces only `Insert` hunks.
- Empty new text with non-empty old text produces only `Delete` hunks.
