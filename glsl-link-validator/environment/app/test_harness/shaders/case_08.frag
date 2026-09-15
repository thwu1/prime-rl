#version 300 es
precision mediump float;
struct LightInfo {
    vec3 position;
    vec4 color;
    float intensity;
};
in LightInfo vLight;
out vec4 fragColor;
void main() {
    fragColor = vLight.color * vLight.intensity;
}
