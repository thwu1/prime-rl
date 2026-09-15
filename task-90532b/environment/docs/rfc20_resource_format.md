# RFC 20: Resource Set Specification (Version 1)

## DESCRIPTION

The resource set describes available HPC resources. In this environment the
canonical representation is a SQLite database (`cluster.db`), but the
conceptual model follows RFC 20.

## RESOURCE MODEL

Each compute node is identified by a unique integer **rank**. A rank has:

- **cores**: number of CPU cores available.
- **gpus**: number of GPU devices available (0 if none).
- **properties**: a set of string tags describing the node's capabilities
  (e.g., `"gpu"`, `"highmem"`, `"standard"`).

A single node may possess multiple properties simultaneously. For example,
a node with both `"gpu"` and `"highmem"` properties is eligible for any
queue requiring either or both properties.

## DATABASE SCHEMA

The cluster database contains the following tables (query with
`sqlite3 /app/cluster.db ".schema"`):

- **nodes** -- One row per rank: `rank`, `hostname`, `cores`, `gpus`.
- **node_properties** -- Property assignments: `rank`, `property`.
  A rank appears once per property it possesses.
- **node_topology** -- Physical placement: `rank`, `rack`, `switch_id`.

## IDSET FORMAT

When idsets appear in event data (e.g., drain targets), they use compact
range notation:

| Idset         | Expanded                                  |
|---------------|-------------------------------------------|
| `"0"`         | {0}                                       |
| `"0-3"`       | {0, 1, 2, 3}                              |
| `"0-3,8-15"`  | {0, 1, 2, 3, 8, 9, 10, 11, 12, 13, 14, 15} |
| `"4-7,12-15"` | {4, 5, 6, 7, 12, 13, 14, 15}             |

Ranges are inclusive on both ends. Multiple ranges or singletons are
separated by commas.

## EXAMPLE QUERIES

Count nodes with GPU capability:

    SELECT COUNT(*) FROM nodes n
    JOIN node_properties p ON n.rank = p.rank
    WHERE p.property = 'gpu';

List all properties for rank 12:

    SELECT property FROM node_properties WHERE rank = 12;

Find nodes possessing both 'gpu' and 'highmem':

    SELECT n.rank, n.hostname, n.cores, n.gpus
    FROM nodes n
    WHERE n.rank IN (
        SELECT rank FROM node_properties WHERE property = 'gpu'
        INTERSECT
        SELECT rank FROM node_properties WHERE property = 'highmem'
    );

## SEE ALSO

`scheduling_semantics.md`, `queue_configuration.md`
