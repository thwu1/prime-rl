#version 300 es
precision mediump float;
in vec2 vTexCoord[5];
out vec4 fragColor;
void main() {
    fragColor = vec4(vTexCoord[0], 0.0, 1.0);
}
