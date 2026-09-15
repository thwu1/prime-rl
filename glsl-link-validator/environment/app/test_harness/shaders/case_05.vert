#version 300 es
in vec4 aPosition;
invariant out vec4 vPosition;
void main() {
    gl_Position = aPosition;
    vPosition = aPosition;
}
