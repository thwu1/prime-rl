# Nanobot Matter Manipulation System — Specification


## Overview

The Nanobot Matter Manipulation System (NMMS) enables 3D construction through
programmable nanobots operating on a voxel grid. A resonant subspace field
establishes a matrix of voxels in which matter can be created. Nanobots focus
the field to fill voxels, assembling target 3D objects. Construction begins and
ends with a single nanobot at the origin and proceeds in discrete time steps.

## Coordinate System

### Resolution

A resolution R specifies the number of voxels along each axis, where R is a
positive integer satisfying 0 < R <= 250.

### Coordinates

A coordinate c = (x, y, z) specifies a voxel, where x, y, z are non-negative
integers. For resolution R, coordinate (0, 0, 0) is the origin and
(R-1, R-1, R-1) is the far corner. A coordinate is valid if
0 <= x < R, 0 <= y < R, 0 <= z < R.

### Coordinate Differences

A coordinate difference d = <dx, dy, dz> specifies relative position.
Adding d to c yields (x+dx, y+dy, z+dz).

The **Manhattan length** of d is: mlen(d) = |dx| + |dy| + |dz|

The **Chessboard length** of d is: clen(d) = max(|dx|, |dy|, |dz|)

Coordinates c and c' are **adjacent** if mlen(c' - c) = 1.

### Linear Coordinate Differences

A coordinate difference d = <dx, dy, dz> is **linear** if exactly one
component is non-zero.

A **short linear coordinate difference** (sld) is a linear coordinate
difference with mlen(d) <= 5. There are exactly 30 sld values.

A **long linear coordinate difference** (lld) is a linear coordinate
difference with mlen(d) <= 15. There are exactly 90 lld values.

### Near Coordinate Differences

A coordinate difference d is a **near coordinate difference** (nd) if
0 < mlen(d) <= 2 and clen(d) = 1. That is, each component is in {-1, 0, 1},
at least one is non-zero, and at most two are non-zero. There are exactly
18 nd values.

### Regions

A region [c1, c2] specifies a rectangular cuboid. Coordinate c = (x, y, z)
is a member of [c1, c2] where c1 = (x1, y1, z1) and c2 = (x2, y2, z2) if:
  min(x1,x2) <= x <= max(x1,x2),
  min(y1,y2) <= y <= max(y1,y2),
  min(z1,z2) <= z <= max(z1,z2).

## Matrix

A matrix M has resolution R and maps each coordinate to either **Full**
(containing matter) or **Void** (empty). Initially all coordinates are Void.

### Grounding

A Full coordinate c = (x, y, z) is **grounded** if y = 0 or there exists an
adjacent Full coordinate that is itself grounded. Equivalently, c is grounded
if there is a path of adjacent Full coordinates from c to some Full coordinate
with y = 0.

## System State

The state S of an executing system consists of:
- **energy**: total energy expended (non-negative integer)
- **harmonics**: the global field harmonics (Low or High)
- **matrix**: the voxel matrix (each voxel Full or Void)
- **bots**: the set of active nanobots
- **trace**: the remaining sequence of commands

Each active nanobot has:
- **bid**: unique positive integer identifier
- **pos**: position coordinate
- **seeds**: a set of identifiers available for fission

### Well-formedness

A state is well-formed if:
1. If harmonics is Low, all Full voxels are grounded.
2. Each bot has a distinct bid.
3. Each bot's position is distinct and Void in the matrix.
4. The seeds of all bots are pairwise disjoint.
5. No bot's seeds contain any active bot's bid.

### Initial State

For a matrix with resolution R:
- energy = 0
- harmonics = Low
- matrix: all Void
- bots = { bot(bid=1, pos=(0,0,0), seeds={2,3,...,20}) }
- trace: loaded from trace file

## Execution

Each time step with n active nanobots:

1. **Well-formedness check**: It is an error if the state is not well-formed.

2. **Command assignment**: Sort bots by bid. Take n commands from the trace
   (error if fewer than n remain). Assign command i to the bot with the i-th
   smallest bid.

3. **Group formation**: Fusion pairs (FusionP + FusionS that reference each
   other's positions) form command groups. All other commands are singleton
   groups.

4. **Precondition check**: Check each command's preconditions against the
   current matrix state. It is an error if any precondition fails.

5. **Interference check**: Compute volatile coordinates for each group. It is
   an error if any two groups share volatile coordinates.

6. **Apply effects** (only if no errors):

   a. Maintenance energy:
      - If harmonics = High: energy += 30 * R^3
      - If harmonics = Low: energy += 3 * R^3
      - For each active bot: energy += 20

   b. Apply each command group's effects. Since groups do not interfere,
      application order does not matter.

7. Remove consumed commands from trace.

Execution ends when either Halt is executed (bots becomes empty) or an error
occurs.

## Commands

### Halt

Preconditions: bot at (0,0,0), exactly one active bot, harmonics is Low.
Volatile: {pos}
Effect: Remove bot from active set. System halts.

### Wait

Volatile: {pos}
Effect: None.

### Flip

Volatile: {pos}
Effect: Toggle harmonics (Low <-> High).

### SMove lld

(lld is a long linear coordinate difference)

Let c' = pos + lld.

Preconditions: c' is valid. All coordinates in region [pos, c'] are Void.
Volatile: region [pos, c']
Effect: pos := c'. energy += 2 * mlen(lld).

### LMove sld1 sld2

(sld1, sld2 are short linear coordinate differences)

Let c' = pos + sld1, c'' = c' + sld2.

Preconditions: c' and c'' are valid. All coordinates in region [pos, c'] and
region [c', c''] are Void.
Volatile: region [pos, c'] union region [c', c'']
Effect: pos := c''. energy += 2 * (mlen(sld1) + 2 + mlen(sld2)).

### Fission nd m

(nd is a near coordinate difference, m is a non-negative integer)

Let c' = pos + nd. Let {bid1, ..., bidk} = bot.seeds sorted ascending.

Preconditions: seeds is non-empty. c' is valid. c' is Void. k >= m + 1.
Volatile: {pos, c'}
Effect:
  - bot.seeds := {bid(m+2), ..., bidk}
  - Create new bot: bid=bid1, pos=c', seeds={bid2, ..., bid(m+1)}
  - energy += 24

### Fill nd

(nd is a near coordinate difference)

Let c' = pos + nd.

Preconditions: c' is valid.
Volatile: {pos, c'}
Effect:
  - If c' is Void: set c' to Full, energy += 12
  - If c' is Full: energy += 6

### FusionP nd (Fusion Primary)

(nd is a near coordinate difference)

Paired with a FusionS command from another bot. Let c' = pos + nd.
The primary bot's c' must equal the secondary bot's position, and the
secondary bot's target must equal the primary bot's position.

Preconditions: c' is valid. A matching FusionS partner exists.
Volatile (group): {primary.pos, secondary.pos}
Effect:
  - primary.seeds := primary.seeds union {secondary.bid} union secondary.seeds
  - Remove secondary bot
  - energy -= 24

### FusionS nd (Fusion Secondary)

Paired with FusionP. See FusionP for semantics.

## Binary Formats

### Model Files (.mdl)

The first byte encodes the resolution R as an unsigned 8-bit integer.

The remaining ceil(R^3 / 8) bytes encode Full coordinates as a bit array.
Coordinate (x, y, z) is Full if and only if bit (x * R * R + y * R + z) is
set. Within each byte, bit 0 is the least significant bit.

### Trace Files (.nbt)

A trace file is a sequence of encoded commands. Each command is 1 or 2 bytes.

#### Encoding Linear Coordinate Differences

A **short linear coordinate difference** sld = <dx, dy, dz> is encoded as:
- 2-bit axis `a`: if dx != 0 then a = 01; if dy != 0 then a = 10;
  if dz != 0 then a = 11
- 4-bit unsigned integer `i`: component value + 5

A **long linear coordinate difference** lld = <dx, dy, dz> is encoded as:
- 2-bit axis `a`: same encoding as sld
- 5-bit unsigned integer `i`: component value + 15

#### Encoding Near Coordinate Differences

A near coordinate difference nd = <dx, dy, dz> is encoded as a 5-bit unsigned
integer with value: (dx + 1) * 9 + (dy + 1) * 3 + (dz + 1).

#### Encoding Commands

Notation: [b7 b6 b5 b4 b3 b2 b1 b0] denotes a byte where b0 is the least
significant bit.

**Halt**: [1 1 1 1 1 1 1 1] = 0xFF

**Wait**: [1 1 1 1 1 1 1 0] = 0xFE

**Flip**: [1 1 1 1 1 1 0 1] = 0xFD

**SMove lld**: Two bytes.
  Byte 1: [0 0 a1 a0 0 1 0 0]
  Byte 2: [0 0 0 i4 i3 i2 i1 i0]
  where a = lld axis, i = lld integer.

  Example: SMove <12,0,0> -> a=01, i=12+15=27 -> [0x14] [0x1B]
  Example: SMove <0,0,-4> -> a=11, i=-4+15=11 -> [0x34] [0x0B]

**LMove sld1 sld2**: Two bytes.
  Byte 1: [a2_1 a2_0 a1_1 a1_0 1 1 0 0]
  Byte 2: [i2_3 i2_2 i2_1 i2_0 i1_3 i1_2 i1_1 i1_0]
  where a1, i1 encode sld1 and a2, i2 encode sld2.

  Example: LMove <3,0,0> <0,-5,0> -> a1=01 i1=8, a2=10 i2=0 -> [0x9C] [0x08]

**FusionP nd**: One byte: [nd4 nd3 nd2 nd1 nd0 1 1 1]

**FusionS nd**: One byte: [nd4 nd3 nd2 nd1 nd0 1 1 0]

**Fission nd m**: Two bytes.
  Byte 1: [nd4 nd3 nd2 nd1 nd0 1 0 1]
  Byte 2: m as unsigned 8-bit integer.

**Fill nd**: One byte: [nd4 nd3 nd2 nd1 nd0 0 1 1]
