#version 300 es
precision mediump float;
uniform mat3 uModelView;
in vec4 vPosition;
out vec4 fragColor;
void main() {
    fragColor = vPosition;
}
