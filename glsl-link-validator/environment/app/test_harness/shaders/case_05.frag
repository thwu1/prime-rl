#version 300 es
precision mediump float;
invariant in vec4 vPosition;
out vec4 fragColor;
void main() {
    fragColor = vPosition;
}
