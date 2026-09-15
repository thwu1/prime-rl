#!/usr/bin/env python3
"""
Redis RDB file parser.
Reads an RDB dump file and outputs a JSON representation of all stored data.
Supports RDB versions up to 11 (Redis 7.x).
"""
import struct
import sys
import json


class RDBParser:
    def __init__(self, filepath):
        with open(filepath, "rb") as f:
            self.data = f.read()
        self.pos = 0
        self.databases = {}
        self.current_db = None

    # ------------------------------------------------------------------
    # Low-level readers
    # ------------------------------------------------------------------

    def read_byte(self):
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_bytes(self, n):
        result = self.data[self.pos : self.pos + n]
        self.pos += n
        return result

    def read_uint_le(self, n):
        return int.from_bytes(self.read_bytes(n), "little", signed=False)

    def read_int_le(self, n):
        return int.from_bytes(self.read_bytes(n), "little", signed=True)

    # ------------------------------------------------------------------
    # Length encoding
    # ------------------------------------------------------------------

    def read_length(self):
        """Read a length-encoded value.

        Returns (value, is_special).  When *is_special* is True the value
        is one of the RDB_ENC_* constants (0 = int8, 1 = int16, 2 = int32,
        3 = LZF).
        """
        first = self.read_byte()
        top2 = (first & 0xC0) >> 6

        if top2 == 0:  # 00xxxxxx → 6-bit length
            return (first & 0x3F, False)
        elif top2 == 1:  # 01xxxxxx → 14-bit length
            second = self.read_byte()
            return (((first & 0x3F) << 8) | second, False)
        elif top2 == 2:  # 10xxxxxx → 32-bit or 64-bit
            if first == 0x80:
                return (struct.unpack(">I", self.read_bytes(4))[0], False)
            elif first == 0x81:
                return (struct.unpack(">Q", self.read_bytes(8))[0], False)
            else:
                return (struct.unpack(">I", self.read_bytes(4))[0], False)
        else:  # 11xxxxxx → special encoding
            return (first & 0x3F, True)

    # ------------------------------------------------------------------
    # String decoding
    # ------------------------------------------------------------------

    def read_string(self):
        """Read and decode a string (may be integer-encoded or LZF)."""
        length, is_special = self.read_length()
        if not is_special:
            return self.read_bytes(length).decode("utf-8", errors="replace")
        if length == 0:
            return str(self.read_int_le(1))
        elif length == 1:
            return str(self.read_int_le(2))
        elif length == 2:
            return str(self.read_int_le(4))
        elif length == 3:
            clen, _ = self.read_length()
            ulen, _ = self.read_length()
            compressed = self.read_bytes(clen)
            return self._lzf_decompress(compressed, ulen).decode(
                "utf-8", errors="replace"
            )
        raise ValueError(f"Unknown special string encoding: {length}")

    def read_string_raw(self):
        """Read a string and return the raw bytes (no UTF-8 decode)."""
        length, is_special = self.read_length()
        if not is_special:
            return self.read_bytes(length)
        if length == 0:
            return str(self.read_int_le(1)).encode()
        elif length == 1:
            return str(self.read_int_le(2)).encode()
        elif length == 2:
            return str(self.read_int_le(4)).encode()
        elif length == 3:
            clen, _ = self.read_length()
            ulen, _ = self.read_length()
            compressed = self.read_bytes(clen)
            return self._lzf_decompress(compressed, ulen)
        raise ValueError(f"Unknown special string encoding: {length}")

    # ------------------------------------------------------------------
    # LZF decompression
    # ------------------------------------------------------------------

    @staticmethod
    def _lzf_decompress(data, expected_len):
        out = bytearray()
        i = 0
        while i < len(data):
            ctrl = data[i]
            i += 1
            if ctrl < 32:
                # Literal run: copy ctrl+1 bytes
                n = ctrl + 1
                out.extend(data[i : i + n])
                i += n
            else:
                # Back-reference
                length = ctrl >> 5
                if length == 7:
                    length += data[i]
                    i += 1
                length += 2
                offset = ((ctrl & 0x1F) << 8) | data[i]
                i += 1
                offset += 1
                ref = len(out) - offset
                for j in range(length):
                    out.append(out[ref + j])
        if len(out) != expected_len:
            raise ValueError(
                f"LZF: got {len(out)} bytes, expected {expected_len}"
            )
        return bytes(out)

    # ------------------------------------------------------------------
    # Listpack
    # ------------------------------------------------------------------

    @staticmethod
    def _backlen_size(entry_len):
        if entry_len <= 127:
            return 1
        if entry_len < 16383:
            return 2
        if entry_len < 2097151:
            return 3
        if entry_len < 268435455:
            return 4
        return 5

    def _parse_listpack(self, raw):
        """Parse a Redis listpack blob into a list of Python strings."""
        entries = []
        pos = 0

        # Header: 4-byte total_bytes + 2-byte num_elements
        _total_bytes = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        num_elements = struct.unpack_from("<H", raw, pos)[0]
        pos += 2

        for _ in range(num_elements):
            if pos >= len(raw) or raw[pos] == 0xFF:
                break

            entry_start = pos
            first = raw[pos]
            pos += 1

            if (first & 0x80) == 0:
                # 7-bit unsigned int (0–127)
                entries.append(str(first & 0x7F))

            elif (first & 0xC0) == 0x80:
                # 6-bit string length (0–63)
                slen = first & 0x3F
                entries.append(
                    raw[pos : pos + slen].decode("utf-8", errors="replace")
                )
                pos += slen

            elif (first & 0xE0) == 0xC0:
                # 13-bit signed int
                second = raw[pos]
                pos += 1
                uval = ((first & 0x1F) << 8) | second
                val = uval - 8192 if uval >= 4096 else uval
                entries.append(str(val))

            elif first == 0xF1:
                # 16-bit signed int
                val = struct.unpack_from("<h", raw, pos)[0]
                pos += 2
                entries.append(str(val))

            elif first == 0xF2:
                # 24-bit signed int
                b0, b1, b2 = raw[pos], raw[pos + 1], raw[pos + 2]
                pos += 3
                val = b0 | (b1 << 8) | (b2 << 16)
                if val >= (1 << 23):
                    val -= 1 << 24
                entries.append(str(val))

            elif first == 0xF3:
                # 32-bit signed int
                val = struct.unpack_from("<i", raw, pos)[0]
                pos += 4
                entries.append(str(val))

            elif first == 0xF4:
                # 64-bit signed int
                val = struct.unpack_from("<q", raw, pos)[0]
                pos += 8
                entries.append(str(val))

            elif (first & 0xF0) == 0xE0:
                # 12-bit string length
                second = raw[pos]
                pos += 1
                slen = ((first & 0x0F) << 8) | second
                entries.append(
                    raw[pos : pos + slen].decode("utf-8", errors="replace")
                )
                pos += slen

            elif first == 0xF0:
                # 32-bit string length
                slen = struct.unpack_from("<I", raw, pos)[0]
                pos += 4
                entries.append(
                    raw[pos : pos + slen].decode("utf-8", errors="replace")
                )
                pos += slen

            else:
                raise ValueError(f"Unknown listpack encoding: 0x{first:02x}")

            # Skip backlen
            entry_len = pos - entry_start
            pos += self._backlen_size(entry_len)

        return entries

    # ------------------------------------------------------------------
    # Ziplist (older Redis – kept for compatibility)
    # ------------------------------------------------------------------

    def _parse_ziplist(self, raw):
        entries = []
        pos = 0

        _zlbytes = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        _zltail = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        zllen = struct.unpack_from("<H", raw, pos)[0]
        pos += 2

        for _ in range(zllen):
            if pos >= len(raw) or raw[pos] == 0xFF:
                break

            # Previous-entry length
            prev_len = raw[pos]
            pos += 1
            if prev_len == 254:
                pos += 4  # 4-byte prev_len follows (we skip the value)

            enc = raw[pos]

            if (enc & 0xC0) == 0x00:
                slen = enc & 0x3F
                pos += 1
                entries.append(
                    raw[pos : pos + slen].decode("utf-8", errors="replace")
                )
                pos += slen
            elif (enc & 0xC0) == 0x40:
                slen = ((enc & 0x3F) << 8) | raw[pos + 1]
                pos += 2
                entries.append(
                    raw[pos : pos + slen].decode("utf-8", errors="replace")
                )
                pos += slen
            elif (enc & 0xC0) == 0x80:
                pos += 1
                slen = struct.unpack_from(">I", raw, pos)[0]
                pos += 4
                entries.append(
                    raw[pos : pos + slen].decode("utf-8", errors="replace")
                )
                pos += slen
            elif enc == 0xC0:
                pos += 1
                val = struct.unpack_from("<h", raw, pos)[0]
                pos += 2
                entries.append(str(val))
            elif enc == 0xD0:
                pos += 1
                val = struct.unpack_from("<i", raw, pos)[0]
                pos += 4
                entries.append(str(val))
            elif enc == 0xE0:
                pos += 1
                val = struct.unpack_from("<q", raw, pos)[0]
                pos += 8
                entries.append(str(val))
            elif enc == 0xF0:
                pos += 1
                b0, b1, b2 = raw[pos], raw[pos + 1], raw[pos + 2]
                val = b0 | (b1 << 8) | (b2 << 16)
                if val >= (1 << 23):
                    val -= 1 << 24
                pos += 3
                entries.append(str(val))
            elif enc == 0xFE:
                pos += 1
                val = struct.unpack_from("<b", raw, pos)[0]
                pos += 1
                entries.append(str(val))
            elif (enc & 0xF0) == 0xF0 and enc not in (0xF0, 0xFE, 0xFF):
                pos += 1
                val = (enc & 0x0F) - 1
                entries.append(str(val))
            else:
                raise ValueError(f"Unknown ziplist encoding: 0x{enc:02x}")

        return entries

    # ------------------------------------------------------------------
    # Value type dispatch
    # ------------------------------------------------------------------

    def _parse_value(self, vtype):
        # Type 0: String
        if vtype == 0:
            return {"type": "string", "value": self.read_string()}

        # Type 16: Hash in Listpack
        elif vtype == 16:
            raw = self.read_string_raw()
            entries = self._parse_listpack(raw)
            h = {}
            for i in range(0, len(entries), 2):
                h[entries[i]] = entries[i + 1]
            return {"type": "hash", "value": h}

        # Type 17: Sorted set in Listpack
        elif vtype == 17:
            raw = self.read_string_raw()
            entries = self._parse_listpack(raw)
            pairs = []
            for i in range(0, len(entries), 2):
                pairs.append([entries[i], float(entries[i + 1])])
            return {"type": "zset", "value": pairs}

        # Type 18: List in Quicklist2
        elif vtype == 18:
            num_nodes, _ = self.read_length()
            items = []
            for _ in range(num_nodes):
                container, _ = self.read_length()
                if container == 2:  # PACKED → listpack
                    raw = self.read_string_raw()
                    items.extend(self._parse_listpack(raw))
                else:  # PLAIN → single element
                    items.append(self.read_string())
            return {"type": "list", "value": items}

        # Type 20: Set in Listpack
        elif vtype == 20:
            raw = self.read_string_raw()
            entries = self._parse_listpack(raw)
            return {"type": "set", "value": entries}

        # Type 11: Intset
        elif vtype == 11:
            raw = self.read_string_raw()
            encoding = struct.unpack_from("<I", raw, 0)[0]
            count = struct.unpack_from("<I", raw, 4)[0]
            fmt = {2: "<h", 4: "<i", 8: "<q"}[encoding]
            values = []
            for i in range(count):
                offset = 8 + i * encoding
                val = struct.unpack_from(fmt, raw, offset)[0]
                values.append(str(val))
            return {"type": "set", "value": values}

        # Type 1: List (old linkedlist)
        elif vtype == 1:
            count, _ = self.read_length()
            return {
                "type": "list",
                "value": [self.read_string() for _ in range(count)],
            }

        # Type 2: Set (hashtable)
        elif vtype == 2:
            count, _ = self.read_length()
            return {
                "type": "set",
                "value": [self.read_string() for _ in range(count)],
            }

        # Type 4: Hash (hashtable)
        elif vtype == 4:
            count, _ = self.read_length()
            h = {}
            for _ in range(count):
                k = self.read_string()
                v = self.read_string()
                h[k] = v
            return {"type": "hash", "value": h}

        # Type 3: Sorted set (old skiplist format)
        elif vtype == 3:
            count, _ = self.read_length()
            pairs = []
            for _ in range(count):
                member = self.read_string()
                slen = self.read_byte()
                if slen == 253:
                    score = float("nan")
                elif slen == 254:
                    score = float("inf")
                elif slen == 255:
                    score = float("-inf")
                else:
                    score = float(self.read_bytes(slen).decode("ascii"))
                pairs.append([member, score])
            return {"type": "zset", "value": pairs}

        # Type 5: Sorted set v2 (binary double)
        elif vtype == 5:
            count, _ = self.read_length()
            pairs = []
            for _ in range(count):
                member = self.read_string()
                score = struct.unpack("<d", self.read_bytes(8))[0]
                pairs.append([member, score])
            return {"type": "zset", "value": pairs}

        # Type 14: List in Quicklist v1 (ziplist nodes)
        elif vtype == 14:
            count, _ = self.read_length()
            items = []
            for _ in range(count):
                raw = self.read_string_raw()
                items.extend(self._parse_ziplist(raw))
            return {"type": "list", "value": items}

        # Type 13: Hash in Ziplist
        elif vtype == 13:
            raw = self.read_string_raw()
            entries = self._parse_ziplist(raw)
            h = {}
            for i in range(0, len(entries), 2):
                h[entries[i]] = entries[i + 1]
            return {"type": "hash", "value": h}

        # Type 12: Sorted set in Ziplist
        elif vtype == 12:
            raw = self.read_string_raw()
            entries = self._parse_ziplist(raw)
            pairs = []
            for i in range(0, len(entries), 2):
                pairs.append([entries[i], float(entries[i + 1])])
            return {"type": "zset", "value": pairs}

        # Type 10: Ziplist (as list)
        elif vtype == 10:
            raw = self.read_string_raw()
            return {"type": "list", "value": self._parse_ziplist(raw)}

        else:
            raise ValueError(f"Unsupported RDB value type: {vtype}")

    # ------------------------------------------------------------------
    # Main parse loop
    # ------------------------------------------------------------------

    def parse(self):
        # Header
        magic = self.read_bytes(5)
        if magic != b"REDIS":
            raise ValueError(f"Invalid RDB magic: {magic!r}")
        _version = self.read_bytes(4).decode("ascii")

        while self.pos < len(self.data):
            opcode = self.read_byte()

            if opcode == 0xFA:  # AUX
                self.read_string()
                self.read_string()

            elif opcode == 0xFE:  # SELECTDB
                db_id, _ = self.read_length()
                self.current_db = str(db_id)
                if self.current_db not in self.databases:
                    self.databases[self.current_db] = {}

            elif opcode == 0xFB:  # RESIZEDB
                self.read_length()
                self.read_length()

            elif opcode == 0xFC:  # EXPIRETIME_MS
                expiry_ms = self.read_uint_le(8)
                vtype = self.read_byte()
                key = self.read_string()
                entry = self._parse_value(vtype)
                entry["expiry_ms"] = expiry_ms
                self.databases[self.current_db][key] = entry

            elif opcode == 0xFD:  # EXPIRETIME (seconds)
                expiry_s = self.read_uint_le(4)
                vtype = self.read_byte()
                key = self.read_string()
                entry = self._parse_value(vtype)
                entry["expiry_ms"] = expiry_s * 1000
                self.databases[self.current_db][key] = entry

            elif opcode == 0xFF:  # EOF
                break

            else:
                # opcode is the value-type byte
                key = self.read_string()
                entry = self._parse_value(opcode)
                self.databases[self.current_db][key] = entry

        return {"databases": self.databases}


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <rdb_file>", file=sys.stderr)
        sys.exit(1)
    parser = RDBParser(sys.argv[1])
    result = parser.parse()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
