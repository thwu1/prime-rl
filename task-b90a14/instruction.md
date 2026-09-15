The Conjecture engine at `/app/conjecture/` is a simplified property-based testing framework inspired by Hypothesis. Test cases are represented as sequences of typed choices (integers, booleans, strings). When a test function marks a case as INTERESTING (failing), the `Shrinker` class should find the shortlex-minimal choice sequence that still triggers the failure.

All shrinker infrastructure — caching, candidate evaluation via `consider_new_choices()`, and fixed-point iteration — is implemented in `/app/conjecture/shrinker.py`. The `_reduce()` method raises `NotImplementedError`. Implement it.

A correct implementation produces choice sequences that are near shortlex-minimal across all three supported choice types within the evaluation budget.