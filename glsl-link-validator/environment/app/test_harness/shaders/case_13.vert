#version 300 es
uniform mat4 uModelView;
in vec4 aPosition;
out vec4 vPosition;
void main() {
    vPosition = uModelView * aPosition;
    gl_Position = vPosition;
}
