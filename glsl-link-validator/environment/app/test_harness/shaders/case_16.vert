#version 300 es
struct SurfaceA {
    vec3 normal;
    float roughness;
};
in vec4 aPosition;
out SurfaceA vSurface;
void main() {
    gl_Position = aPosition;
    vSurface.normal = vec3(0.0, 1.0, 0.0);
    vSurface.roughness = 0.5;
}
