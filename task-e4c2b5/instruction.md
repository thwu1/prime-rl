Complete the implementation of `lockfree::spsc::BipartiteBuf<T, N>` at `/app/include/bipartite_buf.hpp`.

The file contains a class template skeleton with empty method bodies (`WriteAcquire`, `WriteRelease`, `ReadAcquire`, `ReadRelease`). The specification defining the required behavior and correctness constraints is at `/app/spec.md`.

Your implementation must:

- Be correct under concurrent use by exactly one producer thread and one consumer thread
- Pass the provided C++ test suite, including multi-threaded stress tests
- Be ThreadSanitizer clean (no data races)