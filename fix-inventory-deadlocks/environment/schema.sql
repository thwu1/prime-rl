
-- Multi-warehouse inventory reservation system schema

CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(50) NOT NULL,
    unit_cost NUMERIC(12,2) NOT NULL
);

CREATE TABLE warehouses (
    warehouse_id SERIAL PRIMARY KEY,
    code VARCHAR(10) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL
);

CREATE TABLE inventory (
    inventory_id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(product_id),
    warehouse_id INT NOT NULL REFERENCES warehouses(warehouse_id),
    quantity_on_hand INT NOT NULL DEFAULT 0,
    quantity_reserved INT NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(product_id, warehouse_id),
    CONSTRAINT chk_on_hand_nonneg CHECK (quantity_on_hand >= 0),
    CONSTRAINT chk_reserved_nonneg CHECK (quantity_reserved >= 0),
    CONSTRAINT chk_reserved_le_onhand CHECK (quantity_reserved <= quantity_on_hand)
);

CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    order_number VARCHAR(30) UNIQUE NOT NULL,
    customer_id INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','RESERVED','SHIPPED','CANCELLED','FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE order_lines (
    line_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(order_id),
    product_id INT NOT NULL REFERENCES products(product_id),
    warehouse_id INT NOT NULL REFERENCES warehouses(warehouse_id),
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12,2) NOT NULL
);

CREATE TABLE reservations (
    reservation_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(order_id),
    product_id INT NOT NULL REFERENCES products(product_id),
    warehouse_id INT NOT NULL REFERENCES warehouses(warehouse_id),
    quantity INT NOT NULL CHECK (quantity > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE','RELEASED','FULFILLED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE stock_movements (
    movement_id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(product_id),
    warehouse_id INT NOT NULL REFERENCES warehouses(warehouse_id),
    movement_type VARCHAR(20) NOT NULL
        CHECK (movement_type IN (
            'RECEIPT','RESERVATION','RELEASE',
            'SHIPMENT','ADJUSTMENT','TRANSFER_IN','TRANSFER_OUT'
        )),
    quantity INT NOT NULL,
    reference_id INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
