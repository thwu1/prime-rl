A hierarchical state machine (HSM) engine skeleton is at `/app/`. The header `/app/hsm.h` defines the complete interface for a UML statechart engine where states are C function pointers responding to reserved signals (entry, exit, init, superstate-query) and user-defined signals. The implementation file `/app/hsm.c` provides the constructor, root handler, and trace infrastructure. Three core engine functions are unimplemented: `hsm_init()`, `hsm_dispatch()`, and `hsm_is_in()`.

The engine must implement correct UML statechart transition semantics including: superstate hierarchy traversal via dynamic signal-based queries, Lowest Common Ancestor computation for arbitrary state pairs, ordered exit/entry action sequencing, self-transitions with exit-then-reentry, transitions to composite states requiring initial-pseudostate drill-down chains, transitions to ancestor states requiring substate re-initialization, and guard-condition failures (`HSM_UNHANDLED`) that propagate events upward through the hierarchy to be retried by ancestor handlers.

Four test programs verify correctness across distinct topologies:
- `/app/main.c` + `/app/test_sm.c` — 10 tests over a 4-level, 10-state hierarchy exercising cross-hierarchy transitions, event bubbling, self-transitions, and ancestor re-initialization
- `/tests/test_main2.c` + `/tests/test_sm2.c` — 6 tests over an independent 3-level topology
- `/tests/test_main3.c` + `/tests/test_sm3.c` — 8 tests exercising `HSM_UNHANDLED` guard conditions with fallback propagation to ancestor handlers
- `/tests/test_is_in.c` — 14 assertions verifying `hsm_is_in()` state-containment queries and post-query dispatch integrity

All tests across all four programs must pass with zero failures. The implementation must be memory-safe: zero Valgrind memcheck errors and clean execution under GCC AddressSanitizer and UndefinedBehaviorSanitizer. No build system is provided.