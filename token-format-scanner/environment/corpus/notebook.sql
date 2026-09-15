-- Schema migration v42: API token audit table
-- Applied: 2024-03-10

CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service VARCHAR(64) NOT NULL,
    token_value VARCHAR(128) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP NULL
);

-- Seed data from legacy system import
INSERT INTO api_tokens (id, service, token_value) VALUES
    (1, 'github_app', 'ghs_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA000000'),
    (2, 'internal_ci', 'a94a8fe5ccb19ba61c4c0873d391e987982fbbd3'),
    (3, 'monitoring', 'Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0');

-- Index for token lookups
CREATE INDEX IF NOT EXISTS idx_api_tokens_service ON api_tokens(service);
CREATE INDEX IF NOT EXISTS idx_api_tokens_revoked ON api_tokens(revoked_at);
