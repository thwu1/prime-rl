#version 300 es
precision mediump float;
smooth in int vId;
out vec4 fragColor;
void main() {
    fragColor = vec4(float(vId));
}
