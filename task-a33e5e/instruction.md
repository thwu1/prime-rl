Implement a star tree index in `/app/star_tree.py` — a pre-aggregation data structure used in OLAP-style analytics engines (such as OpenSearch's Star Tree Index) to achieve orders-of-magnitude faster aggregation queries over high-volume datasets.

## Background

A star tree organizes data along an ordered list of dimensions in a tree. Each level of the tree corresponds to one dimension; child nodes at that level represent distinct values. In addition, a special "star" node (keyed as the string `'*'`) may be created at each level to aggregate across ALL values of that dimension, enabling fast query evaluation when a dimension is unconstrained. Leaf nodes store pre-computed metric aggregations.

Derived aggregations like AVG must be internally decomposed into primitives (SUM + COUNT) so they remain correct after tree merges — averaging two averages is wrong when the underlying counts differ.

## Data and Config

- `/app/data/sales_data_segment_a.csv` and `/app/data/sales_data_segment_b.csv` — two data segments with dimension columns (region, category, channel, day_of_week) and metric columns (revenue, quantity, discount)
- `/app/config.json` — specifies ordered dimensions, metrics with their required aggregation types, `max_leaf_documents` (below this count a node becomes a leaf), and `star_node_creation_threshold` (minimum distinct values at a level to create a star node)

## Required API — `/app/star_tree.py`

- `STAR = '*'`
- `StarTreeNode` — attributes: `children: Dict[str, StarTreeNode]`, `document_count: int`, `dimension_value: str`, `dimension_index: int`
- `StarTreeBuilder(config: dict)` with `.build(data: List[dict]) -> StarTreeNode` and `.get_tree() -> StarTreeNode`
- `StarTreeQueryEngine(root: StarTreeNode, config: dict)`:
  - `.query(constraints: dict, metric: str, agg_type: str) -> Optional[float]` — point aggregation with partial dimension constraints; returns `None` when no data matches
  - `.group_by_query(constraints: dict, group_by_dimension: str, metric: str, agg_type: str) -> Dict[str, float]` — returns `{dimension_value: result}` partitioned by the group-by dimension
- `merge_star_trees(tree_a: StarTreeNode, tree_b: StarTreeNode, config: dict) -> StarTreeNode` — merge two star trees, correctly combining pre-aggregated metrics

Star nodes are created only when distinct value count >= `star_node_creation_threshold`. Nodes split into children only when document count > `max_leaf_documents` and dimensions remain. Unconstrained dimensions in queries use star nodes when available; otherwise iterate all non-star children.

The dataset contains 25,000 records per segment with 5 regions, 7 product categories, 4 channels, and 7 days-of-week. Segment A total revenue is `4358853.35`, the merged total across both segments is `8740891.04`. Your implementation must reproduce these values exactly when queried.