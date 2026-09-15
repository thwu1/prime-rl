-- migration: 003_create_tags
-- depends_on: 001_create_users
-- description: Create the tags table

CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_by INTEGER,
    FOREIGN KEY (created_by) REFERENCES users(id)
);
