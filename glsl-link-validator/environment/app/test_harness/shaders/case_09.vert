#version 300 es
struct Material {
    vec4 diffuse;
    vec3 specular;
    float shininess;
};
in vec4 aPosition;
out Material vMat;
void main() {
    gl_Position = aPosition;
    vMat.diffuse = vec4(1.0);
    vMat.specular = vec3(1.0);
    vMat.shininess = 32.0;
}
