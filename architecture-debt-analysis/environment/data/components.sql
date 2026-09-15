CREATE TABLE components (
    name TEXT PRIMARY KEY,
    layer TEXT NOT NULL,
    abstract_types INTEGER NOT NULL,
    concrete_types INTEGER NOT NULL
);

CREATE INDEX idx_components_layer ON components(layer);

INSERT INTO components VALUES ('web-frontend', 'ui', 3, 15);
INSERT INTO components VALUES ('mobile-app', 'ui', 2, 12);
INSERT INTO components VALUES ('admin-panel', 'ui', 1, 8);
INSERT INTO components VALUES ('api-gateway', 'ui', 4, 10);
INSERT INTO components VALUES ('user-service', 'service', 5, 18);
INSERT INTO components VALUES ('order-service', 'service', 4, 22);
INSERT INTO components VALUES ('payment-service', 'service', 6, 14);
INSERT INTO components VALUES ('notification-service', 'service', 3, 11);
INSERT INTO components VALUES ('inventory-service', 'service', 4, 16);
INSERT INTO components VALUES ('reporting-service', 'service', 2, 19);
INSERT INTO components VALUES ('auth-service', 'service', 7, 13);
INSERT INTO components VALUES ('search-service', 'service', 3, 15);
INSERT INTO components VALUES ('shipping-service', 'service', 3, 12);
INSERT INTO components VALUES ('pricing-service', 'service', 2, 9);
INSERT INTO components VALUES ('analytics-service', 'service', 1, 14);
INSERT INTO components VALUES ('user-domain', 'domain', 8, 12);
INSERT INTO components VALUES ('order-domain', 'domain', 10, 15);
INSERT INTO components VALUES ('product-domain', 'domain', 7, 11);
INSERT INTO components VALUES ('payment-domain', 'domain', 6, 8);
INSERT INTO components VALUES ('shipping-domain', 'domain', 5, 7);
INSERT INTO components VALUES ('db-adapter', 'infrastructure', 10, 20);
INSERT INTO components VALUES ('cache-adapter', 'infrastructure', 4, 8);
INSERT INTO components VALUES ('message-queue', 'infrastructure', 6, 10);
INSERT INTO components VALUES ('email-adapter', 'infrastructure', 3, 6);
INSERT INTO components VALUES ('storage-adapter', 'infrastructure', 5, 9);
INSERT INTO components VALUES ('logging-framework', 'infrastructure', 4, 12);
INSERT INTO components VALUES ('monitoring-adapter', 'infrastructure', 3, 7);
INSERT INTO components VALUES ('common-utils', 'shared', 2, 25);
INSERT INTO components VALUES ('shared-types', 'shared', 15, 10);
INSERT INTO components VALUES ('event-bus', 'shared', 8, 5);
INSERT INTO components VALUES ('config-manager', 'shared', 3, 9);
INSERT INTO components VALUES ('security-core', 'shared', 9, 11);
INSERT INTO components VALUES ('validation-lib', 'shared', 4, 14);
INSERT INTO components VALUES ('serialization-lib', 'shared', 3, 8);
INSERT INTO components VALUES ('metrics-collector', 'shared', 5, 7);
