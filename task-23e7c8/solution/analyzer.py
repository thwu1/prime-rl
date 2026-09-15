#!/usr/bin/env python3
"""
eBPF Reachability Analyzer — reads ELF objects and SQLite database.

"""

import json
import struct
import sqlite3
import os


def parse_elf_program(filepath):
    """Parse a BPF ELF relocatable object to extract bytecodes and relocations."""
    with open(filepath, 'rb') as f:
        data = f.read()

    # ELF64 header (skip 16-byte e_ident)
    (_, _, _, _, _, e_shoff, _, _, _, _, _,
     e_shnum, e_shstrndx) = struct.unpack_from('<HHIQQQIHHHHHH', data, 16)

    # Read section headers (each 64 bytes)
    shdrs = []
    for i in range(e_shnum):
        o = e_shoff + i * 64
        shdrs.append(struct.unpack_from('<IIQQQQIIQQ', data, o))

    # .shstrtab for section names
    sh = shdrs[e_shstrndx]
    shstrtab = data[sh[4]:sh[4] + sh[5]]

    def cstr(buf, idx):
        end = buf.index(b'\x00', idx)
        return buf[idx:end].decode()

    sec = {}
    for s in shdrs:
        sec[cstr(shstrtab, s[0])] = s

    # .text bytecodes
    t = sec['.text']
    bytecode = data[t[4]:t[4] + t[5]]

    # .strtab (symbol name strings)
    st = sec['.strtab']
    strtab = data[st[4]:st[4] + st[5]]

    # .symtab (symbol entries, 24 bytes each)
    sy = sec['.symtab']
    sd = data[sy[4]:sy[4] + sy[5]]
    symbols = [cstr(strtab, struct.unpack_from('<I', sd, i * 24)[0])
               for i in range(len(sd) // 24)]

    # .rela.text (relocation entries, 24 bytes each)
    r = sec['.rela.text']
    rd = data[r[4]:r[4] + r[5]]
    relocations = []
    for i in range(len(rd) // 24):
        r_offset, r_info, _ = struct.unpack_from('<QQq', rd, i * 24)
        relocations.append({
            'insn_idx': r_offset // 8,
            'map_name': symbols[r_info >> 32],
        })

    return bytecode, relocations


def decode_instructions(bytecode):
    insns = []
    idx = 0
    offset = 0
    while offset < len(bytecode):
        opcode, regs, off, imm = struct.unpack_from('<BBhi', bytecode, offset)
        insns.append({
            'idx': idx,
            'opcode': opcode,
            'dst': regs & 0x0F,
            'src': (regs >> 4) & 0x0F,
            'off': off,
            'imm': imm,
        })
        idx += 1
        offset += 8
    return insns


def build_rodata_bytes(config_values, rodata_fields, total_size):
    data = bytearray(total_size)
    for field in rodata_fields:
        struct.pack_into('<I', data, field['offset'],
                         config_values.get(field['name'], 0))
    return bytes(data)


def read_u32(rodata, offset):
    return struct.unpack_from('<I', rodata, offset)[0]


def writes_to_reg(insn, reg):
    op = insn['opcode']
    if op == 0x00:
        return False
    cls = op & 0x07
    if cls in (0x04, 0x07):
        return insn['dst'] == reg
    if cls == 0x01:
        return insn['dst'] == reg
    if op == 0x18:
        return insn['dst'] == reg
    if op == 0x85:
        return reg <= 5
    return False


def backtrace_register(insns, from_idx, target_reg, rodata_bytes,
                       reloc_by_insn, rodata_map_name):
    for i in range(from_idx - 1, -1, -1):
        insn = insns[i]
        if insn['opcode'] == 0x00:
            continue
        if insn['opcode'] == 0x61 and insn['dst'] == target_reg:
            ptr_reg = insn['src']
            load_off = insn['off']
            for j in range(i - 1, -1, -1):
                jinsn = insns[j]
                if jinsn['opcode'] == 0x00:
                    continue
                if writes_to_reg(jinsn, ptr_reg):
                    if jinsn['opcode'] == 0x18 and jinsn['src'] == 2:
                        if j in reloc_by_insn:
                            if reloc_by_insn[j]['map_name'] == rodata_map_name:
                                if (load_off >= 0
                                        and load_off + 4 <= len(rodata_bytes)):
                                    return read_u32(rodata_bytes, load_off)
                    return None
            return None
        if writes_to_reg(insn, target_reg):
            return None
    return None


def try_resolve_branch(insns, branch_insn, rodata_bytes, reloc_by_insn,
                       rodata_map_name):
    op = branch_insn['opcode']
    if (op & 0x08) != 0:
        return None

    dst_value = backtrace_register(
        insns, branch_insn['idx'], branch_insn['dst'],
        rodata_bytes, reloc_by_insn, rodata_map_name)

    if dst_value is None:
        return None

    imm = branch_insn['imm']
    operation = op & 0xF0

    if operation == 0x10:
        return 'always_taken' if dst_value == imm else 'never_taken'
    elif operation == 0x50:
        return 'always_taken' if dst_value != imm else 'never_taken'
    elif operation == 0x20:
        return 'always_taken' if dst_value > imm else 'never_taken'
    elif operation == 0x30:
        return 'always_taken' if dst_value >= imm else 'never_taken'
    elif operation == 0xA0:
        return 'always_taken' if dst_value < imm else 'never_taken'
    elif operation == 0xB0:
        return 'always_taken' if dst_value <= imm else 'never_taken'
    return None


def find_tail_call_index(insns, call_idx):
    for i in range(call_idx - 1, max(call_idx - 6, -1), -1):
        insn = insns[i]
        if insn['opcode'] == 0xb7 and insn['dst'] == 3:
            return insn['imm']
        if writes_to_reg(insn, 3):
            break
    return None


def analyze_program(bytecode, relocations, rodata_bytes, rodata_map_name):
    insns = decode_instructions(bytecode)
    reloc_by_insn = {r['insn_idx']: r for r in relocations}
    n = len(insns)
    if n == 0:
        return set(), set()

    # Basic block boundaries
    block_starts = {0}
    for insn in insns:
        idx = insn['idx']
        op = insn['opcode']
        if op == 0x00:
            continue
        cls = op & 0x07
        if op == 0x05:
            target = idx + 1 + insn['off']
            if 0 <= target < n:
                block_starts.add(target)
            if idx + 1 < n:
                block_starts.add(idx + 1)
        elif op == 0x95:
            if idx + 1 < n:
                block_starts.add(idx + 1)
        elif cls in (0x05, 0x06) and op not in (0x05, 0x85, 0x95):
            target = idx + 1 + insn['off']
            if 0 <= target < n:
                block_starts.add(target)
            if idx + 1 < n:
                block_starts.add(idx + 1)

    sorted_starts = sorted(block_starts)
    blocks = {}
    for i, start in enumerate(sorted_starts):
        end = sorted_starts[i + 1] if i + 1 < len(sorted_starts) else n
        blocks[start] = list(range(start, end))

    # Block successors
    block_succ = {}
    for start, idxs in blocks.items():
        if not idxs:
            block_succ[start] = []
            continue
        last_idx = idxs[-1]
        last = insns[last_idx]
        op = last['opcode']

        if (op == 0x00 and last_idx > 0
                and insns[last_idx - 1]['opcode'] == 0x18):
            nxt = last_idx + 1
            block_succ[start] = [nxt] if nxt in blocks else []
            continue

        successors = []
        if op == 0x05:
            t = last_idx + 1 + last['off']
            if t in blocks:
                successors.append(t)
        elif op == 0x95:
            pass
        elif op == 0x85:
            nxt = last_idx + 1
            if nxt in blocks:
                successors.append(nxt)
        elif (op & 0x07) in (0x05, 0x06) and op not in (0x05, 0x85, 0x95):
            target = last_idx + 1 + last['off']
            fallthrough = last_idx + 1
            resolved = try_resolve_branch(
                insns, last, rodata_bytes, reloc_by_insn, rodata_map_name)
            if resolved == 'always_taken':
                if target in blocks:
                    successors.append(target)
            elif resolved == 'never_taken':
                if fallthrough in blocks:
                    successors.append(fallthrough)
            else:
                if target in blocks:
                    successors.append(target)
                if fallthrough in blocks:
                    successors.append(fallthrough)
        else:
            nxt = last_idx + 1
            if nxt in blocks:
                successors.append(nxt)
        block_succ[start] = successors

    # BFS reachability
    reachable = set()
    wl = [0]
    while wl:
        b = wl.pop()
        if b in reachable:
            continue
        reachable.add(b)
        for s in block_succ.get(b, []):
            if s not in reachable:
                wl.append(s)

    # Collect maps and tail calls from reachable blocks
    reach_maps = set()
    reach_tc = set()
    for b in reachable:
        for idx in blocks[b]:
            if idx in reloc_by_insn:
                reach_maps.add(reloc_by_insn[idx]['map_name'])
            insn = insns[idx]
            if insn['opcode'] == 0x85 and insn['imm'] == 12:
                tc = find_tail_call_index(insns, idx)
                if tc is not None:
                    reach_tc.add(tc)

    return reach_maps, reach_tc


def main():
    conn = sqlite3.connect('/app/ebpf_programs.db')
    conn.row_factory = sqlite3.Row

    meta = {r['key']: r['value']
            for r in conn.execute('SELECT key, value FROM metadata')}
    rodata_map_name = meta['rodata_map_name']
    rodata_total_size = int(meta['rodata_total_size'])

    rodata_fields = [
        {'name': r['field_name'], 'offset': r['byte_offset'], 'size': r['size']}
        for r in conn.execute(
            'SELECT field_name, byte_offset, size FROM rodata_layout '
            'ORDER BY byte_offset')]

    all_map_names = {r['name'] for r in conn.execute('SELECT name FROM maps')}

    programs = {}
    all_prog_names = set()
    progs_by_tc = {}
    entry = None
    for r in conn.execute(
            'SELECT name, elf_file, is_entry, tail_call_index FROM programs'):
        programs[r['name']] = {
            'elf_file': r['elf_file'],
            'tc_idx': r['tail_call_index'],
        }
        all_prog_names.add(r['name'])
        if r['is_entry']:
            entry = r['name']
        if r['tail_call_index'] is not None:
            progs_by_tc[r['tail_call_index']] = r['name']

    configs = {}
    for r in conn.execute('SELECT name FROM configs'):
        configs[r['name']] = {}
    for r in conn.execute(
            'SELECT config_name, field_name, value FROM config_values'):
        configs[r['config_name']][r['field_name']] = r['value']

    conn.close()

    os.makedirs('/app/results', exist_ok=True)

    for cname in sorted(configs):
        rodata = build_rodata_bytes(
            configs[cname], rodata_fields, rodata_total_size)
        reached_progs = set()
        reached_maps = set()
        wl = [entry]

        while wl:
            pname = wl.pop()
            if pname in reached_progs:
                continue
            reached_progs.add(pname)
            bc, relocs = parse_elf_program(programs[pname]['elf_file'])
            maps, tcs = analyze_program(bc, relocs, rodata, rodata_map_name)
            reached_maps.update(maps)
            for tc in tcs:
                if tc in progs_by_tc and progs_by_tc[tc] not in reached_progs:
                    wl.append(progs_by_tc[tc])

        result = {
            'reachable_maps': sorted(reached_maps),
            'eliminable_maps': sorted(all_map_names - reached_maps),
            'reachable_programs': sorted(reached_progs),
            'eliminable_programs': sorted(all_prog_names - reached_progs),
        }
        with open(f'/app/results/{cname}_result.json', 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Wrote /app/results/{cname}_result.json")


if __name__ == '__main__':
    main()
