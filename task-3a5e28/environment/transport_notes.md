# Transport Layer

The serial capture uses COBS (Consistent Overhead Byte Stuffing) encoding for
frame delimiting. Each COBS-encoded payload is terminated by a 0x00 byte.

See: https://en.wikipedia.org/wiki/Consistent_Overhead_Byte_Stuffing

## Integrity

A 2-byte CRC-16/CCITT checksum (polynomial 0x1021, init 0xFFFF, no final XOR)
is appended in little-endian order to each raw frame before COBS encoding:

    wire = COBS_encode(raw_frame || CRC16_LE) || 0x00

Frames with CRC mismatches should be treated as corrupt.
