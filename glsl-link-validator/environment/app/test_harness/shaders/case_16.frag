#version 300 es
precision mediump float;
struct SurfaceB {
    vec3 direction;
    float smoothness;
};
in SurfaceB vSurface;
out vec4 fragColor;
void main() {
    fragColor = vec4(vSurface.direction, vSurface.smoothness);
}
