#version 450

layout(location = 0) in vec2 v_texcoord;
layout(location = 1) in vec3 v_normal;

layout(location = 0) out vec4 frag_color;

layout(set = 0, binding = 0) uniform sampler2D u_texture;

layout(set = 0, binding = 1) uniform PostProcessParams {
    float brightness;
    float contrast;
    float saturation;
    float vignette_strength;
};

vec3 adjust_saturation(vec3 color, float sat) {
    const vec3 luminance_weights = vec3(0.2126, 0.7152, 0.0722);
    float lum = dot(color, luminance_weights);
    return mix(vec3(lum), color, sat);
}

float compute_vignette(vec2 uv, float strength) {
    vec2 centered = uv - 0.5;
    float dist = length(centered);
    return 1.0 - strength * smoothstep(0.2, 0.7, dist);
}

void main() {
    vec4 tex_color = texture(u_texture, v_texcoord);
    vec3 color = tex_color.rgb;

    color *= brightness;
    color = (color - 0.5) * contrast + 0.5;
    color = adjust_saturation(color, saturation);

    float vig = compute_vignette(v_texcoord, vignette_strength);
    color *= vig;

    vec3 light_dir = normalize(vec3(0.5, 1.0, 0.3));
    float ndl = max(dot(normalize(v_normal), light_dir), 0.0);
    color *= 0.3 + 0.7 * ndl;

    color = pow(max(color, vec3(0.0)), vec3(1.0 / 2.2));

    frag_color = vec4(color, tex_color.a);
}
