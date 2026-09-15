#!/usr/bin/env python3
"""Tree query pipeline CLI.

Routes commands to the appropriate pipeline modules:
  build     - reads tree from SQLite, builds index in DuckDB
  ancestors - retrieves ancestor path from DuckDB index
  lca       - finds lowest common ancestor via DuckDB index
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TREE_DB = '/app/tree.db'
ANALYTICS_DB = '/app/analytics.duckdb'


def main():
    if len(sys.argv) < 2:
        print("Usage: api.py {build|ancestors|lca} [args...]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'build':
        from pipeline.index import build_index
        build_index(TREE_DB, ANALYTICS_DB)
        print("Build complete.", file=sys.stderr)
    elif command == 'ancestors':
        if len(sys.argv) != 3:
            print("Usage: api.py ancestors <node_id>", file=sys.stderr)
            sys.exit(1)
        from pipeline.query import query_ancestors
        result = query_ancestors(ANALYTICS_DB, int(sys.argv[2]))
        print(json.dumps(result))
    elif command == 'lca':
        if len(sys.argv) != 4:
            print("Usage: api.py lca <node_a> <node_b>", file=sys.stderr)
            sys.exit(1)
        from pipeline.query import query_lca
        result = query_lca(ANALYTICS_DB, int(sys.argv[2]), int(sys.argv[3]))
        print(result)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
