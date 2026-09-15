#!/usr/bin/env python3
"""

Analyze v2 and v5 processor library APIs and produce a structured
compatibility assessment as JSON.
"""
import json
import re
import subprocess
import sys


def get_needed_libs(binary_path):
    """Extract NEEDED entries from an ELF binary's dynamic section."""
    result = subprocess.run(
        ["readelf", "-d", binary_path], capture_output=True, text=True
    )
    needed = []
    for line in result.stdout.split("\n"):
        if "NEEDED" in line:
            m = re.search(r"\[(.+?)\]", line)
            if m:
                needed.append(m.group(1))
    return needed


def get_undefined_symbols(binary_path):
    """Extract undefined dynamic symbols (imports) from a binary."""
    result = subprocess.run(
        ["nm", "-D", "-u", binary_path], capture_output=True, text=True
    )
    symbols = []
    for line in result.stdout.strip().split("\n"):
        parts = line.strip().split()
        if parts:
            symbols.append(parts[-1])
    return symbols


def parse_functions(header_path):
    """Extract function declarations from a C header file."""
    functions = []
    with open(header_path) as f:
        content = f.read()
    # Handle pointer return types like "char *func()" where there is no
    # whitespace between the asterisk and the function name.
    pattern = r"(\w+\s*\*?)\s*(\w+)\s*\(([^)]*)\)\s*;"
    for m in re.finditer(pattern, content):
        functions.append({
            "return_type": m.group(1).strip(),
            "name": m.group(2),
            "params": m.group(3).strip(),
        })
    return functions


def parse_struct_fields(header_path):
    """Extract typedef struct fields from a header."""
    with open(header_path) as f:
        content = f.read()
    pattern = r"typedef\s+struct\s*\{([^}]+)\}\s*(\w+)\s*;"
    for m in re.finditer(pattern, content, re.DOTALL):
        body = m.group(1)
        name = m.group(2)
        fields = []
        for line in body.strip().split("\n"):
            line = re.sub(r"/\*.*?\*/", "", line).strip().rstrip(";").strip()
            line = re.sub(r"//.*", "", line).strip()
            if line:
                fields.append(line)
        return name, fields
    return None, []


# --- Analyze binary ---
needed = get_needed_libs("/app/legacy_app")
imports = get_undefined_symbols("/app/legacy_app")
proc_imports = [s for s in imports if s.startswith("proc_")]

# --- Parse headers ---
v2_funcs = parse_functions("/app/libprocessor_v2.h")
v5_funcs = parse_functions("/app/libprocessor_v5/processor.h")
v2_struct_name, v2_fields = parse_struct_fields("/app/libprocessor_v2.h")
v5_struct_name, v5_fields = parse_struct_fields("/app/libprocessor_v5/processor.h")

# --- Build function mappings based on semantic analysis ---
MAPPING_KNOWLEDGE = {
    "proc_init": {
        "v5_function": "processor_initialize",
        "change_type": "renamed_and_signature_changed",
        "details": (
            "Renamed. Added 'verbose' parameter (int). "
            "Shim passes 0 for backward-compatible silent operation."
        ),
        "complexity": "low",
    },
    "proc_load": {
        "v5_function": "processor_load_file",
        "change_type": "renamed_and_semantics_changed",
        "details": (
            "Renamed. Return value semantics changed: v2 returns record count "
            "on success (-1 on error); v5 returns 0 on success (-1 on error) "
            "with count via output parameter. Requires bidirectional struct "
            "layout conversion (v5->v2 after loading)."
        ),
        "complexity": "high",
    },
    "proc_compute": {
        "v5_function": "processor_compute",
        "change_type": "renamed_and_struct_changed",
        "details": (
            "Renamed. Identical operation semantics for ops 0-3. "
            "Requires v2->v5 struct conversion of the input record array."
        ),
        "complexity": "moderate",
    },
    "proc_format": {
        "v5_function": "processor_format_result",
        "change_type": "renamed_and_signature_changed",
        "details": (
            "Renamed. Added 'scientific' parameter (int). "
            "Shim passes 0 for decimal notation to match v2 behavior."
        ),
        "complexity": "low",
    },
    "proc_cleanup": {
        "v5_function": "processor_shutdown",
        "change_type": "renamed",
        "details": "Simple rename with identical semantics.",
        "complexity": "trivial",
    },
}

mappings = []
v5_func_names = {f["name"] for f in v5_funcs}
for v2_f in v2_funcs:
    name = v2_f["name"]
    if name in MAPPING_KNOWLEDGE:
        mk = MAPPING_KNOWLEDGE[name]
        v5_match = next(
            (f for f in v5_funcs if f["name"] == mk["v5_function"]), None
        )
        entry = {
            "v2_function": name,
            "v2_signature": f"{v2_f['return_type']} {name}({v2_f['params']})",
            "v5_function": mk["v5_function"],
            "v5_signature": (
                f"{v5_match['return_type']} {v5_match['name']}({v5_match['params']})"
                if v5_match else "unknown"
            ),
            "change_type": mk["change_type"],
            "details": mk["details"],
            "complexity": mk["complexity"],
        }
        mappings.append(entry)

# --- Analyze struct differences ---
struct_changes = []
if v2_fields and v5_fields:
    v2_names = [f.split()[-1].split("[")[0] for f in v2_fields]
    v5_names = [f.split()[-1].split("[")[0] for f in v5_fields]

    common = set(v2_names) & set(v5_names)
    for field in sorted(common):
        v2_idx = v2_names.index(field)
        v5_idx = v5_names.index(field)
        v2_decl = v2_fields[v2_idx]
        v5_decl = v5_fields[v5_idx]
        if v2_idx != v5_idx or v2_decl != v5_decl:
            change = "position_moved" if v2_idx != v5_idx else "type_or_size_changed"
            struct_changes.append({
                "field": field,
                "change": change,
                "v2_declaration": v2_decl,
                "v5_declaration": v5_decl,
                "v2_position": v2_idx,
                "v5_position": v5_idx,
                "impact": (
                    "Field reordering means raw memory copy between v2 and v5 "
                    "structs is unsafe; explicit per-field conversion required"
                    if change == "position_moved"
                    else "Size/type difference requires truncation or extension "
                    "during struct conversion"
                ),
            })

    new_in_v5 = set(v5_names) - set(v2_names)
    for field in sorted(new_in_v5):
        idx = v5_names.index(field)
        struct_changes.append({
            "field": field,
            "change": "added_in_v5",
            "v5_declaration": v5_fields[idx],
            "impact": "New field requires a sensible default value when "
            "converting v2 records to v5 format",
        })

# --- Behavioral differences ---
behavioral = [
    {
        "function_pair": "proc_load / processor_load_file",
        "difference": "return_value_semantics",
        "details": (
            "v2 returns count of loaded records on success, -1 on error. "
            "v5 returns 0 on success, -1 on error, with count provided "
            "via an int* output parameter."
        ),
    },
    {
        "function_pair": "proc_compute / processor_compute",
        "difference": "error_handling_for_unknown_operations",
        "details": (
            "v5 returns NAN for unknown operation codes; v2 returns 0.0. "
            "Not triggered by legacy_app which only uses operations 0-3."
        ),
    },
]

# --- Assemble assessment ---
mapped_v5_names = {m["v5_function"] for m in mappings}
new_v5_funcs = [f["name"] for f in v5_funcs if f["name"] not in mapped_v5_names]

assessment = {
    "binary_analysis": {
        "needed_libraries": needed,
        "required_v2_symbols": proc_imports,
    },
    "mappings": mappings,
    "struct_changes": struct_changes,
    "behavioral_differences": behavioral,
    "new_v5_functions_without_v2_equivalent": new_v5_funcs,
    "overall_risk": "moderate",
    "overall_assessment": (
        "All v2 functions have direct v5 equivalents. Primary complexity "
        "arises from struct layout conversion (field reordering, label "
        "buffer resize 32->64, new priority field) and the return value "
        "semantic change in proc_load/processor_load_file. No v2 "
        "functionality was removed without replacement in v5."
    ),
}

with open("/app/compatibility_assessment.json", "w") as f:
    json.dump(assessment, f, indent=2)

print("Compatibility assessment written to /app/compatibility_assessment.json")
