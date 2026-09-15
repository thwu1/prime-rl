#!/usr/bin/env python3
"""
defmt wire format decoder.

Usage: python3 decoder.py scenario.json

Reads a scenario JSON file containing a string table and hex-encoded binary
frames, decodes each frame, and prints the human-readable output to stdout.
"""

import json
import sys
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Binary reader
# ---------------------------------------------------------------------------
class BinaryReader:
    """Reads binary data sequentially from a byte buffer."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def read_u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def read_u16_le(self) -> int:
        v = int.from_bytes(self.data[self.pos : self.pos + 2], "little", signed=False)
        self.pos += 2
        return v

    def read_u32_le(self) -> int:
        v = int.from_bytes(self.data[self.pos : self.pos + 4], "little", signed=False)
        self.pos += 4
        return v

    def read_u64_le(self) -> int:
        v = int.from_bytes(self.data[self.pos : self.pos + 8], "little", signed=False)
        self.pos += 8
        return v

    def read_u128_le(self) -> int:
        v = int.from_bytes(self.data[self.pos : self.pos + 16], "little", signed=False)
        self.pos += 16
        return v

    def read_n_le_unsigned(self, n: int) -> int:
        v = int.from_bytes(self.data[self.pos : self.pos + n], "little", signed=False)
        self.pos += n
        return v

    def read_n_le_signed(self, n: int) -> int:
        v = int.from_bytes(self.data[self.pos : self.pos + n], "little", signed=True)
        self.pos += n
        return v

    def read_bytes(self, n: int) -> bytes:
        v = self.data[self.pos : self.pos + n]
        self.pos += n
        return v


# ---------------------------------------------------------------------------
# Format string parser
# ---------------------------------------------------------------------------
def parse_format_string(fmt_str):
    """Parse a defmt format string into a list of fragments.

    Returns a list where each element is one of:
      ('literal', text_str)
      ('param', arg_index, type_str, hint_str_or_None)
    """
    fragments = []
    end_pos = 0
    next_arg_index = 0

    i = 0
    while i < len(fmt_str):
        if fmt_str[i] != "{":
            i += 1
            continue

        # Escaped {{
        if i + 1 < len(fmt_str) and fmt_str[i + 1] == "{":
            i += 2
            continue

        # Save literal before this parameter
        if i > end_pos:
            literal = fmt_str[end_pos:i].replace("{{", "{").replace("}}", "}")
            fragments.append(("literal", literal))

        # Find closing brace
        close_idx = fmt_str.index("}", i + 1)
        param_str = fmt_str[i + 1 : close_idx]

        index, type_str, hint_str = _parse_param(param_str)
        if index is None:
            index = next_arg_index
            next_arg_index += 1
        # Explicit indices do NOT advance next_arg_index

        fragments.append(("param", index, type_str, hint_str))
        end_pos = close_idx + 1
        i = end_pos

    # Trailing literal
    if end_pos < len(fmt_str):
        literal = fmt_str[end_pos:].replace("{{", "{").replace("}}", "}")
        fragments.append(("literal", literal))

    return fragments


def _parse_param(s):
    """Parse '{...}' content into (index_or_None, type_str, hint_str_or_None)."""
    index = None
    type_str = "?"  # default type is Format
    hint_str = None

    # Optional index (leading digits)
    idx_end = 0
    while idx_end < len(s) and s[idx_end].isdigit():
        idx_end += 1
    if idx_end > 0:
        index = int(s[:idx_end])
    s = s[idx_end:]

    # Optional type (after '=')
    if s.startswith("="):
        s = s[1:]
        colon_pos = s.find(":")
        if colon_pos >= 0:
            type_str = s[:colon_pos]
            s = s[colon_pos:]
        else:
            type_str = s
            s = ""

    # Optional hint (after ':')
    if s.startswith(":"):
        hint_str = s[1:]
        if not hint_str:
            hint_str = None

    return index, type_str, hint_str


def _parse_hint(hint_str):
    """Parse a hint string like '04x' into components.

    Returns dict: {zero_pad: int, alternate: bool, type: str} or None.
    """
    if hint_str is None:
        return None

    s = hint_str
    zero_pad = 0

    # Optional zero_pad: literal '0' followed by digits
    if len(s) >= 2 and s[0] == "0" and s[1].isdigit():
        j = 1
        while j < len(s) and s[j].isdigit():
            j += 1
        zero_pad = int(s[1:j])
        s = s[j:]

    # Optional alternate flag
    alternate = s.startswith("#")
    if alternate:
        s = s[1:]

    return {"zero_pad": zero_pad, "alternate": alternate, "type": s}


# ---------------------------------------------------------------------------
# Type info
# ---------------------------------------------------------------------------
UINT_SIZES = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "u128": 16, "usize": 4}
INT_SIZES = {"i8": 1, "i16": 2, "i32": 4, "i64": 8, "i128": 16, "isize": 4}
INT_BITS = {"i8": 8, "i16": 16, "i32": 32, "i64": 64, "i128": 128, "isize": 32}


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------
class DefmtDecoder:
    def __init__(self, table):
        self.entries = {int(k): v for k, v in table["entries"].items()}
        self.timestamp = table.get("timestamp")

    def decode_frame(self, frame_bytes):
        reader = BinaryReader(frame_bytes)

        # Frame index
        index = reader.read_u16_le()

        # Timestamp
        timestamp_str = None
        if self.timestamp:
            ts_format = self.timestamp["format"]
            ts_args = self._read_args(reader, ts_format)
            ts_fragments = parse_format_string(ts_format)
            timestamp_str = self._format_fragments(ts_fragments, ts_args, None)

        # Look up entry
        entry = self.entries[index]
        tag = entry["tag"]
        fmt = entry["format"]

        # Level
        level = {
            "Trace": "TRACE",
            "Debug": "DEBUG",
            "Info": "INFO",
            "Warn": "WARN",
            "Error": "ERROR",
        }.get(tag)

        # Read and format message
        args = self._read_args(reader, fmt)
        fragments = parse_format_string(fmt)
        message = self._format_fragments(fragments, args, None)

        parts = []
        if timestamp_str:
            parts.append(timestamp_str)
        if level:
            parts.append(level)
        parts.append(message)
        return " ".join(parts)

    # -- argument reading --------------------------------------------------

    def _read_args(self, reader, fmt_str):
        """Read arguments from binary data based on the format string.

        Returns a dict mapping argument index to an Arg tuple.
        """
        fragments = parse_format_string(fmt_str)

        # Collect params grouped by index
        params_by_idx = {}
        for frag in fragments:
            if frag[0] != "param":
                continue
            _, idx, type_str, _hint = frag
            if idx not in params_by_idx:
                params_by_idx[idx] = type_str

        # Detect bitfield ranges per index
        bitfield_ranges = {}
        for frag in fragments:
            if frag[0] != "param":
                continue
            _, idx, type_str, _ = frag
            if ".." in type_str:
                parts = type_str.split("..")
                start, end = int(parts[0]), int(parts[1])
                if idx not in bitfield_ranges:
                    bitfield_ranges[idx] = (start, end)
                else:
                    cur_s, cur_e = bitfield_ranges[idx]
                    bitfield_ranges[idx] = (min(cur_s, start), max(cur_e, end))

        # Read args in index order
        args = {}
        for idx in sorted(params_by_idx.keys()):
            type_str = params_by_idx[idx]

            if idx in bitfield_ranges:
                min_bit, max_bit = bitfield_ranges[idx]
                min_byte = min_bit // 8
                max_byte = max_bit // 8
                n_bytes = max_byte - min_byte + 1
                raw = reader.read_bytes(n_bytes)
                value = int.from_bytes(raw, "little", signed=False)
                value <<= min_byte * 8
                args[idx] = ("bitfield", value)
            elif type_str in UINT_SIZES:
                size = UINT_SIZES[type_str]
                args[idx] = ("uint", reader.read_n_le_unsigned(size))
            elif type_str in INT_SIZES:
                size = INT_SIZES[type_str]
                args[idx] = ("int", reader.read_n_le_signed(size), type_str)
            elif type_str == "bool":
                args[idx] = ("bool", reader.read_u8() != 0)
            elif type_str == "char":
                cp = reader.read_u32_le()
                args[idx] = ("char", chr(cp))
            elif type_str == "str":
                length = reader.read_u32_le()
                data = reader.read_bytes(length)
                args[idx] = ("str", data.decode("utf-8"))
            elif type_str == "[u8]":
                length = reader.read_u32_le()
                data = reader.read_bytes(length)
                args[idx] = ("byte_slice", list(data))
            elif type_str == "?" or type_str == "":
                sub_idx = reader.read_u16_le()
                sub_entry = self.entries[sub_idx]
                sub_fmt = sub_entry["format"]
                sub_args = self._read_args(reader, sub_fmt)
                args[idx] = ("format", sub_fmt, sub_args)
            elif type_str == "[?]":
                count = reader.read_u32_le()
                elements = []
                for _ in range(count):
                    sub_idx = reader.read_u16_le()
                    sub_entry = self.entries[sub_idx]
                    sub_fmt = sub_entry["format"]
                    sub_args = self._read_args(reader, sub_fmt)
                    elements.append((sub_fmt, sub_args))
                args[idx] = ("format_slice", elements)
            elif type_str == "__internal_FormatSequence":
                elements = []
                while True:
                    sub_idx = reader.read_u8()
                    if sub_idx == 0:
                        break
                    sub_entry = self.entries[sub_idx]
                    sub_fmt = sub_entry["format"]
                    sub_args = self._read_args(reader, sub_fmt)
                    elements.append((sub_fmt, sub_args))
                args[idx] = ("format_sequence", elements)
            elif type_str.startswith("[u8;") and type_str.endswith("]"):
                n = int(type_str[4:-1].strip())
                data = reader.read_bytes(n)
                args[idx] = ("byte_slice", list(data))
            elif type_str.startswith("[?;") and type_str.endswith("]"):
                n = int(type_str[3:-1].strip())
                elements = []
                for _ in range(n):
                    sub_idx = reader.read_u16_le()
                    sub_entry = self.entries[sub_idx]
                    sub_fmt = sub_entry["format"]
                    sub_args = self._read_args(reader, sub_fmt)
                    elements.append((sub_fmt, sub_args))
                args[idx] = ("format_slice", elements)
            elif type_str == "f32":
                import struct

                raw = reader.read_bytes(4)
                args[idx] = ("float", struct.unpack("<f", raw)[0])
            elif type_str == "f64":
                import struct

                raw = reader.read_bytes(8)
                args[idx] = ("float", struct.unpack("<d", raw)[0])
            else:
                raise ValueError(f"Unknown type: {type_str!r}")

        return args

    # -- formatting --------------------------------------------------------

    def _format_fragments(self, fragments, args, parent_hint_str):
        """Format parsed fragments with argument values."""
        result = []
        for frag in fragments:
            if frag[0] == "literal":
                result.append(frag[1])
            elif frag[0] == "param":
                _, idx, type_str, hint_str = frag
                arg = args[idx]
                # Effective hint: param's hint if present, else parent
                eff_hint = hint_str if hint_str is not None else parent_hint_str
                result.append(
                    self._format_arg(arg, type_str, eff_hint, parent_hint_str)
                )
        return "".join(result)

    def _format_arg(self, arg, type_str, eff_hint_str, parent_hint_str):
        kind = arg[0]

        if kind == "bool":
            return "true" if arg[1] else "false"

        if kind == "char":
            return arg[1]

        if kind == "str":
            s = arg[1]
            h = _parse_hint(eff_hint_str)
            if h and h["type"] == "?":
                return f'"{s}"'
            return s

        if kind == "uint":
            value = arg[1]
            h = _parse_hint(eff_hint_str)
            if h and h["type"] == "?":
                return self._fmt_uint(value, None)
            return self._fmt_uint(value, eff_hint_str)

        if kind == "int":
            value = arg[1]
            int_type = arg[2]
            h = _parse_hint(eff_hint_str)
            if h and h["type"] == "?":
                return self._fmt_int(value, int_type, None)
            return self._fmt_int(value, int_type, eff_hint_str)

        if kind == "float":
            return str(arg[1])

        if kind == "byte_slice":
            data = arg[1]
            return self._fmt_byte_slice(data, eff_hint_str)

        if kind == "format":
            sub_fmt = arg[1]
            sub_args = arg[2]
            sub_frags = parse_format_string(sub_fmt)
            if parent_hint_str == "a":
                return self._format_fragments(sub_frags, sub_args, parent_hint_str)
            return self._format_fragments(sub_frags, sub_args, eff_hint_str)

        if kind == "format_slice":
            elements = arg[1]
            parts = []
            for sub_fmt, sub_args in elements:
                sub_frags = parse_format_string(sub_fmt)
                parts.append(
                    self._format_fragments(sub_frags, sub_args, eff_hint_str)
                )
            return "[" + ", ".join(parts) + "]"

        if kind == "format_sequence":
            elements = arg[1]
            parts = []
            for sub_fmt, sub_args in elements:
                sub_frags = parse_format_string(sub_fmt)
                parts.append(
                    self._format_fragments(sub_frags, sub_args, eff_hint_str)
                )
            return "".join(parts)

        if kind == "bitfield":
            value = arg[1]
            parts = type_str.split("..")
            start, end = int(parts[0]), int(parts[1])
            left_zeroes = 128 - end
            right_zeroes = left_zeroes + start
            mask = (1 << 128) - 1
            extracted = ((value << left_zeroes) & mask) >> right_zeroes
            return self._fmt_uint(extracted, eff_hint_str)

        return str(arg)

    # -- number formatting -------------------------------------------------

    def _fmt_uint(self, value, hint_str):
        h = _parse_hint(hint_str)
        if h is None:
            return str(value)

        zp = h["zero_pad"]
        alt = h["alternate"]
        ht = h["type"]

        if ht == "x":
            return self._hex_str(value, False, alt, zp)
        if ht == "X":
            return self._hex_str(value, True, alt, zp)
        if ht == "b":
            return self._bin_str(value, alt, zp)
        if ht == "o":
            return self._oct_str(value, alt, zp)
        if ht == "" or ht is None:
            return f"{value:0{zp}d}" if zp else str(value)
        if ht == "us":
            secs = value // 1_000_000
            micros = value % 1_000_000
            return f"{secs}.{micros:06d}"
        if ht == "ms":
            secs = value // 1_000
            millis = value % 1_000
            return f"{secs}.{millis:03d}"
        if ht.startswith("iso8601"):
            return self._iso8601(value, ht[7:])
        if ht == "?":
            return str(value)

        # Unknown hint -- fall back to decimal
        return str(value)

    def _fmt_int(self, value, int_type, hint_str):
        h = _parse_hint(hint_str)
        if h is None:
            return str(value)

        zp = h["zero_pad"]
        alt = h["alternate"]
        ht = h["type"]

        if ht in ("x", "X", "b", "o"):
            bits = 32
            uval = value if value >= 0 else value + (1 << bits)
            if ht == "x":
                return self._hex_str(uval, False, alt, zp)
            if ht == "X":
                return self._hex_str(uval, True, alt, zp)
            if ht == "b":
                return self._bin_str(uval, alt, zp)
            if ht == "o":
                return self._oct_str(uval, alt, zp)

        if ht == "" or ht is None:
            return f"{value:0{zp}d}" if zp else str(value)

        return str(value)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _hex_str(value, uppercase, alternate, zero_pad):
        digits = format(value, "X" if uppercase else "x")
        if alternate:
            if zero_pad > 2:
                digits = digits.zfill(zero_pad - 2)
            return "0x" + digits
        if zero_pad:
            digits = digits.zfill(zero_pad)
        return digits

    @staticmethod
    def _bin_str(value, alternate, zero_pad):
        digits = format(value, "b")
        if alternate:
            if zero_pad > 2:
                digits = digits.zfill(zero_pad - 2)
            return "0b" + digits
        if zero_pad:
            digits = digits.zfill(zero_pad)
        return digits

    @staticmethod
    def _oct_str(value, alternate, zero_pad):
        digits = format(value, "o")
        if alternate:
            if zero_pad > 2:
                digits = digits.zfill(zero_pad - 2)
            return "0o" + digits
        if zero_pad:
            digits = digits.zfill(zero_pad)
        return digits

    @staticmethod
    def _iso8601(value, precision):
        if precision == "ms":
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                microseconds=value
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 1000000:06d}Z"
        if precision == "us":
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                milliseconds=value
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 1000:03d}Z"
        if precision == "s":
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=value)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return str(value)

    def _fmt_byte_slice(self, data, hint_str):
        h = _parse_hint(hint_str)
        if h and h["type"] in ("x", "X", "b", "o"):
            parts = [self._fmt_uint(b, hint_str) for b in data]
            return "[" + ", ".join(parts) + "]"
        if h and h["type"] == "a":
            buf = 'b"'
            for b in data:
                if b == ord("\t"):
                    buf += "\\t"
                elif b == ord("\n"):
                    buf += "\\n"
                elif b == ord("\r"):
                    buf += "\\r"
                elif b == ord(" "):
                    buf += " "
                elif b == ord('"'):
                    buf += '\\"'
                elif b == ord("\\"):
                    buf += "\\\\"
                elif 33 <= b <= 126:
                    buf += chr(b)
                else:
                    buf += f"\\x{b:02x}"
            buf += '"'
            return buf
        return "[" + ", ".join(str(b) for b in data) + "]"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) != 2:
        print("Usage: python3 decoder.py scenario.json", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        scenario = json.load(f)

    decoder = DefmtDecoder(scenario["table"])
    for frame_hex in scenario["frames"]:
        frame_bytes = bytes.fromhex(frame_hex)
        print(decoder.decode_frame(frame_bytes))


if __name__ == "__main__":
    main()
