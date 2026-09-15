A field-deployed sensor node (SN-3000) became unresponsive. Before power-cycling, a technician captured the firmware ELF binary and a full SRAM dump via JTAG.

## Files

- `/app/firmware.elf` — The device's firmware binary (ELF32, ARM). Contains a symbol table exporting the addresses and sizes of ring buffer data structures in RAM, and a custom linker section holding the telemetry message type schema in a compact binary encoding.
- `/app/ram_dump.bin` — Raw SRAM contents. The dump begins at the address given by the `_sram` linker symbol in the firmware's symbol table. Multiple ring buffers for different firmware subsystems coexist in this memory region.

## Context

Outbound telemetry uses a BipBuffer (bipartite circular buffer). Each message is serialized with the postcard v1.0 wire format, then a CRC32 checksum (IEEE polynomial, little-endian u32, computed over the serialized payload bytes) is appended, and the combined payload is COBS-encoded with `0x00` frame delimiters. BipBuffer control metadata is four consecutive LE u32 values: `write_head`, `read_head`, `watermark`, `capacity`.

The postcard wire format uses unsigned LEB128 (varint) encoding for most integer types, zigzag encoding before varint for signed integers, and tagged-union discriminants as varint u32. Some fields may use fixed-width encodings instead of varint — the type schema indicates which encoding applies to each field.

## Goal

Recover all CRC32-verified telemetry messages from the correct ring buffer in the RAM dump and write them to `/app/recovered.json` as a JSON array in buffer-read order (oldest valid message first).

Each JSON object must contain a `"type"` field with the enum variant name plus one key per struct field. Nested enum values as variant name strings, `None` options as `null`, sequences as JSON arrays.