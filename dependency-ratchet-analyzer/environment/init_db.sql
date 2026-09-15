-- Monolith dependency database schema and data

CREATE TABLE layers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    rank INTEGER NOT NULL
);

CREATE TABLE packages (
    name TEXT PRIMARY KEY,
    layer_id INTEGER NOT NULL REFERENCES layers(id),
    enforcement_level TEXT NOT NULL DEFAULT 'false'
);

CREATE TABLE dependencies (
    source TEXT NOT NULL REFERENCES packages(name),
    target TEXT NOT NULL REFERENCES packages(name),
    PRIMARY KEY (source, target)
);

-- Layer hierarchy
INSERT INTO layers VALUES (1, 'utility', 0);
INSERT INTO layers VALUES (2, 'power', 1);
INSERT INTO layers VALUES (3, 'business', 2);
INSERT INTO layers VALUES (4, 'api', 3);
INSERT INTO layers VALUES (5, 'services', 4);

-- Utility layer packages
INSERT INTO packages VALUES ('logging', 1, 'dag');
INSERT INTO packages VALUES ('config', 1, 'layered');
INSERT INTO packages VALUES ('crypto', 1, 'layered');
INSERT INTO packages VALUES ('metrics', 1, 'layered_dag');
INSERT INTO packages VALUES ('cache', 1, 'layered');
INSERT INTO packages VALUES ('serializer', 1, 'layered');

-- Power layer packages
INSERT INTO packages VALUES ('http_client', 2, 'layered');
INSERT INTO packages VALUES ('db_driver', 2, 'layered_dag');
INSERT INTO packages VALUES ('queue_client', 2, 'layered');
INSERT INTO packages VALUES ('storage_client', 2, 'layered');
INSERT INTO packages VALUES ('email_client', 2, 'layered');
INSERT INTO packages VALUES ('search_client', 2, 'layered');

-- Business layer packages
INSERT INTO packages VALUES ('user_model', 3, 'layered');
INSERT INTO packages VALUES ('payment_model', 3, 'layered');
INSERT INTO packages VALUES ('order_model', 3, 'false');
INSERT INTO packages VALUES ('inventory_model', 3, 'false');
INSERT INTO packages VALUES ('notification_model', 3, 'false');
INSERT INTO packages VALUES ('analytics_model', 3, 'layered');
INSERT INTO packages VALUES ('shipping_model', 3, 'false');
INSERT INTO packages VALUES ('subscription_model', 3, 'false');
INSERT INTO packages VALUES ('fraud_model', 3, 'false');
INSERT INTO packages VALUES ('refund_model', 3, 'false');

-- API layer packages
INSERT INTO packages VALUES ('auth_api', 4, 'layered');
INSERT INTO packages VALUES ('payment_api', 4, 'false');
INSERT INTO packages VALUES ('order_api', 4, 'layered_dag');
INSERT INTO packages VALUES ('admin_api', 4, 'false');
INSERT INTO packages VALUES ('webhook_api', 4, 'false');
INSERT INTO packages VALUES ('search_api', 4, 'false');
INSERT INTO packages VALUES ('subscription_api', 4, 'false');

-- Services layer packages
INSERT INTO packages VALUES ('web_service', 5, 'false');
INSERT INTO packages VALUES ('worker_service', 5, 'false');
INSERT INTO packages VALUES ('admin_service', 5, 'false');
INSERT INTO packages VALUES ('cron_service', 5, 'false');
INSERT INTO packages VALUES ('webhook_service', 5, 'false');

-- Dependencies: utility layer
INSERT INTO dependencies VALUES ('config', 'logging');
INSERT INTO dependencies VALUES ('crypto', 'logging');
INSERT INTO dependencies VALUES ('crypto', 'config');
INSERT INTO dependencies VALUES ('metrics', 'logging');
INSERT INTO dependencies VALUES ('cache', 'logging');
INSERT INTO dependencies VALUES ('cache', 'config');
INSERT INTO dependencies VALUES ('cache', 'metrics');
INSERT INTO dependencies VALUES ('serializer', 'logging');
INSERT INTO dependencies VALUES ('serializer', 'crypto');
INSERT INTO dependencies VALUES ('serializer', 'config');

-- Dependencies: power layer
INSERT INTO dependencies VALUES ('http_client', 'logging');
INSERT INTO dependencies VALUES ('http_client', 'config');
INSERT INTO dependencies VALUES ('http_client', 'crypto');
INSERT INTO dependencies VALUES ('http_client', 'serializer');
INSERT INTO dependencies VALUES ('db_driver', 'logging');
INSERT INTO dependencies VALUES ('db_driver', 'config');
INSERT INTO dependencies VALUES ('db_driver', 'metrics');
INSERT INTO dependencies VALUES ('db_driver', 'http_client');
INSERT INTO dependencies VALUES ('db_driver', 'storage_client');
INSERT INTO dependencies VALUES ('queue_client', 'logging');
INSERT INTO dependencies VALUES ('queue_client', 'config');
INSERT INTO dependencies VALUES ('queue_client', 'serializer');
INSERT INTO dependencies VALUES ('queue_client', 'user_model');
INSERT INTO dependencies VALUES ('storage_client', 'logging');
INSERT INTO dependencies VALUES ('storage_client', 'http_client');
INSERT INTO dependencies VALUES ('storage_client', 'crypto');
INSERT INTO dependencies VALUES ('storage_client', 'db_driver');
INSERT INTO dependencies VALUES ('email_client', 'http_client');
INSERT INTO dependencies VALUES ('email_client', 'logging');
INSERT INTO dependencies VALUES ('email_client', 'config');
INSERT INTO dependencies VALUES ('search_client', 'http_client');
INSERT INTO dependencies VALUES ('search_client', 'serializer');
INSERT INTO dependencies VALUES ('search_client', 'logging');

-- Dependencies: business layer
INSERT INTO dependencies VALUES ('user_model', 'db_driver');
INSERT INTO dependencies VALUES ('user_model', 'logging');
INSERT INTO dependencies VALUES ('user_model', 'cache');
INSERT INTO dependencies VALUES ('user_model', 'crypto');
INSERT INTO dependencies VALUES ('payment_model', 'db_driver');
INSERT INTO dependencies VALUES ('payment_model', 'logging');
INSERT INTO dependencies VALUES ('payment_model', 'crypto');
INSERT INTO dependencies VALUES ('payment_model', 'user_model');
INSERT INTO dependencies VALUES ('payment_model', 'auth_api');
INSERT INTO dependencies VALUES ('order_model', 'db_driver');
INSERT INTO dependencies VALUES ('order_model', 'payment_model');
INSERT INTO dependencies VALUES ('order_model', 'user_model');
INSERT INTO dependencies VALUES ('order_model', 'logging');
INSERT INTO dependencies VALUES ('order_model', 'queue_client');
INSERT INTO dependencies VALUES ('order_model', 'notification_model');
INSERT INTO dependencies VALUES ('order_model', 'inventory_model');
INSERT INTO dependencies VALUES ('inventory_model', 'db_driver');
INSERT INTO dependencies VALUES ('inventory_model', 'logging');
INSERT INTO dependencies VALUES ('inventory_model', 'order_model');
INSERT INTO dependencies VALUES ('notification_model', 'email_client');
INSERT INTO dependencies VALUES ('notification_model', 'user_model');
INSERT INTO dependencies VALUES ('notification_model', 'logging');
INSERT INTO dependencies VALUES ('notification_model', 'order_model');
INSERT INTO dependencies VALUES ('analytics_model', 'db_driver');
INSERT INTO dependencies VALUES ('analytics_model', 'user_model');
INSERT INTO dependencies VALUES ('analytics_model', 'order_model');
INSERT INTO dependencies VALUES ('analytics_model', 'payment_model');
INSERT INTO dependencies VALUES ('analytics_model', 'metrics');
INSERT INTO dependencies VALUES ('analytics_model', 'logging');
INSERT INTO dependencies VALUES ('shipping_model', 'order_model');
INSERT INTO dependencies VALUES ('shipping_model', 'inventory_model');
INSERT INTO dependencies VALUES ('shipping_model', 'logging');
INSERT INTO dependencies VALUES ('shipping_model', 'http_client');
INSERT INTO dependencies VALUES ('shipping_model', 'notification_model');
INSERT INTO dependencies VALUES ('subscription_model', 'payment_model');
INSERT INTO dependencies VALUES ('subscription_model', 'user_model');
INSERT INTO dependencies VALUES ('subscription_model', 'notification_model');
INSERT INTO dependencies VALUES ('subscription_model', 'db_driver');
INSERT INTO dependencies VALUES ('subscription_model', 'logging');
INSERT INTO dependencies VALUES ('fraud_model', 'payment_model');
INSERT INTO dependencies VALUES ('fraud_model', 'user_model');
INSERT INTO dependencies VALUES ('fraud_model', 'analytics_model');
INSERT INTO dependencies VALUES ('fraud_model', 'order_model');
INSERT INTO dependencies VALUES ('fraud_model', 'logging');
INSERT INTO dependencies VALUES ('refund_model', 'payment_model');
INSERT INTO dependencies VALUES ('refund_model', 'order_model');
INSERT INTO dependencies VALUES ('refund_model', 'fraud_model');
INSERT INTO dependencies VALUES ('refund_model', 'user_model');
INSERT INTO dependencies VALUES ('refund_model', 'logging');
INSERT INTO dependencies VALUES ('refund_model', 'notification_model');

-- Dependencies: API layer
INSERT INTO dependencies VALUES ('auth_api', 'user_model');
INSERT INTO dependencies VALUES ('auth_api', 'crypto');
INSERT INTO dependencies VALUES ('auth_api', 'logging');
INSERT INTO dependencies VALUES ('auth_api', 'config');
INSERT INTO dependencies VALUES ('auth_api', 'metrics');
INSERT INTO dependencies VALUES ('auth_api', 'payment_api');
INSERT INTO dependencies VALUES ('payment_api', 'payment_model');
INSERT INTO dependencies VALUES ('payment_api', 'user_model');
INSERT INTO dependencies VALUES ('payment_api', 'auth_api');
INSERT INTO dependencies VALUES ('payment_api', 'logging');
INSERT INTO dependencies VALUES ('payment_api', 'fraud_model');
INSERT INTO dependencies VALUES ('order_api', 'order_model');
INSERT INTO dependencies VALUES ('order_api', 'payment_model');
INSERT INTO dependencies VALUES ('order_api', 'user_model');
INSERT INTO dependencies VALUES ('order_api', 'auth_api');
INSERT INTO dependencies VALUES ('order_api', 'inventory_model');
INSERT INTO dependencies VALUES ('order_api', 'logging');
INSERT INTO dependencies VALUES ('admin_api', 'user_model');
INSERT INTO dependencies VALUES ('admin_api', 'order_model');
INSERT INTO dependencies VALUES ('admin_api', 'payment_model');
INSERT INTO dependencies VALUES ('admin_api', 'analytics_model');
INSERT INTO dependencies VALUES ('admin_api', 'auth_api');
INSERT INTO dependencies VALUES ('admin_api', 'logging');
INSERT INTO dependencies VALUES ('webhook_api', 'notification_model');
INSERT INTO dependencies VALUES ('webhook_api', 'order_model');
INSERT INTO dependencies VALUES ('webhook_api', 'logging');
INSERT INTO dependencies VALUES ('webhook_api', 'crypto');
INSERT INTO dependencies VALUES ('webhook_api', 'queue_client');
INSERT INTO dependencies VALUES ('search_api', 'search_client');
INSERT INTO dependencies VALUES ('search_api', 'user_model');
INSERT INTO dependencies VALUES ('search_api', 'order_model');
INSERT INTO dependencies VALUES ('search_api', 'auth_api');
INSERT INTO dependencies VALUES ('search_api', 'logging');
INSERT INTO dependencies VALUES ('subscription_api', 'subscription_model');
INSERT INTO dependencies VALUES ('subscription_api', 'payment_model');
INSERT INTO dependencies VALUES ('subscription_api', 'auth_api');
INSERT INTO dependencies VALUES ('subscription_api', 'user_model');
INSERT INTO dependencies VALUES ('subscription_api', 'logging');

-- Dependencies: services layer
INSERT INTO dependencies VALUES ('web_service', 'auth_api');
INSERT INTO dependencies VALUES ('web_service', 'payment_api');
INSERT INTO dependencies VALUES ('web_service', 'order_api');
INSERT INTO dependencies VALUES ('web_service', 'search_api');
INSERT INTO dependencies VALUES ('web_service', 'logging');
INSERT INTO dependencies VALUES ('web_service', 'config');
INSERT INTO dependencies VALUES ('web_service', 'metrics');
INSERT INTO dependencies VALUES ('worker_service', 'order_model');
INSERT INTO dependencies VALUES ('worker_service', 'payment_model');
INSERT INTO dependencies VALUES ('worker_service', 'notification_model');
INSERT INTO dependencies VALUES ('worker_service', 'queue_client');
INSERT INTO dependencies VALUES ('worker_service', 'logging');
INSERT INTO dependencies VALUES ('worker_service', 'shipping_model');
INSERT INTO dependencies VALUES ('admin_service', 'admin_api');
INSERT INTO dependencies VALUES ('admin_service', 'auth_api');
INSERT INTO dependencies VALUES ('admin_service', 'logging');
INSERT INTO dependencies VALUES ('admin_service', 'config');
INSERT INTO dependencies VALUES ('cron_service', 'analytics_model');
INSERT INTO dependencies VALUES ('cron_service', 'inventory_model');
INSERT INTO dependencies VALUES ('cron_service', 'shipping_model');
INSERT INTO dependencies VALUES ('cron_service', 'logging');
INSERT INTO dependencies VALUES ('cron_service', 'db_driver');
INSERT INTO dependencies VALUES ('cron_service', 'subscription_model');
INSERT INTO dependencies VALUES ('webhook_service', 'webhook_api');
INSERT INTO dependencies VALUES ('webhook_service', 'queue_client');
INSERT INTO dependencies VALUES ('webhook_service', 'notification_model');
INSERT INTO dependencies VALUES ('webhook_service', 'logging');
