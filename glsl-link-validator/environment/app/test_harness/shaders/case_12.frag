#version 300 es
precision mediump float;
layout(location=3) in vec4 vColor;
out vec4 fragColor;
void main() {
    fragColor = vColor;
}
