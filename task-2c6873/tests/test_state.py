
import subprocess
import struct
import os
import tempfile

ASSEMBLER = "/app/cpu0asm"
LINKER = "/app/cpu0ld"
SIMULATOR = "/app/cpu0sim"
PROGRAMS = "/app/programs"
TMPDIR = tempfile.mkdtemp(prefix="cpu0_test_")


# -- Helpers ----------------------------------------------------------------


def run_cmd(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, timeout=60, **kw)
    return r


def asm(src_name):
    """Assemble a .s file, return path to .o output."""
    src = os.path.join(PROGRAMS, src_name)
    out = os.path.join(TMPDIR, src_name.replace(".s", ".o"))
    r = run_cmd([ASSEMBLER, src, out])
    assert r.returncode == 0, f"asm {src_name} failed: {r.stderr}"
    assert os.path.isfile(out)
    return out


def link(obj_paths, out_name):
    """Link .o files into executable, return path."""
    out = os.path.join(TMPDIR, out_name)
    r = run_cmd([LINKER, "-o", out] + obj_paths)
    assert r.returncode == 0, f"link failed: {r.stderr}"
    assert os.path.isfile(out)
    return out


def sim(exe_path):
    """Simulate executable, return register dict."""
    r = run_cmd([SIMULATOR, exe_path])
    assert r.returncode == 0, f"sim failed: {r.stderr}"
    regs = {}
    for line in r.stdout.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            try:
                regs[k.strip()] = int(v.strip())
            except ValueError:
                pass
    return regs


def pipeline_single(src_name):
    """Full assemble -> link -> simulate for single file."""
    obj = asm(src_name)
    exe = link([obj], src_name.replace(".s", ""))
    return sim(exe)


def readelf(flag, path):
    """Run readelf with given flag(s) and return stdout."""
    r = run_cmd(["readelf", flag, path])
    return r.stdout


def get_elf_machine(path):
    """Read the e_machine field directly from the ELF header (big-endian)."""
    with open(path, "rb") as f:
        data = f.read(20)
    assert len(data) >= 20, "File too small to be ELF"
    return struct.unpack_from(">H", data, 18)[0]


def extract_text_from_elf(elf_path):
    """Extract raw .text section bytes from an ELF file."""
    with open(elf_path, "rb") as f:
        data = f.read()

    # ELF header fields (big-endian)
    e_shoff = struct.unpack_from(">I", data, 32)[0]
    e_shentsize = struct.unpack_from(">H", data, 46)[0]
    e_shnum = struct.unpack_from(">H", data, 48)[0]
    e_shstrndx = struct.unpack_from(">H", data, 50)[0]

    # Read .shstrtab
    shstr_hdr = e_shoff + e_shstrndx * e_shentsize
    shstr_off = struct.unpack_from(">I", data, shstr_hdr + 16)[0]
    shstr_sz = struct.unpack_from(">I", data, shstr_hdr + 20)[0]
    shstrtab = data[shstr_off:shstr_off + shstr_sz]

    for i in range(e_shnum):
        hdr = e_shoff + i * e_shentsize
        sh_name = struct.unpack_from(">I", data, hdr)[0]
        end = shstrtab.index(b"\0", sh_name)
        name = shstrtab[sh_name:end].decode()
        if name == ".text":
            sh_offset = struct.unpack_from(">I", data, hdr + 16)[0]
            sh_size = struct.unpack_from(">I", data, hdr + 20)[0]
            return data[sh_offset:sh_offset + sh_size]
    return None


# -- Tool existence ---------------------------------------------------------


def test_assembler_exists():
    assert os.path.isfile(ASSEMBLER), f"{ASSEMBLER} not found"
    assert os.access(ASSEMBLER, os.X_OK), f"{ASSEMBLER} not executable"


def test_linker_exists():
    assert os.path.isfile(LINKER), f"{LINKER} not found"
    assert os.access(LINKER, os.X_OK), f"{LINKER} not executable"


def test_simulator_exists():
    assert os.path.isfile(SIMULATOR), f"{SIMULATOR} not found"
    assert os.access(SIMULATOR, os.X_OK), f"{SIMULATOR} not executable"


# -- ELF structure (readelf + binary verification) -------------------------


def test_elf_header_object():
    """Assembled .o must be a valid ELF32 big-endian REL file with machine EM_CPU0 (0xC9)."""
    obj = asm("arith.s")
    hdr = readelf("-h", obj)
    assert "ELF32" in hdr, f"Not ELF32:\n{hdr}"
    assert "big endian" in hdr.lower(), f"Not big-endian:\n{hdr}"
    assert "REL" in hdr, f"Not relocatable:\n{hdr}"
    # readelf maps 0xC9 to a named architecture string, so check binary directly
    em = get_elf_machine(obj)
    assert em == 0xC9, f"e_machine not 0xC9, got 0x{em:04X}"


def test_elf_sections_present():
    """Object file must have .text and .symtab sections."""
    obj = asm("arith.s")
    sec = readelf("-S", obj)
    assert ".text" in sec, f"No .text section:\n{sec}"
    assert ".symtab" in sec, f"No .symtab section:\n{sec}"
    assert ".strtab" in sec, f"No .strtab section:\n{sec}"
    assert ".shstrtab" in sec, f"No .shstrtab section:\n{sec}"


def test_elf_global_symbol():
    """_start must appear as a GLOBAL symbol in the object file."""
    obj = asm("arith.s")
    syms = readelf("-s", obj)
    found = False
    for line in syms.split("\n"):
        if "_start" in line and "GLOBAL" in line:
            found = True
            break
    assert found, f"_start not found as GLOBAL:\n{syms}"


def test_elf_relocations_present():
    """main.o must have .rel.text with relocations for external symbols."""
    obj = asm("main.s")
    rel = readelf("-r", obj)
    assert ".rel.text" in rel or "Relocation" in rel, f"No relocation section:\n{rel}"
    assert "square" in rel, f"No relocation for 'square':\n{rel}"
    assert "cube" in rel, f"No relocation for 'cube':\n{rel}"
    assert "sum_range" in rel, f"No relocation for 'sum_range':\n{rel}"


def test_elf_relocation_count():
    """main.s has exactly 3 external JSUB calls -> 3 relocation entries."""
    obj = asm("main.s")
    rel = readelf("-r", obj)
    # Count lines that look like relocation entries (have hex offset at start)
    entries = [l for l in rel.split("\n") if l.strip() and l.strip()[0].isdigit()]
    assert len(entries) == 3, f"Expected 3 relocations, got {len(entries)}:\n{rel}"


def test_linked_elf_header():
    """Linked executable must have ET_EXEC type and machine EM_CPU0."""
    obj = asm("arith.s")
    exe = link([obj], "arith_exec")
    hdr = readelf("-h", exe)
    assert "EXEC" in hdr, f"Linked file not EXEC:\n{hdr}"
    em = get_elf_machine(exe)
    assert em == 0xC9, f"Linked e_machine not 0xC9, got 0x{em:04X}"


def test_linked_entry_point():
    """Linked executable must have a valid entry point."""
    obj = asm("arith.s")
    exe = link([obj], "arith_exec2")
    hdr = readelf("-h", exe)
    # Entry point should be present and may be 0x0 for single-file
    assert "Entry point" in hdr, f"No entry point:\n{hdr}"


# -- Instruction encoding --------------------------------------------------


def test_arith_encoding():
    """Verify instruction encodings in arith.o .text section."""
    obj = asm("arith.s")
    text = extract_text_from_elf(obj)
    assert text is not None, "Could not extract .text"
    assert len(text) == 28, f"Expected 28 bytes (7 instr), got {len(text)}"

    words = [struct.unpack(">I", text[i:i+4])[0] for i in range(0, len(text), 4)]

    # addiu $v0, $zero, 10 -> [09][2][0][000A]
    assert words[0] == 0x0920000A, f"Inst 0: got 0x{words[0]:08X}"
    # addiu $v1, $zero, 3  -> [09][3][0][0003]
    assert words[1] == 0x09300003, f"Inst 1: got 0x{words[1]:08X}"
    # addu $a0, $v0, $v1   -> [11][4][2][3][000]
    assert words[2] == 0x11423000, f"Inst 2: got 0x{words[2]:08X}"
    # subu $a1, $v0, $v1   -> [12][5][2][3][000]
    assert words[3] == 0x12523000, f"Inst 3: got 0x{words[3]:08X}"
    # mul $t0, $a0, $a1    -> [17][7][4][5][000]
    assert words[4] == 0x17745000, f"Inst 4: got 0x{words[4]:08X}"
    # addu $v0, $t0, $zero -> [11][2][7][0][000]
    assert words[5] == 0x11270000, f"Inst 5: got 0x{words[5]:08X}"
    # ret $lr              -> [3C][E][0][0][000]
    assert words[6] == 0x3CE00000, f"Inst 6: got 0x{words[6]:08X}"


def test_factorial_branch_encoding():
    """Verify branch offset encoding in factorial.o."""
    obj = asm("factorial.s")
    text = extract_text_from_elf(obj)
    assert text is not None
    assert len(text) == 28, f"Expected 28 bytes, got {len(text)}"

    words = [struct.unpack(">I", text[i:i+4])[0] for i in range(0, len(text), 4)]

    # beq $t1, $zero, loop at addr 0x14, target=0x08
    # offset = 0x08 - (0x14+4) = -16 = 0xFFF0
    # [37][8][0][FFF0]
    assert words[5] == 0x3780FFF0, f"BEQ: got 0x{words[5]:08X}"


def test_main_relocation_offsets():
    """Verify relocation offsets for JSUB instructions in main.o."""
    obj = asm("main.s")

    # Read the ELF to find relocation entries
    with open(obj, "rb") as f:
        data = f.read()

    e_shoff = struct.unpack_from(">I", data, 32)[0]
    e_shentsize = struct.unpack_from(">H", data, 46)[0]
    e_shnum = struct.unpack_from(">H", data, 48)[0]
    e_shstrndx = struct.unpack_from(">H", data, 50)[0]

    shstr_hdr = e_shoff + e_shstrndx * e_shentsize
    shstr_off = struct.unpack_from(">I", data, shstr_hdr + 16)[0]
    shstr_sz = struct.unpack_from(">I", data, shstr_hdr + 20)[0]
    shstrtab = data[shstr_off:shstr_off + shstr_sz]

    rel_data = None
    for i in range(e_shnum):
        hdr = e_shoff + i * e_shentsize
        sh_name = struct.unpack_from(">I", data, hdr)[0]
        end = shstrtab.index(b"\0", sh_name)
        name = shstrtab[sh_name:end].decode()
        if name == ".rel.text":
            sh_offset = struct.unpack_from(">I", data, hdr + 16)[0]
            sh_size = struct.unpack_from(">I", data, hdr + 20)[0]
            rel_data = data[sh_offset:sh_offset + sh_size]
            break

    assert rel_data is not None, "No .rel.text section"
    assert len(rel_data) == 24, f"Expected 24 bytes (3 entries), got {len(rel_data)}"

    # Parse relocation offsets
    offsets = []
    for i in range(3):
        r_offset = struct.unpack_from(">I", rel_data, i * 8)[0]
        r_info = struct.unpack_from(">I", rel_data, i * 8 + 4)[0]
        rtype = r_info & 0xFF
        assert rtype == 1, f"Expected R_CPU0_PC24 (1), got {rtype}"
        offsets.append(r_offset)

    # jsub square at offset 0x0C, jsub cube at 0x18, jsub sum_range at 0x2C
    assert offsets[0] == 0x0C, f"First reloc at 0x{offsets[0]:02X}, expected 0x0C"
    assert offsets[1] == 0x18, f"Second reloc at 0x{offsets[1]:02X}, expected 0x18"
    assert offsets[2] == 0x2C, f"Third reloc at 0x{offsets[2]:02X}, expected 0x2C"


# -- Execution correctness -------------------------------------------------


def test_exec_arith():
    """(10+3)*(10-3) = 91."""
    regs = pipeline_single("arith.s")
    assert regs["r2"] == 91, f"Expected r2=91, got {regs.get('r2')}"


def test_exec_factorial():
    """10! = 3628800."""
    regs = pipeline_single("factorial.s")
    assert regs["r2"] == 3628800, f"Expected r2=3628800, got {regs.get('r2')}"


def test_exec_gcd():
    """GCD(252, 105) = 21 via Euclidean algorithm with DIVU/MFHI."""
    regs = pipeline_single("gcd.s")
    assert regs["r2"] == 21, f"Expected r2=21, got {regs.get('r2')}"


def test_exec_multifile():
    """square(7)+cube(3)+sum_range(10) = 49+27+55 = 131 via cross-file linking."""
    main_o = asm("main.s")
    math_o = asm("mathlib.s")
    util_o = asm("utils.s")
    exe = link([main_o, math_o, util_o], "multifile")
    regs = sim(exe)
    assert regs["r2"] == 131, f"Expected r2=131, got {regs.get('r2')}"


def test_sp_restored_multifile():
    """SP must be restored to 0xFF00 after multi-file program."""
    main_o = asm("main.s")
    math_o = asm("mathlib.s")
    util_o = asm("utils.s")
    exe = link([main_o, math_o, util_o], "multifile_sp")
    regs = sim(exe)
    assert regs["r13"] == 0xFF00, f"Expected SP=0xFF00, got {regs.get('r13')}"


def test_multifile_link_order():
    """Linking in different order must still produce correct results."""
    main_o = asm("main.s")
    math_o = asm("mathlib.s")
    util_o = asm("utils.s")
    # Link with main first but libs in reverse order
    exe = link([main_o, util_o, math_o], "multifile_reorder")
    regs = sim(exe)
    assert regs["r2"] == 131, f"Expected r2=131 with reordered link, got {regs.get('r2')}"
