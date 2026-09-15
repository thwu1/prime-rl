#!/usr/bin/env python3
"""
Valkey/Redis RDB binary format parser and analyzer.
Parses an RDB dump file and produces a JSON analysis report.
"""

import struct
import json
import sys


# =============================================================================
# CRC64 — Jones polynomial, reflected form
# =============================================================================

def _make_crc64_table():
    poly = 0x95AC9329AC4BC9B5
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
        table.append(crc)
    return table


_CRC64_TAB = _make_crc64_table()


def crc64(data):
    crc = 0
    for b in data:
        crc = _CRC64_TAB[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc


# =============================================================================
# LZF decompression
# =============================================================================

def lzf_decompress(compressed, expected_len):
    out = bytearray()
    i = 0
    while i < len(compressed):
        ctrl = compressed[i]
        i += 1
        if ctrl < 32:
            # Literal run: ctrl+1 bytes
            count = ctrl + 1
            out.extend(compressed[i:i + count])
            i += count
        else:
            # Back reference
            length = ctrl >> 5
            if length == 7:
                length += compressed[i]
                i += 1
            offset = ((ctrl & 0x1F) << 8) + compressed[i] + 1
            i += 1
            length += 2
            ref_start = len(out) - offset
            for j in range(length):
                out.append(out[ref_start + j])
    if len(out) != expected_len:
        raise ValueError(
            f"LZF decompression size mismatch: got {len(out)}, expected {expected_len}"
        )
    return bytes(out)


# =============================================================================
# RDB constants
# =============================================================================

# Opcodes
RDB_OPCODE_AUX = 0xFA
RDB_OPCODE_RESIZEDB = 0xFB
RDB_OPCODE_EXPIRETIME_MS = 0xFC
RDB_OPCODE_EXPIRETIME = 0xFD
RDB_OPCODE_SELECTDB = 0xFE
RDB_OPCODE_EOF = 0xFF

# Value types
RDB_TYPE_STRING = 0
RDB_TYPE_LIST = 1
RDB_TYPE_SET = 2
RDB_TYPE_ZSET = 3
RDB_TYPE_HASH = 4
RDB_TYPE_ZSET_2 = 5
RDB_TYPE_MODULE_PRE_GA = 6
RDB_TYPE_MODULE_2 = 7
# 8 is unused
RDB_TYPE_HASH_ZIPMAP = 9
RDB_TYPE_LIST_ZIPLIST = 10
RDB_TYPE_SET_INTSET = 11
RDB_TYPE_ZSET_ZIPLIST = 12
RDB_TYPE_HASH_ZIPLIST = 13
RDB_TYPE_LIST_QUICKLIST = 14
RDB_TYPE_STREAM_LISTPACKS = 15
RDB_TYPE_HASH_LISTPACK = 16
RDB_TYPE_ZSET_LISTPACK = 17
RDB_TYPE_LIST_QUICKLIST_2 = 18
RDB_TYPE_SET_LISTPACK = 19
RDB_TYPE_STREAM_LISTPACKS_2 = 20
RDB_TYPE_STREAM_LISTPACKS_3 = 21
RDB_TYPE_HASH_LISTPACK_EX = 22

# Map RDB type codes to logical type names
TYPE_NAMES = {
    RDB_TYPE_STRING: "string",
    RDB_TYPE_LIST: "list",
    RDB_TYPE_SET: "set",
    RDB_TYPE_ZSET: "zset",
    RDB_TYPE_HASH: "hash",
    RDB_TYPE_ZSET_2: "zset",
    RDB_TYPE_HASH_ZIPMAP: "hash",
    RDB_TYPE_LIST_ZIPLIST: "list",
    RDB_TYPE_SET_INTSET: "set",
    RDB_TYPE_ZSET_ZIPLIST: "zset",
    RDB_TYPE_HASH_ZIPLIST: "hash",
    RDB_TYPE_LIST_QUICKLIST: "list",
    RDB_TYPE_HASH_LISTPACK: "hash",
    RDB_TYPE_ZSET_LISTPACK: "zset",
    RDB_TYPE_LIST_QUICKLIST_2: "list",
    RDB_TYPE_SET_LISTPACK: "set",
    RDB_TYPE_HASH_LISTPACK_EX: "hash",
}


# =============================================================================
# Listpack parser
# =============================================================================

def _backlen_size(entry_len):
    """Compute size of the backlen field given the entry data length."""
    if entry_len <= 127:
        return 1
    elif entry_len <= 16383:
        return 2
    elif entry_len <= 2097151:
        return 3
    elif entry_len <= 268435455:
        return 4
    else:
        return 5


def parse_listpack(raw):
    """Parse a listpack blob and return a list of string values."""
    if len(raw) < 7:
        return []

    # Header: total_bytes (4B LE), num_elements (2B LE)
    num_elements = struct.unpack_from('<H', raw, 4)[0]
    entries = []
    pos = 6

    for _ in range(num_elements):
        if pos >= len(raw) or raw[pos] == 0xFF:
            break

        entry_start = pos
        byte = raw[pos]

        if (byte & 0x80) == 0:
            # 7-bit unsigned integer: 0xxxxxxx
            val = str(byte & 0x7F)
            pos += 1

        elif (byte & 0xC0) == 0x80:
            # 6-bit string length: 10xxxxxx
            str_len = byte & 0x3F
            val = raw[pos + 1:pos + 1 + str_len].decode('utf-8', errors='replace')
            pos += 1 + str_len

        elif (byte & 0xE0) == 0xC0:
            # 13-bit signed integer: 110xxxxx yyyyyyyy
            val_raw = ((byte & 0x1F) << 8) | raw[pos + 1]
            if val_raw >= 4096:
                val_raw -= 8192
            val = str(val_raw)
            pos += 2

        elif (byte & 0xF0) == 0xE0:
            # 12-bit string length: 1110xxxx yyyyyyyy
            str_len = ((byte & 0x0F) << 8) | raw[pos + 1]
            val = raw[pos + 2:pos + 2 + str_len].decode('utf-8', errors='replace')
            pos += 2 + str_len

        elif byte == 0xF1:
            # 16-bit signed integer
            val = str(struct.unpack_from('<h', raw, pos + 1)[0])
            pos += 3

        elif byte == 0xF2:
            # 24-bit signed integer
            b0, b1, b2 = raw[pos + 1], raw[pos + 2], raw[pos + 3]
            val_raw = b0 | (b1 << 8) | (b2 << 16)
            if val_raw >= (1 << 23):
                val_raw -= (1 << 24)
            val = str(val_raw)
            pos += 4

        elif byte == 0xF3:
            # 32-bit signed integer
            val = str(struct.unpack_from('<i', raw, pos + 1)[0])
            pos += 5

        elif byte == 0xF4:
            # 64-bit signed integer
            val = str(struct.unpack_from('<q', raw, pos + 1)[0])
            pos += 9

        elif byte == 0xF0:
            # 32-bit string length
            str_len = struct.unpack_from('<I', raw, pos + 1)[0]
            val = raw[pos + 5:pos + 5 + str_len].decode('utf-8', errors='replace')
            pos += 5 + str_len

        else:
            raise ValueError(f"Unknown listpack encoding byte: 0x{byte:02x} at pos {pos}")

        entries.append(val)

        # Skip backlen
        entry_len = pos - entry_start
        pos += _backlen_size(entry_len)

    return entries


# =============================================================================
# Ziplist parser (legacy format, pre-listpack)
# =============================================================================

def parse_ziplist(raw):
    """Parse a ziplist blob and return a list of string values."""
    if len(raw) < 11:
        return []

    # Header: zlbytes(4B LE), zltail(4B LE), zllen(2B LE)
    zllen = struct.unpack_from('<H', raw, 8)[0]
    entries = []
    pos = 10

    while pos < len(raw) - 1:
        if raw[pos] == 0xFF:
            break

        # Previous entry length
        if raw[pos] < 254:
            pos += 1
        else:
            pos += 5

        # Encoding
        enc = raw[pos]

        if (enc & 0xC0) == 0x00:
            # 6-bit string length
            str_len = enc & 0x3F
            pos += 1
            val = raw[pos:pos + str_len].decode('utf-8', errors='replace')
            pos += str_len

        elif (enc & 0xC0) == 0x40:
            # 14-bit string length
            str_len = ((enc & 0x3F) << 8) | raw[pos + 1]
            pos += 2
            val = raw[pos:pos + str_len].decode('utf-8', errors='replace')
            pos += str_len

        elif (enc & 0xC0) == 0x80:
            # 32-bit string length
            str_len = struct.unpack_from('<I', raw, pos + 1)[0]
            pos += 5
            val = raw[pos:pos + str_len].decode('utf-8', errors='replace')
            pos += str_len

        elif enc == 0xC0:
            # 16-bit signed integer
            val = str(struct.unpack_from('<h', raw, pos + 1)[0])
            pos += 3

        elif enc == 0xD0:
            # 32-bit signed integer
            val = str(struct.unpack_from('<i', raw, pos + 1)[0])
            pos += 5

        elif enc == 0xE0:
            # 64-bit signed integer
            val = str(struct.unpack_from('<q', raw, pos + 1)[0])
            pos += 9

        elif enc == 0xF0:
            # 24-bit signed integer
            b0, b1, b2 = raw[pos + 1], raw[pos + 2], raw[pos + 3]
            val_raw = b0 | (b1 << 8) | (b2 << 16)
            if val_raw >= (1 << 23):
                val_raw -= (1 << 24)
            val = str(val_raw)
            pos += 4

        elif enc == 0xFE:
            # 8-bit signed integer
            val = str(struct.unpack_from('b', raw, pos + 1)[0])
            pos += 2

        elif (enc & 0xF0) == 0xF0:
            # 4-bit unsigned integer (0xF1-0xFD), value = (enc >> 0 & 0x0F) - 1
            val = str((enc & 0x0F) - 1)
            pos += 1

        else:
            raise ValueError(f"Unknown ziplist encoding: 0x{enc:02x} at pos {pos}")

        entries.append(val)

    return entries


# =============================================================================
# Intset parser
# =============================================================================

def parse_intset(raw):
    """Parse an intset blob and return a list of string members."""
    encoding = struct.unpack_from('<I', raw, 0)[0]  # 2, 4, or 8
    num_entries = struct.unpack_from('<I', raw, 4)[0]
    members = []
    for i in range(num_entries):
        offset = 8 + i * encoding
        if encoding == 2:
            val = struct.unpack_from('<h', raw, offset)[0]
        elif encoding == 4:
            val = struct.unpack_from('<i', raw, offset)[0]
        elif encoding == 8:
            val = struct.unpack_from('<q', raw, offset)[0]
        else:
            raise ValueError(f"Unknown intset encoding width: {encoding}")
        members.append(str(val))
    return members


# =============================================================================
# Main RDB parser
# =============================================================================

class RDBParser:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n):
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result

    def read_byte(self):
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_length(self):
        """Read a length-encoded value. Returns (length, is_special_encoding)."""
        first = self.read_byte()
        enc_type = (first & 0xC0) >> 6

        if enc_type == 0:
            return (first & 0x3F, False)
        elif enc_type == 1:
            second = self.read_byte()
            return (((first & 0x3F) << 8) | second, False)
        elif enc_type == 2:
            if first == 0x80:
                return (struct.unpack('>I', self.read(4))[0], False)
            elif first == 0x81:
                return (struct.unpack('>Q', self.read(8))[0], False)
            else:
                raise ValueError(f"Unknown 10xxxxxx length byte: 0x{first:02x}")
        else:  # enc_type == 3 → special encoding
            return (first & 0x3F, True)

    def read_string(self):
        """Read an RDB-encoded string, returning a Python str."""
        length, is_encoded = self.read_length()
        if not is_encoded:
            return self.read(length).decode('utf-8', errors='replace')

        if length == 0:   # INT8
            return str(struct.unpack('b', self.read(1))[0])
        elif length == 1:  # INT16 LE
            return str(struct.unpack('<h', self.read(2))[0])
        elif length == 2:  # INT32 LE
            return str(struct.unpack('<i', self.read(4))[0])
        elif length == 3:  # LZF compressed
            clen, _ = self.read_length()
            ulen, _ = self.read_length()
            compressed = self.read(clen)
            return lzf_decompress(compressed, ulen).decode('utf-8', errors='replace')
        else:
            raise ValueError(f"Unknown string special encoding: {length}")

    def read_string_raw(self):
        """Read an RDB-encoded string, returning raw bytes."""
        length, is_encoded = self.read_length()
        if not is_encoded:
            return self.read(length)

        if length == 0:
            return str(struct.unpack('b', self.read(1))[0]).encode()
        elif length == 1:
            return str(struct.unpack('<h', self.read(2))[0]).encode()
        elif length == 2:
            return str(struct.unpack('<i', self.read(4))[0]).encode()
        elif length == 3:
            clen, _ = self.read_length()
            ulen, _ = self.read_length()
            compressed = self.read(clen)
            return lzf_decompress(compressed, ulen)
        else:
            raise ValueError(f"Unknown string special encoding: {length}")

    # ----- Type-specific value readers -----

    def read_value(self, value_type):
        """
        Read a value of the given RDB type.
        Returns (logical_type, value, size).
        """
        if value_type == RDB_TYPE_STRING:
            val = self.read_string()
            return ("string", val, 1)

        elif value_type == RDB_TYPE_LIST:
            count, _ = self.read_length()
            items = [self.read_string() for _ in range(count)]
            return ("list", items, len(items))

        elif value_type == RDB_TYPE_SET:
            count, _ = self.read_length()
            members = [self.read_string() for _ in range(count)]
            return ("set", sorted(members), len(members))

        elif value_type == RDB_TYPE_ZSET:
            count, _ = self.read_length()
            pairs = []
            for _ in range(count):
                member = self.read_string()
                score_len = self.read_byte()
                if score_len == 255:
                    score = float('-inf')
                elif score_len == 254:
                    score = float('inf')
                elif score_len == 253:
                    score = float('nan')
                else:
                    score = float(self.read(score_len).decode())
                pairs.append([member, score])
            pairs.sort(key=lambda x: x[1])
            return ("zset", pairs, len(pairs))

        elif value_type == RDB_TYPE_HASH:
            count, _ = self.read_length()
            d = {}
            for _ in range(count):
                field = self.read_string()
                value = self.read_string()
                d[field] = value
            return ("hash", d, len(d))

        elif value_type == RDB_TYPE_ZSET_2:
            count, _ = self.read_length()
            pairs = []
            for _ in range(count):
                member = self.read_string()
                score = struct.unpack('<d', self.read(8))[0]
                pairs.append([member, score])
            pairs.sort(key=lambda x: x[1])
            return ("zset", pairs, len(pairs))

        elif value_type == RDB_TYPE_SET_INTSET:
            raw = self.read_string_raw()
            members = parse_intset(raw)
            return ("set", sorted(members, key=lambda x: int(x)), len(members))

        elif value_type == RDB_TYPE_HASH_LISTPACK:
            raw = self.read_string_raw()
            entries = parse_listpack(raw)
            d = {}
            for i in range(0, len(entries), 2):
                d[entries[i]] = entries[i + 1]
            return ("hash", d, len(d))

        elif value_type == RDB_TYPE_ZSET_LISTPACK:
            raw = self.read_string_raw()
            entries = parse_listpack(raw)
            pairs = []
            for i in range(0, len(entries), 2):
                pairs.append([entries[i], float(entries[i + 1])])
            pairs.sort(key=lambda x: x[1])
            return ("zset", pairs, len(pairs))

        elif value_type == RDB_TYPE_LIST_QUICKLIST_2:
            node_count, _ = self.read_length()
            items = []
            for _ in range(node_count):
                container, _ = self.read_length()
                raw = self.read_string_raw()
                if container == 2:  # PACKED (listpack)
                    entries = parse_listpack(raw)
                    items.extend(entries)
                else:  # PLAIN (single element)
                    items.append(raw.decode('utf-8', errors='replace'))
            return ("list", items, len(items))

        elif value_type == RDB_TYPE_LIST_QUICKLIST:
            node_count, _ = self.read_length()
            items = []
            for _ in range(node_count):
                raw = self.read_string_raw()
                entries = parse_ziplist(raw)
                items.extend(entries)
            return ("list", items, len(items))

        elif value_type == RDB_TYPE_SET_LISTPACK:
            raw = self.read_string_raw()
            entries = parse_listpack(raw)
            return ("set", sorted(entries), len(entries))

        elif value_type == RDB_TYPE_HASH_ZIPLIST:
            raw = self.read_string_raw()
            entries = parse_ziplist(raw)
            d = {}
            for i in range(0, len(entries), 2):
                d[entries[i]] = entries[i + 1]
            return ("hash", d, len(d))

        elif value_type == RDB_TYPE_ZSET_ZIPLIST:
            raw = self.read_string_raw()
            entries = parse_ziplist(raw)
            pairs = []
            for i in range(0, len(entries), 2):
                pairs.append([entries[i], float(entries[i + 1])])
            pairs.sort(key=lambda x: x[1])
            return ("zset", pairs, len(pairs))

        elif value_type == RDB_TYPE_LIST_ZIPLIST:
            raw = self.read_string_raw()
            entries = parse_ziplist(raw)
            return ("list", entries, len(entries))

        elif value_type == RDB_TYPE_HASH_LISTPACK_EX:
            # Valkey-specific: hash with per-field TTL
            # Format in listpack: field, value, ttl, field, value, ttl, ...
            raw = self.read_string_raw()
            entries = parse_listpack(raw)
            d = {}
            for i in range(0, len(entries), 3):
                d[entries[i]] = entries[i + 1]
            return ("hash", d, len(d))

        else:
            raise ValueError(f"Unsupported RDB type: {value_type}")

    # ----- Main parse method -----

    def parse(self):
        # Magic header
        magic = self.read(5)
        if magic != b'REDIS':
            raise ValueError(f"Invalid RDB magic: {magic!r}")

        # Version string (e.g., "0010" for version 10)
        version_str = self.read(4).decode('ascii')
        rdb_version = int(version_str)

        # Result containers
        aux_fields = {}
        databases = {}
        type_counts = {"string": 0, "list": 0, "set": 0, "hash": 0, "zset": 0}
        keys_with_expiry = []
        key_details = {}
        current_db = 0
        total_keys = 0

        while True:
            opcode = self.read_byte()

            if opcode == RDB_OPCODE_EOF:
                break

            elif opcode == RDB_OPCODE_AUX:
                key = self.read_string()
                value = self.read_string()
                aux_fields[key] = value

            elif opcode == RDB_OPCODE_RESIZEDB:
                self.read_length()  # db hash table size (hint)
                self.read_length()  # expires hash table size (hint)

            elif opcode == RDB_OPCODE_SELECTDB:
                current_db, _ = self.read_length()
                if str(current_db) not in databases:
                    databases[str(current_db)] = 0

            elif opcode == RDB_OPCODE_EXPIRETIME_MS:
                expiry_ms = struct.unpack('<Q', self.read(8))[0]
                vtype = self.read_byte()
                key_name = self.read_string()
                logical_type, value, size = self.read_value(vtype)

                db_key = str(current_db)
                if db_key not in databases:
                    databases[db_key] = 0
                databases[db_key] += 1
                total_keys += 1
                type_counts[logical_type] += 1

                keys_with_expiry.append({
                    "key": key_name,
                    "db": current_db,
                    "expiry_ms": expiry_ms,
                })
                key_details[key_name] = {
                    "db": current_db,
                    "type": logical_type,
                    "size": size,
                    "value": value,
                }

            elif opcode == RDB_OPCODE_EXPIRETIME:
                expiry_s = struct.unpack('<I', self.read(4))[0]
                vtype = self.read_byte()
                key_name = self.read_string()
                logical_type, value, size = self.read_value(vtype)

                db_key = str(current_db)
                if db_key not in databases:
                    databases[db_key] = 0
                databases[db_key] += 1
                total_keys += 1
                type_counts[logical_type] += 1

                keys_with_expiry.append({
                    "key": key_name,
                    "db": current_db,
                    "expiry_ms": expiry_s * 1000,
                })
                key_details[key_name] = {
                    "db": current_db,
                    "type": logical_type,
                    "size": size,
                    "value": value,
                }

            else:
                # Regular key-value entry; opcode IS the value type
                vtype = opcode
                if vtype not in TYPE_NAMES:
                    raise ValueError(
                        f"Unknown RDB type byte: 0x{vtype:02x} at pos {self.pos - 1}"
                    )
                key_name = self.read_string()
                logical_type, value, size = self.read_value(vtype)

                db_key = str(current_db)
                if db_key not in databases:
                    databases[db_key] = 0
                databases[db_key] += 1
                total_keys += 1
                type_counts[logical_type] += 1

                key_details[key_name] = {
                    "db": current_db,
                    "type": logical_type,
                    "size": size,
                    "value": value,
                }

        # CRC64 checksum verification (RDB version >= 5)
        checksum_valid = False
        if rdb_version >= 5 and len(self.data) >= 8:
            stored_crc = struct.unpack('<Q', self.data[-8:])[0]
            computed_crc = crc64(self.data[:-8])
            checksum_valid = stored_crc == computed_crc

        return {
            "rdb_version": rdb_version,
            "total_keys": total_keys,
            "databases": databases,
            "type_counts": type_counts,
            "keys_with_expiry": sorted(keys_with_expiry, key=lambda x: x["key"]),
            "checksum_valid": checksum_valid,
            "key_details": key_details,
        }


# =============================================================================
# Entry point
# =============================================================================

def main():
    rdb_path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/dump.rdb"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/app/analysis.json"

    with open(rdb_path, "rb") as f:
        data = f.read()

    parser = RDBParser(data)
    result = parser.parse()

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Analysis written to {output_path}")
    print(f"  RDB version: {result['rdb_version']}")
    print(f"  Total keys:  {result['total_keys']}")
    print(f"  Databases:   {result['databases']}")
    print(f"  Type counts: {result['type_counts']}")
    print(f"  Keys w/ TTL: {len(result['keys_with_expiry'])}")
    print(f"  CRC64 valid: {result['checksum_valid']}")


if __name__ == "__main__":
    main()
