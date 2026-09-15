
import subprocess
import pytest


LUA_PREAMBLE = 'package.path="/app/?.lua;"..package.path; '


def run_lua(code, timeout=30):
    result = subprocess.run(
        ["lua5.4", "-e", LUA_PREAMBLE + code],
        capture_output=True, text=True, timeout=timeout,
    )
    return result


def assert_lua_pass(code, timeout=30):
    result = run_lua(code, timeout)
    assert result.returncode == 0, (
        f"Lua script failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "PASS" in result.stdout, (
        f"PASS not found in output.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# Lua helper: checks red-black tree invariants (embedded in tests that need it)
RB_CHECK = '''
local function check_rb(node, depth)
    if not node then return 0 end
    local color = node[1]
    assert(color == 0 or color == 1,
           "invalid color " .. tostring(color) .. " at depth " .. depth)
    if color == 0 then
        if node[2] and node[2][1] == 0 then
            error("red-red violation (left) at depth " .. depth)
        end
        if node[5] and node[5][1] == 0 then
            error("red-red violation (right) at depth " .. depth)
        end
    end
    local lb = check_rb(node[2], depth + 1)
    local rb = check_rb(node[5], depth + 1)
    assert(lb == rb,
           "black-depth mismatch at depth " .. depth ..
           ": left=" .. lb .. " right=" .. rb)
    return lb + (color == 1 and 1 or 0)
end

local function verify_rb(tree)
    if tree.root then
        assert(tree.root[1] == 1, "root must be black")
        check_rb(tree.root, 0)
    end
end

local function tree_height(node)
    if not node then return 0 end
    local lh = tree_height(node[2])
    local rh = tree_height(node[5])
    return 1 + (lh > rh and lh or rh)
end

local function count_nodes(node)
    if not node then return 0 end
    return 1 + count_nodes(node[2]) + count_nodes(node[5])
end
'''


# ------------------------------------------------------------------
# Basic deletion
# ------------------------------------------------------------------

def test_dissoc_single():
    assert_lua_pass('''
        local t = require("treemap")
        local m = t.new()
        m = t.assoc(m, "a", 1)
        m = t.assoc(m, "b", 2)
        local m2 = t.dissoc(m, "a")
        assert(t.count(m2) == 1)
        assert(t.get(m2, "a") == nil)
        assert(t.get(m2, "b") == 2)
        print("PASS")
    ''')


def test_dissoc_nonexistent():
    assert_lua_pass('''
        local t = require("treemap")
        local m = t.new()
        m = t.assoc(m, "a", 1)
        local m2 = t.dissoc(m, "z")
        assert(m == m2, "dissoc of absent key must return same map object")
        assert(t.count(m2) == 1)
        print("PASS")
    ''')


def test_dissoc_to_empty():
    assert_lua_pass('''
        local t = require("treemap")
        local m = t.assoc(t.new(), "a", 1)
        local m2 = t.dissoc(m, "a")
        assert(t.count(m2) == 0)
        assert(t.get(m2, "a") == nil)
        print("PASS")
    ''')


def test_dissoc_empty_map():
    assert_lua_pass('''
        local t = require("treemap")
        local m = t.new()
        local m2 = t.dissoc(m, "anything")
        assert(m == m2, "dissoc on empty must return same map object")
        assert(t.count(m2) == 0)
        print("PASS")
    ''')


def test_dissoc_all_elements():
    assert_lua_pass('''
        local t = require("treemap")
        local m = t.new()
        for i = 1, 20 do
            m = t.assoc(m, i, i * 100)
        end
        assert(t.count(m) == 20)
        for i = 1, 20 do
            m = t.dissoc(m, i)
        end
        assert(t.count(m) == 0)
        print("PASS")
    ''')


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------

def test_persistence_dissoc():
    assert_lua_pass('''
        local t = require("treemap")
        local m1 = t.new()
        m1 = t.assoc(m1, 1, 10)
        m1 = t.assoc(m1, 2, 20)
        m1 = t.assoc(m1, 3, 30)
        local m2 = t.dissoc(m1, 2)
        assert(t.count(m1) == 3, "m1 count should be 3")
        assert(t.get(m1, 2) == 20, "m1 must still contain key 2")
        assert(t.count(m2) == 2)
        assert(t.get(m2, 2) == nil)
        assert(t.get(m2, 1) == 10)
        assert(t.get(m2, 3) == 30)
        print("PASS")
    ''')


def test_deep_persistence_chain():
    assert_lua_pass('''
        local t = require("treemap")
        local versions = {}
        local m = t.new()
        for i = 1, 50 do
            m = t.assoc(m, i, i * 10)
            versions[i] = m
        end
        -- Delete odd keys from latest
        local m_del = versions[50]
        for i = 1, 49, 2 do
            m_del = t.dissoc(m_del, i)
        end
        -- Verify all old versions unchanged
        for v = 1, 50 do
            assert(t.count(versions[v]) == v,
                   "v" .. v .. " count=" .. t.count(versions[v]))
            for i = 1, v do
                local val = t.get(versions[v], i)
                assert(val == i * 10,
                       "v" .. v .. " key " .. i .. "=" .. tostring(val))
            end
        end
        -- Verify deleted version
        assert(t.count(m_del) == 25)
        for i = 2, 50, 2 do
            assert(t.get(m_del, i) == i * 10)
        end
        for i = 1, 49, 2 do
            assert(t.get(m_del, i) == nil)
        end
        print("PASS")
    ''', timeout=60)


# ------------------------------------------------------------------
# Sorted order after deletion
# ------------------------------------------------------------------

def test_sorted_order_after_deletion():
    assert_lua_pass('''
        local t = require("treemap")
        local m = t.new()
        for i = 1, 30 do
            m = t.assoc(m, i, i)
        end
        -- Delete every third element
        for i = 3, 30, 3 do
            m = t.dissoc(m, i)
        end
        -- Verify iteration is sorted
        local prev = nil
        local count = 0
        for k, v in t.pairs(m) do
            if prev then
                assert(k > prev, "out of order: " .. tostring(prev) .. " >= " .. tostring(k))
            end
            prev = k
            count = count + 1
        end
        assert(count == 20, "expected 20, got " .. count)
        print("PASS")
    ''')


# ------------------------------------------------------------------
# Red-black invariants
# ------------------------------------------------------------------

def test_rb_invariants_after_insertions():
    assert_lua_pass(RB_CHECK + '''
        local t = require("treemap")
        local m = t.new()
        for i = 1, 500 do
            m = t.assoc(m, i, i)
        end
        verify_rb(m)
        assert(count_nodes(m.root) == t.count(m))
        print("PASS")
    ''', timeout=60)


def test_rb_invariants_after_deletions():
    assert_lua_pass(RB_CHECK + '''
        local t = require("treemap")
        local m = t.new()
        for i = 1, 200 do
            m = t.assoc(m, i, i * 10)
        end
        -- Delete first half
        for i = 1, 100 do
            m = t.dissoc(m, i)
        end
        verify_rb(m)
        assert(t.count(m) == 100)
        assert(count_nodes(m.root) == 100)
        print("PASS")
    ''', timeout=60)


def test_rb_invariants_interleaved():
    """Insert and delete in alternating patterns, then verify invariants."""
    assert_lua_pass(RB_CHECK + '''
        local t = require("treemap")
        local m = t.new()
        -- Phase 1: insert 300
        for i = 1, 300 do
            m = t.assoc(m, i, i)
        end
        -- Phase 2: delete even numbers
        for i = 2, 300, 2 do
            m = t.dissoc(m, i)
        end
        verify_rb(m)
        assert(t.count(m) == 150)
        -- Phase 3: re-insert evens with new values
        for i = 2, 300, 2 do
            m = t.assoc(m, i, i * 100)
        end
        verify_rb(m)
        assert(t.count(m) == 300)
        -- Phase 4: delete odd numbers
        for i = 1, 299, 2 do
            m = t.dissoc(m, i)
        end
        verify_rb(m)
        assert(t.count(m) == 150)
        assert(count_nodes(m.root) == 150)
        -- Verify values
        for i = 2, 300, 2 do
            assert(t.get(m, i) == i * 100,
                   "key " .. i .. " expected " .. (i*100) .. " got " .. tostring(t.get(m, i)))
        end
        print("PASS")
    ''', timeout=60)


# ------------------------------------------------------------------
# Height bounds (must be O(log n))
# ------------------------------------------------------------------

def test_height_bounds():
    assert_lua_pass(RB_CHECK + '''
        local t = require("treemap")
        local m = t.new()
        local N = 1000
        for i = 1, N do
            m = t.assoc(m, i, i)
        end
        -- Delete half
        for i = 1, N, 2 do
            m = t.dissoc(m, i)
        end
        local n = t.count(m)
        local h = tree_height(m.root)
        -- RBT height bound: h <= 2 * log2(n + 1)
        local max_h = math.ceil(2 * math.log(n + 1) / math.log(2))
        assert(h <= max_h,
               "height " .. h .. " exceeds bound " .. max_h .. " for n=" .. n)
        verify_rb(m)
        print("PASS")
    ''', timeout=60)


# ------------------------------------------------------------------
# Stress tests
# ------------------------------------------------------------------

def test_large_scale_delete():
    assert_lua_pass(RB_CHECK + '''
        local t = require("treemap")
        local m = t.new()
        local N = 2000
        for i = 1, N do
            m = t.assoc(m, "key" .. i, i)
        end
        assert(t.count(m) == N)
        -- Delete odd-indexed keys
        for i = 1, N, 2 do
            m = t.dissoc(m, "key" .. i)
        end
        assert(t.count(m) == 1000)
        verify_rb(m)
        -- Verify remaining keys
        for i = 2, N, 2 do
            assert(t.get(m, "key" .. i) == i,
                   "missing key" .. i)
        end
        for i = 1, N, 2 do
            assert(t.get(m, "key" .. i) == nil,
                   "key" .. i .. " should be deleted")
        end
        print("PASS")
    ''', timeout=60)


def test_reverse_delete_order():
    """Delete keys in reverse order of insertion."""
    assert_lua_pass(RB_CHECK + '''
        local t = require("treemap")
        local m = t.new()
        for i = 1, 500 do
            m = t.assoc(m, i, i)
        end
        for i = 500, 1, -1 do
            m = t.dissoc(m, i)
            if m.root then
                verify_rb(m)
            end
        end
        assert(t.count(m) == 0)
        print("PASS")
    ''', timeout=60)


def test_delete_then_reinsert():
    assert_lua_pass(RB_CHECK + '''
        local t = require("treemap")
        local m = t.new()
        for i = 1, 100 do
            m = t.assoc(m, i, i)
        end
        -- Delete all
        for i = 1, 100 do
            m = t.dissoc(m, i)
        end
        assert(t.count(m) == 0)
        -- Reinsert
        for i = 1, 100 do
            m = t.assoc(m, i, i * 7)
        end
        assert(t.count(m) == 100)
        verify_rb(m)
        for i = 1, 100 do
            assert(t.get(m, i) == i * 7)
        end
        print("PASS")
    ''', timeout=60)


# ------------------------------------------------------------------
# Mixed key types
# ------------------------------------------------------------------

def test_mixed_key_types_dissoc():
    assert_lua_pass('''
        local t = require("treemap")
        local m = t.new()
        m = t.assoc(m, 1, "one")
        m = t.assoc(m, 2, "two")
        m = t.assoc(m, "hello", "world")
        m = t.assoc(m, true, "yes")
        assert(t.count(m) == 4)
        m = t.dissoc(m, 2)
        assert(t.count(m) == 3)
        assert(t.get(m, 2) == nil)
        assert(t.get(m, 1) == "one")
        assert(t.get(m, "hello") == "world")
        assert(t.get(m, true) == "yes")
        m = t.dissoc(m, true)
        assert(t.count(m) == 2)
        assert(t.get(m, true) == nil)
        print("PASS")
    ''')


# ------------------------------------------------------------------
# Count accuracy
# ------------------------------------------------------------------

def test_count_accuracy_through_operations():
    assert_lua_pass(RB_CHECK + '''
        local t = require("treemap")
        local m = t.new()
        for i = 1, 150 do
            m = t.assoc(m, i, i)
            assert(t.count(m) == i, "count after insert " .. i)
            assert(count_nodes(m.root) == i, "node count mismatch after insert " .. i)
        end
        for i = 1, 150 do
            m = t.dissoc(m, i)
            local expected = 150 - i
            assert(t.count(m) == expected, "count after delete " .. i ..
                   ": expected " .. expected .. " got " .. t.count(m))
            if m.root then
                assert(count_nodes(m.root) == expected,
                       "node count mismatch after delete " .. i)
            end
        end
        assert(t.count(m) == 0)
        print("PASS")
    ''', timeout=60)


# ------------------------------------------------------------------
# Table conversion round-trip with deletion
# ------------------------------------------------------------------

def test_to_table_after_deletion():
    assert_lua_pass('''
        local t = require("treemap")
        local m = t.new()
        m = t.assoc(m, "x", 10)
        m = t.assoc(m, "y", 20)
        m = t.assoc(m, "z", 30)
        m = t.dissoc(m, "y")
        local tbl = t.to_table(m)
        assert(tbl.x == 10)
        assert(tbl.y == nil)
        assert(tbl.z == 30)
        local count = 0
        for _ in pairs(tbl) do count = count + 1 end
        assert(count == 2)
        print("PASS")
    ''')
