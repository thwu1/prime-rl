// Particle rendering and simulation pipeline
// Uses sokol-shdc annotated GLSL format

@block shared_types
struct particle_t {
    vec4 pos;
    vec4 vel;
    vec4 color;
};
@end

@vs vs_particle
@include_block shared_types

layout(binding=0) uniform vs_params {
    mat4 view_proj;
    mat4 model;
    vec4 camera_pos;
};

layout(binding=0) readonly buffer ssbo_particles {
    particle_t particles[];
};

in vec4 position;
in vec2 texcoord;
out vec2 uv;
out vec4 color;
out vec3 world_normal;

void main() {
    int idx = gl_InstanceIndex;
    vec4 world_pos = position + particles[idx].pos;
    gl_Position = view_proj * model * world_pos;
    uv = texcoord;
    color = particles[idx].color;
    world_normal = normalize(position.xyz);
}
@end

@fs fs_particle
layout(binding=1) uniform fs_params {
    vec4 ambient_color;
    vec4 light_dir;
    float specular_power;
};

layout(binding=1) uniform texture2D diffuse_tex;
layout(binding=2) uniform texture2D normal_tex;
layout(binding=0) uniform sampler tex_smp;

in vec2 uv;
in vec4 color;
in vec3 world_normal;
out vec4 frag_color;

void main() {
    vec4 diff = texture(sampler2D(diffuse_tex, tex_smp), uv);
    vec4 norm = texture(sampler2D(normal_tex, tex_smp), uv);
    float ndotl = max(dot(world_normal, light_dir.xyz), 0.0);
    frag_color = diff * color * (ambient_color + vec4(vec3(ndotl), 0.0));
}
@end

@cs cs_update_particles
@include_block shared_types

layout(binding=0) uniform cs_params {
    float dt;
    int num_particles;
    vec4 gravity;
    vec4 wind;
};

layout(binding=0) readonly buffer ssbo_in {
    particle_t particles_in[];
};

layout(binding=1) buffer ssbo_out {
    particle_t particles_out[];
};

layout(local_size_x=64, local_size_y=1, local_size_z=1) in;

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= num_particles) return;

    particle_t p = particles_in[idx];
    p.vel += (gravity + wind) * dt;
    p.pos += p.vel * dt;

    if (p.pos.y < 0.0) {
        p.pos.y = 0.0;
        p.vel.y = -p.vel.y * 0.5;
    }

    particles_out[idx] = p;
}
@end

@program particle_render vs_particle fs_particle
@program particle_update cs_update_particles
