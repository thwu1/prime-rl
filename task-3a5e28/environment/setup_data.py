#!/usr/bin/env python3
"""Generate ELF firmware files with .defmt sections and COBS-framed capture."""
import struct
import json
import os


def crc16_ccitt(data):
    """CRC-16/CCITT: polynomial 0x1021, init 0xFFFF."""
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


def cobs_encode(data):
    """COBS-encode a byte sequence (no 0x00 in output)."""
    output = bytearray()
    code_idx = len(output)
    output.append(0)
    code = 1
    for byte in data:
        if byte == 0:
            output[code_idx] = code
            code_idx = len(output)
            output.append(0)
            code = 1
        else:
            output.append(byte)
            code += 1
            if code == 0xFF:
                output[code_idx] = code
                code_idx = len(output)
                output.append(0)
                code = 1
    output[code_idx] = code
    return bytes(output)


def serialize_table(table):
    """Serialize a string table to the .defmt binary section format.

    Format:
      Magic: 'dFmT' (4 bytes)
      Version: u8 (value 4)
      Encoding: u8 (0=raw, 1=rzcobs)
      Flags: u8 (bit 0 = has_timestamp)
      Reserved: u8
      EntryCount: u16 LE
      Reserved: 2 bytes

      If has_timestamp:
        ts_tag_len: u8
        ts_tag: bytes
        ts_fmt_len: u16 LE
        ts_fmt: bytes

      Entries (sorted by index):
        index: u16 LE
        tag_len: u8
        tag: bytes
        fmt_len: u16 LE
        fmt: bytes
    """
    buf = bytearray()
    buf.extend(b'dFmT')
    buf.append(4)
    encoding = 0 if table.get("encoding", "raw") == "raw" else 1
    buf.append(encoding)
    has_ts = 1 if "timestamp" in table else 0
    buf.append(has_ts)
    buf.append(0)
    entries = table.get("entries", {})
    buf.extend(struct.pack('<H', len(entries)))
    buf.extend(b'\x00\x00')

    if has_ts:
        ts = table["timestamp"]
        ts_tag = ts["tag"].encode('utf-8')
        ts_fmt = ts["string"].encode('utf-8')
        buf.append(len(ts_tag))
        buf.extend(ts_tag)
        buf.extend(struct.pack('<H', len(ts_fmt)))
        buf.extend(ts_fmt)

    for idx_str in sorted(entries.keys(), key=lambda x: int(x)):
        entry = entries[idx_str]
        idx = int(idx_str)
        tag = entry["tag"].encode('utf-8')
        fmt = entry["string"].encode('utf-8')
        buf.extend(struct.pack('<H', idx))
        buf.append(len(tag))
        buf.extend(tag)
        buf.extend(struct.pack('<H', len(fmt)))
        buf.extend(fmt)

    return bytes(buf)


def create_elf(section_data, output_path):
    """Create a minimal ELF64 relocatable file with a .defmt section."""
    elf = bytearray()

    ehdr_size = 64
    defmt_offset = ehdr_size
    defmt_size = len(section_data)
    shstrtab_content = b'\x00.defmt\x00.shstrtab\x00'
    shstrtab_offset = defmt_offset + defmt_size
    shstrtab_size = len(shstrtab_content)

    raw_shdr_offset = shstrtab_offset + shstrtab_size
    shdr_offset = (raw_shdr_offset + 7) & ~7
    shdr_padding = shdr_offset - raw_shdr_offset

    # ELF64 header (64 bytes)
    elf.extend(b'\x7fELF')
    elf.append(2)                      # ELFCLASS64
    elf.append(1)                      # ELFDATA2LSB
    elf.append(1)                      # EV_CURRENT
    elf.extend(b'\x00' * 9)           # OS/ABI + padding
    elf.extend(struct.pack('<H', 1))   # e_type = ET_REL
    elf.extend(struct.pack('<H', 62))  # e_machine = EM_X86_64
    elf.extend(struct.pack('<I', 1))   # e_version
    elf.extend(struct.pack('<Q', 0))   # e_entry
    elf.extend(struct.pack('<Q', 0))   # e_phoff
    elf.extend(struct.pack('<Q', shdr_offset))  # e_shoff
    elf.extend(struct.pack('<I', 0))   # e_flags
    elf.extend(struct.pack('<H', 64))  # e_ehsize
    elf.extend(struct.pack('<H', 0))   # e_phentsize
    elf.extend(struct.pack('<H', 0))   # e_phnum
    elf.extend(struct.pack('<H', 64))  # e_shentsize
    elf.extend(struct.pack('<H', 3))   # e_shnum
    elf.extend(struct.pack('<H', 2))   # e_shstrndx

    assert len(elf) == 64

    # .defmt section data
    elf.extend(section_data)

    # .shstrtab data
    elf.extend(shstrtab_content)

    # Alignment padding
    elf.extend(b'\x00' * shdr_padding)

    # Section header 0: NULL
    elf.extend(b'\x00' * 64)

    # Section header 1: .defmt
    elf.extend(struct.pack('<I', 1))    # sh_name (offset in shstrtab)
    elf.extend(struct.pack('<I', 1))    # sh_type = SHT_PROGBITS
    elf.extend(struct.pack('<Q', 2))    # sh_flags = SHF_ALLOC
    elf.extend(struct.pack('<Q', 0))    # sh_addr
    elf.extend(struct.pack('<Q', defmt_offset))   # sh_offset
    elf.extend(struct.pack('<Q', defmt_size))      # sh_size
    elf.extend(struct.pack('<I', 0))    # sh_link
    elf.extend(struct.pack('<I', 0))    # sh_info
    elf.extend(struct.pack('<Q', 1))    # sh_addralign
    elf.extend(struct.pack('<Q', 0))    # sh_entsize

    # Section header 2: .shstrtab
    elf.extend(struct.pack('<I', 8))    # sh_name (offset in shstrtab)
    elf.extend(struct.pack('<I', 3))    # sh_type = SHT_STRTAB
    elf.extend(struct.pack('<Q', 0))    # sh_flags
    elf.extend(struct.pack('<Q', 0))    # sh_addr
    elf.extend(struct.pack('<Q', shstrtab_offset))  # sh_offset
    elf.extend(struct.pack('<Q', shstrtab_size))    # sh_size
    elf.extend(struct.pack('<I', 0))    # sh_link
    elf.extend(struct.pack('<I', 0))    # sh_info
    elf.extend(struct.pack('<Q', 1))    # sh_addralign
    elf.extend(struct.pack('<Q', 0))    # sh_entsize

    with open(output_path, 'wb') as f:
        f.write(bytes(elf))


# ============================================================
# String Table A (CORRECT)
# ============================================================
table_a = {
    "encoding": "raw",
    "timestamp": {"tag": "Timestamp", "string": "{=u32:us}"},
    "entries": {
        "0":  {"tag": "Info",    "string": "System initialized, clk={=u32}Hz"},
        "1":  {"tag": "Debug",   "string": "ADC ch{=u8}={=u16}"},
        "2":  {"tag": "Warn",    "string": "temp={=i16}dC exceeds limit"},
        "3":  {"tag": "Error",   "string": "fault @ {=u32:#010x}"},
        "4":  {"tag": "Info",    "string": "firmware v{=u8}.{=u8}.{=u8}"},
        "5":  {"tag": "Info",    "string": "payload {=[u8]:x}"},
        "6":  {"tag": "Debug",   "string": "tag={=istr}, seq={=u32}"},
        "7":  {"tag": "Info",    "string": "state={=?}"},
        "8":  {"tag": "Derived", "string": "Idle"},
        "9":  {"tag": "Derived", "string": "Running({=u16})"},
        "10": {"tag": "Info",    "string": "buf={=[u8]:a}"},
        "11": {"tag": "Info",    "string": "delta={=i32} f={=f32}"},
        "12": {"tag": "Info",    "string": "ok={=bool} ch={=char}"},
        "13": {"tag": "Info",    "string": "{=__internal_FormatSequence}"},
        "14": {"tag": "Derived", "string": "Init"},
        "15": {"tag": "Derived", "string": "Ready({=u8})"},
        "16": {"tag": "Derived", "string": "Error({=u16})"},
        "17": {"tag": "Str",     "string": "SENSOR_A"},
        "18": {"tag": "Info",    "string": "i16_hex={=i16:#x}"},
        "19": {"tag": "Info",    "string": "sensor={:x}"},
        "20": {"tag": "Derived", "string": "S {{ val: {=u8:?}, raw: {=u16:?} }}"}
    }
}

# ============================================================
# String Table B (WRONG - missing istr entry + wrong FormatSequence variants)
# ============================================================
table_b = json.loads(json.dumps(table_a))
del table_b["entries"]["17"]
table_b["entries"]["14"] = {"tag": "Info", "string": "mode={=u8}"}
table_b["entries"]["15"] = {"tag": "Debug", "string": "cnt={=u32}"}
table_b["entries"]["16"] = {"tag": "Trace", "string": "tick"}

# ============================================================
# String Table C (WRONG - incompatible type widths cause crashes)
# ============================================================
table_c = json.loads(json.dumps(table_a))
table_c["entries"]["3"]["string"] = "fault @ {=u64:#018x}"
table_c["entries"]["6"]["string"] = "tag={=str}, seq={=u32}"
table_c["entries"]["11"]["string"] = "delta={=i64} f={=f32}"


# ============================================================
# Generate ELF firmware files
# ============================================================
os.makedirs('/app/firmware', exist_ok=True)
os.makedirs('/app/reference', exist_ok=True)

for name, tbl in [("fw_alpha.elf", table_a), ("fw_beta.elf", table_b), ("fw_gamma.elf", table_c)]:
    section_data = serialize_table(tbl)
    create_elf(section_data, f'/app/firmware/{name}')
    print(f"Generated {name} ({os.path.getsize(f'/app/firmware/{name}')} bytes, "
          f".defmt section {len(section_data)} bytes)")


# ============================================================
# Build raw defmt frames (15 valid frames)
# ============================================================
raw_frames = []

# Frame 0: Info "System initialized, clk=72000000Hz"
raw_frames.append(
    struct.pack('<H', 0) + struct.pack('<I', 1000000) +
    struct.pack('<I', 72000000)
)

# Frame 1: Debug "ADC ch3=2048"
raw_frames.append(
    struct.pack('<H', 1) + struct.pack('<I', 1500000) +
    struct.pack('<B', 3) + struct.pack('<H', 2048)
)

# Frame 2: Warn "temp=-23dC exceeds limit"
raw_frames.append(
    struct.pack('<H', 2) + struct.pack('<I', 2000000) +
    struct.pack('<h', -23)
)

# Frame 3: Error "fault @ 0x0800dead"
raw_frames.append(
    struct.pack('<H', 3) + struct.pack('<I', 2500000) +
    struct.pack('<I', 0x0800DEAD)
)

# Frame 4: Info "firmware v2.5.1"
raw_frames.append(
    struct.pack('<H', 4) + struct.pack('<I', 3000000) +
    struct.pack('<BBB', 2, 5, 1)
)

# Frame 5: Info "payload [de, ad, be, ef]"
raw_frames.append(
    struct.pack('<H', 5) + struct.pack('<I', 3500000) +
    struct.pack('<I', 4) + bytes([0xDE, 0xAD, 0xBE, 0xEF])
)

# Frame 6: Debug "tag=SENSOR_A, seq=42" (uses istr)
raw_frames.append(
    struct.pack('<H', 6) + struct.pack('<I', 4000000) +
    struct.pack('<H', 17) + struct.pack('<I', 42)
)

# Frame 7: Info "state=Running(1024)" (nested Format)
raw_frames.append(
    struct.pack('<H', 7) + struct.pack('<I', 4500000) +
    struct.pack('<H', 9) + struct.pack('<H', 1024)
)

# Frame 8: Info "state=Idle" (nested Format, no args)
raw_frames.append(
    struct.pack('<H', 7) + struct.pack('<I', 5000000) +
    struct.pack('<H', 8)
)

# Frame 9: Info 'buf=b"Hello\x00"'
raw_frames.append(
    struct.pack('<H', 10) + struct.pack('<I', 5500000) +
    struct.pack('<I', 6) + b'Hello\x00'
)

# Frame 10: Info "delta=-1000 f=1.5"
raw_frames.append(
    struct.pack('<H', 11) + struct.pack('<I', 6000000) +
    struct.pack('<i', -1000) + struct.pack('<f', 1.5)
)

# Frame 11: Info "ok=true ch=Z"
raw_frames.append(
    struct.pack('<H', 12) + struct.pack('<I', 6500000) +
    struct.pack('<B', 1) + struct.pack('<I', ord('Z'))
)

# Frame 12: Info "InitReady(5)Error(404)" (FormatSequence)
raw_frames.append(
    struct.pack('<H', 13) + struct.pack('<I', 7000000) +
    struct.pack('<H', 14) +                            # Init (no args)
    struct.pack('<H', 15) + struct.pack('<B', 5) +     # Ready(5)
    struct.pack('<H', 16) + struct.pack('<H', 404) +   # Error(404)
    struct.pack('<H', 0)                               # terminator
)

# Frame 13: Info "i16_hex=0xffff" (signed i16 -1 in hex)
raw_frames.append(
    struct.pack('<H', 18) + struct.pack('<I', 7500000) +
    struct.pack('<h', -1)
)

# Frame 14: Info "sensor=S { val: 2a, raw: 100 }" (display hint propagation)
raw_frames.append(
    struct.pack('<H', 19) + struct.pack('<I', 8000000) +
    struct.pack('<H', 20) + struct.pack('<B', 42) + struct.pack('<H', 256)
)


# ============================================================
# Build COBS-framed capture with CRC and corrupted frames
# ============================================================
corrupt_positions = {4, 10, 14}
capture = bytearray()
valid_idx = 0

for pos in range(18):
    if pos in corrupt_positions:
        clean_payload = (
            struct.pack('<H', 0) +
            struct.pack('<I', pos * 500000) +
            struct.pack('<I', 99999)
        )
        crc = crc16_ccitt(clean_payload)
        corrupted = bytearray(clean_payload)
        corrupted[4] ^= 0xFF
        full = bytes(corrupted) + struct.pack('<H', crc)
    else:
        payload = raw_frames[valid_idx]
        crc = crc16_ccitt(payload)
        full = payload + struct.pack('<H', crc)
        valid_idx += 1

    encoded = cobs_encode(full)
    capture.extend(encoded)
    capture.append(0x00)

with open('/app/capture.bin', 'wb') as f:
    f.write(bytes(capture))

print(f"Generated capture.bin ({len(capture)} bytes, 18 COBS frames, 3 corrupt)")
