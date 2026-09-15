# Shader Analysis Report Specification

## Input Format

Input `.glsl` files in `/app/shaders/` use sokol-shdc annotation tags:

- `@vs <name>` / `@fs <name>` / `@cs <name>`: Start a vertex/fragment/compute shader stage
- `@end`: End the current block
- `@block <name>`: Define a reusable code block (not a shader stage)
- `@include_block <name>`: Include a named code block into the current stage
- `@program <name> <stage1> [stage2]`: Link stages into a named program

Code blocks defined with `@block` are inlined wherever referenced by `@include_block`. A stage that uses `@include_block` cannot compile unless the referenced block content is substituted into it.

## Output JSON Schema

Write a JSON report to stdout with this structure:

```json
{
  "files": [
    {
      "filename": "example.glsl",
      "stages": [
        {
          "name": "stage_name",
          "type": "vertex|fragment|compute",
          "compiled": true,
          "validated": true,
          "uniform_blocks": [
            {
              "block_name": "block_name",
              "binding": 0,
              "members": [
                {
                  "name": "member_name",
                  "type": "vec4",
                  "spirv_offset": 0,
                  "computed_offset": 0,
                  "size": 16,
                  "alignment": 16,
                  "offset_match": true
                }
              ],
              "total_size": 16,
              "padding_bytes": 0,
              "optimized_size": 16,
              "all_offsets_match": true
            }
          ]
        }
      ],
      "programs": [
        {"name": "program_name", "stages": ["vs_name", "fs_name"]}
      ]
    }
  ]
}
```

## Field Definitions

- **type**: `"vertex"`, `"fragment"`, or `"compute"`
- **compiled**: whether the stage successfully compiles to valid SPIR-V
- **validated**: whether the compiled SPIR-V passes validation
- **spirv_offset**: the byte offset assigned to this member by the SPIR-V compiler
- **computed_offset**: the byte offset independently computed by applying std140 layout rules to the GLSL source type declarations
- **size**: size in bytes of this member according to std140 rules
- **alignment**: alignment requirement in bytes of this member according to std140 rules
- **offset_match**: `spirv_offset == computed_offset`
- **all_offsets_match**: true if every member in the block has `offset_match == true`
- **total_size**: total block size in bytes (rounded up to next 16-byte multiple)
- **padding_bytes**: `total_size - sum(member sizes)`
- **optimized_size**: minimum achievable `total_size` by reordering members while preserving std140 compliance. A scalar (`float`/`int`, 4 bytes) can pack into the 4-byte gap after a `vec3`/`ivec3` member (which occupies 12 of its 16-byte aligned slot).
- **binding**: the binding number from the `layout(binding=N)` declaration

## std140 Layout Rules

### Base Alignment and Size (bytes)

| GLSL Type | Alignment | Size |
|-----------|-----------|------|
| float     | 4         | 4    |
| int       | 4         | 4    |
| vec2      | 8         | 8    |
| ivec2     | 8         | 8    |
| vec3      | 16        | 12   |
| ivec3     | 16        | 12   |
| vec4      | 16        | 16   |
| ivec4     | 16        | 16   |
| mat4      | 16        | 64   |

Each member is placed at the next offset that is a multiple of its alignment.

### Arrays

- Array element stride is the element size rounded up to 16 bytes
- Array alignment is 16 bytes
- Supported array element types: `vec4`, `ivec4`, `mat4`

### Block Size

Total block size is rounded up to the next 16-byte multiple.

## Constraints

- Only `layout(binding=N) uniform` blocks are analyzed as uniform blocks. Storage buffer declarations (`buffer` keyword) must be excluded from uniform block analysis.
- Files sorted alphabetically by filename
- Stages appear in source order within each file
- Members appear in declared order within each block
- Uniform blocks appear in source order within each stage
