ALTER TABLE products ADD COLUMN category VARCHAR(100);

ALTER TABLE products ADD COLUMN description TEXT;

CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    parent_id INTEGER REFERENCES categories(id)
);

ALTER TABLE orders ADD COLUMN shipping_address VARCHAR(500) NOT NULL;

CREATE INDEX idx_products_category ON products(category);
