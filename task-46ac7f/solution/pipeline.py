#!/usr/bin/env python3
"""
SPIR-V Shader Compilation and Reflection Pipeline
Processes sokol-shdc annotated GLSL, compiles to SPIR-V, validates,
extracts reflection data, and cross-validates against std140 layouts.
"""

import json
import os
import re
import subprocess
import sys
import glob
import tempfile

STD140 = {
    "float": (4, 4), "int": (4, 4),
    "vec2": (8, 8), "ivec2": (8, 8),
    "vec3": (16, 12), "ivec3": (16, 12),
    "vec4": (16, 16), "ivec4": (16, 16),
    "mat4": (16, 64),
}


def align_up(v, a):
    return ((v + a - 1) // a) * a


def member_layout_info(type_str):
    m = re.match(r"(\w+)\[(\d+)\]$", type_str)
    if m:
        base, count = m.group(1), int(m.group(2))
    else:
        base, count = type_str, 0
    if base not in STD140:
        return None
    ba, bs = STD140[base]
    if count > 0:
        stride = align_up(bs, 16)
        return (16, stride * count, base, count)
    return (ba, bs, base, 0)


def compute_std140_layout(members):
    offset = 0
    result = []
    for name, type_str in members:
        info = member_layout_info(type_str)
        if info is None:
            continue
        alignment, size = info[0], info[1]
        offset = align_up(offset, alignment)
        result.append({
            "name": name, "type": type_str,
            "computed_offset": offset, "size": size, "alignment": alignment,
        })
        offset += size
    total = align_up(offset, 16)
    data = sum(m["size"] for m in result)
    return result, total, total - data


def compute_optimized_size(members):
    parsed = []
    for name, type_str in members:
        info = member_layout_info(type_str)
        if info is None:
            continue
        parsed.append(info)
    mat4a = [p for p in parsed if p[2] == "mat4" and p[3] > 0]
    mat4s = [p for p in parsed if p[2] == "mat4" and p[3] == 0]
    v4a = [p for p in parsed if p[2] in ("vec4", "ivec4") and p[3] > 0]
    v4s = [p for p in parsed if p[2] in ("vec4", "ivec4") and p[3] == 0]
    v3 = [p for p in parsed if p[2] in ("vec3", "ivec3")]
    v2 = [p for p in parsed if p[2] in ("vec2", "ivec2")]
    sc = [p for p in parsed if p[2] in ("float", "int")]
    ordered = mat4a + mat4s + v4a + v4s
    si = 0
    for v in v3:
        ordered.append(v)
        if si < len(sc):
            ordered.append(sc[si])
            si += 1
    ordered += v2 + sc[si:]
    off = 0
    for a, s, _, _ in ordered:
        off = align_up(off, a)
        off += s
    return align_up(off, 16)


# --- Annotation Parser ---

def parse_annotations(content):
    code_blocks = {}
    for m in re.finditer(r'@block\s+(\w+)(.*?)@end', content, re.DOTALL):
        code_blocks[m.group(1)] = m.group(2)

    stage_map = {'vs': 'vertex', 'fs': 'fragment', 'cs': 'compute'}
    stages = []
    for m in re.finditer(r'@(vs|fs|cs)\s+(\w+)(.*?)@end', content, re.DOTALL):
        st = m.group(1)
        name = m.group(2)
        code = m.group(3)

        def resolve(c, depth=0):
            if depth > 10:
                return c
            def repl(mm):
                return code_blocks.get(mm.group(1), '')
            return re.sub(r'@include_block\s+(\w+)', repl, c)

        code = resolve(code)
        stages.append((name, stage_map[st], st, code))

    programs = []
    for m in re.finditer(r'@program\s+(\w+)\s+(.+)', content):
        programs.append((m.group(1), m.group(2).strip().split()))

    return stages, programs


def parse_uniform_blocks_from_glsl(code):
    blocks = []
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+uniform\s+(\w+)\s*\{([^}]*)\}',
        code,
    ):
        binding = int(m.group(1))
        bname = m.group(2)
        body = m.group(3)
        members = []
        for line in body.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            mm = re.match(r'(\w+)\s+(\w+)(?:\[(\d+)\])?\s*;', line)
            if mm and mm.group(1) in STD140:
                t = mm.group(1)
                n = mm.group(2)
                ac = mm.group(3)
                ts = f"{t}[{ac}]" if ac else t
                members.append((n, ts))
        blocks.append((bname, binding, members))
    return blocks


# --- SPIR-V Tools ---

def compile_spirv(glsl_src, stage_short, sname, tmpdir):
    smap = {'vs': 'vert', 'fs': 'frag', 'cs': 'comp'}
    sf = smap[stage_short]
    inp = os.path.join(tmpdir, f"{sname}.{sf}.glsl")
    outp = os.path.join(tmpdir, f"{sname}.{sf}.spv")
    with open(inp, 'w') as f:
        f.write(glsl_src)
    r = subprocess.run(
        ['glslangValidator', '-V', '-S', sf,
         '--auto-map-locations', '--auto-map-bindings',
         '-o', outp, inp],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None, r.stderr
    return outp, None


def validate_spirv(spv):
    r = subprocess.run(['spirv-val', spv], capture_output=True, text=True)
    return r.returncode == 0


def disassemble_spirv(spv):
    r = subprocess.run(['spirv-dis', spv], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def parse_spirv_for_ubo_offsets(disasm):
    """Extract uniform block member offsets from SPIR-V disassembly."""
    names = {}
    for m in re.finditer(r'OpName\s+(%\w+)\s+"([^"]*)"', disasm):
        names[m.group(1)] = m.group(2)

    mnames = {}
    for m in re.finditer(r'OpMemberName\s+(%\w+)\s+(\d+)\s+"([^"]*)"', disasm):
        mnames[(m.group(1), int(m.group(2)))] = m.group(3)

    block_ids = set()
    bufblock_ids = set()
    bindings = {}
    moffsets = {}

    for m in re.finditer(r'OpDecorate\s+(%\w+)\s+Block\b', disasm):
        block_ids.add(m.group(1))
    for m in re.finditer(r'OpDecorate\s+(%\w+)\s+BufferBlock\b', disasm):
        bufblock_ids.add(m.group(1))
    for m in re.finditer(r'OpDecorate\s+(%\w+)\s+Binding\s+(\d+)', disasm):
        bindings[m.group(1)] = int(m.group(2))
    for m in re.finditer(
        r'OpMemberDecorate\s+(%\w+)\s+(\d+)\s+Offset\s+(\d+)', disasm
    ):
        moffsets[(m.group(1), int(m.group(2)))] = int(m.group(3))

    ptrs = {}
    for m in re.finditer(r'(%\w+)\s*=\s*OpTypePointer\s+(\w+)\s+(%\w+)', disasm):
        ptrs[m.group(1)] = (m.group(2), m.group(3))

    variables = {}
    for m in re.finditer(r'(%\w+)\s*=\s*OpVariable\s+(%\w+)\s+(\w+)', disasm):
        variables[m.group(1)] = (m.group(2), m.group(3))

    ubos = []
    for var_id, (ptr_type, storage_class) in variables.items():
        if storage_class == 'StorageBuffer':
            continue
        if storage_class != 'Uniform':
            continue
        if ptr_type not in ptrs:
            continue
        _, struct_type = ptrs[ptr_type]
        if struct_type not in block_ids:
            continue
        if struct_type in bufblock_ids:
            continue

        bname = names.get(struct_type, "")
        binding = bindings.get(var_id, -1)

        members = []
        idx = 0
        while (struct_type, idx) in moffsets or (struct_type, idx) in mnames:
            mn = mnames.get((struct_type, idx), f"_m{idx}")
            mo = moffsets.get((struct_type, idx), -1)
            members.append({"name": mn, "spirv_offset": mo})
            idx += 1

        if members:
            ubos.append({
                "block_name": bname, "binding": binding, "members": members
            })

    return ubos


# --- Pipeline ---

def process_file(filepath):
    with open(filepath) as f:
        content = f.read()

    stages_info, programs = parse_annotations(content)

    result_stages = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for sname, stype, sshort, code in stages_info:
            glsl = "#version 450\n" + code

            spv_path, err = compile_spirv(glsl, sshort, sname, tmpdir)
            compiled = spv_path is not None
            validated = False
            spirv_ubos = []

            if compiled:
                validated = validate_spirv(spv_path)
                disasm = disassemble_spirv(spv_path)
                if disasm:
                    spirv_ubos = parse_spirv_for_ubo_offsets(disasm)

            glsl_blocks = parse_uniform_blocks_from_glsl(code)

            ub_results = []
            for bname, binding, members in glsl_blocks:
                layout, total, padding = compute_std140_layout(members)
                opt = compute_optimized_size(members)

                spirv_match = None
                for su in spirv_ubos:
                    if su["block_name"] == bname:
                        spirv_match = su
                        break

                merged = []
                for i, m in enumerate(layout):
                    entry = dict(m)
                    if spirv_match and i < len(spirv_match["members"]):
                        sm = spirv_match["members"][i]
                        entry["spirv_offset"] = sm["spirv_offset"]
                        entry["offset_match"] = (
                            sm["spirv_offset"] == m["computed_offset"]
                        )
                    else:
                        entry["spirv_offset"] = m["computed_offset"]
                        entry["offset_match"] = True
                    merged.append(entry)

                all_match = all(m["offset_match"] for m in merged)

                ub_results.append({
                    "block_name": bname,
                    "binding": binding,
                    "members": merged,
                    "total_size": total,
                    "padding_bytes": padding,
                    "optimized_size": opt,
                    "all_offsets_match": all_match,
                })

            result_stages.append({
                "name": sname,
                "type": stype,
                "compiled": compiled,
                "validated": validated,
                "uniform_blocks": ub_results,
            })

    prog_results = [{"name": pn, "stages": sn} for pn, sn in programs]

    return {
        "filename": os.path.basename(filepath),
        "stages": result_stages,
        "programs": prog_results,
    }


def main():
    shader_dir = "/app/shaders"
    files = sorted(glob.glob(os.path.join(shader_dir, "*.glsl")))
    result = {"files": [process_file(f) for f in files]}
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
