"""
SPIR-V Binary Parser — reads .spv files and extracts structured instruction data.

Uses the SPIR-V core grammar JSON (from spirv-headers) to determine operand
structure for each opcode, enabling correct identification of result IDs,
result types, and ID references.

"""

import struct
import json
import os
import glob as globmod

SPIRV_MAGIC = 0x07230203

# Operand kinds that represent ID references (not result type/id)
ID_REF_KINDS = frozenset([
    "IdRef", "IdScope", "IdMemorySemantics",
])

# Operand kinds that are single-word non-ID values
SINGLE_WORD_KINDS = frozenset([
    "LiteralInteger", "LiteralFloat", "LiteralExtInstInteger",
    "LiteralSpecConstantOpInteger",
    # All enum kinds are single-word
    "Capability", "SourceLanguage", "ExecutionModel", "AddressingModel",
    "MemoryModel", "ExecutionMode", "StorageClass", "Dim",
    "SamplerAddressingMode", "SamplerFilterMode", "ImageFormat",
    "ImageChannelOrder", "ImageChannelDataType", "FPRoundingMode",
    "FPDenormMode", "FPOperationMode", "QuantizationModes",
    "OverflowModes", "LinkageType", "AccessQualifier",
    "FunctionParameterAttribute", "Decoration", "BuiltIn",
    "Scope", "GroupOperation", "KernelEnqueueFlags",
    "RayFlags", "RayQueryIntersection", "RayQueryCommittedIntersectionType",
    "RayQueryCandidateIntersectionType", "PackedVectorFormat",
    "CooperativeMatrixOperands", "CooperativeMatrixLayout",
    "CooperativeMatrixUse", "InitializationModeQualifier",
    "HostAccessQualifier", "LoadCacheControl", "StoreCacheControl",
    "NamedMaximumNumberOfRegisters",
])

# Mask/composite kinds that are one word but may enable extra operands
MASK_KINDS = frozenset([
    "ImageOperands", "FPFastMathMode", "SelectionControl", "LoopControl",
    "FunctionControl", "MemorySemantics", "MemoryAccess",
    "KernelProfilingInfo", "RawAccessChainOperands",
    "CooperativeMatrixOperands",
])

# Pair kinds
PAIR_KINDS = {
    "PairIdRefIdRef": (True, True),
    "PairIdRefLiteralInteger": (True, False),
    "PairLiteralIntegerIdRef": (False, True),
}


def _find_grammar():
    """Locate the SPIR-V core grammar JSON."""
    search_paths = [
        "/usr/include/spirv/unified1/spirv.core.grammar.json",
        "/usr/share/spirv/unified1/spirv.core.grammar.json",
        "/usr/local/include/spirv/unified1/spirv.core.grammar.json",
    ]
    # Also try globbing
    for pattern in ["/usr/**/spirv.core.grammar.json"]:
        search_paths.extend(globmod.glob(pattern, recursive=True))
    for path in search_paths:
        if os.path.isfile(path):
            return path
    return None


def _load_opcode_map(grammar_path):
    """Build opcode -> instruction info mapping from grammar JSON."""
    with open(grammar_path) as f:
        grammar = json.load(f)

    opcode_map = {}
    for inst in grammar.get("instructions", []):
        opcode = inst["opcode"]
        opname = inst["opname"]
        operands = inst.get("operands", [])

        has_result_type = any(op["kind"] == "IdResultType" for op in operands)
        has_result_id = any(op["kind"] == "IdResult" for op in operands)

        # Store the operand specs (excluding IdResultType and IdResult)
        other_operands = [
            op for op in operands
            if op["kind"] not in ("IdResultType", "IdResult")
        ]

        opcode_map[opcode] = {
            "opname": opname,
            "has_result_type": has_result_type,
            "has_result_id": has_result_id,
            "other_operands": other_operands,
            "class": inst.get("class", ""),
        }

    return opcode_map


def _extract_id_refs(other_operands, remaining_words):
    """
    Parse remaining operand words according to grammar operand specs,
    extracting all ID references.
    """
    id_refs = []
    word_idx = 0

    for op_spec in other_operands:
        if word_idx >= len(remaining_words):
            break

        kind = op_spec["kind"]
        quantifier = op_spec.get("quantifier", "")

        if kind in ID_REF_KINDS:
            if quantifier == "*":
                # Variadic — consume all remaining words as ID refs
                while word_idx < len(remaining_words):
                    id_refs.append(remaining_words[word_idx])
                    word_idx += 1
            else:
                id_refs.append(remaining_words[word_idx])
                word_idx += 1

        elif kind == "LiteralString":
            # Variable-length null-terminated string, padded to word boundary
            while word_idx < len(remaining_words):
                w = remaining_words[word_idx]
                word_idx += 1
                # Check if any byte in the word is zero (null terminator)
                has_null = False
                for i in range(4):
                    if ((w >> (8 * i)) & 0xFF) == 0:
                        has_null = True
                        break
                if has_null:
                    break

        elif kind in ("LiteralContextDependentNumber",):
            # Can be 1 or more words depending on type width.
            # In non-variadic context, consume 1 word.
            # In variadic context, consume remaining.
            if quantifier == "*":
                word_idx = len(remaining_words)
            else:
                word_idx += 1

        elif kind in PAIR_KINDS:
            first_is_id, second_is_id = PAIR_KINDS[kind]
            if quantifier == "*":
                while word_idx + 1 < len(remaining_words):
                    if first_is_id:
                        id_refs.append(remaining_words[word_idx])
                    if second_is_id:
                        id_refs.append(remaining_words[word_idx + 1])
                    word_idx += 2
            else:
                if word_idx + 1 < len(remaining_words):
                    if first_is_id:
                        id_refs.append(remaining_words[word_idx])
                    if second_is_id:
                        id_refs.append(remaining_words[word_idx + 1])
                    word_idx += 2

        elif kind in MASK_KINDS:
            # Mask is 1 word; may enable additional operands which
            # we skip for now (they are not commonly ID refs)
            word_idx += 1

        elif kind in SINGLE_WORD_KINDS:
            if quantifier == "*":
                word_idx = len(remaining_words)
            else:
                word_idx += 1

        else:
            # Unknown kind — consume 1 word, treat as non-ID
            word_idx += 1

    return id_refs


def parse_module(filepath):
    """
    Parse a SPIR-V binary module from a .spv file.

    Returns a dict with:
      - header: dict with magic, version_major, version_minor, generator, bound
      - instructions: list of instruction dicts
    """
    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 20:
        raise ValueError("File too small to be a SPIR-V module")

    # Determine endianness from magic number
    magic_le = struct.unpack_from("<I", data, 0)[0]
    magic_be = struct.unpack_from(">I", data, 0)[0]
    if magic_le == SPIRV_MAGIC:
        endian = "<"
    elif magic_be == SPIRV_MAGIC:
        endian = ">"
    else:
        raise ValueError(
            f"Invalid SPIR-V magic number: {hex(magic_le)} / {hex(magic_be)}"
        )

    # Parse 5-word header
    hw = struct.unpack_from(f"{endian}5I", data, 0)
    header = {
        "magic": hw[0],
        "version_major": (hw[1] >> 16) & 0xFF,
        "version_minor": (hw[1] >> 8) & 0xFF,
        "generator": hw[2],
        "bound": hw[3],
        "reserved": hw[4],
    }

    # Load grammar for operand parsing
    grammar_path = _find_grammar()
    if grammar_path:
        opcode_map = _load_opcode_map(grammar_path)
    else:
        opcode_map = {}

    # Parse instruction stream
    instructions = []
    offset = 20  # past header (5 words * 4 bytes)
    while offset < len(data):
        if offset + 4 > len(data):
            break

        first_word = struct.unpack_from(f"{endian}I", data, offset)[0]
        word_count = (first_word >> 16) & 0xFFFF
        opcode = first_word & 0xFFFF

        if word_count == 0:
            raise ValueError(f"Zero word count at byte offset {offset}")
        if offset + word_count * 4 > len(data):
            raise ValueError(
                f"Instruction at offset {offset} extends past end of data "
                f"(wc={word_count}, opcode={opcode})"
            )

        # Read all words of this instruction
        inst_words = struct.unpack_from(
            f"{endian}{word_count}I", data, offset
        )
        operand_words = list(inst_words[1:])  # everything after opcode word

        info = opcode_map.get(opcode, {})
        opname = info.get("opname", f"OpUnknown_{opcode}")
        has_result_type = info.get("has_result_type", False)
        has_result_id = info.get("has_result_id", False)

        result_type = None
        result_id = None
        consumed = 0

        if has_result_type and consumed < len(operand_words):
            result_type = operand_words[consumed]
            consumed += 1
        if has_result_id and consumed < len(operand_words):
            result_id = operand_words[consumed]
            consumed += 1

        remaining_words = operand_words[consumed:]

        # Extract ID references from remaining operands
        other_operands = info.get("other_operands", [])
        if other_operands:
            id_refs = _extract_id_refs(other_operands, remaining_words)
        else:
            # No grammar info — can't extract ID refs reliably
            id_refs = []

        instructions.append({
            "opcode": opcode,
            "opname": opname,
            "word_count": word_count,
            "result_type": result_type,
            "result_id": result_id,
            "id_refs": id_refs,
            "class": info.get("class", ""),
        })

        offset += word_count * 4

    return {
        "header": header,
        "instructions": instructions,
    }
