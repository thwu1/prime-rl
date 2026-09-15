#version 300 es
precision mediump float;
in vec2 vCoords[4];
out vec4 fragColor;
void main() {
    fragColor = vec4(vCoords[0], vCoords[1]);
}
