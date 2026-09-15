# Report Specification

Each query in `queries.sql` is tagged with `-- @name: <name>`. Below is the intended
behavior and expected output for each query. All queries must execute without error and
produce exactly the rows shown, in the order shown.

## alias_shadow
Show negated values of column `a` from `nums`, sorted by the **original** column `a` ascending (0, 1, 2, 3), projecting `-a`.

```
  a
----
  0
 -1
 -2
 -3
```

## quoted_alias_silent
Show items with negated price aliased as `"Price"`, sorted by `"Price"` ascending (most negative first = highest original price first).

```
  item  | Price
--------+-------
 Valve  |   -45
 Pipe   |   -30
 Wrench |   -25
 Hammer |   -18
 Switch |   -15
 Wire   |   -10
 Bolt   |    -2
 Nail   |    -1
```

## group_order_clash
Group items into `price / 10` buckets, count items per bucket, sort by bucket ascending. Must return exactly 5 rows (5 distinct buckets), not 8.

```
 price | cnt
-------+-----
     0 |   2
     1 |   3
     2 |   1
     3 |   1
     4 |   1
```

## window_alias
Rank items by price descending within each category (most expensive item gets rank 1). Include negated price column. Sort output by category then rank.

```
  item  |  category  | neg_price | rnk
--------+------------+-----------+-----
 Switch | electrical |       -15 |   1
 Wire   | electrical |       -10 |   2
 Bolt   | fasteners  |        -2 |   1
 Nail   | fasteners  |        -1 |   2
 Valve  | plumbing   |       -45 |   1
 Pipe   | plumbing   |       -30 |   2
 Wrench | tools      |       -25 |   1
 Hammer | tools      |       -18 |   2
```

## collate_trap
List all items (aliased as `product`), sorted alphabetically using `C` collation.

```
 product
---------
 Bolt
 Hammer
 Nail
 Pipe
 Switch
 Valve
 Wire
 Wrench
```

## unary_plus
Show negated values of column `a` from `nums`, sorted by the **alias** `a` ascending (alias value is `-a`, so ascending gives -3, -2, -1, 0).

```
  a
----
 -3
 -2
 -1
  0
```

## union_expression
Combine tools and fasteners via UNION ALL, sorted by price descending.

```
  item  | price
--------+-------
 Wrench |    25
 Hammer |    18
 Bolt   |     2
 Nail   |     1
```

## cast_scope
Show items with price aliased as `cost`, sorted by cost ascending (cheapest first).

```
  item  | cost
--------+------
 Nail   |    1
 Bolt   |    2
 Wire   |   10
 Switch |   15
 Hammer |   18
 Wrench |   25
 Pipe   |   30
 Valve  |   45
```

## aggregate_window
Show each category with its total price and rank (highest total = rank 1). Sort output alphabetically by category.

```
  category  | total | rnk
------------+-------+-----
 electrical |    25 |   3
 fasteners  |     3 |   4
 plumbing   |    75 |   1
 tools      |    43 |   2
```

## distinct_on_order
Show the cheapest item per category, sorted by category name.

```
  item  |  category  | price
--------+------------+-------
 Wire   | electrical |    10
 Nail   | fasteners  |     1
 Pipe   | plumbing   |    30
 Hammer | tools      |    18
```
