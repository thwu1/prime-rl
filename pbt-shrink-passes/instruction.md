A property-based testing library at `/app/pbt.py` implements test case generation and shrinking for automated testing. The shrinking engine minimizes failing test cases under the shortlex order (shorter choice sequences first, then lexicographically smaller among equal lengths).

The library has a bug in its binary search helper function and is missing several critical shrink passes needed for optimal reduction quality. The test suite at `/tests/test_state.py` verifies both correctness and the quality of shrunk test cases.

Fix the library so that all tests pass. The shrinking engine should produce test cases that are locally minimal: no single transformation from any reduction pass should be able to produce a simpler interesting test case.

Key areas to investigate:
- The `bin_search_down` helper function's behavior at boundary values
- The `shrink` method's reduction passes (look for TODO markers)
- How passes interact to achieve optimal shrink quality for different kinds of properties