-- test_runner.lua — Comprehensive test suite for tablex module

local T = require("tablex")

local pass_count = 0
local fail_count = 0
local current_section = ""

local function section(name)
  current_section = name
  io.write(string.format("\n=== %s ===\n", name))
end

local function check(name, condition)
  if condition then
    pass_count = pass_count + 1
  else
    fail_count = fail_count + 1
    io.write(string.format("  FAIL: [%s] %s\n", current_section, name))
  end
end

local function check_eq(name, expected, got)
  local eq = T.deep_equal(expected, got)
  if not eq then
    fail_count = fail_count + 1
    local function repr(v)
      if type(v) == "table" then
        local parts = {}
        for k, val in pairs(v) do
          parts[#parts + 1] = string.format("[%s]=%s", tostring(k), repr(val))
        end
        return "{" .. table.concat(parts, ",") .. "}"
      else
        return tostring(v)
      end
    end
    io.write(string.format("  FAIL: [%s] %s — expected %s, got %s\n",
      current_section, name, repr(expected), repr(got)))
  else
    pass_count = pass_count + 1
  end
end

local function check_error(name, pattern, fn)
  local ok, err = pcall(fn)
  if ok then
    fail_count = fail_count + 1
    io.write(string.format("  FAIL: [%s] %s — expected error but succeeded\n",
      current_section, name))
  elseif not string.find(err, pattern) then
    fail_count = fail_count + 1
    io.write(string.format("  FAIL: [%s] %s — error '%s' doesn't match '%s'\n",
      current_section, name, err, pattern))
  else
    pass_count = pass_count + 1
  end
end

--------------------------------------------------------------
-- islist
--------------------------------------------------------------
section("islist")
check("empty table is list", T.islist({}) == true)
check("EMPTY_DICT is not list", T.islist(T.empty_dict()) == false)
check("simple list", T.islist({"a", "b", "c"}) == true)
check("mixed keys not list", T.islist({"a", "32", a="hello", b="baz"}) == false)
check("int+string keys not list", T.islist({1, a="hello", b="baz"}) == false)
check("string+int keys not list", T.islist({a="hello", b="baz", 1}) == false)
check("nil hole + string key not list", T.islist({1, 2, nil, a="hello"}) == false)
check("nil hole not list", T.islist({1, 2, nil, 4}) == false)
check("leading nil not list", T.islist({nil, 2, 3, 4}) == false)
check("float key not list", T.islist({1, [1.5]=2, [3]=3}) == false)

-- Metatable __index must not fill holes
do
  local t = setmetatable({1, [3] = 3}, {
    __index = function() return 2 end,
  })
  check("metatable __index not fill holes", T.islist(t) == false)
end

--------------------------------------------------------------
-- tbl_count
--------------------------------------------------------------
section("tbl_count")
check_eq("empty", 0, T.tbl_count({}))
check_eq("empty_dict", 0, T.tbl_count(T.empty_dict()))
check_eq("nil value", 0, T.tbl_count({nil}))
check_eq("nil named value", 0, T.tbl_count({a=nil}))
check_eq("one", 1, T.tbl_count({1}))
check_eq("two", 2, T.tbl_count({1, 2}))
check_eq("holes", 2, T.tbl_count({1, nil, 3}))
check_eq("named one", 1, T.tbl_count({a=1}))
check_eq("named two", 2, T.tbl_count({a=1, b=2}))
check_eq("named holes", 2, T.tbl_count({a=1, b=nil, c=3}))

--------------------------------------------------------------
-- deep_equal
--------------------------------------------------------------
section("deep_equal")
check("same simple", T.deep_equal({a=1}, {a=1}))
check("nested", T.deep_equal({a={b=1}}, {a={b=1}}))
check("nested nil", T.deep_equal({a={b={nil}}}, {a={b={}}}))
check("mixed keys", T.deep_equal({a=1, [5]=5}, {nil,nil,nil,nil,5,a=1}))
check("shared subtable", (function()
  local shared = {}
  return T.deep_equal({1, shared, 1, shared}, {1, {}, 1, {}})
end)())
check("not equal", not T.deep_equal({a=1}, {a=2}))
check("different types", not T.deep_equal({a=1}, "string"))

--------------------------------------------------------------
-- deepcopy
--------------------------------------------------------------
section("deepcopy")

-- Basic copy
do
  local a = { x = { 1, 2 }, y = 5 }
  local b = T.deepcopy(a)
  check("basic values", b.x[1] == 1 and b.x[2] == 2 and b.y == 5)
  check("different identity", tostring(a) ~= tostring(b))
  check("sub-table different identity", tostring(a.x) ~= tostring(b.x))
end

-- Empty table
do
  local a = {}
  local b = T.deepcopy(a)
  check("empty copy is list", T.islist(b))
  check("empty copy different identity", tostring(a) ~= tostring(b))
end

-- EMPTY_DICT preservation
do
  local a = T.empty_dict()
  local b = T.deepcopy(a)
  check("empty_dict preserved", not T.islist(b) and T.tbl_count(b) == 0)
end

-- Mixed empty_dict and list
do
  local a = { x = T.empty_dict(), y = {} }
  local b = T.deepcopy(a)
  check("mixed: x is dict", not T.islist(b.x))
  check("mixed: y is list", T.islist(b.y))
  check("mixed: count", T.tbl_count(b) == 2)
end

-- Function copy by reference
do
  local f1 = function() return 1 end
  local f2 = function() return 2 end
  local t1 = { f = f1 }
  local t2 = T.deepcopy(t1)
  t1.f = f2
  check("function by reference", t1.f() ~= t2.f())
  check("copied function returns original", t2.f() == 1)
end

-- Cycle detection (protected to avoid crash on broken implementations)
do
  local ok, err = pcall(function()
    local t1 = { a = 5 }
    t1.self = t1
    local t2 = T.deepcopy(t1)
    check("cycle: self == self", t2.self == t2)
    check("cycle: self ~= original", t2.self ~= t1)
    check("cycle: value preserved", t2.a == 5)
  end)
  if not ok then
    fail_count = fail_count + 3
    io.write(string.format("  FAIL: [%s] cycle detection crashed: %s\n",
      current_section, tostring(err)))
  end
end

-- Metatable preservation (shared)
do
  local mt = { mt = true }
  local t1 = setmetatable({ a = 5 }, mt)
  local t2 = T.deepcopy(t1)
  check("metatable preserved", getmetatable(t2) == mt)
end

-- Thread error
check_error("thread error", "Cannot deepcopy object of type thread", function()
  local thread = coroutine.create(function() return 0 end)
  local t = { thr = thread }
  T.deepcopy(t)
end)

--------------------------------------------------------------
-- tbl_deep_extend
--------------------------------------------------------------
section("tbl_deep_extend")

-- keep: first value wins for conflicts
do
  local a = { x = { a = 1, b = 2 } }
  local b = { x = { a = 2, c = { y = 3 } } }
  local c = T.tbl_deep_extend("keep", a, b)
  check("keep: a wins", c.x.a == 1)
  check("keep: b preserved", c.x.b == 2)
  check("keep: new key added", c.x.c.y == 3)
end

-- force: last value wins
do
  local a = { x = { a = 1, b = 2 } }
  local b = { x = { a = 2, c = { y = 3 } } }
  local c = T.tbl_deep_extend("force", a, b)
  check("force: b wins", c.x.a == 2)
  check("force: a preserved", c.x.b == 2)
  check("force: new key added", c.x.c.y == 3)
end

-- Three tables keep
do
  local a = { x = { a = 1, b = 2 } }
  local b = { x = { a = 2, c = { y = 3 } } }
  local c = { x = { c = 4, d = { y = 4 } } }
  local d = T.tbl_deep_extend("keep", a, b, c)
  check("3-keep: a=1", d.x.a == 1)
  check("3-keep: b=2", d.x.b == 2)
  check("3-keep: c.y=3", d.x.c.y == 3)
  check("3-keep: d.y=4", d.x.d.y == 4)
end

-- Three tables force
do
  local a = { x = { a = 1, b = 2 } }
  local b = { x = { a = 2, c = { y = 3 } } }
  local c = { x = { c = 4, d = { y = 4 } } }
  local d = T.tbl_deep_extend("force", a, b, c)
  check("3-force: a=2", d.x.a == 2)
  check("3-force: b=2", d.x.b == 2)
  check("3-force: c=4", d.x.c == 4)
  check("3-force: d.y=4", d.x.d.y == 4)
end

-- EMPTY_DICT + {} preserves first type
do
  local a = T.empty_dict()
  local b = {}
  local c = T.tbl_deep_extend("keep", a, b)
  check("empty_dict keep: not list", not T.islist(c))
  check("empty_dict keep: empty", T.tbl_count(c) == 0)
end
do
  local a = {}
  local b = T.empty_dict()
  local c = T.tbl_deep_extend("keep", a, b)
  check("list keep: is list", T.islist(c))
  check("list keep: empty", T.tbl_count(c) == 0)
end

-- Force: empty list overlay on dict triggers list-replacement
do
  local a = { a = { b = 1 } }
  local b = { a = {} }
  local c = T.tbl_deep_extend("force", a, b)
  check("force: empty list over dict", T.deep_equal(c, { a = {} }))
end
do
  local a = { a = 123 }
  local b = { a = { b = 1 } }
  local c = T.tbl_deep_extend("force", a, b)
  check("force: table over scalar", T.deep_equal(c, { a = { b = 1 } }))
end
do
  local a = { a = { b = 1 } }
  local b = { a = 123 }
  local c = T.tbl_deep_extend("force", a, b)
  check("force: scalar over table", T.deep_equal(c, { a = 123 }))
end

-- List replacement (not merge)
do
  local a = { sub = { "a", "b" } }
  local b = { sub = { "b", "c" } }
  local c = T.tbl_deep_extend("force", a, b)
  check("force: list replaced", T.deep_equal(c, { sub = { "b", "c" } }))
end

-- Sparse integer keys merge
do
  local a = { a = { [2] = 3 } }
  local b = { a = { [3] = 3 } }
  local c = T.tbl_deep_extend("force", a, b)
  check("force: sparse merge", T.deep_equal(c, { a = { [2] = 3, [3] = 3 } }))
end

-- Function as behavior
do
  local a = { a = 1, b = 2, c = { d = 1, e = -2 } }
  local b = { a = -1, b = 5, c = { d = 6 } }
  local c = T.tbl_deep_extend(function(k, prev_v, v)
    if prev_v then
      return v > prev_v and v or prev_v
    else
      return v
    end
  end, a, b)
  check("fn behavior: max merge", T.deep_equal(c, { a = 1, b = 5, c = { d = 6, e = -2 } }))
end

-- Error cases
check_error("no args", 'invalid "behavior": nil', function() T.tbl_deep_extend() end)
check_error("one arg", "wrong number of arguments", function() T.tbl_deep_extend("keep") end)
check_error("two args", "wrong number of arguments", function() T.tbl_deep_extend("keep", {}) end)
check_error("non-table arg", "expected table, got number", function() T.tbl_deep_extend("keep", {}, 42) end)

--------------------------------------------------------------
-- tbl_deep_diff
--------------------------------------------------------------
section("tbl_deep_diff")

-- Basic diff
do
  local d = T.tbl_deep_diff({a = 1, b = 2}, {a = 1, b = 3, c = 4})
  check_eq("diff added", {c = 4}, d.added)
  check_eq("diff removed", {}, d.removed)
  check_eq("diff changed b", {b = {old = 2, new = 3}}, d.changed)
end

-- Removed keys
do
  local d = T.tbl_deep_diff({a = 1, b = 2, c = 3}, {a = 1})
  check_eq("diff removed keys", {b = 2, c = 3}, d.removed)
  check_eq("diff no added", {}, d.added)
  check_eq("diff no changed", {}, d.changed)
end

-- Identical tables
do
  local d = T.tbl_deep_diff({a = 1, b = {c = 2}}, {a = 1, b = {c = 2}})
  check_eq("identical added", {}, d.added)
  check_eq("identical removed", {}, d.removed)
  check_eq("identical changed", {}, d.changed)
end

-- Nested diff
do
  local d = T.tbl_deep_diff(
    {a = {x = 1, y = 2}},
    {a = {x = 1, y = 3, z = 4}}
  )
  check_eq("nested no top added", {}, d.added)
  check_eq("nested no top removed", {}, d.removed)
  check("nested has sub-diff", d.changed.a ~= nil)
  check_eq("nested sub added", {z = 4}, d.changed.a.added)
  check_eq("nested sub changed", {y = {old = 2, new = 3}}, d.changed.a.changed)
end

-- Empty tables
do
  local d = T.tbl_deep_diff({}, {})
  check_eq("empty diff added", {}, d.added)
  check_eq("empty diff removed", {}, d.removed)
  check_eq("empty diff changed", {}, d.changed)
end

-- Nested identical subtrees should not appear in changed
do
  local d = T.tbl_deep_diff(
    {a = {x = 1}, b = {y = 2}},
    {a = {x = 1}, b = {y = 99}}
  )
  check("no empty sub-diff for a", d.changed.a == nil)
  check("has sub-diff for b", d.changed.b ~= nil)
  check_eq("b changed", {y = {old = 2, new = 99}}, d.changed.b.changed)
end

-- Only added
do
  local d = T.tbl_deep_diff({}, {x = 10, y = 20})
  check_eq("only added x", 10, d.added.x)
  check_eq("only added y", 20, d.added.y)
  check_eq("only added no removed", {}, d.removed)
end

-- Mixed add/remove/change
do
  local d = T.tbl_deep_diff({a = 1, b = 2, c = 3}, {b = 99, d = 4})
  check_eq("mixed added", {d = 4}, d.added)
  check_eq("mixed removed a", 1, d.removed.a)
  check_eq("mixed removed c", 3, d.removed.c)
  check_eq("mixed changed b", {old = 2, new = 99}, d.changed.b)
end

--------------------------------------------------------------
-- Iterator: filter, map, totable
--------------------------------------------------------------
section("iter: filter/map/totable")

check_eq("filter odd", {1, 3, 5},
  T.iter({1, 2, 3, 4, 5}):filter(function(v) return v % 2 ~= 0 end):totable())

check_eq("filter even", {2, 4},
  T.iter({1, 2, 3, 4, 5}):filter(function(v) return v % 2 == 0 end):totable())

check_eq("filter empty", {},
  T.iter({1, 2, 3, 4, 5}):filter(function(v) return v > 5 end):totable())

check_eq("map double", {2, 4, 6, 8, 10},
  T.iter({1, 2, 3, 4, 5}):map(function(v) return 2 * v end):totable())

-- map returning nil filters out
check_eq("map filter", {"Lion 2", "Lion 4"}, (function()
  local lines = {"  Line 1", "  Line 2", "  Line 3", "  Line 4"}
  return T.iter(lines):map(function(s)
    local lnum = s:match("(%d+)")
    if lnum and tonumber(lnum) % 2 == 0 then
      local trimmed = s:gsub("^%s+", ""):gsub("%s+$", ""):gsub("Line", "Lion")
      return trimmed
    end
  end):totable()
end)())

--------------------------------------------------------------
-- Iterator: join
--------------------------------------------------------------
section("iter: join")
check_eq("join basic", "1, 2, 3", T.iter({1, 2, 3}):join(", "))

--------------------------------------------------------------
-- Iterator: next
--------------------------------------------------------------
section("iter: next")
do
  local it = T.iter({1, 2, 3}):map(function(v) return 2 * v end)
  check_eq("next 1", 2, it:next())
  check_eq("next 2", 4, it:next())
  check_eq("next 3", 6, it:next())
  check("next nil", it:next() == nil)
end

--------------------------------------------------------------
-- Iterator: rev
--------------------------------------------------------------
section("iter: rev")
check_eq("rev basic", {3, 2, 1}, T.iter({1, 2, 3}):rev():totable())
check_eq("rev 4 elements", {4, 3, 2, 1}, T.iter({1, 2, 3, 4}):rev():totable())
check_eq("rev 1 element", {1}, T.iter({1}):rev():totable())
check_eq("rev empty", {}, T.iter({}):rev():totable())
check_eq("rev 6 elements", {6, 5, 4, 3, 2, 1}, T.iter({1, 2, 3, 4, 5, 6}):rev():totable())
check_eq("rev 2 elements", {2, 1}, T.iter({1, 2}):rev():totable())

--------------------------------------------------------------
-- Iterator: skip
--------------------------------------------------------------
section("iter: skip")
do
  local q = {4, 3, 2, 1}
  check_eq("skip 0", {4, 3, 2, 1}, T.iter(q):skip(0):totable())
  check_eq("skip 1", {3, 2, 1}, T.iter(q):skip(1):totable())
  check_eq("skip 2", {2, 1}, T.iter(q):skip(2):totable())
  check_eq("skip n-1", {1}, T.iter(q):skip(#q - 1):totable())
  check_eq("skip n", {}, T.iter(q):skip(#q):totable())
  check_eq("skip n+1", {}, T.iter(q):skip(#q + 1):totable())
end

-- skip with predicate
do
  local q = {4, 3, 2, 1}
  check_eq("skip pred false", {4, 3, 2, 1}, T.iter(q):skip(function() return false end):totable())
  check_eq("skip pred >2", {2, 1}, T.iter(q):skip(function(x) return x > 2 end):totable())
  check_eq("skip pred true", {}, T.iter(q):skip(function() return true end):totable())
end

--------------------------------------------------------------
-- Iterator: take
--------------------------------------------------------------
section("iter: take")
do
  local q = {4, 3, 2, 1}
  check_eq("take 0", {}, T.iter(q):take(0):totable())
  check_eq("take 1", {4}, T.iter(q):take(1):totable())
  check_eq("take 2", {4, 3}, T.iter(q):take(2):totable())
  check_eq("take 3", {4, 3, 2}, T.iter(q):take(3):totable())
  check_eq("take 4", {4, 3, 2, 1}, T.iter(q):take(4):totable())
  check_eq("take 5", {4, 3, 2, 1}, T.iter(q):take(5):totable())
end

-- take with predicate
do
  local q = {4, 3, 2, 1}
  check_eq("take pred false", {}, T.iter(q):take(function() return false end):totable())
  check_eq("take pred >2", {4, 3}, T.iter(q):take(function(x) return x > 2 end):totable())
  check_eq("take pred true", {4, 3, 2, 1}, T.iter(q):take(function() return true end):totable())
end

-- rev + take combo
do
  local q = {4, 3, 2, 1}
  check_eq("rev then take", {1, 2, 3}, T.iter(q):rev():take(3):totable())
  check_eq("take then rev", {2, 3, 4}, T.iter(q):take(3):rev():totable())
end

-- filter + map + take (transforms must flow through take)
do
  check_eq("filter+map+take",
    {20, 40, 60},
    T.iter({1,2,3,4,5,6,7,8,9,10})
      :filter(function(v) return v % 2 == 0 end)
      :map(function(v) return v * 10 end)
      :take(3)
      :totable())
end

-- take with predicate after filter+map
do
  check_eq("filter+map+take_pred",
    {20, 40},
    T.iter({1,2,3,4,5,6,7,8,9,10})
      :filter(function(v) return v % 2 == 0 end)
      :map(function(v) return v * 10 end)
      :take(function(v) return v < 50 end)
      :totable())
end

--------------------------------------------------------------
-- Iterator: rskip
--------------------------------------------------------------
section("iter: rskip")
do
  local q = {4, 3, 2, 1}
  check_eq("rskip 0", q, T.iter(q):rskip(0):totable())
  check_eq("rskip 1", {4, 3, 2}, T.iter(q):rskip(1):totable())
  check_eq("rskip 2", {4, 3}, T.iter(q):rskip(2):totable())
  check_eq("rskip n-1", {4}, T.iter(q):rskip(#q - 1):totable())
  check_eq("rskip n", {}, T.iter(q):rskip(#q):totable())
  check_eq("rskip n+1", {}, T.iter(q):rskip(#q + 1):totable())
end

--------------------------------------------------------------
-- Iterator: slice
--------------------------------------------------------------
section("iter: slice")
do
  local q = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
  check_eq("slice 3,7", {3, 4, 5, 6, 7}, T.iter(q):slice(3, 7):totable())
  check_eq("slice inverted", {}, T.iter(q):slice(6, 5):totable())
  check_eq("slice 0,0", {}, T.iter(q):slice(0, 0):totable())
  check_eq("slice 1,1", {1}, T.iter(q):slice(1, 1):totable())
  check_eq("slice 1,2", {1, 2}, T.iter(q):slice(1, 2):totable())
  check_eq("slice 10,10", {10}, T.iter(q):slice(10, 10):totable())
  check_eq("slice past end", {8, 9, 10}, T.iter(q):slice(8, 11):totable())
end

--------------------------------------------------------------
-- Iterator: nth
--------------------------------------------------------------
section("iter: nth")
do
  local q = {4, 3, 2, 1}
  check("nth 0 nil", T.iter(q):nth(0) == nil)
  check_eq("nth 1", 4, T.iter(q):nth(1))
  check_eq("nth 2", 3, T.iter(q):nth(2))
  check_eq("nth 3", 2, T.iter(q):nth(3))
  check_eq("nth 4", 1, T.iter(q):nth(4))
  check("nth 5 nil", T.iter(q):nth(5) == nil)
end

-- Negative nth
do
  local q = {4, 3, 2, 1}
  check_eq("nth -1", 1, T.iter(q):nth(-1))
  check_eq("nth -2", 2, T.iter(q):nth(-2))
  check_eq("nth -3", 3, T.iter(q):nth(-3))
  check_eq("nth -4", 4, T.iter(q):nth(-4))
  check("nth -5 nil", T.iter(q):nth(-5) == nil)
end

--------------------------------------------------------------
-- Iterator: peek
--------------------------------------------------------------
section("iter: peek")
do
  local it = T.iter({3, 6, 9, 12})
  check_eq("peek first", 3, it:peek())
  check_eq("peek idempotent", 3, it:peek())
  check_eq("peek then next", 3, it:next())
end

-- peek with transforms on array iterator
do
  local it = T.iter({1, 2, 3, 4, 5}):filter(function(v) return v % 2 == 0 end)
  check_eq("peek filtered", 2, it:peek())
  check_eq("peek filtered idem", 2, it:peek())
  check_eq("peek filtered next", 2, it:next())
  check_eq("peek filtered next2", 4, it:next())
end

-- peek multi-value on function iterator
do
  local vals_src = {{1, "one"}, {2, "two"}, {3, "three"}}
  local idx = 0
  local it = T.iter(function()
    idx = idx + 1
    if idx <= #vals_src then
      return vals_src[idx][1], vals_src[idx][2]
    end
  end)
  local k, v = it:peek()
  check_eq("peek mv key", 1, k)
  check_eq("peek mv val", "one", v)
  local k2, v2 = it:peek()
  check_eq("peek mv idem key", 1, k2)
  check_eq("peek mv idem val", "one", v2)
  local k3, v3 = it:next()
  check_eq("peek mv then next key", 1, k3)
  check_eq("peek mv then next val", "one", v3)
end

--------------------------------------------------------------
-- Iterator: pop / rpeek
--------------------------------------------------------------
section("iter: pop/rpeek")
do
  local it = T.iter({1, 2, 3, 4})
  check_eq("pop 4", 4, it:pop())
  check_eq("pop 3", 3, it:pop())
  check_eq("pop 2", 2, it:pop())
  check_eq("pop 1", 1, it:pop())
  check("pop nil", it:pop() == nil)
end
do
  local it = T.iter({1, 2, 3, 4})
  check_eq("rpeek", 4, it:rpeek())
  check_eq("rpeek idem", 4, it:rpeek())
  check_eq("rpeek then pop", 4, it:pop())
end

--------------------------------------------------------------
-- Iterator: find
--------------------------------------------------------------
section("iter: find")
do
  local q = {3, 6, 9, 12}
  check_eq("find 12", 12, T.iter(q):find(12))
  check("find 15 nil", T.iter(q):find(15) == nil)
  check_eq("find pred", 12, T.iter(q):find(function(v) return v % 4 == 0 end))

  local it = T.iter(q)
  local pred = function(v) return v % 3 == 0 end
  check_eq("find seq 1", 3, it:find(pred))
  check_eq("find seq 2", 6, it:find(pred))
  check_eq("find seq 3", 9, it:find(pred))
  check_eq("find seq 4", 12, it:find(pred))
  check("find seq done", it:find(pred) == nil)
end

--------------------------------------------------------------
-- Iterator: rfind
--------------------------------------------------------------
section("iter: rfind")
do
  local q = {1, 2, 3, 2, 1}
  local it = T.iter(q)
  check_eq("rfind 1 first", 1, it:rfind(1))
  check_eq("rfind 1 second", 1, it:rfind(1))
  check("rfind 1 done", it:rfind(1) == nil)
end

--------------------------------------------------------------
-- Iterator: any / all
--------------------------------------------------------------
section("iter: any/all")
do
  local odd = function(v) return v % 2 ~= 0 end
  check("any true", T.iter({4, 8, 9, 10}):any(odd))
  check("any false", not T.iter({4, 8, 10}):any(odd))
  check("all true", T.iter({3, 5, 7, 9}):all(odd))
  check("all false", not T.iter({3, 5, 7, 10}):all(odd))
end

--------------------------------------------------------------
-- Iterator: last
--------------------------------------------------------------
section("iter: last")
do
  local s = "abcdefghijklmnopqrstuvwxyz"
  local chars = {}
  for c in s:gmatch(".") do chars[#chars + 1] = c end
  check_eq("last", "z", T.iter(chars):last())
  check("last filtered nil", T.iter({1,2,3,4,5}):filter(function() return false end):last() == nil)
end

--------------------------------------------------------------
-- Iterator: enumerate
--------------------------------------------------------------
section("iter: enumerate")
do
  local chars = {"a", "b", "c"}
  local it = T.iter(chars):enumerate()
  local i1, v1 = it:next()
  check_eq("enum 1 idx", 1, i1)
  check_eq("enum 1 val", "a", v1)
  local i2, v2 = it:next()
  check_eq("enum 2 idx", 2, i2)
  check_eq("enum 2 val", "b", v2)
  local i3, v3 = it:next()
  check_eq("enum 3 idx", 3, i3)
  check_eq("enum 3 val", "c", v3)
  check("enum done", it:next() == nil)
end

--------------------------------------------------------------
-- Iterator: fold
--------------------------------------------------------------
section("iter: fold")
do
  local q = {1, 2, 3, 4, 5}
  check_eq("fold sum", 115, T.iter(q):fold(100, function(acc, v) return acc + v end))
  check_eq("fold reverse", {5, 4, 3, 2, 1}, T.iter(q):fold({}, function(acc, v)
    table.insert(acc, 1, v)
    return acc
  end))
end

--------------------------------------------------------------
-- Iterator: flatten
--------------------------------------------------------------
section("iter: flatten")
do
  local q = {{1, {2}}, {{{3}}, {4}}, {5}}
  check_eq("flatten 1", {1, {2}, {{3}}, {4}, 5}, T.iter(q):flatten():totable())
  check_eq("flatten 2", {1, 2, {3}, 4, 5}, T.iter(q):flatten(2):totable())
  check_eq("flatten 3", {1, 2, 3, 4, 5}, T.iter(q):flatten(4):totable())
  check_eq("flatten 0 noop", q, T.iter(q):flatten(0):totable())
  check_eq("flatten -1 noop", q, T.iter(q):flatten(-1):totable())
end

--------------------------------------------------------------
-- Iterator: unique
--------------------------------------------------------------
section("iter: unique")
check_eq("unique basic", {1, 2, 3, 4, 5}, T.iter({1, 2, 2, 3, 4, 4, 5}):unique():totable())
check_eq("unique complex", {1, 2, 3, 4, 5},
  T.iter({1, 2, 3, 4, 4, 5, 1, 2, 3, 2, 1, 2, 3, 4, 5}):unique():totable())

-- unique with key function
check_eq("unique key fn", {{1}, {2}, {3}},
  T.iter({{1}, {1}, {2}, {2}, {3}, {3}}):unique(function(x) return x[1] end):totable())

--------------------------------------------------------------
-- Iterator: chain
--------------------------------------------------------------
section("iter: chain")

check_eq("chain arrays", {1, 2, 3, 4, 5, 6},
  T.iter({1, 2, 3}):chain({4, 5, 6}):totable())

check_eq("chain empty first", {4, 5},
  T.iter({}):chain({4, 5}):totable())

check_eq("chain empty second", {1, 2},
  T.iter({1, 2}):chain({}):totable())

check_eq("chain both empty", {},
  T.iter({}):chain({}):totable())

check_eq("chain single elements", {1, 2},
  T.iter({1}):chain({2}):totable())

-- chain with filter
check_eq("chain after filter", {2, 4, 10, 20, 30},
  T.iter({1, 2, 3, 4, 5})
    :filter(function(v) return v % 2 == 0 end)
    :chain({10, 20, 30})
    :totable())

-- chain with function iterator
do
  local i = 0
  local it = T.iter(function()
    i = i + 1
    if i <= 3 then return i end
  end)
  check_eq("chain fn iter", {1, 2, 3, 10, 20},
    it:chain({10, 20}):totable())
end

--------------------------------------------------------------
-- Iterator: zip
--------------------------------------------------------------
section("iter: zip")

check_eq("zip equal", {{1, "a"}, {2, "b"}, {3, "c"}},
  T.iter({1, 2, 3}):zip({"a", "b", "c"}):totable())

check_eq("zip short first", {{1, "a"}, {2, "b"}},
  T.iter({1, 2}):zip({"a", "b", "c"}):totable())

check_eq("zip short second", {{1, "a"}, {2, "b"}},
  T.iter({1, 2, 3}):zip({"a", "b"}):totable())

check_eq("zip empty first", {},
  T.iter({}):zip({1, 2}):totable())

check_eq("zip empty second", {},
  T.iter({1, 2}):zip({}):totable())

-- zip then map
check_eq("zip then map", {11, 22, 33},
  T.iter({1, 2, 3}):zip({10, 20, 30}):map(function(a, b) return a + b end):totable())

--------------------------------------------------------------
-- Iterator: scan
--------------------------------------------------------------
section("iter: scan")

check_eq("scan sum", {0, 1, 3, 6, 10},
  T.iter({1, 2, 3, 4}):scan(0, function(acc, v) return acc + v end):totable())

check_eq("scan concat", {"", "a", "ab", "abc"},
  T.iter({"a", "b", "c"}):scan("", function(acc, v) return acc .. v end):totable())

check_eq("scan empty", {0},
  T.iter({}):scan(0, function(acc, v) return acc + v end):totable())

check_eq("scan product", {1, 2, 6, 24},
  T.iter({2, 3, 4}):scan(1, function(acc, v) return acc * v end):totable())

-- scan after filter
check_eq("scan after filter", {0, 2, 6},
  T.iter({1, 2, 3, 4}):filter(function(v) return v % 2 == 0 end)
    :scan(0, function(acc, v) return acc + v end):totable())

--------------------------------------------------------------
-- Iterator: group_by
--------------------------------------------------------------
section("iter: group_by")

-- basic grouping
do
  local groups = T.iter({1, 2, 3, 4, 5, 6}):group_by(function(v)
    return v % 2 == 0 and "even" or "odd"
  end)
  check_eq("group_by even", {2, 4, 6}, groups["even"])
  check_eq("group_by odd", {1, 3, 5}, groups["odd"])
end

-- group_by with transforms
do
  local groups = T.iter({1, 2, 3, 4, 5, 6, 7, 8, 9, 10})
    :filter(function(v) return v > 3 end)
    :map(function(v) return v * 10 end)
    :group_by(function(v) return v >= 70 and "high" or "low" end)
  check_eq("group_by filtered high", {70, 80, 90, 100}, groups["high"])
  check_eq("group_by filtered low", {40, 50, 60}, groups["low"])
end

-- group_by string key
do
  local groups = T.iter({"apple", "banana", "avocado", "blueberry", "cherry"})
    :group_by(function(s) return s:sub(1, 1) end)
  check_eq("group_by first letter a", {"apple", "avocado"}, groups["a"])
  check_eq("group_by first letter b", {"banana", "blueberry"}, groups["b"])
  check_eq("group_by first letter c", {"cherry"}, groups["c"])
end

-- group_by single element groups
do
  local groups = T.iter({10, 20, 30}):group_by(function(v) return v end)
  check_eq("group_by singleton 10", {10}, groups[10])
  check_eq("group_by singleton 20", {20}, groups[20])
  check_eq("group_by singleton 30", {30}, groups[30])
end

--------------------------------------------------------------
-- Iterator: partition
--------------------------------------------------------------
section("iter: partition")

do
  local evens, odds = T.iter({1, 2, 3, 4, 5, 6}):partition(function(v) return v % 2 == 0 end)
  check_eq("partition evens", {2, 4, 6}, evens)
  check_eq("partition odds", {1, 3, 5}, odds)
end

do
  local pos, neg = T.iter({-3, -2, -1, 0, 1, 2, 3}):partition(function(v) return v >= 0 end)
  check_eq("partition pos", {0, 1, 2, 3}, pos)
  check_eq("partition neg", {-3, -2, -1}, neg)
end

-- partition with filter
do
  local big, small = T.iter({1, 2, 3, 4, 5, 6, 7, 8, 9, 10})
    :filter(function(v) return v % 2 == 0 end)
    :partition(function(v) return v > 5 end)
  check_eq("partition big", {6, 8, 10}, big)
  check_eq("partition small", {2, 4}, small)
end

-- partition empty
do
  local a, b = T.iter({}):partition(function() return true end)
  check_eq("partition empty a", {}, a)
  check_eq("partition empty b", {}, b)
end

-- partition all match
do
  local a, b = T.iter({1, 2, 3}):partition(function() return true end)
  check_eq("partition all match", {1, 2, 3}, a)
  check_eq("partition none fail", {}, b)
end

-- partition none match
do
  local a, b = T.iter({1, 2, 3}):partition(function() return false end)
  check_eq("partition none match", {}, a)
  check_eq("partition all fail", {1, 2, 3}, b)
end

--------------------------------------------------------------
-- Iterator: map-like tables
--------------------------------------------------------------
section("iter: dict tables")
do
  local it = T.iter({a = 1, b = 2, c = 3}):map(function(k, v)
    if v % 2 ~= 0 then
      return k:upper(), v * 2
    end
  end)
  local q = it:fold({}, function(q, k, v)
    q[k] = v
    return q
  end)
  check("dict fold A", q.A == 2)
  check("dict fold C", q.C == 6)
  check("dict fold no B", q.B == nil)
end

--------------------------------------------------------------
-- Iterator: for loop protocol
--------------------------------------------------------------
section("iter: for loop")
do
  local q = {1, 2, 3, 4, 5}
  local acc = 0
  for v in T.iter(q):map(function(v) return v * 3 end) do
    acc = acc + v
  end
  check_eq("for loop sum", 45, acc)
end

--------------------------------------------------------------
-- Iterator: error on array-only methods with function iterators
--------------------------------------------------------------
section("iter: array-only errors")
do
  local function make_fn_iter()
    local i = 0
    return T.iter(function()
      i = i + 1
      if i <= 3 then return i end
    end)
  end
  check_error("rev on fn", "requires an array%-like table", function() make_fn_iter():rev() end)
  check_error("rskip on fn", "requires an array%-like table", function() make_fn_iter():rskip(1) end)
  check_error("pop on fn", "requires an array%-like table", function() make_fn_iter():pop() end)
  check_error("rpeek on fn", "requires an array%-like table", function() make_fn_iter():rpeek() end)
  check_error("slice on fn", "requires an array%-like table", function() make_fn_iter():slice(1, 2) end)
  check_error("flatten on fn", "requires an array%-like table", function() make_fn_iter():flatten() end)
end

--------------------------------------------------------------
-- Iterator: function iterator basics
--------------------------------------------------------------
section("iter: function iterator")
do
  local function gsplit(s, sep)
    local pos = 1
    return function()
      if pos > #s then return nil end
      local start, stop = s:find(sep, pos, true)
      if start then
        local part = s:sub(pos, start - 1)
        pos = stop + 1
        return part
      else
        local part = s:sub(pos)
        pos = #s + 1
        return part
      end
    end
  end

  -- filter on function iterator
  check_eq("fn filter", {"the", "fox"},
    T.iter(gsplit("the quick brown fox", " "))
      :filter(function(s) return #s <= 3 end):totable())

  -- skip on function iterator
  check_eq("fn skip 0", {"a", "b", "c", "d"}, T.iter(gsplit("a|b|c|d", "|")):skip(0):totable())
  check_eq("fn skip 1", {"b", "c", "d"}, T.iter(gsplit("a|b|c|d", "|")):skip(1):totable())
  check_eq("fn skip 2", {"c", "d"}, T.iter(gsplit("a|b|c|d", "|")):skip(2):totable())
  check_eq("fn skip 3", {"d"}, T.iter(gsplit("a|b|c|d", "|")):skip(3):totable())
  check_eq("fn skip 4", {}, T.iter(gsplit("a|b|c|d", "|")):skip(4):totable())

  -- skip with predicate on function iterator
  check_eq("fn skip pred", {"c", "d"},
    T.iter(gsplit("a|b|c|d", "|")):skip(function(s) return s < "c" end):totable())

  -- peek on function iterator
  do
    local it = T.iter(gsplit("a|b|c", "|"))
    check_eq("fn peek 1", "a", it:peek())
    check_eq("fn peek idem", "a", it:peek())
    check_eq("fn peek then next", "a", it:next())
    check_eq("fn next after peek", "b", it:next())
  end

  -- nth on function iterator
  check("fn nth 0", T.iter(gsplit("a|b|c|d", "|")):nth(0) == nil)
  check_eq("fn nth 1", "a", T.iter(gsplit("a|b|c|d", "|")):nth(1))
  check_eq("fn nth 2", "b", T.iter(gsplit("a|b|c|d", "|")):nth(2))
  check_eq("fn nth 4", "d", T.iter(gsplit("a|b|c|d", "|")):nth(4))
  check("fn nth 5", T.iter(gsplit("a|b|c|d", "|")):nth(5) == nil)

  -- take on function iterator
  do
    local it = T.iter(gsplit("a|b|c|d", "|"))
    check_eq("fn take 2", {"a", "b"}, it:take(2):totable())
    check_eq("fn take after consume", {}, it:take(2):totable())
  end

  -- any/all on function iterator
  check("fn any true", T.iter(gsplit("a|b|c|d", "|")):any(function(s) return s == "d" end))
  check("fn any false", not T.iter(gsplit("a|b|c|d", "|")):any(function(s) return s == "e" end))
  check("fn all true", T.iter(gsplit("a|a|a|a", "|")):all(function(s) return s == "a" end))
  check("fn all false", not T.iter(gsplit("a|a|a|b", "|")):all(function(s) return s == "a" end))

  -- last on function iterator
  do
    local s = "abcdefghijklmnopqrstuvwxyz"
    check_eq("fn last via iter", "z", T.iter(s:gmatch(".")):last())
  end

  -- join on function iterator
  check_eq("fn join", "a|b|c|d", T.iter(gsplit("a|b|c|d", "|")):join("|"))
end

--------------------------------------------------------------
-- Summary
--------------------------------------------------------------
io.write(string.format("\n=== RESULTS: %d passed, %d failed ===\n", pass_count, fail_count))
if fail_count > 0 then
  os.exit(1)
else
  io.write("ALL TESTS PASSED\n")
  os.exit(0)
end
