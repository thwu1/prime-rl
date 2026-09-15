#version 300 es
struct LightData {
    vec3 position;
    vec4 color;
    float intensity;
};
in vec4 aPosition;
out LightData vLight;
void main() {
    gl_Position = aPosition;
    vLight.position = vec3(0.0);
    vLight.color = vec4(1.0);
    vLight.intensity = 1.0;
}
