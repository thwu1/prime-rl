
"""Tests for persistent red-black tree deletion in Lua."""

import subprocess
import random


def run_lua(code, timeout=60):
    """Run Lua code via subprocess and return the result."""
    result = subprocess.run(
        ["lua5.4", "-"],
        input=code,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


PRELUDE = 'local rbtree = dofile("/app/rbtree.lua")\n'


# -- sanity ----------------------------------------------------------------

def test_module_loads():
    code = PRELUDE + """
    local t = rbtree.new()
    assert(rbtree.count(t) == 0)
    t = rbtree.insert(t, 10, "ten")
    assert(rbtree.count(t) == 1)
    assert(rbtree.search(t, 10) == "ten")
    assert(rbtree.search(t, 99) == nil)
    local ok, err = rbtree.validate(t)
    assert(ok, err)
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


# -- basic deletion --------------------------------------------------------

def test_delete_single_element():
    """Delete the only element from a one-element tree."""
    code = PRELUDE + """
    local t = rbtree.new()
    t = rbtree.insert(t, 42, "answer")
    t = rbtree.delete(t, 42)
    assert(rbtree.count(t) == 0, "count should be 0")
    assert(rbtree.search(t, 42) == nil, "should not find deleted key")
    local ok, err = rbtree.validate(t)
    assert(ok, err)
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


def test_delete_each_from_three():
    """Delete each element from a three-element tree, one at a time."""
    code = PRELUDE + """
    local base = rbtree.new()
    base = rbtree.insert(base, 2, "b")
    base = rbtree.insert(base, 1, "a")
    base = rbtree.insert(base, 3, "c")

    for _, del_key in ipairs({1, 2, 3}) do
        local t = rbtree.delete(base, del_key)
        assert(rbtree.count(t) == 2,
            "count after deleting " .. del_key .. ": " .. rbtree.count(t))
        assert(not rbtree.contains(t, del_key),
            del_key .. " should be gone")
        for _, k in ipairs({1, 2, 3}) do
            if k ~= del_key then
                assert(rbtree.contains(t, k),
                    k .. " should still be present")
            end
        end
        local ok, err = rbtree.validate(t)
        assert(ok, "invariant after deleting " .. del_key .. ": " .. tostring(err))
    end
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


def test_delete_nonexistent_key():
    """Deleting a key not in the tree returns the same tree object."""
    code = PRELUDE + """
    local t = rbtree.new()
    t = rbtree.insert(t, 5, "five")
    t = rbtree.insert(t, 10, "ten")
    local t2 = rbtree.delete(t, 999)
    -- must be the exact same table (identity)
    assert(rawequal(t, t2), "should return same tree for missing key")
    assert(rbtree.count(t2) == 2)
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


# -- sequential delete-all -------------------------------------------------

def test_delete_all_forward():
    """Insert 1..25, delete in ascending order, validate after each."""
    code = PRELUDE + """
    local t = rbtree.new()
    for i = 1, 25 do
        t = rbtree.insert(t, i, i * 100)
    end
    assert(rbtree.count(t) == 25)
    for i = 1, 25 do
        t = rbtree.delete(t, i)
        local ok, err = rbtree.validate(t)
        if not ok then
            io.stderr:write("after deleting " .. i .. ": " .. err .. "\\n")
            os.exit(1)
        end
        assert(rbtree.count(t) == 25 - i,
            "count after deleting " .. i .. ": " .. rbtree.count(t))
    end
    assert(rbtree.count(t) == 0)
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


def test_delete_all_reverse():
    """Insert 1..25, delete in descending order, validate after each."""
    code = PRELUDE + """
    local t = rbtree.new()
    for i = 1, 25 do
        t = rbtree.insert(t, i, i * 100)
    end
    for i = 25, 1, -1 do
        t = rbtree.delete(t, i)
        local ok, err = rbtree.validate(t)
        if not ok then
            io.stderr:write("after deleting " .. i .. ": " .. err .. "\\n")
            os.exit(1)
        end
    end
    assert(rbtree.count(t) == 0)
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


# -- persistence -----------------------------------------------------------

def test_persistence_after_delete():
    """Old tree versions are unchanged after deletion."""
    code = PRELUDE + """
    local t1 = rbtree.new()
    t1 = rbtree.insert(t1, 5, "five")
    t1 = rbtree.insert(t1, 3, "three")
    t1 = rbtree.insert(t1, 7, "seven")
    t1 = rbtree.insert(t1, 1, "one")
    t1 = rbtree.insert(t1, 9, "nine")

    local t2 = rbtree.delete(t1, 3)
    local t3 = rbtree.delete(t2, 7)

    -- t1 must be completely unchanged
    assert(rbtree.count(t1) == 5, "t1 count: " .. rbtree.count(t1))
    assert(rbtree.search(t1, 3) == "three")
    assert(rbtree.search(t1, 7) == "seven")
    assert(rbtree.search(t1, 1) == "one")
    assert(rbtree.search(t1, 5) == "five")
    assert(rbtree.search(t1, 9) == "nine")

    -- t2: key 3 removed
    assert(rbtree.count(t2) == 4, "t2 count: " .. rbtree.count(t2))
    assert(rbtree.search(t2, 3) == nil)
    assert(rbtree.search(t2, 7) == "seven")

    -- t3: keys 3 and 7 removed
    assert(rbtree.count(t3) == 3, "t3 count: " .. rbtree.count(t3))
    assert(rbtree.search(t3, 3) == nil)
    assert(rbtree.search(t3, 7) == nil)
    assert(rbtree.search(t3, 5) == "five")

    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


# -- sorted order ----------------------------------------------------------

def test_sorted_order_after_deletions():
    """Sorted traversal is correct after a mix of inserts and deletes."""
    code = PRELUDE + """
    local t = rbtree.new()
    local keys = {15, 3, 22, 8, 1, 17, 25, 10, 6, 12, 20, 28, 4, 14}
    for _, k in ipairs(keys) do
        t = rbtree.insert(t, k, k)
    end
    -- delete several
    for _, k in ipairs({8, 22, 1, 14, 25}) do
        t = rbtree.delete(t, k)
    end
    local sorted = rbtree.to_sorted_list(t)
    local expected = {3, 4, 6, 10, 12, 15, 17, 20, 28}
    assert(#sorted == #expected,
        "length: expected " .. #expected .. " got " .. #sorted)
    for i, e in ipairs(expected) do
        assert(sorted[i][1] == e,
            "pos " .. i .. ": expected " .. e .. " got " .. tostring(sorted[i][1]))
    end
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


# -- double-black propagation ----------------------------------------------

def test_double_black_cases():
    """Exercises deletion of black leaves that forces double-black
    propagation and negative-black rebalancing."""
    code = PRELUDE + """
    local t = rbtree.new()
    -- Build a moderately deep tree
    for _, k in ipairs({4, 2, 6, 1, 3, 5, 7}) do
        t = rbtree.insert(t, k, k * 10)
    end
    local ok, err = rbtree.validate(t)
    assert(ok, "initial: " .. tostring(err))

    -- Systematically delete leaves, checking invariants each time
    for _, dk in ipairs({1, 7, 3, 5, 2, 6, 4}) do
        t = rbtree.delete(t, dk)
        ok, err = rbtree.validate(t)
        assert(ok, "after deleting " .. dk .. ": " .. tostring(err))
    end
    assert(rbtree.count(t) == 0)
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


# -- random operations (large) --------------------------------------------

def test_random_mixed_operations():
    """500 random inserts/deletes, validate at end."""
    rng = random.Random(12345)
    keys_in_tree = set()
    universe = list(range(1, 301))

    lua_ops = []
    for _ in range(500):
        if not keys_in_tree or rng.random() < 0.6:
            key = rng.choice(universe)
            lua_ops.append(f"    t = rbtree.insert(t, {key}, {key * 7})")
            keys_in_tree.add(key)
        else:
            key = rng.choice(sorted(keys_in_tree))
            lua_ops.append(f"    t = rbtree.delete(t, {key})")
            keys_in_tree.discard(key)

    expected_count = len(keys_in_tree)
    expected_keys_lua = "{" + ",".join(str(k) for k in sorted(keys_in_tree)) + "}"

    code = (
        PRELUDE
        + "    local t = rbtree.new()\n"
        + "\n".join(lua_ops)
        + f"""
    local ok, err = rbtree.validate(t)
    if not ok then
        io.stderr:write("INVARIANT: " .. err .. "\\n")
        os.exit(1)
    end
    if rbtree.count(t) ~= {expected_count} then
        io.stderr:write("COUNT: expected {expected_count}, got "
            .. rbtree.count(t) .. "\\n")
        os.exit(1)
    end
    local expected_keys = {expected_keys_lua}
    for _, k in ipairs(expected_keys) do
        local v = rbtree.search(t, k)
        if v ~= k * 7 then
            io.stderr:write("SEARCH: key " .. k .. " expected "
                .. (k * 7) .. " got " .. tostring(v) .. "\\n")
            os.exit(1)
        end
    end
    print("PASS")
"""
    )
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


def test_invariants_after_every_operation():
    """100 random operations, validate after EACH one."""
    rng = random.Random(9999)
    keys_in_tree = set()

    lua_lines = [
        PRELUDE,
        "    local t = rbtree.new()",
        "    local ok, err",
    ]
    step = 0
    for _ in range(100):
        if not keys_in_tree or rng.random() < 0.55:
            key = rng.randint(1, 50)
            lua_lines.append(f"    t = rbtree.insert(t, {key}, {key})")
            keys_in_tree.add(key)
        else:
            key = rng.choice(sorted(keys_in_tree))
            lua_lines.append(f"    t = rbtree.delete(t, {key})")
            keys_in_tree.discard(key)
        lua_lines.append(
            f'    ok, err = rbtree.validate(t)\n'
            f'    if not ok then\n'
            f'        io.stderr:write("Step {step}: " .. err .. "\\n")\n'
            f'        os.exit(1)\n'
            f'    end'
        )
        step += 1

    lua_lines.append('    print("PASS")')
    code = "\n".join(lua_lines)
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout


def test_delete_internal_nodes():
    """Delete internal (non-leaf) nodes that have two children,
    exercising the find-min + swap path of remove_node."""
    code = PRELUDE + """
    local t = rbtree.new()
    -- Insert in an order that creates a multi-level tree
    for _, k in ipairs({10, 5, 15, 3, 7, 12, 20, 1, 4, 6, 8, 11, 13, 18, 25}) do
        t = rbtree.insert(t, k, k)
    end
    assert(rbtree.count(t) == 15)

    -- Delete internal nodes (nodes with two children)
    for _, dk in ipairs({5, 15, 10}) do
        t = rbtree.delete(t, dk)
        local ok, err = rbtree.validate(t)
        assert(ok, "after deleting " .. dk .. ": " .. tostring(err))
        assert(not rbtree.contains(t, dk), dk .. " should be gone")
    end
    assert(rbtree.count(t) == 12)

    -- Remaining keys should all be present and in order
    local sorted = rbtree.to_sorted_list(t)
    local expected = {1, 3, 4, 6, 7, 8, 11, 12, 13, 18, 20, 25}
    assert(#sorted == #expected, "length mismatch")
    for i, e in ipairs(expected) do
        assert(sorted[i][1] == e,
            "pos " .. i .. ": expected " .. e .. " got " .. tostring(sorted[i][1]))
    end
    print("PASS")
    """
    r = run_lua(code)
    assert r.returncode == 0, f"Lua error: {r.stderr}"
    assert "PASS" in r.stdout
