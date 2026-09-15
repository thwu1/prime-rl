MODEL (
  name raw.seed_orders,
  kind SEED (
    path '$root/seeds/orders.csv'
  ),
  columns (
    order_id INT,
    customer_id INT,
    product_id INT,
    amount DOUBLE,
    order_date TEXT,
    status TEXT
  ),
  grain order_id
);
