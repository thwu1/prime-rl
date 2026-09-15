-- Shard databases for Vitess-like sharded deployment
CREATE DATABASE IF NOT EXISTS shard0;
CREATE DATABASE IF NOT EXISTS shard1;

-- Messages table (sharded by channel_id via hash vindex)
CREATE TABLE shard0.messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    workspace_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    keyspace_id BINARY(8) NOT NULL,
    INDEX idx_channel (channel_id),
    INDEX idx_workspace (workspace_id),
    INDEX idx_keyspace (keyspace_id)
) ENGINE=InnoDB;

CREATE TABLE shard1.messages LIKE shard0.messages;

-- Subscriptions table (user-channel-thread subscriptions)
CREATE TABLE shard0.subscriptions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    thread_id BIGINT DEFAULT NULL,
    workspace_id BIGINT NOT NULL,
    status ENUM('active', 'inactive') DEFAULT 'active',
    keyspace_id BINARY(8) NOT NULL,
    INDEX idx_user_channel (user_id, channel_id),
    INDEX idx_workspace (workspace_id),
    INDEX idx_keyspace (keyspace_id)
) ENGINE=InnoDB;

CREATE TABLE shard1.subscriptions LIKE shard0.subscriptions;
