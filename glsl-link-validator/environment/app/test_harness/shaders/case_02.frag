#version 300 es
precision mediump float;
in vec4 vNormal;
out vec4 fragColor;
void main() {
    fragColor = vNormal;
}
