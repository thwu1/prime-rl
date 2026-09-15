// Stress test: intentionally suboptimal member ordering
@vs vs_path
layout(binding=0) uniform path_params {
    float a;
    vec3 b;
    float c;
    vec4 d;
    float e;
    vec2 f;
    float g;
    mat4 h;
    int i_val;
    vec3 j;
    vec2 k;
    float l;
    int m;
    vec3 n;
    float o;
    vec4 p;
};

in vec4 position;

void main() {
    gl_Position = h * position * a;
}
@end

@fs fs_path
out vec4 frag_color;

void main() {
    frag_color = vec4(1.0, 0.0, 0.0, 1.0);
}
@end

@program pathological vs_path fs_path
