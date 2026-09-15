# PtrHash: Minimal Perfect Hash Function — Technical Specification

A minimal perfect hash function (MPHF) maps a static set of *n* distinct keys
bijectively to the integers {0, 1, …, n−1}. PtrHash achieves this using a
hash-and-displace strategy with fixed-width 8-bit pilots.

This document specifies the algorithm. All hash primitives are provided in
`ptrhash.h`.

## Data Structure

A constructed PtrHash stores:

| Field | Type | Description |
|-------|------|-------------|
| seed | uint64 | Random seed used during construction for pilot hashing |
| n | size_t | Number of input keys |
| S | size_t | Total number of slots (S > n) |
| B | size_t | Number of buckets |
| pilots | uint8[B] | Pilot value for each bucket |
| remap | size_t[S−n] | Overflow-to-gap remapping table |

## Parameters

- **Load factor α ∈ (0, 1)**: Controls slot count S = ⌈n / α⌉. Lower α gives
  more slack (easier construction) but wastes space. Typical: 0.85–0.99.
- **Average bucket size λ > 0**: Controls bucket count B = ⌈n / λ⌉. Larger λ
  means fewer, bigger buckets. Typical: 3.0–4.0.

## Hash Primitives (from ptrhash.h)

- `fx_hash(key)` → uint64: Multiplicative hash. Bijective on uint64 (the
  constant is odd), so distinct keys always produce distinct hashes.
- `hash_pilot(pilot, seed)` → uint64: Hashes an 8-bit pilot with a 64-bit
  seed. Used to perturb slot computation.
- `fmix64(k)` → uint64: Bijective finalizer (murmur3 fmix64). Mixes all
  input bits so that high-order output bits depend on every input bit.
  Must be applied before `reduce64` to avoid degenerate collisions when
  the reduction modulus is small.
- `reduce64(x, m)` → uint64: Maps a 64-bit value uniformly to [0, m) via
  multiply-shift: ⌊x · m / 2⁶⁴⌋.
- `reduce32(x, m)` → uint32: 32-bit variant: ⌊x · m / 2³²⌋.

## Derived Functions

**Bucket assignment** — determines which bucket a key belongs to:

    bucket(h) = reduce32( hi32(h), B )

where hi32(h) = (uint32_t)(h >> 32). This uses the upper 32 bits of the hash.

**Slot computation** — given a hash and pilot, determines the target slot:

    slot(h, pilot, seed) = reduce64( fmix64( h ⊕ hash_pilot(pilot, seed) ), S )

The XOR combines the key hash with the pilot perturbation. The `fmix64`
finalizer is critical: it is a bijection that thoroughly mixes all 64 input
bits, ensuring the high-order bits that `reduce64` uses depend on the entire
combined value. Without it, when S is small, `reduce64` would extract only a
few top bits, and XOR alone does not change the relative relationship between
two values' top bits — causing permanent intra-bucket collisions that no
pilot can resolve.

## Construction Algorithm

### Phase 1: Hashing and Bucket Assignment

1. Compute h_i = fx_hash(key_i) for all i ∈ {0, …, n−1}.
2. Assign b_i = bucket(h_i) for each key.
3. Group keys by bucket. Record the number of keys per bucket.

### Phase 2: Pilot Search (Hash-and-Displace)

4. Sort buckets by decreasing size. Processing larger buckets first, when most
   slots are still free, greatly increases the probability of finding a
   collision-free pilot.

5. Initialise a boolean array `taken[0..S−1]` to all false.

6. For each bucket b in size-descending order (skip empty buckets):
   - Let K_b = { h_i : b_i = b } be the set of hash values in bucket b.
   - Search for a pilot p ∈ {0, 1, …, 255} satisfying **both** conditions:
     (a) For every h ∈ K_b, the slot `slot(h, p, seed)` is not yet taken.
     (b) All slot values for keys in K_b under pilot p are mutually distinct.
   - If such p is found: set `pilots[b] = p` and mark all slots as taken.
   - If no pilot in {0..255} satisfies both conditions: see Recovery below.

### Phase 3: Overflow Remapping

Because S > n, some keys may land in slots ≥ n ("overflow" slots). These must
be remapped to unused slots < n ("gap" slots) to achieve a bijection to {0..n−1}.

7. Scan slots 0..n−1: those not taken are gap slots.
8. Scan slots n..S−1: those that are taken are overflow slots.
9. The number of gaps always equals the number of overflows (both equal
   S − n minus the unoccupied overflow slots). Pair them one-to-one:
   `remap[s − n] = gap_slot` for each overflow slot s.

## Recovery Strategies

When no 8-bit pilot can produce collision-free slot assignment for a bucket:

**Retry with a new seed.** The seed only affects `hash_pilot`, which changes
the entire slot mapping for every pilot. Restarting construction with a
different seed reshuffles all slot computations while preserving bucket
assignments. This is the simplest strategy.

**Cuckoo-style eviction.** Instead of restarting, select the pilot that causes
the fewest collisions (weighted by bucket size²), evict the conflicting
bucket(s) by clearing their slots and re-inserting them into the processing
queue, and place the current bucket. Guard against infinite eviction cycles
(e.g., limit total evictions, never evict recently-placed buckets). This is
more efficient for large inputs where retry might be slow.

A robust implementation may combine both: use eviction during construction and
fall back to seed retry if evictions exceed a threshold.

## Query Algorithm

Given a key k known to be in the original set:

1. h = fx_hash(k)
2. b = bucket(h) = reduce32(hi32(h), B)
3. p = pilots[b]
4. s = slot(h, p, seed) = reduce64(fmix64(h ⊕ hash_pilot(p, seed)), S)
5. If s < n: return s
6. Else: return remap[s − n]

The result is the key's unique index in {0, …, n−1}.

## Correctness Invariant

For any two distinct keys k₁, k₂ in the input set:
  query(k₁) ≠ query(k₂)

and for every input key k:
  0 ≤ query(k) < n
