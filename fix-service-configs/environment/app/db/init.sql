-- MariaDB Initialization for infra.example.com

CREATE DATABASE IF NOT EXISTS appdb;
CREATE DATABASE IF NOT EXISTS appdb_staging;
CREATE DATABASE IF NOT EXISTS appdb_analytics;

USE appdb;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    email VARCHAR(128),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (username, email) VALUES ('admin', 'admin@infra.example.com');
INSERT INTO orders (user_id, amount, status) VALUES (1, 99.99, 'completed');

-- Application user: data access on primary database
CREATE USER IF NOT EXISTS 'appuser'@'10.20.30.%' IDENTIFIED BY 'SecurePass123!';
GRANT SELECT, INSERT, UPDATE, DELETE ON appdb.* TO 'appuser'@'10.20.30.%';

-- Reporter: read access for reporting
CREATE USER IF NOT EXISTS 'reporter'@'10.20.30.%' IDENTIFIED BY 'SecurePass123!';
GRANT SELECT ON appdb.* TO 'reporter'@'10.20.30.%';

-- Schema migrator: manages database structure
CREATE USER IF NOT EXISTS 'migrator'@'localhost' IDENTIFIED BY 'SecurePass123!';
GRANT CREATE, ALTER, DROP, INDEX, REFERENCES, SELECT ON appdb.* TO 'migrator'@'localhost';

-- Staging environment admin
CREATE USER IF NOT EXISTS 'staging_admin'@'localhost' IDENTIFIED BY 'SecurePass123!';
GRANT ALL PRIVILEGES ON appdb.* TO 'staging_admin'@'localhost';
