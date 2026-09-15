struct Light {
    position: vec3<f32>,
    range: f32,
}

struct SceneUniforms {
    view_proj: mat4x4<f32>,
    camera_pos: vec3<f32>,
    time: f32,
    ambient_color: array<f32, 4>,
    main_light: Light,
}
