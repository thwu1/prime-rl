#version 300 es
in vec4 aPosition;
out vec2 vTexCoord[3];
void main() {
    gl_Position = aPosition;
    vTexCoord[0] = vec2(0.0);
    vTexCoord[1] = vec2(1.0);
    vTexCoord[2] = vec2(0.5);
}
