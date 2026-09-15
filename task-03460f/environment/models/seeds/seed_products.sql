MODEL (
  name raw.seed_products,
  kind SEED (
    path '$root/seeds/products.csv'
  ),
  columns (
    product_id INT,
    product_name TEXT,
    category TEXT,
    unit_price DOUBLE
  ),
  grain product_id
);
