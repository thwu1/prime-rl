#!/usr/bin/env python3
"""
SPIR-V shader cross-compilation and reflection pipeline for sokol-shdc annotated GLSL.

Converts annotated GLSL -> standalone Vulkan GLSL -> SPIR-V -> MSL + HLSL,
producing per-program cross-compiled sources and unified resource metadata.
"""

import sys
import os
import re
import json
import subprocess
import tempfile

GLSLANG = "glslangValidator"
SPIRV_CROSS = "spirv-cross"


def parse_annotated_glsl(source):
    """Parse sokol-shdc annotated GLSL into shader blocks and program definitions."""
    blocks = {}
    programs = []

    cur_name = None
    cur_stage = None
    cur_lines = []

    for line in source.split('\n'):
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


def expand_includes(code, all_blocks):
    """Expand @include_block directives by inserting referenced block code."""
    result = []
    for line in code.split('\n'):
        m = re.match(r'\s*@include_block\s+(\w+)', line)
        if m and m.group(1) in all_blocks:
            result.append(all_blocks[m.group(1)]["code"])
        else:
            result.append(line)
    return '\n'.join(result)


def extract_resources_from_source(code, stage):
    """Extract resource declarations from expanded shader source code."""
    resources = {
        "uniform_blocks": [],
        "storage_buffers": [],
        "textures": [],
        "samplers": []
    }

    # Uniform blocks: layout(binding=N) uniform <name> {
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+uniform\s+(?!texture|sampler)(\w+)\s*\{',
        code
    ):
        resources["uniform_blocks"].append({
            "name": m.group(2), "stage": stage, "slot": int(m.group(1))
        })

    # Readonly storage buffers
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+readonly\s+buffer\s+(\w+)\s*\{',
        code
    ):
        resources["storage_buffers"].append({
            "name": m.group(2), "stage": stage, "slot": int(m.group(1)),
            "readonly": True
        })

    # Readwrite storage buffers (buffer without preceding readonly)
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+buffer\s+(\w+)\s*\{',
        code
    ):
        prefix_start = max(0, m.start() - 40)
        prefix = code[prefix_start:m.start()]
        if 'readonly' not in prefix.split('\n')[-1]:
            resources["storage_buffers"].append({
                "name": m.group(2), "stage": stage, "slot": int(m.group(1)),
                "readonly": False
            })

    # Textures
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+uniform\s+texture\w+\s+(\w+)',
        code
    ):
        resources["textures"].append({
            "name": m.group(2), "stage": stage, "slot": int(m.group(1))
        })

    # Samplers
    for m in re.finditer(
        r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+uniform\s+sampler\s+(\w+)',
        code
    ):
        resources["samplers"].append({
            "name": m.group(2), "stage": stage, "slot": int(m.group(1))
        })

    return resources


def convert_to_vulkan_glsl(block_code, stage, all_blocks):
    """Convert an annotated GLSL block to standalone Vulkan GLSL.

    Key transformations:
    - Add #version 450
    - Expand @include_block directives
    - Remap layout(binding=N) to layout(set=S, binding=N):
        set=0 for uniform blocks
        set=1 for storage buffers and textures (views)
        set=2 for samplers
    - Add layout(location=N) to in/out variables (VS/FS only)
    """
    code = expand_includes(block_code, all_blocks)

    out_lines = ['#version 450', '']
    in_loc = 0
    out_loc = 0

    for line in code.split('\n'):
        s = line.strip()

        # Uniform blocks -> set=0
        m = re.match(
            r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+(uniform\s+(?!texture|sampler)\w+\s*\{)',
            s
        )
        if m:
            out_lines.append(f'layout(set=0, binding={m.group(1)}) {m.group(2)}')
            continue

        # Readonly storage buffers -> set=1
        m = re.match(
            r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+(readonly\s+buffer\s+\w+\s*\{)',
            s
        )
        if m:
            out_lines.append(f'layout(set=1, binding={m.group(1)}) {m.group(2)}')
            continue

        # Readwrite storage buffers -> set=1
        m = re.match(
            r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+(buffer\s+\w+\s*\{)',
            s
        )
        if m:
            out_lines.append(f'layout(set=1, binding={m.group(1)}) {m.group(2)}')
            continue

        # Textures -> set=1
        m = re.match(
            r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+(uniform\s+texture\w+\s+\w+)\s*;',
            s
        )
        if m:
            out_lines.append(f'layout(set=1, binding={m.group(1)}) {m.group(2)};')
            continue

        # Samplers -> set=2
        m = re.match(
            r'layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+(uniform\s+sampler\s+\w+)\s*;',
            s
        )
        if m:
            out_lines.append(f'layout(set=2, binding={m.group(1)}) {m.group(2)};')
            continue

        # I/O location qualifiers (VS and FS only, not CS)
        if stage in ('vs', 'fs'):
            # Input variable: in <type> <name>;
            m_in = re.match(
                r'in\s+((?:flat\s+|smooth\s+|noperspective\s+)?'
                r'(?:vec[234]|ivec[234]|uvec[234]|float|int|uint|'
                r'mat[234](?:x[234])?))\s+(\w+)\s*;',
                s
            )
            if m_in:
                out_lines.append(
                    f'layout(location={in_loc}) in {m_in.group(1)} {m_in.group(2)};'
                )
                in_loc += 1
                continue

            # Output variable: out <type> <name>;
            m_out = re.match(
                r'out\s+((?:flat\s+|smooth\s+|noperspective\s+)?'
                r'(?:vec[234]|ivec[234]|uvec[234]|float|int|uint|'
                r'mat[234](?:x[234])?))\s+(\w+)\s*;',
                s
            )
            if m_out:
                out_lines.append(
                    f'layout(location={out_loc}) out {m_out.group(1)} {m_out.group(2)};'
                )
                out_loc += 1
                continue

        out_lines.append(line)

    return '\n'.join(out_lines)


def compile_to_spirv(glsl_path, spv_path, stage):
    """Compile standalone Vulkan GLSL to SPIR-V using glslangValidator."""
    stage_flag = {"vs": "vert", "fs": "frag", "cs": "comp"}[stage]
    result = subprocess.run(
        [GLSLANG, "-V", "--target-env", "vulkan1.1",
         "-S", stage_flag, "-o", spv_path, glsl_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"glslangValidator failed for {glsl_path} (stage={stage}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def cross_compile_msl(spv_path, msl_path):
    """Cross-compile SPIR-V to Metal Shading Language."""
    result = subprocess.run(
        [SPIRV_CROSS, spv_path, "--msl", "--msl-version", "20100",
         "--output", msl_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"spirv-cross MSL failed for {spv_path}:\n{result.stderr}"
        )


def cross_compile_hlsl(spv_path, hlsl_path):
    """Cross-compile SPIR-V to HLSL (Shader Model 5.0)."""
    result = subprocess.run(
        [SPIRV_CROSS, spv_path, "--hlsl", "--shader-model", "50",
         "--output", hlsl_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"spirv-cross HLSL failed for {spv_path}:\n{result.stderr}"
        )


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.glsl> <output_dir>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_dir = sys.argv[2]

    with open(input_path) as f:
        source = f.read()

    blocks, programs = parse_annotated_glsl(source)
    os.makedirs(output_dir, exist_ok=True)

    metadata = {"programs": {}}

    for prog in programs:
        prog_dir = os.path.join(output_dir, prog["name"])
        os.makedirs(prog_dir, exist_ok=True)

        stages = []
        all_resources = {
            "uniform_blocks": [],
            "storage_buffers": [],
            "textures": [],
            "samplers": []
        }
        stage_info = {}

        if prog["type"] == "render":
            stage_blocks = [("vs", prog["vs"]), ("fs", prog["fs"])]
        else:
            stage_blocks = [("cs", prog["cs"])]

        for stage, block_name in stage_blocks:
            if block_name not in blocks:
                raise RuntimeError(f"Block '{block_name}' not found in source")

            block = blocks[block_name]
            stages.append(stage)

            # Extract resource metadata from original source
            expanded_code = expand_includes(block["code"], blocks)
            res = extract_resources_from_source(expanded_code, stage)
            for key in all_resources:
                all_resources[key].extend(res[key])

            # Convert to standalone Vulkan GLSL
            standalone_glsl = convert_to_vulkan_glsl(block["code"], stage, blocks)

            # Write standalone GLSL to temp file for compilation
            glsl_path = os.path.join(prog_dir, f"{stage}.glsl")
            with open(glsl_path, 'w') as f:
                f.write(standalone_glsl)

            # Compile to SPIR-V
            spv_path = os.path.join(prog_dir, f"{stage}.spv")
            compile_to_spirv(glsl_path, spv_path, stage)

            # Cross-compile to Metal Shading Language
            msl_path = os.path.join(prog_dir, f"{stage}.metal")
            cross_compile_msl(spv_path, msl_path)

            # Cross-compile to HLSL
            hlsl_path = os.path.join(prog_dir, f"{stage}.hlsl")
            cross_compile_hlsl(spv_path, hlsl_path)

            stage_info[stage] = {
                "entry_point": "main",
                "spirv_path": f"{prog['name']}/{stage}.spv",
                "metal_path": f"{prog['name']}/{stage}.metal",
                "hlsl_path": f"{prog['name']}/{stage}.hlsl"
            }

        metadata["programs"][prog["name"]] = {
            "type": prog["type"],
            "stages": stages,
            "stage_info": stage_info,
            "resources": all_resources
        }

    # Write metadata
    meta_path = os.path.join(output_dir, "metadata.json")
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"Pipeline complete: {len(programs)} programs processed -> {output_dir}")


if __name__ == '__main__':
    main()
