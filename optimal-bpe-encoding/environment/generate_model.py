#!/usr/bin/env python3
"""Generate model.bin with offset-based binary format.

Format:
  Bytes 0-3:   magic "BPE1"
  Byte 4:      version (1)
  Bytes 5-6:   uint16 LE num_merges
  Bytes 7-10:  uint32 LE data_offset (byte position of merge data)
  Bytes 11 to data_offset-1: metadata section
  From data_offset: num_merges pairs of (uint16 LE parent0, uint16 LE parent1)
"""
import struct

merges = [
    (101, 32), (32, 116), (116, 104), (32, 97), (104, 101),
    (257, 104), (261, 101), (262, 32), (105, 110), (264, 103),
    (101, 114), (97, 110), (267, 100), (32, 268), (111, 110),
    (114, 101), (101, 110), (116, 105), (273, 111), (274, 110),
    (112, 113), (114, 115), (113, 114), (112, 278), (279, 115),
    (35, 36), (37, 38), (36, 37), (35, 283), (284, 38),
    (285, 39), (123, 124), (124, 125), (123, 288), (74, 75),
    (76, 77), (75, 76), (74, 292), (293, 77), (58, 59),
    (60, 61), (62, 63), (59, 60), (58, 298), (299, 61),
    (300, 62), (301, 63), (302, 64), (97, 116), (111, 114),
]

num_merges = len(merges)
# Header: magic(4) + version(1) + num_merges(2) + data_offset(4) = 11 bytes
# Metadata: 64 bytes of training corpus info
data_offset = 11 + 64  # = 75

buf = bytearray()
buf += b"BPE1"
buf += struct.pack("<B", 1)
buf += struct.pack("<H", num_merges)
buf += struct.pack("<I", data_offset)

# Metadata section (visible via strings/xxd, acts as noise for format analysis)
meta = b"corpus:wikipedia_en_2024\x00"
meta += b"created:2024-03-15\x00"
meta += b"algo:bpe\x00"
meta += b"\xfe" * (64 - len(meta))
buf += meta

assert len(buf) == data_offset

for p0, p1 in merges:
    buf += struct.pack("<HH", p0, p1)

with open("/app/model.bin", "wb") as f:
    f.write(buf)

print(f"Wrote model.bin: {len(buf)} bytes, {num_merges} merges, data at offset {data_offset}")
