#!/usr/bin/env python3

"""Syzlang const extraction, cross-validation, struct audit, and reachability pipeline."""

import json
import os
import re
import subprocess
import tempfile


PRIMITIVE_TYPES = {
    "int8", "int16", "int32", "int64", "intptr",
    "int8be", "int16be", "int32be", "int64be",
    "bool8", "bool16", "bool32", "bool64", "boolptr",
    "void", "filename", "text",
}


# ── Type expression parser ──────────────────────────────────────────────

class TypeExpr:
    def __init__(self, name, params=None):
        self.name = name
        self.params = params or []

    def __repr__(self):
        if self.params:
            return f"{self.name}[{', '.join(str(p) for p in self.params)}]"
        return self.name


def _split_at_top_level(s, sep=","):
    parts = []
    depth = 0
    current = []
    in_string = False
    escape = False
    for c in s:
        if escape:
            current.append(c)
            escape = False
            continue
        if c == "\\":
            current.append(c)
            escape = True
            continue
        if c == '"' and not in_string:
            in_string = True
            current.append(c)
            continue
        if c == '"' and in_string:
            in_string = False
            current.append(c)
            continue
        if in_string:
            current.append(c)
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(c)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_type_expr(s):
    s = s.strip()
    if not s:
        return TypeExpr("")

    bracket_start = -1
    in_string = False
    for i, c in enumerate(s):
        if c == '"':
            in_string = not in_string
        elif c == "[" and not in_string:
            bracket_start = i
            break

    if bracket_start == -1:
        return TypeExpr(s)

    name = s[:bracket_start]

    depth = 0
    close_idx = -1
    in_str = False
    for i in range(bracket_start, len(s)):
        c = s[i]
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break

    if close_idx == -1:
        return TypeExpr(s)

    params_str = s[bracket_start + 1:close_idx]
    raw_params = _split_at_top_level(params_str)
    params = [parse_type_expr(p) for p in raw_params]
    return TypeExpr(name, params)


# ── Const extraction via GCC ────────────────────────────────────────────

def extract_ioctl_constants(header_path, include_dir):
    """Extract HWACCEL_* ioctl command macro values by compiling a C program."""
    with open(header_path) as f:
        header = f.read()

    ioctl_macros = re.findall(
        r'#define\s+(HWACCEL_\w+)\s+_IO(?:R|W|WR)?\s*\(',
        header
    )

    if not ioctl_macros:
        return {}

    c_code = '#include <stdio.h>\n#include "linux/hwaccel.h"\n\nint main(void) {\n'
    for macro in ioctl_macros:
        c_code += f'    printf("{macro}=%u\\n", (unsigned int){macro});\n'
    c_code += '    return 0;\n}\n'

    with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
        f.write(c_code)
        c_file = f.name

    bin_file = c_file.replace('.c', '')
    try:
        subprocess.run(
            ['gcc', f'-I{include_dir}', '-o', bin_file, c_file],
            check=True, capture_output=True
        )
        result = subprocess.run(
            [bin_file], check=True, capture_output=True, text=True
        )
        constants = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                name, val = line.split('=', 1)
                constants[name.strip()] = int(val.strip())
        return constants
    finally:
        os.unlink(c_file)
        if os.path.exists(bin_file):
            os.unlink(bin_file)


# ── IOC field decoder ───────────────────────────────────────────────────

def decode_ioc(value):
    return {
        "direction": (value >> 30) & 0x3,
        "size": (value >> 16) & 0x3FFF,
        "type": (value >> 8) & 0xFF,
        "number": value & 0xFF,
    }


# ── C struct parser ─────────────────────────────────────────────────────

def parse_c_structs(header_path):
    """Parse C struct definitions from a header, extracting field names and array sizes."""
    with open(header_path) as f:
        content = f.read()

    structs = {}
    for m in re.finditer(r'struct\s+(\w+)\s*\{([^}]+)\}', content, re.DOTALL):
        name = m.group(1)
        body = m.group(2)
        fields = []
        for line in body.strip().split('\n'):
            line = line.strip().rstrip(';').strip()
            if not line or line.startswith('/*') or line.startswith('//') or line.startswith('*'):
                continue
            # Match array field: type name[size]
            fm = re.match(r'(__?\w+)\s+(\w+)\[(\d+)\]', line)
            if fm:
                fields.append({
                    'name': fm.group(2),
                    'type': fm.group(1),
                    'array_size': int(fm.group(3)),
                })
            else:
                # Match scalar field: type name
                fm = re.match(r'(__?\w+)\s+(\w+)', line)
                if fm:
                    fields.append({
                        'name': fm.group(2),
                        'type': fm.group(1),
                        'array_size': None,
                    })
        structs[name] = fields

    return structs


# ── Syzlang parser ─────────────────────────────────────────────────────

class SyzlangAnalyzer:
    def __init__(self):
        self.resources = {}
        self.syscalls = {}
        self.structs = {}
        self.flags = {}

    def parse_directory(self, path):
        for fname in sorted(os.listdir(path)):
            if fname.endswith(".txt"):
                self._parse_file(os.path.join(path, fname))

    def _parse_file(self, filepath):
        with open(filepath) as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            line = lines[i].rstrip("\n")
            stripped = line.strip()

            if (
                not stripped
                or stripped.startswith("#")
                or stripped.startswith("include ")
                or stripped.startswith("define ")
                or stripped.startswith("meta ")
            ):
                i += 1
                continue

            if stripped.startswith("resource "):
                self._parse_resource(stripped)
                i += 1
                continue

            if stripped.startswith("type "):
                i += 1
                continue

            if self._looks_like_struct_start(stripped):
                name = stripped.rstrip("{").strip()
                body, i = self._collect_block(lines, i + 1, "}")
                self._parse_struct(name, body)
                continue

            if self._looks_like_union_start(stripped):
                name = stripped.rstrip("[").strip()
                body, i = self._collect_block(lines, i + 1, "]")
                self._parse_struct(name, body)
                continue

            if "=" in stripped and not self._has_paren_before_eq(stripped):
                self._parse_flags(stripped)
                i += 1
                continue

            if "(" in stripped:
                self._parse_syscall(stripped)
                i += 1
                continue

            i += 1

    @staticmethod
    def _looks_like_struct_start(s):
        if not s.endswith("{"):
            return False
        prefix = s[:-1].strip()
        return bool(prefix) and "(" not in prefix

    @staticmethod
    def _looks_like_union_start(s):
        if not s.endswith("["):
            return False
        prefix = s[:-1].strip()
        return bool(prefix) and "(" not in prefix and "=" not in prefix

    @staticmethod
    def _has_paren_before_eq(s):
        eq_idx = s.index("=")
        return "(" in s[:eq_idx]

    @staticmethod
    def _collect_block(lines, start, closer):
        body = []
        i = start
        while i < len(lines):
            l = lines[i].rstrip("\n").strip()
            if l.startswith(closer):
                i += 1
                return body, i
            if l and not l.startswith("#"):
                body.append(l)
            i += 1
        return body, i

    def _parse_resource(self, line):
        m = re.match(r"resource\s+(\w+)\[([^\]]+)\](?:\s*:\s*(.+))?", line)
        if not m:
            return
        name = m.group(1)
        parent = m.group(2).strip()
        special_values = []
        if m.group(3):
            for tok in m.group(3).split(","):
                tok = tok.strip()
                try:
                    if tok.startswith("0x") or tok.startswith("0X"):
                        special_values.append(int(tok, 16))
                    elif tok.lstrip("-").isdigit():
                        special_values.append(int(tok))
                except ValueError:
                    pass
        self.resources[name] = {"parent": parent, "special_values": special_values}

    def _parse_flags(self, line):
        name, _, vals = line.partition("=")
        name = name.strip()
        values = [v.strip() for v in vals.split(",") if v.strip()]
        self.flags[name] = values

    def _parse_struct(self, name, body_lines):
        fields = []
        for raw in body_lines:
            parts = raw.split()
            if len(parts) < 2:
                continue
            field_name = parts[0]
            remaining = raw[len(field_name):].strip()

            direction = None
            dir_match = re.search(r"\((\w+)\)\s*$", remaining)
            if dir_match:
                d = dir_match.group(1)
                if d in ("in", "out", "inout", "out_overlay"):
                    direction = d
                    remaining = remaining[:dir_match.start()].strip()

            if_match = re.search(r"\(if\[.*?\]\)\s*$", remaining)
            if if_match:
                remaining = remaining[:if_match.start()].strip()

            type_expr = parse_type_expr(remaining)
            fields.append(
                {"name": field_name, "type_expr": type_expr, "direction": direction}
            )
        self.structs[name] = fields

    def _parse_syscall(self, line):
        paren_idx = self._find_top_level_char(line, "(")
        if paren_idx == -1:
            return
        name = line[:paren_idx].strip()

        depth = 0
        close_idx = -1
        for i in range(paren_idx, len(line)):
            if line[i] == "(":
                depth += 1
            elif line[i] == ")":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
        if close_idx == -1:
            return

        args_str = line[paren_idx + 1:close_idx]
        after = line[close_idx + 1:].strip()
        after = re.sub(r"\([\w,\s]+\)\s*$", "", after).strip()
        return_type = after if after else None

        args = []
        if args_str.strip():
            for raw_arg in _split_at_top_level(args_str):
                raw_arg = raw_arg.strip()
                if not raw_arg:
                    continue
                sp = raw_arg.split(None, 1)
                if len(sp) == 2:
                    args.append(
                        {"name": sp[0], "type_expr": parse_type_expr(sp[1])}
                    )
        self.syscalls[name] = {"args": args, "return_type": return_type}

    @staticmethod
    def _find_top_level_char(s, ch):
        depth = 0
        for i, c in enumerate(s):
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
            elif c == ch and depth == 0:
                return i
        return -1

    # ── analysis ─────────────────────────────────────────────────────

    def analyze(self, extracted_constants=None, c_structs=None):
        res_info = {}
        for rname, rmeta in self.resources.items():
            producers = sorted(self._find_producers(rname))
            consumers = sorted(self._find_consumers(rname))
            res_info[rname] = {
                "parent": rmeta["parent"],
                "special_values": rmeta["special_values"],
                "producers": producers,
                "consumers": consumers,
            }

        orphans = sorted(
            r for r in self.resources
            if not res_info[r]["producers"] or not res_info[r]["consumers"]
        )

        no_producer = {r for r in self.resources if not res_info[r]["producers"]}
        dead = sorted(
            s for s in self.syscalls
            if self._consumed_resources(s) & no_producer
        )

        # Ioctl mismatch detection
        ioctl_mismatches = []
        if extracted_constants:
            ioctl_mismatches = self._find_ioctl_mismatches(extracted_constants)

        # Resource dependency ordering
        dep_order = self._compute_resource_dependency_order(res_info)

        # Struct field audit
        struct_audit = {}
        if c_structs:
            struct_audit = self._struct_field_audit(c_structs)

        # Minimum call depth
        call_depth = self._compute_minimum_call_depth(res_info)

        return {
            "extracted_constants": extracted_constants or {},
            "ioctl_mismatches": ioctl_mismatches,
            "struct_field_audit": struct_audit,
            "resources": res_info,
            "orphan_resources": orphans,
            "dead_consumers": dead,
            "undefined_refs": self._find_undefined_flag_refs(),
            "invalid_len_refs": self._find_invalid_len_refs(),
            "unused_flags": sorted(self._find_unused_flags()),
            "resource_dependency_order": dep_order,
            "minimum_call_depth": call_depth,
        }

    # ── struct field audit ──────────────────────────────────────────

    @staticmethod
    def _get_syzlang_array_size(type_expr):
        """Extract array size from a syzlang type expression, or None."""
        if type_expr.name == "array" and len(type_expr.params) >= 2:
            try:
                return int(type_expr.params[1].name)
            except ValueError:
                return None
        return None

    def _struct_field_audit(self, c_structs):
        """Compare syzlang struct fields against C struct fields for layout bugs."""
        result = {}
        for syz_name, syz_fields in self.structs.items():
            if syz_name not in c_structs:
                continue
            c_fields_by_name = {}
            for cf in c_structs[syz_name]:
                c_fields_by_name[cf['name']] = cf

            discrepancies = []
            for sf in syz_fields:
                fname = sf['name']
                if fname not in c_fields_by_name:
                    continue
                cf = c_fields_by_name[fname]
                syz_arr = self._get_syzlang_array_size(sf['type_expr'])
                c_arr = cf['array_size']
                if syz_arr is not None and c_arr is not None and syz_arr != c_arr:
                    discrepancies.append({
                        "field": fname,
                        "issue": "array_size_mismatch",
                        "syzlang_value": syz_arr,
                        "c_value": c_arr,
                    })

            if discrepancies:
                result[syz_name] = sorted(discrepancies, key=lambda d: d["field"])
        return result

    # ── minimum call depth ──────────────────────────────────────────

    def _compute_minimum_call_depth(self, res_info):
        """Compute minimum prerequisite syscall count for each syscall."""
        memo = {}
        result = {}
        for sname in self.syscalls:
            prereqs = self._prereq_set(sname, res_info, memo, frozenset())
            if prereqs is None:
                result[sname] = -1
            else:
                result[sname] = len(prereqs)
        return result

    def _prereq_set(self, syscall_name, res_info, memo, in_progress):
        """Recursively compute the set of distinct prerequisite syscalls."""
        if syscall_name in memo:
            return memo[syscall_name]
        if syscall_name in in_progress:
            return frozenset()  # cycle guard

        in_progress = in_progress | {syscall_name}
        consumed = self._consumed_resources(syscall_name)

        if not consumed:
            memo[syscall_name] = frozenset()
            return frozenset()

        prereqs = set()
        for res_name in consumed:
            if res_name not in res_info:
                continue
            producers = res_info[res_name]["producers"]
            if not producers:
                memo[syscall_name] = None
                return None  # unreachable — resource has no producer

            # Find best producer (smallest prerequisite set)
            best = None
            for producer in producers:
                p_prereqs = self._prereq_set(producer, res_info, memo, in_progress)
                if p_prereqs is None:
                    continue  # this producer is also unreachable
                candidate = p_prereqs | {producer}
                if best is None or len(candidate) < len(best):
                    best = candidate

            if best is None:
                memo[syscall_name] = None
                return None  # all producers unreachable
            prereqs |= best

        result = frozenset(prereqs)
        memo[syscall_name] = result
        return result

    # ── ioctl mismatch detection ────────────────────────────────────

    def _find_ioctl_mismatches(self, extracted_constants):
        mismatches = []
        for sname, sinfo in self.syscalls.items():
            if not sname.startswith("ioctl$"):
                continue
            variant = sname.split("$", 1)[1] if "$" in sname else None
            if not variant or variant not in extracted_constants:
                continue

            cmd_val = None
            for arg in sinfo["args"]:
                if arg["name"] == "cmd":
                    te = arg["type_expr"]
                    if te.name == "const" and te.params:
                        try:
                            raw = te.params[0].name
                            if raw.startswith("0x") or raw.startswith("0X"):
                                cmd_val = int(raw, 16)
                            else:
                                cmd_val = int(raw)
                        except ValueError:
                            pass
                    break

            if cmd_val is None:
                continue

            expected_val = extracted_constants[variant]
            if cmd_val != expected_val:
                syz_fields = decode_ioc(cmd_val)
                exp_fields = decode_ioc(expected_val)
                diffs = sorted(
                    f for f in ["direction", "number", "size", "type"]
                    if syz_fields[f] != exp_fields[f]
                )
                mismatches.append({
                    "syscall": sname,
                    "syzlang_value": cmd_val,
                    "expected_value": expected_val,
                    "mismatch_fields": diffs,
                })

        return sorted(mismatches, key=lambda m: m["syscall"])

    # ── resource dependency ordering ────────────────────────────────

    def _compute_resource_dependency_order(self, res_info):
        deps = {}
        for rname, rinfo in res_info.items():
            if not rinfo["producers"]:
                continue
            required = set()
            for producer in rinfo["producers"]:
                if producer in self.syscalls:
                    consumed = self._consumed_resources(producer)
                    required |= consumed
            deps[rname] = {r for r in required if r in deps or res_info.get(r, {}).get("producers")}

        produced = {r for r in res_info if res_info[r]["producers"]}
        for r in list(deps.keys()):
            if r not in produced:
                del deps[r]
        for r in produced:
            if r not in deps:
                deps[r] = set()
            deps[r] = {d for d in deps[r] if d in produced}

        result = []
        remaining = dict(deps)
        while remaining:
            ready = sorted(r for r, d in remaining.items()
                          if not (d - set(result)))
            if not ready:
                result.extend(sorted(remaining.keys()))
                break
            result.append(ready[0])
            del remaining[ready[0]]

        return result

    # ── producer / consumer helpers ──────────────────────────────────

    def _find_producers(self, resource_name):
        producers = []
        for sname, sinfo in self.syscalls.items():
            if sinfo["return_type"] == resource_name:
                producers.append(sname)
                continue
            if self._any_arg_produces(sinfo["args"], resource_name):
                producers.append(sname)
        return producers

    def _any_arg_produces(self, args, resource_name):
        for arg in args:
            te = arg["type_expr"]
            if te.name in ("ptr", "ptr64") and len(te.params) >= 2:
                direction = te.params[0].name
                inner = te.params[1]
                if direction == "out":
                    if self._struct_has_resource_field(inner.name, resource_name):
                        return True
                elif direction == "inout":
                    if self._struct_has_out_resource(inner.name, resource_name):
                        return True
        return False

    def _struct_has_resource_field(self, sname, resource_name):
        if sname not in self.structs:
            return False
        for f in self.structs[sname]:
            if f["type_expr"].name == resource_name:
                return True
        return False

    def _struct_has_out_resource(self, sname, resource_name):
        if sname not in self.structs:
            return False
        for f in self.structs[sname]:
            if f["type_expr"].name == resource_name and f["direction"] == "out":
                return True
        return False

    def _find_consumers(self, resource_name):
        consumers = []
        for sname, sinfo in self.syscalls.items():
            if self._syscall_consumes(sinfo, resource_name):
                consumers.append(sname)
        return consumers

    def _syscall_consumes(self, sinfo, resource_name):
        for arg in sinfo["args"]:
            if arg["type_expr"].name == resource_name:
                return True
            te = arg["type_expr"]
            if te.name in ("ptr", "ptr64") and len(te.params) >= 2:
                direction = te.params[0].name
                inner = te.params[1]
                if direction == "in":
                    if self._struct_consumes(inner.name, resource_name):
                        return True
                elif direction == "inout":
                    if self._struct_consumes_non_out(inner.name, resource_name):
                        return True
        return False

    def _struct_consumes(self, sname, resource_name):
        if sname not in self.structs:
            return False
        for f in self.structs[sname]:
            ft = f["type_expr"]
            if ft.name == resource_name:
                return True
            if ft.name in ("ptr", "ptr64") and len(ft.params) >= 2:
                inner = ft.params[1]
                if inner.name == resource_name:
                    return True
                if inner.name == "array" and inner.params:
                    if inner.params[0].name == resource_name:
                        return True
        return False

    def _struct_consumes_non_out(self, sname, resource_name):
        if sname not in self.structs:
            return False
        for f in self.structs[sname]:
            if f["direction"] == "out":
                continue
            ft = f["type_expr"]
            if ft.name == resource_name:
                return True
            if ft.name in ("ptr", "ptr64") and len(ft.params) >= 2:
                inner = ft.params[1]
                if inner.name == resource_name:
                    return True
                if inner.name == "array" and inner.params:
                    if inner.params[0].name == resource_name:
                        return True
        return False

    def _consumed_resources(self, syscall_name):
        consumed = set()
        sinfo = self.syscalls[syscall_name]
        for arg in sinfo["args"]:
            if arg["type_expr"].name in self.resources:
                consumed.add(arg["type_expr"].name)
            te = arg["type_expr"]
            if te.name in ("ptr", "ptr64") and len(te.params) >= 2:
                direction = te.params[0].name
                inner = te.params[1]
                if inner.name in self.structs:
                    for f in self.structs[inner.name]:
                        if direction == "out":
                            continue
                        if f["direction"] == "out" and direction == "inout":
                            continue
                        ft = f["type_expr"]
                        if ft.name in self.resources:
                            consumed.add(ft.name)
                        if ft.name in ("ptr", "ptr64") and len(ft.params) >= 2:
                            fi = ft.params[1]
                            if fi.name in self.resources:
                                consumed.add(fi.name)
                            if fi.name == "array" and fi.params:
                                if fi.params[0].name in self.resources:
                                    consumed.add(fi.params[0].name)
        return consumed

    # ── undefined flag refs ──────────────────────────────────────────

    def _find_undefined_flag_refs(self):
        results = []
        for sname, fields in self.structs.items():
            for f in fields:
                self._collect_undef_flags(f["type_expr"], sname, results)
        return results

    def _collect_undef_flags(self, te, context, results):
        if te.name == "flags" and te.params:
            fname = te.params[0].name
            if fname not in self.flags:
                results.append(
                    {"category": "flags", "name": fname, "referenced_by": context}
                )
        for p in te.params:
            self._collect_undef_flags(p, context, results)

    # ── invalid len refs ─────────────────────────────────────────────

    def _find_invalid_len_refs(self):
        results = []
        for sname, fields in self.structs.items():
            field_names = {f["name"] for f in fields}
            for f in fields:
                self._collect_invalid_len(
                    f["type_expr"], sname, f["name"], field_names, results
                )
        return results

    def _collect_invalid_len(self, te, sname, fname, field_names, results):
        if te.name in ("len", "bytesize", "bitsize") and te.params:
            ref = te.params[0].name
            if ref != "parent" and ":" not in ref and ref not in field_names:
                results.append(
                    {"struct": sname, "field": fname, "references": ref}
                )
        for p in te.params:
            self._collect_invalid_len(p, sname, fname, field_names, results)

    # ── unused flags ─────────────────────────────────────────────────

    def _find_unused_flags(self):
        used = set()
        for fields in self.structs.values():
            for f in fields:
                self._collect_flag_uses(f["type_expr"], used)
        for sinfo in self.syscalls.values():
            for arg in sinfo["args"]:
                self._collect_flag_uses(arg["type_expr"], used)
        return [f for f in self.flags if f not in used]

    def _collect_flag_uses(self, te, used):
        if te.name == "flags" and te.params:
            used.add(te.params[0].name)
        for p in te.params:
            self._collect_flag_uses(p, used)


def main():
    header_path = "/app/include/linux/hwaccel.h"
    include_dir = "/app/include"

    # Step 1: Extract constants from C headers using GCC
    extracted = extract_ioctl_constants(header_path, include_dir)

    # Step 2: Parse C struct definitions from header
    c_structs = parse_c_structs(header_path)

    # Step 3: Parse syzlang descriptions
    analyzer = SyzlangAnalyzer()
    analyzer.parse_directory("/app/descriptions")

    # Step 4: Analyze, cross-validate, and compute reachability
    report = analyzer.analyze(extracted_constants=extracted, c_structs=c_structs)

    # Step 5: Write report
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
