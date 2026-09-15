INSERT INTO customers (name, email) VALUES
    ('Alice Smith', 'alice@example.com'),
    ('Bob Jones', 'bob@example.com'),
    ('Charlie Brown', 'charlie@example.com');

INSERT INTO products (name, description, price, category) VALUES
    ('Widget A', 'A basic widget', 9.99, 'widgets'),
    ('Gadget B', 'An advanced gadget', 29.99, 'gadgets'),
    ('Doohickey C', 'A mysterious doohickey', 14.99, 'misc');

INSERT INTO orders (customer_id, status) VALUES
    (1, 'completed'),
    (2, 'pending'),
    (3, 'shipped'),
    (1, 'pending');
