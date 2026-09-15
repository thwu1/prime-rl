#version 300 es
in vec4 aPosition;
out vec3 vNormal;
void main() {
    gl_Position = aPosition;
    vNormal = vec3(0.0, 1.0, 0.0);
}
