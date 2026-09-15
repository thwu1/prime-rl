
import subprocess
import pytest


def run_lua(code, timeout=60):
    """Helper to run inline Lua code and return the result."""
    result = subprocess.run(
        ["lua5.4", "-e", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/app",
    )
    return result


def test_lua_test_runner_passes():
    """Run the Lua test suite and verify all tests pass."""
    result = subprocess.run(
        ["lua5.4", "/app/test_runner.lua"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    assert result.returncode == 0, (
        f"Lua test runner failed with exit code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "ALL TESTS PASSED" in result.stdout, (
        f"Expected 'ALL TESTS PASSED' in output.\nstdout:\n{result.stdout}"
    )


def test_tablex_module_loads():
    """Verify the tablex module loads without errors."""
    result = run_lua('local T = require("tablex"); print("OK")')
    assert result.returncode == 0, (
        f"Module failed to load.\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_no_hardcoded_answers():
    """Verify the module uses computation, not hardcoded results."""
    with open("/app/tablex.lua", "r") as f:
        content = f.read()
    assert "function" in content, "tablex.lua must contain function definitions"
    assert "deepcopy" in content, "tablex.lua must implement deepcopy"
    assert "tbl_deep_extend" in content, "tablex.lua must implement tbl_deep_extend"
    assert "tbl_deep_diff" in content, "tablex.lua must implement tbl_deep_diff"
    assert "group_by" in content, "tablex.lua must implement group_by"
    assert "partition" in content, "tablex.lua must implement partition"
    assert "islist" in content, "tablex.lua must implement islist"
    assert len(content) > 2000, "tablex.lua seems too small to be a real implementation"


def test_deepcopy_cycle_detection():
    """Specifically test cycle detection works correctly."""
    result = run_lua('''
    local T = require("tablex")
    local t = {a = 1}
    t.self = t
    local c = T.deepcopy(t)
    assert(c.self == c, "cycle not preserved")
    assert(c.self ~= t, "copy references original")
    assert(c.a == 1, "value not copied")
    print("CYCLE_OK")
    ''')
    assert result.returncode == 0, f"Cycle test failed:\n{result.stderr}"
    assert "CYCLE_OK" in result.stdout


def test_deepcopy_thread_error():
    """Test that deepcopy raises on thread values."""
    result = run_lua('''
    local T = require("tablex")
    local thread = coroutine.create(function() return 0 end)
    local ok, err = pcall(function() T.deepcopy({thr = thread}) end)
    assert(not ok, "expected error")
    assert(string.find(err, "Cannot deepcopy object of type thread"), "wrong error: " .. err)
    print("THREAD_OK")
    ''')
    assert result.returncode == 0, f"Thread test failed:\n{result.stderr}"
    assert "THREAD_OK" in result.stdout


def test_tbl_deep_extend_keep_force():
    """Specifically test keep vs force behavior."""
    result = run_lua('''
    local T = require("tablex")
    local a = {x = {a = 1, b = 2}}
    local b = {x = {a = 99, c = 3}}
    local keep = T.tbl_deep_extend("keep", a, b)
    assert(keep.x.a == 1, "keep should preserve first value, got " .. tostring(keep.x.a))
    assert(keep.x.c == 3, "keep should add new keys")
    local force = T.tbl_deep_extend("force", a, b)
    assert(force.x.a == 99, "force should use last value, got " .. tostring(force.x.a))
    print("EXTEND_OK")
    ''')
    assert result.returncode == 0, f"Extend test failed:\n{result.stderr}"
    assert "EXTEND_OK" in result.stdout


def test_tbl_deep_extend_function_behavior():
    """Test function as behavior with correct argument order."""
    result = run_lua('''
    local T = require("tablex")
    local a = {a = 1, b = 2}
    local b = {a = -1, b = 5}
    local c = T.tbl_deep_extend(function(k, prev_v, v)
      return v > prev_v and v or prev_v
    end, a, b)
    assert(c.a == 1, "expected max(1,-1)=1, got " .. tostring(c.a))
    assert(c.b == 5, "expected max(2,5)=5, got " .. tostring(c.b))
    print("FN_BEHAVIOR_OK")
    ''')
    assert result.returncode == 0, f"Fn behavior test failed:\n{result.stderr}"
    assert "FN_BEHAVIOR_OK" in result.stdout


def test_tbl_deep_diff_basic():
    """Test basic diff detecting added, removed, and changed keys."""
    result = run_lua('''
    local T = require("tablex")
    local d = T.tbl_deep_diff({a = 1, b = 2}, {a = 1, b = 3, c = 4})
    assert(d.added.c == 4, "added c should be 4, got " .. tostring(d.added.c))
    assert(T.tbl_count(d.removed) == 0, "should have no removed keys")
    assert(d.changed.b.old == 2, "changed b old should be 2")
    assert(d.changed.b.new == 3, "changed b new should be 3")
    print("DIFF_BASIC_OK")
    ''')
    assert result.returncode == 0, f"Diff basic failed:\n{result.stderr}"
    assert "DIFF_BASIC_OK" in result.stdout


def test_tbl_deep_diff_identical_nested():
    """Test that identical nested subtrees do not appear in changed."""
    result = run_lua('''
    local T = require("tablex")
    local d = T.tbl_deep_diff(
      {a = {x = 1}, b = {y = 2}},
      {a = {x = 1}, b = {y = 99}}
    )
    assert(d.changed.a == nil, "identical subtree a should not be in changed")
    assert(d.changed.b ~= nil, "different subtree b should be in changed")
    assert(d.changed.b.changed.y.old == 2, "b.y old should be 2")
    assert(d.changed.b.changed.y.new == 99, "b.y new should be 99")
    print("DIFF_NESTED_OK")
    ''')
    assert result.returncode == 0, f"Diff nested failed:\n{result.stderr}"
    assert "DIFF_NESTED_OK" in result.stdout


def test_tbl_deep_diff_added_only():
    """Test diff when all keys are added (empty first table)."""
    result = run_lua('''
    local T = require("tablex")
    local d = T.tbl_deep_diff({}, {x = 10, y = 20})
    assert(d.added.x == 10, "added x should be 10")
    assert(d.added.y == 20, "added y should be 20")
    assert(T.tbl_count(d.removed) == 0, "no removed")
    assert(T.tbl_count(d.changed) == 0, "no changed")
    print("DIFF_ADDED_OK")
    ''')
    assert result.returncode == 0, f"Diff added failed:\n{result.stderr}"
    assert "DIFF_ADDED_OK" in result.stdout


def test_iterator_chaining():
    """Test that iterator chaining works correctly."""
    result = run_lua('''
    local T = require("tablex")
    local result = T.iter({1,2,3,4,5,6,7,8,9,10})
        :filter(function(v) return v % 2 == 0 end)
        :map(function(v) return v * 10 end)
        :take(3)
        :totable()
    assert(#result == 3, "expected 3 elements, got " .. #result)
    assert(result[1] == 20, "expected 20, got " .. tostring(result[1]))
    assert(result[2] == 40, "expected 40, got " .. tostring(result[2]))
    assert(result[3] == 60, "expected 60, got " .. tostring(result[3]))
    print("CHAIN_OK")
    ''')
    assert result.returncode == 0, f"Chain test failed:\n{result.stderr}"
    assert "CHAIN_OK" in result.stdout


def test_iterator_enumerate():
    """Test enumerate produces correct 1-based indices."""
    result = run_lua('''
    local T = require("tablex")
    local it = T.iter({"a", "b", "c"}):enumerate()
    local i, v = it:next()
    assert(i == 1, "first index should be 1, got " .. tostring(i))
    assert(v == "a", "first value should be a, got " .. tostring(v))
    i, v = it:next()
    assert(i == 2, "second index should be 2, got " .. tostring(i))
    i, v = it:next()
    assert(i == 3, "third index should be 3, got " .. tostring(i))
    print("ENUM_OK")
    ''')
    assert result.returncode == 0, f"Enumerate test failed:\n{result.stderr}"
    assert "ENUM_OK" in result.stdout


def test_flatten_depth():
    """Test flatten respects depth parameter."""
    result = run_lua('''
    local T = require("tablex")
    local q = {{1, {2}}, {{{3}}, {4}}, {5}}
    local r1 = T.iter(q):flatten(1):totable()
    assert(#r1 == 5, "flatten(1) should produce 5 elements, got " .. #r1)
    assert(r1[1] == 1, "first should be 1")
    assert(type(r1[2]) == "table", "second should be table {2}")
    assert(r1[5] == 5, "fifth should be 5")
    print("FLATTEN_OK")
    ''')
    assert result.returncode == 0, f"Flatten test failed:\n{result.stderr}"
    assert "FLATTEN_OK" in result.stdout


def test_chain_concatenation():
    """Test chain() concatenates two iterators correctly."""
    result = run_lua('''
    local T = require("tablex")
    local r = T.iter({1, 2, 3}):chain({4, 5, 6}):totable()
    assert(#r == 6, "expected 6 elements, got " .. #r)
    for i = 1, 6 do
        assert(r[i] == i, "element " .. i .. " should be " .. i .. ", got " .. tostring(r[i]))
    end
    -- chain with empty
    local r2 = T.iter({1, 2}):chain({}):totable()
    assert(#r2 == 2, "expected 2 elements, got " .. #r2)
    assert(r2[1] == 1 and r2[2] == 2, "chain with empty second failed")
    print("CHAIN_CONCAT_OK")
    ''')
    assert result.returncode == 0, f"Chain concat test failed:\n{result.stderr}"
    assert "CHAIN_CONCAT_OK" in result.stdout


def test_zip_stops_at_shorter():
    """Test zip() stops when either iterator is exhausted."""
    result = run_lua('''
    local T = require("tablex")
    local r = T.iter({1, 2, 3}):zip({"a", "b"}):totable()
    assert(#r == 2, "expected 2 pairs, got " .. #r)
    assert(r[1][1] == 1 and r[1][2] == "a", "first pair wrong")
    assert(r[2][1] == 2 and r[2][2] == "b", "second pair wrong")
    local r2 = T.iter({1}):zip({10, 20, 30}):totable()
    assert(#r2 == 1, "expected 1 pair from short first, got " .. #r2)
    print("ZIP_OK")
    ''')
    assert result.returncode == 0, f"Zip test failed:\n{result.stderr}"
    assert "ZIP_OK" in result.stdout


def test_scan_accumulates():
    """Test scan() yields correct intermediate accumulator values."""
    result = run_lua('''
    local T = require("tablex")
    local r = T.iter({1, 2, 3, 4}):scan(0, function(acc, v) return acc + v end):totable()
    assert(#r == 5, "expected 5 elements, got " .. #r)
    local expected = {0, 1, 3, 6, 10}
    for i, e in ipairs(expected) do
        assert(r[i] == e, "element " .. i .. " should be " .. e .. ", got " .. tostring(r[i]))
    end
    print("SCAN_OK")
    ''')
    assert result.returncode == 0, f"Scan test failed:\n{result.stderr}"
    assert "SCAN_OK" in result.stdout


def test_peek_with_transforms():
    """Test peek() applies transforms on array iterators."""
    result = run_lua('''
    local T = require("tablex")
    local it = T.iter({1, 2, 3, 4, 5}):filter(function(v) return v % 2 == 0 end)
    local p = it:peek()
    assert(p == 2, "peek should return first even (2), got " .. tostring(p))
    local p2 = it:peek()
    assert(p2 == 2, "peek should be idempotent, got " .. tostring(p2))
    local n = it:next()
    assert(n == 2, "next after peek should return 2, got " .. tostring(n))
    local n2 = it:next()
    assert(n2 == 4, "second next should return 4, got " .. tostring(n2))
    print("PEEK_TRANSFORM_OK")
    ''')
    assert result.returncode == 0, f"Peek transform test failed:\n{result.stderr}"
    assert "PEEK_TRANSFORM_OK" in result.stdout


def test_skip_predicate_preserves():
    """Test skip with predicate preserves the first non-matching element."""
    result = run_lua('''
    local T = require("tablex")
    local r = T.iter({4, 3, 2, 1}):skip(function(x) return x > 2 end):totable()
    assert(#r == 2, "expected 2 elements, got " .. #r)
    assert(r[1] == 2, "first should be 2, got " .. tostring(r[1]))
    assert(r[2] == 1, "second should be 1, got " .. tostring(r[2]))
    print("SKIP_PRED_OK")
    ''')
    assert result.returncode == 0, f"Skip pred test failed:\n{result.stderr}"
    assert "SKIP_PRED_OK" in result.stdout


def test_fold_captures_return():
    """Test fold() correctly captures the return value of the accumulator function."""
    result = run_lua('''
    local T = require("tablex")
    local r = T.iter({1, 2, 3, 4, 5}):fold(100, function(acc, v) return acc + v end)
    assert(r == 115, "expected 115, got " .. tostring(r))
    print("FOLD_OK")
    ''')
    assert result.returncode == 0, f"Fold test failed:\n{result.stderr}"
    assert "FOLD_OK" in result.stdout


def test_islist_raw_access():
    """Test islist uses raw access and __index doesn't fill holes."""
    result = run_lua('''
    local T = require("tablex")
    local t = setmetatable({1, [3] = 3}, {
        __index = function() return 2 end,
    })
    assert(T.islist(t) == false, "metatable __index should not fill holes")
    assert(T.islist({}) == true, "empty table is a list")
    assert(T.islist({1, 2, 3}) == true, "contiguous is a list")
    assert(T.islist({1, 2, nil, 4}) == false, "holes not a list")
    print("ISLIST_OK")
    ''')
    assert result.returncode == 0, f"islist test failed:\n{result.stderr}"
    assert "ISLIST_OK" in result.stdout


def test_rev_even_length():
    """Test rev works correctly on even-length arrays."""
    result = run_lua('''
    local T = require("tablex")
    local r = T.iter({1, 2, 3, 4}):rev():totable()
    assert(#r == 4, "expected 4 elements")
    assert(r[1] == 4, "first should be 4, got " .. tostring(r[1]))
    assert(r[2] == 3, "second should be 3, got " .. tostring(r[2]))
    assert(r[3] == 2, "third should be 2, got " .. tostring(r[3]))
    assert(r[4] == 1, "fourth should be 1, got " .. tostring(r[4]))
    local r6 = T.iter({1,2,3,4,5,6}):rev():totable()
    assert(r6[1] == 6 and r6[6] == 1, "6-element rev failed")
    local r2 = T.iter({1,2}):rev():totable()
    assert(r2[1] == 2 and r2[2] == 1, "2-element rev failed")
    print("REV_OK")
    ''')
    assert result.returncode == 0, f"Rev test failed:\n{result.stderr}"
    assert "REV_OK" in result.stdout


def test_group_by_basic():
    """Test group_by groups elements correctly."""
    result = run_lua('''
    local T = require("tablex")
    local groups = T.iter({1, 2, 3, 4, 5, 6}):group_by(function(v)
      return v % 2 == 0 and "even" or "odd"
    end)
    assert(T.deep_equal(groups["even"], {2, 4, 6}), "even group wrong")
    assert(T.deep_equal(groups["odd"], {1, 3, 5}), "odd group wrong")
    print("GROUP_BY_OK")
    ''')
    assert result.returncode == 0, f"Group by test failed:\n{result.stderr}"
    assert "GROUP_BY_OK" in result.stdout


def test_group_by_with_transforms():
    """Test group_by respects the transform pipeline."""
    result = run_lua('''
    local T = require("tablex")
    local groups = T.iter({1, 2, 3, 4, 5, 6, 7, 8, 9, 10})
      :filter(function(v) return v > 3 end)
      :map(function(v) return v * 10 end)
      :group_by(function(v) return v >= 70 and "high" or "low" end)
    assert(T.deep_equal(groups["high"], {70, 80, 90, 100}), "high group wrong")
    assert(T.deep_equal(groups["low"], {40, 50, 60}), "low group wrong")
    print("GROUP_BY_XFORM_OK")
    ''')
    assert result.returncode == 0, f"Group by xform test failed:\n{result.stderr}"
    assert "GROUP_BY_XFORM_OK" in result.stdout


def test_partition_basic():
    """Test partition splits elements correctly."""
    result = run_lua('''
    local T = require("tablex")
    local evens, odds = T.iter({1, 2, 3, 4, 5, 6}):partition(function(v) return v % 2 == 0 end)
    assert(T.deep_equal(evens, {2, 4, 6}), "evens wrong")
    assert(T.deep_equal(odds, {1, 3, 5}), "odds wrong")
    print("PARTITION_OK")
    ''')
    assert result.returncode == 0, f"Partition test failed:\n{result.stderr}"
    assert "PARTITION_OK" in result.stdout


def test_partition_ordering():
    """Test partition returns matching first, non-matching second."""
    result = run_lua('''
    local T = require("tablex")
    local big, small = T.iter({10, 1, 20, 2, 30, 3}):partition(function(v) return v >= 10 end)
    assert(T.deep_equal(big, {10, 20, 30}), "big should be {10,20,30}")
    assert(T.deep_equal(small, {1, 2, 3}), "small should be {1,2,3}")
    print("PARTITION_ORDER_OK")
    ''')
    assert result.returncode == 0, f"Partition order test failed:\n{result.stderr}"
    assert "PARTITION_ORDER_OK" in result.stdout
