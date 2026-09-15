"""
SPIR-V Dead Code Analyzer — identifies dead instructions and dead functions
in SPIR-V binary modules using iterative (aggressive) elimination.

"""

import json
import os
import sys
import glob as globmod

# Ensure the parser module can be imported from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spirv_parser

# Opcode numbers for key instructions
OP_ENTRY_POINT = 15
OP_FUNCTION = 54
OP_FUNCTION_PARAMETER = 55
OP_FUNCTION_END = 56
OP_FUNCTION_CALL = 57
OP_VARIABLE = 59
OP_LABEL = 248
OP_EXT_INST_IMPORT = 11

# Instruction classes that are excluded from dead-code candidacy
EXCLUDED_CLASSES = frozenset([
    "Type-Declaration",
    "Constant-Creation",
    "Debug",
    "Annotation",
    "Extension",
    "Mode-Setting",
])

# Additional opcodes excluded from dead-code candidacy regardless of class
EXCLUDED_OPCODES = frozenset([
    OP_FUNCTION,            # 54 — OpFunction
    OP_FUNCTION_PARAMETER,  # 55 — OpFunctionParameter
    OP_FUNCTION_END,        # 56 — OpFunctionEnd
    OP_VARIABLE,            # 59 — OpVariable
    OP_LABEL,               # 248 — OpLabel
    OP_EXT_INST_IMPORT,     # 11 — OpExtInstImport
])


def _is_dead_candidate(inst):
    """
    An instruction is a dead-code candidate if:
      1) It produces a result ID
      2) Its class is not in the excluded set
      3) Its opcode is not in the excluded set
    """
    if inst["result_id"] is None:
        return False
    if inst["class"] in EXCLUDED_CLASSES:
        return False
    if inst["opcode"] in EXCLUDED_OPCODES:
        return False
    return True


def analyze(filepath):
    """
    Perform iterative dead-code analysis on a SPIR-V binary module.

    Returns a dict with:
      - dead_instruction_count: int
      - dead_function_count: int
    """
    module = spirv_parser.parse_module(filepath)
    instructions = module["instructions"]

    # ---------------------------------------------------------------
    # 1. Collect entry points and function call targets
    # ---------------------------------------------------------------
    entry_point_ids = set()
    function_call_targets = set()

    for inst in instructions:
        if inst["opcode"] == OP_ENTRY_POINT:
            # OpEntryPoint: first id_ref is the function ID
            if inst["id_refs"]:
                entry_point_ids.add(inst["id_refs"][0])
        elif inst["opcode"] == OP_FUNCTION_CALL:
            # OpFunctionCall: first id_ref is the called function ID
            if inst["id_refs"]:
                function_call_targets.add(inst["id_refs"][0])

    # ---------------------------------------------------------------
    # 2. Collect all function IDs
    # ---------------------------------------------------------------
    function_ids = set()
    for inst in instructions:
        if inst["opcode"] == OP_FUNCTION and inst["result_id"] is not None:
            function_ids.add(inst["result_id"])

    # ---------------------------------------------------------------
    # 3. Dead function detection
    # ---------------------------------------------------------------
    dead_functions = set()
    for fid in function_ids:
        if fid not in entry_point_ids and fid not in function_call_targets:
            dead_functions.add(fid)

    # ---------------------------------------------------------------
    # 4. Build use-def chains and do iterative dead-code elimination
    # ---------------------------------------------------------------
    # Index instructions by their result_id for fast lookup
    # We work with instruction indices
    inst_by_result = {}   # result_id -> instruction index
    for i, inst in enumerate(instructions):
        if inst["result_id"] is not None:
            inst_by_result[inst["result_id"]] = i

    # Build: for each result_id, the set of instruction indices that USE it
    # (not counting the result_type reference, only id_refs)
    users_of = {}   # id -> set of instruction indices that reference it
    for i, inst in enumerate(instructions):
        for ref_id in inst["id_refs"]:
            if ref_id not in users_of:
                users_of[ref_id] = set()
            users_of[ref_id].add(i)
        # Also count result_type as a use (types are excluded from
        # dead-code candidates, but their uses keep other things alive)
        if inst["result_type"] is not None:
            rt = inst["result_type"]
            if rt not in users_of:
                users_of[rt] = set()
            users_of[rt].add(i)

    # Identify dead-code candidates
    candidate_indices = set()
    for i, inst in enumerate(instructions):
        if _is_dead_candidate(inst):
            candidate_indices.add(i)

    # Iteratively remove dead instructions
    dead_indices = set()
    changed = True
    while changed:
        changed = False
        newly_dead = set()
        for i in candidate_indices:
            if i in dead_indices:
                continue
            rid = instructions[i]["result_id"]
            # Check if any LIVE instruction uses this result
            live_users = set()
            for user_idx in users_of.get(rid, set()):
                if user_idx not in dead_indices:
                    live_users.add(user_idx)
            if len(live_users) == 0:
                newly_dead.add(i)
                changed = True
        dead_indices |= newly_dead

    return {
        "dead_instruction_count": len(dead_indices),
        "dead_function_count": len(dead_functions),
    }


def main():
    """Process all .spv modules in /app/modules/ and write analysis_results.json."""
    modules_dir = "/app/modules"
    output_path = "/app/analysis_results.json"

    results = {}
    spv_files = sorted(globmod.glob(os.path.join(modules_dir, "*.spv")))

    for spv_path in spv_files:
        name = os.path.basename(spv_path)
        result = analyze(spv_path)
        results[name] = result
        print(f"{name}: {result['dead_instruction_count']} dead instructions, "
              f"{result['dead_function_count']} dead functions")

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
