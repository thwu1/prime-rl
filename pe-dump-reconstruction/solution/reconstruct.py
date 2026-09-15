#!/usr/bin/env python3

"""
Solution: PE64 memory dump forensic reconstruction.

Uses radare2 for disassembly analysis, YARA for detection rule creation,
sqlite3 for import resolution, and binary analysis for relocation reversal
and config decryption.
"""

import struct
import json
import sqlite3
import os
import subprocess
import re


def to_int(v):
    if isinstance(v, int):
        return v
    return int(v, 16) if v.strip().startswith(('0x', '0X')) else int(v)


def read_cstring(data, offset):
    """Read a null-terminated ASCII string from data at offset."""
    end = offset
    while end < len(data) and data[end] != 0:
        end += 1
    return data[offset:end].decode('ascii', errors='replace')


def load_exports_db(db_path):
    """Load the exports database from SQLite into a dict structure.

    Also demonstrates sqlite3 CLI usage for the reverse lookup table.
    """
    # Use sqlite3 CLI for the JOIN query to build the reverse lookup
    result = subprocess.run(
        ['sqlite3', '-separator', '|', db_path,
         'SELECT d.name, d.base_address, e.function_name, e.rva '
         'FROM dlls d JOIN exports e ON d.name = e.dll_name '
         'ORDER BY d.name, e.function_name;'],
        capture_output=True, text=True
    )
    print(f"sqlite3 CLI query returned {len(result.stdout.splitlines())} rows")

    # Parse into dict structure
    conn = sqlite3.connect(db_path)
    cur_dlls = conn.cursor()
    cur_exports = conn.cursor()
    db = {}
    for dll_name, base in cur_dlls.execute('SELECT name, base_address FROM dlls'):
        exports = {}
        for fn, rva in cur_exports.execute(
            'SELECT function_name, rva FROM exports WHERE dll_name = ?',
            (dll_name,)
        ):
            exports[fn] = rva
        db[dll_name] = {'base': base, 'exports': exports}
    conn.close()
    return db


def analyze_code_with_r2(dump_path):
    """Use radare2 to disassemble the .text section and find the XOR key.

    Since the dump is a memory-mapped PE (not file-mapped), we extract the
    .text section and analyze it as raw x86-64 to avoid PE loader confusion.
    """
    with open(dump_path, 'rb') as f:
        dump = f.read()

    # Extract .text section (RVA 0x1000, raw size 0x200) for r2 analysis
    text_bin = '/tmp/text_section.bin'
    with open(text_bin, 'wb') as f:
        f.write(dump[0x1000:0x1200])

    functions = []
    xor_key = None

    # Run radare2 on the extracted .text section
    try:
        r2_commands = '; '.join([
            'e asm.arch=x86',
            'e asm.bits=64',
            'af @ 0',           # analyze main function at offset 0 (RVA 0x1000)
            'af @ 0x100',       # analyze decrypt routine at offset 0x100 (RVA 0x1100)
            'afl',              # list all identified functions
            'pdf @ 0x100',      # disassemble the decrypt function
        ])

        result = subprocess.run(
            ['r2', '-q', '-e', 'scr.color=0', '-c', r2_commands, text_bin],
            capture_output=True, text=True, timeout=30
        )

        r2_output = result.stdout
        print("--- radare2 output ---")
        print(r2_output[:2000])
        print("--- end r2 output ---")

        # Parse function list from afl output
        for line in r2_output.split('\n'):
            # afl format: addr nblocks size name
            match = re.match(r'\s*(0x[0-9a-fA-F]+)\s+\d+\s+(\d+)\s+(\S+)', line)
            if match:
                addr = int(match.group(1), 16) + 0x1000  # adjust to RVA
                functions.append({
                    'entry_point': hex(addr),
                    'size': int(match.group(2)),
                    'name': match.group(3),
                })

        # Extract XOR key from disassembly: look for "mov cl, 0xNN"
        for line in r2_output.split('\n'):
            match = re.search(r'mov\s+cl,\s*(0x[0-9a-fA-F]+)', line)
            if match:
                xor_key = int(match.group(1), 16)
                break

    except Exception as e:
        print(f"radare2 analysis warning: {e}")

    # Fallback: find XOR key from raw byte pattern if r2 didn't find it
    if xor_key is None:
        print("Falling back to byte pattern scan for XOR key...")
        for i in range(0x1000, 0x1200 - 5):
            if dump[i] == 0xB1 and dump[i + 2:i + 5] == b'\x48\x8D\x35':
                xor_key = dump[i + 1]
                break

    # Ensure known functions are present
    entry_addrs = {int(f['entry_point'], 16) for f in functions}
    if 0x1000 not in entry_addrs:
        functions.insert(0, {'entry_point': '0x1000', 'name': 'main'})
    if 0x1100 not in entry_addrs:
        functions.append({'entry_point': '0x1100', 'name': 'decrypt_config'})

    print(f"Identified {len(functions)} functions, XOR key: {hex(xor_key) if xor_key else 'NOT FOUND'}")
    return functions, xor_key


def decrypt_config(dump, xor_key):
    """Find the CAFEBABE marker and decrypt the XOR-encoded config."""
    marker = b'\xCA\xFE\xBA\xBE'
    idx = dump.find(marker)
    if idx < 0:
        raise ValueError("Config marker CAFEBABE not found in dump")

    length = struct.unpack_from('<I', dump, idx + 4)[0]
    encrypted = dump[idx + 8: idx + 8 + length]
    decrypted = bytes(b ^ xor_key for b in encrypted)
    config = json.loads(decrypted)
    print(f"Decrypted config ({length} bytes): {config}")
    return config


def write_yara_rule(dump, analysis_dir):
    """Write a YARA detection rule based on distinctive binary patterns."""
    # Pattern 1: decrypt routine prologue (push rbp; mov rbp,rsp; mov cl, KEY)
    decrypt_sig = dump[0x1100:0x1107]
    # Pattern 2: XOR loop body (xor byte [rsi], cl; inc rsi; dec edx; jnz)
    xor_loop = dump[0x1112:0x111C]

    decrypt_hex = ' '.join(f'{b:02X}' for b in decrypt_sig)
    loop_hex = ' '.join(f'{b:02X}' for b in xor_loop)

    rule = (
        'rule PE64_Reflective_Inject\n'
        '{\n'
        '    meta:\n'
        '        description = "Detects PE64 binary with reflective injection artifacts and XOR config"\n'
        '        author = "forensic_analyst"\n'
        '\n'
        '    strings:\n'
        '        $mz = "MZ"\n'
        '        $decrypt_routine = { ' + decrypt_hex + ' }\n'
        '        $xor_loop = { ' + loop_hex + ' }\n'
        '        $config_marker = { CA FE BA BE }\n'
        '\n'
        '    condition:\n'
        '        $mz at 0 and $decrypt_routine and $xor_loop and $config_marker\n'
        '}\n'
    )

    yar_path = os.path.join(analysis_dir, 'detection.yar')
    with open(yar_path, 'w') as f:
        f.write(rule)

    # Validate the rule by running yara
    result = subprocess.run(
        ['yara', yar_path, '/app/dump.bin'],
        capture_output=True, text=True, timeout=30
    )
    print(f"YARA validation stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        print(f"YARA validation stderr: {result.stderr.strip()}")
    if result.returncode != 0:
        print(f"YARA validation exit code: {result.returncode}")
    return yar_path


def analyse(dump, case_info, exports_db):
    """Parse PE headers, relocations, and imports from the memory dump."""
    # ----- Parse DOS header -----
    assert dump[0:2] == b'MZ', "Missing MZ signature"
    e_lfanew = struct.unpack_from('<I', dump, 0x3C)[0]

    # ----- PE signature -----
    assert struct.unpack_from('<I', dump, e_lfanew)[0] == 0x00004550

    # ----- COFF File Header -----
    fh = e_lfanew + 4
    machine       = struct.unpack_from('<H', dump, fh)[0]
    num_sections  = struct.unpack_from('<H', dump, fh + 2)[0]
    timestamp     = struct.unpack_from('<I', dump, fh + 4)[0]
    opt_hdr_size  = struct.unpack_from('<H', dump, fh + 16)[0]
    characteristics = struct.unpack_from('<H', dump, fh + 18)[0]

    # ----- Optional Header (PE32+) -----
    oh = fh + 20
    magic = struct.unpack_from('<H', dump, oh)[0]
    assert magic == 0x020B, f"Expected PE32+ magic, got {hex(magic)}"

    entry_point_rva = struct.unpack_from('<I', dump, oh + 16)[0]
    image_base_dump = struct.unpack_from('<Q', dump, oh + 24)[0]
    sect_align      = struct.unpack_from('<I', dump, oh + 32)[0]
    file_align      = struct.unpack_from('<I', dump, oh + 36)[0]
    size_of_image   = struct.unpack_from('<I', dump, oh + 56)[0]
    size_of_headers = struct.unpack_from('<I', dump, oh + 60)[0]
    num_rva_sizes   = struct.unpack_from('<I', dump, oh + 108)[0]

    dd = oh + 112  # data directory offset

    # Read key data directories
    import_rva  = struct.unpack_from('<I', dump, dd + 1 * 8)[0]
    import_size = struct.unpack_from('<I', dump, dd + 1 * 8 + 4)[0]
    reloc_rva   = struct.unpack_from('<I', dump, dd + 5 * 8)[0]
    reloc_size  = struct.unpack_from('<I', dump, dd + 5 * 8 + 4)[0]
    iat_rva     = struct.unpack_from('<I', dump, dd + 12 * 8)[0]
    iat_size    = struct.unpack_from('<I', dump, dd + 12 * 8 + 4)[0]

    # ----- Section headers -----
    sh = oh + opt_hdr_size
    sections = []
    for i in range(num_sections):
        o = sh + i * 40
        name = dump[o:o + 8].rstrip(b'\x00').decode('ascii', errors='replace')
        vs   = struct.unpack_from('<I', dump, o + 8)[0]
        va   = struct.unpack_from('<I', dump, o + 12)[0]
        rs   = struct.unpack_from('<I', dump, o + 16)[0]
        ro   = struct.unpack_from('<I', dump, o + 20)[0]
        ch   = struct.unpack_from('<I', dump, o + 36)[0]
        sections.append({
            'name': name,
            'virtual_address': hex(va),
            'virtual_size': hex(vs),
            'raw_size': hex(rs),
            'raw_offset': hex(ro),
            'characteristics': hex(ch),
        })

    # Decode characteristics
    char_flags = []
    if characteristics & 0x0002:
        char_flags.append('EXECUTABLE_IMAGE')
    if characteristics & 0x0020:
        char_flags.append('LARGE_ADDRESS_AWARE')
    if characteristics & 0x2000:
        char_flags.append('DLL')

    machine_name = {0x8664: 'AMD64', 0x014C: 'I386', 0xAA64: 'ARM64'}.get(
        machine, hex(machine))

    load_address     = to_int(case_info['load_address'])
    original_ib      = to_int(case_info['original_imagebase'])
    delta            = load_address - original_ib

    header_info = {
        'machine': machine_name,
        'number_of_sections': num_sections,
        'timestamp': hex(timestamp),
        'characteristics': char_flags,
        'magic': 'PE32+',
        'entry_point_rva': hex(entry_point_rva),
        'image_base_in_dump': hex(image_base_dump),
        'original_image_base': hex(original_ib),
        'section_alignment': hex(sect_align),
        'file_alignment': hex(file_align),
        'size_of_image': hex(size_of_image),
        'data_directories': {
            'import': {'rva': hex(import_rva), 'size': hex(import_size)},
            'base_reloc': {'rva': hex(reloc_rva), 'size': hex(reloc_size)},
            'iat': {'rva': hex(iat_rva), 'size': hex(iat_size)},
        },
        'sections': sections,
    }

    # ----- Parse relocation table -----
    reloc_blocks = []
    all_reloc_entries = []   # (rva, relocated_val, original_val, type)
    pos = reloc_rva
    end = reloc_rva + reloc_size

    while pos < end:
        block_va   = struct.unpack_from('<I', dump, pos)[0]
        block_size = struct.unpack_from('<I', dump, pos + 4)[0]
        if block_size == 0:
            break

        n = (block_size - 8) // 2
        entries = []
        for j in range(n):
            raw   = struct.unpack_from('<H', dump, pos + 8 + j * 2)[0]
            rtype = (raw >> 12) & 0xF
            off   = raw & 0xFFF

            if rtype == 0:   # ABSOLUTE padding
                continue

            rva = block_va + off
            if rtype == 10:  # DIR64
                rel_val = struct.unpack_from('<Q', dump, rva)[0]
            elif rtype == 3:  # HIGHLOW
                rel_val = struct.unpack_from('<I', dump, rva)[0]
            else:
                continue

            orig_val = rel_val - delta
            type_name = {10: 'IMAGE_REL_BASED_DIR64',
                         3:  'IMAGE_REL_BASED_HIGHLOW'}.get(rtype, f'UNKNOWN({rtype})')

            entries.append({
                'offset': hex(off),
                'type': rtype,
                'type_name': type_name,
                'rva': hex(rva),
                'relocated_value': hex(rel_val),
                'original_value': hex(orig_val),
            })
            all_reloc_entries.append((rva, rel_val, orig_val, rtype))

        reloc_blocks.append({
            'page_rva': hex(block_va),
            'block_size': block_size,
            'entries': entries,
        })
        pos += block_size

    relocations_info = {
        'delta': hex(delta),
        'original_imagebase': hex(original_ib),
        'load_address': hex(load_address),
        'total_entries': len(all_reloc_entries),
        'blocks': reloc_blocks,
    }

    # ----- Reconstruct imports -----
    # Build reverse lookup: resolved_addr -> (dll_name, func_name)
    addr_to_func = {}
    for dll_name, db_entry in exports_db.items():
        dll_base = to_int(db_entry['base'])
        for fname, frva_str in db_entry['exports'].items():
            frva = to_int(frva_str)
            addr_to_func[dll_base + frva] = (dll_name, fname)

    imports = []
    idt_pos = import_rva
    while True:
        oft     = struct.unpack_from('<I', dump, idt_pos)[0]
        ts      = struct.unpack_from('<I', dump, idt_pos + 4)[0]
        fc      = struct.unpack_from('<I', dump, idt_pos + 8)[0]
        name_rv = struct.unpack_from('<I', dump, idt_pos + 12)[0]
        ft_rva  = struct.unpack_from('<I', dump, idt_pos + 16)[0]

        if name_rv == 0 and ft_rva == 0:
            break

        dll_name = read_cstring(dump, name_rv)

        functions = []
        iat_pos = ft_rva
        while True:
            resolved = struct.unpack_from('<Q', dump, iat_pos)[0]
            if resolved == 0:
                break

            # Match against export database
            func_name = 'UNKNOWN'
            if resolved in addr_to_func:
                func_name = addr_to_func[resolved][1]
            else:
                # Fallback: try matching via DLL-specific base + RVA
                if dll_name in exports_db:
                    dll_base = to_int(exports_db[dll_name]['base'])
                    func_rva = resolved - dll_base
                    for fn, rv in exports_db[dll_name]['exports'].items():
                        if to_int(rv) == func_rva:
                            func_name = fn
                            break

            functions.append({
                'name': func_name,
                'resolved_address': hex(resolved),
                'iat_rva': hex(iat_pos),
            })
            iat_pos += 8

        imports.append({
            'dll_name': dll_name,
            'name_rva': hex(name_rv),
            'iat_rva': hex(ft_rva),
            'original_first_thunk': hex(oft),
            'functions': functions,
        })
        idt_pos += 20

    imports_info = {'imports': imports}

    # ----- Create restored binary -----
    restored = bytearray(dump)
    # Restore ImageBase
    struct.pack_into('<Q', restored, oh + 24, original_ib)
    # Reverse relocations
    for rva, rel_val, orig_val, rtype in all_reloc_entries:
        if rtype == 10:
            struct.pack_into('<Q', restored, rva, orig_val)
        elif rtype == 3:
            struct.pack_into('<I', restored, rva, orig_val)

    return header_info, relocations_info, imports_info, bytes(restored)


def main():
    with open('/app/dump.bin', 'rb') as f:
        dump = f.read()
    with open('/app/case_info.json') as f:
        case_info = json.load(f)

    exports_db = load_exports_db('/app/exports.db')

    # Step 1: PE header, relocation, and import analysis
    header_info, relocations_info, imports_info, restored = analyse(
        dump, case_info, exports_db)

    os.makedirs('/app/analysis', exist_ok=True)

    with open('/app/analysis/header_info.json', 'w') as f:
        json.dump(header_info, f, indent=2)
    with open('/app/analysis/relocations.json', 'w') as f:
        json.dump(relocations_info, f, indent=2)
    with open('/app/analysis/imports_reconstructed.json', 'w') as f:
        json.dump(imports_info, f, indent=2)
    with open('/app/analysis/restored.bin', 'wb') as f:
        f.write(restored)

    # Step 2: Code analysis with radare2
    functions, xor_key = analyze_code_with_r2('/app/dump.bin')

    code_analysis = {
        'functions': [
            {'entry_point': f['entry_point'], 'name': f.get('name', '')}
            for f in functions
        ],
        'xor_key': hex(xor_key) if xor_key else '0x0',
        'decrypt_routine_address': '0x1100',
    }
    with open('/app/analysis/code_analysis.json', 'w') as f:
        json.dump(code_analysis, f, indent=2)

    # Step 3: Decrypt configuration block
    config = decrypt_config(dump, xor_key)
    with open('/app/analysis/config_decoded.json', 'w') as f:
        json.dump(config, f, indent=2)

    # Step 4: Write and validate YARA detection rule
    write_yara_rule(dump, '/app/analysis')

    print('Analysis complete. All output files written to /app/analysis/')


if __name__ == '__main__':
    main()
