// Multi-pass deferred renderer: shadow + main geometry passes
@block shared_types
struct LightData {
    vec4 position;
    vec4 color;
    float radius;
    float falloff;
};
@end

@vs vs_shadow
layout(binding=0) uniform shadow_params {
    mat4 light_view_proj;
    vec3 light_pos;
    float near_plane;
    float far_plane;
};

in vec4 position;

void main() {
    gl_Position = light_view_proj * position;
}
@end

@fs fs_shadow
out vec4 frag_color;

void main() {
    frag_color = vec4(gl_FragCoord.z, 0.0, 0.0, 1.0);
}
@end

@vs vs_main
layout(binding=0) uniform vs_main_params {
    mat4 view_proj;
    mat4 model;
    mat4 normal_matrix;
};

layout(binding=1) uniform vs_skinning {
    mat4 bones[4];
    int num_active_bones;
};

in vec4 position;
in vec3 normal;
in vec4 bone_weights;
in ivec4 bone_indices;
out vec3 v_normal;
out vec3 v_world_pos;

void main() {
    gl_Position = view_proj * model * position;
    v_normal = mat3(normal_matrix) * normal;
    v_world_pos = (model * position).xyz;
}
@end

@fs fs_main
@include_block shared_types

layout(binding=0) uniform fs_material {
    vec4 base_color;
    vec3 emissive;
    float metallic;
    float roughness;
    float ao;
    vec2 uv_transform;
};

layout(binding=1) uniform fs_lighting {
    vec4 lights_pos[4];
    vec4 lights_color[4];
    vec4 lights_params[4];
    vec3 ambient;
    int num_lights;
    mat4 shadow_vp;
    vec3 shadow_light_pos;
    float shadow_bias;
};

in vec3 v_normal;
in vec3 v_world_pos;
out vec4 frag_color;

void main() {
    frag_color = base_color;
}
@end

@program shadow vs_shadow fs_shadow
@program main_pass vs_main fs_main
