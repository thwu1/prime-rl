# WGEF Compressed Graph Format

## File Structure

The binary file consists of:
1. **Magic bytes**: 4 bytes — ASCII `WGEF`
2. **Bitstream payload**: all remaining bytes

The bitstream uses big-endian (MSB-first) bit ordering within each byte:
the most significant bit (position 7) is read first, proceeding down to
position 0. When one byte is exhausted, reading continues at position 7
of the next byte.

---

## Instantaneous Codes

### Unary Code

The unary representation of a non-negative integer *n* consists of *n*
zero-bits followed by a single one-bit.

| Value | Codeword |
|-------|----------|
| 0     | `1`      |
| 1     | `01`     |
| 2     | `001`    |
| 3     | `0001`   |

### Elias γ (Gamma) Code

To encode a non-negative integer *n*:

1. Let λ = ⌊log₂(n + 1)⌋
2. Write λ in unary
3. Write the λ least significant bits of (n + 1), MSB first

| Value | λ | Codeword     |
|-------|---|-------------|
| 0     | 0 | `1`         |
| 1     | 1 | `010`       |
| 2     | 1 | `011`       |
| 5     | 2 | `00 110`    |
| 13    | 3 | `000 1110`  |

### Minimal Binary Code

Encodes an integer *x* in the range [0, *m*) using a variable number of
bits:

1. Let *s* = ⌊log₂(m)⌋
2. Let *t* = 2^(*s* + 1) − *m*
3. If *x* < *t*: write *x* in *s* bits
4. If *x* ≥ *t*: write (*x* + *t*) in *s* + 1 bits

### Boldi–Vigna ζₖ (Zeta) Code

A parameterized instantaneous code. The parameter *k* ≥ 1 is specified
in the file header. To encode a non-negative integer *n*:

1. Let λ = ⌊log₂(n + 1)⌋ and *h* = ⌊λ / k⌋
2. Let ℓ = 2^(k · h)
3. Write *h* in unary
4. Write (n + 1 − ℓ) as a minimal binary code with upper bound
   *m* = ℓ · (2ᵏ − 1)

The parameter *k* controls the granularity of the code grouping. Common
values are *k* = 3 (ζ₃, used in standard WebGraph) and *k* = 5. Note
that ζ₁ is equivalent to the γ code. The implied distribution is
≈ 1/*x*^(1+1/k).

---

## Bitstream Layout

### Header

| Field        | Code  | Description                              |
|-------------|-------|------------------------------------------|
| Node count  | γ     | Total number of nodes *N*                |
| Window size | γ     | Maximum backward reference distance *W*  |
| Zeta param  | γ     | Parameter *k* for ζₖ codes               |

### Elias-Fano Offset Index

Immediately after the header, an Elias-Fano encoded monotone sequence
of *N* values stores the cumulative bit offset of each node's data
within the node data section. That is, offset[*i*] gives the bit
position (from the start of the node data section) where node *i*'s
encoding begins. The first offset is always 0.

The Elias-Fano representation of a sorted sequence
*v*₀ ≤ *v*₁ ≤ … ≤ *v*_{*N*−1} with *v*_{*N*−1} < *U* is stored as:

| Field              | Code  | Description                                        |
|-------------------|-------|----------------------------------------------------|
| Lower-bit width   | γ     | *L* = ⌊log₂(*U* / *N*)⌋  (0 if *N* ≥ *U*)       |
| Upper bound       | γ     | *U* (exclusive upper bound of values)              |
| Lower bits        | raw   | *N* values, each *L* bits wide, packed MSB-first   |
| Upper bits        | unary | Gaps between consecutive upper parts, in unary      |

Each value *vᵢ* is split into a lower part (*vᵢ* mod 2^*L*) and an
upper part (*vᵢ* >> *L*). The lower parts are stored contiguously as a
packed bit array. The upper parts are encoded as unary gaps: for *i* = 0,
write (*v*₀ >> *L*) zeros then a 1; for *i* > 0, write
((*vᵢ* >> *L*) − (*v*_{*i*−1} >> *L*)) zeros then a 1.

### Node Data Section

For each node *u* = 0, 1, …, *N* − 1 (in order):

1. **Out-degree** *d*(*u*): γ-coded
2. If *d*(*u*) = 0: nothing further for this node
3. **Reference offset** *r*: γ-coded
   - *r* = 0 means **direct mode** (no reference)
   - *r* > 0 means **copy mode** (reference node *u* − *r*, where *r* ≤ *W*)

#### Direct Mode (*r* = 0)

The successor list *s*₀ < *s*₁ < … < *s*_{*d*−1} is encoded as:
- First successor *s*₀: ζₖ-coded
- For *i* = 1, …, *d*(*u*) − 1: the gap (*sᵢ* − *s*_{*i*−1} − 1) is ζₖ-coded

#### Copy Mode (*r* > 0)

The successor list is built from the reference node's successor list:

1. **Block count** *b*: γ-coded — number of copy/skip run-length entries
2. **Block lengths** *b*₀, *b*₁, …, *b*_{*b*−1}: each γ-coded
   - Block 0 (index 0): **copy** this many consecutive elements from the
     reference list, starting at position 0
   - Block 1 (index 1): **skip** this many consecutive elements
   - Block 2 (index 2): **copy** this many consecutive elements
   - Blocks alternate copy/skip, starting with copy at even indices
   - Reference elements beyond the last block's range are implicitly skipped
3. **Extra count** *e*: γ-coded — number of additional successor values
4. **Extra values** (if *e* > 0):
   - First extra: ζₖ-coded (absolute value)
   - Subsequent extras: ζₖ-coded (gap = *extraᵢ* − *extra*_{*i*−1} − 1)
5. Final successor list = **sorted merge** of copied elements and extras

---

## Query Types

The file `queries.txt` contains queries to answer about the decoded graph,
one per line:

- `NODES` — total number of nodes
- `EDGES` — total number of directed edges
- `OUTDEGREE v` — out-degree of node *v*
- `EDGE u v` — `1` if edge *u*→*v* exists, `0` otherwise
- `SUCCESSORS v` — space-separated sorted successor list, or `NONE`
- `MAX_DEGREE` — maximum out-degree across all nodes
- `ISOLATED_NODES` — count of nodes with out-degree 0
- `FIRST_SUCCESSOR_SUM` — sum of the smallest successor of every non-isolated node
- `IN_DEGREE v` — in-degree of node *v*
- `CHECKSUM` — XOR of (*u* × 31337 + *v*) over all edges (*u*, *v*)
- `TWO_HOP_REACH v` — count of distinct nodes reachable from *v* in
  exactly 1 or 2 hops, excluding *v* itself
