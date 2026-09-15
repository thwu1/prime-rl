A Python simulation at `/app/reference.py` attempts to replicate the exact numerical behavior of embedded LED controller firmware — both the original C implementation (`/app/firmware/c/`) and its Rust rewrite (`/app/firmware/rust/`). The simulation contains multiple correctness bugs where its computations diverge from what the firmware source code actually specifies.

Audit the simulation against the firmware source code and deliver:

- `/app/corrected.py` — a fixed version preserving the same module-level API (all class names, method signatures, and the `analyze_divergences` function must remain unchanged)
- `/app/audit_report.json` — a JSON array documenting each bug found; every element must have keys: `bug_id` (string identifier), `location` (function name in reference.py), `description` (what the code does wrong), `impact` (how outputs differ from correct firmware behavior)

The corrected simulation must faithfully match the firmware source code's behavior for all inputs. Compiling and running small C test programs may help verify exact arithmetic semantics where language-level behavior is ambiguous.