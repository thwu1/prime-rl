#version 450

layout(set = 0, binding = 1) uniform sampler2D texSampler;

layout(set = 0, binding = 2) uniform LightUBO {
    vec3 direction;
    float intensity;
    vec3 ambient;
    float _pad;
} light;

layout(location = 0) in vec3 fragNormal;
layout(location = 1) in vec2 fragTexCoord;
layout(location = 2) in vec4 fragColor;

layout(location = 0) out vec4 outColor;

void main() {
    vec3 n = normalize(fragNormal);
    float diff = max(dot(n, -light.direction), 0.0);
    vec3 lighting = light.ambient + diff * light.intensity;
    vec4 tex = texture(texSampler, fragTexCoord);
    outColor = vec4(tex.rgb * lighting, tex.a) * fragColor;
}
