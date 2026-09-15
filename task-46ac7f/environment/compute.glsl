// GPU particle simulation compute shader
@cs cs_particles
layout(binding=0) uniform cs_params {
    float delta_time;
    int num_particles;
    vec3 gravity;
    float damping;
    vec4 bounds_min;
    vec4 bounds_max;
    mat4 transform;
    vec4 emit_color;
    float emit_rate;
    vec2 life_range;
    int max_particles;
};

struct Particle {
    vec4 pos;
    vec4 vel;
};

layout(std430, binding=1) buffer ssbo {
    Particle particles[];
};

layout(local_size_x=64, local_size_y=1, local_size_z=1) in;

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= num_particles) {
        return;
    }
    vec4 pos = particles[idx].pos;
    vec4 vel = particles[idx].vel;
    vel.xyz += gravity * delta_time;
    vel *= (1.0 - damping * delta_time);
    pos.xyz += vel.xyz * delta_time;
    pos.xyz = clamp(pos.xyz, bounds_min.xyz, bounds_max.xyz);
    particles[idx].pos = pos;
    particles[idx].vel = vel;
}
@end

@program particles cs_particles
