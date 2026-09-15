#!/usr/bin/env python3

import sys
import os
import struct
import zlib

ARKV_VERSION = 2
FLAG_CKSUM = 0x01
FLAG_SCRAM = 0x02
ETYPE_FILE = 0
ETYPE_DIR = 1
CKSUM_SEED = 0x5A3C9E71
MAGIC = b"ARKV"
FOOTER = b"ARKV_END"


def w8(f, v):
    f.write(struct.pack("<B", v))


def w16(f, v):
    f.write(struct.pack("<H", v))


def w32(f, v):
    f.write(struct.pack("<I", v))


def w64(f, v):
    f.write(struct.pack("<q", v))


def r8(f):
    d = f.read(1)
    if len(d) < 1:
        raise EOFError
    return struct.unpack("<B", d)[0]


def r16(f):
    d = f.read(2)
    if len(d) < 2:
        raise EOFError
    return struct.unpack("<H", d)[0]


def r32(f):
    d = f.read(4)
    if len(d) < 4:
        raise EOFError
    return struct.unpack("<I", d)[0]


def r64(f):
    d = f.read(8)
    if len(d) < 8:
        raise EOFError
    return struct.unpack("<q", d)[0]


def arkv_cksum(data):
    if not data:
        return zlib.crc32(b"", CKSUM_SEED) & 0xFFFFFFFF
    return zlib.crc32(data, CKSUM_SEED) & 0xFFFFFFFF


def arkv_scramble(data, key):
    key_bytes = key.encode("latin-1") if isinstance(key, str) else key
    kl = len(key_bytes)
    if kl == 0:
        return data
    result = bytearray(data)
    for i in range(len(result)):
        result[i] ^= (key_bytes[i % kl] ^ 0xA5) & 0xFF
    return bytes(result)


def read_header(f):
    m = f.read(4)
    if m != MAGIC:
        print("Error: not an ARKV archive", file=sys.stderr)
        return None
    ver = r8(f)
    if ver != ARKV_VERSION:
        print(f"Error: unsupported version {ver}", file=sys.stderr)
        return None
    flags = r8(f)
    count = r32(f)
    return {"version": ver, "flags": flags, "count": count}


def read_entry(f, flags):
    plen = r16(f)
    path = f.read(plen).decode("latin-1")
    etype = r8(f)
    mode = r16(f)
    mtime = r64(f)
    size = r32(f)
    data = f.read(size) if size > 0 else b""
    cksum = r32(f) if (flags & FLAG_CKSUM) else 0
    return {
        "path": path,
        "type": etype,
        "mode": mode,
        "mtime": mtime,
        "size": size,
        "data": data,
        "cksum": cksum,
    }


def cmd_create(args):
    if len(args) < 2:
        print("Usage: arkv create <archive> <files...>", file=sys.stderr)
        return 1
    arcpath = args[0]
    files = args[1:]

    flags = 0
    if os.environ.get("ARKV_CHECKSUM") == "1":
        flags |= FLAG_CKSUM
    if os.environ.get("ARKV_SCRAMBLE") == "1":
        flags |= FLAG_SCRAM

    with open(arcpath, "wb") as out:
        out.write(MAGIC)
        w8(out, ARKV_VERSION)
        w8(out, flags)
        w32(out, len(files))

        for fpath in files:
            st = os.stat(fpath)
            path_bytes = fpath.encode("latin-1")
            w16(out, len(path_bytes))
            out.write(path_bytes)

            is_dir = os.path.isdir(fpath)
            etype = ETYPE_DIR if is_dir else ETYPE_FILE
            w8(out, etype)
            w16(out, st.st_mode & 0xFFFF)
            w64(out, int(st.st_mtime))

            if etype == ETYPE_FILE:
                with open(fpath, "rb") as inf:
                    data = inf.read()
                cksum = arkv_cksum(data)
                if flags & FLAG_SCRAM:
                    data = arkv_scramble(data, fpath)
                w32(out, len(data))
                out.write(data)
                if flags & FLAG_CKSUM:
                    w32(out, cksum)
            else:
                w32(out, 0)
                if flags & FLAG_CKSUM:
                    w32(out, arkv_cksum(b""))

        out.write(FOOTER)

    msg = f"Created '{arcpath}': {len(files)} entries"
    if flags & FLAG_CKSUM:
        msg += " [checksum]"
    if flags & FLAG_SCRAM:
        msg += " [scrambled]"
    print(msg)
    return 0


def cmd_list(args):
    if len(args) < 1:
        print("Usage: arkv list <archive>", file=sys.stderr)
        return 1
    with open(args[0], "rb") as f:
        hdr = read_header(f)
        if hdr is None:
            return 1
        for i in range(hdr["count"]):
            try:
                e = read_entry(f, hdr["flags"])
            except EOFError:
                print(f"Error: corrupt entry {i}", file=sys.stderr)
                return 1
            from datetime import datetime, timezone

            dt = datetime.fromtimestamp(e["mtime"], tz=timezone.utc)
            ts = dt.strftime("%Y-%m-%dT%H:%M:%S")
            t = "d" if e["type"] == ETYPE_DIR else "f"
            print(f"{t} {e['mode'] & 0o7777:04o} {e['size']:10d} {ts} {e['path']}")
    return 0


def cmd_extract(args):
    if len(args) < 1:
        print("Usage: arkv extract <archive> [dir]", file=sys.stderr)
        return 1
    target = args[1] if len(args) >= 2 else "."

    with open(args[0], "rb") as f:
        hdr = read_header(f)
        if hdr is None:
            return 1

        if target != ".":
            os.makedirs(target, exist_ok=True)

        for i in range(hdr["count"]):
            try:
                e = read_entry(f, hdr["flags"])
            except EOFError:
                print(f"Error: corrupt entry {i}", file=sys.stderr)
                return 1

            data = e["data"]
            if (hdr["flags"] & FLAG_SCRAM) and data and e["size"] > 0:
                data = arkv_scramble(data, e["path"])

            if hdr["flags"] & FLAG_CKSUM:
                computed = arkv_cksum(data)
                if computed != e["cksum"]:
                    print(
                        f"Warning: checksum mismatch for '{e['path']}'",
                        file=sys.stderr,
                    )

            outpath = os.path.join(target, e["path"])
            if e["type"] == ETYPE_DIR:
                os.makedirs(outpath, mode=e["mode"] & 0o7777, exist_ok=True)
            else:
                parent = os.path.dirname(outpath)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(outpath, "wb") as of:
                    of.write(data)
                os.chmod(outpath, e["mode"] & 0o7777)

            print(f"  {e['path']}")

        print(f"Extracted {hdr['count']} entries to '{target}'")
    return 0


def cmd_info(args):
    if len(args) < 1:
        print("Usage: arkv info <archive>", file=sys.stderr)
        return 1
    with open(args[0], "rb") as f:
        hdr = read_header(f)
        if hdr is None:
            return 1
        print(f"Archive: {args[0]}")
        print(f"Version: {hdr['version']}")
        flags_str = f"Flags: 0x{hdr['flags']:02x}"
        if hdr["flags"] & FLAG_CKSUM:
            flags_str += " checksum"
        if hdr["flags"] & FLAG_SCRAM:
            flags_str += " scramble"
        print(flags_str)
        print(f"Entries: {hdr['count']}")
        for i in range(hdr["count"]):
            try:
                e = read_entry(f, hdr["flags"])
            except EOFError:
                print(f"Error: corrupt entry {i}", file=sys.stderr)
                return 1
            tname = "dir" if e["type"] == ETYPE_DIR else "file"
            print(
                f"  [{i}] {e['path']} ({tname}, {e['size']} bytes, mode {e['mode'] & 0o7777:04o})"
            )
    return 0


def cmd_verify(args):
    if len(args) < 1:
        print("Usage: arkv verify <archive>", file=sys.stderr)
        return 1
    with open(args[0], "rb") as f:
        hdr = read_header(f)
        if hdr is None:
            return 1
        if not (hdr["flags"] & FLAG_CKSUM):
            print("Archive has no checksums")
            return 0
        ok = True
        for i in range(hdr["count"]):
            try:
                e = read_entry(f, hdr["flags"])
            except EOFError:
                print(f"Error: corrupt entry {i}", file=sys.stderr)
                return 1
            data = e["data"]
            if data and e["size"] > 0 and (hdr["flags"] & FLAG_SCRAM):
                data = arkv_scramble(data, e["path"])
            computed = arkv_cksum(data)
            if computed == e["cksum"]:
                print(f"{e['path']}: OK")
            else:
                print(
                    f"{e['path']}: FAIL (expected 0x{e['cksum']:08x}, got 0x{computed:08x})"
                )
                ok = False
    return 0 if ok else 1


def cmd_dump(args):
    if len(args) < 1:
        print("Usage: arkv dump <archive>", file=sys.stderr)
        return 1
    with open(args[0], "rb") as f:
        hdr = read_header(f)
        if hdr is None:
            return 1
        print(
            f"HEADER: magic=ARKV version={hdr['version']} flags=0x{hdr['flags']:02x} entries={hdr['count']}"
        )
        for i in range(hdr["count"]):
            try:
                e = read_entry(f, hdr["flags"])
            except EOFError:
                print(f"Error: corrupt entry {i}", file=sys.stderr)
                return 1
            tname = "dir" if e["type"] == ETYPE_DIR else "file"
            line = f'ENTRY[{i}]: path="{e["path"]}" type={tname} mode={e["mode"] & 0o7777:04o} mtime={e["mtime"]} size={e["size"]}'
            if hdr["flags"] & FLAG_CKSUM:
                line += f" cksum=0x{e['cksum']:08x}"
            print(line)
        ftr = f.read(8)
        if ftr == FOOTER:
            print("FOOTER: ARKV_END")
        else:
            print("FOOTER: <missing or corrupt>")
    return 0


def show_help():
    sys.stdout.write(
        "Usage: arkv <command> [args...]\n\n"
        "Commands:\n"
        "  create <archive> <files...>  Create a new archive\n"
        "  list <archive>              List archive contents\n"
        "  extract <archive> [dir]     Extract archive contents\n"
        "\nOptions:\n"
        "  --help     Show this message\n"
        "  --version  Show version\n"
    )


def main():
    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "--help":
        show_help()
        sys.exit(0)
    if cmd == "--version":
        print("arkv 2.1.0")
        sys.exit(0)

    commands = {
        "create": cmd_create,
        "list": cmd_list,
        "extract": cmd_extract,
        "info": cmd_info,
        "verify": cmd_verify,
        "dump": cmd_dump,
    }

    if cmd in commands:
        sys.exit(commands[cmd](rest))

    print(f"Error: unknown command '{cmd}'", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
