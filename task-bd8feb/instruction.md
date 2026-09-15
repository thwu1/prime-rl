A Rust project at `/app/` implements a dynamic forest query engine using Link-Cut Trees. The project compiles and correctly handles `link`, `cut`, and `path_sum` operations, but the remaining operations specified in `/app/problem.md` are not implemented: `path_max`, `path_min`, `add` (range add on a path), and `update` (point set). These require adding lazy propagation with additive tags and min/max aggregate tracking to the existing splay-tree-based LCT.

There is also at least one latent bug in the existing code that will cause incorrect results once the new operations are exercised alongside `cut`.

Implement all missing operations so the program passes the sample tests in `/app/data/`. Verify with:

    cd /app && cargo build --release 2>&1 && ./target/release/forest_query < data/sample1.in | diff - data/sample1.out

```
```