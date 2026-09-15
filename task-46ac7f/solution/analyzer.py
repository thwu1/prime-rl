#!/usr/bin/env python3
"""
GPU Uniform Block Layout Analyzer - Reference Implementation

Parses sokol-shdc annotated GLSL shader files and computes std140-compliant
memory layouts for all uniform block declarations.
"""

import json
import os
import re
import sys
import glob

# std140 alignment and size rules: (alignment_bytes, size_bytes)
STD140 = {
    "float": (4, 4),
    "int":   (4, 4),
    "vec2":  (8, 8),
    "ivec2": (8, 8),
    "vec3":  (16, 12),
    "ivec3": (16, 12),
    "vec4":  (16, 16),
    "ivec4": (16, 16),
    "mat4":  (16, 64),
}


def align_up(offset, alignment):
    return ((offset + alignment - 1) // alignment) * alignment


def member_layout_info(type_str):
    """Return (alignment, size, base_type, array_count) for a type string."""
    m = re.match(r"(\w+)\[(\d+)\]$", type_str)
    if m:
        base, count = m.group(1), int(m.group(2))
    else:
        base, count = type_str, 0
    if base not in STD140:
        return None
    base_align, base_size = STD140[base]
    if count > 0:
        element_stride = align_up(base_size, 16)
        return (16, element_stride * count, base, count)
    return (base_align, base_size, base, 0)


def compute_layout(members):
    """Compute std140 layout for a list of (name, type_str) tuples.

    Returns: (member_list, total_size, padding_bytes)
    """
    offset = 0
    result = []
    for name, type_str in members:
        info = member_layout_info(type_str)
        if info is None:
            continue
        alignment, size = info[0], info[1]
        offset = align_up(offset, alignment)
        result.append({
            "name": name,
            "type": type_str,
            "offset": offset,
            "size": size,
            "alignment": alignment,
        })
        offset += size
    total_size = align_up(offset, 16)
    data_size = sum(m["size"] for m in result)
    return result, total_size, total_size - data_size


def compute_optimized_size(members):
    """Compute minimum total block size achievable by reordering members.

    Strategy: place members in descending alignment order, packing one scalar
    into the 4-byte gap after each vec3/ivec3.
    """
    parsed = []
    for name, type_str in members:
        info = member_layout_info(type_str)
        if info is None:
            continue
        alignment, size, base, arr_count = info
        parsed.append((alignment, size, base, arr_count))

    # Group by type category
    mat4_arrays = [p for p in parsed if p[2] == "mat4" and p[3] > 0]
    mat4_singles = [p for p in parsed if p[2] == "mat4" and p[3] == 0]
    vec4_arrays = [p for p in parsed if p[2] in ("vec4", "ivec4") and p[3] > 0]
    vec4_singles = [p for p in parsed if p[2] in ("vec4", "ivec4") and p[3] == 0]
    vec3s = [p for p in parsed if p[2] in ("vec3", "ivec3")]
    vec2s = [p for p in parsed if p[2] in ("vec2", "ivec2")]
    scalars = [p for p in parsed if p[2] in ("float", "int")]

    # Build optimized ordering: largest alignment first, pack scalars after vec3s
    ordered = mat4_arrays + mat4_singles + vec4_arrays + vec4_singles
    scalar_idx = 0
    for v3 in vec3s:
        ordered.append(v3)
        if scalar_idx < len(scalars):
            ordered.append(scalars[scalar_idx])
            scalar_idx += 1
    ordered += vec2s
    ordered += scalars[scalar_idx:]

    # Compute layout for the optimized order
    offset = 0
    for alignment, size, _, _ in ordered:
        offset = align_up(offset, alignment)
        offset += size
    return align_up(offset, 16)


def parse_glsl_file(filepath):
    """Parse a sokol-shdc annotated GLSL file and extract uniform blocks."""
    with open(filepath) as f:
        content = f.read()

    blocks = []
    stage_map = {"vs": "vertex", "fs": "fragment", "cs": "compute"}

    # Match @vs/@fs/@cs blocks (non-greedy to handle multiple blocks)
    for stage_match in re.finditer(
        r"@(vs|fs|cs)\s+(\w+)(.*?)@end", content, re.DOTALL
    ):
        stage = stage_map[stage_match.group(1)]
        body = stage_match.group(3)

        # Find uniform block declarations (NOT buffer/storage blocks)
        for ub_match in re.finditer(
            r"layout\s*\(\s*binding\s*=\s*(\d+)\s*\)\s+uniform\s+(\w+)\s*\{([^}]*)\}",
            body,
        ):
            binding = int(ub_match.group(1))
            block_name = ub_match.group(2)
            block_body = ub_match.group(3)

            # Parse member declarations
            members = []
            for line in block_body.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                mm = re.match(r"(\w+)\s+(\w+)(?:\[(\d+)\])?\s*;", line)
                if mm and mm.group(1) in STD140:
                    type_name = mm.group(1)
                    member_name = mm.group(2)
                    arr_count = mm.group(3)
                    type_str = (
                        f"{type_name}[{arr_count}]" if arr_count else type_name
                    )
                    members.append((member_name, type_str))

            layout, total_size, padding = compute_layout(members)
            opt_size = compute_optimized_size(members)

            blocks.append({
                "block_name": block_name,
                "binding": binding,
                "stage": stage,
                "members": layout,
                "total_size": total_size,
                "padding_bytes": padding,
                "optimized_total_size": opt_size,
            })

    return blocks


def main():
    shader_dir = "/app/shaders"
    result = {"files": []}

    glsl_files = sorted(glob.glob(os.path.join(shader_dir, "*.glsl")))
    for filepath in glsl_files:
        filename = os.path.basename(filepath)
        blocks = parse_glsl_file(filepath)
        if blocks:
            result["files"].append({
                "filename": filename,
                "blocks": blocks,
            })

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
