#version 300 es
precision mediump float;
in vec4 vColor;
in vec3 vNormal;
out vec4 fragColor;
void main() {
    fragColor = vColor + vec4(vNormal, 0.0);
}
