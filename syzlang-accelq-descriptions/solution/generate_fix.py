#!/usr/bin/env python3
"""
Evaluate two candidate syzlang description files against the kernel header,
produce evaluation.json with correctness judgments, and generate the correct
unified syzlang descriptions.

"""

import json
import re
import sys
from collections import OrderedDict

CTYPE_MAP = {
    "__u8": "int8", "__u16": "int16", "__u32": "int32", "__u64": "int64",
    "__s8": "int8", "__s16": "int16", "__s32": "int32", "__s64": "int64",
}

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
    with open(path) as f:
        header = f.read()

    flag_defines = []
    for m in re.finditer(r"^#define\s+(ACCELQ_\w+)\s+(\S+)", header, re.MULTILINE):
        name, val = m.group(1), m.group(2)
        if "MAGIC" not in name and "_IO" not in val:
            flag_defines.append(name)

    flag_groups = OrderedDict()
    for name in flag_defines:
        parts = name.split("_")
        if len(parts) >= 3:
            group = "_".join(parts[:2])
            flag_groups.setdefault(group, []).append(name)

    ioctls = []
    for m in re.finditer(
        r"#define\s+(ACCELQ_\w+)\s+_(IO\w*)\s*\(\s*ACCELQ_MAGIC\s*,\s*\w+\s*,"
        r"\s*struct\s+(\w+)\s*\)",
        header,
    ):
        ioctls.append((m.group(1), m.group(2), m.group(3)))

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
    suffix = group_key.replace("ACCELQ_", "").lower()
    if suffix == "op":
        return "accelq_op_types"
    elif suffix == "prio":
        return "accelq_prio_values"
    return f"accelq_{suffix}_flags"


def field_is_output(comment):
    c = comment.strip().lower()
    return c.startswith("out")


def field_is_input(comment):
    c = comment.strip().lower()
    return c.startswith("in:") or c.startswith("in ")


def find_flag_ref(comment, flag_groups):
    for gk in flag_groups:
        prefix = gk.split("_")[1]
        if f"ACCELQ_{prefix}" in comment:
            return syz_flag_name(gk)
    return None


def render_field(field, variant, flag_groups):
    fname = field["name"]
    ctype = field["ctype"]
    comment = field["comment"]
    arr = field["array"]
    base = CTYPE_MAP.get(ctype, "int32")

    if fname == "reserved" or "must be 0" in comment:
        return fname, f"const[0, {base}]", ""

    if fname == "descs_ptr":
        return fname, "ptr64[in, array[accelq_descriptor]]", ""

    if fname == "nr_descs":
        return fname, "len[descs_ptr, int32]", ""

    if arr:
        elem_type = CTYPE_MAP.get(ctype, "int8")
        return fname, f"array[{elem_type}, {arr}]", ""

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

    if variant in ("destroy", "unmap"):
        return fname, f"const[0, {base}]", ""

    fref = find_flag_ref(comment, flag_groups)
    if fref and (fname in ("flags", "op", "priority") or "flags" in comment.lower()):
        return fname, f"flags[{fref}, {base}]", ""

    if field_is_output(comment):
        return fname, base, "(out)"

    return fname, base, ""


def determine_variants(sname, ioctls):
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


def generate_evaluation():
    """Produce the evaluation.json comparing candidates A and B."""
    return {
        "include_path": {
            "correct": "A",
            "explanation": (
                "Candidate A uses 'include <accelq.h>' which matches the direct header "
                "filename. Candidate B uses 'include <uapi/linux/accelq.h>' which requires "
                "fallback resolution during syz-extract, potentially yielding incorrect "
                "constant values. The syz-extract warning in the coverage report confirms "
                "B's path is problematic."
            ),
        },
        "buf_handle_base_type": {
            "correct": "B",
            "explanation": (
                "The kernel header declares handle as __u64, requiring int64 base type. "
                "Candidate B correctly uses 'resource accelq_buf_handle[int64]' while "
                "Candidate A incorrectly uses int32, causing a width mismatch at the "
                "kernel boundary that prevents buffer mapping from succeeding."
            ),
        },
        "create_ctx_ptr_direction": {
            "correct": "A",
            "explanation": (
                "ACCELQ_CREATE_CTX is defined as _IOWR (bidirectional), meaning the kernel "
                "both reads input fields and writes output fields (ctx_id). Candidate A "
                "correctly uses ptr[inout, ...] while Candidate B uses ptr[in, ...], which "
                "prevents the kernel from writing the produced ctx_id back to userspace. "
                "The coverage report shows B's CREATE_CTX never enters the handler."
            ),
        },
        "ctx_id_resource_production": {
            "correct": "A",
            "explanation": (
                "The ctx_id field in the create struct must be typed as accelq_ctx with an "
                "(out) annotation to establish the resource production chain. Candidate A "
                "has 'ctx_id accelq_ctx (out)' while Candidate B uses 'ctx_id int32' — a "
                "raw integer with no resource annotation, breaking the dependency chain "
                "for all downstream operations that consume ctx_id."
            ),
        },
        "queue_id_resource_production": {
            "correct": "B",
            "explanation": (
                "The queue_id field in accelq_queue_args_create must have (out) annotation "
                "since CREATE_QUEUE produces the queue_id. Candidate B correctly has "
                "'queue_id accelq_queue (out)' while Candidate A omits the (out), so "
                "the fuzzer never captures produced queue_ids for use in SUBMIT/WAIT calls."
            ),
        },
        "submit_args_field_order": {
            "correct": "B",
            "explanation": (
                "The C struct accelq_submit_args declares fields in order: ctx_id, "
                "queue_id, nr_descs, flags, descs_ptr, job_id, reserved. Candidate B "
                "preserves this order while Candidate A swaps flags and nr_descs. In "
                "syzlang, struct field order must match C layout for correct memory "
                "mapping — the swap causes the kernel to interpret flags as nr_descs "
                "and vice versa, producing -EINVAL on SUBMIT calls."
            ),
        },
        "descs_ptr_type_modeling": {
            "correct": "A",
            "explanation": (
                "The descs_ptr field holds a userspace pointer to an array of "
                "accelq_descriptor structs. Candidate A correctly models this as "
                "'ptr64[in, array[accelq_descriptor]]' which tells syzkaller to allocate "
                "a descriptor array and pass its address. Candidate B uses raw 'int64' "
                "which causes syzkaller to pass random integers instead of valid pointers."
            ),
        },
        "nr_descs_length_annotation": {
            "correct": "A",
            "explanation": (
                "nr_descs specifies the number of descriptors in the array pointed to by "
                "descs_ptr. Candidate A uses 'len[descs_ptr, int32]' which ensures the "
                "count matches the actual array length. Candidate B uses plain 'int32' "
                "which generates arbitrary values, causing out-of-bounds access or the "
                "kernel rejecting the call for count/array mismatch."
            ),
        },
        "descriptor_op_flag_reference": {
            "correct": "B",
            "explanation": (
                "The header documents the descriptor op field as 'ACCELQ_OP_*' (operation "
                "types: COPY, TRANSFORM, REDUCE, CUSTOM). Candidate B correctly uses "
                "'flags[accelq_op_types, int32]' while Candidate A incorrectly uses "
                "'flags[accelq_submit_flags, int32]', generating submission flags "
                "(FENCE/SIGNAL/NO_WAIT) as operation codes — semantically invalid values "
                "that always fail validation."
            ),
        },
        "descriptor_handle_resource_types": {
            "correct": "A",
            "explanation": (
                "The src_handle and dst_handle fields in accelq_descriptor reference "
                "buffer handles produced by ACCELQ_MAP_BUFFER. Candidate A correctly "
                "types them as 'accelq_buf_handle' (the resource type), enabling "
                "syzkaller to use previously mapped buffer handles. Candidate B uses "
                "raw 'int64', so the fuzzer passes random values that never match "
                "valid mapped buffers."
            ),
        },
    }


def generate_syzlang(header_path, output_path):
    flag_groups, ioctls, structs = parse_header(header_path)

    out = []
    out.append("# Syzkaller descriptions for /dev/accelq")
    out.append("")
    out.append("include <linux/ioctl.h>")
    out.append("include <accelq.h>")
    out.append("")

    out.append("resource fd_accelq[fd]")
    emitted = set()
    for fname, (rname, btype) in RESOURCE_FIELDS.items():
        if rname not in emitted:
            out.append(f"resource {rname}[{btype}]")
            emitted.add(rname)
    out.append("")

    out.append(
        'syz_open_dev$accelq(dev ptr[in, string["/dev/accelq"]], '
        "id const[0], flags flags[open_flags]) fd_accelq"
    )
    out.append("")

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

    for gk, members in flag_groups.items():
        out.append(f"{syz_flag_name(gk)} = {', '.join(members)}")
    out.append("")

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

    print(f"Generated {len(ioctls)} ioctls, {len(structs)} structs -> {output_path}")


def main():
    header_path = sys.argv[1] if len(sys.argv) > 1 else "/app/header/accelq.h"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/app/accelq.txt"
    eval_path = sys.argv[3] if len(sys.argv) > 3 else "/app/evaluation.json"

    # Generate evaluation
    evaluation = generate_evaluation()
    with open(eval_path, "w") as f:
        json.dump(evaluation, f, indent=2)
    print(f"Wrote evaluation to {eval_path}")

    # Generate correct syzlang
    generate_syzlang(header_path, output_path)


if __name__ == "__main__":
    main()
