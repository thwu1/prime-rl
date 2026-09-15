-- Fulfillment Analytics Database Schema

DROP TABLE IF EXISTS order_events CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS fulfillment_stages CASCADE;
DROP TABLE IF EXISTS warehouses CASCADE;

CREATE TABLE warehouses (
    warehouse_id INTEGER PRIMARY KEY,
    warehouse_name VARCHAR(100) NOT NULL,
    parent_id INTEGER REFERENCES warehouses(warehouse_id),
    region VARCHAR(50) NOT NULL,
    capacity INTEGER NOT NULL,
    warehouse_type VARCHAR(20) NOT NULL
);

CREATE TABLE fulfillment_stages (
    stage_id INTEGER PRIMARY KEY,
    stage_name VARCHAR(50) NOT NULL,
    stage_order INTEGER NOT NULL UNIQUE
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    order_date TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata JSONB NOT NULL,
    total_amount NUMERIC(10,2) NOT NULL
);

CREATE TABLE order_events (
    event_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    stage_id INTEGER NOT NULL REFERENCES fulfillment_stages(stage_id),
    entered_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(20) NOT NULL
);
