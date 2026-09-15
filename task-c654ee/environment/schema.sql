-- Schema for github_meta database
-- Column ordinal positions correspond to @N references in ROW-format binary logs

CREATE TABLE repositories (
    id INT PRIMARY KEY,
    owner VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    stars INT NOT NULL DEFAULT 0,
    forks INT NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL
);

CREATE TABLE issues (
    id INT PRIMARY KEY AUTO_INCREMENT,
    repo_id INT NOT NULL,
    number INT NOT NULL,
    title VARCHAR(256) NOT NULL,
    body TEXT,
    state ENUM('open', 'closed') NOT NULL DEFAULT 'open',
    author VARCHAR(64) NOT NULL,
    assignee VARCHAR(64) DEFAULT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    closed_at DATETIME DEFAULT NULL,
    UNIQUE KEY idx_repo_number (repo_id, number)
);
