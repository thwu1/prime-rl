
-- Schema history seed data: MySQL DDL statements captured from a CDC pipeline.
-- These represent a production schema's evolution over time.

DROP TABLE IF EXISTS ddl_history;
CREATE TABLE ddl_history (
    seq_id SERIAL PRIMARY KEY,
    ddl_text TEXT NOT NULL
);

INSERT INTO ddl_history (ddl_text) VALUES
($DDL$CREATE TABLE `customers` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL,
  `email` varchar(255) NOT NULL,
  `status` enum('ACTIVE','INACTIVE','SUSPENDED') NOT NULL DEFAULT 'ACTIVE',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;$DDL$),

($DDL$CREATE TABLE `products` (
  `product_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `sku` varchar(50) NOT NULL,
  `title` varchar(255) NOT NULL DEFAULT '',
  `description` text,
  `price` decimal(10,2) NOT NULL DEFAULT '0.00',
  `weight_kg` double(8,3) DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`product_id`),
  UNIQUE KEY `uk_sku` (`sku`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;$DDL$),

($DDL$CREATE TABLE `orders` (
  `order_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `customer_id` bigint NOT NULL,
  `order_total` decimal(18,2) NOT NULL DEFAULT '0.00',
  `currency` char(3) NOT NULL DEFAULT 'USD',
  `payment_method` set('CREDIT_CARD','DEBIT_CARD','PAYPAL','WIRE','CRYPTO') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `ordered_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  PRIMARY KEY (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;$DDL$),

($DDL$CREATE TABLE `change_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `target_table` varchar(128) NOT NULL,
  `target_id` bigint NOT NULL,
  `before_state` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT (json_object()),
  `after_state` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT (json_object()),
  `changed_by` varchar(64) NOT NULL DEFAULT '',
  `changed_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_target` (`target_table`, `target_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Audit trail for all tables';$DDL$),

($DDL$ALTER TABLE `customers` ADD COLUMN `phone` varchar(20) DEFAULT NULL AFTER `email`, ADD COLUMN `country` char(2) NOT NULL DEFAULT 'US';$DDL$),

($DDL$ALTER TABLE `orders` MODIFY COLUMN `order_total` decimal(20,4) NOT NULL DEFAULT '0.0000';$DDL$),

($DDL$ALTER TABLE `orders` CHANGE COLUMN `ordered_at` `placed_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6);$DDL$),

($DDL$CREATE TABLE IF NOT EXISTS `select` (
  `id` int NOT NULL AUTO_INCREMENT,
  `from` varchar(255) DEFAULT NULL,
  `where` varchar(255) NOT NULL,
  `group` int DEFAULT 0,
  `order` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;$DDL$),

($DDL$ALTER TABLE `products` ADD COLUMN `cost_price` decimal(10,2) DEFAULT NULL, ADD COLUMN `margin_pct` decimal(5,2) GENERATED ALWAYS AS (CASE WHEN `cost_price` > 0 THEN (`price` - `cost_price`) / `cost_price` * 100 ELSE NULL END) STORED;$DDL$),

($DDL$ALTER TABLE `customers` DROP COLUMN `country`;$DDL$),

($DDL$ALTER TABLE `customers` RENAME COLUMN `phone` TO `mobile`;$DDL$),

($DDL$ALTER TABLE `customers` MODIFY COLUMN `status` enum('ACTIVE','INACTIVE','SUSPENDED','BANNED','DELETED') NOT NULL DEFAULT 'ACTIVE';$DDL$),

($DDL$DROP TABLE IF EXISTS `select`;$DDL$),

($DDL$CREATE TABLE `inventory` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `product_id` bigint unsigned NOT NULL,
  `warehouse` varchar(50) NOT NULL,
  `quantity` int NOT NULL DEFAULT 0,
  `reserved` int unsigned NOT NULL DEFAULT 0,
  `available` int GENERATED ALWAYS AS (`quantity` - `reserved`) VIRTUAL,
  `last_counted_at` datetime DEFAULT curtime(),
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_product_warehouse` (`product_id`, `warehouse`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;$DDL$),

($DDL$ALTER TABLE `orders` ADD COLUMN `shipping_type` varchar(50) DEFAULT 'STANDARD', ADD COLUMN `tracking_id` varchar(100) DEFAULT NULL;$DDL$),

($DDL$ALTER TABLE `orders` DROP COLUMN `tracking_id`, DROP COLUMN `shipping_type`;$DDL$),

($DDL$ALTER TABLE `products` RENAME TO `catalog_items`;$DDL$),

($DDL$ALTER TABLE `catalog_items` CHANGE COLUMN `weight_kg` `weight_g` int unsigned DEFAULT NULL;$DDL$),

($DDL$ALTER TABLE `catalog_items` MODIFY COLUMN `price` decimal(12,2) NOT NULL DEFAULT '0.00';$DDL$),

($DDL$ALTER TABLE `change_log` ADD COLUMN `event_uuid` varchar(36) NOT NULL DEFAULT (UUID()), DROP COLUMN `changed_by`, ADD COLUMN `actor_id` bigint DEFAULT NULL, ADD COLUMN `actor_type` enum('USER','SYSTEM','API','WEBHOOK') NOT NULL DEFAULT 'USER';$DDL$),

($DDL$ALTER TABLE `customers` ADD COLUMN `tenant_id` int NOT NULL DEFAULT 1 FIRST;$DDL$),

($DDL$ALTER TABLE `catalog_items` DROP PRIMARY KEY, ADD PRIMARY KEY (`sku`);$DDL$),

($DDL$CREATE TABLE `order_lines` (
  `line_id` bigint NOT NULL AUTO_INCREMENT,
  `order_id` bigint unsigned NOT NULL,
  `product_sku` varchar(50) NOT NULL,
  `quantity` smallint unsigned NOT NULL DEFAULT 1,
  `unit_price` decimal(12,2) NOT NULL,
  `line_total` decimal(14,2) GENERATED ALWAYS AS (`quantity` * `unit_price`) STORED,
  `discount_pct` decimal(5,2) NOT NULL DEFAULT '0.00',
  `net_total` decimal(14,2) GENERATED ALWAYS AS (`quantity` * `unit_price` * (1 - `discount_pct` / 100)) STORED,
  PRIMARY KEY (`line_id`),
  KEY `idx_order` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;$DDL$),

($DDL$ALTER TABLE `inventory` MODIFY COLUMN `quantity` int NOT NULL DEFAULT 0 COMMENT 'Physical count', MODIFY COLUMN `reserved` int unsigned NOT NULL DEFAULT 0 COMMENT 'Reserved for orders';$DDL$),

($DDL$ALTER TABLE `change_log` MODIFY COLUMN `target_table` varchar(255) NOT NULL;$DDL$);
