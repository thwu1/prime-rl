# ETW Kernel Memory Dump Format Specification

This document describes the binary format of the ETW kernel memory dump file.
**Note:** Some structure offsets are incomplete or unverified. Fields marked with
`[UNKNOWN]` must be determined through analysis of the binary data.

## File Header (64 bytes at offset 0x0)

| Offset | Size | Type     | Description                     |
|--------|------|----------|---------------------------------|
| 0x00   | 8    | char[8]  | Magic: `ETWDUMP1`              |
| 0x08   | 4    | uint32   | Number of trace sessions        |
| 0x0C   | 4    | uint32   | Number of process entries       |
| 0x10   | 4    | uint32   | Number of consumer entries      |
| 0x14   | 4    | uint32   | Reserved (0)                    |
| 0x18   | 8    | uint64   | Offset to session table         |
| 0x20   | 8    | uint64   | Offset to process table         |
| 0x28   | 8    | uint64   | Offset to consumer table        |
| 0x30   | 8    | uint64   | Offset to string table          |
| 0x38   | 8    | uint64   | Offset to provider table        |

## Session Entry (0x400 bytes each)

Based on the Windows kernel `WMI_LOGGER_CONTEXT` structure. Sessions are stored
sequentially starting at the session table offset.

| Offset | Size | Type     | Description                           |
|--------|------|----------|---------------------------------------|
| 0x000  | 4    | uint32   | LoggerId                              |
| 0x004  | 4    | uint32   | BufferSize (KB)                       |
| 0x008  | 4    | uint32   | MaximumEventSize                      |
| 0x00C  | 4    | uint32   | LoggerMode                            |
| 0x010  | 4    | int32    | AcceptNewEvents                       |
| 0x070  | 4    | uint32   | LogBuffersLost (count of dropped buffers) |
| 0x074  | 4    | uint32   | LogBuffersWritten                     |
| 0x078  | 4    | uint32   | RealTimeBuffersDelivered              |
| 0x088  | 2    | uint16   | LoggerName.Length (bytes)              |
| 0x08A  | 2    | uint16   | LoggerName.MaximumLength              |
| 0x090  | 8    | uint64   | LoggerName.Buffer (-> string table)   |
| ...    |      |          | [many undocumented fields]             |
| [UNK]  | 4    | uint32   | Flags (bitfield, see reference_flags)  |
| [UNK]  | 4    | uint32   | NumProviders                          |
| [UNK]  | 8    | uint64   | ProviderListOffset (-> provider table) |
| [UNK]  | 4    | uint32   | NumConsumers                          |
| [UNK]  | 8    | uint64   | ConsumerListOffset (-> consumer table) |

**Important:** The offset of the `Flags` field, and the provider/consumer
reference fields, within the session entry is NOT documented. You must determine
these offsets by analyzing the binary data. The `Flags` field is a 32-bit
bitfield. The `NumProviders`, `ProviderListOffset`, `NumConsumers`, and
`ConsumerListOffset` fields are located near each other, likely at 16-byte
aligned offsets after the Flags field.

**Hint:** The Flags field for well-known sessions should contain predictable
bit patterns based on their type (see `reference_flags.txt`).

## Process Entry (0x100 bytes each)

Subset of the Windows kernel `EPROCESS` structure.

| Offset | Size | Type     | Description                          |
|--------|------|----------|--------------------------------------|
| 0x000  | 8    | uint64   | UniqueProcessId (PID)                |
| 0x008  | 16   | char[16] | ImageFileName (null-terminated ASCII) |
| 0x020  | 1    | uint8    | Protection.Level (PS_PROTECTION)     |

### PS_PROTECTION.Level encoding:
- Bits 0-2: Type (0=None, 1=ProtectedLight, 2=Protected)
- Bit 3: Audit
- Bits 4-7: Signer (0=None, 3=Antimalware, 4=Lsa, 5=Windows, 6=WinTcb)

Antimalware-PPL has Type=1, Signer=3, giving Level=0x31.

## Consumer Entry (0xA0 bytes each)

Based on the `ETW_REALTIME_CONSUMER` structure. Consumers are processes
that are actively consuming events from a trace session.

| Offset | Size | Type   | Description                              |
|--------|------|--------|------------------------------------------|
| 0x000  | 8    | uint64 | Links.Flink (0 if end of list)           |
| 0x008  | 8    | uint64 | Links.Blink                              |
| 0x010  | 8    | uint64 | ProcessHandle                            |
| 0x018  | 8    | uint64 | ProcessObject (-> process table entry)   |
| 0x058  | 2    | uint16 | LoggerId                                 |
| 0x05A  | 1    | uint8  | Flags                                    |

## Provider Entry (0x20 bytes each)

Each entry describes an ETW provider enabled in a trace session.

| Offset | Size | Type     | Description                           |
|--------|------|----------|---------------------------------------|
| 0x00   | 16   | GUID     | Provider GUID (mixed-endian format)   |
| 0x10   | 8    | uint64   | EnabledKeywords                       |
| 0x18   | 1    | uint8    | EnabledLevel                          |

### GUID binary format (Windows mixed-endian):
A GUID `{AABBCCDD-EEFF-1122-3344-556677889900}` is stored as:
- Data1 (4 bytes, little-endian): DD CC BB AA
- Data2 (2 bytes, little-endian): FF EE
- Data3 (2 bytes, little-endian): 22 11
- Data4 (8 bytes, big-endian): 33 44 55 66 77 88 99 00

## String Table

Logger names are stored as null-terminated UTF-16LE encoded strings,
packed sequentially starting at the string table offset.
