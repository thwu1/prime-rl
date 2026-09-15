"""
Write the design evaluation document.

"""


def main():
    content = """\
# Cache-Consistent Revocation — Design Evaluation

## Analysis

### Candidate A: Cache-First with Background Invalidation

**Verdict: INSECURE**

Candidate A checks the cache before checking the revocation blacklist. This
means a token that was previously verified and cached as valid will continue to
be served as valid from cache even after it has been revoked. The background
purge is asynchronous and cannot guarantee timely invalidation — there is an
unbounded window during which a revoked token is incorrectly accepted.

This is a classic stale-cache vulnerability. In the worst case, an attacker
who has obtained a stolen token can continue to use it indefinitely after the
legitimate user revokes it, as long as the cached result persists.

### Candidate B: Dual-Index with Eager Purge

**Verdict: FRAGILE / RACE CONDITION**

Candidate B also checks the cache before the blacklist on verify(). It relies
on the revoke() method to eagerly purge matching entries using a reverse index
(signature → identifier). While this works in simple single-threaded scenarios,
it has a TOCTOU (time-of-check-to-time-of-use) vulnerability:

1. Thread/request 1 calls verify(), gets a cache miss, starts full verification
2. Thread/request 2 calls revoke(), purges the cache (entry not yet present)
3. Thread/request 1 finishes verification, caches the result as valid
4. The token is now revoked but cached as valid

Additionally, verify() checks the cache before the blacklist, so even without
concurrency issues, a token that was verified, then revoked (and purged), then
the same cache entry could be re-populated on a subsequent verify() call before
the blacklist check runs.

The reverse index also adds implementation complexity and memory overhead.

### Candidate C: Revocation-First with Cache Fallthrough

**Verdict: CORRECT**

Candidate C always checks the revocation blacklist as the first operation in
verify(), before consulting the cache. This guarantees that a revoked token is
never returned as valid regardless of cache state. The cache only accelerates
verification for non-revoked tokens.

Key security properties:
- No stale cache vulnerability: blacklist is checked before cache on every call
- No TOCTOU race: revocation check is atomic with respect to the verify flow
- Simple implementation: no reverse index, no background tasks
- Cache still provides performance benefit for the common case (non-revoked tokens)

## Selection

**Candidate C (Revocation-First with Cache Fallthrough)** is the correct design.

It is the only candidate that unconditionally guarantees a revoked token will
never be served as valid from cache. The performance cost of checking the
blacklist on every verify() call is minimal compared to the full cryptographic
verification it replaces on cache hits.
"""

    with open("/app/EVALUATION.md", "w") as f:
        f.write(content)
    print("Evaluation written to /app/EVALUATION.md")


if __name__ == "__main__":
    main()
