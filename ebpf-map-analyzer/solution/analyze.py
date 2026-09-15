#!/usr/bin/env python3
"""
Static analyzer for Retina eBPF plugin source files.

Parses BPF map definitions, computes C struct sizes with natural alignment,
classifies SEC() kernel attachment points, and generates a corrected JSON report.

"""

import json
import os
import re
import sys

NUM_CPUS = 8
PLUGINS_DIR = "/app/plugins"
OUTPUT_FILE = "/app/corrected_report.json"

PRIMITIVE_TYPES = {
    "__u8": (1, 1),
    "__u16": (2, 2),
    "__u32": (4, 4),
    "__u64": (8, 8),
    "__s8": (1, 1),
    "__s16": (2, 2),
    "__s32": (4, 4),
    "__s64": (8, 8),
    "bool": (1, 1),
    "_Bool": (1, 1),
}


def strip_comments(content):
    content = re.sub(r"//[^\n]*", "", content)
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return content


def parse_defines(content):
    defines = {}
    for m in re.finditer(r"#define\s+(\w+)\s+(\d+)", content):
        defines[m.group(1)] = int(m.group(2))
    return defines


def parse_typedefs(content):
    typedefs = {}
    for m in re.finditer(r"typedef\s+(\w+)\s+(\w+)\s*;", content):
        typedefs[m.group(2)] = m.group(1)
    return typedefs


def parse_struct_fields(body):
    body = strip_comments(body)
    fields = []
    for segment in body.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        m = re.match(r"(struct\s+\w+|\w+)\s+(\w+)\s*\[(\d+)\]", segment)
        if m:
            fields.append((m.group(1).strip(), m.group(2), int(m.group(3))))
            continue
        m = re.match(r"(struct\s+\w+|\w+)\s+(\w+)", segment)
        if m:
            fields.append((m.group(1).strip(), m.group(2), None))
    return fields


def resolve_type(type_str, typedefs):
    resolved = type_str
    seen = set()
    while resolved in typedefs and resolved not in seen:
        seen.add(resolved)
        resolved = typedefs[resolved]
    return resolved


def get_type_size_align(type_str, struct_sizes, typedefs):
    if type_str in PRIMITIVE_TYPES:
        return PRIMITIVE_TYPES[type_str]
    resolved = resolve_type(type_str, typedefs)
    if resolved in PRIMITIVE_TYPES:
        return PRIMITIVE_TYPES[resolved]
    if resolved.startswith("struct "):
        struct_name = resolved[7:]
        if struct_name in struct_sizes:
            return struct_sizes[struct_name]
        raise ValueError(f"Unknown struct: {struct_name}")
    if type_str.startswith("struct "):
        struct_name = type_str[7:]
        if struct_name in struct_sizes:
            return struct_sizes[struct_name]
    raise ValueError(f"Unknown type: {type_str} (resolved: {resolved})")


def compute_struct_size(fields, struct_sizes, typedefs):
    offset = 0
    max_align = 1
    for field_type, _field_name, array_size in fields:
        field_size, field_align = get_type_size_align(field_type, struct_sizes, typedefs)
        if array_size is not None:
            field_size *= array_size
        padding = (field_align - (offset % field_align)) % field_align
        offset += padding + field_size
        max_align = max(max_align, field_align)
    trailing = (max_align - (offset % max_align)) % max_align
    offset += trailing
    return offset, max_align


def parse_all_structs(content, typedefs):
    struct_sizes = {}
    pattern = r"struct\s+(\w+)\s*\{([^}]+)\}\s*;"
    raw_structs = re.findall(pattern, content)
    remaining = list(raw_structs)
    for _ in range(20):
        if not remaining:
            break
        still_remaining = []
        for name, body in remaining:
            try:
                fields = parse_struct_fields(body)
                size, align = compute_struct_size(fields, struct_sizes, typedefs)
                struct_sizes[name] = (size, align)
            except ValueError:
                still_remaining.append((name, body))
        if len(still_remaining) == len(remaining):
            for name, body in still_remaining:
                print(f"Warning: could not resolve struct {name}", file=sys.stderr)
            break
        remaining = still_remaining
    return struct_sizes


def resolve_sizeof(expr, struct_sizes, typedefs):
    m = re.match(r"sizeof\s*\(\s*(struct\s+\w+|\w+)\s*\)", expr.strip())
    if m:
        type_str = m.group(1).strip()
        try:
            size, _ = get_type_size_align(type_str, struct_sizes, typedefs)
            return size
        except ValueError:
            return None
    return None


def parse_maps(content, struct_sizes, typedefs, defines):
    maps = []
    pattern = r'struct\s*\{([^}]+)\}\s*(\w+)\s*SEC\s*\(\s*"\.maps"\s*\)'
    for match in re.finditer(pattern, content):
        body = match.group(1)
        name = match.group(2)
        map_info = {
            "name": name, "type": None, "max_entries": 0,
            "key_size": 0, "value_size": 0, "pinned": False, "memory_bytes": 0,
        }
        m = re.search(r"__uint\s*\(\s*type\s*,\s*(\w+)\s*\)", body)
        if m:
            map_info["type"] = m.group(1).replace("BPF_MAP_TYPE_", "")
        m = re.search(r"__uint\s*\(\s*max_entries\s*,\s*(\w+)\s*\)", body)
        if m:
            val = m.group(1)
            if val.isdigit():
                map_info["max_entries"] = int(val)
            elif val in defines:
                map_info["max_entries"] = defines[val]
        m = re.search(r"__type\s*\(\s*key\s*,\s*([\w\s]+)\s*\)", body)
        if m:
            key_type = m.group(1).strip()
            try:
                size, _ = get_type_size_align(key_type, struct_sizes, typedefs)
                map_info["key_size"] = size
            except ValueError:
                pass
        m = re.search(r"__type\s*\(\s*value\s*,\s*([\w\s]+)\s*\)", body)
        if m:
            value_type = m.group(1).strip()
            try:
                size, _ = get_type_size_align(value_type, struct_sizes, typedefs)
                map_info["value_size"] = size
            except ValueError:
                pass
        m = re.search(r"__uint\s*\(\s*key_size\s*,\s*(.+?)\s*\)", body)
        if m:
            val = m.group(1).strip()
            if val.isdigit():
                map_info["key_size"] = int(val)
            else:
                resolved = resolve_sizeof(val, struct_sizes, typedefs)
                if resolved is not None:
                    map_info["key_size"] = resolved
        m = re.search(r"__uint\s*\(\s*value_size\s*,\s*(.+?)\s*\)", body)
        if m:
            val = m.group(1).strip()
            if val.isdigit():
                map_info["value_size"] = int(val)
            else:
                resolved = resolve_sizeof(val, struct_sizes, typedefs)
                if resolved is not None:
                    map_info["value_size"] = resolved
        if "LIBBPF_PIN_BY_NAME" in body:
            map_info["pinned"] = True
        map_info["memory_bytes"] = calculate_memory(map_info)
        maps.append(map_info)
    return maps


def calculate_memory(map_info):
    map_type = map_info.get("type", "")
    max_entries = map_info.get("max_entries", 0)
    key_size = map_info.get("key_size", 0) or 0
    value_size = map_info.get("value_size", 0) or 0
    if map_type in ("HASH", "LRU_HASH"):
        return max_entries * (key_size + value_size)
    elif map_type == "PERCPU_HASH":
        return max_entries * (key_size + value_size * NUM_CPUS)
    elif map_type == "PERCPU_ARRAY":
        return max_entries * value_size * NUM_CPUS
    elif map_type == "PERF_EVENT_ARRAY":
        return 0
    elif map_type == "RINGBUF":
        return max_entries
    return 0


def classify_section(section):
    if section.startswith("kprobe/"):
        return "kprobe"
    elif section.startswith("kretprobe/"):
        return "kretprobe"
    elif section.startswith("fexit/"):
        return "fexit"
    elif section.startswith("fentry/"):
        return "fentry"
    elif section.startswith("tracepoint/") or section.startswith("tp/"):
        return "tracepoint"
    elif section.startswith("classifier") or section.startswith("tc"):
        return "classifier"
    elif section.startswith("socket"):
        return "socket_filter"
    elif section.startswith("xdp"):
        return "xdp"
    return "unknown"


def parse_attachments(content):
    attachments = []
    pattern = r'SEC\s*\(\s*"([^"]+)"\s*\)\s*\n\s*int\s+(\w+)'
    for match in re.finditer(pattern, content):
        section = match.group(1)
        if section in (".maps", "license"):
            continue
        attach_type = classify_section(section)
        attachments.append({"section": section, "type": attach_type})
    return attachments


def analyze_plugin(filepath):
    with open(filepath) as f:
        content = f.read()
    defines = parse_defines(content)
    typedefs = parse_typedefs(content)
    struct_sizes = parse_all_structs(content, typedefs)
    maps = parse_maps(content, struct_sizes, typedefs, defines)
    attachments = parse_attachments(content)
    return {
        "maps": maps,
        "structs": {
            name: {"size": size, "alignment": align}
            for name, (size, align) in struct_sizes.items()
        },
        "attachments": attachments,
    }


def main():
    report = {"plugins": {}, "shared_maps": [], "total_memory_bytes": 0}
    for filename in sorted(os.listdir(PLUGINS_DIR)):
        if not filename.endswith(".c"):
            continue
        filepath = os.path.join(PLUGINS_DIR, filename)
        plugin_data = analyze_plugin(filepath)
        report["plugins"][filename] = plugin_data
    total_memory = 0
    for _filename, plugin_data in report["plugins"].items():
        for map_info in plugin_data["maps"]:
            total_memory += map_info.get("memory_bytes", 0)
            if map_info.get("pinned", False):
                report["shared_maps"].append(map_info["name"])
    report["total_memory_bytes"] = total_memory
    with open(OUTPUT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Corrected report written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
