#!/usr/bin/env python3
"""
SPIR-V Binary Surgeon - Direct binary manipulation tool for SPIR-V modules.
Parses, analyzes, and transforms SPIR-V at the 32-bit word level.
"""

import sys
import json
import struct
import os

SPIRV_MAGIC = 0x07230203

# --- Opcode constants ---
OP_SOURCE = 3
OP_SOURCE_CONTINUED = 2
OP_SOURCE_EXTENSION = 4
OP_NAME = 5
OP_MEMBER_NAME = 6
OP_STRING = 7
OP_LINE = 8
OP_NO_LINE = 317
OP_MODULE_PROCESSED = 330
OP_CAPABILITY = 17
OP_EXTENSION = 10
OP_EXT_INST_IMPORT = 11
OP_MEMORY_MODEL = 14
OP_ENTRY_POINT = 15
OP_EXECUTION_MODE = 16
OP_TYPE_VOID = 19
OP_TYPE_BOOL = 20
OP_TYPE_INT = 21
OP_TYPE_FLOAT = 22
OP_TYPE_VECTOR = 23
OP_TYPE_MATRIX = 24
OP_TYPE_IMAGE = 25
OP_TYPE_SAMPLER = 26
OP_TYPE_SAMPLED_IMAGE = 27
OP_TYPE_ARRAY = 28
OP_TYPE_RUNTIME_ARRAY = 29
OP_TYPE_STRUCT = 30
OP_TYPE_OPAQUE = 31
OP_TYPE_POINTER = 32
OP_TYPE_FUNCTION = 33
OP_CONSTANT = 43
OP_SPEC_CONSTANT = 50
OP_VARIABLE = 59
OP_DECORATE = 71
OP_MEMBER_DECORATE = 72

# --- Decoration enum values ---
DEC_BLOCK = 2
DEC_BUFFER_BLOCK = 3
DEC_ROW_MAJOR = 4
DEC_COL_MAJOR = 5
DEC_ARRAY_STRIDE = 6
DEC_MATRIX_STRIDE = 7
DEC_BUILTIN = 11
DEC_NON_WRITABLE = 24
DEC_NON_READABLE = 25
DEC_LOCATION = 30
DEC_BINDING = 33
DEC_DESCRIPTOR_SET = 34
DEC_OFFSET = 35

DEBUG_OPCODES = frozenset([
    OP_NAME, OP_MEMBER_NAME, OP_STRING, OP_SOURCE,
    OP_SOURCE_CONTINUED, OP_SOURCE_EXTENSION,
    OP_LINE, OP_NO_LINE, OP_MODULE_PROCESSED,
])

EXEC_MODEL_NAMES = {
    0: "Vertex", 1: "TessellationControl", 2: "TessellationEvaluation",
    3: "Geometry", 4: "Fragment", 5: "GLCompute", 6: "Kernel",
}

CAPABILITY_NAMES = {
    0: "Matrix", 1: "Shader", 2: "Geometry", 3: "Tessellation",
    5: "Linkage", 6: "Kernel", 22: "InputAttachment",
    29: "SampledBuffer", 31: "Sampled1D", 32: "Image1D",
    34: "SampledCubeArray", 40: "ImageBuffer", 41: "ImageMSArray",
    42: "StorageImageExtendedFormats", 43: "ImageQuery",
    44: "DerivativeControl", 45: "InterpolationFunction",
    46: "TransformFeedback", 48: "StorageInputOutput16",
    4427: "ShaderNonUniform", 4437: "RuntimeDescriptorArray",
}

STORAGE_CLASS_NAMES = {
    0: "UniformConstant", 1: "Input", 2: "Uniform", 3: "Output",
    4: "Workgroup", 5: "CrossWorkgroup", 6: "Private", 7: "Function",
    8: "Generic", 9: "PushConstant", 10: "AtomicCounter", 11: "Image",
    12: "StorageBuffer",
}

ADDRESSING_MODEL_NAMES = {
    0: "Logical", 1: "Physical32", 2: "Physical64",
    3: "PhysicalStorageBuffer64",
}

MEMORY_MODEL_NAMES = {
    0: "Simple", 1: "GLSL450", 2: "OpenCL", 3: "Vulkan",
}

DECORATION_NAMES = {
    DEC_BLOCK: "Block", DEC_BUFFER_BLOCK: "BufferBlock",
    DEC_ROW_MAJOR: "RowMajor", DEC_COL_MAJOR: "ColMajor",
    DEC_ARRAY_STRIDE: "ArrayStride", DEC_MATRIX_STRIDE: "MatrixStride",
    DEC_BUILTIN: "BuiltIn", DEC_NON_WRITABLE: "NonWritable",
    DEC_NON_READABLE: "NonReadable", DEC_LOCATION: "Location",
    DEC_BINDING: "Binding", DEC_DESCRIPTOR_SET: "DescriptorSet",
    DEC_OFFSET: "Offset",
}

EXEC_MODE_LOCAL_SIZE = 17
EXEC_MODE_ORIGIN_UPPER_LEFT = 7
EXEC_MODE_ORIGIN_LOWER_LEFT = 8
EXEC_MODE_DEPTH_REPLACING = 12


# --- Binary helpers ---

def decode_string(words, start_idx):
    """Decode a null-terminated UTF-8 string from SPIR-V word array."""
    raw = b''
    for i in range(start_idx, len(words)):
        raw += struct.pack('<I', words[i])
    null_pos = raw.find(b'\x00')
    if null_pos >= 0:
        raw = raw[:null_pos]
    return raw.decode('utf-8', errors='replace')


def string_word_count(s):
    """Number of 32-bit words needed to encode a string with null terminator."""
    encoded = s.encode('utf-8') + b'\x00'
    return (len(encoded) + 3) // 4


def parse_module(data):
    """Parse SPIR-V binary bytes into (header_dict, instruction_list)."""
    if len(data) < 20:
        raise ValueError("Data too short for SPIR-V header")

    magic = struct.unpack_from('<I', data, 0)[0]
    if magic == SPIRV_MAGIC:
        endian = '<'
    elif struct.unpack_from('>I', data, 0)[0] == SPIRV_MAGIC:
        endian = '>'
    else:
        raise ValueError(f"Invalid SPIR-V magic: 0x{magic:08x}")

    word_count = len(data) // 4
    words = list(struct.unpack(f'{endian}{word_count}I', data[:word_count * 4]))

    header = {
        'magic': words[0],
        'version': words[1],
        'generator': words[2],
        'bound': words[3],
        'reserved': words[4],
    }

    instructions = []
    pos = 5
    while pos < len(words):
        first = words[pos]
        wc = first >> 16
        op = first & 0xFFFF
        if wc == 0:
            raise ValueError(f"Zero word count at position {pos}")
        if pos + wc > len(words):
            raise ValueError(f"Instruction at {pos} overflows (wc={wc})")
        instructions.append((op, list(words[pos:pos + wc])))
        pos += wc

    return header, instructions


def serialize_module(header, instructions):
    """Serialize (header, instructions) back to SPIR-V binary bytes."""
    out = [
        header['magic'], header['version'], header['generator'],
        header['bound'], header['reserved'],
    ]
    for op, ws in instructions:
        first_word = (len(ws) << 16) | (op & 0xFFFF)
        out.append(first_word)
        out.extend(ws[1:])
    return struct.pack(f'<{len(out)}I', *out)


# --- Subcommands ---

def cmd_analyze(spv_path):
    with open(spv_path, 'rb') as f:
        data = f.read()

    header, instructions = parse_module(data)

    result = {
        "header": {
            "magic": f"0x{header['magic']:08x}",
            "version": f"{(header['version'] >> 16) & 0xFF}.{(header['version'] >> 8) & 0xFF}",
            "generator": header['generator'],
            "bound": header['bound'],
        },
        "capabilities": [],
        "extensions": [],
        "ext_inst_imports": [],
        "memory_model": {},
        "entry_points": [],
        "execution_modes": [],
        "names": {},
        "member_names": {},
        "decorations": {},
        "member_decorations": {},
        "types": {},
        "variables": [],
    }

    for op, ws in instructions:
        if op == OP_CAPABILITY:
            cap = ws[1]
            result["capabilities"].append(
                CAPABILITY_NAMES.get(cap, f"Cap{cap}"))

        elif op == OP_EXTENSION:
            result["extensions"].append(decode_string(ws, 1))

        elif op == OP_EXT_INST_IMPORT:
            result["ext_inst_imports"].append({
                "id": ws[1], "name": decode_string(ws, 2),
            })

        elif op == OP_MEMORY_MODEL:
            result["memory_model"] = {
                "addressing": ADDRESSING_MODEL_NAMES.get(
                    ws[1], f"Unknown({ws[1]})"),
                "model": MEMORY_MODEL_NAMES.get(
                    ws[2], f"Unknown({ws[2]})"),
            }

        elif op == OP_ENTRY_POINT:
            name = decode_string(ws, 3)
            nwc = string_word_count(name)
            iface = list(ws[3 + nwc:])
            result["entry_points"].append({
                "execution_model": EXEC_MODEL_NAMES.get(
                    ws[1], f"Unknown({ws[1]})"),
                "id": ws[2],
                "name": name,
                "interface_ids": iface,
            })

        elif op == OP_EXECUTION_MODE:
            mode_info = {"entry_point_id": ws[1], "mode": ws[2]}
            extras = list(ws[3:])
            if ws[2] == EXEC_MODE_LOCAL_SIZE and len(extras) >= 3:
                mode_info["local_size"] = extras[:3]
            elif ws[2] == EXEC_MODE_ORIGIN_UPPER_LEFT:
                mode_info["name"] = "OriginUpperLeft"
            elif ws[2] == EXEC_MODE_ORIGIN_LOWER_LEFT:
                mode_info["name"] = "OriginLowerLeft"
            elif ws[2] == EXEC_MODE_DEPTH_REPLACING:
                mode_info["name"] = "DepthReplacing"
            result["execution_modes"].append(mode_info)

        elif op == OP_NAME:
            result["names"][str(ws[1])] = decode_string(ws, 2)

        elif op == OP_MEMBER_NAME:
            key = str(ws[1])
            if key not in result["member_names"]:
                result["member_names"][key] = {}
            result["member_names"][key][str(ws[2])] = decode_string(ws, 3)

        elif op == OP_DECORATE:
            key = str(ws[1])
            if key not in result["decorations"]:
                result["decorations"][key] = []
            dec = {"decoration": ws[2]}
            dn = DECORATION_NAMES.get(ws[2])
            if dn:
                dec["name"] = dn
            extras = list(ws[3:])
            if ws[2] in (DEC_DESCRIPTOR_SET, DEC_BINDING, DEC_LOCATION,
                         DEC_BUILTIN, DEC_OFFSET, DEC_ARRAY_STRIDE,
                         DEC_MATRIX_STRIDE) and extras:
                dec["value"] = extras[0]
            elif extras:
                dec["operands"] = extras
            result["decorations"][key].append(dec)

        elif op == OP_MEMBER_DECORATE:
            key = str(ws[1])
            mkey = str(ws[2])
            if key not in result["member_decorations"]:
                result["member_decorations"][key] = {}
            if mkey not in result["member_decorations"][key]:
                result["member_decorations"][key][mkey] = []
            dec = {"decoration": ws[3]}
            dn = DECORATION_NAMES.get(ws[3])
            if dn:
                dec["name"] = dn
            extras = list(ws[4:])
            if extras:
                dec["value"] = extras[0]
            result["member_decorations"][key][mkey].append(dec)

        elif op == OP_TYPE_VOID:
            result["types"][str(ws[1])] = {"kind": "void"}
        elif op == OP_TYPE_BOOL:
            result["types"][str(ws[1])] = {"kind": "bool"}
        elif op == OP_TYPE_INT:
            result["types"][str(ws[1])] = {
                "kind": "int", "width": ws[2], "signedness": ws[3],
            }
        elif op == OP_TYPE_FLOAT:
            result["types"][str(ws[1])] = {"kind": "float", "width": ws[2]}
        elif op == OP_TYPE_VECTOR:
            result["types"][str(ws[1])] = {
                "kind": "vector", "component_type": ws[2], "count": ws[3],
            }
        elif op == OP_TYPE_MATRIX:
            result["types"][str(ws[1])] = {
                "kind": "matrix", "column_type": ws[2],
                "column_count": ws[3],
            }
        elif op == OP_TYPE_IMAGE:
            t = {"kind": "image", "sampled_type": ws[2], "dim": ws[3]}
            if len(ws) > 4: t["depth"] = ws[4]
            if len(ws) > 5: t["arrayed"] = ws[5]
            if len(ws) > 6: t["ms"] = ws[6]
            if len(ws) > 7: t["sampled"] = ws[7]
            if len(ws) > 8: t["format"] = ws[8]
            result["types"][str(ws[1])] = t
        elif op == OP_TYPE_SAMPLER:
            result["types"][str(ws[1])] = {"kind": "sampler"}
        elif op == OP_TYPE_SAMPLED_IMAGE:
            result["types"][str(ws[1])] = {
                "kind": "sampled_image", "image_type": ws[2],
            }
        elif op == OP_TYPE_ARRAY:
            result["types"][str(ws[1])] = {
                "kind": "array", "element_type": ws[2], "length_id": ws[3],
            }
        elif op == OP_TYPE_RUNTIME_ARRAY:
            result["types"][str(ws[1])] = {
                "kind": "runtime_array", "element_type": ws[2],
            }
        elif op == OP_TYPE_STRUCT:
            result["types"][str(ws[1])] = {
                "kind": "struct", "member_types": list(ws[2:]),
            }
        elif op == OP_TYPE_OPAQUE:
            result["types"][str(ws[1])] = {
                "kind": "opaque", "name": decode_string(ws, 2),
            }
        elif op == OP_TYPE_POINTER:
            sc = ws[2]
            result["types"][str(ws[1])] = {
                "kind": "pointer",
                "storage_class": STORAGE_CLASS_NAMES.get(
                    sc, f"Unknown({sc})"),
                "pointee_type": ws[3],
            }
        elif op == OP_TYPE_FUNCTION:
            result["types"][str(ws[1])] = {
                "kind": "function", "return_type": ws[2],
                "parameter_types": list(ws[3:]),
            }

        elif op == OP_VARIABLE:
            sc = ws[3]
            v = {
                "result_type": ws[1],
                "id": ws[2],
                "storage_class": STORAGE_CLASS_NAMES.get(
                    sc, f"Unknown({sc})"),
            }
            if len(ws) > 4:
                v["initializer"] = ws[4]
            result["variables"].append(v)

    print(json.dumps(result, indent=2))


def cmd_remap(input_path, output_path, mapping_path):
    with open(input_path, 'rb') as f:
        data = f.read()
    with open(mapping_path, 'r') as f:
        mapping = json.load(f)

    header, instructions = parse_module(data)

    for i, (op, ws) in enumerate(instructions):
        if op == OP_DECORATE and len(ws) >= 4 and ws[2] == DEC_DESCRIPTOR_SET:
            old_set = ws[3]
            old_key = str(old_set)
            if old_key in mapping:
                new_ws = list(ws)
                new_ws[3] = int(mapping[old_key])
                instructions[i] = (op, new_ws)

    output = serialize_module(header, instructions)
    with open(output_path, 'wb') as f:
        f.write(output)


def cmd_strip_debug(input_path, output_path):
    with open(input_path, 'rb') as f:
        data = f.read()

    header, instructions = parse_module(data)

    # Remove all debug instructions
    instructions = [
        (op, ws) for op, ws in instructions if op not in DEBUG_OPCODES
    ]

    output = serialize_module(header, instructions)
    with open(output_path, 'wb') as f:
        f.write(output)


def cmd_merge_reflection(*spv_paths):
    result = {"modules": [], "conflicts": []}
    all_bindings = {}  # (set, binding) -> list of {file, stage}

    for path in spv_paths:
        with open(path, 'rb') as f:
            data = f.read()

        header, instructions = parse_module(data)

        names = {}
        entry_points = []
        decorations = {}
        variables = []

        for op, ws in instructions:
            if op == OP_NAME:
                names[ws[1]] = decode_string(ws, 2)

            elif op == OP_ENTRY_POINT:
                name = decode_string(ws, 3)
                entry_points.append({
                    "execution_model": EXEC_MODEL_NAMES.get(
                        ws[1], str(ws[1])),
                    "name": name,
                })

            elif op == OP_DECORATE:
                target = ws[1]
                if target not in decorations:
                    decorations[target] = {}
                if ws[2] == DEC_DESCRIPTOR_SET:
                    decorations[target]["set"] = ws[3]
                elif ws[2] == DEC_BINDING:
                    decorations[target]["binding"] = ws[3]
                elif ws[2] == DEC_LOCATION:
                    decorations[target]["location"] = ws[3]

            elif op == OP_VARIABLE:
                sc = ws[3]
                variables.append({
                    "id": ws[2],
                    "type_id": ws[1],
                    "storage_class": STORAGE_CLASS_NAMES.get(sc, str(sc)),
                })

        # Build binding list
        bindings = []
        for var in variables:
            vid = var["id"]
            if vid in decorations:
                d = decorations[vid]
                if "set" in d and "binding" in d:
                    b = {
                        "set": d["set"],
                        "binding": d["binding"],
                        "storage_class": var["storage_class"],
                    }
                    if vid in names:
                        b["name"] = names[vid]
                    bindings.append(b)

                    key = (d["set"], d["binding"])
                    fname = os.path.basename(path)
                    stage = (entry_points[0]["execution_model"]
                             if entry_points else "unknown")
                    if key not in all_bindings:
                        all_bindings[key] = []
                    all_bindings[key].append({"file": fname, "stage": stage})

        # Build I/O interface
        inputs = []
        outputs = []
        for var in variables:
            vid = var["id"]
            if vid in decorations and "location" in decorations[vid]:
                loc_info = {"location": decorations[vid]["location"]}
                if vid in names:
                    loc_info["name"] = names[vid]
                if var["storage_class"] == "Input":
                    inputs.append(loc_info)
                elif var["storage_class"] == "Output":
                    outputs.append(loc_info)

        push_constants = any(
            v["storage_class"] == "PushConstant" for v in variables)

        mod_info = {
            "file": os.path.basename(path),
            "entry_points": entry_points,
            "bindings": bindings,
            "push_constants": push_constants,
            "inputs": sorted(inputs, key=lambda x: x["location"]),
            "outputs": sorted(outputs, key=lambda x: x["location"]),
        }
        result["modules"].append(mod_info)

    # Detect shared bindings across modules
    for (s, b), users in all_bindings.items():
        if len(users) > 1:
            result["conflicts"].append({
                "set": s, "binding": b, "used_by": users,
            })

    print(json.dumps(result, indent=2))


def main():
    if len(sys.argv) < 2:
        print("Usage: spirv_surgeon.py <command> [args...]", file=sys.stderr)
        print("Commands: analyze, remap, strip-debug, merge-reflection",
              file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "analyze":
        if len(sys.argv) < 3:
            print("Usage: spirv_surgeon.py analyze <input.spv>",
                  file=sys.stderr)
            sys.exit(1)
        cmd_analyze(sys.argv[2])

    elif cmd == "remap":
        if len(sys.argv) < 5:
            print("Usage: spirv_surgeon.py remap <in.spv> <out.spv> <map.json>",
                  file=sys.stderr)
            sys.exit(1)
        cmd_remap(sys.argv[2], sys.argv[3], sys.argv[4])

    elif cmd == "strip-debug":
        if len(sys.argv) < 4:
            print("Usage: spirv_surgeon.py strip-debug <in.spv> <out.spv>",
                  file=sys.stderr)
            sys.exit(1)
        cmd_strip_debug(sys.argv[2], sys.argv[3])

    elif cmd == "merge-reflection":
        if len(sys.argv) < 3:
            print("Usage: spirv_surgeon.py merge-reflection <f1.spv> [...]",
                  file=sys.stderr)
            sys.exit(1)
        cmd_merge_reflection(*sys.argv[2:])

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
