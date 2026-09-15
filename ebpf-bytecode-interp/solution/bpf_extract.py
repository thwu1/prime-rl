#!/usr/bin/env python3
"""Extract BPF program bytecode from an ELF object file."""
import os
import re
import subprocess
import sys
import tempfile


def find_cmd(*names):
    for n in names:
        try:
            subprocess.run([n, '--version'], capture_output=True, check=False)
            return n
        except FileNotFoundError:
            continue
    return None


def find_prog_section(elf_path):
    """Discover the BPF program section name using readelf."""
    readelf = find_cmd('readelf', 'llvm-readelf', 'llvm-readelf-18')
    if not readelf:
        return None
    result = subprocess.run([readelf, '-S', elf_path],
                            capture_output=True, text=True)
    skip = {'.strtab', '.symtab', '.comment', '.note', '.BTF', '.BTF.ext',
            '.debug_info', '.debug_abbrev', '.debug_line', '.debug_str',
            '.eh_frame', '.llvm_addrsig'}
    candidates = []
    for line in result.stdout.splitlines():
        m = re.search(r'\[\s*\d+\]\s+(\S+)\s+PROGBITS', line)
        if m:
            name = m.group(1)
            if name in skip or name.startswith('.rel'):
                continue
            candidates.append(name)
    # Prefer non-dot sections, then .text
    for c in candidates:
        if not c.startswith('.'):
            return c
    for c in candidates:
        if c == '.text':
            return c
    return candidates[0] if candidates else None


def extract_via_objcopy(elf_path, section):
    objcopy = find_cmd('llvm-objcopy', 'llvm-objcopy-18', 'objcopy')
    if not objcopy:
        return None
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        r = subprocess.run(
            [objcopy, '--dump-section', f'{section}={tmp_path}', elf_path],
            capture_output=True, text=True)
        if r.returncode != 0:
            return None
        with open(tmp_path, 'rb') as f:
            data = f.read()
        return data if data else None
    finally:
        os.unlink(tmp_path)


def extract_via_objdump(elf_path):
    """Fallback: parse llvm-objdump -d output for hex bytes."""
    objdump = find_cmd('llvm-objdump', 'llvm-objdump-18', 'objdump')
    if not objdump:
        return None
    r = subprocess.run([objdump, '-d', elf_path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    hex_parts = []
    for line in r.stdout.splitlines():
        m = re.match(r'\s+\d+:\s+((?:[0-9a-f]{2}\s)+)', line)
        if m:
            hex_parts.append(m.group(1).strip().replace(' ', ''))
    if not hex_parts:
        return None
    return bytes.fromhex(''.join(hex_parts))


def main():
    if len(sys.argv) != 2:
        print("Usage: bpf_extract <elf_file>", file=sys.stderr)
        sys.exit(1)

    elf_path = sys.argv[1]
    if not os.path.exists(elf_path):
        print(f"File not found: {elf_path}", file=sys.stderr)
        sys.exit(1)

    section = find_prog_section(elf_path)
    data = None
    if section:
        data = extract_via_objcopy(elf_path, section)

    if data is None:
        # Try common section names
        for s in ['prog', '.text', 'xdp', 'kprobe', 'tracepoint']:
            data = extract_via_objcopy(elf_path, s)
            if data:
                break

    if data is None:
        data = extract_via_objdump(elf_path)

    if data is None:
        print("Failed to extract BPF bytecode", file=sys.stderr)
        sys.exit(1)

    print(data.hex())


if __name__ == '__main__':
    main()
