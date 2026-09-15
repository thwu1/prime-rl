#!/usr/bin/env python3
"""
Decoder for defmt binary log frames.

Reads /app/string_table.json and /app/frames.bin,
writes decoded log lines to /app/output.txt.
"""
import json
import struct
import re


# ---------------------------------------------------------------------------
# Display-hint parsing
# ---------------------------------------------------------------------------

def parse_hint(s):
    """Parse a display hint string into a structured tuple."""
    if not s:
        return None
    if s == "us":
        return ("us",)
    if s == "a":
        return ("ascii",)
    if s == "?":
        return ("debug",)
    m = re.match(r"^(#)?(?:0(\d+))?(b|o|x|X)$", s)
    if m:
        alt = m.group(1) == "#"
        zp = int(m.group(2)) if m.group(2) else 0
        return ("numfmt", m.group(3), alt, zp)
    return None


# ---------------------------------------------------------------------------
# Format-string parsing
# ---------------------------------------------------------------------------

def parse_param(s):
    """Parse the contents of a {…} parameter spec."""
    result = {"index": None, "type": "?", "hint": None, "bitfield": None}

    # Optional leading integer index
    idx_end = 0
    while idx_end < len(s) and s[idx_end].isdigit():
        idx_end += 1
    if idx_end > 0 and (idx_end >= len(s) or s[idx_end] in "=:"):
        result["index"] = int(s[:idx_end])
        s = s[idx_end:]

    # Optional =type
    if s.startswith("="):
        s = s[1:]
        colon = s.find(":")
        if colon >= 0:
            type_str, hint_str = s[:colon], s[colon + 1:]
        else:
            type_str, hint_str = s, ""

        bf = re.match(r"^(\d+)\.\.(\d+)$", type_str)
        if bf:
            result["type"] = "bitfield"
            result["bitfield"] = (int(bf.group(1)), int(bf.group(2)))
        else:
            result["type"] = type_str

        if hint_str:
            result["hint"] = parse_hint(hint_str)
    elif s.startswith(":"):
        result["hint"] = parse_hint(s[1:])

    return result


def parse_format_string(fmt):
    """Parse a defmt format string into a list of ('literal', text) and
    ('param', param_dict) fragments."""
    fragments = []
    i = 0
    next_auto = 0

    while i < len(fmt):
        ch = fmt[i]
        if ch == "{":
            if i + 1 < len(fmt) and fmt[i + 1] == "{":
                fragments.append(("literal", "{"))
                i += 2
                continue
            end = fmt.index("}", i + 1)
            param = parse_param(fmt[i + 1:end])
            if param["index"] is None:
                param["index"] = next_auto
                next_auto += 1
            fragments.append(("param", param))
            i = end + 1
        elif ch == "}":
            if i + 1 < len(fmt) and fmt[i + 1] == "}":
                fragments.append(("literal", "}"))
                i += 2
                continue
            i += 1
        else:
            start = i
            while i < len(fmt) and fmt[i] not in "{}":
                i += 1
            fragments.append(("literal", fmt[start:i]))

    return fragments


# ---------------------------------------------------------------------------
# Binary reading
# ---------------------------------------------------------------------------

_TYPE_STRUCT = {
    "u8": ("<B", 1),
    "u16": ("<H", 2),
    "u32": ("<I", 4),
    "u64": ("<Q", 8),
    "i8": ("<b", 1),
    "i16": ("<h", 2),
    "i32": ("<i", 4),
    "i64": ("<q", 8),
    "f32": ("<f", 4),
    "f64": ("<d", 8),
    "bool": ("<B", 1),
    "char": ("<I", 4),
}


def read_typed(data, off, ty):
    """Read a single typed value from *data* at *off*.
    Returns (value, new_offset)."""
    if ty in _TYPE_STRUCT:
        fmt, sz = _TYPE_STRUCT[ty]
        val = struct.unpack_from(fmt, data, off)[0]
        off += sz
        if ty == "bool":
            return val != 0, off
        if ty == "char":
            return chr(val), off
        return val, off
    if ty == "str":
        length = struct.unpack_from("<I", data, off)[0]
        off += 4
        return data[off:off + length].decode("utf-8"), off + length
    if ty == "[u8]":
        length = struct.unpack_from("<I", data, off)[0]
        off += 4
        return bytes(data[off:off + length]), off + length
    raise ValueError(f"Unknown wire type: {ty!r}")


def _bf_read_type(max_end):
    """Choose the smallest integer type that fits a bitfield range."""
    if max_end <= 8:
        return "u8"
    if max_end <= 16:
        return "u16"
    if max_end <= 32:
        return "u32"
    if max_end <= 64:
        return "u64"
    raise ValueError(f"Bitfield range end {max_end} too large")


def extract_bits(val, start, end):
    """Extract bits [start, end) from *val* (LSB = bit 0)."""
    return (val >> start) & ((1 << (end - start)) - 1)


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------

def _fmt_num(val, fmt_type, alt, zp):
    """Format a single number with a numeric display hint."""
    specs = {"x": "x", "X": "X", "b": "b", "o": "o"}
    spec = specs.get(fmt_type, "")
    if alt:
        return format(val, f"#0{zp}{spec}")
    if zp:
        return format(val, f"0{zp}{spec}")
    return format(val, spec)


def fmt_val(val, hint, parent_hint=None):
    """Format *val* according to its display *hint*."""
    if hint is None:
        if isinstance(val, bool):
            return str(val).lower()
        if isinstance(val, float):
            return str(val)
        return str(val)

    kind = hint[0]

    if kind == "us":
        secs = val // 1_000_000
        us = val % 1_000_000
        return f"{secs}.{us:06d}"

    if kind == "ascii":
        buf = 'b"'
        for b in val:
            if b == 0x09:
                buf += "\\t"
            elif b == 0x0A:
                buf += "\\n"
            elif b == 0x0D:
                buf += "\\r"
            elif b == 0x20:
                buf += " "
            elif b == 0x22:
                buf += '\\"'
            elif b == 0x5C:
                buf += "\\\\"
            elif 0x21 <= b <= 0x7E:
                buf += chr(b)
            else:
                buf += f"\\x{b:02x}"
        return buf + '"'

    if kind == "numfmt":
        _, ft, alt, zp = hint
        if isinstance(val, (bytes, bytearray)):
            return "[" + ", ".join(_fmt_num(b, ft, alt, zp) for b in val) + "]"
        return _fmt_num(val, ft, alt, zp)

    if kind == "debug":
        return str(val)

    return str(val)


# ---------------------------------------------------------------------------
# Frame decoding
# ---------------------------------------------------------------------------

LEVELS = {
    "Trace": "TRACE",
    "Debug": "DEBUG",
    "Info": "INFO",
    "Warn": "WARN",
    "Error": "ERROR",
}


def decode_args(data, off, fragments, table, parent_hint=None):
    """Decode wire arguments for a list of parsed fragments.
    Returns (args_dict, new_offset).
    args_dict maps argument index -> ('val'|'bf'|'fmt', value)."""

    # Collect unique argument indices and their info
    arg_info = {}
    for ftype, fdata in fragments:
        if ftype != "param":
            continue
        idx = fdata["index"]
        if idx not in arg_info:
            arg_info[idx] = {"type": fdata["type"], "bf_ranges": [], "hint": fdata.get("hint")}
        if fdata["type"] == "bitfield":
            arg_info[idx]["type"] = "bitfield"
            rng = fdata["bitfield"]
            if rng not in arg_info[idx]["bf_ranges"]:
                arg_info[idx]["bf_ranges"].append(rng)

    # Read arguments in index order
    args = {}
    for idx in sorted(arg_info):
        info = arg_info[idx]

        if info["type"] == "bitfield":
            max_end = max(e for _, e in info["bf_ranges"])
            raw, off = read_typed(data, off, _bf_read_type(max_end))
            args[idx] = ("bf", raw)

        elif info["type"] == "?":
            # Nested Format: read u16 LE index, recursive decode
            nested_idx = struct.unpack_from("<H", data, off)[0]
            off += 2
            entry = table["entries"][str(nested_idx)]
            nfrags = parse_format_string(entry["string"])
            nargs, off = decode_args(data, off, nfrags, table)
            args[idx] = ("fmt", render(nfrags, nargs))

        else:
            val, off = read_typed(data, off, info["type"])
            args[idx] = ("val", val)

    return args, off


def render(fragments, args, parent_hint=None):
    """Render parsed fragments with decoded arguments into a string."""
    buf = []
    for ftype, fdata in fragments:
        if ftype == "literal":
            buf.append(fdata)
        elif ftype == "param":
            idx = fdata["index"]
            hint = fdata.get("hint")
            effective_hint = hint if hint is not None else parent_hint
            kind, val = args[idx]
            if kind == "bf":
                start, end = fdata["bitfield"]
                extracted = extract_bits(val, start, end)
                buf.append(fmt_val(extracted, effective_hint, parent_hint))
            elif kind == "fmt":
                buf.append(val)
            else:
                buf.append(fmt_val(val, effective_hint, parent_hint))
    return "".join(buf)


def decode_all(data, table):
    """Decode all concatenated frames from raw binary data."""
    off = 0
    lines = []
    ts_frags = parse_format_string(table["timestamp"]["string"])

    while off < len(data):
        # 1. Frame index
        frame_idx = struct.unpack_from("<H", data, off)[0]
        off += 2

        # 2. Timestamp
        ts_args, off = decode_args(data, off, ts_frags, table)
        ts_str = render(ts_frags, ts_args)

        # 3. Message
        entry = table["entries"][str(frame_idx)]
        level = LEVELS.get(entry["tag"], "")
        msg_frags = parse_format_string(entry["string"])
        msg_args, off = decode_args(data, off, msg_frags, table)
        msg_str = render(msg_frags, msg_args)

        lines.append(f"{ts_str} {level} {msg_str}")

    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open("/app/string_table.json") as f:
        table = json.load(f)
    with open("/app/frames.bin", "rb") as f:
        data = f.read()

    lines = decode_all(data, table)

    with open("/app/output.txt", "w") as f:
        for line in lines:
            f.write(line + "\n")


if __name__ == "__main__":
    main()
