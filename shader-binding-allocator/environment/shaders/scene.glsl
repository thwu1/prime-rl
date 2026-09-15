// Multi-program scene rendering with PBR materials and GPU frustum culling
// Demonstrates shared vertex shaders, multiple fragment shader variants,
// and compute-based indirect draw generation

@block material_types
struct material_t {
    vec4 base_color;
    vec4 emissive;
    float metallic;
    float roughness;
};
@end

@vs vs_scene
layout(binding=0) uniform vs_uniforms {
    mat4 view_proj;
    mat4 model;
    mat4 normal_matrix;
};

in vec4 position;
in vec3 normal;
in vec2 texcoord;

out vec3 v_normal;
out vec2 v_uv;
out vec3 v_world_pos;

void main() {
    vec4 world_pos = model * position;
    gl_Position = view_proj * world_pos;
    v_normal = mat3(normal_matrix) * normal;
    v_uv = texcoord;
    v_world_pos = world_pos.xyz;
}
@end

@fs fs_textured
@include_block material_types

layout(binding=1) uniform fs_material {
    material_t material;
};

layout(binding=0) uniform texture2D albedo_tex;
layout(binding=1) uniform texture2D metallic_roughness_tex;
layout(binding=2) uniform texture2D emissive_tex;
layout(binding=0) uniform sampler material_smp;
layout(binding=1) uniform sampler emissive_smp;

in vec3 v_normal;
in vec2 v_uv;
in vec3 v_world_pos;
out vec4 frag_color;

void main() {
    vec4 albedo = texture(sampler2D(albedo_tex, material_smp), v_uv);
    vec2 mr = texture(sampler2D(metallic_roughness_tex, material_smp), v_uv).rg;
    vec4 emissive = texture(sampler2D(emissive_tex, emissive_smp), v_uv);
    frag_color = albedo * material.base_color + emissive * material.emissive;
}
@end

@fs fs_flat_color
@include_block material_types

layout(binding=1) uniform fs_flat_material {
    material_t material;
};

layout(binding=0) readonly buffer ssbo_color_table {
    vec4 color_table[];
};

in vec3 v_normal;
in vec2 v_uv;
in vec3 v_world_pos;
out vec4 frag_color;

void main() {
    int idx = int(v_uv.x * 255.0);
    vec4 table_color = color_table[idx];
    frag_color = table_color * material.base_color;
}
@end

@cs cs_frustum_cull
layout(binding=0) uniform cull_params {
    mat4 view_proj;
    vec4 frustum_planes[6];
    int num_objects;
};

struct aabb_t {
    vec4 min_pt;
    vec4 max_pt;
};

struct draw_cmd_t {
    int index_count;
    int instance_count;
    int first_index;
    int base_vertex;
    int first_instance;
};

layout(binding=0) readonly buffer ssbo_aabbs {
    aabb_t aabbs[];
};

layout(binding=1) buffer ssbo_draw_cmds {
    draw_cmd_t draw_cmds[];
};

layout(binding=2) buffer ssbo_visible_count {
    int visible_count;
};

layout(local_size_x=256, local_size_y=1, local_size_z=1) in;

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= num_objects) return;

    aabb_t aabb = aabbs[idx];
    bool visible = true;

    for (int i = 0; i < 6; i++) {
        vec4 plane = frustum_planes[i];
        vec4 positive_vertex = mix(aabb.min_pt, aabb.max_pt,
            step(vec4(0.0), plane));
        if (dot(plane, positive_vertex) < 0.0) {
            visible = false;
            break;
        }
    }

    if (visible) {
        int out_idx = atomicAdd(visible_count, 1);
        draw_cmds[out_idx] = draw_cmd_t(
            draw_cmds[idx].index_count,
            1,
            draw_cmds[idx].first_index,
            draw_cmds[idx].base_vertex,
            0
        );
    }
}
@end

@program scene_textured vs_scene fs_textured
@program scene_flat vs_scene fs_flat_color
@program frustum_cull cs_frustum_cull
