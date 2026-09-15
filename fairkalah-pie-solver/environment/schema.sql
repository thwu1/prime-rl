-- Endgame database schema for FairKalah solver
-- board_key: comma-separated board array values, e.g. "1,1,1,0,1,1,1,0"

CREATE TABLE IF NOT EXISTS endgame_positions (
    board_key TEXT NOT NULL,
    n INTEGER NOT NULL,
    side INTEGER NOT NULL,
    total_stones INTEGER NOT NULL,
    value INTEGER NOT NULL,
    best_move INTEGER NOT NULL,
    captures INTEGER NOT NULL,
    PRIMARY KEY (board_key, side, captures)
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_endgame_config
    ON endgame_positions(n, total_stones, captures);
