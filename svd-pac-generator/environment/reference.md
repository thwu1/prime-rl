# PAC API Reference for TBMCU-001

## Overview

The generated PAC (Peripheral Access Crate) provides type-safe access to memory-mapped
peripheral registers. The generated crate must be `#![no_std]`, have no external
dependencies, use Rust edition 2021, and be named `tbmcu001-pac`.

## SVD File Format

The input SVD file (`/app/device.svd`) follows the CMSIS-SVD standard:

- `<peripheral>` elements contain `<name>`, `<description>`, `<baseAddress>`, and `<registers>`
- `<register>` elements contain `<name>`, `<description>`, `<addressOffset>`, `<size>`, `<access>`, `<resetValue>`, and `<fields>`
- `<field>` elements contain `<name>`, `<description>`, `<bitOffset>`, `<bitWidth>`, and optional `<enumeratedValues>`
- `<enumeratedValue>` elements contain `<name>` and `<value>`
- Access types: `"read-only"`, `"write-only"`, `"read-write"`

Register addresses are computed as: `peripheral.baseAddress + register.addressOffset`

## Derived Peripherals

A `<peripheral>` element may have a `derivedFrom` attribute naming another peripheral.
The derived peripheral inherits all registers from the parent peripheral. If the derived
peripheral also contains its own `<registers>` element, those registers are merged:
registers with the same name override the parent's, and registers with new names are
appended. The derived peripheral uses its own `<baseAddress>` for address computation.

Example: if `GPIOB` has `derivedFrom="GPIOA"`, it inherits all of GPIOA's registers
(MODER, ODR, etc.) but at GPIOB's base address. Any additional registers listed under
GPIOB are added to the inherited set.

## Register Arrays (Dimensioned Registers)

A `<register>` element may contain `<dim>`, `<dimIncrement>`, and `<dimIndex>` child
elements, indicating a register array. The generator must expand these into individual
registers:

- `<dim>` — number of instances
- `<dimIncrement>` — address offset increment between instances (in bytes)
- `<dimIndex>` — index values, either as a range `"M-N"` or comma-separated `"A,B,C"`

The `%s` placeholder in the register's `<name>` and `<description>` is replaced with
the corresponding index value from `<dimIndex>`. The address offset of the i-th instance
(0-based) is: `addressOffset + i * dimIncrement`.

Each expanded register becomes an independent register struct and module in the generated
code, following the same naming conventions as non-array registers.

## Peripherals Singleton

```rust
// Take singleton (returns None on second call)
let p = Peripherals::take().unwrap();

// Unsafe bypass (always returns, skips singleton check)
let p = unsafe { Peripherals::steal() };

// Reset singleton flag (for testing)
Peripherals::reset_singleton();
```

The singleton uses `core::sync::atomic::AtomicBool`.

## Register Access Pattern

### Read (available for `read-write` and `read-only` registers)

```rust
let val = p.GPIOA.moder.read();        // Returns module::R
let raw = val.bits();                    // Raw u32 value
let field = val.mode0().bits();          // Field as integer
let check = val.mode0().is_output();     // Check enum variant
```

### Write (available for `read-write` and `write-only` registers)

```rust
p.GPIOA.moder.write(|w| {
    w.mode0().output()       // Named variant setter
     .mode1().bits(2)        // Raw bits setter
     .od0().set_bit()        // For 1-bit fields without enums
     .od1().clear_bit()      // Clear a single bit
});
```

**Critical**: `write()` initializes the writer `W` from the register's **reset value**,
not the current register value. Fields not explicitly set in the closure retain their
reset value. This means a second `write()` call does NOT preserve values from a
previous write.

### Modify (available for `read-write` registers ONLY)

```rust
p.GPIOA.moder.modify(|r, w| {
    // r: read current value; w: initialized from current value
    if r.mode0().is_input() {
        w.mode0().output()
    } else {
        w
    }
});
```

**Critical**: `modify()` initializes the writer `W` from the **current register value**.
Fields not explicitly set in the closure are preserved (not reset).

### Reset

```rust
p.GPIOA.moder.reset(); // Write the reset value to the register
```

Available for writable registers.

### Raw Bits

```rust
// Write arbitrary 32-bit value (unsafe because it bypasses field validation)
p.TIM2.cnt.write(|w| unsafe { w.bits(0x12345678) });
```

## Generated Code Structure

```
generated-pac/
  Cargo.toml
  src/
    lib.rs          # #![no_std], module declarations, Peripherals struct
    mmio.rs         # Memory simulation backend
    gpioa.rs        # GPIOA peripheral module
    gpiob.rs        # GPIOB peripheral module (derived)
    spi1.rs         # SPI1 peripheral module
    tim2.rs         # TIM2 peripheral module
```

## Naming Conventions

| SVD Element | Generated Rust Name | Example |
|---|---|---|
| Peripheral struct | Original SVD name (uppercase) | `GPIOA`, `SPI1` |
| Peripheral module | Lowercase of name | `gpioa`, `spi1` |
| Register struct | Original SVD name (uppercase) | `MODER`, `CR1`, `CCR1` |
| Register module | Lowercase of name | `moder`, `cr1`, `ccr1` |
| Register field on peripheral | Lowercase | `p.GPIOA.moder` |
| Reader struct (in register module) | `R` | `moder::R` |
| Writer struct (in register module) | `W` | `moder::W` |
| Field reader type | `{FIELD}_R` | `MODE0_R` |
| Field writer type | `{FIELD}_W<'a>` | `MODE0_W<'a>` |
| Field accessor on R | Lowercase of field name | `.mode0()` |
| Field accessor on W | Lowercase of field name | `.mode0()` |
| Enum variant checker on reader | `is_{snake_case}()` | `.is_output()`, `.is_idle_high()` |
| Enum variant setter on writer | `{snake_case}()` | `.output()`, `.idle_high()` |

**snake_case conversion**: Insert `_` before each uppercase letter that follows a
lowercase letter or digit. Examples: `FirstEdge` → `first_edge`, `IdleHigh` → `idle_high`,
`CenterAligned2` → `center_aligned2`, `Div128` → `div128`.

## Field Type Mapping

| Bit Width | Rust Type |
|---|---|
| 1-8 | `u8` |
| 9-16 | `u16` |
| 17-32 | `u32` |

## Access Restrictions

| SVD Access | Generated Methods |
|---|---|
| `read-write` | `read()`, `write()`, `modify()`, `reset()` |
| `read-only` | `read()` only |
| `write-only` | `write()`, `reset()` only |

For read-only registers, the register module contains only `R` and field reader types.
For write-only registers, the register module contains only `W` and field writer types.

## Single-Bit Fields

For 1-bit fields **without** enumerated values, the writer provides `set_bit()` and
`clear_bit()` convenience methods in addition to `bits()`.

For 1-bit fields **with** enumerated values, the writer provides named variant setters
(e.g., `.master()`, `.slave()`) but NOT `set_bit()`/`clear_bit()`.

## Memory Backend (`mmio` module)

The generated PAC must include a public `mmio` module:

```rust
pub fn read(addr: u32) -> u32;
pub fn write(addr: u32, val: u32);
pub fn init();  // Reset all memory to register reset values
```

The backend maps addresses in the range starting at `0x4000_0000` using a static
array wrapped in `core::cell::UnsafeCell` for interior mutability. The `init()`
function zeros the array and then writes non-zero reset values for registers that
have them (e.g., SPI1.SR reset = 0x02, TIM2.ARR reset = 0xFFFF).
