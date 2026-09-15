# Shader Cross-Compilation Pipeline Specification

## 1. Annotated GLSL Format

Input files use sokol-shdc's annotated GLSL format with `@`-tags:

- `@vs <name>` / `@end` — vertex shader block
- `@fs <name>` / `@end` — fragment shader block
- `@cs <name>` / `@end` — compute shader block
- `@block <name>` / `@end` — reusable code block (not a shader stage)
- `@include_block <name>` — insert a `@block`'s content into the current block
- `@program <name> <vs> <fs>` — define a render program (vertex + fragment)
- `@program <name> <cs>` — define a compute program

A `@program` with 3 arguments is a render program; with 2 arguments, compute.

The GLSL inside each block is Vulkan-flavored GLSL (version 450) using separate
texture and sampler objects (`uniform texture2D` + `uniform sampler`, combined
at the call site with `sampler2D(tex, smp)`).

## 2. Resource Declarations

Resources are declared with `layout(binding=N)`:

| Declaration Pattern | Resource Type |
|---|---|
| `layout(binding=N) uniform <block_name> { ... }` | Uniform Block |
| `layout(binding=N) readonly buffer <name> { ... }` | Storage Buffer (readonly) |
| `layout(binding=N) buffer <name> { ... }` | Storage Buffer (readwrite) |
| `layout(binding=N) uniform texture2D <name>` | Texture |
| `layout(binding=N) uniform textureCube <name>` | Texture |
| `layout(binding=N) uniform sampler <name>` | Sampler |

The `binding=N` value is the index into the sokol-gfx resource array for that
category. **Uniform blocks, views (textures + storage buffers), and samplers
occupy separate arrays** — so a uniform block with `binding=0` and a storage
buffer with `binding=0` do NOT conflict in the annotated format, but they
refer to different sokol-gfx array slots.

Readwrite storage buffers (`buffer` without `readonly`) may only appear in
compute shader blocks (`@cs`).

## 3. Pipeline Output

Usage: `python3 /app/pipeline.py <input.glsl> <output_dir>`

The pipeline must produce the following output structure:

```
<output_dir>/
  metadata.json
  <program_name>/
    <stage>.spv          — SPIR-V bytecode
    <stage>.metal        — Metal Shading Language source
    <stage>.hlsl         — HLSL (Shader Model 5.0) source
```

Where `<stage>` is `vs`, `fs`, or `cs`.

## 4. metadata.json Schema

```json
{
  "programs": {
    "<program_name>": {
      "type": "render" | "compute",
      "stages": ["vs", "fs"] | ["cs"],
      "stage_info": {
        "<stage>": {
          "entry_point": "main",
          "spirv_path": "<program_name>/<stage>.spv",
          "metal_path": "<program_name>/<stage>.metal",
          "hlsl_path": "<program_name>/<stage>.hlsl"
        }
      },
      "resources": {
        "uniform_blocks": [
          {"name": "<name>", "stage": "<vs|fs|cs>", "slot": <int>}
        ],
        "storage_buffers": [
          {"name": "<name>", "stage": "<vs|fs|cs>", "slot": <int>, "readonly": <bool>}
        ],
        "textures": [
          {"name": "<name>", "stage": "<vs|fs|cs>", "slot": <int>}
        ],
        "samplers": [
          {"name": "<name>", "stage": "<vs|fs|cs>", "slot": <int>}
        ]
      }
    }
  }
}
```

The `slot` field is the original `binding=N` value from the annotated GLSL source.

## 5. Available Tools

- `glslangValidator` — Khronos reference GLSL-to-SPIR-V compiler (at `/usr/bin/glslangValidator`)
- `spirv-cross` — SPIR-V to MSL/HLSL cross-compiler and reflection tool (at `/usr/local/bin/spirv-cross`)

## 6. Notes

- The annotated GLSL is NOT directly compilable by `glslangValidator`. It must
  be preprocessed to produce standalone Vulkan GLSL for each shader stage.
- A `@vs` or `@fs` block may be referenced by multiple `@program` definitions.
  Each program's cross-compilation is independent.
- Vertex shader outputs and fragment shader inputs must have matching interface
  qualifiers for the pipeline to produce valid cross-compiled code.
