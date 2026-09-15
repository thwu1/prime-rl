#version 300 es
precision mediump float;
struct Material {
    float shininess;
    vec4 diffuse;
    vec3 specular;
};
in Material vMat;
out vec4 fragColor;
void main() {
    fragColor = vMat.diffuse;
}
