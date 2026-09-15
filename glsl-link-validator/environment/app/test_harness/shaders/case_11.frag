#version 300 es
precision mediump float;
in vec4 vAlbedo;
in vec4 vEmissive;
out vec4 fragColor;
void main() {
    fragColor = vAlbedo + vEmissive;
}
