# Cache-Consistent Revocation — Design Candidates

Three candidate designs for integrating token revocation with the verification
cache. Each design must satisfy:

1. A revoked token is **never** returned as valid from cache
2. No TOCTOU race conditions between concurrent `revoke()` and `verify()` calls
3. Cache provides measurable performance benefit (repeated verifications avoid full crypto)
4. Implementation complexity is minimized

Evaluate all three. Select the correct one. Implement it in your `TkdbService.verify()`.

---

## Candidate A: Cache-First with Background Invalidation

```python
def verify(self, token_b64, satisfiers=None):
    m = self._deserialize(token_b64)

    # Check cache first for maximum performance
    cache_key = m.signature
    if cache_key in self._cache:
        self._cache_hits += 1
        return {"valid": self._cache[cache_key], "identifier": m.identifier, "cached": True}

    # Cache miss: check blacklist, then full verify
    if self._is_blacklisted(m.identifier):
        return {"valid": False, "identifier": m.identifier, "cached": False}

    self._cache_misses += 1
    result = self._full_verify(m, satisfiers)
    self._cache[cache_key] = result
    return {"valid": result, "identifier": m.identifier, "cached": False}

def revoke(self, identifier):
    self._add_to_blacklist(identifier)
    # Schedule background cache purge — runs asynchronously
    self._schedule_cache_purge(identifier)
    return {"revoked": True, "identifier": identifier}
```

**Rationale**: Maximizes cache hit rate by checking cache before anything else.
Background purge handles invalidation asynchronously to avoid blocking the
revocation call.

---

## Candidate B: Dual-Index with Eager Purge

```python
def verify(self, token_b64, satisfiers=None):
    m = self._deserialize(token_b64)
    cache_key = m.signature

    # Check cache first
    if cache_key in self._cache:
        self._cache_hits += 1
        return {"valid": self._cache[cache_key], "identifier": m.identifier, "cached": True}

    # Cache miss: check blacklist
    if self._is_blacklisted(m.identifier):
        return {"valid": False, "identifier": m.identifier, "cached": False}

    # Full verify and cache with reverse index
    self._cache_misses += 1
    result = self._full_verify(m, satisfiers)
    self._cache[cache_key] = result
    self._sig_to_id[cache_key] = m.identifier  # reverse mapping
    return {"valid": result, "identifier": m.identifier, "cached": False}

def revoke(self, identifier):
    self._add_to_blacklist(identifier)
    # Eagerly purge cache using reverse index
    sigs_to_remove = [sig for sig, tid in self._sig_to_id.items() if tid == identifier]
    for sig in sigs_to_remove:
        self._cache.pop(sig, None)
        self._sig_to_id.pop(sig, None)
    return {"revoked": True, "identifier": identifier}
```

**Rationale**: Maintains a reverse mapping (signature → identifier) so that
`revoke()` can immediately purge all cached entries for the revoked identifier.
No background tasks needed.

---

## Candidate C: Revocation-First with Cache Fallthrough

```python
def verify(self, token_b64, satisfiers=None):
    m = self._deserialize(token_b64)
    cache_key = m.signature

    # ALWAYS check revocation before cache
    if self._is_blacklisted(m.identifier):
        self._cache.pop(cache_key, None)  # clean up stale entry if present
        return {"valid": False, "identifier": m.identifier, "cached": False}

    # Then check cache
    if cache_key in self._cache:
        self._cache_hits += 1
        return {"valid": self._cache[cache_key], "identifier": m.identifier, "cached": True}

    # Cache miss: full verify
    self._cache_misses += 1
    result = self._full_verify(m, satisfiers)
    self._cache[cache_key] = result
    return {"valid": result, "identifier": m.identifier, "cached": False}

def revoke(self, identifier):
    self._add_to_blacklist(identifier)
    # No explicit cache purge needed — revocation check always runs first
    return {"revoked": True, "identifier": identifier}
```

**Rationale**: Revocation check is the first operation in every `verify()` call,
guaranteeing that no stale cache entry can mask a revocation. The cache only
accelerates verification for non-revoked tokens. Simple implementation with
no reverse index or background tasks.

