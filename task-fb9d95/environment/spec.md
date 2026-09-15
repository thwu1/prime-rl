# WGSL Memory Layout Specification

This document defines the memory layout rules for WGSL (WebGPU Shading Language) types
in host-shareable address spaces, as specified by the WebGPU standard.

## Utility Function

```
roundUp(k, n) = ⌈n / k⌉ × k
```

Rounds `n` up to the next multiple of `k`.

## Scalar Types

| Type | AlignOf | SizeOf |
|------|---------|--------|
| i32  | 4       | 4      |
| u32  | 4       | 4      |
| f32  | 4       | 4      |
| f16  | 2       | 2      |

Scalar layout is identical in all address spaces.

## Vector Types

A vector `vecN<T>` contains N components of scalar type T.

| Type      | AlignOf         | SizeOf        |
|-----------|-----------------|---------------|
| vec2\<T\> | 2 × AlignOf(T)  | 2 × SizeOf(T) |
| vec3\<T\> | 4 × AlignOf(T)  | 3 × SizeOf(T) |
| vec4\<T\> | 4 × AlignOf(T)  | 4 × SizeOf(T) |

**Important:** `vec3<T>` has alignment `4 × AlignOf(T)`, NOT `3 × AlignOf(T)`.
This means `vec3<f32>` has alignment 16 but size only 12, leaving 4 bytes of
trailing padding when used in arrays or structs.

Vector layout is identical in all address spaces.

## Matrix Types

A matrix `matCxR<T>` has C columns and R rows, stored in column-major order.
Each column is a `vecR<T>` vector. For layout purposes, a matrix is equivalent
to an array of its column vectors:

```
matCxR<T>  ≡  array<vecR<T>, C>
```

Therefore:

- **AlignOf(matCxR\<T\>)** = AlignOf(array\<vecR\<T\>, C\>) (see Array Types below)
- **SizeOf(matCxR\<T\>)** = SizeOf(array\<vecR\<T\>, C\>) (see Array Types below)

The matrix inherits all address-space-dependent behaviors from its equivalent
array type, including uniform address space alignment rounding.

## Array Types

An array `array<E, N>` contains N elements of type E.

### Storage Address Space

| Property | Value |
|----------|-------|
| AlignOf(array\<E, N\>) | AlignOf(E) |
| Stride | roundUp(AlignOf(E), SizeOf(E)) |
| SizeOf(array\<E, N\>) | N × Stride |

### Uniform Address Space

In the uniform address space, array element alignment is rounded up to a
multiple of 16:

| Property | Value |
|----------|-------|
| AlignOf(array\<E, N\>) | roundUp(16, AlignOf(E)) |
| Stride | roundUp(AlignOf(array\<E, N\>), SizeOf(E)) |
| SizeOf(array\<E, N\>) | N × Stride |

Note that the stride is computed using the **array's alignment** (which includes
the roundUp(16, ...) adjustment), not the bare element alignment.

## Structure Types

A structure `struct S { m₁: T₁, m₂: T₂, ..., mₙ: Tₙ }` lays out its members
sequentially with alignment-based padding.

### Member Layout

Members are laid out in declaration order. For each member mᵢ:

1. Compute the **effective member alignment**: the alignment used to determine
   the member's byte offset within the struct.
2. The member's offset is `roundUp(effective_alignment, previous_end)`.
3. The member's contribution to struct size is its **effective size**.

### Effective Member Alignment

The effective alignment of a struct member combines three factors:

1. Start with `AlignOf(member_type)` in the current address space.
2. If the member has an `@align(n)` attribute, take the maximum:
   `max(AlignOf(member_type), n)`.
3. **Uniform address space only:** If the member's type is a structure type or
   array type, round the alignment up to a multiple of 16:
   `roundUp(16, alignment)`.

### Effective Member Size

- If the member has a `@size(n)` attribute, the effective size is `n`
  (must satisfy n ≥ SizeOf(member_type)).
- Otherwise, the effective size is `SizeOf(member_type)`.

### Structure Alignment

The alignment of a structure is the maximum of all its members' **effective
alignments** (as computed above, including any uniform rounding):

```
AlignOf(S) = max(effective_alignment(mᵢ) for all members mᵢ)
```

### Structure Size

The total size of a structure must be rounded up to a multiple of the
structure's own alignment, to ensure correct layout when the structure appears
in arrays or as a member of another structure:

```
SizeOf(S) = roundUp(AlignOf(S), offset_after_last_member)
```

where `offset_after_last_member = OffsetOf(mₙ) + effective_size(mₙ)`.

### Member Offset

```
OffsetOf(m₁) = 0
OffsetOf(mᵢ) = roundUp(effective_alignment(mᵢ), OffsetOf(mᵢ₋₁) + effective_size(mᵢ₋₁))
```

## Example: Storage Layout

```wgsl
struct Example {
    a: f32,           // offset=0,  align=4,  size=4
    b: vec3<f32>,     // offset=16, align=16, size=12
    c: f32,           // offset=28, align=4,  size=4
}
// AlignOf = 16, SizeOf = roundUp(16, 32) = 32
```

## Example: Uniform Layout

```wgsl
struct Inner { x: f32, y: f32 }
// AlignOf(Inner) = 4, SizeOf(Inner) = 8

struct Outer {
    a: f32,           // offset=0,  align=4,  size=4
    b: Inner,         // offset=16, align=roundUp(16, 4)=16, size=8  [struct member in uniform]
    c: f32,           // offset=24, align=4,  size=4
}
// AlignOf(Outer) = 16, SizeOf(Outer) = roundUp(16, 28) = 32
```

## Example: Uniform Array

```wgsl
struct Data {
    values: array<f32, 4>,
}
// In uniform: AlignOf(array<f32, 4>) = roundUp(16, 4) = 16
//             Stride = roundUp(16, 4) = 16
//             SizeOf(array<f32, 4>) = 4 × 16 = 64
```
