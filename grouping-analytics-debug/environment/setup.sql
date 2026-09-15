
CREATE TABLE IF NOT EXISTS sales (
    id SERIAL PRIMARY KEY,
    region TEXT NOT NULL,
    category TEXT NOT NULL,
    channel TEXT NOT NULL,
    sale_date DATE NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    quantity INT NOT NULL,
    cost NUMERIC(10,2) NOT NULL
);

TRUNCATE sales RESTART IDENTITY;

INSERT INTO sales (region, category, channel, sale_date, amount, quantity, cost) VALUES
('North', 'Electronics', 'online',  '2024-01-15', 1200.00, 2,   800.00),
('North', 'Electronics', 'retail',  '2024-01-20',  850.00, 1,   750.00),
('North', 'Clothing',    'online',  '2024-02-10',  350.00, 5,   100.00),
('North', 'Clothing',    'retail',  '2024-02-15',  480.00, 8,   300.00),
('North', 'Food',        'online',  '2024-03-05',  120.00, 10,   80.00),
('North', 'Food',        'retail',  '2024-03-10',   95.00, 7,    85.00),
('South', 'Electronics', 'online',  '2024-01-18', 2200.00, 4,   900.00),
('South', 'Electronics', 'retail',  '2024-02-22', 1650.00, 3,  1100.00),
('South', 'Clothing',    'online',  '2024-01-25',  520.00, 6,   150.00),
('South', 'Clothing',    'retail',  '2024-03-12',  710.00, 9,   450.00),
('South', 'Food',        'online',  '2024-02-28',  180.00, 12,   50.00),
('South', 'Food',        'retail',  '2024-03-15',  240.00, 15,  200.00),
('West',  'Electronics', 'online',  '2024-04-10', 1800.00, 3,   800.00),
('West',  'Electronics', 'retail',  '2024-04-15',  950.00, 2,   650.00),
('West',  'Clothing',    'online',  '2024-05-05',  620.00, 7,   200.00),
('West',  'Clothing',    'retail',  '2024-05-10',  430.00, 4,   270.00),
('West',  'Food',        'online',  '2024-06-01',  310.00, 20,  250.00),
('West',  'Food',        'retail',  '2024-06-15',  150.00, 8,   100.00),
('North', 'Electronics', 'online',  '2024-04-20', 1500.00, 3,   600.00),
('North', 'Clothing',    'retail',  '2024-05-25',  290.00, 3,   180.00),
('South', 'Electronics', 'online',  '2024-05-10', 1900.00, 2,   800.00),
('South', 'Food',        'retail',  '2024-06-20',  200.00, 11,  170.00),
('West',  'Clothing',    'online',  '2024-04-25',  550.00, 6,   180.00),
('West',  'Electronics', 'retail',  '2024-06-10', 1100.00, 1,   750.00);
