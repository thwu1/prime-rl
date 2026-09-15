#!/usr/bin/env python3
"""
Generate syzkaller syzlang descriptions from the accelq.h kernel header.

Parses the header to extract ioctl commands, data structures, flag definitions,
and field-level annotations, then applies syzlang modeling rules to produce
correct syscall descriptions with resource types, producer/consumer chains,
pointer directions, and length annotations.

"""

import re
import sys
from collections import OrderedDict

# C-to-syzlang type mapping
CTYPE_MAP = {
    "__u8": "int8", "__u16": "int16", "__u32": "int32", "__u64": "int64",
    "__s8": "int8", "__s16": "int16", "__s32": "int32", "__s64": "int64",
}

# Fields that represent resource types: name -> (syzlang_resource, base_type)
RESOURCE_FIELDS = {
    "ctx_id": ("accelq_ctx", "int32"),
    "queue_id": ("accelq_queue", "int32"),
    "job_id": ("accelq_job", "int32"),
    "handle": ("accelq_buf_handle", "int64"),
    "src_handle": ("accelq_buf_handle", "int64"),
    "dst_handle": ("accelq_buf_handle", "int64"),
}

DIRECTION_MAP = {"IOW": "in", "IOR": "out", "IOWR": "inout"}


def parse_header(path):
    """Extract defines, ioctls, and structs from the kernel header."""
    with open(path) as f:
        header = f.read()

    # Extract ACCELQ_* flag constants (not ioctl macros, not header guard, not MAGIC)
    flag_defines = []
    for m in re.finditer(r"^#define\s+(ACCELQ_\w+)\s+(\S+)", header, re.MULTILINE):
        name, val = m.group(1), m.group(2)
        if "MAGIC" not in name and "_IO" not in val:
            flag_defines.append(name)

    # Group flag constants by category prefix (ACCELQ_CTX, ACCELQ_QUEUE, etc.)
    flag_groups = OrderedDict()
    for name in flag_defines:
        parts = name.split("_")
        if len(parts) >= 3:
            group = "_".join(parts[:2])  # e.g. ACCELQ_CTX from ACCELQ_CTX_SHARED
            flag_groups.setdefault(group, []).append(name)

    # Extract ioctl commands: (name, direction_macro, struct_type)
    ioctls = []
    for m in re.finditer(
        r"#define\s+(ACCELQ_\w+)\s+_(IO\w*)\s*\(\s*ACCELQ_MAGIC\s*,\s*\w+\s*,"
        r"\s*struct\s+(\w+)\s*\)",
        header,
    ):
        ioctls.append((m.group(1), m.group(2), m.group(3)))

    # Extract struct definitions with fields and comments
    structs = OrderedDict()
    for m in re.finditer(r"struct\s+(\w+)\s*\{(.*?)\};", header, re.DOTALL):
        sname = m.group(1)
        fields = []
        for fm in re.finditer(
            r"(__\w+)\s+(\w+)(?:\[(\d+)\])?\s*;\s*/\*\s*(.*?)\s*\*/",
            m.group(2),
        ):
            fields.append({
                "ctype": fm.group(1),
                "name": fm.group(2),
                "array": fm.group(3),
                "comment": fm.group(4),
            })
        structs[sname] = fields

    return flag_groups, ioctls, structs


def syz_flag_name(group_key):
    """Convert a flag group prefix to a syzlang flag set name."""
    suffix = group_key.replace("ACCELQ_", "").lower()
    if suffix == "op":
        return "accelq_op_types"
    elif suffix == "prio":
        return "accelq_prio_values"
    return f"accelq_{suffix}_flags"


def field_is_output(comment):
    """Check if a field comment indicates output direction."""
    c = comment.strip().lower()
    return c.startswith("out")


def field_is_input(comment):
    """Check if a field comment indicates input-only direction."""
    c = comment.strip().lower()
    return c.startswith("in:") or c.startswith("in ")


def find_flag_ref(comment, flag_groups):
    """Find which flag group a comment references, if any."""
    for gk in flag_groups:
        prefix = gk.split("_")[1]  # CTX, QUEUE, SUBMIT, etc.
        if f"ACCELQ_{prefix}" in comment:
            return syz_flag_name(gk)
    return None


def render_field(field, variant, flag_groups):
    """Convert a C struct field to syzlang type and annotation."""
    fname = field["name"]
    ctype = field["ctype"]
    comment = field["comment"]
    arr = field["array"]
    base = CTYPE_MAP.get(ctype, "int32")

    # Reserved / zero fields
    if fname == "reserved" or "must be 0" in comment:
        return fname, f"const[0, {base}]", ""

    # Special indirect pointer field
    if fname == "descs_ptr":
        return fname, "ptr64[in, array[accelq_descriptor]]", ""

    # Length field for descriptor array
    if fname == "nr_descs":
        return fname, "len[descs_ptr, int32]", ""

    # Fixed-size array fields
    if arr:
        elem_type = CTYPE_MAP.get(ctype, "int8")
        return fname, f"array[{elem_type}, {arr}]", ""

    # Resource-typed fields
    if fname in RESOURCE_FIELDS:
        rtype = RESOURCE_FIELDS[fname][0]
        if variant in ("create", "map") and field_is_output(comment):
            return fname, rtype, "(out)"
        elif variant in ("destroy", "unmap"):
            return fname, rtype, ""
        elif field_is_output(comment):
            return fname, rtype, "(out)"
        elif field_is_input(comment):
            return fname, rtype, "(in)"
        return fname, rtype, ""

    # For destroy/unmap, non-resource fields become const[0]
    if variant in ("destroy", "unmap"):
        return fname, f"const[0, {base}]", ""

    # Flag-typed fields
    fref = find_flag_ref(comment, flag_groups)
    if fref and (fname in ("flags", "op", "priority") or "flags" in comment.lower()):
        return fname, f"flags[{fref}, {base}]", ""

    # Regular fields with output direction
    if field_is_output(comment):
        return fname, base, "(out)"

    return fname, base, ""


def determine_variants(sname, ioctls):
    """Determine which struct variants are needed based on ioctl usage."""
    variants = set()
    for iname, _, istruct in ioctls:
        if istruct == sname:
            if "CREATE" in iname:
                variants.add("create")
            elif "DESTROY" in iname:
                variants.add("destroy")
            elif iname == "ACCELQ_MAP_BUFFER":
                variants.add("map")
            elif iname == "ACCELQ_UNMAP_BUFFER":
                variants.add("unmap")
            else:
                variants.add("default")
    return variants or {"default"}


def generate(header_path, output_path):
    """Main generation logic."""
    flag_groups, ioctls, structs = parse_header(header_path)

    out = []

    # Header
    out.append("# Syzkaller descriptions for /dev/accelq")
    out.append("# Generated from kernel header analysis")
    out.append("")
    out.append("include <linux/ioctl.h>")
    out.append("include <accelq.h>")
    out.append("")

    # Resources
    out.append("resource fd_accelq[fd]")
    emitted = set()
    for fname, (rname, btype) in RESOURCE_FIELDS.items():
        if rname not in emitted:
            out.append(f"resource {rname}[{btype}]")
            emitted.add(rname)
    out.append("")

    # Device open
    out.append(
        'syz_open_dev$accelq(dev ptr[in, string["/dev/accelq"]], '
        "id const[0], flags flags[open_flags]) fd_accelq"
    )
    out.append("")

    # ioctl declarations
    for iname, idir, istruct in ioctls:
        pdir = DIRECTION_MAP.get(idir, "in")
        if "CREATE" in iname:
            vname = f"{istruct}_create"
        elif "DESTROY" in iname:
            vname = f"{istruct}_destroy"
        elif iname == "ACCELQ_MAP_BUFFER":
            vname = f"{istruct}_map"
        elif iname == "ACCELQ_UNMAP_BUFFER":
            vname = f"{istruct}_unmap"
        else:
            vname = istruct
        out.append(
            f"ioctl${iname}(fd fd_accelq, cmd const[{iname}], "
            f"arg ptr[{pdir}, {vname}])"
        )
    out.append("")

    # Flag declarations
    for gk, members in flag_groups.items():
        out.append(f"{syz_flag_name(gk)} = {', '.join(members)}")
    out.append("")

    # Struct declarations
    for sname, fields in structs.items():
        variants = determine_variants(sname, ioctls)
        for var in sorted(variants):
            vname = sname if var == "default" else f"{sname}_{var}"
            out.append(f"{vname} {{")
            for field in fields:
                fname, stype, ann = render_field(field, var, flag_groups)
                suffix = f"\t{ann}" if ann else ""
                out.append(f"\t{fname}\t{stype}{suffix}")
            out.append("}")
            out.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(out))

    print(
        f"Generated {len(ioctls)} ioctls, {len(structs)} structs, "
        f"{len(flag_groups)} flag groups -> {output_path}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <header.h> <output.txt>", file=sys.stderr)
        sys.exit(1)
    generate(sys.argv[1], sys.argv[2])
