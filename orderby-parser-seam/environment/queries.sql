-- @name: alias_shadow
-- Intended: Show negated 'a' values, sorted by the ORIGINAL column 'a' ascending
SELECT -a AS a FROM nums ORDER BY a;

-- @name: quoted_alias_silent
-- Intended: Show items with negated price as "Price", sorted by "Price" ascending (most negative first)
SELECT item, -price AS "Price" FROM inventory ORDER BY price;

-- @name: group_order_clash
-- Intended: Group items into price/10 buckets, count per bucket, sort by bucket ascending
SELECT price / 10 AS price, count(*) AS cnt FROM inventory GROUP BY price ORDER BY price;

-- @name: window_alias
-- Intended: Rank items by price descending within each category (most expensive = rank 1)
SELECT item, category, -price AS neg_price,
       row_number() OVER (PARTITION BY category ORDER BY neg_price) AS rnk
FROM inventory
ORDER BY category, rnk;

-- @name: collate_trap
-- Intended: List items sorted alphabetically by name using C collation
SELECT item AS product FROM inventory ORDER BY product COLLATE "C";

-- @name: unary_plus
-- Intended: Show negated 'a' values sorted by the ALIAS ascending (-3, -2, -1, 0)
SELECT -a AS a FROM nums ORDER BY +a;

-- @name: union_expression
-- Intended: Combine tools and fasteners, sorted by price descending
(SELECT item, price FROM inventory WHERE category = 'tools')
UNION ALL
(SELECT item, price FROM inventory WHERE category = 'fasteners')
ORDER BY -price;

-- @name: cast_scope
-- Intended: Show items with price aliased as cost, sorted by cost ascending
SELECT item, price AS cost FROM inventory ORDER BY cost::float;

-- @name: aggregate_window
-- Intended: Rank categories by total price (highest total = rank 1), show results ordered by category
SELECT category, SUM(price) AS total,
       RANK() OVER (ORDER BY total DESC) AS rnk
FROM inventory
GROUP BY category
ORDER BY category;

-- @name: distinct_on_order
-- Intended: Show the cheapest item per category, sorted by category name
SELECT DISTINCT ON (category) item, category, price
FROM inventory
ORDER BY price;
