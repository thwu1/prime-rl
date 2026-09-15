A SPIR-V assembly compute shader at `/app/shaders/particle_update.spvasm` contains multiple validation errors preventing Vulkan 1.0 environment validation. A GLSL 450 fragment shader is at `/app/shaders/postprocess.frag`. Platform deployment profiles with weighted scoring criteria are defined in `/app/platform_profiles.json`.

Fix the compute shader's validation errors, then architect and comparatively evaluate at least 4 distinct `spirv-opt` optimization strategies for the corrected module. Each strategy must use a different combination of optimization passes and produce a measurably different outcome across the metrics defined in the platform profiles. Implement the weighted normalized scoring method specified in `/app/platform_profiles.json` to rank all strategies per deployment target, determine which strategy is optimal for each platform, and produce the platform-specific optimized binaries with cross-compiled shader outputs.

Write all outputs to `/app/output/`:
- `particle_update_fixed.spvasm` — corrected SPIR-V assembly
- `particle_update.spv` — assembled binary (must pass `spirv-val --target-env vulkan1.0`)
- `evaluation_report.json` — JSON with `strategies` array (each: `name`, `passes` array of spirv-opt CLI flags, `metrics` object with `binary_size`/`instruction_count`/`id_count`) and `platform_recommendations` object keyed by profile name (each: `recommended_strategy`, `weighted_score`, `all_scores` mapping every strategy name to its score, `justification`)
- `mobile_vulkan.spv` + `mobile_vulkan.glsl` — binary optimized with mobile profile's recommended strategy, cross-compiled to GLSL 310 ES
- `desktop_vulkan.spv` + `desktop_vulkan.glsl` — binary optimized with desktop profile's recommended strategy, cross-compiled to GLSL 450 with Vulkan semantics
- `console_metal.spv` + `console_metal.msl` — binary optimized with console profile's recommended strategy, cross-compiled to MSL
- `postprocess.spv` — compiled fragment shader binary
- `postprocess_es.glsl` — fragment shader cross-compiled to GLSL 310 ES

Reported metrics must be reproducible by re-running `spirv-opt` with the listed passes on `particle_update.spv`. Platform recommendations must select the strategy with the lowest weighted score under each profile's criteria. The desktop GLSL 450 output must survive round-trip re-compilation to valid SPIR-V.