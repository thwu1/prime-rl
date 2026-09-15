The Lean 4 project at `/app/` defines custom recursive list operations (`myAppend`, `myReverse`, `myLength`, `myMap`, `myFilter`) and states 8 correctness theorems about them in `/app/VerifiedListOps.lean`. All theorem bodies currently contain `sorry` placeholders, and the project has additional issues that prevent successful proof compilation.

Get the project to a state where `lake build` completes with exit code 0, produces no `sorry`-related warnings, and no theorem depends on the `sorryAx` axiom. The five function definitions must remain unchanged. You may need to diagnose and fix project issues beyond filling in proof terms.

The Lean 4 toolchain (`lean`, `lake`) is pre-installed and the project dependencies are cached.