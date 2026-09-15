CREATE DATABASE IF NOT EXISTS github_meta;
USE github_meta;

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

-- Base data: last consistent state before network partition at 2018-10-21 22:52:00 UTC

INSERT INTO repositories VALUES
(1, 'acme-corp', 'web-platform', 'Main web application platform', 1542, 203, '2018-10-21 22:40:00'),
(2, 'acme-corp', 'api-gateway', 'API gateway service', 876, 112, '2018-10-21 22:45:00'),
(3, 'acme-corp', 'data-pipeline', 'ETL and data processing', 432, 67, '2018-10-21 22:30:00'),
(4, 'acme-corp', 'mobile-app', 'iOS and Android client', 2105, 341, '2018-10-21 22:50:00'),
(5, 'acme-corp', 'infra-tools', 'Infrastructure automation', 654, 89, '2018-10-21 22:35:00');

INSERT INTO issues (id, repo_id, number, title, body, state, author, assignee, created_at, updated_at, closed_at) VALUES
(1, 1, 101, 'Login timeout on Safari', 'Users report 30s timeout on Safari 12', 'open', 'jsmith', NULL, '2018-10-21 20:00:00', '2018-10-21 22:00:00', NULL),
(2, 1, 102, 'CSS grid layout broken in IE11', 'Grid not rendering correctly in IE11', 'open', 'mchen', 'alee', '2018-10-21 20:15:00', '2018-10-21 22:10:00', NULL),
(3, 1, 103, 'Add SAML SSO support', 'Enterprise customers need SAML 2.0 integration', 'open', 'kpatel', NULL, '2018-10-21 20:30:00', '2018-10-21 22:20:00', NULL),
(4, 2, 201, 'Rate limiting not working', '429 responses not returned for exceeded limits', 'open', 'rjones', 'bwilson', '2018-10-21 19:00:00', '2018-10-21 22:30:00', NULL),
(5, 2, 202, 'Add GraphQL endpoint', 'REST API too verbose for mobile clients', 'open', 'mchen', NULL, '2018-10-21 19:30:00', '2018-10-21 22:35:00', NULL),
(6, 2, 203, 'JWT token expiry too short', 'Tokens expire in 15min causing UX issues', 'open', 'jsmith', 'rjones', '2018-10-21 20:00:00', '2018-10-21 22:40:00', NULL),
(7, 3, 301, 'Spark job OOM on large datasets', '64GB heap not enough for daily aggregation', 'open', 'dkim', NULL, '2018-10-21 18:00:00', '2018-10-21 22:45:00', NULL),
(8, 3, 302, 'Add Kafka connector', 'Need real-time ingestion from event bus', 'open', 'alee', 'dkim', '2018-10-21 18:30:00', '2018-10-21 22:48:00', NULL),
(9, 4, 401, 'Push notifications delayed', '5-10 min delay reported by users', 'open', 'bwilson', NULL, '2018-10-21 19:00:00', '2018-10-21 22:40:00', NULL),
(10, 4, 402, 'Offline mode data sync', 'Sync fails after 24h offline period', 'open', 'kpatel', 'bwilson', '2018-10-21 19:30:00', '2018-10-21 22:42:00', NULL),
(11, 4, 403, 'Biometric auth on Android', 'Fingerprint authentication needed for Android', 'open', 'rjones', NULL, '2018-10-21 20:00:00', '2018-10-21 22:44:00', NULL),
(12, 5, 501, 'Terraform state locking', 'State file corruption during concurrent CI runs', 'open', 'dkim', 'alee', '2018-10-21 17:00:00', '2018-10-21 22:46:00', NULL),
(13, 5, 502, 'K8s pod autoscaling', 'HPA configuration not responding to load', 'open', 'jsmith', NULL, '2018-10-21 17:30:00', '2018-10-21 22:47:00', NULL),
(14, 1, 104, 'Memory leak in WebSocket handler', 'RSS grows unbounded after 10k connections', 'open', 'alee', 'jsmith', '2018-10-21 21:00:00', '2018-10-21 22:49:00', NULL),
(15, 1, 105, 'Add rate limiting to uploads', 'Large file uploads causing resource exhaustion', 'open', 'bwilson', NULL, '2018-10-21 21:30:00', '2018-10-21 22:50:00', NULL),
(16, 2, 204, 'Add OpenAPI spec generation', 'Auto-generate from route definitions', 'open', 'kpatel', 'mchen', '2018-10-21 21:45:00', '2018-10-21 22:50:00', NULL),
(17, 3, 303, 'Add data quality checks', 'Alert on null values in required fields', 'open', 'rjones', NULL, '2018-10-21 22:00:00', '2018-10-21 22:50:00', NULL),
(18, 4, 404, 'Dark mode support', 'User-requested dark theme for mobile app', 'open', 'mchen', 'kpatel', '2018-10-21 22:10:00', '2018-10-21 22:50:00', NULL),
(19, 5, 503, 'Ansible to Terraform migration', 'Legacy Ansible playbooks need migration', 'open', 'alee', NULL, '2018-10-21 22:20:00', '2018-10-21 22:50:00', NULL),
(20, 5, 504, 'Vault secret rotation', 'HashiCorp Vault secrets not auto-rotating', 'open', 'bwilson', 'dkim', '2018-10-21 22:30:00', '2018-10-21 22:51:00', NULL);
