#!/usr/bin/env python3
"""
Analyze the meta page of the database using xxd.
Hex-dumps the first 64 bytes and annotates each field
with its name, byte range, and decoded little-endian value.
"""

import struct
import subprocess

DB_PATH = "/tmp/trace_test.db"
OUTPUT = "/app/meta_page_report.txt"


def main():
    # Run xxd to get hex dump of the first 64 bytes (meta page)
    result = subprocess.run(
        ["xxd", "-l", "64", DB_PATH],
        capture_output=True, text=True
    )
    hex_dump = result.stdout

    # Read raw bytes for field decoding
    with open(DB_PATH, 'rb') as f:
        data = f.read(64)

    with open(OUTPUT, 'w') as f:
        f.write("=== Meta Page Binary Analysis (xxd) ===\n\n")
        f.write(f"Database file: {DB_PATH}\n")
        f.write(f"Page size: 4096 bytes (meta page occupies page 0)\n\n")
        f.write("Raw hex dump (first 64 bytes):\n")
        f.write(hex_dump)
        f.write("\n")
        f.write("Field annotations:\n")
        f.write("-" * 60 + "\n")

        # Signature (bytes 0-15)
        sig = data[0:16].decode('ascii', errors='replace').rstrip('\x00')
        f.write(
            f"  Bytes  0-15: signature    = {repr(sig)}\n"
        )

        # Root pointer (bytes 16-23)
        root = struct.unpack_from('<Q', data, 16)[0]
        f.write(
            f"  Bytes 16-23: root_ptr     = {root} "
            f"(B+tree root page number)\n"
        )

        # Page count / pages flushed (bytes 24-31)
        page_used = struct.unpack_from('<Q', data, 24)[0]
        f.write(
            f"  Bytes 24-31: page_flushed = {page_used} "
            f"(total pages written to file)\n"
        )

        # Free list head page (bytes 32-39)
        if len(data) >= 40:
            head_page = struct.unpack_from('<Q', data, 32)[0]
            f.write(
                f"  Bytes 32-39: fl_head_page = {head_page} "
                f"(free list head node page)\n"
            )

        # Free list head sequence (bytes 40-47)
        if len(data) >= 48:
            head_seq = struct.unpack_from('<Q', data, 40)[0]
            f.write(
                f"  Bytes 40-47: fl_head_seq  = {head_seq} "
                f"(free list head sequence number)\n"
            )

        # Free list tail page (bytes 48-55)
        if len(data) >= 56:
            tail_page = struct.unpack_from('<Q', data, 48)[0]
            f.write(
                f"  Bytes 48-55: fl_tail_page = {tail_page} "
                f"(free list tail node page)\n"
            )

        # Free list tail sequence (bytes 56-63)
        if len(data) >= 64:
            tail_seq = struct.unpack_from('<Q', data, 56)[0]
            f.write(
                f"  Bytes 56-63: fl_tail_seq  = {tail_seq} "
                f"(free list tail sequence number)\n"
            )

        f.write("-" * 60 + "\n")

    print(f"Meta page report written to {OUTPUT}")


if __name__ == "__main__":
    main()
