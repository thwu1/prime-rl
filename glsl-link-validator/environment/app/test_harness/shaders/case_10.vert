#version 300 es
in vec4 aPosition;
out vec2[4] vCoords;
void main() {
    gl_Position = aPosition;
    vCoords[0] = aPosition.xy;
    vCoords[1] = aPosition.yz;
    vCoords[2] = aPosition.zw;
    vCoords[3] = aPosition.xz;
}
