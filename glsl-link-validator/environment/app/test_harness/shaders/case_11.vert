#version 300 es
in vec4 aPosition;
out vec4 vAlbedo, vEmissive;
void main() {
    gl_Position = aPosition;
    vAlbedo = vec4(0.8);
    vEmissive = vec4(0.0);
}
