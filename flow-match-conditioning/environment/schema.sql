CREATE TABLE episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT NOT NULL,
    num_frames INTEGER NOT NULL,
    num_views INTEGER NOT NULL,
    trajectory_dim INTEGER NOT NULL,
    fps INTEGER NOT NULL
);

CREATE TABLE views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL REFERENCES episodes(id),
    view_index INTEGER NOT NULL,
    name TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    fx REAL NOT NULL,
    fy REAL NOT NULL,
    cx REAL NOT NULL,
    cy REAL NOT NULL
);

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL REFERENCES episodes(id),
    chunk_index INTEGER NOT NULL,
    sample_start INTEGER NOT NULL,
    sample_end INTEGER NOT NULL,
    num_sampled_frames INTEGER NOT NULL,
    num_steps INTEGER NOT NULL,
    flow_shift REAL NOT NULL,
    stage_boundary INTEGER NOT NULL,
    action_variance REAL NOT NULL,
    latent_t INTEGER NOT NULL,
    latent_h INTEGER NOT NULL,
    latent_w INTEGER NOT NULL
);

CREATE TABLE geometry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL REFERENCES episodes(id),
    padded_height INTEGER NOT NULL,
    total_width INTEGER NOT NULL,
    num_views INTEGER NOT NULL
);

CREATE TABLE view_crops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL REFERENCES episodes(id),
    view_index INTEGER NOT NULL,
    pixel_w_start INTEGER NOT NULL,
    pixel_w_end INTEGER NOT NULL,
    pixel_h_content INTEGER NOT NULL,
    latent_w_start INTEGER NOT NULL,
    latent_w_end INTEGER NOT NULL,
    latent_h_content INTEGER NOT NULL
);
