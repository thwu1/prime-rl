#!/usr/bin/env python3
"""WebAssembly binary module instrumentation: inject function call counter global.

Parses a WASM binary module, adds a mutable i32 global '__call_count' (init 0),
and prepends a counter-increment prologue to every defined function body.
"""


import sys
import struct


# ======================== LEB128 Codec ========================

def decode_uleb128(data, offset):
    """Decode unsigned LEB128 at offset, return (value, new_offset)."""
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, offset


def encode_uleb128(value):
    """Encode an unsigned integer as LEB128 bytes."""
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            break
    return bytes(result)


def encode_sleb128(value):
    """Encode a signed integer as LEB128 bytes."""
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if (value == 0 and (byte & 0x40) == 0) or \
           (value == -1 and (byte & 0x40) != 0):
            result.append(byte)
            break
        else:
            result.append(byte | 0x80)
    return bytes(result)


# ======================== WASM Module Parsing ========================

def parse_module(data):
    """Parse a WASM binary into a list of (section_id, content_bytes)."""
    if len(data) < 8:
        raise ValueError("File too short for WASM header")
    if data[:4] != b'\x00asm':
        raise ValueError("Invalid WASM magic number")
    version = struct.unpack('<I', data[4:8])[0]
    if version != 1:
        raise ValueError(f"Unsupported WASM version: {version}")

    offset = 8
    sections = []
    while offset < len(data):
        section_id = data[offset]
        offset += 1
        section_size, offset = decode_uleb128(data, offset)
        section_content = data[offset:offset + section_size]
        sections.append((section_id, bytes(section_content)))
        offset += section_size
    return sections


def count_imported_globals(import_content):
    """Count global imports in an import section."""
    offset = 0
    count, offset = decode_uleb128(import_content, offset)
    num_globals = 0
    for _ in range(count):
        # Skip module name
        name_len, offset = decode_uleb128(import_content, offset)
        offset += name_len
        # Skip field name
        name_len, offset = decode_uleb128(import_content, offset)
        offset += name_len
        # Import descriptor
        kind = import_content[offset]
        offset += 1
        if kind == 0x00:  # func: typeidx
            _, offset = decode_uleb128(import_content, offset)
        elif kind == 0x01:  # table: reftype + limits
            offset += 1  # reftype byte
            flag = import_content[offset]
            offset += 1
            _, offset = decode_uleb128(import_content, offset)  # min
            if flag & 0x01:
                _, offset = decode_uleb128(import_content, offset)  # max
        elif kind == 0x02:  # memory: limits
            flag = import_content[offset]
            offset += 1
            _, offset = decode_uleb128(import_content, offset)  # min
            if flag & 0x01:
                _, offset = decode_uleb128(import_content, offset)  # max
        elif kind == 0x03:  # global: valtype + mut
            offset += 1  # valtype
            offset += 1  # mutability
            num_globals += 1
        elif kind == 0x04:  # tag (exception handling): attribute + typeidx
            offset += 1  # attribute byte
            _, offset = decode_uleb128(import_content, offset)
        else:
            raise ValueError(f"Unknown import descriptor kind: 0x{kind:02X}")
    return num_globals


def count_defined_globals(global_content):
    """Count defined globals in a global section."""
    count, _ = decode_uleb128(global_content, 0)
    return count


# ======================== Binary Builders ========================

def make_global_entry():
    """Build a global entry: mutable i32, initialized to 0."""
    entry = bytearray()
    entry.append(0x7F)  # valtype: i32
    entry.append(0x01)  # mutability: mutable
    # init_expr: i32.const 0, end
    entry.append(0x41)  # i32.const
    entry.extend(encode_sleb128(0))
    entry.append(0x0B)  # end
    return bytes(entry)


def make_export_entry(name, kind, index):
    """Build an export entry: name + kind + index."""
    entry = bytearray()
    name_bytes = name.encode('utf-8')
    entry.extend(encode_uleb128(len(name_bytes)))
    entry.extend(name_bytes)
    entry.append(kind)
    entry.extend(encode_uleb128(index))
    return bytes(entry)


def make_counter_prologue(global_idx):
    """Build instruction bytes: global.get idx; i32.const 1; i32.add; global.set idx."""
    code = bytearray()
    code.append(0x23)  # global.get
    code.extend(encode_uleb128(global_idx))
    code.append(0x41)  # i32.const
    code.extend(encode_sleb128(1))
    code.append(0x6A)  # i32.add
    code.append(0x24)  # global.set
    code.extend(encode_uleb128(global_idx))
    return bytes(code)


# ======================== Section Transformers ========================

def modify_global_section(content, new_entry):
    """Append a global entry to an existing global section."""
    count, offset = decode_uleb128(content, 0)
    existing_entries = content[offset:]
    result = bytearray()
    result.extend(encode_uleb128(count + 1))
    result.extend(existing_entries)
    result.extend(new_entry)
    return bytes(result)


def create_global_section(new_entry):
    """Create a global section containing exactly one global."""
    result = bytearray()
    result.extend(encode_uleb128(1))
    result.extend(new_entry)
    return bytes(result)


def modify_export_section(content, new_entry):
    """Append an export entry to an existing export section."""
    count, offset = decode_uleb128(content, 0)
    existing_entries = content[offset:]
    result = bytearray()
    result.extend(encode_uleb128(count + 1))
    result.extend(existing_entries)
    result.extend(new_entry)
    return bytes(result)


def create_export_section(new_entry):
    """Create an export section containing exactly one export."""
    result = bytearray()
    result.extend(encode_uleb128(1))
    result.extend(new_entry)
    return bytes(result)


def modify_code_section(content, prologue):
    """Inject a prologue into every function body in the code section."""
    offset = 0
    func_count, offset = decode_uleb128(content, offset)

    new_bodies = bytearray()
    for _ in range(func_count):
        # Read original body size and boundaries
        body_size, offset = decode_uleb128(content, offset)
        body_start = offset
        body_end = offset + body_size

        # Parse past local declarations (count + entries)
        local_decl_count, pos = decode_uleb128(content, body_start)
        for _ in range(local_decl_count):
            _, pos = decode_uleb128(content, pos)  # run-length count
            pos += 1  # valtype byte

        locals_bytes = content[body_start:pos]
        instructions = content[pos:body_end]

        # Reconstruct body: locals + prologue + original instructions
        new_body = bytearray()
        new_body.extend(locals_bytes)
        new_body.extend(prologue)
        new_body.extend(instructions)

        # Write with updated size
        new_bodies.extend(encode_uleb128(len(new_body)))
        new_bodies.extend(new_body)

        offset = body_end

    result = bytearray()
    result.extend(encode_uleb128(func_count))
    result.extend(new_bodies)
    return bytes(result)


# ======================== Output Assembly ========================

def encode_section(section_id, content):
    """Encode a complete section: id + LEB128(size) + content."""
    result = bytearray()
    result.append(section_id)
    result.extend(encode_uleb128(len(content)))
    result.extend(content)
    return bytes(result)


def find_insert_position(sections, target_id):
    """Find the correct position to insert a section, maintaining known-section order.

    Known sections (id 1-12) must appear in increasing order.
    Custom sections (id 0) can appear anywhere and are skipped in ordering logic.
    """
    for i, (sid, _) in enumerate(sections):
        if sid != 0 and sid > target_id:
            return i
    return len(sections)


# ======================== Main ========================

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.wasm> <output.wasm>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    with open(input_path, 'rb') as f:
        data = f.read()

    sections = parse_module(data)

    # --- Determine global index space ---
    num_imported_globals = 0
    for sid, content in sections:
        if sid == 2:  # import section
            num_imported_globals = count_imported_globals(content)
            break

    num_defined_globals = 0
    for sid, content in sections:
        if sid == 6:  # global section
            num_defined_globals = count_defined_globals(content)
            break

    new_global_idx = num_imported_globals + num_defined_globals

    # --- Build injection components ---
    global_entry = make_global_entry()
    export_entry = make_export_entry("__call_count", 0x03, new_global_idx)
    prologue = make_counter_prologue(new_global_idx)

    # --- Transform sections ---
    has_global = False
    has_export = False
    new_sections = []

    for sid, content in sections:
        if sid == 6:  # global section
            new_sections.append((6, modify_global_section(content, global_entry)))
            has_global = True
        elif sid == 7:  # export section
            new_sections.append((7, modify_export_section(content, export_entry)))
            has_export = True
        elif sid == 10:  # code section
            new_sections.append((10, modify_code_section(content, prologue)))
        else:
            new_sections.append((sid, content))

    # --- Insert missing sections at correct positions ---
    if not has_global:
        pos = find_insert_position(new_sections, 6)
        new_sections.insert(pos, (6, create_global_section(global_entry)))

    if not has_export:
        pos = find_insert_position(new_sections, 7)
        new_sections.insert(pos, (7, create_export_section(export_entry)))

    # --- Write output ---
    with open(output_path, 'wb') as f:
        f.write(b'\x00asm')
        f.write(struct.pack('<I', 1))
        for sid, content in new_sections:
            f.write(encode_section(sid, content))


if __name__ == '__main__':
    main()
