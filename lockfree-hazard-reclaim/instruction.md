`/app/lockfree_stack.hpp` contains a lock-free Treiber stack that leaks memory — popped nodes are never freed because deleting them while other threads may hold stale references causes use-after-free.

Modify `/app/lockfree_stack.hpp` to:

1. **Add hazard pointer-based memory reclamation.** Implement the full hazard pointer protocol: each thread claims a hazard pointer slot, sets it before accessing a node, verifies the node hasn't been reclaimed, and clears it afterward. Nodes removed from the stack are either deleted immediately (if no hazard pointer protects them) or placed on a retire list for deferred reclamation.

2. **Add `std::optional<T> try_pop()`** that returns `std::nullopt` when the stack is empty instead of throwing.

3. **Optimize memory ordering.** Replace default sequential consistency with acquire-release semantics where safe. Identify which operations in the hazard pointer protocol *require* sequential consistency for correctness (hint: the HP-store / head-reread pair needs a total order to prevent a race between setting a hazard pointer and another thread scanning for protected nodes).

4. **Ensure complete cleanup.** The destructor must free all remaining nodes on the stack and all nodes deferred in the retire list.

The result must be a single header-only `.hpp` file that compiles with `g++ -std=c++20 -pthread` and is correct under 16+ concurrent threads performing interleaved push/pop operations.