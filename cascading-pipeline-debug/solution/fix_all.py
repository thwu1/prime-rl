#!/usr/bin/env python3
"""
Fix the Python config generator and Go prefix manager bugs.
The Rust config loader fix is handled separately via main_fixed.rs.
"""
import re


def fix_config_generator():
    """
    Fix: Add schema_name = 'default' filter to the SQL query.

    The bug: The query selects from feature_columns WHERE table_name = '...'
    but does not filter by schema_name. After the permissions change made the
    'r0' replica schema visible, the query returns duplicate rows from both
    'default' and 'r0' schemas, doubling the feature count from ~105 to ~210.
    """
    path = "/app/configgen/generate.py"
    with open(path) as f:
        content = f.read()

    # Add the schema filter to the WHERE clause
    old = "WHERE table_name = 'http_requests_features'"
    new = "WHERE table_name = 'http_requests_features'\n        AND schema_name = 'default'"

    if old not in content:
        print(f"[fix_configgen] WARNING: expected SQL pattern not found in {path}")
        return False

    content = content.replace(old, new)

    with open(path, 'w') as f:
        f.write(content)
    print("[fix] Config generator: added schema_name = 'default' filter to SQL query")
    return True


def fix_prefix_manager():
    """
    Fix: Replace Query().Get("pending_delete") != "" with Query().Has("pending_delete").

    The bug: url.Query().Get("pending_delete") returns "" (empty string) when the
    parameter is present but has no value (e.g., ?pending_delete without =true).
    The check `v != ""` then evaluates to false, causing the code to fall through
    and treat the request as "list all prefixes" instead of "list pending deletions".
    The cleanup task then deletes ALL prefixes instead of only pending ones.

    url.Values.Has() correctly returns true when the key exists regardless of value.
    """
    path = "/app/prefixmgr/main.go"
    with open(path) as f:
        content = f.read()

    fixes_applied = 0

    # Fix FetchPrefixes method
    old_fetch = 'if v := params.Get("pending_delete"); v != "" {'
    new_fetch = 'if params.Has("pending_delete") {'
    if old_fetch in content:
        content = content.replace(old_fetch, new_fetch)
        fixes_applied += 1

    # Fix HandlePrefixes method
    old_handle = 'if v := r.URL.Query().Get("pending_delete"); v != "" {'
    new_handle = 'if r.URL.Query().Has("pending_delete") {'
    if old_handle in content:
        content = content.replace(old_handle, new_handle)
        fixes_applied += 1

    if fixes_applied == 0:
        print(f"[fix_prefixmgr] WARNING: expected patterns not found in {path}")
        return False

    with open(path, 'w') as f:
        f.write(content)
    print(f"[fix] Prefix manager: replaced {fixes_applied} Get()!=\"\" checks with Has()")
    return True


if __name__ == "__main__":
    ok = True
    ok = fix_config_generator() and ok
    ok = fix_prefix_manager() and ok
    if ok:
        print("[fix] All Python/Go fixes applied successfully")
    else:
        print("[fix] WARNING: Some fixes may not have applied correctly")
        exit(1)
