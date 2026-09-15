#!/usr/bin/env python3
"""
Minimal x86_64 ELF JIT Loader.

Parses ELF64 relocatable object files (.o), loads code and data into
executable memory, resolves symbols across multiple objects, applies
x86_64 relocations, and executes functions via ctypes.

Inspired by LLVM ORC JIT's incremental compilation model used in clang-repl.
"""

import ctypes
import mmap
import struct

# ── ELF64 constants ──────────────────────────────────────────────────

EI_MAG = b'\x7fELF'
ELFCLASS64 = 2
ELFDATA2LSB = 1
ET_REL = 1
EM_X86_64 = 62

SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_RELA = 4
SHT_NOBITS = 8

SHF_ALLOC = 0x2

STB_LOCAL = 0
STB_GLOBAL = 1
STB_WEAK = 2

SHN_UNDEF = 0

R_X86_64_NONE = 0
R_X86_64_64 = 1
R_X86_64_PC32 = 2
R_X86_64_PLT32 = 4
R_X86_64_32 = 10
R_X86_64_32S = 11

PAGE_SIZE = 4096


def _align(val, align):
    if align <= 1:
        return val
    return (val + align - 1) & ~(align - 1)


def _cstr(data, offset):
    end = data.index(b'\x00', offset)
    return data[offset:end].decode('ascii')


# ── ELF data structures ─────────────────────────────────────────────

class _Section:
    __slots__ = ('name', 'sh_type', 'flags', 'data', 'size',
                 'addralign', 'link', 'info', 'entsize', 'addr')
    def __init__(self):
        self.addr = 0


class _Symbol:
    __slots__ = ('name', 'value', 'size', 'binding', 'stype', 'shndx', 'addr')
    def __init__(self):
        self.addr = 0


class _Rela:
    __slots__ = ('offset', 'sym_idx', 'rtype', 'addend')


# ── Object file parser ───────────────────────────────────────────────

class _ObjectFile:
    def __init__(self, path):
        self.sections = []
        self.symbols = []
        self.relas = {}          # target_section_idx -> [_Rela]
        self._parse(path)

    def _parse(self, path):
        with open(path, 'rb') as f:
            raw = f.read()

        # ELF header validation
        assert raw[:4] == EI_MAG
        assert raw[4] == ELFCLASS64
        assert raw[5] == ELFDATA2LSB
        assert struct.unpack_from('<H', raw, 16)[0] == ET_REL
        assert struct.unpack_from('<H', raw, 18)[0] == EM_X86_64

        e_shoff = struct.unpack_from('<Q', raw, 40)[0]
        e_shentsize = struct.unpack_from('<H', raw, 58)[0]
        e_shnum = struct.unpack_from('<H', raw, 60)[0]
        e_shstrndx = struct.unpack_from('<H', raw, 62)[0]

        # Parse section headers
        name_idxs = []
        for i in range(e_shnum):
            b = e_shoff + i * e_shentsize
            s = _Section()
            name_idxs.append(struct.unpack_from('<I', raw, b)[0])
            s.sh_type = struct.unpack_from('<I', raw, b + 4)[0]
            s.flags = struct.unpack_from('<Q', raw, b + 8)[0]
            sh_offset = struct.unpack_from('<Q', raw, b + 24)[0]
            s.size = struct.unpack_from('<Q', raw, b + 32)[0]
            s.link = struct.unpack_from('<I', raw, b + 40)[0]
            s.info = struct.unpack_from('<I', raw, b + 44)[0]
            s.addralign = max(struct.unpack_from('<Q', raw, b + 48)[0], 1)
            s.entsize = struct.unpack_from('<Q', raw, b + 56)[0]
            if s.sh_type == SHT_NOBITS:
                s.data = bytearray(s.size)
            else:
                s.data = bytearray(raw[sh_offset:sh_offset + s.size])
            self.sections.append(s)

        # Resolve section names
        shstrtab = self.sections[e_shstrndx].data
        for i, s in enumerate(self.sections):
            s.name = _cstr(bytes(shstrtab), name_idxs[i])

        # Parse symbol table
        for sec in self.sections:
            if sec.sh_type != SHT_SYMTAB:
                continue
            strtab = self.sections[sec.link].data
            n = sec.size // sec.entsize
            for j in range(n):
                o = j * sec.entsize
                sym = _Symbol()
                st_name = struct.unpack_from('<I', sec.data, o)[0]
                st_info = sec.data[o + 4]
                sym.shndx = struct.unpack_from('<H', sec.data, o + 6)[0]
                sym.value = struct.unpack_from('<Q', sec.data, o + 8)[0]
                sym.size = struct.unpack_from('<Q', sec.data, o + 16)[0]
                sym.name = _cstr(bytes(strtab), st_name)
                sym.binding = st_info >> 4
                sym.stype = st_info & 0xf
                self.symbols.append(sym)

        # Parse RELA relocations
        for sec in self.sections:
            if sec.sh_type != SHT_RELA:
                continue
            target_idx = sec.info
            entries = []
            n = sec.size // sec.entsize
            for j in range(n):
                o = j * sec.entsize
                r = _Rela()
                r.offset = struct.unpack_from('<Q', sec.data, o)[0]
                r_info = struct.unpack_from('<Q', sec.data, o + 8)[0]
                r.addend = struct.unpack_from('<q', sec.data, o + 16)[0]
                r.sym_idx = r_info >> 32
                r.rtype = r_info & 0xffffffff
                entries.append(r)
            self.relas[target_idx] = entries


# ── JIT Loader ───────────────────────────────────────────────────────

class JITLoader:
    """Load x86_64 ELF .o files and execute functions from JIT-mapped memory."""

    def __init__(self):
        self._objects = []
        self._globals = {}       # name -> address
        self._mem = None
        self._mem_base = 0
        self._mem_size = 0

    def load(self, *object_files):
        """Parse ELF .o files, allocate memory, resolve symbols, apply relocations."""
        for path in object_files:
            self._objects.append(_ObjectFile(path))
        self._place_sections()
        self._resolve_symbols()
        self._apply_relocations()

    def call(self, function_name, *args):
        """Call a loaded function by name with int args, return int result."""
        if function_name not in self._globals:
            raise RuntimeError(f"symbol not found: {function_name}")
        addr = self._globals[function_name]
        argtypes = [ctypes.c_int] * len(args)
        ftype = ctypes.CFUNCTYPE(ctypes.c_int, *argtypes)
        return ftype(addr)(*args)

    # ── internal ─────────────────────────────────────────────────────

    def _place_sections(self):
        """Allocate one RWX mmap region and lay out all ALLOC sections."""
        total = 0
        for obj in self._objects:
            for sec in obj.sections:
                if sec.flags & SHF_ALLOC:
                    total = _align(total, sec.addralign)
                    total += sec.size
        total = _align(total, PAGE_SIZE)
        if total == 0:
            total = PAGE_SIZE

        self._mem = mmap.mmap(
            -1, total,
            prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC,
        )
        self._mem_base = ctypes.addressof(ctypes.c_char.from_buffer(self._mem))
        self._mem_size = total

        offset = 0
        for obj in self._objects:
            for sec in obj.sections:
                if not (sec.flags & SHF_ALLOC):
                    continue
                offset = _align(offset, sec.addralign)
                sec.addr = self._mem_base + offset
                if sec.sh_type != SHT_NOBITS:
                    self._mem[offset:offset + len(sec.data)] = sec.data
                # NOBITS (BSS) is already zeroed by mmap
                offset += sec.size

    def _resolve_symbols(self):
        """Two-pass symbol resolution: collect defined, then resolve undefined."""
        # Pass 1: all defined symbols
        for obj in self._objects:
            for sym in obj.symbols:
                if sym.shndx == SHN_UNDEF or sym.shndx >= 0xff00:
                    continue
                sec = obj.sections[sym.shndx]
                sym.addr = sec.addr + sym.value
                if sym.binding in (STB_GLOBAL, STB_WEAK) and sym.name:
                    if sym.name not in self._globals or sym.binding == STB_GLOBAL:
                        self._globals[sym.name] = sym.addr

        # Pass 2: undefined symbols
        for obj in self._objects:
            for sym in obj.symbols:
                if sym.shndx != SHN_UNDEF or not sym.name:
                    continue
                if sym.name in self._globals:
                    sym.addr = self._globals[sym.name]
                else:
                    raise RuntimeError(f"undefined symbol: {sym.name}")

    def _apply_relocations(self):
        """Apply RELA relocations for all loaded objects."""
        for obj in self._objects:
            for sec_idx, relas in obj.relas.items():
                sec = obj.sections[sec_idx]
                if not (sec.flags & SHF_ALLOC):
                    continue
                for r in relas:
                    if r.rtype == R_X86_64_NONE:
                        continue
                    sym = obj.symbols[r.sym_idx]
                    S = sym.addr
                    A = r.addend
                    P = sec.addr + r.offset
                    mem_off = P - self._mem_base

                    if r.rtype in (R_X86_64_PC32, R_X86_64_PLT32):
                        # S + A - P, truncated to 32 bits
                        val = (S + A - P) & 0xffffffff
                        self._mem[mem_off:mem_off + 4] = struct.pack('<I', val)

                    elif r.rtype == R_X86_64_64:
                        val = (S + A) & 0xffffffffffffffff
                        self._mem[mem_off:mem_off + 8] = struct.pack('<Q', val)

                    elif r.rtype in (R_X86_64_32, R_X86_64_32S):
                        val = (S + A) & 0xffffffff
                        self._mem[mem_off:mem_off + 4] = struct.pack('<I', val)

                    else:
                        raise RuntimeError(
                            f"unsupported relocation type {r.rtype}")
