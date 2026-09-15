#!/usr/bin/env python3

"""
defmt wire-format codec: encode structured logs to binary frames,
decode binary frames to human-readable text.

Usage:
    python3 codec.py encode <input.json>
    python3 codec.py decode <scenario.json>
"""

import json
import struct
import sys
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Binary I/O
# ---------------------------------------------------------------------------
class BinaryReader:
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
        v = int.from_bytes(self.data[self.pos:self.pos + 2], "little", signed=False)
        self.pos += 2
        return v

    def read_u32_le(self) -> int:
        v = int.from_bytes(self.data[self.pos:self.pos + 4], "little", signed=False)
        self.pos += 4
        return v

    def read_u64_le(self) -> int:
        v = int.from_bytes(self.data[self.pos:self.pos + 8], "little", signed=False)
        self.pos += 8
        return v

    def read_u128_le(self) -> int:
        v = int.from_bytes(self.data[self.pos:self.pos + 16], "little", signed=False)
        self.pos += 16
        return v

    def read_n_le_unsigned(self, n: int) -> int:
        v = int.from_bytes(self.data[self.pos:self.pos + n], "little", signed=False)
        self.pos += n
        return v

    def read_n_le_signed(self, n: int) -> int:
        v = int.from_bytes(self.data[self.pos:self.pos + n], "little", signed=True)
        self.pos += n
        return v

    def read_bytes(self, n: int) -> bytes:
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v


class BinaryWriter:
    def __init__(self):
        self.buf = bytearray()

    def write_u8(self, v):
        self.buf.append(v & 0xFF)

    def write_u16_le(self, v):
        self.buf.extend((v & 0xFFFF).to_bytes(2, "little"))

    def write_u32_le(self, v):
        self.buf.extend((v & 0xFFFFFFFF).to_bytes(4, "little"))

    def write_u64_le(self, v):
        self.buf.extend((v & ((1 << 64) - 1)).to_bytes(8, "little"))

    def write_u128_le(self, v):
        self.buf.extend((v & ((1 << 128) - 1)).to_bytes(16, "little"))

    def write_n_le_unsigned(self, v, n):
        self.buf.extend((v & ((1 << (n * 8)) - 1)).to_bytes(n, "little"))

    def write_n_le_signed(self, v, n):
        self.buf.extend(v.to_bytes(n, "little", signed=True))

    def write_bytes(self, data):
        self.buf.extend(data)

    def write_f32(self, v):
        self.buf.extend(struct.pack("<f", v))

    def write_f64(self, v):
        self.buf.extend(struct.pack("<d", v))

    def to_hex(self):
        return self.buf.hex()


# ---------------------------------------------------------------------------
# Format string parser
# ---------------------------------------------------------------------------
def parse_format_string(fmt_str):
    """Parse a defmt format string into fragments.

    Returns list of:
      ('literal', text)
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

        if i + 1 < len(fmt_str) and fmt_str[i + 1] == "{":
            i += 2
            continue

        if i > end_pos:
            literal = fmt_str[end_pos:i].replace("{{", "{").replace("}}", "}")
            fragments.append(("literal", literal))

        close_idx = fmt_str.index("}", i + 1)
        param_str = fmt_str[i + 1:close_idx]

        index, type_str, hint_str = _parse_param(param_str)
        if index is None:
            index = next_arg_index
            next_arg_index += 1

        fragments.append(("param", index, type_str, hint_str))
        end_pos = close_idx + 1
        i = end_pos

    if end_pos < len(fmt_str):
        literal = fmt_str[end_pos:].replace("{{", "{").replace("}}", "}")
        fragments.append(("literal", literal))

    return fragments


def _parse_param(s):
    """Parse '{...}' content into (index_or_None, type_str, hint_str_or_None)."""
    index = None
    type_str = "?"
    hint_str = None

    idx_end = 0
    while idx_end < len(s) and s[idx_end].isdigit():
        idx_end += 1
    if idx_end > 0:
        index = int(s[:idx_end])
    s = s[idx_end:]

    if s.startswith("="):
        s = s[1:]
        colon_pos = s.find(":")
        if colon_pos >= 0:
            type_str = s[:colon_pos]
            s = s[colon_pos:]
        else:
            type_str = s
            s = ""

    if s.startswith(":"):
        hint_str = s[1:]
        if not hint_str:
            hint_str = None

    return index, type_str, hint_str


def _parse_hint(hint_str):
    if hint_str is None:
        return None

    s = hint_str
    zero_pad = 0

    if len(s) >= 2 and s[0] == "0" and s[1].isdigit():
        j = 1
        while j < len(s) and s[j].isdigit():
            j += 1
        zero_pad = int(s[1:j])
        s = s[j:]

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
# Encoder
# ---------------------------------------------------------------------------
class DefmtEncoder:
    def __init__(self, table):
        self.entries = {int(k): v for k, v in table["entries"].items()}
        self.timestamp = table.get("timestamp")

    def encode_log(self, log_entry):
        """Encode a structured log entry to a hex string."""
        writer = BinaryWriter()
        index = log_entry["index"]
        writer.write_u16_le(index)

        # Timestamp arguments
        if self.timestamp and "timestamp_values" in log_entry:
            ts_format = self.timestamp["format"]
            self._write_args(writer, ts_format, log_entry["timestamp_values"])

        # Message arguments
        entry = self.entries[index]
        fmt = entry["format"]
        self._write_args(writer, fmt, log_entry["values"])

        return writer.to_hex()

    def _write_args(self, writer, fmt_str, values):
        """Write argument values to the binary writer based on the format string."""
        fragments = parse_format_string(fmt_str)

        # Collect unique params in index order
        params_by_idx = {}
        bitfield_ranges = {}

        for frag in fragments:
            if frag[0] != "param":
                continue
            _, idx, type_str, _ = frag
            if idx not in params_by_idx:
                params_by_idx[idx] = type_str
            if ".." in type_str:
                parts = type_str.split("..")
                start, end = int(parts[0]), int(parts[1])
                if idx not in bitfield_ranges:
                    bitfield_ranges[idx] = (start, end)
                else:
                    cur_s, cur_e = bitfield_ranges[idx]
                    bitfield_ranges[idx] = (min(cur_s, start), max(cur_e, end))

        # Serialize in index order
        val_idx = 0
        for idx in sorted(params_by_idx.keys()):
            type_str = params_by_idx[idx]
            value = values[val_idx]
            val_idx += 1

            if idx in bitfield_ranges:
                # Bitfield: value is hex string of raw bytes
                raw = bytes.fromhex(value)
                writer.write_bytes(raw)
            elif type_str in UINT_SIZES:
                size = UINT_SIZES[type_str]
                writer.write_n_le_unsigned(int(value), size)
            elif type_str in INT_SIZES:
                size = INT_SIZES[type_str]
                writer.write_n_le_signed(int(value), size)
            elif type_str == "bool":
                writer.write_u8(1 if value else 0)
            elif type_str == "char":
                writer.write_u32_le(ord(value))
            elif type_str == "str":
                encoded = value.encode("utf-8")
                writer.write_u32_le(len(encoded))
                writer.write_bytes(encoded)
            elif type_str == "[u8]":
                raw = bytes.fromhex(value)
                writer.write_u32_le(len(raw))
                writer.write_bytes(raw)
            elif type_str.startswith("[u8;") and type_str.endswith("]"):
                raw = bytes.fromhex(value)
                writer.write_bytes(raw)
            elif type_str == "?" or type_str == "":
                # Nested Format
                sub_idx = value["format_ref"]
                writer.write_u16_le(sub_idx)
                sub_entry = self.entries[sub_idx]
                sub_fmt = sub_entry["format"]
                self._write_args(writer, sub_fmt, value["values"])
            elif type_str == "[?]":
                # FormatSlice
                elements = value
                writer.write_u32_le(len(elements))
                for elem in elements:
                    sub_idx = elem["format_ref"]
                    writer.write_u16_le(sub_idx)
                    sub_entry = self.entries[sub_idx]
                    sub_fmt = sub_entry["format"]
                    self._write_args(writer, sub_fmt, elem["values"])
            elif type_str.startswith("[?;") and type_str.endswith("]"):
                # Fixed-length format array
                elements = value
                for elem in elements:
                    sub_idx = elem["format_ref"]
                    writer.write_u16_le(sub_idx)
                    sub_entry = self.entries[sub_idx]
                    sub_fmt = sub_entry["format"]
                    self._write_args(writer, sub_fmt, elem["values"])
            elif type_str == "__internal_FormatSequence":
                # FormatSequence: u16 LE indices with args, zero-terminated
                elements = value
                for elem in elements:
                    sub_idx = elem["format_ref"]
                    writer.write_u16_le(sub_idx)
                    sub_entry = self.entries[sub_idx]
                    sub_fmt = sub_entry["format"]
                    self._write_args(writer, sub_fmt, elem["values"])
                writer.write_u16_le(0)  # terminator
            elif type_str == "f32":
                writer.write_f32(float(value))
            elif type_str == "f64":
                writer.write_f64(float(value))
            else:
                raise ValueError(f"Unknown type for encoding: {type_str!r}")


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------
class DefmtDecoder:
    def __init__(self, table):
        self.entries = {int(k): v for k, v in table["entries"].items()}
        self.timestamp = table.get("timestamp")

    def decode_frame(self, frame_bytes):
        reader = BinaryReader(frame_bytes)
        index = reader.read_u16_le()

        timestamp_str = None
        if self.timestamp:
            ts_format = self.timestamp["format"]
            ts_args = self._read_args(reader, ts_format)
            ts_fragments = parse_format_string(ts_format)
            timestamp_str = self._format_fragments(ts_fragments, ts_args, None)

        entry = self.entries[index]
        tag = entry["tag"]
        fmt = entry["format"]

        level = {
            "Trace": "TRACE", "Debug": "DEBUG", "Info": "INFO",
            "Warn": "WARN", "Error": "ERROR",
        }.get(tag)

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

    def _read_args(self, reader, fmt_str):
        fragments = parse_format_string(fmt_str)

        params_by_idx = {}
        for frag in fragments:
            if frag[0] != "param":
                continue
            _, idx, type_str, _hint = frag
            if idx not in params_by_idx:
                params_by_idx[idx] = type_str

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

        args = {}
        for idx in sorted(params_by_idx.keys()):
            type_str = params_by_idx[idx]

            if idx in bitfield_ranges:
                min_bit, max_bit = bitfield_ranges[idx]
                min_byte = min_bit // 8
                max_byte = (max_bit - 1) // 8  # correct: (max_bit-1)//8
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
                    sub_idx = reader.read_u16_le()  # correct: u16 LE
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
                raw = reader.read_bytes(4)
                args[idx] = ("float", struct.unpack("<f", raw)[0])
            elif type_str == "f64":
                raw = reader.read_bytes(8)
                args[idx] = ("float", struct.unpack("<d", raw)[0])
            else:
                raise ValueError(f"Unknown type: {type_str!r}")

        return args

    def _format_fragments(self, fragments, args, parent_hint_str):
        result = []
        for frag in fragments:
            if frag[0] == "literal":
                result.append(frag[1])
            elif frag[0] == "param":
                _, idx, type_str, hint_str = frag
                arg = args[idx]
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
                # Debug hint: delegate to parent
                return self._fmt_uint(value, parent_hint_str)
            return self._fmt_uint(value, eff_hint_str)

        if kind == "int":
            value = arg[1]
            int_type = arg[2]
            h = _parse_hint(eff_hint_str)
            if h and h["type"] == "?":
                # Debug hint: delegate to parent
                return self._fmt_int(value, int_type, parent_hint_str)
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
        return str(value)

    def _fmt_int(self, value, int_type, hint_str):
        h = _parse_hint(hint_str)
        if h is None:
            return str(value)

        zp = h["zero_pad"]
        alt = h["alternate"]
        ht = h["type"]

        if ht in ("x", "X", "b", "o"):
            # Use type-specific bit width for two's complement conversion
            bits = INT_BITS.get(int_type, 32)
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
                milliseconds=value
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 1000:03d}Z"
        if precision == "us":
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                microseconds=value
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 1000000:06d}Z"
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
    if len(sys.argv) != 3:
        print("Usage: python3 codec.py <encode|decode> <file.json>", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    with open(sys.argv[2]) as f:
        data = json.load(f)

    if mode == "encode":
        encoder = DefmtEncoder(data["table"])
        for log in data["logs"]:
            print(encoder.encode_log(log))
    elif mode == "decode":
        decoder = DefmtDecoder(data["table"])
        for frame_hex in data["frames"]:
            frame_bytes = bytes.fromhex(frame_hex)
            print(decoder.decode_frame(frame_bytes))
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
