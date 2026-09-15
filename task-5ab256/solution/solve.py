#!/usr/bin/env python3
"""
Solution for the microcode ROM reverse engineering task.

Reads the raw binary ROM and SQLite database, cracks the bit-column permutation,
decodes the full ROM, generates a Graphviz control flow graph, and answers all
questions.

"""

import json
import os
import sqlite3
import subprocess
import struct


# -- Read binary ROM --

def read_binary_rom(path):
    """Read raw binary ROM: 128 x 3 bytes big-endian 24-bit words."""
    rom = {}
    with open(path, 'rb') as f:
        data = f.read()
    for addr in range(128):
        offset = addr * 3
        b = data[offset:offset+3]
        rom[addr] = (b[0] << 16) | (b[1] << 8) | b[2]
    return rom


# -- Query SQLite database --

def query_db(db_path):
    """Extract all needed data from the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get known patent words for permutation cracking
    c.execute("SELECT addr, logical_hex FROM patent_words WHERE section = 'known'")
    known_words = {}
    for row in c.fetchall():
        known_words[row['addr']] = int(row['logical_hex'], 16)

    # Get REP STOSW patent words for bug detection
    c.execute("SELECT addr, logical_hex FROM patent_words WHERE section = 'patent_rep_stosw'")
    patent_words = {}
    for row in c.fetchall():
        patent_words[row['addr']] = int(row['logical_hex'], 16)

    # Get ALU operation names
    c.execute("SELECT id, name FROM alu_ops ORDER BY id")
    alu_names = {row['id']: row['name'] for row in c.fetchall()}

    # Get control flow names
    c.execute("SELECT id, name FROM ctrl_ops ORDER BY id")
    ctrl_names = {row['id']: row['name'] for row in c.fetchall()}

    # Get register names
    c.execute("SELECT id, name FROM registers ORDER BY id")
    reg_names = {row['id']: row['name'] for row in c.fetchall()}

    # Get translation table
    c.execute("SELECT opcode, start_addr, mnemonic FROM translations ORDER BY opcode")
    translations = [(row['opcode'], row['start_addr'], row['mnemonic']) for row in c.fetchall()]

    # Get field layout
    c.execute("SELECT field_name, bit_lo, bit_hi, width FROM field_layout")
    field_layout = {row['field_name']: (row['bit_lo'], row['bit_hi'], row['width'])
                    for row in c.fetchall()}

    conn.close()
    return known_words, patent_words, alu_names, ctrl_names, reg_names, translations, field_layout


# -- Crack permutation --

def crack_permutation(scrambled_rom, known_words):
    """Determine P where physical_bit[i] = logical_bit[P[i]]."""
    pairs = []
    for addr, logical in known_words.items():
        if addr in scrambled_rom:
            pairs.append((logical, scrambled_rom[addr]))

    if not pairs:
        raise ValueError("No known word pairs found!")

    logical_fps = {}
    scrambled_fps = {}
    for bit in range(24):
        logical_fps[bit] = tuple((lw >> bit) & 1 for lw, sw in pairs)
        scrambled_fps[bit] = tuple((sw >> bit) & 1 for lw, sw in pairs)

    perm = [None] * 24
    for s_bit in range(24):
        s_fp = scrambled_fps[s_bit]
        matches = [l_bit for l_bit in range(24) if logical_fps[l_bit] == s_fp]
        if len(matches) == 1:
            perm[s_bit] = matches[0]
        elif len(matches) == 0:
            raise ValueError(f"No logical match for scrambled bit {s_bit}")
        else:
            raise ValueError(f"Ambiguous match for scrambled bit {s_bit}: {matches}")

    if sorted(perm) != list(range(24)):
        raise ValueError(f"Invalid permutation: {perm}")
    return perm


def unscramble_word(scrambled, perm):
    """Apply permutation to unscramble a word."""
    result = 0
    for i in range(24):
        if scrambled & (1 << i):
            result |= (1 << perm[i])
    return result


def decode_fields(word):
    """Extract fields from a logical 24-bit word."""
    src = word & 0xF
    dst = (word >> 4) & 0xF
    alu = (word >> 8) & 0xF
    ctrl = (word >> 12) & 0x7
    imm = (word >> 15) & 0x1FF
    return src, dst, alu, ctrl, imm


# -- Find bug --

def find_bug(decoded_rom, patent_words):
    """Compare patent REP STOSW against actual ROM."""
    for addr, patent_word in patent_words.items():
        if addr in decoded_rom and patent_word != decoded_rom[addr]:
            p_src, p_dst, p_alu, p_ctrl, p_imm = decode_fields(patent_word)
            a_src, a_dst, a_alu, a_ctrl, a_imm = decode_fields(decoded_rom[addr])
            if p_src != a_src: return addr, "src", a_src, p_src
            if p_dst != a_dst: return addr, "dst", a_dst, p_dst
            if p_alu != a_alu: return addr, "alu", a_alu, p_alu
            if p_ctrl != a_ctrl: return addr, "ctrl", a_ctrl, p_ctrl
            if p_imm != a_imm: return addr, "imm", a_imm, p_imm
    return None, None, None, None


# -- Generate control flow graph --

def generate_cfg(decoded_rom, translations, alu_names, ctrl_names, reg_names, dot_path, svg_path):
    """Generate DOT control flow graph and render to SVG."""
    # Build instruction ownership map: addr -> (opcode, mnemonic)
    # Sort translations by start_addr descending to assign each addr to its instruction
    trans_sorted = sorted(translations, key=lambda t: t[1], reverse=True)

    # Determine instruction boundaries
    # Each instruction starts at start_addr and runs until the next instruction starts
    # or until an END/JMP
    instr_ranges = {}  # start_addr -> (opcode, mnemonic, set of owned addrs)
    starts = sorted(set(t[1] for t in translations))
    for i, start in enumerate(starts):
        end = starts[i+1] if i+1 < len(starts) else 128
        opcode = None
        mnemonic = None
        for opc, sa, mn in translations:
            if sa == start:
                opcode = opc
                mnemonic = mn
                break
        instr_ranges[start] = (opcode, mnemonic, set(range(start, end)))

    lines = []
    lines.append("digraph microcode_cfg {")
    lines.append('    rankdir=TB;')
    lines.append('    node [shape=box, fontname="Courier", fontsize=8];')
    lines.append('    edge [fontsize=7];')
    lines.append('')

    # Generate subgraph clusters by instruction
    for start in sorted(instr_ranges.keys()):
        opcode, mnemonic, addrs = instr_ranges[start]
        cluster_name = f"cluster_{start}"
        label = f"0x{opcode:02X}: {mnemonic}" if opcode is not None else f"addr_{start}"
        lines.append(f'    subgraph {cluster_name} {{')
        lines.append(f'        label="{label}";')
        lines.append(f'        style=dashed;')
        for addr in sorted(addrs):
            if addr in decoded_rom:
                word = decoded_rom[addr]
                src, dst, alu, ctrl, imm = decode_fields(word)
                s_name = reg_names.get(src, str(src))
                d_name = reg_names.get(dst, str(dst))
                a_name = alu_names.get(alu, str(alu))
                c_name = ctrl_names.get(ctrl, str(ctrl))
                node_label = f"{addr:03d}: {a_name} {s_name}=>{d_name} [{c_name}"
                if ctrl in (2, 3, 4):  # JZ, JNZ, JMP
                    node_label += f" {imm}"
                node_label += "]"
                lines.append(f'        n{addr} [label="{node_label}"];')
        lines.append('    }')
        lines.append('')

    # Generate edges
    for addr in range(128):
        if addr not in decoded_rom:
            continue
        word = decoded_rom[addr]
        _, _, _, ctrl, imm = decode_fields(word)
        if ctrl == 0:  # NEXT
            lines.append(f'    n{addr} -> n{addr+1};')
        elif ctrl == 1:  # END
            pass
        elif ctrl == 2:  # JZ
            lines.append(f'    n{addr} -> n{imm} [label="JZ"];')
            lines.append(f'    n{addr} -> n{addr+1} [style=dashed];')
        elif ctrl == 3:  # JNZ
            lines.append(f'    n{addr} -> n{imm} [label="JNZ"];')
            lines.append(f'    n{addr} -> n{addr+1} [style=dashed];')
        elif ctrl == 4:  # JMP
            lines.append(f'    n{addr} -> n{imm} [label="JMP"];')
        # ctrl 5,6,7 (HALT etc): no outgoing edges

    lines.append('}')

    dot_content = '\n'.join(lines)
    with open(dot_path, 'w') as f:
        f.write(dot_content)

    # Render SVG using dot
    subprocess.run(['dot', '-Tsvg', dot_path, '-o', svg_path], check=True)
    print(f"DOT written to {dot_path}")
    print(f"SVG rendered to {svg_path}")


# -- Main --

def main():
    # Step 1: Read binary ROM
    scrambled_rom = read_binary_rom("/app/rom.bin")
    print(f"Read {len(scrambled_rom)} scrambled ROM entries from binary")

    # Step 2: Query SQLite database
    known_words, patent_words, alu_names, ctrl_names, reg_names, translations, field_layout = \
        query_db("/app/microcode.db")
    print(f"Loaded {len(known_words)} known words, {len(patent_words)} patent words from DB")

    # Step 3: Crack the permutation
    perm = crack_permutation(scrambled_rom, known_words)
    print(f"Cracked permutation: {perm}")

    # Step 4: Decode the full ROM
    decoded_rom = {}
    for addr in range(128):
        decoded_rom[addr] = unscramble_word(scrambled_rom[addr], perm)

    # Verify against known words
    for addr, logical in known_words.items():
        assert decoded_rom[addr] == logical, (
            f"Verification failed at addr {addr}: "
            f"decoded 0x{decoded_rom[addr]:06X} != known 0x{logical:06X}"
        )
    print("Verification against known words: PASSED")

    # Step 5: Build answers
    answers = {"permutation": perm}

    # Decoded words
    answers["decoded_words"] = {}
    for addr in [10, 25, 49, 75, 100]:
        answers["decoded_words"][str(addr)] = f"0x{decoded_rom[addr]:06X}"

    # END count
    end_count = sum(1 for addr in range(128)
                    if ((decoded_rom[addr] >> 12) & 0x7) == 1)
    answers["end_count"] = end_count

    # ALU histogram
    alu_hist = {name: 0 for name in alu_names.values()}
    for addr in range(128):
        alu_op = (decoded_rom[addr] >> 8) & 0xF
        alu_hist[alu_names[alu_op]] += 1
    answers["alu_histogram"] = alu_hist

    # Bug detection
    bug_addr, bug_field, actual_val, correct_val = find_bug(decoded_rom, patent_words)
    if bug_addr is not None:
        answers["bug"] = {
            "address": bug_addr, "field": bug_field,
            "actual_value": actual_val, "correct_value": correct_val,
        }
        print(f"Bug found at addr {bug_addr}: {bug_field} = {actual_val} (should be {correct_val})")
    else:
        answers["bug"] = {"address": None, "field": None, "actual_value": None, "correct_value": None}

    # Unique register pairs
    pairs = set()
    for addr in range(128):
        src = decoded_rom[addr] & 0xF
        dst = (decoded_rom[addr] >> 4) & 0xF
        pairs.add((src, dst))
    answers["unique_register_pairs"] = len(pairs)

    # CFG edge count
    edge_count = 0
    for addr in range(128):
        ctrl = (decoded_rom[addr] >> 12) & 0x7
        if ctrl == 0:   # NEXT
            edge_count += 1
        elif ctrl in (2, 3):  # JZ, JNZ
            edge_count += 2
        elif ctrl == 4:  # JMP
            edge_count += 1
    answers["cfg_edge_count"] = edge_count

    # Write answers
    with open("/app/answers.json", 'w') as f:
        json.dump(answers, f, indent=2)
    print(f"Answers written to /app/answers.json")

    # Step 6: Generate control flow graph
    generate_cfg(decoded_rom, translations, alu_names, ctrl_names, reg_names,
                 "/app/microcode_cfg.dot", "/app/microcode_cfg.svg")


if __name__ == "__main__":
    main()
