#!/usr/bin/env python3
"""
Valkey persistence & encoding audit tool.
Combines RDB binary parsing with live redis-server introspection.
"""

import struct
import json
import sys
import subprocess


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
            count = ctrl + 1
            out.extend(compressed[i:i + count])
            i += count
        else:
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
            f"LZF size mismatch: got {len(out)}, expected {expected_len}"
        )
    return bytes(out)


# =============================================================================
# RDB constants
# =============================================================================

RDB_OPCODE_AUX = 0xFA
RDB_OPCODE_RESIZEDB = 0xFB
RDB_OPCODE_EXPIRETIME_MS = 0xFC
RDB_OPCODE_EXPIRETIME = 0xFD
RDB_OPCODE_SELECTDB = 0xFE
RDB_OPCODE_EOF = 0xFF

RDB_TYPE_STRING = 0
RDB_TYPE_LIST = 1
RDB_TYPE_SET = 2
RDB_TYPE_ZSET = 3
RDB_TYPE_HASH = 4
RDB_TYPE_ZSET_2 = 5
RDB_TYPE_MODULE_PRE_GA = 6
RDB_TYPE_MODULE_2 = 7
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
    if len(raw) < 7:
        return []
    num_elements = struct.unpack_from('<H', raw, 4)[0]
    entries = []
    pos = 6

    for _ in range(num_elements):
        if pos >= len(raw) or raw[pos] == 0xFF:
            break
        entry_start = pos
        byte = raw[pos]

        if (byte & 0x80) == 0:
            val = str(byte & 0x7F)
            pos += 1
        elif (byte & 0xC0) == 0x80:
            str_len = byte & 0x3F
            val = raw[pos + 1:pos + 1 + str_len].decode('utf-8', errors='replace')
            pos += 1 + str_len
        elif (byte & 0xE0) == 0xC0:
            val_raw = ((byte & 0x1F) << 8) | raw[pos + 1]
            if val_raw >= 4096:
                val_raw -= 8192
            val = str(val_raw)
            pos += 2
        elif (byte & 0xF0) == 0xE0:
            str_len = ((byte & 0x0F) << 8) | raw[pos + 1]
            val = raw[pos + 2:pos + 2 + str_len].decode('utf-8', errors='replace')
            pos += 2 + str_len
        elif byte == 0xF1:
            val = str(struct.unpack_from('<h', raw, pos + 1)[0])
            pos += 3
        elif byte == 0xF2:
            b0, b1, b2 = raw[pos + 1], raw[pos + 2], raw[pos + 3]
            val_raw = b0 | (b1 << 8) | (b2 << 16)
            if val_raw >= (1 << 23):
                val_raw -= (1 << 24)
            val = str(val_raw)
            pos += 4
        elif byte == 0xF3:
            val = str(struct.unpack_from('<i', raw, pos + 1)[0])
            pos += 5
        elif byte == 0xF4:
            val = str(struct.unpack_from('<q', raw, pos + 1)[0])
            pos += 9
        elif byte == 0xF0:
            str_len = struct.unpack_from('<I', raw, pos + 1)[0]
            val = raw[pos + 5:pos + 5 + str_len].decode('utf-8', errors='replace')
            pos += 5 + str_len
        else:
            raise ValueError(f"Unknown listpack byte: 0x{byte:02x} at {pos}")

        entries.append(val)
        entry_len = pos - entry_start
        pos += _backlen_size(entry_len)

    return entries


# =============================================================================
# Ziplist parser
# =============================================================================

def parse_ziplist(raw):
    if len(raw) < 11:
        return []
    entries = []
    pos = 10

    while pos < len(raw) - 1:
        if raw[pos] == 0xFF:
            break
        if raw[pos] < 254:
            pos += 1
        else:
            pos += 5

        enc = raw[pos]
        if (enc & 0xC0) == 0x00:
            str_len = enc & 0x3F
            pos += 1
            val = raw[pos:pos + str_len].decode('utf-8', errors='replace')
            pos += str_len
        elif (enc & 0xC0) == 0x40:
            str_len = ((enc & 0x3F) << 8) | raw[pos + 1]
            pos += 2
            val = raw[pos:pos + str_len].decode('utf-8', errors='replace')
            pos += str_len
        elif (enc & 0xC0) == 0x80:
            str_len = struct.unpack_from('<I', raw, pos + 1)[0]
            pos += 5
            val = raw[pos:pos + str_len].decode('utf-8', errors='replace')
            pos += str_len
        elif enc == 0xC0:
            val = str(struct.unpack_from('<h', raw, pos + 1)[0])
            pos += 3
        elif enc == 0xD0:
            val = str(struct.unpack_from('<i', raw, pos + 1)[0])
            pos += 5
        elif enc == 0xE0:
            val = str(struct.unpack_from('<q', raw, pos + 1)[0])
            pos += 9
        elif enc == 0xF0:
            b0, b1, b2 = raw[pos + 1], raw[pos + 2], raw[pos + 3]
            val_raw = b0 | (b1 << 8) | (b2 << 16)
            if val_raw >= (1 << 23):
                val_raw -= (1 << 24)
            val = str(val_raw)
            pos += 4
        elif enc == 0xFE:
            val = str(struct.unpack_from('b', raw, pos + 1)[0])
            pos += 2
        elif (enc & 0xF0) == 0xF0:
            val = str((enc & 0x0F) - 1)
            pos += 1
        else:
            raise ValueError(f"Unknown ziplist encoding: 0x{enc:02x}")
        entries.append(val)

    return entries


# =============================================================================
# Intset parser
# =============================================================================

def parse_intset(raw):
    encoding = struct.unpack_from('<I', raw, 0)[0]
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
            raise ValueError(f"Unknown intset width: {encoding}")
        members.append(str(val))
    return members


# =============================================================================
# RDB parser
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
                raise ValueError(f"Unknown length byte: 0x{first:02x}")
        else:
            return (first & 0x3F, True)

    def read_string(self):
        length, is_encoded = self.read_length()
        if not is_encoded:
            return self.read(length).decode('utf-8', errors='replace')
        if length == 0:
            return str(struct.unpack('b', self.read(1))[0])
        elif length == 1:
            return str(struct.unpack('<h', self.read(2))[0])
        elif length == 2:
            return str(struct.unpack('<i', self.read(4))[0])
        elif length == 3:
            clen, _ = self.read_length()
            ulen, _ = self.read_length()
            compressed = self.read(clen)
            return lzf_decompress(compressed, ulen).decode('utf-8', errors='replace')
        else:
            raise ValueError(f"Unknown string encoding: {length}")

    def read_string_raw(self):
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
            raise ValueError(f"Unknown string encoding: {length}")

    def read_value(self, value_type):
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
                if container == 2:
                    entries = parse_listpack(raw)
                    items.extend(entries)
                else:
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
            raw = self.read_string_raw()
            entries = parse_listpack(raw)
            d = {}
            for i in range(0, len(entries), 3):
                d[entries[i]] = entries[i + 1]
            return ("hash", d, len(d))

        else:
            raise ValueError(f"Unsupported RDB type: {value_type}")

    def parse(self):
        magic = self.read(5)
        if magic != b'REDIS':
            raise ValueError(f"Invalid RDB magic: {magic!r}")

        version_str = self.read(4).decode('ascii')
        rdb_version = int(version_str)

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
                self.read_string()
                self.read_string()

            elif opcode == RDB_OPCODE_RESIZEDB:
                self.read_length()
                self.read_length()

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
                vtype = opcode
                if vtype not in TYPE_NAMES:
                    raise ValueError(
                        f"Unknown RDB type: 0x{vtype:02x} at {self.pos - 1}"
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
# Redis CLI interaction
# =============================================================================

def redis_cli(*args, db=0):
    """Execute redis-cli --raw and return stdout."""
    cmd = ["redis-cli", "--raw", "-p", "6379"]
    if db != 0:
        cmd.extend(["-n", str(db)])
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.stdout.strip()


def get_config_int(param):
    """Get integer config value via CONFIG GET."""
    output = redis_cli("CONFIG", "GET", param)
    lines = output.split('\n')
    if len(lines) >= 2:
        try:
            return int(lines[1].strip())
        except ValueError:
            return 0
    return 0


def get_encoding_report(key_details):
    """Query OBJECT ENCODING and MEMORY USAGE for every key."""
    report = {}
    for key_name, info in key_details.items():
        db = info["db"]
        encoding = redis_cli("OBJECT", "ENCODING", key_name, db=db)
        memory_str = redis_cli("MEMORY", "USAGE", key_name, db=db)
        try:
            memory = int(memory_str)
        except (ValueError, TypeError):
            memory = 0
        report[key_name] = {
            "live_encoding": encoding,
            "memory_bytes": memory,
        }
    return report


def get_server_info():
    """Extract server info via INFO command."""
    info_server = redis_cli("INFO", "server")
    info_memory = redis_cli("INFO", "memory")

    version = ""
    used_memory = 0

    for line in info_server.split('\n'):
        line = line.strip()
        if line.startswith("redis_version:"):
            version = line.split(':', 1)[1].strip()

    for line in info_memory.split('\n'):
        line = line.strip()
        if line.startswith("used_memory:"):
            used_memory = int(line.split(':', 1)[1].strip())

    return {
        "redis_version": version,
        "used_memory_bytes": used_memory,
    }


def get_optimization_findings(key_details, encoding_report):
    """Identify keys with suboptimal encodings due to config thresholds."""
    hash_max = get_config_int("hash-max-listpack-entries")
    zset_max = get_config_int("zset-max-listpack-entries")
    set_max_intset = get_config_int("set-max-intset-entries")

    findings = []

    for key_name, info in key_details.items():
        enc = encoding_report[key_name]["live_encoding"]
        size = info["size"]
        ktype = info["type"]

        # Hash using hashtable but small enough for listpack with default config
        if ktype == "hash" and enc == "hashtable" and size <= 128:
            if size > hash_max:
                findings.append({
                    "key": key_name,
                    "current_encoding": "hashtable",
                    "optimal_encoding": "listpack",
                    "config_parameter": "hash-max-listpack-entries",
                    "current_threshold": hash_max,
                    "recommended_threshold": size,
                })

        # Zset using skiplist but small enough for listpack with default config
        elif ktype == "zset" and enc == "skiplist" and size <= 128:
            if size > zset_max:
                findings.append({
                    "key": key_name,
                    "current_encoding": "skiplist",
                    "optimal_encoding": "listpack",
                    "config_parameter": "zset-max-listpack-entries",
                    "current_threshold": zset_max,
                    "recommended_threshold": size,
                })

        # Set using hashtable but all-integer and small enough for intset
        elif ktype == "set" and enc == "hashtable":
            values = info["value"]
            all_int = all(
                isinstance(v, str) and v.lstrip('-').isdigit()
                for v in values
            )
            if all_int and size > set_max_intset and size <= 512:
                findings.append({
                    "key": key_name,
                    "current_encoding": "hashtable",
                    "optimal_encoding": "intset",
                    "config_parameter": "set-max-intset-entries",
                    "current_threshold": set_max_intset,
                    "recommended_threshold": size,
                })

    return sorted(findings, key=lambda f: f["key"])


# =============================================================================
# Main
# =============================================================================

def main():
    rdb_path = "/app/data/dump.rdb"
    output_path = "/app/audit.json"

    # Step 1: Parse the RDB binary
    with open(rdb_path, "rb") as f:
        data = f.read()
    parser = RDBParser(data)
    rdb_result = parser.parse()

    print(f"RDB parsed: {rdb_result['total_keys']} keys, "
          f"CRC64 valid: {rdb_result['checksum_valid']}")

    # Step 2: Live server introspection via redis-cli
    encoding_report = get_encoding_report(rdb_result["key_details"])
    server_info = get_server_info()

    print(f"Server: Redis {server_info['redis_version']}, "
          f"memory: {server_info['used_memory_bytes']} bytes")

    # Step 3: Optimization analysis
    optimization_findings = get_optimization_findings(
        rdb_result["key_details"], encoding_report
    )

    print(f"Found {len(optimization_findings)} optimization opportunities")

    # Produce combined audit report
    audit = {
        "rdb_version": rdb_result["rdb_version"],
        "total_keys": rdb_result["total_keys"],
        "databases": rdb_result["databases"],
        "type_counts": rdb_result["type_counts"],
        "keys_with_expiry": rdb_result["keys_with_expiry"],
        "checksum_valid": rdb_result["checksum_valid"],
        "key_details": rdb_result["key_details"],
        "encoding_report": encoding_report,
        "server_info": server_info,
        "optimization_findings": optimization_findings,
    }

    with open(output_path, "w") as f:
        json.dump(audit, f, indent=2, default=str)

    print(f"Audit written to {output_path}")


if __name__ == "__main__":
    main()
