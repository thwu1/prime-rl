A property-based testing framework at `/app/` discovers failing test cases but does not minimize them. The minimizer should reduce each failing input to the simplest form that still triggers the failure, across all supported data types, within the performance budget enforced by the test suite.

The codebase is tracked in a git repository. The verification tests are at `/tests/test_state.py`.