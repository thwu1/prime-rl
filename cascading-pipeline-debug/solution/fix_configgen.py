#!/usr/bin/env python3
"""
Fix the config generator SQL query to filter by schema.

"""

path = "/app/configgen/generate.py"
with open(path) as f:
    content = f.read()

old = "WHERE table_name = 'http_requests_features'"
new = "WHERE table_name = 'http_requests_features'\n        AND schema_name = 'default'"

if old not in content:
    print("[fix_configgen] Pattern not found — may already be fixed")
else:
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    print("[fix] Added schema_name = 'default' filter to SQL query")
