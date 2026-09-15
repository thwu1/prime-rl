#!/usr/bin/env python3
"""
Solution: defmt ELF firmware decoder.

Implements:
1. ELF64 parsing to extract .defmt section data
2. .defmt binary format parsing to reconstruct string tables
3. COBS deframing (split at 0x00, decode overhead bytes)
4. CRC-16/CCITT validation (poly=0x1021, init=0xFFFF)
5. String table evaluation (trial-decode all frames, pick best)
6. Full defmt wire format decoding (raw encoding)
7. Output: sorted decoded lines + analysis JSON
"""
import json
import struct
import re
import os


# ============================================================
# ELF64 parsing
# ============================================================

def read_elf_section(elf_path, section_name):
    """Read the contents of a named section from an ELF64 file."""
    with open(elf_path, 'rb') as f:
        data = f.read()

    assert data[:4] == b'\x7fELF', f"Not an ELF file: {elf_path}"
    ei_class = data[4]
    assert ei_class == 2, "Not ELF64"

    e_shoff = struct.unpack_from('<Q', data, 40)[0]
    e_shentsize = struct.unpack_from('<H', data, 58)[0]
    e_shnum = struct.unpack_from('<H', data, 60)[0]
    e_shstrndx = struct.unpack_from('<H', data, 62)[0]

    # Read section header string table
    shstrtab_hdr_off = e_shoff + e_shstrndx * e_shentsize
    shstrtab_off = struct.unpack_from('<Q', data, shstrtab_hdr_off + 24)[0]
    shstrtab_size = struct.unpack_from('<Q', data, shstrtab_hdr_off + 32)[0]
    shstrtab = data[shstrtab_off:shstrtab_off + shstrtab_size]

    # Find the target section
    for i in range(e_shnum):
        hdr_off = e_shoff + i * e_shentsize
        sh_name_off = struct.unpack_from('<I', data, hdr_off)[0]
        name_end = shstrtab.index(b'\x00', sh_name_off)
        name = shstrtab[sh_name_off:name_end].decode('ascii')
        if name == section_name:
            sh_offset = struct.unpack_from('<Q', data, hdr_off + 24)[0]
            sh_size = struct.unpack_from('<Q', data, hdr_off + 32)[0]
            return data[sh_offset:sh_offset + sh_size]

    return None


def parse_defmt_section(section_data):
    """Parse the binary .defmt section into a string table dict."""
    off = 0
    magic = section_data[off:off + 4]
    assert magic == b'dFmT', f"Bad magic: {magic}"
    off += 4

    version = section_data[off]; off += 1
    encoding_byte = section_data[off]; off += 1
    flags = section_data[off]; off += 1
    off += 1  # reserved
    entry_count = struct.unpack_from('<H', section_data, off)[0]; off += 2
    off += 2  # reserved

    table = {
        "encoding": "raw" if encoding_byte == 0 else "rzcobs",
        "entries": {}
    }

    # Timestamp
    if flags & 1:
        tag_len = section_data[off]; off += 1
        tag = section_data[off:off + tag_len].decode('utf-8'); off += tag_len
        fmt_len = struct.unpack_from('<H', section_data, off)[0]; off += 2
        fmt_str = section_data[off:off + fmt_len].decode('utf-8'); off += fmt_len
        table["timestamp"] = {"tag": tag, "string": fmt_str}

    # Entries
    for _ in range(entry_count):
        idx = struct.unpack_from('<H', section_data, off)[0]; off += 2
        tag_len = section_data[off]; off += 1
        tag = section_data[off:off + tag_len].decode('utf-8'); off += tag_len
        fmt_len = struct.unpack_from('<H', section_data, off)[0]; off += 2
        fmt_str = section_data[off:off + fmt_len].decode('utf-8'); off += fmt_len
        table["entries"][str(idx)] = {"tag": tag, "string": fmt_str}

    return table


def load_table_from_elf(elf_path):
    """Load a defmt string table from an ELF firmware file."""
    section = read_elf_section(elf_path, ".defmt")
    if section is None:
        raise ValueError(f"No .defmt section in {elf_path}")
    return parse_defmt_section(section)


# ============================================================
# COBS decode
# ============================================================

def cobs_decode(data):
    """Decode COBS-encoded data. Raises ValueError on malformed input."""
    output = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]
        if code == 0:
            raise ValueError("Unexpected zero in COBS data")
        idx += 1
        for _ in range(code - 1):
            if idx >= len(data):
                raise ValueError("COBS truncated")
            output.append(data[idx])
            idx += 1
        if code < 0xFF and idx < len(data):
            output.append(0)
    return bytes(output)


# ============================================================
# CRC-16/CCITT
# ============================================================

def crc16_ccitt(data):
    """CRC-16/CCITT: polynomial 0x1021, initial value 0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


# ============================================================
# Display hint parsing
# ============================================================

def parse_hint(s):
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


# ============================================================
# Format string parsing
# ============================================================

def parse_param(s):
    result = {"index": None, "type": "?", "hint": None, "bitfield": None}

    idx_end = 0
    while idx_end < len(s) and s[idx_end].isdigit():
        idx_end += 1
    if idx_end > 0 and (idx_end >= len(s) or s[idx_end] in "=:"):
        result["index"] = int(s[:idx_end])
        s = s[idx_end:]

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


# ============================================================
# Binary reading
# ============================================================

_TYPE_STRUCT = {
    "u8": ("<B", 1), "u16": ("<H", 2), "u32": ("<I", 4), "u64": ("<Q", 8),
    "i8": ("<b", 1), "i16": ("<h", 2), "i32": ("<i", 4), "i64": ("<q", 8),
    "f32": ("<f", 4), "f64": ("<d", 8),
    "bool": ("<B", 1), "char": ("<I", 4),
}

_SIGNED_MASKS = {
    "i8": 0xFF, "i16": 0xFFFF, "i32": 0xFFFFFFFF, "i64": 0xFFFFFFFFFFFFFFFF,
}


def read_typed(data, off, ty):
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
    return (val >> start) & ((1 << (end - start)) - 1)


# ============================================================
# Value formatting
# ============================================================

def _fmt_num(val, fmt_type, alt, zp):
    specs = {"x": "x", "X": "X", "b": "b", "o": "o"}
    spec = specs.get(fmt_type, "")
    if alt:
        return format(val, f"#0{zp}{spec}")
    if zp:
        return format(val, f"0{zp}{spec}")
    return format(val, spec)


def fmt_val(val, hint, parent_hint=None, wire_type=None):
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
        if isinstance(val, int) and val < 0 and wire_type in _SIGNED_MASKS:
            val = val & _SIGNED_MASKS[wire_type]
        return _fmt_num(val, ft, alt, zp)

    if kind == "debug":
        if parent_hint is not None:
            return fmt_val(val, parent_hint, None, wire_type)
        return str(val)

    return str(val)


# ============================================================
# Frame decoding
# ============================================================

LEVELS = {
    "Trace": "TRACE", "Debug": "DEBUG", "Info": "INFO",
    "Warn": "WARN", "Error": "ERROR",
}


def decode_args(data, off, fragments, table, parent_hint=None):
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

    args = {}
    for idx in sorted(arg_info):
        info = arg_info[idx]

        if info["type"] == "bitfield":
            max_end = max(e for _, e in info["bf_ranges"])
            raw, off = read_typed(data, off, _bf_read_type(max_end))
            args[idx] = ("bf", raw)

        elif info["type"] == "?":
            nested_idx = struct.unpack_from("<H", data, off)[0]
            off += 2
            entry = table["entries"][str(nested_idx)]
            nfrags = parse_format_string(entry["string"])
            outer_hint = info["hint"] if info["hint"] is not None else parent_hint
            nargs, off = decode_args(data, off, nfrags, table, outer_hint)
            args[idx] = ("fmt", render(nfrags, nargs, outer_hint))

        elif info["type"] == "istr":
            istr_idx = struct.unpack_from("<H", data, off)[0]
            off += 2
            entry = table["entries"][str(istr_idx)]
            args[idx] = ("val", entry["string"])

        elif info["type"] == "__internal_FormatSequence":
            parts = []
            while True:
                variant_idx = struct.unpack_from("<H", data, off)[0]
                off += 2
                if variant_idx == 0:
                    break
                entry = table["entries"][str(variant_idx)]
                nfrags = parse_format_string(entry["string"])
                nargs, off = decode_args(data, off, nfrags, table, parent_hint)
                parts.append(render(nfrags, nargs, parent_hint))
            args[idx] = ("val", "".join(parts))

        else:
            val, off = read_typed(data, off, info["type"])
            args[idx] = ("val", val)

    return args, off


def render(fragments, args, parent_hint=None):
    buf = []
    for ftype, fdata in fragments:
        if ftype == "literal":
            buf.append(fdata)
        elif ftype == "param":
            idx = fdata["index"]
            hint = fdata.get("hint")
            effective_hint = hint if hint is not None else parent_hint
            kind, val = args[idx]
            wire_type = fdata.get("type")
            if kind == "bf":
                start, end = fdata["bitfield"]
                extracted = extract_bits(val, start, end)
                buf.append(fmt_val(extracted, effective_hint, parent_hint))
            elif kind == "fmt":
                buf.append(val)
            else:
                buf.append(fmt_val(val, effective_hint, parent_hint, wire_type))
    return "".join(buf)


def try_decode_frame(frame_data, table):
    try:
        off = 0
        frame_idx = struct.unpack_from("<H", frame_data, off)[0]
        off += 2

        ts_frags = parse_format_string(table["timestamp"]["string"])
        ts_args, off = decode_args(frame_data, off, ts_frags, table)
        ts_str = render(ts_frags, ts_args)

        entry = table["entries"][str(frame_idx)]
        level = LEVELS.get(entry["tag"], "")
        msg_frags = parse_format_string(entry["string"])
        msg_args, off = decode_args(frame_data, off, msg_frags, table)
        msg_str = render(msg_frags, msg_args)

        return f"{ts_str} {level} {msg_str}"
    except Exception:
        return None


# ============================================================
# Main pipeline
# ============================================================

def main():
    # 1. Load string tables from ELF firmware files
    fw_dir = "/app/firmware"
    fw_names = sorted([f for f in os.listdir(fw_dir) if f.endswith(".elf")])
    tables = {}
    for name in fw_names:
        tables[name] = load_table_from_elf(os.path.join(fw_dir, name))

    # 2. Read capture
    with open("/app/capture.bin", "rb") as f:
        capture = f.read()

    # 3. Split into COBS frames at 0x00 delimiters
    cobs_frames = []
    start = 0
    for i in range(len(capture)):
        if capture[i] == 0x00:
            if i > start:
                cobs_frames.append(capture[start:i])
            start = i + 1

    total_frames = len(cobs_frames)

    # 4. COBS-decode and CRC-validate each frame
    valid_payloads = []
    corrupt_indices = []

    for idx, cobs_data in enumerate(cobs_frames):
        try:
            decoded = cobs_decode(cobs_data)
        except ValueError:
            corrupt_indices.append(idx)
            continue

        if len(decoded) < 4:
            corrupt_indices.append(idx)
            continue

        payload = decoded[:-2]
        crc_received = struct.unpack_from("<H", decoded, len(decoded) - 2)[0]
        crc_computed = crc16_ccitt(payload)

        if crc_received != crc_computed:
            corrupt_indices.append(idx)
        else:
            valid_payloads.append((idx, payload))

    # 5. Determine correct firmware by trial decoding
    best_fw = None
    best_count = -1
    for name, table in tables.items():
        success = 0
        for _, payload in valid_payloads:
            result = try_decode_frame(payload, table)
            if result is not None:
                success += 1
        if success > best_count:
            best_count = success
            best_fw = name

    # 6. Decode all valid frames with the correct table
    table = tables[best_fw]
    lines = []
    for _, payload in valid_payloads:
        line = try_decode_frame(payload, table)
        if line:
            lines.append(line)

    # 7. Sort by timestamp
    def ts_key(line):
        return float(line.split(" ")[0])
    lines.sort(key=ts_key)

    # 8. Write output
    with open("/app/output.txt", "w") as f:
        for line in lines:
            f.write(line + "\n")

    # 9. Write analysis
    analysis = {
        "correct_firmware": best_fw,
        "total_frames": total_frames,
        "valid_frames": len(valid_payloads),
        "corrupt_frame_indices": sorted(corrupt_indices),
    }
    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)


if __name__ == "__main__":
    main()
