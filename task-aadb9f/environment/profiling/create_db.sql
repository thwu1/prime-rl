CREATE TABLE measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arch TEXT NOT NULL,
    kernel TEXT NOT NULL,
    block_size INTEGER NOT NULL,
    active_blocks_per_sm INTEGER,
    active_warps_per_sm INTEGER,
    occupancy REAL,
    limiting_resource TEXT,
    valid TEXT NOT NULL
);

INSERT INTO measurements (arch, kernel, block_size, active_blocks_per_sm, active_warps_per_sm, occupancy, limiting_resource, valid) VALUES
('volta', 'matmul_tiled', 256, 6, 48, 0.75, 'registers', 'true'),
('volta', 'conv_shared', 256, 5, 40, 0.625, 'registers', 'true'),
('volta', 'reduce_warp', 128, 16, 64, 1.0, 'warps', 'true'),
('volta', 'stencil_3d', 256, 4, 32, 0.5, 'registers', 'true'),
('volta', 'scan_block', 64, 32, 64, 1.0, 'warps', 'true'),
('volta', 'attention', 256, NULL, NULL, NULL, NULL, 'false'),
('ampere', 'matmul_tiled', 256, 6, 48, 0.75, 'registers', 'true'),
('ampere', 'conv_shared', 512, 2, 32, 0.5, 'registers', 'true'),
('ampere', 'fft_radix', 256, 1, 8, 0.125, 'shared_memory', 'true'),
('ampere', 'attention', 256, 2, 16, 0.25, 'shared_memory', 'true'),
('hopper', 'matmul_tiled', 256, 6, 48, 0.75, 'registers', 'true'),
('hopper', 'stencil_3d', 256, 4, 32, 0.5, 'registers', 'true'),
('hopper', 'reduce_warp', 256, 8, 64, 1.0, 'warps', 'true'),
('hopper', 'attention', 512, 3, 48, 0.75, 'shared_memory', 'true'),
('ampere', 'stencil_3d', 256, 4, 32, 0.5, 'registers', 'true'),
('ampere', 'matmul_tiled', 512, 3, 48, 0.75, 'registers', 'true'),
('hopper', 'conv_shared', 256, 5, 40, 0.625, 'registers', 'true'),
('volta', 'scan_block', 128, 16, 64, 1.0, 'warps', 'true'),
('ampere', 'scan_block', 128, 16, 64, 1.0, 'warps', 'true'),
('hopper', 'fft_radix', 128, 1, 4, 0.0625, 'shared_memory', 'true');
