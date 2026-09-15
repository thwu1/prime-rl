# Xor8 Filter Specification

## Overview

An xor8 filter is an immutable approximate membership data structure using 8-bit fingerprints. Given a set of `n` 64-bit integer keys, it answers membership queries with no false negatives and an expected false positive rate of approximately 1/256 ≈ 0.39%.

The filter consists of a byte array `B` of size `capacity`. A query checks whether `B[h0] XOR B[h1] XOR B[h2] == fingerprint(key)`, where `h0`, `h1`, `h2` are three positions derived from the key's hash.

## Hash Function

The filter uses the murmur64 finalizer:

```
murmur64(h):
    h ^= h >> 33
    h  = (h * 0xff51afd7ed558ccd) mod 2^64
    h ^= h >> 33
    h  = (h * 0xc4ceb9fe1a85ec53) mod 2^64
    h ^= h >> 33
    return h
```

For a key `k` and seed `s`, compute:

```
hash = murmur64((k + s) mod 2^64)
```

## Key Mapping

From the 64-bit hash value, derive:

- **fingerprint**: `(hash >> 56) & 0xFF` — the top 8 bits
- Three table positions, one per segment:
  - `h0 = reduce(uint32(hash), segment_length)`
  - `h1 = reduce(uint32(rotl64(hash, 21)), segment_length) + segment_length`
  - `h2 = reduce(uint32(rotl64(hash, 42)), segment_length) + 2 * segment_length`

Where:

- `uint32(x) = x & 0xFFFFFFFF` — low 32 bits
- `rotl64(x, r) = ((x << r) | (x >> (64 - r))) & 0xFFFFFFFFFFFFFFFF` — 64-bit left rotation
- `reduce(x, n) = floor(x * n / 2^32)` — maps a 32-bit value uniformly to `[0, n)` (Lemire's fast range reduction: compute the full 64-bit product of the 32-bit value `x` and `n`, then take the upper 32 bits)

## Filter Sizing

```
capacity = ceil(n * 1.23)
capacity = capacity rounded UP to the nearest multiple of 3
segment_length = capacity / 3
```

The filter table `B` is an array of `capacity` unsigned bytes, initialized to zero.

For `n = 50,000`: capacity = 61,500; segment_length = 20,500.

## Construction Algorithm

### Phase 1 — Map

For each key, compute its hash (using the current seed), fingerprint, and positions `h0`, `h1`, `h2`. Maintain two arrays indexed by table position `[0, capacity)`:

- `count[i]` — number of keys that map to position `i` (via any of their three positions)
- `xor_set[i]` — XOR of the hash values of all keys mapping to position `i`

### Phase 2 — Peel

Initialize a queue with all positions where `count[i] == 1`. Process the queue:

1. Dequeue position `p`. If `count[p] != 1`, skip (stale entry).
2. The sole key's hash at this position is `xor_set[p]`. Record `(hash, p)` in the peel order.
3. Recompute `h0`, `h1`, `h2` from this hash.
4. For each of `h0`, `h1`, `h2`: decrement `count`, XOR the hash out of `xor_set`. If the count drops to 1, enqueue that position.

If all `n` keys are peeled, construction succeeds. Otherwise, increment the seed and restart from Phase 1.

### Phase 3 — Fill

Process the peel order in **reverse** (last peeled → first processed):

For each `(hash, lone_position)`:

1. Compute fingerprint, `h0`, `h1`, `h2` from `hash`.
2. Set `B[lone_position] = fingerprint XOR B[h0] XOR B[h1] XOR B[h2]`.

This guarantees `B[h0] XOR B[h1] XOR B[h2] == fingerprint` for every key.

## Query

To check if key `k` is (probably) in the set:

1. Compute `hash = murmur64((k + seed) mod 2^64)`.
2. Derive `fingerprint`, `h0`, `h1`, `h2` as above.
3. Return `(B[h0] XOR B[h1] XOR B[h2]) == fingerprint`.

## Test Vectors

With `segment_length = 20500`:

| Input to murmur64 | hash (hex)           | fingerprint | h0    | h1    | h2    |
|--------------------|----------------------|-------------|-------|-------|-------|
| 1                  | 0xb456bcfc34c2cb2c   | 180         | 4224  | 28634 | 48283 |
| 42                 | 0x810879608e4259cc   | 129         | 11391 | 25109 | 43714 |
| 12346              | 0x58f103c03d3e6065   | 88          | 4904  | 21514 | 56700 |
| 999999             | 0xc4d3634595d45baa   | 196         | 11998 | 29896 | 47210 |

## Output Format

- `/app/output/filter.bin` — raw bytes of table `B` (exactly `capacity` bytes)
- `/app/output/meta.txt` — plain text, one `key=value` pair per line:
  ```
  seed=<integer seed used for successful construction>
  segment_length=<segment length>
  table_size=<capacity, i.e., total table size in bytes>
  attempts=<number of seeds tried before success>
  ```
