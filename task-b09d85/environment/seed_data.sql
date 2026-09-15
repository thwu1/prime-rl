INSERT INTO users (username, email, full_name) VALUES
    ('alice', 'alice@example.com', 'Alice Johnson'),
    ('bob', 'bob@example.com', 'Bob Smith'),
    ('charlie', 'charlie@example.com', 'Charlie Brown');

INSERT INTO products (name, price, stock) VALUES
    ('Widget A', 19.99, 100),
    ('Widget B', 29.99, 50),
    ('Gadget X', 49.99, 25);

INSERT INTO orders (user_id, total, status) VALUES
    (1, 49.98, 'completed'),
    (2, 29.99, 'pending'),
    (3, 99.97, 'shipped');

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 2, 19.99),
    (2, 2, 1, 29.99),
    (3, 3, 2, 49.99);
