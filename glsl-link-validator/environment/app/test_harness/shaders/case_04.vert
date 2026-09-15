#version 300 es
in vec4 aPosition;
flat out int vId;
void main() {
    gl_Position = aPosition;
    vId = 1;
}
