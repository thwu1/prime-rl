#!/usr/bin/env python3
"""
Generate a PE64 memory dump for the forensic reconstruction task.
Creates a realistic PE binary with an XOR-encrypted config block and
decryption subroutine, simulates loading at a non-preferred base address
(reflective injection), and produces a memory dump with supporting
case metadata files and a SQLite exports database.
"""
import struct
import json
import sqlite3
import os

# ===== Configuration =====
ORIGINAL_IMAGEBASE = 0x0000000140000000
LOAD_ADDRESS       = 0x00007FF6B8A20000
DELTA              = LOAD_ADDRESS - ORIGINAL_IMAGEBASE

SECTION_ALIGNMENT = 0x1000
FILE_ALIGNMENT    = 0x200
SIZE_OF_IMAGE     = 0x5000
E_LFANEW          = 0x80
NUM_SECTIONS      = 4

# XOR key and config
XOR_KEY = 0x5A
CONFIG_PLAINTEXT = b'{"c2":"10.0.13.37","port":8443,"interval":300,"mutex":"MTX_A1B2C3"}'
CONFIG_MARKER = b'\xCA\xFE\xBA\xBE'

# Relocation entries: (rva_in_image, original_absolute_value)
# All are IMAGE_REL_BASED_DIR64 (type 10)
TEXT_RELOCS = [
    (0x1010, 0x0000000140001050),
    (0x1028, 0x0000000140003000),
    (0x1040, 0x0000000140001080),
    (0x1058, 0x0000000140002000),
    (0x1070, 0x0000000140003020),
    (0x1088, 0x0000000140000000),  # ImageBase reference
    (0x10A0, 0x00000001400010C0),
    (0x10B8, 0x0000000140002080),
    (0x10D0, 0x00000001400030A0),
    (0x10E8, 0x0000000140001100),
]

DATA_RELOCS = [
    (0x3010, 0x0000000140001000),
    (0x3028, 0x0000000140002000),
    (0x3040, 0x0000000140003060),
]

ALL_RELOCS = TEXT_RELOCS + DATA_RELOCS

# DLL import definitions
DLLS = [
    {
        "name": "KERNEL32.dll",
        "base": 0x00007FFB80100000,
        "functions": [
            ("CreateFileA",  0x21A30),
            ("ReadFile",     0x22B40),
            ("WriteFile",    0x23C50),
            ("CloseHandle",  0x14D60),
            ("GetLastError", 0x15E70),
            ("VirtualAlloc", 0x26F80),
        ],
    },
    {
        "name": "USER32.dll",
        "base": 0x00007FFB70200000,
        "functions": [
            ("MessageBoxA",    0x712A0),
            ("GetWindowTextA", 0x523B0),
        ],
    },
    {
        "name": "ADVAPI32.dll",
        "base": 0x00007FFB60300000,
        "functions": [
            ("RegOpenKeyExA",    0x31100),
            ("RegQueryValueExA", 0x32200),
            ("RegCloseKey",      0x23300),
        ],
    },
]

# Extra exports (not imported) to pad the exports DB
EXTRA_EXPORTS = {
    "KERNEL32.dll": {
        "ExitProcess": 0x18900, "GetProcessHeap": 0x19A00,
        "HeapAlloc": 0x1AB10, "HeapFree": 0x1BC20,
        "GetModuleHandleA": 0x1CD30, "LoadLibraryA": 0x1DE40,
        "GetProcAddress": 0x1EF50, "FreeLibrary": 0x20060,
        "CreateThread": 0x21170, "ExitThread": 0x22280,
        "GetCurrentProcessId": 0x23390, "OpenProcess": 0x244A0,
        "VirtualFree": 0x255B0, "VirtualProtect": 0x266C0,
        "FlushFileBuffers": 0x277D0, "SetFilePointer": 0x288E0,
        "GetFileSize": 0x299F0, "CreateMutexA": 0x2AA00,
        "WaitForSingleObject": 0x2BB10, "Sleep": 0x2CC20,
    },
    "USER32.dll": {
        "MessageBoxW": 0x724C0, "SendMessageA": 0x535D0,
        "PostMessageA": 0x546E0, "GetDlgItem": 0x557F0,
        "SetWindowTextA": 0x56900, "DestroyWindow": 0x67A10,
        "ShowWindow": 0x68B20, "UpdateWindow": 0x69C30,
        "DefWindowProcA": 0x6AD40, "RegisterClassA": 0x6BE50,
        "CreateWindowExA": 0x6CF60,
    },
    "ADVAPI32.dll": {
        "RegSetValueExA": 0x34400, "RegDeleteKeyA": 0x35500,
        "RegEnumKeyExA": 0x36600, "RegCreateKeyExA": 0x37700,
        "OpenProcessToken": 0x28800, "AdjustTokenPrivileges": 0x29900,
        "LookupPrivilegeValueA": 0x2AA00, "GetTokenInformation": 0x2BB00,
        "CryptAcquireContextA": 0x3CC00, "CryptGenRandom": 0x3DD00,
    },
}


def main():
    img = bytearray(SIZE_OF_IMAGE)

    # ===== DOS Header (offset 0x000) =====
    struct.pack_into('<H', img, 0x00, 0x5A4D)          # e_magic = "MZ"
    struct.pack_into('<I', img, 0x3C, E_LFANEW)        # e_lfanew
    dos_stub = b'This program cannot be run in DOS mode.\r\n$'
    img[0x40:0x40 + len(dos_stub)] = dos_stub

    # ===== PE Signature (offset 0x80) =====
    struct.pack_into('<I', img, E_LFANEW, 0x00004550)  # "PE\0\0"

    # ===== COFF File Header (offset 0x84) =====
    fh = E_LFANEW + 4
    struct.pack_into('<H', img, fh + 0,  0x8664)       # Machine = AMD64
    struct.pack_into('<H', img, fh + 2,  NUM_SECTIONS)
    struct.pack_into('<I', img, fh + 4,  0x65A1B2C3)   # TimeDateStamp
    struct.pack_into('<I', img, fh + 8,  0)             # PointerToSymbolTable
    struct.pack_into('<I', img, fh + 12, 0)             # NumberOfSymbols
    struct.pack_into('<H', img, fh + 16, 240)           # SizeOfOptionalHeader (PE32+)
    struct.pack_into('<H', img, fh + 18, 0x0022)        # EXECUTABLE_IMAGE | LARGE_ADDRESS_AWARE

    # ===== Optional Header PE32+ (offset 0x98, 240 bytes) =====
    oh = fh + 20  # 0x98
    struct.pack_into('<H', img, oh + 0,  0x020B)        # Magic = PE32+
    struct.pack_into('<B', img, oh + 2,  14)             # MajorLinkerVersion
    struct.pack_into('<B', img, oh + 3,  30)             # MinorLinkerVersion
    struct.pack_into('<I', img, oh + 4,  0x200)          # SizeOfCode
    struct.pack_into('<I', img, oh + 8,  0x600)          # SizeOfInitializedData
    struct.pack_into('<I', img, oh + 12, 0)              # SizeOfUninitializedData
    struct.pack_into('<I', img, oh + 16, 0x1000)         # AddressOfEntryPoint
    struct.pack_into('<I', img, oh + 20, 0x1000)         # BaseOfCode
    struct.pack_into('<Q', img, oh + 24, LOAD_ADDRESS)   # ImageBase (set to load addr)
    struct.pack_into('<I', img, oh + 32, SECTION_ALIGNMENT)
    struct.pack_into('<I', img, oh + 36, FILE_ALIGNMENT)
    struct.pack_into('<H', img, oh + 40, 6)              # MajorOSVersion
    struct.pack_into('<H', img, oh + 42, 0)
    struct.pack_into('<H', img, oh + 44, 0)              # MajorImageVersion
    struct.pack_into('<H', img, oh + 46, 0)
    struct.pack_into('<H', img, oh + 48, 6)              # MajorSubsystemVersion
    struct.pack_into('<H', img, oh + 50, 0)
    struct.pack_into('<I', img, oh + 52, 0)              # Win32VersionValue
    struct.pack_into('<I', img, oh + 56, SIZE_OF_IMAGE)
    struct.pack_into('<I', img, oh + 60, 0x400)          # SizeOfHeaders (on-disk)
    struct.pack_into('<I', img, oh + 64, 0)              # CheckSum
    struct.pack_into('<H', img, oh + 68, 3)              # Subsystem = CONSOLE
    struct.pack_into('<H', img, oh + 70, 0x8160)         # DllCharacteristics
    struct.pack_into('<Q', img, oh + 72, 0x100000)       # SizeOfStackReserve
    struct.pack_into('<Q', img, oh + 80, 0x1000)         # SizeOfStackCommit
    struct.pack_into('<Q', img, oh + 88, 0x100000)       # SizeOfHeapReserve
    struct.pack_into('<Q', img, oh + 96, 0x1000)         # SizeOfHeapCommit
    struct.pack_into('<I', img, oh + 104, 0)             # LoaderFlags
    struct.pack_into('<I', img, oh + 108, 16)            # NumberOfRvaAndSizes

    # ----- Data Directories (oh+112 = 0x108) -----
    dd = oh + 112
    # [1] Import Directory: RVA=0x2000, Size=80 (4 IDT entries x 20)
    struct.pack_into('<II', img, dd + 1 * 8, 0x2000, 0x50)
    # [5] Base Relocation: RVA=0x4000, Size=44
    struct.pack_into('<II', img, dd + 5 * 8, 0x4000, 44)
    # [12] IAT: RVA=0x2078, Size=112
    struct.pack_into('<II', img, dd + 12 * 8, 0x2078, 0x70)

    # ===== Section Headers (offset 0x188) =====
    secs = [
        # (name,             VirtSize, VA,     RawSize, RawOff, Characteristics)
        (b'.text\x00\x00\x00', 0x1C0, 0x1000, 0x200,  0x400,  0x60000020),
        (b'.rdata\x00\x00',    0x1A0, 0x2000, 0x200,  0x600,  0x40000040),
        (b'.data\x00\x00\x00', 0x100, 0x3000, 0x200,  0x800,  0xC0000040),
        (b'.reloc\x00\x00',    0x080, 0x4000, 0x200,  0xA00,  0x42000040),
    ]
    sh = oh + 240  # 0x188
    for i, (name, vs, va, rs, ro, ch) in enumerate(secs):
        o = sh + i * 40
        img[o:o + 8] = name
        struct.pack_into('<I', img, o + 8,  vs)
        struct.pack_into('<I', img, o + 12, va)
        struct.pack_into('<I', img, o + 16, rs)
        struct.pack_into('<I', img, o + 20, ro)
        struct.pack_into('<I', img, o + 24, 0)   # PointerToRelocations
        struct.pack_into('<I', img, o + 28, 0)   # PointerToLinenumbers
        struct.pack_into('<H', img, o + 32, 0)
        struct.pack_into('<H', img, o + 34, 0)
        struct.pack_into('<I', img, o + 36, ch)

    # ===== .text section (memory offset 0x1000) =====
    # Fill with INT3 (0xCC) then overlay x64 instruction patterns
    for i in range(0x200):
        img[0x1000 + i] = 0xCC

    code = [
        # ----- Main function at .text+0x000 -----
        (0x000, b'\x48\x89\xE5'),           # mov rbp, rsp
        (0x003, b'\x48\x83\xEC\x40'),       # sub rsp, 0x40
        (0x007, b'\x53'),                    # push rbx
        (0x008, b'\x56'),                    # push rsi
        (0x009, b'\x57'),                    # push rdi
        (0x00A, b'\x48\x31\xC0'),           # xor rax, rax
        (0x00D, b'\x90'),                    # nop
        (0x00E, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#1 @0x010
        (0x018, b'\x48\x89\x45\xF0'),       # mov [rbp-0x10], rax
        (0x01C, b'\x48\x8D\x4D\xF0'),       # lea rcx, [rbp-0x10]
        (0x020, b'\x48\x89\xC3'),           # mov rbx, rax
        (0x023, b'\x48\x89\xDA'),           # mov rdx, rbx
        (0x026, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#2 @0x028
        (0x030, b'\xFF\xD0'),               # call rax
        (0x032, b'\x48\x85\xC0'),           # test rax, rax
        (0x035, b'\x74\x10'),               # jz +0x10
        (0x037, b'\x48\x89\xC6'),           # mov rsi, rax
        (0x03A, b'\x48\x89\x75\xE8'),       # mov [rbp-0x18], rsi
        (0x03E, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#3 @0x040
        (0x048, b'\xFF\xD0'),               # call rax
        (0x04A, b'\x48\x89\xC7'),           # mov rdi, rax
        (0x04D, b'\x48\x89\xE5'),           # mov rbp, rsp
        (0x050, b'\x48\x83\xEC\x20'),       # sub rsp, 0x20
        (0x054, b'\x48\x31\xDB'),           # xor rbx, rbx
        (0x056, b'\x48\xB9'),               # mov rcx, imm64  -> RELOC#4 @0x058
        (0x060, b'\xFF\x15\x00\x00\x00\x00'),  # call [rip+0]
        (0x066, b'\x48\x89\xC6'),           # mov rsi, rax
        (0x069, b'\x48\x8D\x55\xC0'),       # lea rdx, [rbp-0x40]
        (0x06D, b'\x90'),                    # nop
        (0x06E, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#5 @0x070
        (0x078, b'\x48\x89\xC2'),           # mov rdx, rax
        (0x07B, b'\x4C\x89\xE1'),           # mov rcx, r12
        (0x07E, b'\xFF\xD6'),               # call rsi
        (0x080, b'\x55'),                    # push rbp
        (0x081, b'\x48\x89\xE5'),           # mov rbp, rsp
        (0x084, b'\x48\x83\xEC\x30'),       # sub rsp, 0x30
        (0x086, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#6 @0x088
        (0x090, b'\x48\x89\x06'),           # mov [rsi], rax
        (0x093, b'\x48\x83\xC6\x08'),       # add rsi, 8
        (0x097, b'\x48\x89\xF1'),           # mov rcx, rsi
        (0x09A, b'\x48\x89\xFA'),           # mov rdx, rdi
        (0x09D, b'\x90'),                    # nop
        (0x09E, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#7 @0x0A0
        (0x0A8, b'\xFF\xD0'),               # call rax
        (0x0AA, b'\x48\x89\xC3'),           # mov rbx, rax
        (0x0AD, b'\x48\x85\xDB'),           # test rbx, rbx
        (0x0B0, b'\x74\x20'),               # jz +0x20
        (0x0B2, b'\x48\x8D\x75\xD0'),       # lea rsi, [rbp-0x30]
        (0x0B6, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#8 @0x0B8
        (0x0C0, b'\x48\x89\x45\xE8'),       # mov [rbp-0x18], rax
        (0x0C4, b'\x48\x8B\x4D\xE8'),       # mov rcx, [rbp-0x18]
        (0x0C8, b'\x48\x8B\x55\xF0'),       # mov rdx, [rbp-0x10]
        (0x0CC, b'\x90\x90'),               # nops
        (0x0CE, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#9 @0x0D0
        (0x0D8, b'\x48\x39\xC3'),           # cmp rbx, rax
        (0x0DB, b'\x75\x10'),               # jne +0x10
        (0x0DD, b'\x48\x89\xD9'),           # mov rcx, rbx
        (0x0E0, b'\x48\x89\xC2'),           # mov rdx, rax
        (0x0E3, b'\xFF\xD7'),               # call rdi
        (0x0E5, b'\x90'),                    # nop
        (0x0E6, b'\x48\xB8'),               # mov rax, imm64  -> RELOC#10 @0x0E8
        (0x0F0, b'\x48\x89\x45\xE0'),       # mov [rbp-0x20], rax
        (0x0F4, b'\x48\x83\xC4\x40'),       # add rsp, 0x40
        (0x0F8, b'\x5F'),                    # pop rdi
        (0x0F9, b'\x5E'),                    # pop rsi
        (0x0FA, b'\x5B'),                    # pop rbx
        (0x0FB, b'\x5D'),                    # pop rbp
        (0x0FC, b'\xC3'),                    # ret

        # ----- Decryption subroutine at .text+0x100 -----
        (0x100, b'\x55'),                             # push rbp
        (0x101, b'\x48\x89\xE5'),                     # mov rbp, rsp
        (0x104, b'\xB1\x5A'),                         # mov cl, 0x5A (XOR key)
        (0x106, b'\x48\x8D\x35\x73\x1F\x00\x00'),    # lea rsi, [rip+0x1F73] -> RVA 0x3080
        (0x10D, b'\xBA\x43\x00\x00\x00'),             # mov edx, 67 (config length)
        (0x112, b'\x30\x0E'),                         # xor byte [rsi], cl
        (0x114, b'\x48\xFF\xC6'),                     # inc rsi
        (0x117, b'\xFF\xCA'),                         # dec edx
        (0x119, b'\x75\xF7'),                         # jnz -9 (back to xor)
        (0x11B, b'\x5D'),                             # pop rbp
        (0x11C, b'\xC3'),                             # ret
    ]
    for off, data in code:
        for j, b in enumerate(data):
            img[0x1000 + off + j] = b

    # Place original values at relocation points (overwritten by relocate step)
    for rva, orig in TEXT_RELOCS:
        struct.pack_into('<Q', img, rva, orig)

    # ===== .rdata section (memory offset 0x2000) =====
    # Import Directory Table layout:
    #   IDT:      0x2000 - 0x204F  (4 entries x 20 bytes)
    #   Names:    0x2050 - 0x2074
    #   IAT:      0x2078 - 0x20E7

    dll_name_off = 0x2050
    dll_name_rvas = []
    off = dll_name_off
    for dll in DLLS:
        dll_name_rvas.append(off)
        off += len(dll["name"]) + 1

    iat_start = 0x2078
    iat_rvas = []
    off = iat_start
    for dll in DLLS:
        iat_rvas.append(off)
        off += (len(dll["functions"]) + 1) * 8  # +1 for null terminator

    # Write IDT entries
    for i, dll in enumerate(DLLS):
        idt = 0x2000 + i * 20
        struct.pack_into('<I', img, idt + 0,  0)                 # OriginalFirstThunk (destroyed)
        struct.pack_into('<I', img, idt + 4,  0)                 # TimeDateStamp
        struct.pack_into('<I', img, idt + 8,  0)                 # ForwarderChain
        struct.pack_into('<I', img, idt + 12, dll_name_rvas[i])  # Name RVA
        struct.pack_into('<I', img, idt + 16, iat_rvas[i])       # FirstThunk RVA
    # Entry 3 = null terminator (already zeroes)

    # Write DLL name strings
    for i, dll in enumerate(DLLS):
        name_bytes = dll["name"].encode('ascii') + b'\x00'
        r = dll_name_rvas[i]
        img[r:r + len(name_bytes)] = name_bytes

    # Write IAT entries with resolved addresses
    for i, dll in enumerate(DLLS):
        base = dll["base"]
        for j, (fname, frva) in enumerate(dll["functions"]):
            resolved = base + frva
            struct.pack_into('<Q', img, iat_rvas[i] + j * 8, resolved)
        # null terminator already zeroes

    # ===== .data section (memory offset 0x3000) =====
    img[0x3000:0x3008] = b'\x01\x00\x00\x00\x02\x00\x00\x00'
    img[0x3008:0x3010] = b'\xFF\xFF\xFF\xFF\x00\x00\x00\x00'
    # Place original values at relocation points
    for rva, orig in DATA_RELOCS:
        struct.pack_into('<Q', img, rva, orig)
    # Extra data
    img[0x3048:0x3058] = b'ConfigData\x00\x00\x00\x00\x00\x00'
    img[0x3060:0x3070] = b'\xDE\xAD\xBE\xEF' + b'\x00' * 12

    # ----- Encrypted configuration block -----
    # Marker at 0x3078: CAFEBABE + length (uint32)
    img[0x3078:0x307C] = CONFIG_MARKER
    struct.pack_into('<I', img, 0x307C, len(CONFIG_PLAINTEXT))
    # XOR-encrypted config at 0x3080
    encrypted_config = bytes(b ^ XOR_KEY for b in CONFIG_PLAINTEXT)
    img[0x3080:0x3080 + len(encrypted_config)] = encrypted_config

    # ===== .reloc section (memory offset 0x4000) =====
    roff = 0x4000

    # Block 1: page 0x1000 (.text), 10 DIR64 entries
    struct.pack_into('<I', img, roff, 0x1000)      # VirtualAddress
    struct.pack_into('<I', img, roff + 4, 28)      # SizeOfBlock = 8 + 10*2
    for j, (rva, _) in enumerate(TEXT_RELOCS):
        entry = (10 << 12) | (rva - 0x1000)        # type=DIR64, offset in page
        struct.pack_into('<H', img, roff + 8 + j * 2, entry)
    roff += 28

    # Block 2: page 0x3000 (.data), 3 DIR64 entries + 1 ABSOLUTE padding
    struct.pack_into('<I', img, roff, 0x3000)
    struct.pack_into('<I', img, roff + 4, 16)      # SizeOfBlock = 8 + 4*2
    for j, (rva, _) in enumerate(DATA_RELOCS):
        entry = (10 << 12) | (rva - 0x3000)
        struct.pack_into('<H', img, roff + 8 + j * 2, entry)
    struct.pack_into('<H', img, roff + 8 + 3 * 2, 0x0000)  # ABSOLUTE padding

    # ===== Apply relocations (simulate loading at LOAD_ADDRESS) =====
    for rva, orig in ALL_RELOCS:
        struct.pack_into('<Q', img, rva, orig + DELTA)

    # ===== Save output files =====
    os.makedirs('/app', exist_ok=True)

    with open('/app/dump.bin', 'wb') as f:
        f.write(img)

    case_info = {
        "load_address": hex(LOAD_ADDRESS),
        "original_imagebase": hex(ORIGINAL_IMAGEBASE)
    }
    with open('/app/case_info.json', 'w') as f:
        json.dump(case_info, f, indent=2)

    config_info = {
        "encrypted_config_section": ".data",
        "encrypted_config_marker": "0xCAFEBABE",
        "encryption": "single_byte_xor",
        "key_hint": "The XOR key is loaded as an immediate operand in the decryption subroutine within the .text section. Use a disassembler to locate it."
    }
    with open('/app/config_info.json', 'w') as f:
        json.dump(config_info, f, indent=2)

    # Build SQLite exports database
    db_path = '/app/exports.db'
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('CREATE TABLE dlls (name TEXT PRIMARY KEY, base_address TEXT NOT NULL)')
    cur.execute('CREATE TABLE exports (dll_name TEXT NOT NULL, function_name TEXT NOT NULL, rva TEXT NOT NULL, PRIMARY KEY(dll_name, function_name), FOREIGN KEY(dll_name) REFERENCES dlls(name))')

    for dll in DLLS:
        cur.execute('INSERT INTO dlls VALUES (?, ?)', (dll["name"], hex(dll["base"])))
        for fname, frva in dll["functions"]:
            cur.execute('INSERT INTO exports VALUES (?, ?, ?)', (dll["name"], fname, hex(frva)))
        if dll["name"] in EXTRA_EXPORTS:
            for fname, frva in EXTRA_EXPORTS[dll["name"]].items():
                cur.execute('INSERT INTO exports VALUES (?, ?, ?)', (dll["name"], fname, hex(frva)))

    conn.commit()
    conn.close()

    print("PE dump, case files, config, and exports database generated successfully.")


if __name__ == '__main__':
    main()
