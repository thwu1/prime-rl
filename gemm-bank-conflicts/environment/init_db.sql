CREATE TABLE hardware (
    warp_size INTEGER NOT NULL,
    num_banks INTEGER NOT NULL,
    bank_width_bytes INTEGER NOT NULL
);

INSERT INTO hardware VALUES (32, 32, 4);

CREATE TABLE kernels (
    name TEXT PRIMARY KEY,
    block_tile_m INTEGER NOT NULL,
    block_tile_n INTEGER NOT NULL,
    block_tile_k INTEGER NOT NULL,
    thread_tile_m INTEGER NOT NULL,
    thread_tile_n INTEGER NOT NULL,
    element_bytes INTEGER NOT NULL
);

INSERT INTO kernels VALUES ('small_tiles', 32, 32, 8, 4, 4, 4);
INSERT INTO kernels VALUES ('medium_tiles', 64, 64, 8, 4, 4, 4);
INSERT INTO kernels VALUES ('large_tiles', 128, 128, 16, 8, 8, 4);
