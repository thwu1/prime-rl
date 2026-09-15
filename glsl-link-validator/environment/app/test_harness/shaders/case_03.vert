#version 300 es
in vec4 aPosition;
out highp float vDepth;
void main() {
    gl_Position = aPosition;
    vDepth = gl_Position.z;
}
