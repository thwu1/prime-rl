#!/usr/bin/env python3
"""Generate firmware.elf (with embedded type registry and symbol table)
and ram_dump.bin (SRAM image containing BipBuffer ring buffers).

Runs at Docker build time and is deleted afterward.
"""

import struct
import zlib
import random

random.seed(0xBEEF)

# ═══════════════════════════════════════════════════════════════════════
# Memory layout constants
# ═══════════════════════════════════════════════════════════════════════
RAM_ORIGIN       = 0x20000000
TELEM_BUF_OFF    = 0x0000;  TELEM_BUF_CAP = 1024
TELEM_META_OFF   = 0x0400   # 16 bytes (4 x u32 LE)
DEBUG_BUF_OFF    = 0x0410;  DEBUG_BUF_CAP = 512
DEBUG_META_OFF   = 0x0610   # 16 bytes
RAM_DUMP_SIZE    = 8192     # total SRAM dump

# ═══════════════════════════════════════════════════════════════════════
# Binary type schema encoding
# ═══════════════════════════════════════════════════════════════════════
TAG_U8          = 0x01
TAG_U16         = 0x02
TAG_U32         = 0x03
TAG_U64         = 0x04
TAG_I16         = 0x05
TAG_FIXINT_LE32 = 0x06
TAG_F32         = 0x07
TAG_BOOL        = 0x08
TAG_STRING      = 0x09
TAG_OPTION      = 0x0A  # followed by 1 byte: inner type tag
TAG_SEQ         = 0x0B  # followed by 1 byte: element type tag
TAG_ENUM_REF    = 0x0C  # followed by 1 byte: enum definition id


def _lps(s):
    """Length-prefixed string: u8 len followed by UTF-8 bytes."""
    b = s.encode('utf-8')
    return bytes([len(b)]) + b


def build_type_schema():
    """Build the binary type registry that will live in .type_registry."""
    d = bytearray()
    d.append(0x01)  # schema format version
    d.append(4)     # number of message variants
    d.append(1)     # number of enum definitions

    # ── Enum 0: LogLevel ──────────────────────────────────────────────
    d.append(0)                         # enum_id
    d.extend(_lps('LogLevel'))          # enum name
    d.append(5)                         # variant count
    for v in ('Trace', 'Debug', 'Info', 'Warn', 'Error'):
        d.extend(_lps(v))

    # ── Variant 0: Heartbeat ──────────────────────────────────────────
    d.append(0)
    d.extend(_lps('Heartbeat'))
    d.append(3)  # field count
    d.extend(_lps('sequence'));    d.append(TAG_U32)
    d.extend(_lps('uptime_ms'));   d.append(TAG_U64)
    d.extend(_lps('cpu_temp_c'));  d.append(TAG_I16)

    # ── Variant 1: SensorData ─────────────────────────────────────────
    d.append(1)
    d.extend(_lps('SensorData'))
    d.append(3)
    d.extend(_lps('channel'));       d.append(TAG_U8)
    d.extend(_lps('timestamp_us')); d.append(TAG_FIXINT_LE32)
    d.extend(_lps('samples'));       d.extend([TAG_SEQ, TAG_I16])

    # ── Variant 2: DiagnosticLog ──────────────────────────────────────
    d.append(2)
    d.extend(_lps('DiagnosticLog'))
    d.append(4)
    d.extend(_lps('level'));        d.extend([TAG_ENUM_REF, 0])
    d.extend(_lps('module_path')); d.append(TAG_STRING)
    d.extend(_lps('message'));     d.append(TAG_STRING)
    d.extend(_lps('error_code'));  d.extend([TAG_OPTION, TAG_U16])

    # ── Variant 3: ConfigAck ──────────────────────────────────────────
    d.append(3)
    d.extend(_lps('ConfigAck'))
    d.append(4)
    d.extend(_lps('request_id'));        d.append(TAG_U32)
    d.extend(_lps('accepted'));          d.append(TAG_BOOL)
    d.extend(_lps('effective_rate_hz')); d.append(TAG_F32)
    d.extend(_lps('active_channels'));   d.extend([TAG_SEQ, TAG_U8])

    return bytes(d)


# ═══════════════════════════════════════════════════════════════════════
# Postcard v1.0 encoding primitives
# ═══════════════════════════════════════════════════════════════════════
def enc_varint_u(v):
    if v == 0:
        return b'\x00'
    r = bytearray()
    while v > 0:
        b = v & 0x7F
        v >>= 7
        if v > 0:
            b |= 0x80
        r.append(b)
    return bytes(r)


def enc_zigzag(v, bits):
    z = (v << 1) ^ (v >> (bits - 1))
    return enc_varint_u(z & ((1 << bits) - 1))


def enc_u8(v):       return bytes([v & 0xFF])
def enc_u16(v):      return enc_varint_u(v)
def enc_u32(v):      return enc_varint_u(v)
def enc_u64(v):      return enc_varint_u(v)
def enc_i16(v):      return enc_zigzag(v, 16)
def enc_fixle32(v):  return struct.pack('<I', v)
def enc_f32(v):      return struct.pack('<f', v)
def enc_bool(v):     return b'\x01' if v else b'\x00'


def enc_string(s):
    b = s.encode('utf-8')
    return enc_varint_u(len(b)) + b


# ═══════════════════════════════════════════════════════════════════════
# COBS encoding
# ═══════════════════════════════════════════════════════════════════════
def cobs_encode(data):
    out = bytearray()
    ci = 0
    out.append(0)
    code = 1
    for byte in data:
        if byte == 0:
            out[ci] = code
            ci = len(out)
            out.append(0)
            code = 1
        else:
            out.append(byte)
            code += 1
            if code == 0xFF:
                out[ci] = code
                ci = len(out)
                out.append(0)
                code = 1
    out[ci] = code
    return bytes(out)


def make_frame(payload, corrupt_crc=False):
    """COBS-encode payload+CRC32, terminate with 0x00."""
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    if corrupt_crc:
        crc ^= 0xDEADBEEF
    return cobs_encode(payload + struct.pack('<I', crc)) + b'\x00'


# ═══════════════════════════════════════════════════════════════════════
# Telemetry message frames (10 valid + 2 corrupted)
# ═══════════════════════════════════════════════════════════════════════
frames = []

# 0: Heartbeat(seq=1, uptime=60000, cpu_temp=23)
frames.append(make_frame(
    enc_u32(0) + enc_u32(1) + enc_u64(60000) + enc_i16(23)))

# 1: SensorData(ch=0, ts=90000, samples=[100,-50,200,-300,150])
msg = enc_u32(1) + enc_u8(0) + enc_fixle32(90000) + enc_varint_u(5)
msg += enc_i16(100) + enc_i16(-50) + enc_i16(200) + enc_i16(-300) + enc_i16(150)
frames.append(make_frame(msg))

# 2: DiagnosticLog(Info, "sensor_drv", "all channels initialized", None)
msg = enc_u32(2) + enc_u32(2)  # variant=2, LogLevel::Info=2
msg += enc_string("sensor_drv")
msg += enc_string("all channels initialized")
msg += b'\x00'  # Option::None
frames.append(make_frame(msg))

# 3: Heartbeat(seq=2, uptime=120000, cpu_temp=25)
frames.append(make_frame(
    enc_u32(0) + enc_u32(2) + enc_u64(120000) + enc_i16(25)))

# 4: SensorData(ch=1, ts=180000, samples=[-1000,500])
msg = enc_u32(1) + enc_u8(1) + enc_fixle32(180000) + enc_varint_u(2)
msg += enc_i16(-1000) + enc_i16(500)
frames.append(make_frame(msg))

# 5: ConfigAck(req=42, accepted=true, rate=100.0, channels=[0,1,2])
msg = enc_u32(3) + enc_u32(42) + enc_bool(True) + enc_f32(100.0)
msg += enc_varint_u(3) + enc_u8(0) + enc_u8(1) + enc_u8(2)
frames.append(make_frame(msg))

# 6: CORRUPTED Heartbeat (bad CRC)
frames.append(make_frame(
    enc_u32(0) + enc_u32(99) + enc_u64(999999) + enc_i16(50),
    corrupt_crc=True))

# 7: DiagnosticLog(Warn, "power_mgmt", "battery below threshold", Some(1024))
msg = enc_u32(2) + enc_u32(3)  # variant=2, LogLevel::Warn=3
msg += enc_string("power_mgmt")
msg += enc_string("battery below threshold")
msg += b'\x01' + enc_u16(1024)  # Option::Some(1024)
frames.append(make_frame(msg))

# 8: Heartbeat(seq=3, uptime=180000, cpu_temp=28)
frames.append(make_frame(
    enc_u32(0) + enc_u32(3) + enc_u64(180000) + enc_i16(28)))

# 9: SensorData(ch=2, ts=300000, samples=[0,0,0,-1,1])
msg = enc_u32(1) + enc_u8(2) + enc_fixle32(300000) + enc_varint_u(5)
msg += enc_i16(0) + enc_i16(0) + enc_i16(0) + enc_i16(-1) + enc_i16(1)
frames.append(make_frame(msg))

# 10: CORRUPTED ConfigAck (bad CRC)
msg = enc_u32(3) + enc_u32(99) + enc_bool(True) + enc_f32(0.0) + enc_varint_u(0)
frames.append(make_frame(msg, corrupt_crc=True))

# 11: ConfigAck(req=43, accepted=false, rate=50.0, channels=[0])
msg = enc_u32(3) + enc_u32(43) + enc_bool(False) + enc_f32(50.0)
msg += enc_varint_u(1) + enc_u8(0)
frames.append(make_frame(msg))


# ═══════════════════════════════════════════════════════════════════════
# Telemetry BipBuffer layout
# ═══════════════════════════════════════════════════════════════════════
region_a = b''.join(frames[0:5])    # older: frames 0-4
region_b = b''.join(frames[5:12])   # newer: frames 5-11

READ_HEAD  = 700
WATERMARK  = READ_HEAD + len(region_a)
WRITE_HEAD = len(region_b)

assert WATERMARK <= TELEM_BUF_CAP, f"Region A overflow: wm={WATERMARK} > cap={TELEM_BUF_CAP}"
assert WRITE_HEAD <= READ_HEAD, f"Regions overlap: wh={WRITE_HEAD} >= rh={READ_HEAD}"

telem_buf = bytearray(TELEM_BUF_CAP)

# Stale data: consumed area [WRITE_HEAD, READ_HEAD)
stale1 = bytearray()
for _ in range(6):
    fake = bytes([random.randint(1, 255) for _ in range(random.randint(5, 25))])
    stale1.extend(cobs_encode(fake) + b'\x00')
while len(stale1) < (READ_HEAD - WRITE_HEAD):
    stale1.append(random.randint(0, 255))
stale1 = stale1[:READ_HEAD - WRITE_HEAD]
telem_buf[WRITE_HEAD:READ_HEAD] = stale1

# Stale data: unused tail [WATERMARK, CAPACITY)
stale2 = bytearray()
for _ in range(3):
    fake = bytes([random.randint(1, 255) for _ in range(random.randint(3, 15))])
    stale2.extend(cobs_encode(fake) + b'\x00')
while len(stale2) < (TELEM_BUF_CAP - WATERMARK):
    stale2.append(random.randint(0, 255))
stale2 = stale2[:TELEM_BUF_CAP - WATERMARK]
telem_buf[WATERMARK:TELEM_BUF_CAP] = stale2

# Place valid data
telem_buf[0:WRITE_HEAD] = region_b
telem_buf[READ_HEAD:WATERMARK] = region_a

telem_meta = struct.pack('<IIII', WRITE_HEAD, READ_HEAD, WATERMARK, TELEM_BUF_CAP)


# ═══════════════════════════════════════════════════════════════════════
# Debug/syslog ring buffer (decoy — different content format)
# ═══════════════════════════════════════════════════════════════════════
debug_msgs = [
    b"[DEBUG] uart0: baud=115200 initialized",
    b"[INFO] spi1: flash ID=0xEF4018",
    b"[WARN] adc: ch3 cal drift +12mV",
    b"[DEBUG] dma: xfer done, 256B",
    b"[ERROR] i2c0: NACK at addr 0x48",
]
debug_frames = [make_frame(m) for m in debug_msgs]
debug_data = b''.join(debug_frames)

# Non-wrapped buffer: write_head > read_head
DBG_READ_HEAD  = 0
DBG_WRITE_HEAD = min(len(debug_data), DEBUG_BUF_CAP)
DBG_WATERMARK  = DEBUG_BUF_CAP

debug_buf = bytearray(DEBUG_BUF_CAP)
debug_buf[0:DBG_WRITE_HEAD] = debug_data[:DBG_WRITE_HEAD]
for i in range(DBG_WRITE_HEAD, DEBUG_BUF_CAP):
    debug_buf[i] = random.randint(0, 255)

debug_meta = struct.pack('<IIII', DBG_WRITE_HEAD, DBG_READ_HEAD,
                         DBG_WATERMARK, DEBUG_BUF_CAP)


# ═══════════════════════════════════════════════════════════════════════
# RAM dump assembly
# ═══════════════════════════════════════════════════════════════════════
ram = bytearray(RAM_DUMP_SIZE)
ram[TELEM_BUF_OFF:TELEM_BUF_OFF + TELEM_BUF_CAP] = telem_buf
ram[TELEM_META_OFF:TELEM_META_OFF + 16] = telem_meta
ram[DEBUG_BUF_OFF:DEBUG_BUF_OFF + DEBUG_BUF_CAP] = debug_buf
ram[DEBUG_META_OFF:DEBUG_META_OFF + 16] = debug_meta
# Fill rest of SRAM with random data (stack, heap, peripherals)
for i in range(DEBUG_META_OFF + 16, RAM_DUMP_SIZE):
    ram[i] = random.randint(0, 255)


# ═══════════════════════════════════════════════════════════════════════
# ELF32 (ARM, little-endian) generation
# ═══════════════════════════════════════════════════════════════════════
def align4(x):
    return (x + 3) & ~3


def build_elf32(schema_data):
    """Produce a minimal valid ELF32 ARM binary with:
      .text            — dummy code
      .type_registry   — binary type schema
      .note.fw_info    — firmware build metadata
      .symtab          — ring buffer symbols
      .strtab          — symbol string table
      .shstrtab        — section name string table
    """
    # ── Section data ──────────────────────────────────────────────────
    text_data = b'\x00\xbf' * 2  # ARM Thumb NOP × 2

    # .note.fw_info (ELF note format)
    note_name_raw = b'FW\x00'
    note_name_pad = note_name_raw + b'\x00' * ((4 - len(note_name_raw) % 4) % 4)
    note_desc_raw = b'SN3000-TELEM v2.4.1\nbuild:2024-11-15T08:23:41Z\ntarget:thumbv7em-none-eabihf\n'
    note_desc_pad = note_desc_raw + b'\x00' * ((4 - len(note_desc_raw) % 4) % 4)
    note_data = (struct.pack('<III', len(note_name_raw), len(note_desc_raw), 1)
                 + note_name_pad + note_desc_pad)

    # ── Symbol table ──────────────────────────────────────────────────
    STT_OBJECT  = 2
    STT_NOTYPE  = 0
    STB_GLOBAL  = 1
    SHN_ABS     = 0xFFF1

    sym_defs = [
        ('g_telem_ringbuf',  RAM_ORIGIN + TELEM_BUF_OFF,  TELEM_BUF_CAP, STT_OBJECT),
        ('g_telem_meta',     RAM_ORIGIN + TELEM_META_OFF,  16,            STT_OBJECT),
        ('g_dbglog_ringbuf', RAM_ORIGIN + DEBUG_BUF_OFF,   DEBUG_BUF_CAP, STT_OBJECT),
        ('g_dbglog_meta',    RAM_ORIGIN + DEBUG_META_OFF,   16,            STT_OBJECT),
        ('_sram',            RAM_ORIGIN,                    0,             STT_NOTYPE),
    ]

    # .strtab
    strtab = bytearray(b'\x00')
    name_offsets = {}
    for nm, _, _, _ in sym_defs:
        name_offsets[nm] = len(strtab)
        strtab.extend(nm.encode() + b'\x00')
    strtab = bytes(strtab)

    # .symtab (Elf32_Sym = 16 bytes each)
    symtab = bytearray(b'\x00' * 16)  # symbol 0: STN_UNDEF
    for nm, val, sz, stt in sym_defs:
        st_info = (STB_GLOBAL << 4) | stt
        symtab.extend(struct.pack('<IIIBBH',
                                  name_offsets[nm], val, sz,
                                  st_info, 0, SHN_ABS))
    symtab = bytes(symtab)

    # .shstrtab
    sec_names = ['', '.text', '.type_registry', '.note.fw_info',
                 '.symtab', '.strtab', '.shstrtab']
    shstrtab = bytearray()
    sn_off = []
    for n in sec_names:
        sn_off.append(len(shstrtab))
        shstrtab.extend(n.encode() + b'\x00')
    shstrtab = bytes(shstrtab)

    # ── File layout ───────────────────────────────────────────────────
    EHDR_SZ  = 52   # Elf32_Ehdr
    SHDR_SZ  = 40   # Elf32_Shdr
    NUM_SECS = 7

    o = EHDR_SZ
    off_text     = o;  o = align4(o + len(text_data))
    off_schema   = o;  o = align4(o + len(schema_data))
    off_note     = o;  o = align4(o + len(note_data))
    off_symtab   = o;  o = align4(o + len(symtab))
    off_strtab   = o;  o = align4(o + len(strtab))
    off_shstrtab = o;  o = align4(o + len(shstrtab))
    off_shdrs    = o

    # ── ELF header ────────────────────────────────────────────────────
    hdr  = b'\x7fELF'                             # e_ident magic
    hdr += bytes([1, 1, 1, 0])                     # class32, LE, ver1, OSABI_NONE
    hdr += b'\x00' * 8                             # padding
    hdr += struct.pack('<HHIIIIIHHHHHH',
        2,              # e_type      = ET_EXEC
        40,             # e_machine   = EM_ARM
        1,              # e_version   = EV_CURRENT
        0x08000000,     # e_entry
        0,              # e_phoff     (no program headers)
        off_shdrs,      # e_shoff
        0x05000000,     # e_flags     (ARM EABI v5)
        EHDR_SZ,        # e_ehsize
        0, 0,           # e_phentsize, e_phnum
        SHDR_SZ,        # e_shentsize
        NUM_SECS,       # e_shnum
        6,              # e_shstrndx
    )
    assert len(hdr) == EHDR_SZ

    # ── Section header table ──────────────────────────────────────────
    SHT_NULL     = 0
    SHT_PROGBITS = 1
    SHT_SYMTAB   = 2
    SHT_STRTAB   = 3
    SHT_NOTE     = 7
    SHF_ALLOC    = 2
    SHF_EXEC     = 4

    def shdr(ni, stype, flags, addr, offset, size,
             link=0, info=0, addralign=1, entsize=0):
        return struct.pack('<IIIIIIIIII',
                           sn_off[ni], stype, flags, addr,
                           offset, size, link, info,
                           addralign, entsize)

    sht  = shdr(0, SHT_NULL,     0,                 0,          0,            0)
    sht += shdr(1, SHT_PROGBITS, SHF_ALLOC|SHF_EXEC,0x08000000,off_text,     len(text_data),    addralign=4)
    sht += shdr(2, SHT_PROGBITS, SHF_ALLOC,         0,         off_schema,   len(schema_data),  addralign=4)
    sht += shdr(3, SHT_NOTE,     0,                 0,          off_note,     len(note_data),    addralign=4)
    sht += shdr(4, SHT_SYMTAB,   0,                 0,          off_symtab,   len(symtab),
                link=5, info=1, addralign=4, entsize=16)
    sht += shdr(5, SHT_STRTAB,   0,                 0,          off_strtab,   len(strtab))
    sht += shdr(6, SHT_STRTAB,   0,                 0,          off_shstrtab, len(shstrtab))

    # ── Assemble ELF file ─────────────────────────────────────────────
    elf = bytearray(hdr)
    for off, data in [(off_text, text_data), (off_schema, schema_data),
                      (off_note, note_data), (off_symtab, symtab),
                      (off_strtab, strtab), (off_shstrtab, shstrtab)]:
        if len(elf) < off:
            elf.extend(b'\x00' * (off - len(elf)))
        elf.extend(data)
    if len(elf) < off_shdrs:
        elf.extend(b'\x00' * (off_shdrs - len(elf)))
    elf.extend(sht)

    return bytes(elf)


# ═══════════════════════════════════════════════════════════════════════
# Write output files
# ═══════════════════════════════════════════════════════════════════════
schema = build_type_schema()
elf = build_elf32(schema)

with open('/app/firmware.elf', 'wb') as f:
    f.write(elf)

with open('/app/ram_dump.bin', 'wb') as f:
    f.write(bytes(ram))

print(f"firmware.elf : {len(elf)} bytes  (schema section: {len(schema)} bytes)")
print(f"ram_dump.bin : {len(ram)} bytes")
print(f"Telem buffer : wh={WRITE_HEAD} rh={READ_HEAD} wm={WATERMARK} cap={TELEM_BUF_CAP}")
print(f"Debug buffer : wh={DBG_WRITE_HEAD} rh={DBG_READ_HEAD} wm={DBG_WATERMARK} cap={DEBUG_BUF_CAP}")
print(f"Frames: {len(frames)} total (2 corrupted, 10 valid)")
