# Cross-Backend Shader Resource Binding Rules

This document describes the resource binding model used by sokol-gfx and the
backend-specific slot assignment rules that a binding allocator must implement.

## 1. Annotated GLSL Format

Shader source files use sokol-shdc's annotated GLSL format with `@` tags:

- `@vs <name>` / `@end` — vertex shader block
- `@fs <name>` / `@end` — fragment shader block
- `@cs <name>` / `@end` — compute shader block
- `@block <name>` / `@end` — reusable code block (no stage)
- `@include_block <name>` — insert a `@block`'s code into current block
- `@program <name> <vs> <fs>` — define a render program (vertex + fragment)
- `@program <name> <cs>` — define a compute program

A `@program` with 3 arguments is a render program; with 2 arguments, compute.

## 2. Resource Types

Resources are declared inside shader blocks with `layout(binding=N)`:

| Declaration Pattern | Resource Type | Binding Array |
|---|---|---|
| `layout(binding=N) uniform <block_name> { ... }` | Uniform Block | `uniform_blocks[N]` |
| `layout(binding=N) readonly buffer <name> { ... }` | Storage Buffer (readonly) | `views[N]` |
| `layout(binding=N) buffer <name> { ... }` | Storage Buffer (readwrite) | `views[N]` |
| `layout(binding=N) uniform texture2D <name>` | Texture | `views[N]` |
| `layout(binding=N) uniform textureCube <name>` | Texture | `views[N]` |
| `layout(binding=N) uniform sampler <name>` | Sampler | `samplers[N]` |

**Key:** Textures and storage buffers share the `views[]` array. They must have
different binding slot numbers even if they are in different shader stages.

Each resource is associated with the stage (`vs`, `fs`, or `cs`) of the block
it is declared in. The `binding=N` value is the index into the flat
sokol-gfx array (`uniform_blocks[N]`, `views[N]`, or `samplers[N]`).

## 3. Backend Binding Assignment

For each program, the allocator must assign backend-specific slot numbers.
Resources are processed in order of their sokol-gfx slot number (the `N` in
`layout(binding=N)`). Backend-specific counters track the next available slot.

### 3.1 Metal

Metal uses **per-stage** slot assignment. Each shader stage has independent
slot spaces:

| Resource | Metal Field | Slot Range | Namespace |
|---|---|---|---|
| Uniform Block | `msl_buffer_n` | 0–7 | Buffer slots (per-stage) |
| Storage Buffer | `msl_buffer_n` | 8–15 | Buffer slots (per-stage) |
| Texture | `msl_texture_n` | 0–31 | Texture slots (per-stage) |
| Sampler | `msl_sampler_n` | 0–15 | Sampler slots (per-stage) |

**Collision rules (per-stage):**
- Uniform blocks and storage buffers occupy the same "buffer" slot space
  but use non-overlapping ranges (UBs: 0–7, SBs: 8–15), so they do not
  collide by convention.
- Texture slots must be unique among textures within the same stage.
- Sampler slots must be unique among samplers within the same stage.

**Assignment:** Within each stage, assign sequential values starting from the
base of each range. Process resources in ascending slot order.

### 3.2 D3D11 / HLSL

D3D11 uses **per-stage** slot assignment with four register types:

| Resource | D3D11 Field | Register | Namespace |
|---|---|---|---|
| Uniform Block | `hlsl_register_b_n` | `register(bN)` | Constant buffers (per-stage) |
| Readonly Storage Buffer | `hlsl_register_t_n` | `register(tN)` | Shader Resource Views (per-stage) |
| Texture | `hlsl_register_t_n` | `register(tN)` | Shader Resource Views (per-stage) |
| Readwrite Storage Buffer | `hlsl_register_u_n` | `register(uN)` | Unordered Access Views (per-stage) |
| Sampler | `hlsl_register_s_n` | `register(sN)` | Samplers (per-stage) |

**Collision rules (per-stage):**
- Readonly storage buffers and textures **share the `register(tN)` space**.
  They must have unique `t` register values within the same stage.
- Readwrite storage buffers use the separate `register(uN)` space.
- Constant buffers (`b`), samplers (`s`) each have their own space.

**Assignment:** Within each stage, assign sequential values starting from 0
for each register type. For the shared `t` register, process all views
(readonly SBs and textures) together in ascending slot order.

### 3.3 WebGPU / WGSL

WGSL uses **cross-stage** slot assignment. All stages share the same binding
spaces:

| Resource | WGSL Field | Bind Group | Namespace |
|---|---|---|---|
| Uniform Block | `wgsl_group0_binding_n` | `@group(0)` | UB bindings (0–15, cross-stage) |
| Storage Buffer | `wgsl_group1_binding_n` | `@group(1)` | View+sampler bindings (0–127, cross-stage) |
| Texture | `wgsl_group1_binding_n` | `@group(1)` | View+sampler bindings (0–127, cross-stage) |
| Sampler | `wgsl_group1_binding_n` | `@group(1)` | View+sampler bindings (0–127, cross-stage) |

**Collision rules (cross-stage):**
- All uniform blocks across all stages must have unique `@group(0)` bindings.
- All views (textures, storage buffers) AND all samplers across all stages
  share `@group(1)` and must have unique bindings within it.

**Assignment:** Assign sequential values globally. First assign `group(0)`
bindings to all uniform blocks (in slot order). Then assign `group(1)`
bindings to all views (in slot order), followed by all samplers (in slot
order).

## 4. Constraints

- **Render pipelines:** All storage buffer bindings in vertex and fragment
  shaders must be `readonly`. Only compute shaders may use readwrite
  (`buffer` without `readonly`) storage buffers.
- **Compute programs:** A `@program` with a single `@cs` reference is a
  compute program. It may use readwrite storage buffers.
- **Shared stages:** A `@vs` or `@fs` block may be referenced by multiple
  `@program` definitions. Each program is processed independently — the
  same shader block may produce different backend-specific bindings in
  different programs depending on the combined resource set.

## 5. Output Format

The allocator must output a JSON file with the following structure:

```json
{
  "programs": {
    "<program_name>": {
      "type": "render" | "compute",
      "uniform_blocks": {
        "<ub_name>": {
          "stage": "vs" | "fs" | "cs",
          "slot": <int>,
          "metal": { "buffer_n": <int> },
          "d3d11": { "register_b_n": <int> },
          "wgsl": { "group0_binding_n": <int> }
        }
      },
      "views": {
        "<view_name>": {
          "type": "storage_buffer" | "texture",
          "readonly": <bool>,
          "stage": "vs" | "fs" | "cs",
          "slot": <int>,
          "metal": { "buffer_n": <int> } | { "texture_n": <int> },
          "d3d11": { "register_t_n": <int> } | { "register_u_n": <int> },
          "wgsl": { "group1_binding_n": <int> }
        }
      },
      "samplers": {
        "<sampler_name>": {
          "stage": "vs" | "fs" | "cs",
          "slot": <int>,
          "metal": { "sampler_n": <int> },
          "d3d11": { "register_s_n": <int> },
          "wgsl": { "group1_binding_n": <int> }
        }
      }
    }
  }
}
```

Notes:
- Storage buffer views use `metal.buffer_n`; texture views use `metal.texture_n`.
- Readonly storage buffers use `d3d11.register_t_n`; readwrite use `d3d11.register_u_n`.
- The `readonly` field is only present on storage buffer views.
- Texture views do not have a `readonly` field.
