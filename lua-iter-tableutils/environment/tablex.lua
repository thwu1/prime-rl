-- tablex.lua — Table utilities and lazy iterator library

local M = {}

------------------------------------------------------------
-- Sentinel: distinguishes an intentionally-empty dict from {}
------------------------------------------------------------
local EMPTY_DICT_MT = { __name = "EMPTY_DICT" }
M.EMPTY_DICT = setmetatable({}, EMPTY_DICT_MT)

function M.empty_dict()
  return setmetatable({}, EMPTY_DICT_MT)
end

local function is_empty_dict(v)
  return type(v) == "table" and getmetatable(v) == EMPTY_DICT_MT
end

------------------------------------------------------------
-- islist: true iff t is contiguous 1..n with no extra keys
------------------------------------------------------------
function M.islist(t)
  if type(t) ~= "table" then return false end
  if is_empty_dict(t) then return false end
  local n = 0
  for k, _ in next, t do
    if type(k) ~= "number" then return false end
    if k ~= math.floor(k) then return false end
    if k < 1 then return false end
    n = n + 1
  end
  for i = 1, n do
    if t[i] == nil then return false end
  end
  return true
end

------------------------------------------------------------
-- tbl_count
------------------------------------------------------------
function M.tbl_count(t)
  local count = 0
  for _ in pairs(t) do
    count = count + 1
  end
  return count
end

------------------------------------------------------------
-- deep_equal
------------------------------------------------------------
function M.deep_equal(a, b)
  if a == b then return true end
  if type(a) ~= type(b) then return false end
  if type(a) ~= "table" then return false end
  local ca, cb = 0, 0
  for _ in pairs(a) do ca = ca + 1 end
  for _ in pairs(b) do cb = cb + 1 end
  if ca ~= cb then return false end
  for k, v in pairs(a) do
    if not M.deep_equal(v, b[k]) then return false end
  end
  return true
end

------------------------------------------------------------
-- deepcopy
------------------------------------------------------------
function M.deepcopy(val)
  local function _copy(v, memo)
    if type(v) ~= "table" then
      return v
    end
    if memo[v] then
      return memo[v]
    end
    local copy = {}
    memo[copy] = copy

    for k, val_inner in pairs(v) do
      copy[k] = _copy(val_inner, memo)
    end

    local mt = getmetatable(v)
    if mt then
      setmetatable(copy, mt)
    end

    return copy
  end

  return _copy(val, {})
end

------------------------------------------------------------
-- tbl_keys / tbl_values
------------------------------------------------------------
function M.tbl_keys(t)
  local keys = {}
  for k in pairs(t) do keys[#keys + 1] = k end
  return keys
end

function M.tbl_values(t)
  local vals = {}
  for _, v in pairs(t) do vals[#vals + 1] = v end
  return vals
end

------------------------------------------------------------
-- tbl_map / tbl_filter
------------------------------------------------------------
function M.tbl_map(f, t)
  local result = {}
  for k, v in pairs(t) do
    result[k] = f(v)
  end
  return result
end

function M.tbl_filter(f, t)
  local result = {}
  for _, v in pairs(t) do
    if f(v) then
      result[#result + 1] = v
    end
  end
  return result
end

------------------------------------------------------------
-- tbl_contains
------------------------------------------------------------
function M.tbl_contains(t, val, opts)
  local predicate = opts and opts.predicate
  for _, v in pairs(t) do
    if predicate then
      if val(v) then return true end
    else
      if v == val then return true end
    end
  end
  return false
end

------------------------------------------------------------
-- tbl_deep_extend
------------------------------------------------------------
function M.tbl_deep_extend(behavior, ...)
  if behavior == nil and select("#", ...) == 0 then
    error('invalid "behavior": nil')
  end
  if type(behavior) ~= "string" and type(behavior) ~= "function" then
    error('invalid "behavior": ' .. tostring(behavior))
  end

  local nargs = select("#", ...) + 1
  if nargs < 2 then
    error(string.format("wrong number of arguments (given %d, expected at least 3)", nargs))
  end
  if nargs < 3 then
    error(string.format("wrong number of arguments (given %d, expected at least 3)", nargs))
  end

  local tables = { ... }
  for i = 1, #tables do
    if type(tables[i]) ~= "table" then
      error(string.format("after the second argument: expected table, got %s", type(tables[i])))
    end
  end

  local function resolve(k, prev, new)
    if type(behavior) == "function" then
      return behavior(new, prev, k)
    elseif behavior == "keep" then
      return new
    else -- "force"
      return prev
    end
  end

  local function do_merge(base, overlay)
    for k, new_v in pairs(overlay) do
      local base_v = base[k]
      if base_v == nil then
        if type(new_v) == "table" then
          base[k] = M.deepcopy(new_v)
        else
          base[k] = new_v
        end
      elseif type(base_v) == "table" and type(new_v) == "table"
             and not M.islist(base_v) and not M.islist(new_v) then
        do_merge(base_v, new_v)
      else
        local winner = resolve(k, base_v, new_v)
        if type(winner) == "table" then
          base[k] = M.deepcopy(winner)
        else
          base[k] = winner
        end
      end
    end
  end

  local result = M.deepcopy(tables[1])

  for i = 2, #tables do
    do_merge(result, tables[i])
  end

  return result
end

------------------------------------------------------------
-- tbl_deep_diff
------------------------------------------------------------
function M.tbl_deep_diff(a, b)
  local diff = { added = {}, removed = {}, changed = {} }

  for k, v_a in pairs(a) do
    local v_b = b[k]
    if v_b == nil then
      diff.removed[k] = v_a
    elseif type(v_a) == "table" and type(v_b) == "table" then
      local sub = M.tbl_deep_diff(v_a, v_b)
      diff.changed[k] = sub
    elseif v_a ~= v_b then
      diff.changed[k] = { old = v_a, new = v_b }
    end
  end

  for k, v in pairs(a) do
    if a[k] == nil then
      diff.added[k] = v
    end
  end

  return diff
end

------------------------------------------------------------
-- Iterator
------------------------------------------------------------
local Iter = {}
Iter.__index = Iter

function Iter.new(src)
  local self = setmetatable({}, Iter)
  if type(src) == "function" then
    self._fn = src
    self._is_array = false
    self._peeked = nil
    self._has_peeked = false
  elseif type(src) == "table" then
    if M.islist(src) or #src > 0 then
      self._arr = {}
      for i = 1, #src do
        self._arr[i] = src[i]
      end
      self._head = 1
      self._tail = #self._arr
      self._is_array = true
    else
      local pairs_list = {}
      for k, v in pairs(src) do
        pairs_list[#pairs_list + 1] = { k, v }
      end
      local idx = 0
      self._fn = function()
        idx = idx + 1
        if idx <= #pairs_list then
          return pairs_list[idx][1], pairs_list[idx][2]
        end
        return nil
      end
      self._is_array = false
      self._peeked = nil
      self._has_peeked = false
    end
  else
    error("Expected table or function, got " .. type(src))
  end
  self._transforms = {}
  return self
end

--- Apply accumulated transforms to a set of values.
local function apply_transforms(transforms, ...)
  local vals = table.pack(...)
  for _, tr in ipairs(transforms) do
    if tr.kind == "filter" then
      if not tr.fn(table.unpack(vals, 1, vals.n)) then
        return nil
      end
    elseif tr.kind == "map" then
      vals = table.pack(tr.fn(table.unpack(vals, 1, vals.n)))
      if vals.n == 0 then
        return nil
      end
    elseif tr.kind == "enumerate" then
      tr.counter = tr.counter + 1
      local new_vals = table.pack(tr.counter, table.unpack(vals, 1, vals.n))
      vals = new_vals
    end
  end
  return vals
end

--- Raw next value from source (no transforms).
function Iter:_raw_next()
  if self._is_array then
    if self._head > self._tail then
      return nil
    end
    local v = self._arr[self._head]
    self._head = self._head + 1
    return table.pack(v)
  else
    if self._has_peeked then
      self._has_peeked = false
      local p = self._peeked
      self._peeked = nil
      return p
    end
    local vals = table.pack(self._fn())
    if vals[1] == nil and vals.n <= 1 then
      return nil
    end
    return vals
  end
end

function Iter:__call()
  return self:next()
end

--- Get next transformed value.
function Iter:_next_transformed()
  while true do
    local raw = self:_raw_next()
    if raw == nil then return nil end
    local result = apply_transforms(self._transforms, table.unpack(raw, 1, raw.n))
    if result ~= nil then
      return result
    end
  end
end

--- Return the next value(s).
function Iter:next()
  local vals = self:_next_transformed()
  if vals == nil then return nil end
  return table.unpack(vals, 1, vals.n)
end

--- Peek at next value without consuming.
function Iter:peek()
  if self._is_array then
    if self._head > self._tail then return nil end
    return self._arr[self._head]
  else
    if self._has_peeked then
      return self._peeked[1]
    end
    local vals = self:_next_transformed()
    if vals == nil then return nil end
    self._peeked = vals
    self._has_peeked = true
    return vals[1]
  end
end

--- Filter: keep only items where f returns truthy.
function Iter:filter(f)
  self._transforms[#self._transforms + 1] = { kind = "filter", fn = f }
  return self
end

--- Map: transform each item.
function Iter:map(f)
  self._transforms[#self._transforms + 1] = { kind = "map", fn = f }
  return self
end

--- Enumerate: prepend a 1-based counter.
function Iter:enumerate()
  self._transforms[#self._transforms + 1] = { kind = "enumerate", counter = 1 }
  return self
end

--- Collect all remaining values into a list.
function Iter:totable()
  local result = {}
  while true do
    local vals = self:_next_transformed()
    if vals == nil then break end
    if vals.n == 1 then
      result[#result + 1] = vals[1]
    else
      result[#result + 1] = { table.unpack(vals, 1, vals.n) }
    end
  end
  return result
end

--- Join values with separator.
function Iter:join(sep)
  local parts = {}
  while true do
    local vals = self:_next_transformed()
    if vals == nil then break end
    parts[#parts + 1] = tostring(vals[1])
  end
  return table.concat(parts, sep)
end

--- Skip first n items, or skip while predicate is true.
function Iter:skip(n_or_pred)
  if type(n_or_pred) == "function" then
    while true do
      local vals = self:_next_transformed()
      if vals == nil then break end
      if not n_or_pred(table.unpack(vals, 1, vals.n)) then
        break
      end
    end
  else
    local n = n_or_pred
    if self._is_array and #self._transforms == 0 then
      self._head = math.min(self._head + n, self._tail + 1)
    else
      for _ = 1, n do
        if self:_next_transformed() == nil then break end
      end
    end
  end
  return self
end

--- Reverse (array-only).
function Iter:rev()
  if not self._is_array then
    error("rev() requires an array-like table")
  end
  local arr = self._arr
  local h, t = self._head, self._tail
  local len = t - h + 1
  for i = 0, math.floor(len / 2) do
    local a = h + i
    local b = t - i
    arr[a], arr[b] = arr[b], arr[a]
  end
  return self
end

--- Take first n items, or take while predicate is true.
function Iter:take(n_or_pred)
  if type(n_or_pred) == "function" then
    if self._is_array then
      local new_tail = self._head - 1
      for i = self._head, self._tail do
        if n_or_pred(self._arr[i]) then
          new_tail = i
        else
          break
        end
      end
      self._tail = new_tail
    else
      local collected = {}
      while true do
        local vals = self:_next_transformed()
        if vals == nil then break end
        if not n_or_pred(table.unpack(vals, 1, vals.n)) then
          break
        end
        collected[#collected + 1] = vals
      end
      local idx = 0
      self._fn = function()
        idx = idx + 1
        if idx <= #collected then
          return table.unpack(collected[idx], 1, collected[idx].n)
        end
        return nil
      end
      self._has_peeked = false
      self._peeked = nil
    end
  else
    local n = n_or_pred
    if self._is_array then
      self._tail = math.min(self._head + n - 1, self._tail)
    else
      local collected = {}
      for _ = 1, n do
        local vals = self:_next_transformed()
        if vals == nil then break end
        collected[#collected + 1] = vals
      end
      local idx = 0
      self._fn = function()
        idx = idx + 1
        if idx <= #collected then
          return table.unpack(collected[idx], 1, collected[idx].n)
        end
        return nil
      end
      self._has_peeked = false
      self._peeked = nil
    end
  end
  return self
end

--- rskip: skip n items from the end (array-only).
function Iter:rskip(n)
  if not self._is_array then
    error("rskip() requires an array-like table")
  end
  self._tail = math.max(self._head - 1, self._tail - n)
  return self
end

--- slice(from, to): keep only indices from..to (array-only, 1-based).
function Iter:slice(from, to)
  if not self._is_array then
    error("slice() requires an array-like table")
  end
  local new_head = math.max(self._head, self._head + from - 1)
  local new_tail = math.min(self._tail, self._head + to - 1)
  if new_head > new_tail then
    self._head = 1
    self._tail = 0
  else
    self._head = new_head
    self._tail = new_tail
  end
  return self
end

--- nth(n): get the n-th element (1-based). Negative n counts from end (array-only).
function Iter:nth(n)
  if n == 0 then return nil end
  if n < 0 then
    if not self._is_array then
      error("nth() requires an array-like table for negative indices")
    end
    local idx = self._tail + n + 1
    if idx < self._head or idx > self._tail then
      return nil
    end
    return self._arr[idx]
  end
  for _ = 1, n - 1 do
    if self:_next_transformed() == nil then return nil end
  end
  local vals = self:_next_transformed()
  if vals == nil then return nil end
  return table.unpack(vals, 1, vals.n)
end

--- pop: remove and return last element (array-only).
function Iter:pop()
  if not self._is_array then
    error("pop() requires an array-like table")
  end
  if self._head > self._tail then return nil end
  local v = self._arr[self._tail]
  self._tail = self._tail - 1
  return v
end

--- rpeek: peek at last element (array-only).
function Iter:rpeek()
  if not self._is_array then
    error("rpeek() requires an array-like table")
  end
  if self._head > self._tail then return nil end
  return self._arr[self._tail]
end

--- find: find first element matching val or predicate.
function Iter:find(val_or_pred)
  local pred
  if type(val_or_pred) == "function" then
    pred = val_or_pred
  else
    pred = function(v) return v == val_or_pred end
  end
  while true do
    local vals = self:_next_transformed()
    if vals == nil then return nil end
    if pred(table.unpack(vals, 1, vals.n)) then
      return table.unpack(vals, 1, vals.n)
    end
  end
end

--- rfind: find from end (array-only).
function Iter:rfind(val_or_pred)
  if not self._is_array then
    error("rfind() requires an array-like table")
  end
  local pred
  if type(val_or_pred) == "function" then
    pred = val_or_pred
  else
    pred = function(v) return v == val_or_pred end
  end
  while self._head <= self._tail do
    local v = self._arr[self._tail]
    self._tail = self._tail - 1
    local vals = apply_transforms(self._transforms, v)
    if vals ~= nil and pred(table.unpack(vals, 1, vals.n)) then
      return table.unpack(vals, 1, vals.n)
    end
  end
  return nil
end

--- any: true if any element satisfies f.
function Iter:any(f)
  while true do
    local vals = self:_next_transformed()
    if vals == nil then return false end
    if f(table.unpack(vals, 1, vals.n)) then
      return true
    end
  end
end

--- all: true if all elements satisfy f.
function Iter:all(f)
  while true do
    local vals = self:_next_transformed()
    if vals == nil then return true end
    if not f(table.unpack(vals, 1, vals.n)) then
      return false
    end
  end
end

--- last: consume iterator and return last value.
function Iter:last()
  local last_vals = nil
  while true do
    local vals = self:_next_transformed()
    if vals == nil then break end
    last_vals = vals
  end
  if last_vals == nil then return nil end
  return table.unpack(last_vals, 1, last_vals.n)
end

--- fold: reduce with accumulator.
function Iter:fold(init, f)
  local acc = init
  while true do
    local vals = self:_next_transformed()
    if vals == nil then break end
    f(acc, table.unpack(vals, 1, vals.n))
  end
  return acc
end

--- flatten: flatten nested tables to given depth (default 1). Array-only.
function Iter:flatten(depth)
  if not self._is_array then
    error("flatten() requires an array-like table")
  end
  depth = depth or 1
  if depth <= 0 then return self end

  local function do_flatten(arr, d)
    local result = {}
    for _, v in ipairs(arr) do
      if type(v) == "table" and d > 0 then
        if M.islist(v) or #v > 0 then
          local sub = do_flatten(v, d)
          for _, sv in ipairs(sub) do
            result[#result + 1] = sv
          end
        else
          result[#result + 1] = v
        end
      else
        result[#result + 1] = v
      end
    end
    return result
  end

  local new_arr = do_flatten(self._arr, depth)
  self._arr = new_arr
  self._head = 1
  self._tail = #new_arr
  return self
end

--- unique: remove duplicates, optionally by key function.
function Iter:unique(key_fn)
  local seen = {}
  local old_transforms = self._transforms
  self._transforms = {}
  for _, t in ipairs(old_transforms) do
    self._transforms[#self._transforms + 1] = t
  end
  self._transforms[#self._transforms + 1] = {
    kind = "filter",
    fn = function(...)
      local key
      if key_fn then
        key = key_fn(...)
      else
        key = select(1, ...)
      end
      if seen[key] then
        return false
      end
      seen[key] = true
      return true
    end,
  }
  return self
end

--- chain: concatenate with another iterator.
function Iter:chain(other)
  if type(other) ~= "table" or getmetatable(other) ~= Iter then
    other = Iter.new(other)
  end
  local collected = {}
  while true do
    local vals = self:_next_transformed()
    if vals == nil then break end
    collected[#collected + 1] = vals
  end
  local idx = 1
  local switched = false
  self._fn = function()
    if not switched then
      idx = idx + 1
      if idx <= #collected then
        return table.unpack(collected[idx], 1, collected[idx].n)
      end
      switched = true
    end
    return other:next()
  end
  self._is_array = false
  self._transforms = {}
  self._has_peeked = false
  self._peeked = nil
  return self
end

--- zip: pair elements from two iterators.
function Iter:zip(other)
  if type(other) ~= "table" or getmetatable(other) ~= Iter then
    other = Iter.new(other)
  end
  local collected = {}
  while true do
    local vals = self:_next_transformed()
    if vals == nil then break end
    collected[#collected + 1] = vals
  end
  local idx = 0
  self._fn = function()
    idx = idx + 1
    if idx > #collected then return nil end
    local other_val = other:next()
    return collected[idx][1], other_val
  end
  self._is_array = false
  self._transforms = {}
  self._has_peeked = false
  self._peeked = nil
  return self
end

--- scan: like fold but yields each intermediate accumulator value.
function Iter:scan(init, f)
  local collected = { table.pack(init) }
  local acc = init
  while true do
    local vals = self:_next_transformed()
    if vals == nil then break end
    f(acc, table.unpack(vals, 1, vals.n))
    collected[#collected + 1] = table.pack(acc)
  end
  local idx = 0
  self._fn = function()
    idx = idx + 1
    if idx <= #collected then
      return table.unpack(collected[idx], 1, collected[idx].n)
    end
    return nil
  end
  self._is_array = false
  self._transforms = {}
  self._has_peeked = false
  self._peeked = nil
  return self
end

--- group_by: group elements by key function result.
function Iter:group_by(key_fn)
  local groups = {}
  while true do
    local vals = self:_raw_next()
    if vals == nil then break end
    local key = key_fn(table.unpack(vals, 1, vals.n))
    if not groups[key] then
      groups[key] = {}
    end
    groups[key][#groups[key] + 1] = key
  end
  return groups
end

--- partition: split into matching and non-matching.
function Iter:partition(pred)
  local pass_t = {}
  local fail_t = {}
  while true do
    local vals = self:_next_transformed()
    if vals == nil then break end
    if pred(table.unpack(vals, 1, vals.n)) then
      fail_t[#fail_t + 1] = vals[1]
    else
      pass_t[#pass_t + 1] = vals[1]
    end
  end
  return pass_t, fail_t
end

-- Export iterator constructor
function M.iter(src)
  return Iter.new(src)
end

return M
