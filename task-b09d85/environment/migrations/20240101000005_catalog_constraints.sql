ALTER TABLE categories ADD CONSTRAINT categories_name_key UNIQUE (name);

ALTER TABLE products ADD CONSTRAINT fk_products_category
    FOREIGN KEY (category) REFERENCES categories(name);

CREATE MATERIALIZED VIEW product_catalog AS
    SELECT p.id, p.name AS product_name, p.price, p.stock,
           COALESCE(p.category, 'Uncategorized') AS category,
           p.description
    FROM products p
    LEFT JOIN categories c ON p.category = c.name;
