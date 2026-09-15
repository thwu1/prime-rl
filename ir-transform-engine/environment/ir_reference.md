# Chiptool IR Format Reference

## Overview

The chiptool intermediate representation (IR) describes microcontroller peripheral
register layouts as a flat YAML file. Each top-level key is prefixed with its category:

- `block/<path>` — Register block (a group of memory-mapped register items)
- `fieldset/<path>` — Bit-field layout for a register value
- `enum/<path>` — Named value set for a field

Paths use `::` as a namespace separator
(e.g., `block/dma::Dma`, `fieldset/dma::regs::ChCtrl`, `enum/dma::vals::DataSize`).

## Blocks

A block groups register items at specific byte offsets within a memory-mapped region.

```yaml
block/ns::BlockName:
  description: "Optional description"
  items:
  - name: register_name
    byte_offset: 0
    access: ReadWrite       # ReadWrite (default), Read, or Write
    bit_size: 32            # Register width in bits (default 32)
    fieldset: "ns::regs::FieldsetRef"   # Optional reference to bit-field layout
  - name: sub_block_ref
    byte_offset: 64
    block: "ns::SubBlockName"   # Reference to another block definition
    array:
      len: 4
      stride: 16                # Byte spacing between array instances
```

Each item is either:
- A **register**: has optional `fieldset`, `access`, `bit_size` properties
- A **sub-block reference**: has a `block` property pointing to another block definition

These are mutually exclusive — an item cannot be both a register and a sub-block reference.

Items may have an `array` property with `len` (count) and `stride` (byte spacing)
indicating repeated instances at uniform intervals.

## Fieldsets

A fieldset defines the bit-field layout within a register value.

```yaml
fieldset/ns::regs::FieldsetName:
  description: "Optional"
  bit_size: 32
  fields:
  - name: field_name
    bit_offset: 0           # Bit position within the register
    bit_size: 1             # Field width in bits
    enum: "ns::vals::EnumRef"   # Optional reference to enumerated values
    array:
      len: 4
      stride: 1             # Bit spacing between field array instances
```

Fields within a fieldset may also have an `array` property for repeated
bit-fields at regular bit-position intervals.

## Enums

An enum defines named constants for a field's possible values.

```yaml
enum/ns::vals::EnumName:
  bit_size: 2
  variants:
  - name: VARIANT_A
    value: 0
  - name: VARIANT_B
    value: 1
```

## Cross-References

- Block items reference fieldsets and sub-blocks by their full namespaced path string
- Fieldset fields reference enums by their full namespaced path string
- All references use the same `::` namespace format as the defining keys (without the
  category prefix — e.g., a fieldset defined as `fieldset/dma::regs::ChCtrl` is
  referenced as `dma::regs::ChCtrl`)
