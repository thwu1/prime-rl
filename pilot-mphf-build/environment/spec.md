
# Algorithm Specification: Pilot-Based Minimal Perfect Hash Function

## Goal

Given a set K of n integer keys, construct a data structure that maps each key
bijectively to an integer in {0, 1, ..., n-1}. This is called a Minimal Perfect
Hash Function (MPHF).

## Algorithm Overview

1. Choose a global random seed s.
2. Hash each key using a seeded hash function to produce a 64-bit value.
3. Partition keys into "buckets" based on their hash values.
4. For each bucket (processed largest-first), find a "pilot" value (an 8-bit
   integer, 0-255) that maps all keys in the bucket to distinct,
   previously-unoccupied "slots".
5. When no collision-free pilot exists, use cuckoo-hashing-style eviction:
   choose the pilot that minimizes a collision score, evict the colliding
   buckets, and re-process them.
6. After all buckets are assigned pilots, build a "remap" table that maps
   slot indices >= n down to free positions < n, yielding a minimal PHF.

## Parameters

- `n` — number of keys.
- `alpha` — load factor, default 0.98.
  - `num_slots = max(floor(n / alpha) + 1, n + 1)`
  - If `num_slots` is a power of 2, increment it by 1.
- `lam` (lambda) — target average bucket size, default 3.0.
  - `num_buckets = max(floor(n / lam) + 3, 4)`

## Hash Function

For a 64-bit integer key `k` and 64-bit seed `s`, compute:

    x = (k XOR s) mod 2^64

Then apply the SplitMix64 finalizer (a strong 64-bit bit mixer):

    x = (x XOR (x >> 30)) * 0xbf58476d1ce4e5b9   mod 2^64
    x = (x XOR (x >> 27)) * 0x94d049bb133111eb   mod 2^64
    hash(k, s) = x XOR (x >> 31)

This produces a single 64-bit hash value with excellent avalanche properties,
used for both bucket and slot computation. Any hash function with comparable
distribution quality may be substituted (a simple FxHash-style multiply may
fail for structured inputs like sequential integers).

## Bucket Assignment

    bucket(h) = floor(h * num_buckets / 2^64)

This "fast reduce" maps the hash uniformly to an index in [0, num_buckets).
It uses the high bits of the 128-bit product h * num_buckets.

## Pilot Hash

For a pilot value p (in 0..255) and seed s:

    pilot_hash(p, s) = (C * (p XOR s)) mod 2^64

## Slot Computation

Given hash `h` and pilot `p`:

    slot(h, p) = ((h XOR pilot_hash(p, s)) mod 2^64) mod num_slots

## Construction

### Step 1: Hashing and Bucketing

- Choose a random 64-bit seed `s`.
- Compute `h_i = hash(k_i, s)` for each key `k_i`.
- If any two keys produce the same hash, discard this seed and retry.
- Assign each key to bucket `b_i = bucket(h_i)`.

### Step 2: Pilot Search with Eviction

- Sort bucket indices by bucket size (number of keys), largest first.
- Initialize arrays:
  - `pilots[0..num_buckets]` — 8-bit pilot for each bucket (initially 0).
  - `taken[0..num_slots]` — boolean, whether each slot is occupied.
  - `slot_owner[0..num_slots]` — which bucket occupies each slot (-1 if free).

- For each bucket `new_b` in sorted order:
  - If `new_b` is empty, skip.
  - Push `(size_of(new_b), new_b)` onto a max-priority stack (largest first).
  - Initialize a "recent" list containing `new_b`.

  - While the stack is non-empty:
    - Pop the largest bucket `b` from the stack.

    - **Phase 1 — collision-free pilot search:**
      For each pilot p = 0, 1, ..., 255:
        - Compute `slots_p = [slot(h, p) for each h in bucket b]`.
        - If any two values in `slots_p` are equal (self-collision), skip p.
        - If all positions in `slots_p` are free (`taken[s] == false`):
          - Set `pilots[b] = p`.
          - Mark all positions in `slots_p` as taken, owned by `b`.
          - Proceed to the next item on the stack.

    - **Phase 2 — eviction pilot search (if Phase 1 failed):**
      For each pilot p = 0, 1, ..., 255 (optionally starting from a varied
      offset to reduce cycles):
        - Compute `slots_p` as above.
        - If self-collision, skip p.
        - For each slot in `slots_p` that is already taken by bucket `o`:
          - If `o` is in the "recent" list, skip this pilot entirely
            (to avoid eviction cycles).
          - Otherwise, add `size_of(bucket_o)^2` to a collision score.
        - Track the pilot with minimum collision score.

      If no valid pilot exists (all 256 cause self-collisions or hit recent
      buckets), the current seed has failed; retry with a new seed.

      Apply the best pilot:
        - Set `pilots[b] = best_pilot`.
        - Compute the slot positions for this pilot.
        - For each slot that is owned by another bucket `o`:
          - Remove ALL of `o`'s slots from taken/slot_owner (using `o`'s
            current pilot to recompute `o`'s slot positions).
          - Push `o` onto the stack for re-processing.
        - Mark all of `b`'s slots as taken, owned by `b`.
        - Add `b` to the "recent" list (keep only the 16 most recent entries).

  - If total evictions across all buckets exceed `10 * num_slots`, the seed
    has failed; retry with a new seed.

- Retry with a new seed if construction fails (up to 10 attempts total).

### Step 3: Remap Table

After all pilots are assigned, some keys may hash to slot positions >= n. These
must be remapped to free positions < n.

- Collect `free_below_n`: all positions `i` where `i < n` and `taken[i]` is
  false, in ascending order.
- Create `remap` array of length `num_slots - n`.
- Iterate j = 0, 1, ..., num_slots - n - 1:
  - If `taken[n + j]` is true, set `remap[j]` = next value from
    `free_below_n`.
  - Otherwise, set `remap[j] = 0` (this entry is never accessed).

The number of free positions below n equals the number of taken positions
above n, so the lists are exactly matched.

## Query

    query(k):
        h = hash(k, seed)
        b = bucket(h)
        p = pilots[b]
        s = slot(h, p)
        if s < n:
            return s
        else:
            return remap[s - n]

## bits_per_key Formula

    bits_per_key = 8 * (len(pilots) + 4 * len(remap)) / n

This counts each pilot as 1 byte (8 bits) and each remap entry as 4 bytes
(32 bits, sufficient for index values up to 2^32).
