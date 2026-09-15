// Forward lighting shader with fog
@block fog_util
vec3 apply_fog(vec3 color, float density, float start, float dist) {
    float ff = exp(-density * max(dist - start, 0.0));
    return mix(vec3(0.5, 0.5, 0.6), color, ff);
}
@end

@vs vs_lit
layout(binding=0) uniform vs_uniforms {
    mat4 view_proj;
    mat4 model;
    vec3 eye_pos;
};

in vec4 position;
in vec3 normal;
out vec3 v_normal;
out vec3 v_eye_dir;
out float v_dist;

void main() {
    vec4 world_pos = model * position;
    gl_Position = view_proj * world_pos;
    v_normal = normal;
    v_eye_dir = eye_pos - world_pos.xyz;
    v_dist = length(v_eye_dir);
}
@end

@fs fs_lit
@include_block fog_util

layout(binding=0) uniform fs_uniforms {
    vec3 light_dir;
    float light_intensity;
    vec3 light_color;
    float ambient_strength;
    vec3 ambient_color;
    float specular_power;
    vec4 fog_color;
    float fog_density;
    float fog_start;
    vec2 uv_scale;
};

in vec3 v_normal;
in vec3 v_eye_dir;
in float v_dist;
out vec4 frag_color;

void main() {
    float NdotL = max(dot(normalize(v_normal), normalize(light_dir)), 0.0);
    vec3 diffuse = light_color * NdotL * light_intensity;
    vec3 ambient = ambient_color * ambient_strength;
    vec3 color = diffuse + ambient;
    color = apply_fog(color, fog_density, fog_start, v_dist);
    frag_color = vec4(color, 1.0);
}
@end

@program lighting vs_lit fs_lit
