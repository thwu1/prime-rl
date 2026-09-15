#!/usr/bin/env python3
"""Recover telemetry from firmware ELF + RAM dump.

Steps:
  1. Parse ELF32 to extract .type_registry section and symbol table
  2. Parse the binary type schema to learn message structure
  3. Use symbols to locate ring buffer data in the RAM dump
  4. Decode: BipBuffer → COBS → CRC32 → postcard (schema-driven)
  5. Write recovered.json
"""

import json
import struct
import zlib


# ═══════════════════════════════════════════════════════════════════════
# ELF32 parser (minimal, pure Python)
# ═══════════════════════════════════════════════════════════════════════
def parse_elf32(path):
    """Return (symbols_dict, get_section_data_fn) from an ELF32 LE file."""
    with open(path, 'rb') as f:
        data = f.read()

    assert data[:4] == b'\x7fELF', "Not an ELF file"
    assert data[4] == 1, "Not ELF32"
    assert data[5] == 1, "Not little-endian"

    e_shoff     = struct.unpack_from('<I', data, 32)[0]
    e_shentsize = struct.unpack_from('<H', data, 46)[0]
    e_shnum     = struct.unpack_from('<H', data, 48)[0]
    e_shstrndx  = struct.unpack_from('<H', data, 50)[0]

    # Parse section headers
    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        fields = struct.unpack_from('<IIIIIIIIII', data, off)
        sections.append(dict(zip(
            ('sh_name', 'sh_type', 'sh_flags', 'sh_addr',
             'sh_offset', 'sh_size', 'sh_link', 'sh_info',
             'sh_addralign', 'sh_entsize'), fields)))

    # Resolve section names from .shstrtab
    ss = sections[e_shstrndx]
    shstrtab = data[ss['sh_offset']:ss['sh_offset'] + ss['sh_size']]
    for sec in sections:
        n = sec['sh_name']
        end = shstrtab.index(b'\x00', n)
        sec['name'] = shstrtab[n:end].decode()

    sec_by_name = {s['name']: s for s in sections if s['name']}

    def get_section_data(name):
        s = sec_by_name[name]
        return data[s['sh_offset']:s['sh_offset'] + s['sh_size']]

    # Parse symbol table
    symbols = {}
    st = sec_by_name.get('.symtab')
    if st:
        strtab_sec = sections[st['sh_link']]
        strtab = data[strtab_sec['sh_offset']:
                      strtab_sec['sh_offset'] + strtab_sec['sh_size']]
        num_syms = st['sh_size'] // st['sh_entsize']
        for i in range(num_syms):
            sym_off = st['sh_offset'] + i * st['sh_entsize']
            st_name, st_value, st_size, st_info, st_other, st_shndx = \
                struct.unpack_from('<IIIBBH', data, sym_off)
            end = strtab.index(b'\x00', st_name)
            nm = strtab[st_name:end].decode()
            if nm:
                symbols[nm] = {'value': st_value, 'size': st_size}

    return symbols, get_section_data


# ═══════════════════════════════════════════════════════════════════════
# Binary type schema parser
# ═══════════════════════════════════════════════════════════════════════
TAG_U8       = 0x01
TAG_U16      = 0x02
TAG_U32      = 0x03
TAG_U64      = 0x04
TAG_I16      = 0x05
TAG_FIXLE32  = 0x06
TAG_F32      = 0x07
TAG_BOOL     = 0x08
TAG_STRING   = 0x09
TAG_OPTION   = 0x0A
TAG_SEQ      = 0x0B
TAG_ENUM_REF = 0x0C


def parse_type_schema(raw):
    """Parse the binary type registry into (enums, message_types)."""
    pos = [0]

    def u8():
        v = raw[pos[0]]; pos[0] += 1; return v

    def lps():
        n = u8()
        s = raw[pos[0]:pos[0] + n].decode('utf-8')
        pos[0] += n
        return s

    _version   = u8()
    num_vars   = u8()
    num_enums  = u8()

    enums = {}
    for _ in range(num_enums):
        eid   = u8()
        _name = lps()
        nv    = u8()
        enums[eid] = [lps() for _ in range(nv)]

    msg_types = {}
    for _ in range(num_vars):
        disc  = u8()
        vname = lps()
        nf    = u8()
        fields = []
        for _ in range(nf):
            fname = lps()
            tag   = u8()
            ft = {'tag': tag}
            if tag == TAG_OPTION:
                ft['inner'] = u8()
            elif tag == TAG_SEQ:
                ft['inner'] = u8()
            elif tag == TAG_ENUM_REF:
                ft['eid'] = u8()
            fields.append((fname, ft))
        msg_types[disc] = (vname, fields)

    return enums, msg_types


# ═══════════════════════════════════════════════════════════════════════
# COBS decoder
# ═══════════════════════════════════════════════════════════════════════
class DecodeError(Exception):
    pass


def cobs_decode(data):
    out = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]; idx += 1
        if code == 0:
            raise DecodeError("Zero byte in COBS data")
        for _ in range(code - 1):
            if idx >= len(data):
                raise DecodeError("COBS truncated")
            out.append(data[idx]); idx += 1
        if code < 0xFF and idx < len(data):
            out.append(0x00)
    return bytes(out)


# ═══════════════════════════════════════════════════════════════════════
# Postcard v1.0 reader (schema-driven)
# ═══════════════════════════════════════════════════════════════════════
class PostcardReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def byte(self):
        if self.pos >= len(self.data):
            raise DecodeError("EOF")
        v = self.data[self.pos]; self.pos += 1
        return v

    def nbytes(self, n):
        if self.pos + n > len(self.data):
            raise DecodeError("EOF")
        r = self.data[self.pos:self.pos + n]; self.pos += n
        return r

    def varint(self, max_bytes=10):
        result = 0; shift = 0
        for _ in range(max_bytes):
            b = self.byte()
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                return result
            shift += 7
        raise DecodeError("varint overflow")


def decode_field(rd, ft, enums):
    """Decode one field from the postcard stream based on schema type info."""
    tag = ft['tag']
    if tag == TAG_U8:
        return rd.byte()
    if tag == TAG_U16:
        return rd.varint(3)
    if tag == TAG_U32:
        return rd.varint(5)
    if tag == TAG_U64:
        return rd.varint(10)
    if tag == TAG_I16:
        z = rd.varint(3)
        return (z >> 1) ^ -(z & 1)
    if tag == TAG_FIXLE32:
        return struct.unpack('<I', rd.nbytes(4))[0]
    if tag == TAG_F32:
        return struct.unpack('<f', rd.nbytes(4))[0]
    if tag == TAG_BOOL:
        return rd.byte() != 0
    if tag == TAG_STRING:
        n = rd.varint()
        return rd.nbytes(n).decode('utf-8')
    if tag == TAG_OPTION:
        if rd.byte() == 0:
            return None
        return decode_field(rd, {'tag': ft['inner']}, enums)
    if tag == TAG_SEQ:
        n = rd.varint()
        return [decode_field(rd, {'tag': ft['inner']}, enums) for _ in range(n)]
    if tag == TAG_ENUM_REF:
        idx = rd.varint(5)
        return enums[ft['eid']][idx]
    raise DecodeError(f"Unknown type tag: 0x{tag:02x}")


def decode_message(payload, enums, msg_types):
    """Decode a full postcard message using the schema."""
    rd = PostcardReader(payload)
    disc = rd.varint(5)
    if disc not in msg_types:
        raise DecodeError(f"Unknown discriminant: {disc}")
    vname, fields = msg_types[disc]
    obj = {'type': vname}
    for fname, ft in fields:
        obj[fname] = decode_field(rd, ft, enums)
    return obj


# ═══════════════════════════════════════════════════════════════════════
# Main recovery logic
# ═══════════════════════════════════════════════════════════════════════
def main():
    # 1. Parse firmware ELF
    syms, get_sec = parse_elf32('/app/firmware.elf')

    # 2. Extract and parse the binary type schema
    schema_raw = get_sec('.type_registry')
    enums, msg_types = parse_type_schema(schema_raw)

    # 3. Determine RAM layout from symbols
    ram_base       = syms['_sram']['value']
    telem_buf_off  = syms['g_telem_ringbuf']['value'] - ram_base
    telem_buf_size = syms['g_telem_ringbuf']['size']
    telem_meta_off = syms['g_telem_meta']['value'] - ram_base

    # 4. Read RAM dump
    with open('/app/ram_dump.bin', 'rb') as f:
        ram = f.read()

    # 5. Extract BipBuffer control metadata
    wh, rh, wm, cap = struct.unpack_from('<IIII', ram, telem_meta_off)

    # 6. Extract valid data regions
    buf = ram[telem_buf_off:telem_buf_off + telem_buf_size]
    if wh < rh:
        # Wrapped: Region A (older, upper) then Region B (newer, lower)
        valid = buf[rh:wm] + buf[0:wh]
    else:
        valid = buf[rh:wh]

    # 7. Split COBS frames on 0x00 delimiter
    cobs_frames = []
    cur = bytearray()
    for b in valid:
        if b == 0x00:
            if cur:
                cobs_frames.append(bytes(cur))
                cur = bytearray()
        else:
            cur.append(b)
    if cur:
        cobs_frames.append(bytes(cur))

    # 8. Decode each frame: COBS → CRC32 verify → postcard deserialize
    messages = []
    for frame in cobs_frames:
        try:
            decoded = cobs_decode(frame)
            if len(decoded) < 5:
                continue
            payload = decoded[:-4]
            exp_crc = struct.unpack('<I', decoded[-4:])[0]
            act_crc = zlib.crc32(payload) & 0xFFFFFFFF
            if act_crc != exp_crc:
                continue
            msg = decode_message(payload, enums, msg_types)
            messages.append(msg)
        except Exception:
            continue

    # 9. Write output
    with open('/app/recovered.json', 'w') as f:
        json.dump(messages, f, indent=2)

    print(f"Recovered {len(messages)} valid messages")


if __name__ == '__main__':
    main()
