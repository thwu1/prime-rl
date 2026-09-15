CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE discounts (
    discount_id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN (
        'multi_buy', 'percentage', 'bundle',
        'buy_n_get_m_free', 'cheapest_free_group'
    )),
    description TEXT
);

CREATE TABLE discount_params (
    discount_id TEXT NOT NULL REFERENCES discounts(discount_id),
    param_name TEXT NOT NULL,
    param_value TEXT NOT NULL,
    PRIMARY KEY (discount_id, param_name)
);

CREATE TABLE discount_products (
    discount_id TEXT NOT NULL REFERENCES discounts(discount_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    role TEXT NOT NULL DEFAULT 'eligible',
    PRIMARY KEY (discount_id, product_id)
);

INSERT INTO products VALUES ('TOOTH_BRUSH', 'Toothbrush', 1.99);
INSERT INTO products VALUES ('TOOTH_PASTE', 'Toothpaste', 3.49);
INSERT INTO products VALUES ('MOUTH_WASH', 'Mouthwash', 5.99);
INSERT INTO products VALUES ('DENTAL_FLOSS', 'Dental Floss', 2.29);
INSERT INTO products VALUES ('SHAMPOO', 'Shampoo', 4.99);
INSERT INTO products VALUES ('CONDITIONER', 'Conditioner', 4.99);
INSERT INTO products VALUES ('SOAP', 'Bar Soap', 1.49);
INSERT INTO products VALUES ('RICE', 'Rice (1kg bag)', 2.49);
INSERT INTO products VALUES ('APPLE_JUICE', 'Apple Juice', 2.99);
INSERT INTO products VALUES ('MILK', 'Milk', 1.29);

INSERT INTO discounts VALUES ('D1', 'multi_buy', '3 toothbrushes for $5.00');
INSERT INTO discount_params VALUES ('D1', 'quantity', '3');
INSERT INTO discount_params VALUES ('D1', 'fixed_price', '5.00');
INSERT INTO discount_products VALUES ('D1', 'TOOTH_BRUSH', 'target');

INSERT INTO discounts VALUES ('D2', 'percentage', '20% off toothpaste');
INSERT INTO discount_params VALUES ('D2', 'percent_off', '20');
INSERT INTO discount_products VALUES ('D2', 'TOOTH_PASTE', 'target');

INSERT INTO discounts VALUES ('D3', 'bundle', 'Oral care bundle: 25% off');
INSERT INTO discount_params VALUES ('D3', 'percent_off', '25');
INSERT INTO discount_products VALUES ('D3', 'TOOTH_BRUSH', 'bundle_member');
INSERT INTO discount_products VALUES ('D3', 'TOOTH_PASTE', 'bundle_member');
INSERT INTO discount_products VALUES ('D3', 'MOUTH_WASH', 'bundle_member');

INSERT INTO discounts VALUES ('D4', 'bundle', 'Hair care bundle: 30% off');
INSERT INTO discount_params VALUES ('D4', 'percent_off', '30');
INSERT INTO discount_products VALUES ('D4', 'SHAMPOO', 'bundle_member');
INSERT INTO discount_products VALUES ('D4', 'CONDITIONER', 'bundle_member');

INSERT INTO discounts VALUES ('D5', 'buy_n_get_m_free', 'Buy 2 soaps, get 1 free');
INSERT INTO discount_params VALUES ('D5', 'buy_count', '2');
INSERT INTO discount_params VALUES ('D5', 'free_count', '1');
INSERT INTO discount_products VALUES ('D5', 'SOAP', 'target');

INSERT INTO discounts VALUES ('D6', 'percentage', '10% off rice');
INSERT INTO discount_params VALUES ('D6', 'percent_off', '10');
INSERT INTO discount_products VALUES ('D6', 'RICE', 'target');

INSERT INTO discounts VALUES ('D7', 'cheapest_free_group', 'Buy 3 oral care items, cheapest is free');
INSERT INTO discount_params VALUES ('D7', 'group_size', '3');
INSERT INTO discount_products VALUES ('D7', 'TOOTH_BRUSH', 'eligible');
INSERT INTO discount_products VALUES ('D7', 'TOOTH_PASTE', 'eligible');
INSERT INTO discount_products VALUES ('D7', 'DENTAL_FLOSS', 'eligible');
INSERT INTO discount_products VALUES ('D7', 'MOUTH_WASH', 'eligible');

INSERT INTO discounts VALUES ('D8', 'multi_buy', '2 milks for $2.00');
INSERT INTO discount_params VALUES ('D8', 'quantity', '2');
INSERT INTO discount_params VALUES ('D8', 'fixed_price', '2.00');
INSERT INTO discount_products VALUES ('D8', 'MILK', 'target');
