The file `/app/verified_algorithms.rs` contains a Verus program implementing verified merge sort and binary search over `Vec<u64>`. Running `verus /app/verified_algorithms.rs` currently fails with multiple verification errors.

Verus is installed at `/opt/verus/verus`. The required Rust toolchain is pre-installed.

Your task: modify `/app/verified_algorithms.rs` so that `verus /app/verified_algorithms.rs` completes with zero verification errors (exit code 0). The final file must not contain any `assume(false)` statements. Do not remove or rename any existing functions.