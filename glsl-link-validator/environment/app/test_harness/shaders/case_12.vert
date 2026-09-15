#version 300 es
in vec4 aPosition;
layout( location = 1 ) out vec4 vColor;
void main() {
    gl_Position = aPosition;
    vColor = vec4(1.0);
}
