#!/usr/bin/env python3
"""WebAssembly binary profiling transformer.

Transforms a WASM module to add per-function call counters, a synthesized
reporter function (__get_call_count), and a metadata global (__num_functions).
Operates directly on the binary format — no text-format round-tripping.
"""


import sys
import struct


# ======================== LEB128 Encoding/Decoding ========================

def decode_uleb128(data, offset):
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


# ======================== Section Management ========================

def parse_sections(data):
    """Parse WASM binary into list of [section_id, bytearray(content)]."""
    assert data[:4] == b'\x00asm', "Invalid WASM magic"
    assert struct.unpack('<I', data[4:8])[0] == 1, "Unexpected WASM version"
    offset = 8
    sections = []
    while offset < len(data):
        sid = data[offset]
        offset += 1
        size, offset = decode_uleb128(data, offset)
        content = data[offset:offset + size]
        sections.append([sid, bytearray(content)])
        offset += size
    return sections


def find_section_idx(sections, target_id):
    for i, (sid, _) in enumerate(sections):
        if sid == target_id:
            return i
    return -1


def get_section(sections, target_id):
    idx = find_section_idx(sections, target_id)
    if idx >= 0:
        return sections[idx][1]
    return None


def insert_section(sections, section_id, content):
    """Insert a new section at the correct position to maintain ID ordering."""
    pos = len(sections)
    for i, (sid, _) in enumerate(sections):
        if sid != 0 and sid > section_id:
            pos = i
            break
    sections.insert(pos, [section_id, bytearray(content)])


def assemble(sections):
    """Reassemble WASM binary from sections."""
    result = bytearray(b'\x00asm')
    result.extend(struct.pack('<I', 1))
    for sid, content in sections:
        result.append(sid)
        result.extend(encode_uleb128(len(content)))
        result.extend(content)
    return bytes(result)


# ======================== Import Section Analysis ========================

def skip_limits(data, offset):
    flags = data[offset]
    offset += 1
    _, offset = decode_uleb128(data, offset)  # min
    if flags & 0x01:  # has max
        _, offset = decode_uleb128(data, offset)
    return offset


def count_imports_by_kind(sections, target_kind):
    """Count imports of a given kind (0=func, 1=table, 2=memory, 3=global)."""
    content = get_section(sections, 2)
    if content is None:
        return 0
    offset = 0
    count, offset = decode_uleb128(content, offset)
    result = 0
    for _ in range(count):
        # Module name
        name_len, offset = decode_uleb128(content, offset)
        offset += name_len
        # Field name
        name_len, offset = decode_uleb128(content, offset)
        offset += name_len
        # Import descriptor
        kind = content[offset]
        offset += 1
        if kind == 0x00:  # func
            _, offset = decode_uleb128(content, offset)  # typeidx
        elif kind == 0x01:  # table
            offset += 1  # reftype
            offset = skip_limits(content, offset)
        elif kind == 0x02:  # memory
            offset = skip_limits(content, offset)
        elif kind == 0x03:  # global
            offset += 1  # valtype
            offset += 1  # mutability
        if kind == target_kind:
            result += 1
    return result


# ======================== Type Section Management ========================

def parse_type_entries(content):
    """Parse type section into list of (params_list, results_list)."""
    if content is None:
        return []
    offset = 0
    count, offset = decode_uleb128(content, offset)
    types = []
    for _ in range(count):
        assert content[offset] == 0x60  # functype
        offset += 1
        param_count, offset = decode_uleb128(content, offset)
        params = list(content[offset:offset + param_count])
        offset += param_count
        result_count, offset = decode_uleb128(content, offset)
        results = list(content[offset:offset + result_count])
        offset += result_count
        types.append((params, results))
    return types


def encode_type_section(types):
    content = bytearray()
    content.extend(encode_uleb128(len(types)))
    for params, results in types:
        content.append(0x60)
        content.extend(encode_uleb128(len(params)))
        content.extend(params)
        content.extend(encode_uleb128(len(results)))
        content.extend(results)
    return bytes(content)


def find_or_add_type(sections, params, results):
    """Find or add a function type. Returns the type index."""
    content = get_section(sections, 1)
    types = parse_type_entries(content)

    for i, (p, r) in enumerate(types):
        if p == params and r == results:
            return i

    types.append((params, results))
    new_content = encode_type_section(types)

    idx = find_section_idx(sections, 1)
    if idx >= 0:
        sections[idx][1] = bytearray(new_content)
    else:
        insert_section(sections, 1, new_content)

    return len(types) - 1


# ======================== Function Section Management ========================

def get_defined_function_count(sections):
    content = get_section(sections, 3)
    if content is None:
        return 0
    count, _ = decode_uleb128(content, 0)
    return count


def add_function_entry(sections, type_index):
    """Append a function entry to the function section."""
    content = get_section(sections, 3)
    if content is None:
        new_content = bytearray()
        new_content.extend(encode_uleb128(1))
        new_content.extend(encode_uleb128(type_index))
        insert_section(sections, 3, new_content)
    else:
        offset = 0
        count, offset = decode_uleb128(content, offset)
        rest = content[offset:]
        new_content = bytearray()
        new_content.extend(encode_uleb128(count + 1))
        new_content.extend(rest)
        new_content.extend(encode_uleb128(type_index))
        idx = find_section_idx(sections, 3)
        sections[idx][1] = bytearray(new_content)


# ======================== Global Section Management ========================

def get_defined_global_count(sections):
    content = get_section(sections, 6)
    if content is None:
        return 0
    count, _ = decode_uleb128(content, 0)
    return count


def add_globals(sections, num_counters, num_defined_functions):
    """Add N counter globals and 1 __num_functions global to global section."""
    # Counter global entry: mutable i32, init=0
    counter_entry = bytes([0x7F, 0x01, 0x41, 0x00, 0x0B])

    # __num_functions global: immutable i32, init=num_defined_functions
    meta_entry = bytearray([0x7F, 0x00, 0x41])
    meta_entry.extend(encode_sleb128(num_defined_functions))
    meta_entry.append(0x0B)
    meta_entry = bytes(meta_entry)

    content = get_section(sections, 6)
    if content is None:
        new_content = bytearray()
        new_content.extend(encode_uleb128(num_counters + 1))
        for _ in range(num_counters):
            new_content.extend(counter_entry)
        new_content.extend(meta_entry)
        insert_section(sections, 6, new_content)
    else:
        offset = 0
        count, offset = decode_uleb128(content, offset)
        rest = content[offset:]
        new_content = bytearray()
        new_content.extend(encode_uleb128(count + num_counters + 1))
        new_content.extend(rest)
        for _ in range(num_counters):
            new_content.extend(counter_entry)
        new_content.extend(meta_entry)
        idx = find_section_idx(sections, 6)
        sections[idx][1] = bytearray(new_content)


# ======================== Export Section Management ========================

def add_exports(sections, reporter_func_idx, num_functions_global_idx):
    """Add __get_call_count and __num_functions exports."""
    entries = bytearray()

    # __get_call_count function export
    name = b'__get_call_count'
    entries.extend(encode_uleb128(len(name)))
    entries.extend(name)
    entries.append(0x00)  # func kind
    entries.extend(encode_uleb128(reporter_func_idx))

    # __num_functions global export
    name = b'__num_functions'
    entries.extend(encode_uleb128(len(name)))
    entries.extend(name)
    entries.append(0x03)  # global kind
    entries.extend(encode_uleb128(num_functions_global_idx))

    content = get_section(sections, 7)
    if content is None:
        new_content = bytearray()
        new_content.extend(encode_uleb128(2))
        new_content.extend(entries)
        insert_section(sections, 7, new_content)
    else:
        offset = 0
        count, offset = decode_uleb128(content, offset)
        rest = content[offset:]
        new_content = bytearray()
        new_content.extend(encode_uleb128(count + 2))
        new_content.extend(rest)
        new_content.extend(entries)
        idx = find_section_idx(sections, 7)
        sections[idx][1] = bytearray(new_content)


# ======================== Code Section: Prologue & Reporter ========================

def build_prologue(global_idx):
    """Build counter-increment prologue: global.get idx / i32.const 1 / i32.add / global.set idx."""
    code = bytearray()
    code.append(0x23)  # global.get
    code.extend(encode_uleb128(global_idx))
    code.append(0x41)  # i32.const
    code.extend(encode_sleb128(1))
    code.append(0x6A)  # i32.add
    code.append(0x24)  # global.set
    code.extend(encode_uleb128(global_idx))
    return bytes(code)


def build_reporter_body(counter_base_global, num_funcs):
    """Build __get_call_count function body with br_table dispatch.

    For N functions with counter globals at G..G+N-1:
    - N=0: returns i32.const 0
    - N>=1: uses br_table to dispatch index to the correct global.get
    """
    body = bytearray()
    body.extend(encode_uleb128(0))  # 0 local declaration groups

    if num_funcs == 0:
        body.append(0x41)  # i32.const
        body.extend(encode_sleb128(0))
        body.append(0x0B)  # end
        return bytes(body)

    N = num_funcs
    G = counter_base_global

    # block $done (result i32)
    body.append(0x02)  # block
    body.append(0x7F)  # blocktype: i32

    # N blocks for dispatch targets: $L_0 .. $L_{N-1}
    for _ in range(N):
        body.append(0x02)  # block
        body.append(0x40)  # blocktype: void

    # block $default (void)
    body.append(0x02)  # block
    body.append(0x40)  # blocktype: void

    # local.get 0 (the function index parameter)
    body.append(0x20)
    body.extend(encode_uleb128(0))

    # br_table: dispatch to the correct handler
    # Inside $default, label depths:
    #   $default=0, $L_{N-1}=1, ..., $L_0=N, $done=N+1
    # For value k, target label = N-k (jumps to $L_k end → handler for func k)
    body.append(0x0E)  # br_table
    body.extend(encode_uleb128(N))  # vector length
    for k in range(N):
        body.extend(encode_uleb128(N - k))  # target for value k
    body.extend(encode_uleb128(0))  # default: $default (falls through)

    # end $default
    body.append(0x0B)

    # Default handler: return 0 for out-of-range indices
    # Inside: $L_{N-1}, ..., $L_0, $done → $done is at depth N
    body.append(0x41)  # i32.const
    body.extend(encode_sleb128(0))
    body.append(0x0C)  # br
    body.extend(encode_uleb128(N))  # to $done

    # Handlers for func N-1 down to func 1
    for k in range(N - 1, 0, -1):
        body.append(0x0B)  # end $L_k
        # Inside: $L_{k-1}, ..., $L_0, $done → $done is at depth k
        body.append(0x23)  # global.get
        body.extend(encode_uleb128(G + k))
        body.append(0x0C)  # br
        body.extend(encode_uleb128(k))  # to $done

    # end $L_0, handler for func 0 (falls through to $done)
    body.append(0x0B)
    body.append(0x23)  # global.get
    body.extend(encode_uleb128(G))
    # Falls through to $done end

    # end $done
    body.append(0x0B)

    # end function body (expr terminator — separate from block end)
    body.append(0x0B)

    return bytes(body)


def modify_code_section(sections, counter_base_global, num_defined_functions):
    """Inject prologues into existing function bodies and append reporter body."""
    reporter_body = build_reporter_body(counter_base_global, num_defined_functions)

    # Size-prefix the reporter body
    reporter_entry = bytearray()
    reporter_entry.extend(encode_uleb128(len(reporter_body)))
    reporter_entry.extend(reporter_body)

    content = get_section(sections, 10)
    if content is None:
        # No code section — create one with just the reporter
        new_content = bytearray()
        new_content.extend(encode_uleb128(1))
        new_content.extend(reporter_entry)
        insert_section(sections, 10, new_content)
        return

    # Parse existing code section and inject prologues
    offset = 0
    func_count, offset = decode_uleb128(content, offset)

    new_bodies = bytearray()
    for i in range(func_count):
        body_size, offset = decode_uleb128(content, offset)
        body_start = offset
        body_end = offset + body_size

        # Parse local declarations to find where instructions begin
        pos = body_start
        local_decl_count, pos = decode_uleb128(content, pos)
        for _ in range(local_decl_count):
            _, pos = decode_uleb128(content, pos)  # run-length count
            pos += 1  # valtype

        locals_bytes = content[body_start:pos]
        instructions = content[pos:body_end]

        # Build modified body: locals + prologue + original instructions
        prologue = build_prologue(counter_base_global + i)
        new_body = bytearray()
        new_body.extend(locals_bytes)
        new_body.extend(prologue)
        new_body.extend(instructions)

        new_bodies.extend(encode_uleb128(len(new_body)))
        new_bodies.extend(new_body)

        offset = body_end

    # Append reporter body
    new_bodies.extend(reporter_entry)

    # Rebuild code section with incremented count
    new_content = bytearray()
    new_content.extend(encode_uleb128(func_count + 1))
    new_content.extend(new_bodies)

    idx = find_section_idx(sections, 10)
    sections[idx][1] = bytearray(new_content)


# ======================== Main ========================

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.wasm> <output.wasm>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], 'rb') as f:
        data = f.read()

    sections = parse_sections(data)

    # Analyze index spaces
    num_imported_globals = count_imports_by_kind(sections, 3)
    num_imported_functions = count_imports_by_kind(sections, 0)
    num_defined_globals = get_defined_global_count(sections)
    num_defined_functions = get_defined_function_count(sections)

    # Compute target indices
    counter_base_global = num_imported_globals + num_defined_globals
    num_functions_global_idx = counter_base_global + num_defined_functions
    reporter_func_idx = num_imported_functions + num_defined_functions

    # 1. Find or add type (i32) -> (i32) for the reporter
    reporter_type_idx = find_or_add_type(sections, [0x7F], [0x7F])

    # 2. Add counter globals + __num_functions metadata global
    add_globals(sections, num_defined_functions, num_defined_functions)

    # 3. Add function section entry for the reporter
    add_function_entry(sections, reporter_type_idx)

    # 4. Inject prologues into existing function bodies + append reporter body
    modify_code_section(sections, counter_base_global, num_defined_functions)

    # 5. Add exports for __get_call_count and __num_functions
    add_exports(sections, reporter_func_idx, num_functions_global_idx)

    # 6. Reassemble and write output
    output = assemble(sections)

    with open(sys.argv[2], 'wb') as f:
        f.write(output)


if __name__ == '__main__':
    main()
