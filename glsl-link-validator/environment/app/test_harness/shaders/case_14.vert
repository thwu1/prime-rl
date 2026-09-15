#version 300 es
in vec4 aPosition;
centroid out vec4 vColor;
void main() {
    gl_Position = aPosition;
    vColor = vec4(1.0);
}
