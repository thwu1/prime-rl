#version 450

layout(set = 0, binding = 0) uniform CameraUBO {
    mat4 view;
    mat4 proj;
} camera;

layout(set = 1, binding = 0) uniform ModelUBO {
    mat4 model;
    vec4 color;
} modelData;

layout(push_constant) uniform PushConstants {
    uint objectId;
    float time;
} pc;

layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;
layout(location = 2) in vec2 inTexCoord;

layout(location = 0) out vec3 fragNormal;
layout(location = 1) out vec2 fragTexCoord;
layout(location = 2) out vec4 fragColor;

void main() {
    mat4 mvp = camera.proj * camera.view * modelData.model;
    gl_Position = mvp * vec4(inPosition, 1.0);
    fragNormal = mat3(modelData.model) * inNormal;
    fragTexCoord = inTexCoord;
    fragColor = modelData.color * (1.0 + sin(pc.time) * 0.1);
}
