#version 300 es
precision mediump float;
in highp float vDepth;
out vec4 fragColor;
void main() {
    fragColor = vec4(vDepth);
}
