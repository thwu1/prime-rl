#!/usr/bin/env python3
"""SIMDB Control Tool v1.3.2"""
import sys
import os
import struct
import zlib
import json


PAGE_SIZE = 4096
HEADER_SIZE = 32


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def cmd_info(args):
    """Print database file header information."""
    if not args:
        die("info requires a database file path")
    path = args[0]
    if not os.path.isfile(path):
        die(f"no such file: {path}")
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) < HEADER_SIZE:
        die("file too small for header")
    magic, ver, ps, pc, cksum = struct.unpack_from('>6sHIII', data, 0)
    computed = zlib.crc32(data[HEADER_SIZE:]) & 0xFFFFFFFF
    print(f"magic:    {magic!r}")
    print(f"version:  {ver}")
    print(f"pagesize: {ps}")
    print(f"pages:    {pc}")
    print(f"checksum: 0x{cksum:08X} ({'OK' if cksum == computed else 'MISMATCH (computed 0x' + format(computed, '08X') + ')'})")
    print(f"filesize: {len(data)} (expected {HEADER_SIZE + pc * ps})")


def cmd_page(args):
    """Dump a single page as JSON."""
    if len(args) < 2:
        die("page requires <dbfile> <page_num>")
    path, pnum = args[0], int(args[1])
    if not os.path.isfile(path):
        die(f"no such file: {path}")
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) < HEADER_SIZE:
        die("file too small")
    magic, ver, ps, pc, cksum = struct.unpack_from('>6sHIII', data, 0)
    if pnum >= pc:
        die(f"page {pnum} out of range (0..{pc - 1})")
    base = HEADER_SIZE + pnum * ps
    pdata = data[base:base + ps]
    n = struct.unpack_from('>H', pdata, 0)[0]
    pos = 2
    entries = {}
    for _ in range(n):
        klen, vlen = struct.unpack_from('>HH', pdata, pos)
        pos += 4
        key = pdata[pos:pos + klen].decode('utf-8')
        pos += klen
        val = pdata[pos:pos + vlen].decode('utf-8')
        pos += vlen
        entries[key] = val
    print(json.dumps({"page": pnum, "entries": entries, "count": n}, indent=2))


def cmd_wal_dump(args):
    """Dump WAL frame summary."""
    if not args:
        die("wal-dump requires a WAL file path")
    path = args[0]
    if not os.path.isfile(path):
        die(f"no such file: {path}")
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) < 32:
        die("WAL file too small")
    magic = data[0:8]
    if magic != b'SIMWAL\x00\x00':
        die(f"bad WAL magic: {magic!r}")
    ver = struct.unpack_from('>H', data, 8)[0]
    db_cksum = struct.unpack_from('>I', data, 10)[0]
    print(f"WAL version: {ver}")
    print(f"DB checksum: 0x{db_cksum:08X}")
    print("---")

    FT = {1: 'BEGIN', 2: 'PAGE_WRITE', 3: 'COMMIT', 4: 'ABORT'}
    offset = 32
    idx = 0
    while offset < len(data):
        if offset + 4 > len(data):
            print(f"[{idx:3d}] TRUNCATED (incomplete length field)")
            break
        frame_len = struct.unpack_from('>I', data, offset)[0]
        if offset + 4 + frame_len > len(data):
            avail = len(data) - offset - 4
            print(f"[{idx:3d}] TRUNCATED (frame_len={frame_len}, available={avail})")
            break
        payload = data[offset + 4:offset + 4 + frame_len]
        body = payload[:-4]
        stored_crc = struct.unpack_from('>I', payload, len(payload) - 4)[0]
        computed_crc = zlib.crc32(body) & 0xFFFFFFFF
        crc_ok = stored_crc == computed_crc

        ft, txn_id = struct.unpack_from('>BI', body, 0)
        ft_name = FT.get(ft, f'UNKNOWN(0x{ft:02x})')

        extra = ""
        if ft == 2 and len(body) > 5:
            pg_num = struct.unpack_from('>I', body, 5)[0]
            extra = f" page={pg_num}"

        crc_status = "OK" if crc_ok else "CORRUPT"
        print(f"[{idx:3d}] {ft_name:12s} txn={txn_id:5d}{extra:20s} crc={crc_status}")

        offset += 4 + frame_len
        idx += 1


def cmd_validate(args):
    """Strict database validation."""
    if not args:
        die("validate requires a database file path")
    path = args[0]
    errors = []

    if not os.path.isfile(path):
        die(f"no such file: {path}")

    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < HEADER_SIZE:
        errors.append("file smaller than minimum header size")
    else:
        magic, ver, ps, pc, cksum = struct.unpack_from('>6sHIII', data, 0)

        if magic != b'SIMDB\x00':
            errors.append(f"bad magic: {magic!r}")
        if ver != 1:
            errors.append(f"unsupported format version: {ver}")
        if ps != PAGE_SIZE:
            errors.append(f"unexpected page size: {ps}")

        expected_len = HEADER_SIZE + pc * ps
        if len(data) != expected_len:
            errors.append(
                f"file size {len(data)} != expected {expected_len}")

        # Header checksum
        computed = zlib.crc32(data[HEADER_SIZE:]) & 0xFFFFFFFF
        if cksum != computed:
            errors.append(
                f"header checksum mismatch: "
                f"stored=0x{cksum:08X} computed=0x{computed:08X}")

        # Reserved bytes must be zero
        reserved = data[20:32]
        if reserved != b'\x00' * 12:
            errors.append("reserved header bytes are not zero")

        # Per-page validation
        for i in range(min(pc, (len(data) - HEADER_SIZE) // ps)):
            base = HEADER_SIZE + i * ps
            pdata = data[base:base + ps]
            try:
                n = struct.unpack_from('>H', pdata, 0)[0]
                pos = 2
                prev_key = None
                for j in range(n):
                    if pos + 4 > ps:
                        errors.append(
                            f"page {i}: entry {j} header overflows page")
                        break
                    klen, vlen = struct.unpack_from('>HH', pdata, pos)
                    pos += 4
                    if pos + klen + vlen > ps:
                        errors.append(
                            f"page {i}: entry {j} data overflows page")
                        break
                    key = pdata[pos:pos + klen].decode('utf-8')
                    pos += klen + vlen

                    if prev_key is not None and key <= prev_key:
                        errors.append(
                            f"page {i}: entries not sorted by key "
                            f"('{prev_key}' >= '{key}')")
                    prev_key = key

                # Zero-padding check
                if pos < ps:
                    padding = pdata[pos:]
                    if padding != b'\x00' * (ps - pos):
                        errors.append(
                            f"page {i}: non-zero padding after entries")
            except Exception as e:
                errors.append(f"page {i}: parse error: {e}")

    if errors:
        print("VALIDATION FAILED")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("VALIDATION PASSED")
        sys.exit(0)


COMMANDS = {
    'info': cmd_info,
    'page': cmd_page,
    'wal-dump': cmd_wal_dump,
    'validate': cmd_validate,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        names = ', '.join(sorted(COMMANDS))
        print(f"usage: simdb-ctl <command> [args...]", file=sys.stderr)
        print(f"commands: {names}", file=sys.stderr)
        sys.exit(1)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    main()
