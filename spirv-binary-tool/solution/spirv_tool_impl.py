#!/usr/bin/env python3

"""SPIR-V binary tool: analyze, strip-dead, compact, merge.

Operates directly on SPIR-V binary format without shelling out to spirv-tools.
Uses /app/spirv_reference.json for opcode operand layout information.
"""

import json
import struct
import sys
from collections import defaultdict

SPIRV_MAGIC = 0x07230203

# Non-aggregate type opcodes that must be unique per SPIR-V spec 2.2.1
TYPE_OPCODES = {
    19,  # OpTypeVoid
    20,  # OpTypeBool
    21,  # OpTypeInt
    22,  # OpTypeFloat
    23,  # OpTypeVector
    24,  # OpTypeMatrix
    25,  # OpTypeImage
    27,  # OpTypeSampledImage
    28,  # OpTypeArray
    29,  # OpTypeRuntimeArray
    30,  # OpTypeStruct
    31,  # OpTypePointer
    33,  # OpTypeFunction
}

_ref_cache = None


def load_reference(path="/app/spirv_reference.json"):
    global _ref_cache
    if _ref_cache is None:
        with open(path) as f:
            _ref_cache = json.load(f)
    return _ref_cache


class SpvInstruction:
    """A single SPIR-V instruction with all its words."""

    __slots__ = ("opcode", "words", "result_id", "type_id")

    def __init__(self, opcode, words, result_id=None, type_id=None):
        self.opcode = opcode
        self.words = words
        self.result_id = result_id
        self.type_id = type_id

    @property
    def word_count(self):
        return len(self.words)


class SpvModule:
    """In-memory representation of a SPIR-V module."""

    def __init__(self):
        self.magic = SPIRV_MAGIC
        self.version = 0
        self.generator = 0
        self.bound = 0
        self.schema = 0
        self.instructions = []

    @staticmethod
    def from_binary(data):
        """Parse a SPIR-V binary blob into a SpvModule."""
        if len(data) < 20:
            raise ValueError("Data too short for SPIR-V header")

        words = struct.unpack(f"<{len(data) // 4}I", data)

        module = SpvModule()
        module.magic = words[0]
        if module.magic != SPIRV_MAGIC:
            raise ValueError(f"Bad SPIR-V magic: 0x{module.magic:08x}")
        module.version = words[1]
        module.generator = words[2]
        module.bound = words[3]
        module.schema = words[4]

        ref = load_reference()
        inst_defs = ref["instructions"]

        pos = 5
        while pos < len(words):
            wc = words[pos] >> 16
            opcode = words[pos] & 0xFFFF

            if wc == 0:
                raise ValueError(f"Zero word-count at position {pos}")

            inst_words = list(words[pos : pos + wc])

            result_id = None
            type_id = None

            opc_str = str(opcode)
            if opc_str in inst_defs:
                defn = inst_defs[opc_str]
                idx = 1
                if defn.get("has_type_id"):
                    if idx < len(inst_words):
                        type_id = inst_words[idx]
                    idx += 1
                if defn.get("has_result_id"):
                    if idx < len(inst_words):
                        result_id = inst_words[idx]
                    idx += 1

            inst = SpvInstruction(opcode, inst_words, result_id, type_id)
            module.instructions.append(inst)
            pos += wc

        return module

    # -----------------------------------------------------------------
    # ID position analysis
    # -----------------------------------------------------------------

    @staticmethod
    def _get_id_positions(inst):
        """Return indices into inst.words that hold SPIR-V IDs."""
        ref = load_reference()
        inst_defs = ref["instructions"]
        opc_str = str(inst.opcode)

        positions = []

        if opc_str not in inst_defs:
            return positions

        defn = inst_defs[opc_str]
        idx = 1

        if defn.get("has_type_id"):
            if idx < len(inst.words):
                positions.append(idx)
            idx += 1
        if defn.get("has_result_id"):
            if idx < len(inst.words):
                positions.append(idx)
            idx += 1

        for op in defn.get("operands", []):
            if idx >= len(inst.words):
                break
            kind = op["kind"]
            if kind == "id":
                positions.append(idx)
                idx += 1
            elif kind == "literal":
                idx += 1
            elif kind == "string":
                # Scan for null-terminated string padded to word boundary
                while idx < len(inst.words):
                    w = inst.words[idx]
                    idx += 1
                    # Check each byte for NUL terminator
                    bs = struct.pack("<I", w)
                    if 0 in bs:
                        break
            elif kind == "id_list":
                while idx < len(inst.words):
                    positions.append(idx)
                    idx += 1
            elif kind == "literal_list":
                idx = len(inst.words)
            elif kind == "literal_id_pairs":
                while idx + 1 < len(inst.words):
                    idx += 1  # skip literal
                    positions.append(idx)  # id
                    idx += 1
            else:
                idx += 1

        return positions

    @staticmethod
    def _get_result_id_pos(inst):
        """Return the word index of the result ID, or None."""
        ref = load_reference()
        inst_defs = ref["instructions"]
        opc_str = str(inst.opcode)
        if opc_str not in inst_defs:
            return None
        defn = inst_defs[opc_str]
        idx = 1
        if defn.get("has_type_id"):
            idx += 1
        if defn.get("has_result_id"):
            return idx
        return None

    # -----------------------------------------------------------------
    # Serialization
    # -----------------------------------------------------------------

    def to_binary(self):
        """Serialize module back to a SPIR-V binary blob."""
        # Recompute bound from all IDs
        max_id = 0
        for inst in self.instructions:
            for pos in self._get_id_positions(inst):
                if pos < len(inst.words) and inst.words[pos] > max_id:
                    max_id = inst.words[pos]
        self.bound = max_id + 1

        header = struct.pack(
            "<5I", self.magic, self.version, self.generator, self.bound, self.schema
        )
        body = b""
        for inst in self.instructions:
            body += struct.pack(f"<{len(inst.words)}I", *inst.words)
        return header + body

    # -----------------------------------------------------------------
    # ID remapping
    # -----------------------------------------------------------------

    def remap_ids(self, id_map):
        """Replace every ID occurrence according to id_map."""
        for inst in self.instructions:
            _remap_inst_ids(inst, id_map)

    # -----------------------------------------------------------------
    # Convenience queries
    # -----------------------------------------------------------------

    def _extract_string(self, words, start_idx):
        """Extract a null-terminated string from instruction words."""
        raw = b""
        for w in words[start_idx:]:
            raw += struct.pack("<I", w)
            if 0 in struct.pack("<I", w):
                break
        return raw.split(b"\x00")[0].decode("utf-8", errors="replace")

    def _string_word_count(self, s):
        """Number of 32-bit words needed to encode string s (incl NUL)."""
        return (len(s.encode("utf-8")) + 1 + 3) // 4

    def get_names(self):
        """Return dict mapping ID -> name from OpName instructions."""
        names = {}
        for inst in self.instructions:
            if inst.opcode == 5:  # OpName
                target_id = inst.words[1]
                names[target_id] = self._extract_string(inst.words, 2)
        return names

    def get_entry_points(self):
        """Return list of entry point dicts."""
        ref = load_reference()
        exec_models = ref["execution_models"]
        eps = []
        for inst in self.instructions:
            if inst.opcode == 15:  # OpEntryPoint
                model = inst.words[1]
                func_id = inst.words[2]
                name = self._extract_string(inst.words, 3)
                eps.append(
                    {
                        "name": name,
                        "execution_model": exec_models.get(str(model), str(model)),
                        "id": func_id,
                    }
                )
        return eps

    def get_capabilities(self):
        ref = load_reference()
        cap_names = ref["capabilities"]
        caps = []
        for inst in self.instructions:
            if inst.opcode == 17:
                val = inst.words[1]
                caps.append(cap_names.get(str(val), str(val)))
        return caps

    def get_functions(self):
        names = self.get_names()
        funcs = []
        for inst in self.instructions:
            if inst.opcode == 54:  # OpFunction
                fid = inst.result_id
                funcs.append(
                    {
                        "name": names.get(fid, f"func_{fid}"),
                        "id": fid,
                        "return_type_id": inst.type_id,
                    }
                )
        return funcs


# =====================================================================
# Helper functions for merge type deduplication
# =====================================================================


def _remap_inst_ids(inst, id_map):
    """Remap all IDs in an instruction according to id_map."""
    if not id_map:
        return
    for pos in SpvModule._get_id_positions(inst):
        if pos < len(inst.words) and inst.words[pos] in id_map:
            inst.words[pos] = id_map[inst.words[pos]]
    if inst.result_id is not None and inst.result_id in id_map:
        inst.result_id = id_map[inst.result_id]
    if inst.type_id is not None and inst.type_id in id_map:
        inst.type_id = id_map[inst.type_id]


def _type_fingerprint(inst, dedup_map):
    """Compute a canonical fingerprint for a type instruction.

    The result_id is zeroed out (so two types with different result IDs
    but identical structure produce the same fingerprint). All other ID
    references are resolved through dedup_map so that types depending on
    already-deduplicated types can be matched correctly.
    """
    id_positions = set(SpvModule._get_id_positions(inst))
    result_id_pos = SpvModule._get_result_id_pos(inst)

    fp = []
    for i, w in enumerate(inst.words):
        if i == result_id_pos:
            fp.append(0)
        elif i in id_positions:
            fp.append(dedup_map.get(w, w))
        else:
            fp.append(w)
    return tuple(fp)


# =====================================================================
# Subcommands
# =====================================================================


def cmd_analyze(input_path):
    with open(input_path, "rb") as f:
        data = f.read()
    module = SpvModule.from_binary(data)

    ver_major = (module.version >> 16) & 0xFF
    ver_minor = (module.version >> 8) & 0xFF

    report = {
        "header": {
            "magic": module.magic,
            "version": {"major": ver_major, "minor": ver_minor},
            "generator": module.generator,
            "bound": module.bound,
            "schema": module.schema,
        },
        "entry_points": module.get_entry_points(),
        "functions": module.get_functions(),
        "capabilities": module.get_capabilities(),
    }
    print(json.dumps(report, indent=2))


def cmd_strip_dead(input_path, output_path):
    with open(input_path, "rb") as f:
        data = f.read()
    module = SpvModule.from_binary(data)

    # --- determine root functions (entry points + exports) ---
    roots = set()
    for inst in module.instructions:
        if inst.opcode == 15:  # OpEntryPoint
            roots.add(inst.words[2])
    # Exported functions (OpDecorate with decoration 41 = LinkageAttributes,
    # last word 0 = Export)
    for inst in module.instructions:
        if inst.opcode == 71 and len(inst.words) >= 4:
            if inst.words[2] == 41 and inst.words[-1] == 0:
                roots.add(inst.words[1])

    # --- locate function bodies and build call graph ---
    functions = {}  # func_id -> (start_idx, end_idx)
    calls = defaultdict(set)
    cur_func = None
    cur_start = None

    for i, inst in enumerate(module.instructions):
        if inst.opcode == 54:  # OpFunction
            cur_func = inst.result_id
            cur_start = i
        elif inst.opcode == 56:  # OpFunctionEnd
            if cur_func is not None:
                functions[cur_func] = (cur_start, i)
            cur_func = None
        elif inst.opcode == 57 and cur_func is not None:  # OpFunctionCall
            calls[cur_func].add(inst.words[3])

    # --- BFS to find reachable functions ---
    reachable = set()
    queue = list(roots)
    while queue:
        fid = queue.pop()
        if fid in reachable:
            continue
        reachable.add(fid)
        for callee in calls.get(fid, ()):
            if callee not in reachable:
                queue.append(callee)

    dead_fids = set(functions.keys()) - reachable

    # Collect all result-IDs defined inside dead functions
    dead_result_ids = set()
    for fid in dead_fids:
        s, e = functions[fid]
        for idx in range(s, e + 1):
            inst = module.instructions[idx]
            if inst.result_id is not None:
                dead_result_ids.add(inst.result_id)

    # --- build set of instruction indices to remove ---
    remove = set()
    for fid in dead_fids:
        s, e = functions[fid]
        for idx in range(s, e + 1):
            remove.add(idx)

    # Remove orphaned OpName / OpDecorate / OpMemberDecorate
    for i, inst in enumerate(module.instructions):
        if inst.opcode in (5, 71):  # OpName, OpDecorate
            if inst.words[1] in dead_result_ids:
                remove.add(i)
        elif inst.opcode == 72:  # OpMemberDecorate
            if inst.words[1] in dead_result_ids:
                remove.add(i)

    module.instructions = [
        inst for i, inst in enumerate(module.instructions) if i not in remove
    ]

    with open(output_path, "wb") as f:
        f.write(module.to_binary())


def cmd_compact(input_path, output_path):
    with open(input_path, "rb") as f:
        data = f.read()
    module = SpvModule.from_binary(data)

    # Collect IDs in order of first appearance
    seen_order = []
    seen_set = set()
    for inst in module.instructions:
        for pos in SpvModule._get_id_positions(inst):
            if pos < len(inst.words):
                val = inst.words[pos]
                if val > 0 and val not in seen_set:
                    seen_order.append(val)
                    seen_set.add(val)

    id_map = {old: new for new, old in enumerate(seen_order, start=1)}
    module.remap_ids(id_map)

    with open(output_path, "wb") as f:
        f.write(module.to_binary())


def cmd_merge(path_a, path_b, output_path):
    with open(path_a, "rb") as f:
        data_a = f.read()
    with open(path_b, "rb") as f:
        data_b = f.read()

    mod_a = SpvModule.from_binary(data_a)
    mod_b = SpvModule.from_binary(data_b)

    # --- shift all IDs in mod_b so they don't collide with mod_a ---
    offset = mod_a.bound - 1

    b_ids = set()
    for inst in mod_b.instructions:
        for pos in SpvModule._get_id_positions(inst):
            if pos < len(inst.words) and inst.words[pos] > 0:
                b_ids.add(inst.words[pos])

    id_map = {old: old + offset for old in b_ids}
    mod_b.remap_ids(id_map)

    # --- categorize instructions by SPIR-V section ---
    def _categorize(instructions):
        secs = {
            "cap": [],
            "ext": [],
            "ext_import": [],
            "memmodel": [],
            "entry": [],
            "exec_mode": [],
            "debug": [],
            "annot": [],
            "types": [],
            "funcs": [],
        }
        in_func = False
        for inst in instructions:
            op = inst.opcode
            if op == 17:
                secs["cap"].append(inst)
            elif op == 10:
                secs["ext"].append(inst)
            elif op == 11:
                secs["ext_import"].append(inst)
            elif op == 14:
                secs["memmodel"].append(inst)
            elif op == 15:
                secs["entry"].append(inst)
            elif op == 16:
                secs["exec_mode"].append(inst)
            elif op in (5, 6, 7, 8, 330):  # debug / names / strings / line
                secs["debug"].append(inst)
            elif op in (71, 72, 73, 74, 75, 76, 77):
                secs["annot"].append(inst)
            elif op == 54:
                in_func = True
                secs["funcs"].append(inst)
            elif in_func:
                secs["funcs"].append(inst)
                if op == 56:
                    in_func = False
            else:
                secs["types"].append(inst)
        return secs

    sa = _categorize(mod_a.instructions)
    sb = _categorize(mod_b.instructions)

    # --- Deduplicate type declarations from module B against module A ---
    # SPIR-V spec 2.2.1: non-aggregate type declarations must be unique.
    # After ID-shifting, B may have structurally identical types to A
    # (e.g. both modules declare OpTypeVoid). We detect these and remap
    # B's type IDs to A's equivalents.

    # Build fingerprint -> result_id map from A's types
    a_type_fps = {}
    for inst in sa["types"]:
        if inst.opcode in TYPE_OPCODES and inst.result_id is not None:
            fp = _type_fingerprint(inst, {})
            a_type_fps[fp] = inst.result_id

    # Process B's types in order, building a dedup map
    dedup_map = {}  # B_shifted_type_id -> A_type_id
    b_types_kept = []
    for inst in sb["types"]:
        if inst.opcode in TYPE_OPCODES and inst.result_id is not None:
            # Compute fingerprint with current dedup map applied
            fp = _type_fingerprint(inst, dedup_map)
            if fp in a_type_fps:
                # Duplicate — map B's ID to A's existing ID
                dedup_map[inst.result_id] = a_type_fps[fp]
            else:
                # New type — keep it, apply dedup map to its operands
                _remap_inst_ids(inst, dedup_map)
                a_type_fps[fp] = inst.result_id
                b_types_kept.append(inst)
        else:
            # Non-type instruction (constant, variable, etc.) — keep it
            _remap_inst_ids(inst, dedup_map)
            b_types_kept.append(inst)

    # Apply dedup map to all other B sections
    for section_name in ("entry", "exec_mode", "debug", "annot", "funcs"):
        for inst in sb[section_name]:
            _remap_inst_ids(inst, dedup_map)

    # --- Assemble merged module ---
    merged = SpvModule()
    merged.magic = mod_a.magic
    merged.version = max(mod_a.version, mod_b.version)
    merged.generator = mod_a.generator
    merged.schema = 0

    # Capabilities: deduplicate by value
    seen_caps = set()
    for inst in sa["cap"] + sb["cap"]:
        cv = inst.words[1]
        if cv not in seen_caps:
            seen_caps.add(cv)
            merged.instructions.append(inst)

    # Extensions
    merged.instructions.extend(sa["ext"])
    merged.instructions.extend(sb["ext"])

    # ExtInstImport
    merged.instructions.extend(sa["ext_import"])
    merged.instructions.extend(sb["ext_import"])

    # Memory model: use module A's
    merged.instructions.extend(sa["memmodel"])

    # Entry points
    merged.instructions.extend(sa["entry"])
    merged.instructions.extend(sb["entry"])

    # Execution modes
    merged.instructions.extend(sa["exec_mode"])
    merged.instructions.extend(sb["exec_mode"])

    # Debug
    merged.instructions.extend(sa["debug"])
    merged.instructions.extend(sb["debug"])

    # Annotations
    merged.instructions.extend(sa["annot"])
    merged.instructions.extend(sb["annot"])

    # Types & constants — use A's full set + B's deduplicated set
    merged.instructions.extend(sa["types"])
    merged.instructions.extend(b_types_kept)

    # Functions
    merged.instructions.extend(sa["funcs"])
    merged.instructions.extend(sb["funcs"])

    with open(output_path, "wb") as f:
        f.write(merged.to_binary())


# =====================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: spirv_tool.py <command> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "analyze":
        if len(sys.argv) != 3:
            print("Usage: spirv_tool.py analyze <input.spv>", file=sys.stderr)
            sys.exit(1)
        cmd_analyze(sys.argv[2])

    elif cmd == "strip-dead":
        if len(sys.argv) != 4:
            print(
                "Usage: spirv_tool.py strip-dead <input.spv> <output.spv>",
                file=sys.stderr,
            )
            sys.exit(1)
        cmd_strip_dead(sys.argv[2], sys.argv[3])

    elif cmd == "compact":
        if len(sys.argv) != 4:
            print(
                "Usage: spirv_tool.py compact <input.spv> <output.spv>",
                file=sys.stderr,
            )
            sys.exit(1)
        cmd_compact(sys.argv[2], sys.argv[3])

    elif cmd == "merge":
        if len(sys.argv) != 5:
            print(
                "Usage: spirv_tool.py merge <a.spv> <b.spv> <output.spv>",
                file=sys.stderr,
            )
            sys.exit(1)
        cmd_merge(sys.argv[2], sys.argv[3], sys.argv[4])

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
