Build a SPIR-V shader cross-compilation and resource reflection pipeline at `/app/pipeline.py`.

The tool processes sokol-shdc annotated GLSL shader files containing `@vs`, `@fs`, `@cs`, `@block`, `@include_block`, and `@program` tags. It must convert each shader stage to standalone Vulkan GLSL suitable for `glslangValidator`, compile to SPIR-V, cross-compile to Metal Shading Language and HLSL via `spirv-cross`, and produce structured resource reflection metadata.

The annotated GLSL binding numbers (`layout(binding=N)`) index into separate per-category arrays (uniform blocks, views, samplers) and are NOT directly usable as Vulkan descriptor bindings without remapping. The pipeline must resolve this to produce compilable Vulkan GLSL, including correct I/O location qualifiers for cross-stage interface matching.

Input shaders are at `/app/shaders/`. Format specification and output schema are at `/app/docs/pipeline_spec.md`. Backend-specific resource binding rules are at `/app/docs/binding_rules.md`. The tools `glslangValidator` and `spirv-cross` are pre-installed.

Usage: `python3 /app/pipeline.py <input.glsl> <output_dir>`