#!/bin/bash

# Deploy the complete treemap implementation
cp /solution/treemap_solution.lua /app/treemap.lua

# Verify correctness through computation
lua5.4 -e '
package.path = "/app/?.lua;" .. package.path
local t = require("treemap")

-- Build a sorted map
local m = t.new()
for i = 1, 500 do m = t.assoc(m, i, i * 10) end
assert(t.count(m) == 500, "insert count failed")

-- Verify all lookups
for i = 1, 500 do
    assert(t.get(m, i) == i * 10, "get failed at " .. i)
end

-- Save reference for persistence check
local m_original = m

-- Delete odd keys
for i = 1, 499, 2 do
    m = t.dissoc(m, i)
end
assert(t.count(m) == 250, "dissoc count failed: " .. t.count(m))

-- Verify remaining keys
for i = 2, 500, 2 do
    assert(t.get(m, i) == i * 10, "even key " .. i .. " missing")
end
for i = 1, 499, 2 do
    assert(t.get(m, i) == nil, "odd key " .. i .. " should be gone")
end

-- Verify persistence: original unchanged
assert(t.count(m_original) == 500, "persistence failed")
for i = 1, 500 do
    assert(t.get(m_original, i) == i * 10, "original corrupted at " .. i)
end

-- Verify sorted iteration
local prev = nil
for k, v in t.pairs(m) do
    if prev then assert(k > prev, "sort order broken") end
    prev = k
end

-- Verify no-op dissoc returns same object
local m2 = t.dissoc(m, 9999)
assert(m == m2, "no-op dissoc must return identical object")

-- Verify red-black invariants
local function check_rb(node, depth)
    if not node then return 0 end
    local color = node[1]
    assert(color == 0 or color == 1, "invalid color at depth " .. depth)
    if color == 0 then
        assert(not node[2] or node[2][1] ~= 0, "red-red left at depth " .. depth)
        assert(not node[5] or node[5][1] ~= 0, "red-red right at depth " .. depth)
    end
    local lb = check_rb(node[2], depth + 1)
    local rb = check_rb(node[5], depth + 1)
    assert(lb == rb, "black depth mismatch at depth " .. depth)
    return lb + (color == 1 and 1 or 0)
end
if m.root then
    assert(m.root[1] == 1, "root must be black")
    check_rb(m.root, 0)
end

print("Solution verified: all checks passed")
'
