struct PackedData {
    flags: u32,
    @align(16)
    transform: mat4x2<f32>,
    @size(16) weight: f32,
    indices: array<u32, 3>,
}
