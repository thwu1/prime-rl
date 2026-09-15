#!/usr/bin/env python3
"""
Fix all bugs in the syzlang description file by analyzing the C header
and applying corrections based on syzlang semantic rules.

"""

import re
import sys

SYZLANG_FILE = "/app/dev_dmabuf_mgr.txt"
HEADER_FILE = "/app/include/dmabuf_mgr.h"


def parse_header_typedefs(header_content):
    """Extract typedef information from C header."""
    typedefs = {}
    for match in re.finditer(
        r"typedef\s+(__u\d+)\s+(\w+)", header_content
    ):
        c_type, name = match.groups()
        type_map = {"__u8": "int8", "__u16": "int16", "__u32": "int32", "__u64": "int64"}
        typedefs[name] = type_map.get(c_type, "intptr")
    return typedefs


def parse_header_structs(header_content):
    """Extract struct field order from C header."""
    structs = {}
    for match in re.finditer(
        r"struct\s+(\w+)\s*\{(.*?)\}", header_content, re.DOTALL
    ):
        name = match.group(1)
        body = match.group(2)
        fields = []
        for line in body.split("\n"):
            line = line.strip()
            if not line or line.startswith("/*") or line.startswith("*") or line.startswith("//"):
                continue
            # Parse field: type fieldname;
            field_match = re.match(r"(?:(?:struct\s+)?\w+)\s+(\w+)(?:\s*\[.*?\])?\s*;", line)
            if field_match:
                fields.append(field_match.group(1))
        structs[name] = fields
    return structs


def check_packed_structs(header_content):
    """Find structs with __attribute__((packed)).

    Uses a regex that handles one level of brace nesting (for unions inside
    structs) so it doesn't accidentally span across multiple struct definitions.
    """
    packed = set()
    # Match struct body allowing one level of nested { ... } (e.g. anonymous unions)
    pattern = (
        r"struct\s+(\w+)\s*\{"
        r"(?:[^{}]|\{[^{}]*\})*"
        r"\}\s*__attribute__\s*\(\s*\(\s*packed\s*\)\s*\)"
    )
    for match in re.finditer(pattern, header_content, re.DOTALL):
        packed.add(match.group(1))
    return packed


def find_zero_padding_fields(header_content):
    """Find structs where padding field comments say 'must be zero'."""
    results = {}
    for struct_match in re.finditer(
        r"struct\s+(\w+)\s*\{(.*?)\}", header_content, re.DOTALL
    ):
        name = struct_match.group(1)
        body = struct_match.group(2)
        # Look for fields with "must be zero" in nearby comment
        for line in body.split("\n"):
            if "must be zero" in line.lower() and "padding" in line.lower():
                field_match = re.search(r"__u(\d+)\s+padding", line)
                if field_match:
                    results[name] = f"int{field_match.group(1)}"
    return results


def find_sync_flag_constants(header_content):
    """Extract DMABUF_SYNC_* constants."""
    sync_flags = []
    for match in re.finditer(r"#define\s+(DMABUF_SYNC_\w+)", header_content):
        sync_flags.append(match.group(1))
    return sync_flags


def apply_fixes(syzlang_content, header_content):
    """Analyze header and apply all fixes to syzlang content."""

    typedefs = parse_header_typedefs(header_content)
    header_structs = parse_header_structs(header_content)
    packed_structs = check_packed_structs(header_content)
    zero_padding = find_zero_padding_fields(header_content)
    sync_flags = find_sync_flag_constants(header_content)

    content = syzlang_content

    # Fix 11: Add include directive for the UAPI header
    if not re.search(r"include\s+<.*dmabuf_mgr\.h>", content):
        content = "include <uapi/linux/dmabuf_mgr.h>\n" + content

    # Fix 1: Resource base type - dmabuf_handle_t is __u32 -> int32
    handle_syz_type = typedefs.get("dmabuf_handle_t", "int32")
    content = re.sub(
        r"resource\s+dmabuf_handle\s*\[\s*int64\s*\]\s*:\s*0x[fF]+",
        f"resource dmabuf_handle[{handle_syz_type}]: 0xffffffff",
        content,
    )

    # Fix 12: Type alias - alignment is __u32 in C header
    content = re.sub(
        r"type\s+dmabuf_alignment\s+int16",
        "type dmabuf_alignment int32",
        content,
    )

    # Fix 5: Sync flags - must use DMABUF_SYNC_* constants, not DMABUF_FLAG_*
    sync_line_match = re.search(r"dmabuf_sync_flags\s*=\s*(.+)", content)
    if sync_line_match:
        new_sync = "dmabuf_sync_flags = " + ", ".join(sync_flags)
        content = re.sub(r"dmabuf_sync_flags\s*=\s*.+", new_sync, content)

    # Fix 2: Open device must return fd_dmabuf
    content = re.sub(
        r"(openat\$dmabuf_mgr\s*\([^)]*\))\s+fd\b",
        r"\1 fd_dmabuf",
        content,
    )

    # Fix 4: CREATE ioctl - struct has output field, ptr must be inout
    content = re.sub(
        r"(ioctl\$DMABUF_IOC_CREATE\([^)]*?)ptr\s*\[\s*in\s*,\s*dmabuf_create_req\s*\]",
        r"\1ptr[inout, dmabuf_create_req]",
        content,
    )

    # Fix 9: DESTROY must consume dmabuf_handle resource
    content = re.sub(
        r"(ioctl\$DMABUF_IOC_DESTROY\([^)]*?)ptr\s*\[\s*in\s*,\s*int32\s*\]",
        r"\1ptr[in, dmabuf_handle]",
        content,
    )

    # Fix 10: sg_entry field order must match C header (addr, length, flags)
    sg_header_order = header_structs.get("dmabuf_sg_entry", [])
    if sg_header_order and sg_header_order[0] == "addr":
        # Reorder: current is length, addr, flags -> should be addr, length, flags
        old_sg = re.search(
            r"(dmabuf_sg_entry\s*\{)\s*\n(\s+length\s+int32)\s*\n(\s+addr\s+int64)\s*\n(\s+flags\s+.*?)\n(\s*\})",
            content, re.DOTALL
        )
        if old_sg:
            content = content[:old_sg.start()] + (
                f"{old_sg.group(1)}\n"
                f"{old_sg.group(3)}\n"
                f"{old_sg.group(2)}\n"
                f"{old_sg.group(4)}\n"
                f"{old_sg.group(5)}"
            ) + content[old_sg.end():]

    # Fix 3 & 7: dmabuf_create_req - handle must be resource output, padding const
    content = re.sub(
        r"(dmabuf_create_req\s*\{[^}]*?)(\bpadding\s+)int32(\s*\n)",
        r"\1\2const[0, int32]\3",
        content, count=1
    )
    content = re.sub(
        r"(dmabuf_create_req\s*\{[^}]*?)(\bhandle\s+)int32(\s*\n)",
        r"\1\2dmabuf_handle\t(out)\3",
        content, count=1
    )

    # Fix 7b: dmabuf_transfer_req padding must be const[0, int32]
    content = re.sub(
        r"(dmabuf_transfer_req\s*\{[^}]*?)(\bpadding\s+)int32(\s*\n)",
        r"\1\2const[0, int32]\3",
        content, count=1
    )

    # Fix 6: sg_count should be len[sg_entries, int32]
    content = re.sub(
        r"(dmabuf_query_resp\s*\{[^}]*?)(\bsg_count\s+)int32(\s+\(out\))",
        r"\1\2len[sg_entries, int32]\3",
        content, count=1
    )

    # Fix 8: dmabuf_batch_op needs [packed]
    for packed_name in packed_structs:
        syz_name = packed_name  # e.g., dmabuf_batch_op
        pattern = rf"({syz_name}\s*\{{[^}}]*\}})"
        match = re.search(pattern, content, re.DOTALL)
        if match and "[packed]" not in match.group(0):
            content = content[:match.end()] + " [packed]" + content[match.end():]

    return content


def main():
    with open(HEADER_FILE, "r") as f:
        header_content = f.read()

    with open(SYZLANG_FILE, "r") as f:
        syzlang_content = f.read()

    fixed_content = apply_fixes(syzlang_content, header_content)

    with open(SYZLANG_FILE, "w") as f:
        f.write(fixed_content)

    print(f"Fixed syzlang descriptions written to {SYZLANG_FILE}")


if __name__ == "__main__":
    main()
