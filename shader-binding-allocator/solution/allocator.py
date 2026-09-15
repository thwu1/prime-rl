#!/usr/bin/env python3
"""
Cross-backend shader resource binding allocator for sokol-shdc annotated GLSL.

Parses annotated GLSL files, extracts resource declarations, and computes
backend-specific binding slot assignments for Metal, D3D11, and WebGPU/WGSL.
"""

import sys
import re
import json


def parse_blocks_and_programs(source):
    """Parse annotated GLSL source into shader blocks and program definitions."""
    blocks = {}  # name -> {"stage": "vs"|"fs"|"cs"|None, "code": str}
    programs = []  # [{"name": str, "type": "render"|"compute", vs/fs/cs: str}]

    lines = source.split('\n')
    cur_name = None
    cur_stage = None
    cur_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('#pragma sokol'):
            stripped = stripped[len('#pragma sokol'):].strip()

        m_vs = re.match(r'^@vs\s+(\w+)', stripped)
        m_fs = re.match(r'^@fs\s+(\w+)', stripped)
        m_cs = re.match(r'^@cs\s+(\w+)', stripped)
        m_bl = re.match(r'^@block\s+(\w+)', stripped)

        if m_vs:
            cur_name, cur_stage, cur_lines = m_vs.group(1), 'vs', []
            continue
        if m_fs:
            cur_name, cur_stage, cur_lines = m_fs.group(1), 'fs', []
            continue
        if m_cs:
            cur_name, cur_stage, cur_lines = m_cs.group(1), 'cs', []
            continue
        if m_bl:
            cur_name, cur_stage, cur_lines = m_bl.group(1), None, []
            continue

        if stripped == '@end' and cur_name is not None:
            blocks[cur_name] = {"stage": cur_stage, "code": '\n'.join(cur_lines)}
            cur_name = None
            continue

        m_prog = re.match(r'^@program\s+(\w+)\s+(\w+)(?:\s+(\w+))?', stripped)
        if m_prog:
            name, arg1, arg2 = m_prog.group(1), m_prog.group(2), m_prog.group(3)
            if arg2:
                programs.append({"name": name, "type": "render", "vs": arg1, "fs": arg2})
            else:
                programs.append({"name": name, "type": "compute", "cs": arg1})
            continue

        if cur_name is not None:
            cur_lines.append(line)

    return blocks, programs


def resolve_includes(blocks):
    """Expand @include_block directives in each block's code."""
    for block in blocks.values():
        if block["stage"] is None:
            continue
        resolved = []
        for line in block["code"].split('\n'):
            m = re.match(r'\s*@include_block\s+(\w+)', line)
            if m and m.group(1) in blocks:
                resolved.append(blocks[m.group(1)]["code"])
            else:
                resolved.append(line)
        block["code"] = '\n'.join(resolved)


def extract_resources(block):
    """Extract resource declarations from a shader block."""
    resources = []
    if block["stage"] is None:
        return resources

    code = block["code"]
    stage = block["stage"]

    # Uniform blocks: layout(binding=N) uniform <name> {
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+uniform\s+(?!texture|sampler)(\w+)\s*\{',
        code
    ):
        resources.append({
            "name": m.group(2), "resource_type": "uniform_block",
            "stage": stage, "slot": int(m.group(1))
        })

    # Readonly storage buffers: layout(binding=N) readonly buffer <name> {
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+readonly\s+buffer\s+(\w+)\s*\{',
        code
    ):
        resources.append({
            "name": m.group(2), "resource_type": "storage_buffer",
            "stage": stage, "slot": int(m.group(1)), "readonly": True
        })

    # Readwrite storage buffers: layout(binding=N) buffer <name> {
    # Avoid matching 'readonly buffer' by checking for 'readonly' before the match
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+buffer\s+(\w+)\s*\{',
        code
    ):
        # Verify this isn't part of a 'readonly buffer' match
        prefix_start = max(0, m.start() - 30)
        prefix = code[prefix_start:m.start()]
        if 'readonly' not in prefix.split('\n')[-1]:
            resources.append({
                "name": m.group(2), "resource_type": "storage_buffer",
                "stage": stage, "slot": int(m.group(1)), "readonly": False
            })

    # Textures: layout(binding=N) uniform texture2D|textureCube|texture3D <name>
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+uniform\s+texture\w+\s+(\w+)',
        code
    ):
        resources.append({
            "name": m.group(2), "resource_type": "texture",
            "stage": stage, "slot": int(m.group(1))
        })

    # Samplers: layout(binding=N) uniform sampler <name>
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+uniform\s+sampler\s+(\w+)',
        code
    ):
        resources.append({
            "name": m.group(2), "resource_type": "sampler",
            "stage": stage, "slot": int(m.group(1))
        })

    return resources


def collect_program_resources(program, blocks):
    """Collect all resources from all stages of a program."""
    resources = []
    stage_names = []
    if program["type"] == "render":
        stage_names = [program.get("vs"), program.get("fs")]
    else:
        stage_names = [program.get("cs")]

    for sname in stage_names:
        if sname and sname in blocks:
            resources.extend(extract_resources(blocks[sname]))
    return resources


def assign_metal(resources):
    """Assign Metal binding slots (per-stage)."""
    result = {}
    stages = sorted(set(r["stage"] for r in resources))

    for stage in stages:
        stage_res = [r for r in resources if r["stage"] == stage]
        ub_ctr = 0
        sb_ctr = 8
        tex_ctr = 0
        smp_ctr = 0

        for r in sorted(stage_res, key=lambda x: x["slot"]):
            if r["resource_type"] == "uniform_block":
                result[r["name"]] = {"buffer_n": ub_ctr}
                ub_ctr += 1

        for r in sorted(stage_res, key=lambda x: x["slot"]):
            if r["resource_type"] == "storage_buffer":
                result[r["name"]] = {"buffer_n": sb_ctr}
                sb_ctr += 1

        for r in sorted(stage_res, key=lambda x: x["slot"]):
            if r["resource_type"] == "texture":
                result[r["name"]] = {"texture_n": tex_ctr}
                tex_ctr += 1

        for r in sorted(stage_res, key=lambda x: x["slot"]):
            if r["resource_type"] == "sampler":
                result[r["name"]] = {"sampler_n": smp_ctr}
                smp_ctr += 1

    return result


def assign_d3d11(resources):
    """Assign D3D11/HLSL binding slots (per-stage)."""
    result = {}
    stages = sorted(set(r["stage"] for r in resources))

    for stage in stages:
        stage_res = [r for r in resources if r["stage"] == stage]
        b_ctr = 0
        t_ctr = 0
        u_ctr = 0
        s_ctr = 0

        for r in sorted(stage_res, key=lambda x: x["slot"]):
            if r["resource_type"] == "uniform_block":
                result[r["name"]] = {"register_b_n": b_ctr}
                b_ctr += 1

        # Shared t-register for readonly SBs + textures; u-register for readwrite SBs
        for r in sorted(stage_res, key=lambda x: x["slot"]):
            if r["resource_type"] == "storage_buffer":
                if r.get("readonly", True):
                    result[r["name"]] = {"register_t_n": t_ctr}
                    t_ctr += 1
                else:
                    result[r["name"]] = {"register_u_n": u_ctr}
                    u_ctr += 1
            elif r["resource_type"] == "texture":
                result[r["name"]] = {"register_t_n": t_ctr}
                t_ctr += 1

        for r in sorted(stage_res, key=lambda x: x["slot"]):
            if r["resource_type"] == "sampler":
                result[r["name"]] = {"register_s_n": s_ctr}
                s_ctr += 1

    return result


def assign_wgsl(resources):
    """Assign WGSL/WebGPU binding slots (cross-stage)."""
    result = {}
    g0_ctr = 0
    g1_ctr = 0

    # group(0) for uniform blocks, in slot order
    for r in sorted(
        [r for r in resources if r["resource_type"] == "uniform_block"],
        key=lambda x: x["slot"]
    ):
        result[r["name"]] = {"group0_binding_n": g0_ctr}
        g0_ctr += 1

    # group(1) for views (textures + storage buffers) then samplers, in slot order
    for r in sorted(
        [r for r in resources if r["resource_type"] in ("storage_buffer", "texture")],
        key=lambda x: x["slot"]
    ):
        result[r["name"]] = {"group1_binding_n": g1_ctr}
        g1_ctr += 1

    for r in sorted(
        [r for r in resources if r["resource_type"] == "sampler"],
        key=lambda x: x["slot"]
    ):
        result[r["name"]] = {"group1_binding_n": g1_ctr}
        g1_ctr += 1

    return result


def build_output(programs, blocks):
    """Build the complete output JSON."""
    output = {"programs": {}}

    for prog in programs:
        resources = collect_program_resources(prog, blocks)
        metal = assign_metal(resources)
        d3d11 = assign_d3d11(resources)
        wgsl = assign_wgsl(resources)

        prog_out = {
            "type": prog["type"],
            "uniform_blocks": {},
            "views": {},
            "samplers": {}
        }

        for r in resources:
            entry = {
                "stage": r["stage"],
                "slot": r["slot"],
                "metal": metal.get(r["name"], {}),
                "d3d11": d3d11.get(r["name"], {}),
                "wgsl": wgsl.get(r["name"], {})
            }

            if r["resource_type"] == "uniform_block":
                prog_out["uniform_blocks"][r["name"]] = entry
            elif r["resource_type"] == "storage_buffer":
                entry["type"] = "storage_buffer"
                entry["readonly"] = r.get("readonly", True)
                prog_out["views"][r["name"]] = entry
            elif r["resource_type"] == "texture":
                entry["type"] = "texture"
                prog_out["views"][r["name"]] = entry
            elif r["resource_type"] == "sampler":
                prog_out["samplers"][r["name"]] = entry

        output["programs"][prog["name"]] = prog_out

    return output


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.glsl> <output.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    blocks, programs = parse_blocks_and_programs(source)
    resolve_includes(blocks)
    output = build_output(programs, blocks)

    with open(sys.argv[2], 'w') as f:
        json.dump(output, f, indent=2)


if __name__ == '__main__':
    main()
