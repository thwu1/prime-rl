#!/usr/bin/env python3
"""
Cilium bpf_lxc.c eBPF Datapath Static Analyzer

Parses the eBPF C source to extract:
- BPF map definitions
- Entry point functions
- Tail call program declarations (both __declare_tail and TAIL_CT_LOOKUP macros)
- Complete tail call graph (with transitive inline function resolution)
"""

import re
import json
import sys


def read_file(path):
    with open(path) as f:
        return f.read()


def extract_body_from_brace(content, brace_pos):
    """Extract a balanced brace block starting from an opening brace position."""
    brace_count = 1
    pos = brace_pos + 1
    while pos < len(content) and brace_count > 0:
        c = content[pos]
        if c == '{':
            brace_count += 1
        elif c == '}':
            brace_count -= 1
        elif c == '/' and pos + 1 < len(content):
            if content[pos + 1] == '/':
                nl = content.find('\n', pos)
                pos = nl if nl != -1 else len(content) - 1
            elif content[pos + 1] == '*':
                end = content.find('*/', pos + 2)
                pos = end + 1 if end != -1 else len(content) - 1
        elif c == '"':
            pos += 1
            while pos < len(content) and content[pos] != '"':
                if content[pos] == '\\':
                    pos += 1
                pos += 1
        elif c == "'":
            pos += 1
            while pos < len(content) and content[pos] != "'":
                if content[pos] == '\\':
                    pos += 1
                pos += 1
        pos += 1
    if brace_count == 0:
        return content[brace_pos:pos]
    return None


def extract_bpf_maps(content):
    """Extract BPF map definitions marked with __section_maps_btf."""
    maps = []
    pattern = re.compile(
        r'struct\s*\{([^}]+)\}\s*(\w+)\s*__section_maps_btf\s*;',
        re.DOTALL
    )
    for m in pattern.finditer(content):
        body = m.group(1)
        name = m.group(2)
        map_type = re.search(r'__uint\(type,\s*(BPF_MAP_TYPE_\w+)\)', body)
        key_type = re.search(r'__type\(key,\s*(.+?)\)', body)
        value_type = re.search(r'__type\(value,\s*(.+?)\)', body)
        max_entries = re.search(r'__uint\(max_entries,\s*(\d+)\)', body)
        maps.append({
            "name": name,
            "type": map_type.group(1) if map_type else "unknown",
            "key_type": key_type.group(1).strip() if key_type else "unknown",
            "value_type": value_type.group(1).strip() if value_type else "unknown",
            "max_entries": int(max_entries.group(1)) if max_entries else 0,
        })
    return maps


def extract_entry_points(content):
    """Extract functions annotated with __section_entry."""
    entries = []
    pattern = re.compile(r'__section_entry\s+int\s+(\w+)\s*\(')
    for m in pattern.finditer(content):
        entries.append({
            "function_name": m.group(1),
            "annotation": "__section_entry",
        })
    return entries


def extract_tail_call_programs(content):
    """Extract tail call programs from __declare_tail and TAIL_CT_LOOKUP macros."""
    programs = []
    # Direct __declare_tail programs
    pattern = re.compile(
        r'__declare_tail\((\w+)\)\s*'
        r'(?:static\s+__always_inline\s+)?'
        r'int\s+(\w+)\s*\(',
        re.DOTALL
    )
    for m in pattern.finditer(content):
        prog_id = m.group(1)
        if prog_id == "ID":
            continue
        programs.append({
            "id": prog_id,
            "function_name": m.group(2),
            "source": "declare_tail",
        })
    # TAIL_CT_LOOKUP4/6 macro invocations
    pattern = re.compile(r'TAIL_CT_LOOKUP[46]\(\s*(\w+)\s*,\s*(\w+)\s*,')
    for m in pattern.finditer(content):
        prog_id = m.group(1)
        if prog_id == "ID":
            continue
        programs.append({
            "id": prog_id,
            "function_name": m.group(2),
            "source": "macro",
        })
    return programs


def extract_all_function_bodies(content):
    """Extract bodies for all function definitions in the file."""
    function_bodies = {}

    pattern = re.compile(
        r'^[ \t]*(?:static\s+)?(?:__always_inline\s+)?'
        r'(?:int|void|__u32|__u16|__be32|bool)\s+'
        r'(\w+)\s*\(',
        re.MULTILINE
    )

    for m in pattern.finditer(content):
        func_name = m.group(1)
        if func_name in function_bodies:
            continue

        line_start = content.rfind('\n', 0, m.start()) + 1
        prefix = content[line_start:m.start()].strip()
        if prefix.startswith('//') or prefix.startswith('*') or prefix.startswith('#'):
            continue

        paren_pos = content.find('(', m.start() + len(m.group(0)) - 1)
        if paren_pos == -1:
            continue

        paren_count = 1
        pos = paren_pos + 1
        while pos < len(content) and paren_count > 0:
            if content[pos] == '(':
                paren_count += 1
            elif content[pos] == ')':
                paren_count -= 1
            pos += 1

        if paren_count != 0:
            continue

        rest = content[pos:pos + 200]
        brace_match = re.match(r'[\s]*(?:__maybe_unused\s*)?\{', rest)
        if not brace_match:
            continue

        brace_pos = pos + brace_match.end() - 1
        body = extract_body_from_brace(content, brace_pos)
        if body:
            function_bodies[func_name] = body

    return function_bodies


def strip_c_comments(code):
    """Remove C-style line and block comments from code."""
    result = []
    i = 0
    while i < len(code):
        if code[i] == '/' and i + 1 < len(code):
            if code[i + 1] == '/':
                end = code.find('\n', i)
                if end == -1:
                    break
                i = end
                continue
            elif code[i + 1] == '*':
                end = code.find('*/', i + 2)
                if end == -1:
                    break
                i = end + 2
                continue
        result.append(code[i])
        i += 1
    return ''.join(result)


def find_tail_call_targets(body):
    """Find CILIUM_CALL_* targets in tail_call_internal calls within a body."""
    targets = set()
    if body is None:
        return targets
    stripped = strip_c_comments(body)
    pattern = re.compile(r'tail_call_internal\s*\([^,]+,\s*(CILIUM_CALL_\w+)')
    for m in pattern.finditer(stripped):
        targets.add(m.group(1))
    return targets


def find_called_functions(body, known_functions):
    """Find calls to known functions within a function body (ignoring comments)."""
    calls = set()
    if body is None:
        return calls
    stripped = strip_c_comments(body)
    for func_name in known_functions:
        if len(func_name) < 4:
            continue
        pattern = re.compile(r'\b' + re.escape(func_name) + r'\s*\(')
        if pattern.search(stripped):
            calls.add(func_name)
    return calls


def resolve_transitive_targets(func_name, function_bodies, known_functions, visited=None):
    """Resolve all tail_call_internal targets reachable from a function, transitively."""
    if visited is None:
        visited = set()
    if func_name in visited:
        return set()
    visited.add(func_name)

    body = function_bodies.get(func_name)
    if body is None:
        return set()

    targets = find_tail_call_targets(body)

    calls = find_called_functions(body, known_functions)
    for called_func in calls:
        if called_func != func_name:
            targets |= resolve_transitive_targets(
                called_func, function_bodies, known_functions, visited
            )

    return targets


def build_tail_call_graph(content, tail_call_programs, entry_points):
    """Build the complete tail call graph."""
    graph = {}
    function_bodies = extract_all_function_bodies(content)
    known_functions = set(function_bodies.keys())

    # 1. Entry points
    for ep in entry_points:
        func_name = ep["function_name"]
        targets = resolve_transitive_targets(func_name, function_bodies, known_functions)
        if targets:
            graph[func_name] = sorted(targets)

    # 2. Direct __declare_tail programs
    for prog in tail_call_programs:
        if prog["source"] == "declare_tail":
            func_name = prog["function_name"]
            targets = resolve_transitive_targets(
                func_name, function_bodies, known_functions
            )
            if targets:
                graph[prog["id"]] = sorted(targets)

    # 3. TAIL_CT_LOOKUP macros - extract TARGET_ID (5th argument)
    tc_pattern = re.compile(
        r'TAIL_CT_LOOKUP[46]\(\s*'
        r'(\w+)\s*,\s*'      # ID (source)
        r'\w+\s*,\s*'        # NAME
        r'\w+\s*,\s*'        # DIR
        r'[^,]+?,\s*'        # CONDITION (lazy to handle multi-line)
        r'(\w+)\s*,',        # TARGET_ID
        re.DOTALL
    )
    for m in tc_pattern.finditer(content):
        source_id = m.group(1)
        target_id = m.group(2)
        if source_id == "ID":
            continue
        if source_id not in graph:
            graph[source_id] = []
        if target_id not in graph[source_id]:
            graph[source_id].append(target_id)
        graph[source_id] = sorted(set(graph[source_id]))

    return graph


def main():
    filepath = "/app/bpf_lxc.c"
    content = read_file(filepath)

    entry_points = extract_entry_points(content)
    tail_call_programs = extract_tail_call_programs(content)

    result = {
        "bpf_maps": extract_bpf_maps(content),
        "entry_points": entry_points,
        "tail_call_programs": tail_call_programs,
        "tail_call_graph": build_tail_call_graph(content, tail_call_programs, entry_points),
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Analysis complete: {len(result['bpf_maps'])} maps, "
          f"{len(result['entry_points'])} entry points, "
          f"{len(result['tail_call_programs'])} tail call programs, "
          f"{len(result['tail_call_graph'])} graph nodes")


if __name__ == "__main__":
    main()
