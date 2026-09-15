A text search library (`searchidx`) is being incrementally migrated from C to Rust. The Rust tokenizer (`/app/src/tokenizer.rs`) and the C inverted index (`/app/src/c/index.c`) are both correct and must not be modified. The canonical ABI contract is defined in `/app/include/searchidx.h`.

The project currently does not compile. The build system, FFI bridge layer, module declarations, and safe wrapper API all contain defects — some cause compilation or link failures, others produce silent data corruption or memory safety violations at runtime.

Fix all defects so that:

```
cd /app && cargo build && cargo test -- --test-threads=1
```

succeeds with zero failures. The integration tests (`/app/tests/integration_test.rs`) fully specify the expected behavior and public API contract. Do not modify the integration tests, the C source (`index.c`), the C header (`searchidx.h`), or the tokenizer (`tokenizer.rs`).